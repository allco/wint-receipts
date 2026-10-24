"""Receipts already in Wint: a table with server-side filters and sorting, and a preview of the attachment."""
from __future__ import annotations

import io
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, QSortFilterProxyModel, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QDoubleValidator, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QProgressBar,
    QPushButton, QSizePolicy, QSplitter, QStackedWidget, QTableView, QToolBar, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from ..core import browse, pdf
from ..core.models import PageStatus, ReferenceData
from ..core.wint import WintClient
from . import empty_states as es
from . import icons as app_icons
from . import theme
from .image_view import ImagePane
from .workers import Job

COLUMNS = [  # (title, sort key for the server or None, alignment)
    ("Nr", "serial", Qt.AlignmentFlag.AlignRight),
    ("Date", "date", Qt.AlignmentFlag.AlignLeft),
    ("Amount", "amount", Qt.AlignmentFlag.AlignRight),
    ("Cur", None, Qt.AlignmentFlag.AlignLeft),
    ("Category", "category", Qt.AlignmentFlag.AlignLeft),
    ("Payment method", None, Qt.AlignmentFlag.AlignLeft),
    ("State", "state", Qt.AlignmentFlag.AlignLeft),
    ("Paid", None, Qt.AlignmentFlag.AlignLeft),
    ("Files", None, Qt.AlignmentFlag.AlignRight),
]
STATE_FILTERS = [("All states", []), ("Booked", [1]), ("Received", [0]), ("Waiting acceptance", [3]),
                 ("Sent back", [5, 6]), ("Canceled", [2])]
STATE_COLORS = {1: theme.STATUS[PageStatus.UPLOADED], 0: theme.STATUS[PageStatus.NEW],
                2: theme.STATUS[PageStatus.FAILED], 5: theme.STATUS[PageStatus.NEEDS_REVIEW],
                6: theme.STATUS[PageStatus.NEEDS_REVIEW], 3: theme.STATUS[PageStatus.UPLOADING]}
ANY_DATE = QDate(2000, 1, 1)
PREVIEW_DPI = 150
PREVIEW_MAX_SIDE = 2400


class ReceiptModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[browse.Row] = []

    def set_rows(self, rows: list[browse.Row]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def append(self, rows: list[browse.Row]) -> None:
        known = {r.id for r in self.rows}
        rows = [r for r in rows if r.id not in known]
        if rows:
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(rows) - 1)
            self.rows.extend(rows)
            self.endInsertRows()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return COLUMNS[section][0]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return COLUMNS[section][2] | Qt.AlignmentFlag.AlignVCenter
            if role == Qt.ItemDataRole.ToolTipRole:
                return "Click to sort" if COLUMNS[section][1] else "Wint can't sort by this column"
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [str(r.serial or ""), r.date, f"{r.amount:,.2f}".replace(",", " "), r.currency, r.category,
                    r.payment_method, r.state_name, "Yes" if r.paid else "No",
                    str(len(r.attachments)) if r.attachments else ""][col]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return COLUMNS[col][2] | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.DecorationRole and col == 6 and r.state is not None:
            return es.status_dot(STATE_COLORS.get(r.state, theme.STATUS[PageStatus.SKIPPED]), 10)
        if role == Qt.ItemDataRole.FontRole and col == 2:
            f = QFont()
            f.setBold(True)
            return f
        if role == Qt.ItemDataRole.UserRole:
            return r
        return None


class SearchProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""

    def set_text(self, text: str) -> None:
        self.beginFilterChange()
        self.text = text.strip()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, row, parent):  # noqa: N802 - Qt API
        return not self.text or self.sourceModel().rows[row].matches(self.text)


class BusyIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(self.fontMetrics().averageCharWidth() * 12)
        self.bar.setMaximumHeight(self.fontMetrics().height() // 2 + 2)
        self.label = QLabel()
        lay.addWidget(self.bar)
        lay.addWidget(self.label)
        self.hide()

    def show_text(self, text: str | None) -> None:
        if text:
            self.label.setText(text)
        self.setVisible(bool(text))


class BrowserWindow(QMainWindow):
    """A window of its own, so it can stay open next to the main one."""

    def __init__(self, client_factory: Callable[[], WintClient | None], reference: ReferenceData | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Receipts in Wint")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._client_factory = client_factory
        self.reference = reference
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self._jobs: set[Job] = set()
        self._generation = 0  # bumps on every new query, so late pages of an old one are dropped
        self._next_page = 0
        self._total = 0
        self._loading = False
        self._fetched_at: float | None = None
        self.query = browse.Query()
        self._preview_for: int | None = None
        self._preview_pages: list[tuple[Path, int | None]] = []  # (file, PDF page index or None for an image)

        tb = QToolBar("Browser")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.refresh_act = QAction(app_icons.icon("reload"), "Refresh", self)
        self.refresh_act.setShortcut("F5")
        self.refresh_act.setToolTip("Load again from Wint, skipping the cache (F5)")
        self.refresh_act.triggered.connect(lambda: self.reload(use_cache=False))
        tb.addAction(self.refresh_act)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search loaded receipts…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(self.fontMetrics().averageCharWidth() * 40)
        tb.addWidget(self.search)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        self.cached_label = QLabel()
        tb.addWidget(self.cached_label)

        self.date_from = self._date_edit()
        self.date_to = self._date_edit()
        self.state = QComboBox()
        for name, _ in STATE_FILTERS:
            self.state.addItem(name)
        self.category = QComboBox()
        self.category.addItem("All categories", None)
        for c in (reference.categories if reference else []):
            self.category.addItem(c.name, c.id)
        self.payment = QComboBox()
        for name, value in (("Paid and unpaid", None), ("Paid", True), ("Unpaid", False)):
            self.payment.addItem(name, value)
        self.amount_from = self._amount_edit("from")
        self.amount_to = self._amount_edit("to")
        self.clear_btn = QPushButton("Clear filters")
        self.clear_btn.setFlat(True)
        self.clear_btn.setObjectName("link")
        self.clear_btn.clicked.connect(self.clear_filters)
        filters = QWidget()
        fl = QHBoxLayout(filters)
        fl.setContentsMargins(10, 6, 10, 6)
        for label, widgets in (("Date", [self.date_from, QLabel("–"), self.date_to]), ("State", [self.state]),
                               ("Category", [self.category]), ("Payment", [self.payment]),
                               ("Amount", [self.amount_from, QLabel("–"), self.amount_to])):
            fl.addWidget(QLabel(label))
            for w in widgets:
                fl.addWidget(w)
            fl.addSpacing(12)
        fl.addWidget(self.clear_btn)
        fl.addStretch(1)

        self.model = ReceiptModel(self)
        self.proxy = SearchProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.setStyleSheet("QTableView::item { padding: 0 8px; } QHeaderView::section { padding: 2px 8px; }")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._header_clicked)
        self._show_sort_indicator()
        self.table.selectionModel().currentRowChanged.connect(lambda cur, _prev: self._select(cur))
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._update_count())
        self.table.verticalScrollBar().valueChanged.connect(self._maybe_load_more)
        self.table_message = QLabel()
        self.table_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table_message.setWordWrap(True)
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        self.table_stack.addWidget(self.table_message)

        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details.setContentsMargins(12, 10, 12, 6)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.attachment_pick = QComboBox()
        self.attachment_pick.currentIndexChanged.connect(self._show_preview_page)
        self.image = ImagePane()
        for a in (self.image.rotate_left, self.image.rotate_right):
            a.setVisible(False)
        loading = QWidget()
        ll = QVBoxLayout(loading)
        ll.addStretch(1)
        bar = QProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedWidth(self.fontMetrics().averageCharWidth() * 24)
        bar.setMaximumHeight(self.fontMetrics().height() // 2 + 2)
        ll.addWidget(bar, 0, Qt.AlignmentFlag.AlignHCenter)
        ll.addWidget(QLabel("Loading attachment…"), 0, Qt.AlignmentFlag.AlignHCenter)
        ll.addStretch(1)
        self.preview_message = QLabel()
        self.preview_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_message.setWordWrap(True)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.image)
        self.preview_stack.addWidget(loading)
        self.preview_stack.addWidget(self.preview_message)
        preview = QWidget()
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        pl.addWidget(self.details)
        pick_row = QHBoxLayout()
        pick_row.setContentsMargins(12, 0, 12, 6)
        pick_row.addWidget(self.attachment_pick)
        pick_row.addStretch(1)
        pl.addLayout(pick_row)
        pl.addWidget(self.preview_stack, 1)

        split = QSplitter()
        split.addWidget(self.table_stack)
        split.addWidget(preview)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(filters)
        cl.addWidget(split, 1)
        self.setCentralWidget(central)

        self.count_label = QLabel()
        self.statusBar().addWidget(self.count_label)
        self.totals_label = QLabel()
        self.statusBar().addWidget(self.totals_label)
        self.summary: browse.Summary | None = None
        self.busy = BusyIndicator()
        self.statusBar().addPermanentWidget(self.busy)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self.reload)
        for w in (self.state, self.category, self.payment):
            w.currentIndexChanged.connect(self._filters_changed)
        for w in (self.date_from, self.date_to):
            w.dateChanged.connect(self._filters_changed)
        for w in (self.amount_from, self.amount_to):
            w.textChanged.connect(self._filters_changed)
        self.search.textChanged.connect(self._search_changed)
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._update_cached_label)
        self._clock.start(30_000)

        self._select(QModelIndex())
        self.resize(1440, 900)
        self.reload()

    # ---- filters

    def _date_edit(self) -> QDateEdit:
        d = QDateEdit()
        d.setCalendarPopup(True)
        d.setDisplayFormat("yyyy-MM-dd")
        d.setMinimumDate(ANY_DATE)
        d.setSpecialValueText("any")  # shown at the minimum date
        d.setDate(ANY_DATE)
        return d

    def _amount_edit(self, placeholder: str) -> QLineEdit:
        e = QLineEdit()
        e.setPlaceholderText(placeholder)
        v = QDoubleValidator(0, 1e9, 2, e)
        v.setNotation(QDoubleValidator.Notation.StandardNotation)
        e.setValidator(v)
        e.setMaximumWidth(self.fontMetrics().averageCharWidth() * 10)
        return e

    @staticmethod
    def _date(edit: QDateEdit) -> date | None:
        d = edit.date()
        return None if d == ANY_DATE else date(d.year(), d.month(), d.day())

    @staticmethod
    def _amount(edit: QLineEdit) -> float | None:
        try:
            return float(edit.text().replace(",", ".").replace(" ", ""))
        except ValueError:
            return None

    def _query_from_filters(self) -> browse.Query:
        return browse.Query(
            date_from=self._date(self.date_from), date_to=self._date(self.date_to),
            states=STATE_FILTERS[self.state.currentIndex()][1], category_id=self.category.currentData(),
            paid=self.payment.currentData(), amount_from=self._amount(self.amount_from),
            amount_to=self._amount(self.amount_to), sort=self.query.sort, descending=self.query.descending)

    def _filters_changed(self, *_):
        self._debounce.start()

    def clear_filters(self) -> None:
        widgets = (self.date_from, self.date_to, self.state, self.category, self.payment, self.amount_from,
                   self.amount_to)
        for w in widgets:
            w.blockSignals(True)
        self.date_from.setDate(ANY_DATE)
        self.date_to.setDate(ANY_DATE)
        for c in (self.state, self.category, self.payment):
            c.setCurrentIndex(0)
        self.amount_from.clear()
        self.amount_to.clear()
        for w in widgets:
            w.blockSignals(False)
        self.search.clear()
        self.reload()

    def _search_changed(self, text: str) -> None:
        self.proxy.set_text(text)
        self._update_count()

    # ---- sorting

    def _header_clicked(self, section: int) -> None:
        key = COLUMNS[section][1]
        if key is None:
            self._show_sort_indicator()
            return
        if key == self.query.sort:
            self.query = self.query.model_copy(update={"descending": not self.query.descending})
        else:
            self.query = self.query.model_copy(update={"sort": key, "descending": key in ("date", "amount", "serial")})
        self._show_sort_indicator()
        self.reload()

    def _show_sort_indicator(self) -> None:
        section = next(i for i, c in enumerate(COLUMNS) if c[1] == self.query.sort)
        order = Qt.SortOrder.DescendingOrder if self.query.descending else Qt.SortOrder.AscendingOrder
        header = self.table.horizontalHeader()
        header.blockSignals(True)
        header.setSortIndicator(section, order)
        header.blockSignals(False)

    # ---- loading

    def _run(self, job: Job, on_done, on_failed) -> None:
        self._jobs.add(job)

        def deliver(handler, tag, value):
            self._jobs.discard(job)
            if isValid(self):
                handler(tag, value)

        job.signals.done.connect(lambda tag, res: deliver(on_done, tag, res))
        job.signals.failed.connect(lambda tag, msg: deliver(on_failed, tag, msg))
        self.pool.start(job)

    def reload(self, use_cache: bool = True) -> None:
        self._debounce.stop()
        self.query = self._query_from_filters()
        self._generation += 1
        self._next_page = 0
        self._total = 0
        self._loading = False
        self.model.set_rows([])
        self.summary = None
        self._select(QModelIndex())
        self._load_page(use_cache)
        self._load_summary(use_cache)

    def _load_page(self, use_cache: bool = True) -> None:
        client = self._client_factory()
        if client is None:
            self._show_table_message("Add your Wint user name and API key in Settings → Wint API to see receipts.")
            return
        self._loading = True
        first = self._next_page == 0
        self.busy.show_text("Loading receipts…" if first else "Loading more…")
        if first:
            self._show_table_message("Loading receipts from Wint…")
        query, page, gen = self.query, self._next_page, self._generation

        def work():
            try:
                return browse.fetch_page(client, query, page, use_cache=use_cache)
            finally:
                client.close()

        self._run(Job(gen, work), self._page_loaded, self._page_failed)

    def _load_summary(self, use_cache: bool = True) -> None:
        client = self._client_factory()
        if client is None:
            return
        query, gen = self.query, self._generation

        def work():
            try:
                return browse.fetch_summary(client, query, use_cache=use_cache)
            finally:
                client.close()

        self._run(Job(gen, work), self._summary_loaded, lambda *_: None)

    def _summary_loaded(self, gen: int, summary: browse.Summary) -> None:
        if gen == self._generation:
            self.summary = summary
            self._update_count()

    def _page_loaded(self, gen: int, result: browse.Page) -> None:
        if gen != self._generation:
            return
        self._loading = False
        self.busy.show_text(None)
        self._total = result.total
        self._next_page += 1
        self.model.append(result.rows)
        self._fetched_at = result.fetched_at if self._fetched_at is None or self._next_page == 1 else \
            min(self._fetched_at, result.fetched_at)
        self._update_cached_label()
        if not self.model.rows:
            self._show_table_message("No receipts match these filters.")
        else:
            self.table_stack.setCurrentWidget(self.table)
            if self.table.currentIndex().row() < 0:
                self.table.selectRow(0)
        self._update_count()
        QTimer.singleShot(0, self._maybe_load_more)  # a tall window may not have a scroll bar yet

    def _page_failed(self, gen: int, msg: str) -> None:
        if gen != self._generation:
            return
        self._loading = False
        self.busy.show_text(None)
        if not self.model.rows:
            self._show_table_message(f"Couldn't load receipts from Wint.\n\n{msg}")
        self.statusBar().showMessage(f"Loading failed: {msg}", 10000)

    def _maybe_load_more(self, *_):
        if self._loading or len(self.model.rows) >= self._total or self._next_page == 0:
            return
        bar = self.table.verticalScrollBar()
        if bar.maximum() == 0 or bar.value() >= bar.maximum() - 5:
            self._load_page()

    def _show_table_message(self, text: str) -> None:
        self.table_message.setText(text)
        self.table_stack.setCurrentWidget(self.table_message)

    def _update_count(self) -> None:
        shown, loaded = self.proxy.rowCount(), len(self.model.rows)
        text = f"Showing {loaded:,} of {self._total:,} receipts".replace(",", " ")
        if self.proxy.text:
            text = f"{shown:,} match the search · {text[0].lower()}{text[1:]}".replace(",", " ")
        self.count_label.setText(text if self._total else "")
        selected = [self.proxy.index(i.row(), 0).data(Qt.ItemDataRole.UserRole)
                    for i in self.table.selectionModel().selectedRows()]
        if len(selected) > 1:
            totals = browse.sum_by_currency((r.currency, r.amount) for r in selected)
            self.totals_label.setText(f"   |   {len(selected)} selected: {browse.format_totals(totals)}")
        elif self.proxy.text:
            rows = [self.proxy.index(i, 0).data(Qt.ItemDataRole.UserRole) for i in range(shown)]
            totals = browse.sum_by_currency((r.currency, r.amount) for r in rows)
            self.totals_label.setText(f"   |   {shown} found: {browse.format_totals(totals)}" if rows else "")
        elif self.summary is not None:
            self.totals_label.setText(f"   |   {self.summary.count:,} receipts: ".replace(",", " ")
                                      + (browse.format_totals(self.summary.totals) or "0.00"))
        else:
            self.totals_label.setText("")

    def _update_cached_label(self) -> None:
        if self._fetched_at is None:
            self.cached_label.setText("")
            return
        minutes = int((time.time() - self._fetched_at) // 60)
        self.cached_label.setText("Fresh from Wint" if minutes < 1 else f"Cached {minutes} min ago")

    # ---- preview

    def _select(self, index: QModelIndex) -> None:
        row: browse.Row | None = index.data(Qt.ItemDataRole.UserRole) if index.isValid() else None
        self._preview_for = row.id if row else None
        self._preview_pages = []
        self.attachment_pick.blockSignals(True)
        self.attachment_pick.clear()
        self.attachment_pick.blockSignals(False)
        self.attachment_pick.hide()
        if row is None:
            self.details.setText("<span style='color:gray'>Select a receipt to see it here.</span>")
            self.preview_message.setText("")
            self.preview_stack.setCurrentWidget(self.preview_message)
            return
        self.details.setText(self._details_html(row))
        if not row.attachments:
            self.preview_message.setText("This receipt has no attachment.")
            self.preview_stack.setCurrentWidget(self.preview_message)
            return
        client = self._client_factory()
        if client is None:
            return
        self.preview_stack.setCurrentWidget(self.preview_stack.widget(1))
        rid, attachments = row.id, list(row.attachments)

        def work():
            try:
                pages: list[tuple[Path, int | None]] = []
                for aid, _kind in attachments:
                    path = browse.fetch_attachment(client, rid, aid)
                    if path.suffix == ".pdf":
                        pages += [(path, i) for i in range(pdf.page_count(path))]
                    else:
                        pages.append((path, None))
                first = _render(*pages[0]) if pages else None
                return pages, first
            finally:
                client.close()

        self._run(Job(rid, work), self._attachments_loaded, self._attachments_failed)

    def _attachments_loaded(self, rid: int, result) -> None:
        if rid != self._preview_for:
            return
        pages, first = result
        self._preview_pages = pages
        self.attachment_pick.blockSignals(True)
        self.attachment_pick.clear()
        for n, _ in enumerate(pages):
            self.attachment_pick.addItem(f"Page {n + 1} of {len(pages)}")
        self.attachment_pick.blockSignals(False)
        self.attachment_pick.setVisible(len(pages) > 1)
        self.image.view.set_png(first)
        self.preview_stack.setCurrentWidget(self.image)

    def _attachments_failed(self, rid: int, msg: str) -> None:
        if rid != self._preview_for:
            return
        self.preview_message.setText(f"Couldn't load the attachment.\n\n{msg}")
        self.preview_stack.setCurrentWidget(self.preview_message)

    def _show_preview_page(self, n: int) -> None:
        if not 0 <= n < len(self._preview_pages):
            return
        rid = self._preview_for
        page = self._preview_pages[n]
        self.preview_stack.setCurrentWidget(self.preview_stack.widget(1))
        self._run(Job(rid, lambda: _render(*page)), self._page_rendered, self._attachments_failed)

    def _page_rendered(self, rid: int, png: bytes) -> None:
        if rid == self._preview_for:
            self.image.view.set_png(png)
            self.preview_stack.setCurrentWidget(self.image)

    def _details_html(self, r: browse.Row) -> str:
        def esc(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        amount = f"{r.amount:,.2f}".replace(",", " ")
        title = f"Receipt #{r.serial} · <b>{amount} {esc(r.currency)}</b>" + (f" · {esc(r.category)}" if r.category else "")
        lines = [("Date", r.date), ("State", f"{r.state_name} · {'paid' if r.paid else 'unpaid'}"),
                 ("Payment", r.payment_method), ("Supplier", r.supplier), ("Created by", r.created_by),
                 ("Participants", ", ".join(r.persons)), ("Reason", r.intent), ("Comment", r.comment),
                 ("Wint id", str(r.id))]
        body = "".join(f"<tr><td style='color:gray;padding-right:12px'>{k}</td><td>{esc(v)}</td></tr>"
                       for k, v in lines if v)
        return f"<div style='font-size:large'>{title}</div><table style='margin-top:6px'>{body}</table>"

    def closeEvent(self, event):  # noqa: N802 - Qt API
        self._generation += 1
        self.pool.clear()
        self.pool.waitForDone(3000)
        event.accept()


def _render(path: Path, page: int | None) -> bytes:
    if page is not None:
        return pdf.render_png(path, page, PREVIEW_DPI, max_side=PREVIEW_MAX_SIDE)
    from PIL import Image

    with Image.open(path) as im:
        im.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG", compress_level=1)
        return buf.getvalue()
