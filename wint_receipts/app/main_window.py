"""Main window: page list | page image | receipt form."""
from __future__ import annotations

import json
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, QThreadPool, QTimer, Qt
from shiboken6 import isValid
from PySide6.QtGui import QAction, QBrush, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFrame, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QStackedWidget, QToolBar, QVBoxLayout,
)

from ..core import checks, config, pdf, reclog, recognize, upload
from ..core.learnings import Learnings
from ..core.config import Settings
from ..core.models import PageKind, PageState, PageStatus, ReceiptDraft, ReferenceData, Session
from ..core.session import open_session, save_session
from ..core.wint import WintClient, receipt_post_body
from . import empty_states as es
from . import icons as app_icons
from . import theme
from .address_book import AddressBookDialog
from .image_view import ImagePane
from .receipt_form import ReceiptForm, format_amount
from .settings_dialog import SettingsDialog
from .workers import Job

STATUS_COLORS = theme.STATUS
STATUS_LABELS = {
    PageStatus.NEW: "waiting", PageStatus.RECOGNIZING: "AI reading", PageStatus.NEEDS_REVIEW: "needs review",
    PageStatus.APPROVED: "approved", PageStatus.SKIPPED: "skipped", PageStatus.UPLOADING: "uploading",
    PageStatus.UPLOADED: "uploaded", PageStatus.FAILED: "failed",
}
REFERENCE_CACHE = "reference.json"
DISPLAY_DPI = 150
DISPLAY_MAX_SIDE = 2400  # px; big scans would otherwise take seconds to render
RECOGNITION_MAX_SIDE = 2000  # px; Claude scales larger images down anyway


def _log_quietly(path: Path | None, entry: dict) -> None:
    """A recognition log write that fails must not turn a good recognition into a failed one."""
    try:
        reclog.write(path, entry)
    except OSError:
        traceback.print_exc()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.session: Session | None = None
        self.reference: ReferenceData | None = self._load_cached_reference()
        self._display_cache: dict[tuple[int, int], bytes] = {}  # (page, rotation) → PNG
        self._jobs: set[Job] = set()  # keep Python refs until the signals fire
        self._upload_queue: list[int] = []
        self._reference_loading = False
        self._recognize_after_reference = False  # a PDF was opened before the categories arrived
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(settings.parallel_recognitions)
        # Page images for the screen render on their own thread, so they never queue behind AI jobs.
        self.render_pool = QThreadPool(self)
        self.render_pool.setMaxThreadCount(1)
        self._rendering: set[tuple[int, int]] = set()
        self._save_timer = QTimer(self, singleShot=True, interval=400, timeout=self._save_now)

        self.setWindowTitle("Wint receipts")
        self.resize(1740, 1000)

        self.setStyleSheet(theme.STYLE_SHEET)
        self.setAcceptDrops(True)

        self.page_list = QListWidget()
        self.page_list.setObjectName("pages")
        self.page_list.setMinimumWidth(320)
        self.page_list.currentRowChanged.connect(self._show_page)
        self.page_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.page_list.customContextMenuRequested.connect(self._show_page_menu)
        self.image_pane = ImagePane()
        self.image_pane.rotate_requested.connect(self._rotate)
        self.image = self.image_pane.view
        self.image.setAcceptDrops(False)  # let PDF drops reach the window
        self.image.viewport().setAcceptDrops(False)
        self.form = ReceiptForm()
        self.form.set_reference(self.reference)
        self.form.changed.connect(self._form_changed)
        self.form.approve_requested.connect(self._approve)
        self.form.skip_requested.connect(self._toggle_skip)
        self.form.rerecognize_requested.connect(lambda: self._recognize([self._current_index()], force=True))
        self.form.attach_to_previous_requested.connect(self._attach_to_previous)
        self.form.detach_requested.connect(self._detach)
        self._deleted_stack: list[int] = []  # for Ctrl+Z, most recent last
        self.learnings = self._load_learnings()

        self._build_empty_states()
        self.list_stack = self._stack(self.list_empty, self.page_list)
        self.image_stack = self._stack(self.image_empty, self.image_pane)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_scroll.setWidget(self.form)
        self.form_stack = self._stack(self.form_empty, self.form_waiting, form_scroll)

        split = QSplitter()
        split.setHandleWidth(1)  # 1 px divider as in the design
        split.addWidget(self.list_stack)
        split.addWidget(self.image_stack)
        split.addWidget(self.form_stack)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 2)
        split.setSizes([420, 760, 560])
        self.setCentralWidget(split)

        self._build_toolbar()
        self.restore_btn = QPushButton()
        self.restore_btn.setFlat(True)
        self.restore_btn.setObjectName("link")
        self.restore_btn.clicked.connect(self._restore_all)
        self.restore_btn.hide()
        self.statusBar().addWidget(self.restore_btn)
        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)
        self._update_status()
        self._sync_panes()
        QTimer.singleShot(0, self._refresh_reference)

    # ---- empty states

    @staticmethod
    def _stack(*widgets) -> QStackedWidget:
        s = QStackedWidget()
        for w in widgets:
            s.addWidget(w)
        return s

    def _build_empty_states(self) -> None:
        self.list_empty = es.EmptyState(
            es.PAGES_SVG, "Pages", "Every page of the PDF shows up here with its date, amount and supplier.",
            width_em=8)
        for s in (PageStatus.NEEDS_REVIEW, PageStatus.APPROVED, PageStatus.UPLOADED, PageStatus.SKIPPED,
                  PageStatus.FAILED):
            self.list_empty.add_row(STATUS_LABELS[s], icon=es.status_dot(STATUS_COLORS[s], 16))
        self.image_empty = es.EmptyState(
            es.RECEIPTS_SVG, "Open a PDF of scanned receipts",
            "Drag a PDF onto this window, or click <b>Open PDF</b>. Each page should hold one receipt.",
            width_em=16)
        for lead, text in (("1 · Open", "Claude AI reads every page: date, amount, VAT, supplier, category."),
                           ("2 · Review", "check the AI's reading against the scan, fix what's marked, approve."),
                           ("3 · Upload", "each approved receipt goes to Wint with only its own page.")):
            self.image_empty.add_row(text, lead=lead)
        self.image_empty.add_button("Open PDF…", self._open_dialog, primary=True,
                                    icon=app_icons.icon("open"))
        self.image_empty.finish_buttons()
        self.form_empty = es.EmptyState(
            es.FORM_SVG, "Receipt details",
            "The fields Claude AI read from the selected page appear here, ready to check.<br><br>"
            f"<span style='color:{theme.WARNING_TEXT}'>Amber</span>: the AI wasn't sure, compare with the scan.<br>"
            f"<span style='color:{theme.ERROR_TEXT}'>Red</span>: must be fixed before approving.<br><br>"
            "<b>Ctrl+Enter</b> approve &nbsp;·&nbsp; <b>PgUp/PgDn</b> previous/next page<br>"
            "Scroll on the image to zoom, double-click to fit.",
            width_em=10)
        self.form_waiting = es.EmptyState(es.READING_SVG, "", "", width_em=10)
        self._waiting_buttons = [
            self.form_waiting.add_button("Read with AI", lambda: self._recognize([self._current_index()], force=True),
                                         primary=True),
            self.form_waiting.add_button("Skip page", self._toggle_skip),
        ]
        self.form_waiting.finish_buttons()

    def _sync_panes(self) -> None:
        """Show placeholders when there is nothing to show yet."""
        has_pdf = self.session is not None and bool(self.session.pages)
        self.list_stack.setCurrentIndex(1 if has_pdf else 0)
        self.image_stack.setCurrentIndex(1 if has_pdf else 0)
        p = self._page(self._current_index()) if has_pdf else None
        if p is None:
            self.form_stack.setCurrentIndex(0)
        elif p.draft is None:
            if p.status is PageStatus.RECOGNIZING:
                self.form_waiting.set_text("Claude AI is reading this receipt…",
                                           "Usually a few seconds per page. You can review other pages meanwhile.")
            elif p.status is PageStatus.FAILED:
                self.form_waiting.set_text("AI reading failed", f"{p.error or 'Unknown error'}<br><br>Try again, or skip the page.")
            elif p.status is PageStatus.SKIPPED:
                self.form_waiting.set_text("Page skipped", "Read it with AI if it does hold a receipt.")
            else:
                self.form_waiting.set_text("Not read yet", "Let the AI read this page to fill in the receipt fields.")
            busy = p.status is PageStatus.RECOGNIZING
            for b in self._waiting_buttons:
                b.setVisible(not busy)
            self.form_stack.setCurrentIndex(1)
        else:
            self.form_stack.setCurrentIndex(2)

    def _fit_icons(self) -> None:
        h = round(self.fontMetrics().height() * 1.15)
        gap = max(4, round(h * 0.3))  # icon-to-label gap (design: 6 px at 18 px icons)
        self._toolbar.setIconSize(QSize(h + gap, h))

    def changeEvent(self, event):  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.FontChange and hasattr(self, "_toolbar"):
            self._fit_icons()
        super().changeEvent(event)

    def dragEnterEvent(self, event):  # noqa: N802 - Qt API
        if any(u.toLocalFile().lower().endswith(".pdf") for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        for u in event.mimeData().urls():
            if u.toLocalFile().lower().endswith(".pdf"):
                self.open_pdf(Path(u.toLocalFile()))
                event.acceptProposedAction()
                return

    # ---- toolbar

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toolbar = tb
        self._fit_icons()
        self.addToolBar(tb)
        icons = {
            "Open PDF…": "open", "Read with AI": "recognise", "Previous": "previous", "Next": "next",
            "Preview request": "preview", "Upload approved": "upload",
            "Address book": "people", "Reload Wint data": "reload", "Settings…": "settings",
        }

        def act(text, slot, shortcut=None, tip=None):
            a = QAction(app_icons.icon(icons[text]), text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(tip)
            tb.addAction(a)
            tb.widgetForAction(a).setFocusPolicy(Qt.FocusPolicy.NoFocus)  # no focus frame on toolbar buttons
            return a

        act("Open PDF…", self._open_dialog, QKeySequence.StandardKey.Open)
        self.recognize_act = act("Read with AI", lambda: self._recognize(None), tip="Let Claude AI read every page that hasn't been read yet")
        tb.addSeparator()
        act("Previous", lambda: self._step(-1), "PgUp")
        act("Next", lambda: self._step(1), "PgDown")
        tb.addSeparator()
        act("Preview request", self._preview_request, tip="Show the JSON that would be sent to Wint for this page")
        self.upload_act = act("Upload approved", self._upload_approved)
        tb.addSeparator()
        act("Address book", self._open_address_book, tip="Add, edit or remove the people you pick as participants")
        act("Reload Wint data", self._refresh_reference, tip="Reload categories and payment methods from Wint")
        act("Settings…", self._open_settings, "Ctrl+,")
        undo = QAction(self)
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        undo.triggered.connect(self._restore_last)
        self.addAction(undo)
        QShortcut(QKeySequence.StandardKey.Delete, self.page_list, self._delete_page,
                  context=Qt.ShortcutContext.WidgetShortcut)
        approve = QAction(self)
        approve.setShortcuts([QKeySequence("Ctrl+Return"), QKeySequence("Ctrl+Enter")])
        approve.triggered.connect(self._approve)
        self.addAction(approve)

    # ---- Wint

    def _client(self, allow_writes: bool = False) -> WintClient | None:
        creds = config.resolve_credentials(self.settings)
        if not creds.complete:
            return None
        return WintClient(creds, base_url=self.settings.wint_base_url, log_path=self.settings.request_log_path(),
                          allow_writes=allow_writes)

    def _load_cached_reference(self) -> ReferenceData | None:
        path = config.cache_dir() / REFERENCE_CACHE
        try:
            return ReferenceData.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _refresh_reference(self) -> None:
        client = self._client()
        if client is None:
            self.statusBar().showMessage("Wint credentials are not set — open Settings", 8000)
            return
        self.statusBar().showMessage("Loading categories and payment methods from Wint…")
        self._reference_loading = True

        def work():
            try:
                return client.reference_data()
            finally:
                client.close()

        self._run(Job("reference", work), self._reference_loaded, self._reference_failed)

    def _reference_loaded(self, _tag, ref: ReferenceData) -> None:
        self._reference_loading = False
        self.reference = ref
        path = config.cache_dir() / REFERENCE_CACHE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ref.model_dump_json(indent=2), encoding="utf-8")
        self.form.set_reference(ref)
        self.statusBar().showMessage(
            f"{ref.company_name}: {len(ref.categories)} categories, {len(ref.payment_methods)} payment methods", 6000)
        self._fill_default_payment_method()
        self._update_status()
        self._recognize_if_waiting()

    def _reference_failed(self, _tag, msg: str) -> None:
        self._reference_loading = False
        self.statusBar().showMessage(f"Could not load Wint data: {msg}", 10000)
        self._recognize_if_waiting()  # recognise without categories rather than not at all

    def _recognize_if_waiting(self) -> None:
        if self._recognize_after_reference:
            self._recognize_after_reference = False
            self._recognize(None)

    def _default_payment_method(self) -> int | None:
        """The configured default, otherwise the first available payment method."""
        if self.settings.default_payment_method_id is not None:
            return self.settings.default_payment_method_id
        methods = self.reference.payment_methods if self.reference else []
        return methods[0].id if methods else None

    def _fill_default_payment_method(self) -> None:
        default = self._default_payment_method()
        if default is None or not self.session:
            return
        for p in self.session.pages:
            if p.draft and p.draft.payment_method_id is None and p.status in (
                    PageStatus.NEEDS_REVIEW, PageStatus.FAILED, PageStatus.SKIPPED):
                p.draft.payment_method_id = default
                self._after_page_change(p.index)

    # ---- jobs

    def _run(self, job: Job, on_done, on_failed, pool: QThreadPool | None = None) -> None:
        self._jobs.add(job)

        def deliver(handler, tag, value):
            self._jobs.discard(job)
            if isValid(self):  # the window may be gone by the time a background job finishes
                handler(tag, value)

        job.signals.done.connect(lambda tag, res: deliver(on_done, tag, res))
        job.signals.failed.connect(lambda tag, msg: deliver(on_failed, tag, msg))
        (pool or self.pool).start(job)

    # ---- opening

    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF of receipts", str(Path.home()), "PDF files (*.pdf)")
        if path:
            self.open_pdf(Path(path))

    def open_pdf(self, path: Path) -> None:
        try:
            session = open_session(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Open PDF", f"Could not open {path.name}: {e}")
            return
        self.session = session
        self._display_cache.clear()
        self._rendering.clear()
        self.setWindowTitle(f"Wint receipts — {path.name}")
        self.page_list.clear()
        self._deleted_stack = []
        for p in session.pages:
            self.page_list.addItem(QListWidgetItem())
            self._refresh_item(p.index)
        visible = [p for p in session.pages if not p.deleted]
        self.page_list.setCurrentRow(next((p.index for p in visible if p.status in (PageStatus.NEEDS_REVIEW, PageStatus.NEW)),
                                          visible[0].index if visible else -1))
        self._fill_default_payment_method()
        self._update_status()
        if any(p.status is PageStatus.NEW for p in session.pages):
            if self.reference is None and self._reference_loading:
                # Wait for the categories so Claude can suggest one.
                self._recognize_after_reference = True
                self.statusBar().showMessage("Waiting for Wint categories before recognising…")
            else:
                self._recognize(None)

    # ---- page list

    def _page(self, index: int) -> PageState | None:
        if self.session and 0 <= index < len(self.session.pages):
            return self.session.pages[index]
        return None

    def _current_index(self) -> int:
        return self.page_list.currentRow()

    def _owner_of(self, index: int) -> int | None:
        """Index of the receipt page this page is attached to, if it is attached to another one."""
        for p in self.session.pages if self.session else []:
            if p.index != index and p.draft and index in p.draft.pages:
                return p.index
        return None

    def _refresh_item(self, index: int) -> None:
        p = self._page(index)
        item = self.page_list.item(index)
        if p is None or item is None:
            return
        owner = self._owner_of(index)
        d = p.draft
        if owner is not None:
            detail = f"attached to page {owner + 1}"
        elif p.status is PageStatus.SKIPPED:
            detail = p.recognition.page_kind.value.replace("_", " ") if p.recognition else "skipped"
        elif d and (d.date or d.amount):
            detail = " · ".join(x for x in (
                d.date.isoformat() if d.date else "?",
                f"{format_amount(d.amount)} {d.currency}" if d.amount is not None else "?",
                self._category_name(d.category_id)) if x)
        elif p.status is PageStatus.FAILED:
            detail = "failed"
        else:
            detail = STATUS_LABELS[p.status]
        item.setText(f"{index + 1}.  {detail}")
        item.setIcon(es.status_dot(STATUS_COLORS[p.status]))
        dim = p.status is PageStatus.SKIPPED or owner is not None
        item.setForeground(QBrush(self.palette().color(
            QPalette.ColorRole.PlaceholderText if dim else QPalette.ColorRole.Text)))
        item.setToolTip(p.error or STATUS_LABELS[p.status])
        item.setHidden(p.deleted)

    def _category_name(self, category_id: int | None) -> str:
        cats = self.reference.categories if self.reference else []
        return next((c.name for c in cats if c.id == category_id), "")

    def _show_page(self, index: int) -> None:
        p = self._page(index)
        if p is None:
            self.image.set_png(None)
            self.form.set_page(None, None)
            self._sync_panes()
            return
        self._show_image(p)
        self.image_pane.set_rotation_enabled(p.wint_receipt_id is None and p.status is not PageStatus.UPLOADING)
        if p.draft and p.draft.payment_method_id is None and p.status is not PageStatus.UPLOADED:
            if (default := self._default_payment_method()) is not None:
                p.draft.payment_method_id = default
                self._schedule_save()
        self.form.set_page(p, self._owner_of(index))
        self._run_checks()
        self._sync_panes()

    def _show_image(self, p: PageState, keep_view: bool = False) -> None:
        """Show the page image; renders it in the background if it isn't cached yet."""
        key = (p.index, p.rotation)
        if key in self._display_cache:
            self.image.set_png(self._display_cache[key], keep_view=keep_view)
            self._prefetch(p.index + 1)
            return
        self.image.set_png(None)  # don't keep showing the previous page while this one renders
        self._render_async(key)

    def _render_async(self, key: tuple[int, int]) -> None:
        if key in self._rendering or key in self._display_cache or not self.session:
            return
        self._rendering.add(key)
        path, (index, rotation) = Path(self.session.pdf_path), key
        job = Job(key, lambda: pdf.render_png(path, index, DISPLAY_DPI, rotation, DISPLAY_MAX_SIDE))
        self._run(job, self._rendered, self._render_failed, pool=self.render_pool)

    def _prefetch(self, index: int) -> None:
        p = self._page(index)
        if p is not None and not p.deleted:
            self._render_async((p.index, p.rotation))

    def _rendered(self, key: tuple[int, int], png: bytes) -> None:
        self._rendering.discard(key)
        self._display_cache[key] = png
        p = self._page(self._current_index())
        if p is not None and (p.index, p.rotation) == key:
            self.image.set_png(png)
            self._prefetch(p.index + 1)

    def _render_failed(self, key: tuple[int, int], msg: str) -> None:
        self._rendering.discard(key)
        self.statusBar().showMessage(f"Could not render page {key[0] + 1}: {msg}", 8000)

    def _rotate(self, delta: int) -> None:
        """Turn the current page; applies to the view, the next AI reading, and the uploaded PDF page."""
        p = self._page(self._current_index())
        if p is None or p.wint_receipt_id is not None or p.status is PageStatus.UPLOADING:
            return
        p.rotation = (p.rotation + delta) % 360
        self._show_image(p)
        self._schedule_save()
        hint = " — use “Read again with AI” if it was read sideways" if p.recognition else ""
        self.statusBar().showMessage(f"Page {p.index + 1} turned to {p.rotation}°{hint}", 6000)

    def _rotations(self) -> dict[int, int]:
        return {q.index: q.rotation for q in self.session.pages if q.rotation} if self.session else {}

    def _step(self, delta: int) -> None:
        """Move to the next/previous page that is not deleted."""
        if not self.session:
            return
        i = self._current_index() + delta
        while 0 <= i < len(self.session.pages):
            if not self.session.pages[i].deleted:
                self.page_list.setCurrentRow(i)
                return
            i += delta

    def _next_needing_review(self) -> None:
        if not self.session:
            return
        n = len(self.session.pages)
        cur = self._current_index()
        for k in range(1, n + 1):
            p = self.session.pages[(cur + k) % n]
            if p.status is PageStatus.NEEDS_REVIEW and not p.deleted and self._owner_of(p.index) is None:
                self.page_list.setCurrentRow(p.index)
                return
        self._step(1)

    # ---- recognition

    def _recognize(self, indices: list[int] | None, force: bool = False) -> None:
        if not self.session:
            return
        if indices is None:
            indices = [p.index for p in self.session.pages if p.status in (PageStatus.NEW, PageStatus.FAILED)
                       and p.wint_receipt_id is None and not p.deleted]
        categories = list(self.reference.categories) if self.reference else []
        learnings_text = self.learnings.prompt_section() if self.learnings else ""
        pdf_path = Path(self.session.pdf_path)
        sha = self.session.pdf_sha256
        s = self.settings
        log = s.recognition_log_path()
        for i in indices:
            p = self._page(i)
            if p is None or p.status in (PageStatus.RECOGNIZING, PageStatus.UPLOADING, PageStatus.UPLOADED):
                continue
            if not force and p.recognition is not None:
                continue
            p.status = PageStatus.RECOGNIZING
            p.error = None
            self._refresh_item(i)

            def work(i=i, rotation=p.rotation):
                context = {"pdf": str(pdf_path), "pdf_sha256": sha, "page": i + 1, "model": s.claude_model,
                           "dpi": s.recognition_dpi, "rotation": rotation, "categories": len(categories)}
                try:
                    png = pdf.render_png(pdf_path, i, s.recognition_dpi, rotation, RECOGNITION_MAX_SIDE)
                    res = recognize.recognize_png(png, categories, claude_path=s.claude_path, model=s.claude_model,
                                                  learnings=learnings_text)
                except Exception as e:
                    _log_quietly(log, {"event": "failed", **context, "error": str(e) or type(e).__name__})
                    raise
                res.rotation_used = rotation
                _log_quietly(log, {"event": "recognized", **context, "seconds": res.seconds, "cost_usd": res.cost_usd,
                                   "turns": res.num_turns, "usage": res.usage,
                                   "recognition": res.recognition.model_dump(mode="json")})
                return res

            self._run(Job(i, work), self._recognized, self._recognition_failed)
        self._schedule_save()
        self._update_status()
        if 0 <= self._current_index() < len(self.session.pages):
            self.form.set_page(self._page(self._current_index()), self._owner_of(self._current_index()))
        self._sync_panes()

    def _recognized(self, index: int, result: recognize.RecognitionResult) -> None:
        p = self._page(index)
        if p is None:
            return
        rec = result.recognition
        p.recognition = rec
        p.recognition_cost_usd = result.cost_usd
        keep_pages = p.draft.pages if p.draft and len(p.draft.pages) > 1 else None
        p.draft = ReceiptDraft.from_recognition(rec, index, self._default_payment_method())
        if keep_pages:
            p.draft.pages = keep_pages
        if self.learnings and rec.page_kind is PageKind.RECEIPT:
            applied = self.learnings.apply(p.draft.supplier_name, rec.supplier_org_number, p.draft.category_id)
            p.draft.supplier_name = applied.supplier_name or ""
            p.draft.category_id = applied.category_id
            if applied.notes:
                rec.notes = " ".join(([rec.notes] if rec.notes else []) + applied.notes)
        if rec.rotation_needed % 360 and rec.page_kind is not PageKind.BLANK:
            # The AI saw the page sideways or upside down: turn it, relative to how it was shown to the AI.
            p.rotation = (result.rotation_used + rec.rotation_needed) % 360
            note = f"Page turned {rec.rotation_needed}° automatically so it reads upright."
            rec.notes = " ".join(x for x in (rec.notes, note) if x)
            if index == self._current_index():
                self._show_image(p)
        p.status = PageStatus.SKIPPED if rec.page_kind in (PageKind.BLANK, PageKind.BACK_SIDE) else PageStatus.NEEDS_REVIEW
        if rec.page_kind is PageKind.BLANK:
            # Blank pages don't get a row; they can still be brought back with "Restore deleted pages".
            p.deleted = True
            if index == self._current_index():
                self._step_away_from(index)
            self.statusBar().showMessage(f"Page {index + 1} is blank and was left out of the list", 6000)
        self._after_page_change(index)

    def _recognition_failed(self, index: int, msg: str) -> None:
        p = self._page(index)
        if p is None:
            return
        p.status = PageStatus.FAILED
        p.error = msg
        self._after_page_change(index)

    # ---- review

    def _form_changed(self) -> None:
        p = self._page(self._current_index())
        if p is None or p.draft is None:
            return
        p.draft = self.form.read_draft(p.draft)
        if p.status is PageStatus.APPROVED:
            p.status = PageStatus.NEEDS_REVIEW  # edits after approval need another look
        self._refresh_item(p.index)
        self._run_checks()
        self._schedule_save()
        self._update_status()

    def _issues(self, p: PageState) -> list[checks.Issue]:
        if p.draft is None:
            return []
        issues = checks.check(p.draft, self.reference, p.recognition)
        if p.recognition and p.recognition.page_kind is PageKind.CONTINUATION and self._owner_of(p.index) is None:
            issues.append(checks.Issue(checks.Level.WARNING, "pages",
                                       "Looks like a continuation of the previous page — consider “Attach to previous receipt”"))
        return issues

    def _run_checks(self) -> None:
        p = self._page(self._current_index())
        issues = self._issues(p) if p else []
        if p and self.form.date_text_invalid():
            issues.insert(0, checks.Issue(checks.Level.ERROR, "date", "Date must be YYYY-MM-DD"))
        self.form.show_issues(issues if p and p.draft else [])

    def _approve(self) -> None:
        index = self._current_index()
        p = self._page(index)
        if p is None or p.draft is None or self._owner_of(index) is not None:
            return
        if p.status not in (PageStatus.NEEDS_REVIEW, PageStatus.FAILED, PageStatus.APPROVED):
            return
        p.draft = self.form.read_draft(p.draft)
        issues = self._issues(p)
        if checks.blocking(issues) or self.form.date_text_invalid():
            self._run_checks()
            self.statusBar().showMessage("Fix the errors marked in red before approving", 6000)
            return
        p.status = PageStatus.APPROVED
        p.error = None
        learned = self._learn_from(p)
        self._log_approval(p, learned)
        self._after_page_change(index)
        self._next_needing_review()

    def _load_learnings(self) -> Learnings | None:
        path = self.settings.learnings_path()
        return Learnings(path) if path else None

    def _learn_from(self, p: PageState) -> list[str]:
        """Remember the user's corrections to the AI's reading, for the next readings."""
        rec, d = p.recognition, p.draft
        if not self.learnings or rec is None or d is None or rec.page_kind is not PageKind.RECEIPT:
            return []
        learned = []
        try:
            supplier = d.supplier_name or rec.supplier_name
            if supplier and d.category_id is not None and d.category_id != rec.category_id:
                name = self._category_name(d.category_id) or str(d.category_id)
                learned.append(self.learnings.learn_category(supplier, rec.supplier_org_number, d.category_id, name))
        except OSError as e:
            self.statusBar().showMessage(f"Could not update the AI learnings file: {e}", 8000)
            return []
        if learned:
            self.statusBar().showMessage("Learned for next time: " + "; ".join(l.split("   #")[0] for l in learned), 8000)
        return learned

    def _log_approval(self, p: PageState, learned: list[str] | None = None) -> None:
        log = self.settings.recognition_log_path()
        try:
            reclog.write(log, {
                "event": "approved", "pdf": self.session.pdf_path, "pdf_sha256": self.session.pdf_sha256,
                "page": p.index + 1, "pages": [i + 1 for i in p.draft.pages], "client_id": p.client_id,
                "changed": reclog.changed_fields(p.recognition, p.draft),
                "uncertain": p.recognition.uncertain_fields if p.recognition else [],
                "final": p.draft.model_dump(mode="json", exclude={"pages"}),
                "learned": [l.split("   #")[0] for l in learned or []],
            })
        except OSError as e:
            self.statusBar().showMessage(f"Could not write recognition log: {e}", 8000)

    def _toggle_skip(self) -> None:
        index = self._current_index()
        p = self._page(index)
        if p is None or self._owner_of(index) is not None:
            return
        if p.status is PageStatus.SKIPPED:
            p.status = PageStatus.NEEDS_REVIEW if p.draft else PageStatus.NEW
        else:
            p.status = PageStatus.SKIPPED
        self._after_page_change(index)
        if p.status is PageStatus.SKIPPED:
            self._next_needing_review()

    def _attach_to_previous(self) -> None:
        index = self._current_index()
        p = self._page(index)
        if p is None:
            return
        prev = next((i for i in range(index - 1, -1, -1) if not self.session.pages[i].deleted), None)
        if prev is None:
            return
        owner_index = self._owner_of(prev)
        owner = self._page(prev if owner_index is None else owner_index)
        if owner is None or owner.draft is None:
            QMessageBox.information(self, "Attach page", "The previous page has no receipt to attach to yet.")
            return
        if owner.status in (PageStatus.UPLOADED, PageStatus.UPLOADING):
            QMessageBox.information(self, "Attach page", "The previous receipt is already uploaded.")
            return
        # Pages attached to this one move along with it.
        moved = p.draft.pages if p.draft else [index]
        owner.draft.pages = sorted(set(owner.draft.pages) | set(moved) | {index})
        if p.draft:
            p.draft.pages = [index]
        p.status = PageStatus.SKIPPED
        if owner.status is PageStatus.APPROVED:
            owner.status = PageStatus.NEEDS_REVIEW
        self._after_page_change(index)
        for i in owner.draft.pages:
            self._refresh_item(i)
        self._refresh_item(owner.index)

    def _detach(self) -> None:
        index = self._current_index()
        owner_index = self._owner_of(index)
        p, owner = self._page(index), self._page(owner_index if owner_index is not None else -1)
        if p is None or owner is None or owner.draft is None:
            return
        owner.draft.pages = [i for i in owner.draft.pages if i != index]
        if owner.status is PageStatus.APPROVED:
            owner.status = PageStatus.NEEDS_REVIEW
        p.status = PageStatus.NEEDS_REVIEW if p.draft else PageStatus.NEW
        self._refresh_item(owner.index)
        self._after_page_change(index)

    def _can_delete(self, p: PageState) -> bool:
        return not p.deleted and p.wint_receipt_id is None and p.status not in (PageStatus.UPLOADING, PageStatus.RECOGNIZING)

    def _page_menu(self) -> QMenu:
        """Context menu for the current page in the list."""
        menu = QMenu(self.page_list)
        p = self._page(self._current_index())
        delete = menu.addAction("Delete page", self._delete_page)
        delete.setShortcut(QKeySequence.StandardKey.Delete)  # shown as a hint; the shortcut lives on the list
        delete.setEnabled(p is not None and self._can_delete(p))
        if p is not None and not delete.isEnabled():
            delete.setToolTip("Uploaded pages and pages being processed can't be deleted")
        deleted = sum(q.deleted for q in self.session.pages) if self.session else 0
        if deleted:
            menu.addSeparator()
            menu.addAction(f"Restore deleted pages ({deleted})", self._restore_all)
        return menu

    def _show_page_menu(self, pos) -> None:
        item = self.page_list.itemAt(pos)
        if item is not None:
            self.page_list.setCurrentItem(item)  # right-click selects the page it acts on
        self._page_menu().exec(self.page_list.viewport().mapToGlobal(pos))

    def _delete_page(self) -> None:
        index = self._current_index()
        p = self._page(index)
        if p is None or p.deleted:
            return
        if not self._can_delete(p):
            self.statusBar().showMessage("This page can't be deleted while it is being processed or after it is uploaded", 6000)
            return
        # Detach from the receipt it belongs to, and release pages attached to it.
        owner_index = self._owner_of(index)
        if owner_index is not None:
            owner = self._page(owner_index)
            owner.draft.pages = [i for i in owner.draft.pages if i != index]
            if owner.status is PageStatus.APPROVED:
                owner.status = PageStatus.NEEDS_REVIEW
            self._refresh_item(owner_index)
        if p.draft and len(p.draft.pages) > 1:
            for i in p.draft.pages:
                q = self._page(i)
                if i != index and q is not None:
                    q.status = PageStatus.NEEDS_REVIEW if q.draft else PageStatus.NEW
            p.draft.pages = [index]
        p.deleted = True
        self._deleted_stack.append(index)
        self._step_away_from(index)
        self._after_page_change(index)
        for q in self.session.pages:
            self._refresh_item(q.index)
        self.statusBar().showMessage(f"Page {index + 1} deleted — Ctrl+Z to restore", 6000)

    def _step_away_from(self, index: int) -> bool:
        for delta in (1, -1):
            i = index + delta
            while 0 <= i < len(self.session.pages):
                if not self.session.pages[i].deleted:
                    self.page_list.setCurrentRow(i)
                    return True
                i += delta
        self.page_list.setCurrentRow(-1)
        return False

    def _restore(self, indices: list[int]) -> None:
        for i in indices:
            p = self._page(i)
            if p is not None and p.deleted:
                p.deleted = False
                self._refresh_item(i)
        if indices:
            self.page_list.setCurrentRow(indices[-1])
            self._after_page_change(indices[-1])

    def _restore_last(self) -> None:
        while self._deleted_stack:
            i = self._deleted_stack.pop()
            if self._page(i) is not None and self._page(i).deleted:
                self._restore([i])
                return

    def _restore_all(self) -> None:
        if self.session:
            self._deleted_stack.clear()
            self._restore([p.index for p in self.session.pages if p.deleted])

    def _after_page_change(self, index: int) -> None:
        self._refresh_item(index)
        if index == self._current_index():
            self.form.set_page(self._page(index), self._owner_of(index))
            self._run_checks()
            self._sync_panes()
        self._schedule_save()
        self._update_status()

    # ---- upload

    def _approved(self) -> list[PageState]:
        return [p for p in self.session.pages if p.status is PageStatus.APPROVED and not p.deleted
                and self._owner_of(p.index) is None] if self.session else []

    def _preview_request(self) -> None:
        p = self._page(self._current_index())
        if p is None or p.draft is None:
            return
        try:
            data = pdf.extract_pages(Path(self.session.pdf_path), p.draft.pages or [p.index], self._rotations())
            name = upload.attachment_name(Path(self.session.pdf_path), p.draft.pages or [p.index])
            body = receipt_post_body(p.draft, data, p.client_id, name)
        except ValueError as e:
            QMessageBox.information(self, "Preview request", str(e))
            return
        att = body["Attachments"][0]
        att["Data"] = f"<base64, {len(data):,} bytes of PDF>"
        text = "POST /api/Receipt\n\n" + json.dumps(body, indent=2, ensure_ascii=False)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Request for page {p.index + 1}")
        dlg.resize(620, 560)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        lay = QVBoxLayout(dlg)
        lay.addWidget(view)
        lay.addWidget(bb)
        dlg.exec()

    def _upload_approved(self) -> None:
        pages = self._approved()
        if not pages:
            QMessageBox.information(self, "Upload", "No approved receipts to upload.")
            return
        if not self.settings.uploads_enabled:
            QMessageBox.information(self, "Upload", "Uploads are turned off in Settings, because creating receipts "
                                    "has not been tested against the Wint API yet.\n\nUse “Preview request” to see "
                                    "what would be sent.")
            return
        bad = [p.index + 1 for p in pages if checks.blocking(self._issues(p))]
        if bad:
            QMessageBox.warning(self, "Upload", f"Pages {', '.join(map(str, bad))} have errors; fix them first.")
            return
        totals: dict[str, float] = {}
        for p in pages:
            totals[p.draft.currency] = totals.get(p.draft.currency, 0) + (p.draft.amount or 0)
        summary = ", ".join(f"{format_amount(v)} {k}" for k, v in totals.items())
        company = self.reference.company_name if self.reference else "Wint"
        if QMessageBox.question(self, "Upload to Wint",
                                f"Create {len(pages)} receipt(s) in {company}, total {summary}?\n\n"
                                "This writes to your real bookkeeping.") != QMessageBox.StandardButton.Yes:
            return
        self._upload_queue = [p.index for p in pages]
        self.upload_act.setEnabled(False)
        self._upload_next()

    def _upload_next(self) -> None:
        if not self._upload_queue:
            self.upload_act.setEnabled(True)
            self.statusBar().showMessage("Upload finished", 8000)
            return
        index = self._upload_queue.pop(0)
        p = self._page(index)
        client = self._client(allow_writes=True)
        if p is None or client is None:
            self._upload_queue.clear()
            self.upload_act.setEnabled(True)
            return
        snapshot = p.model_copy(deep=True)
        rotations = self._rotations()
        pdf_path = Path(self.session.pdf_path)
        p.status = PageStatus.UPLOADING
        self._after_page_change(index)
        self._save_now()  # so a crash mid-upload is recoverable

        def work():
            try:
                return upload.upload_page(client, pdf_path, snapshot, rotations)
            finally:
                client.close()

        self._run(Job(index, work), self._uploaded, self._upload_failed)

    def _uploaded(self, index: int, receipt_id: int) -> None:
        p = self._page(index)
        if p:
            p.status = PageStatus.UPLOADED
            p.wint_receipt_id = receipt_id
            p.error = None
            self._after_page_change(index)
            if p.draft:
                for i in p.draft.pages:
                    self._refresh_item(i)
        self._upload_next()

    def _upload_failed(self, index: int, msg: str) -> None:
        p = self._page(index)
        if p:
            p.status = PageStatus.APPROVED
            p.error = f"Upload failed: {msg}"
            self._after_page_change(index)
        self._upload_queue.clear()
        self.upload_act.setEnabled(True)
        QMessageBox.warning(self, "Upload", f"Page {index + 1} failed to upload; remaining uploads stopped.\n\n{msg}")

    # ---- settings

    def _open_address_book(self) -> None:
        if self.reference is None:
            QMessageBox.information(self, "Address book", "Wint data isn't loaded yet; check Settings → Wint API.")
            return
        dlg = AddressBookDialog(self.reference.persons, self.reference.common_person_ids,
                                lambda: self._client(allow_writes=True), self)
        dlg.exec()
        if dlg.changed:
            self._refresh_reference()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self.reference, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings = dlg.apply()
        self.learnings = self._load_learnings()
        self.pool.setMaxThreadCount(self.settings.parallel_recognitions)
        self._update_status()
        self._refresh_reference()

    # ---- persistence and status

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save_now(self) -> None:
        if self.session:
            try:
                save_session(self.session)
            except OSError as e:
                self.statusBar().showMessage(f"Could not save session: {e}", 10000)

    def _update_status(self) -> None:
        ref = self.reference
        parts = [ref.company_name if ref else "not connected to Wint"]
        if self.session:
            counts: dict[PageStatus, int] = {}
            for p in self.session.pages:
                if not p.deleted:
                    counts[p.status] = counts.get(p.status, 0) + 1
            parts.append(", ".join(f"{n} {STATUS_LABELS[s]}" for s, n in counts.items()))
            cost = sum(p.recognition_cost_usd or 0 for p in self.session.pages)
            if cost:
                parts.append(f"AI cost ${cost:.2f}")
        parts.append("uploads ON" if self.settings.uploads_enabled else "uploads off")
        deleted = sum(p.deleted for p in self.session.pages) if self.session else 0
        self.restore_btn.setText(f"Restore deleted pages ({deleted})")
        self.restore_btn.setVisible(deleted > 0)
        self.status_label.setText("   |   ".join(parts))
        self.upload_act.setText(f"Upload approved ({len(self._approved())})")

    def closeEvent(self, event):  # noqa: N802
        self._save_timer.stop()
        self._save_now()
        if any(p.status in (PageStatus.RECOGNIZING, PageStatus.UPLOADING) for p in (self.session.pages if self.session else [])):
            if QMessageBox.question(self, "Quit", "Work is still running. Quit anyway?") != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.pool.clear()
        self.render_pool.clear()
        self.render_pool.waitForDone(2000)  # a page render takes well under a second
        event.accept()
