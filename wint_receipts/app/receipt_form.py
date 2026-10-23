"""Editable fields of one receipt, with the check results shown under them."""
from __future__ import annotations

import html
from datetime import date

from PySide6.QtCore import QEvent, QSize, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..core.checks import DEFAULT_REASON, Issue, Level, is_representation
from . import icons as app_icons
from . import theme
from .people_picker import PeoplePicker
from ..core.models import PageState, PageStatus, ReceiptDraft, ReferenceData

WARN_STYLE = f"background-color: {theme.SURFACE_WARNING};"
ERROR_STYLE = f"background-color: {theme.SURFACE_ERROR};"
BOLD_STYLE = "font-weight: 700;"  # the amount is the number to check first


def parse_amount(text: str) -> float | None:
    t = text.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def format_amount(v: float | None) -> str:
    return "" if v is None else f"{v:.2f}"


class ReceiptForm(QWidget):
    changed = Signal()  # user edited a field
    approve_requested = Signal()
    skip_requested = Signal()
    rerecognize_requested = Signal()
    attach_to_previous_requested = Signal()
    detach_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._page: PageState | None = None

        self.title = QLabel()
        self._update_title_font()
        self.date = QLineEdit()
        self.date.setPlaceholderText("YYYY-MM-DD")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("total incl. VAT")
        self.amount.setStyleSheet(BOLD_STYLE)
        self.currency = QLineEdit()
        self.currency.setMaxLength(3)
        self.category = QComboBox()
        self.payment = QComboBox()
        self.people = PeoplePicker()
        self.people.changed.connect(self._edited)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText(DEFAULT_REASON)
        self.reason.textEdited.connect(self._edited)
        self.vat = QLabel()
        self.vat.setWordWrap(True)
        self.pages = QLabel()
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(120)  # room for the usual 2–3 sentences without scrolling
        self.issues = QLabel()
        self.issues.setWordWrap(True)

        for w in (self.date, self.amount, self.currency):
            w.textEdited.connect(self._edited)
        for w in (self.category, self.payment):
            w.currentIndexChanged.connect(self._edited)
        self.category.currentIndexChanged.connect(self._update_people_row)

        form = QFormLayout()
        self._form = form
        form.addRow("Date", self.date)
        form.addRow("Amount", self.amount)
        form.addRow("Currency", self.currency)
        form.addRow("Category", self.category)
        form.addRow("Payment method", self.payment)
        form.addRow("Participants", self.people)
        form.addRow("Reason", self.reason)
        form.addRow("VAT (AI-read)", self.vat)
        form.addRow("Attached pages", self.pages)
        form.addRow("AI notes", self.notes)

        self.approve_btn = QPushButton("Approve  (Ctrl+Enter)")
        self.approve_btn.setObjectName("primary")
        self.approve_btn.clicked.connect(self.approve_requested)
        self.skip_btn = QPushButton("Skip page")
        self.skip_btn.clicked.connect(self.skip_requested)
        self.rerec_btn = QPushButton("Read again with AI")
        self.rerec_btn.setIcon(app_icons.icon("recognise"))
        self._update_title_font()
        self.rerec_btn.clicked.connect(self.rerecognize_requested)
        self.attach_btn = QPushButton("Attach to previous")
        self.attach_btn.setToolTip("This page continues the receipt on the previous page")
        self.attach_btn.clicked.connect(self.attach_to_previous_requested)
        self.detach_btn = QPushButton("Separate receipt")
        self.detach_btn.clicked.connect(self.detach_requested)
        # Two columns so the pane stays narrow at large font sizes.
        actions = QGridLayout()
        actions.addWidget(self.approve_btn, 0, 0)
        actions.addWidget(self.skip_btn, 0, 1)
        actions.addWidget(self.rerec_btn, 1, 0)
        actions.addWidget(self.attach_btn, 1, 1)
        actions.addWidget(self.detach_btn, 2, 1)

        lay = QVBoxLayout(self)
        lay.addWidget(self.title)
        lay.addLayout(form)
        lay.addWidget(self.issues)
        lay.addLayout(actions)
        lay.addStretch()
        self.set_page(None, None)

    def _update_title_font(self) -> None:
        f = self.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.title.setFont(f)
        if hasattr(self, "rerec_btn"):  # button icons follow the font size
            h = self.fontMetrics().height()
            self.rerec_btn.setIconSize(QSize(h, h))

    def changeEvent(self, event):  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.FontChange:  # app font scaled from Settings
            self._update_title_font()
        super().changeEvent(event)

    # ---- reference data

    def set_reference(self, ref: ReferenceData | None) -> None:
        self._loading = True
        try:
            for combo, items in ((self.category, ref.categories if ref else []),
                                 (self.payment, ref.payment_methods if ref else [])):
                current = combo.currentData()
                combo.clear()
                combo.addItem("— choose —", None)
                for it in items:
                    combo.addItem(it.name, it.id)
                if (i := combo.findData(current)) >= 0:
                    combo.setCurrentIndex(i)
            self.people.set_people(ref.persons if ref else [], ref.common_person_ids if ref else [],
                                   ref.me if ref else None)
        finally:
            self._loading = False
        if self._page:
            self.set_page(self._page, self._merged_into)

    # ---- page binding

    def set_page(self, page: PageState | None, merged_into: int | None) -> None:
        """Show a page. merged_into is set when this page is attached to another receipt."""
        self._page = page
        self._merged_into = merged_into
        self._loading = True
        try:
            enabled = page is not None and page.draft is not None and merged_into is None \
                and page.status not in (PageStatus.UPLOADED, PageStatus.UPLOADING)
            for w in (self.date, self.amount, self.currency, self.category,
                      self.payment, self.people, self.reason, self.approve_btn):
                w.setEnabled(enabled)
            if page is None:
                self.title.setText("Open a PDF to start")
                self._fill(ReceiptDraft())
                self.notes.setPlainText("")
                self.pages.setText("")
                for b in (self.skip_btn, self.rerec_btn, self.attach_btn, self.detach_btn):
                    b.setEnabled(False)
                return
            status = page.status.value.replace("_", " ")
            extra = f" — Wint receipt {page.wint_receipt_id}" if page.wint_receipt_id else ""
            self.title.setText(f"Page {page.index + 1} · {status}{extra}")
            self._fill(page.draft or ReceiptDraft())
            rec = page.recognition
            notes = [rec.notes] if rec and rec.notes else []
            if rec and rec.page_kind.value != "receipt":
                notes.insert(0, f"Page looks like: {rec.page_kind.value.replace('_', ' ')}")
            if page.error:
                notes.append(f"Error: {page.error}")
            self.notes.setPlainText("\n".join(notes))
            if merged_into is not None:
                self.pages.setText(f"attached to the receipt on page {merged_into + 1}")
            elif page.draft:
                self.pages.setText(", ".join(str(i + 1) for i in page.draft.pages))
            else:
                self.pages.setText("")
            busy = page.status in (PageStatus.RECOGNIZING, PageStatus.UPLOADING, PageStatus.UPLOADED)
            self.skip_btn.setEnabled(not busy)
            self.rerec_btn.setEnabled(not busy and merged_into is None)
            self.attach_btn.setEnabled(not busy and merged_into is None and page.index > 0)
            self.detach_btn.setEnabled(merged_into is not None and page.status is not PageStatus.UPLOADED)
        finally:
            self._loading = False

    def _fill(self, d: ReceiptDraft) -> None:
        self.date.setText(d.date.isoformat() if d.date else "")
        self.amount.setText(format_amount(d.amount))
        self.currency.setText(d.currency)
        self.category.setCurrentIndex(max(self.category.findData(d.category_id), 0))
        self.payment.setCurrentIndex(max(self.payment.findData(d.payment_method_id), 0))
        self.people.set_selected(d.persons)
        self.reason.setText(d.intent)
        self._update_people_row()
        self.vat.setText("; ".join(
            f"{v.rate:g} %: {format_amount(v.amount)}" + (f" on {format_amount(v.net)}" if v.net is not None else "")
            for v in d.vat) or "—")

    def _edited(self, *_):
        if not self._loading and self._page is not None and self._page.draft is not None:
            self.changed.emit()

    def read_draft(self, base: ReceiptDraft) -> ReceiptDraft:
        try:
            d = date.fromisoformat(self.date.text().strip()) if self.date.text().strip() else None
        except ValueError:
            d = None
        return base.model_copy(update={
            "date": d,
            "amount": parse_amount(self.amount.text()),
            "currency": self.currency.text().strip().upper(),
            "category_id": self.category.currentData(),
            "payment_method_id": self.payment.currentData(),
            "persons": self.people.selected() if self.people_row_visible() else [],
            "intent": self.reason.text().strip() if self.people_row_visible() else "",
        })

    def people_row_visible(self) -> bool:
        return is_representation(self.category.currentText())

    def _update_people_row(self, *_):
        """Participants and Reason are only for representation receipts; the reason starts as the usual one."""
        visible = self.people_row_visible()
        self._form.setRowVisible(self.people, visible)
        self._form.setRowVisible(self.reason, visible)
        if visible and not self.reason.text().strip():
            self.reason.setText(DEFAULT_REASON)

    def date_text_invalid(self) -> bool:
        t = self.date.text().strip()
        if not t:
            return False
        try:
            date.fromisoformat(t)
            return False
        except ValueError:
            return True

    # ---- issues

    def _base_style(self, w) -> str:
        """Per-field style that the amber/red highlights are added to; the amount is bold."""
        return BOLD_STYLE if w is self.amount else ""

    def show_issues(self, issues: list[Issue]) -> None:
        widgets = {"date": self.date, "amount": self.amount, "total": self.amount, "currency": self.currency,
                   "category": self.category, "category_id": self.category,
                   "payment_method": self.payment, "persons": self.people.list, "intent": self.reason}
        for w in set(widgets.values()):
            w.setStyleSheet(self._base_style(w))
        for i in sorted(issues, key=lambda i: i.level is Level.ERROR):  # errors win
            if w := widgets.get(i.field):
                w.setStyleSheet(self._base_style(w) + (ERROR_STYLE if i.level is Level.ERROR else WARN_STYLE))
        if not issues:
            self.issues.setText(f"<span style='color:{theme.OK_TEXT}'>✓ No problems found</span>")
            return
        lines = [f"<span style='color:{theme.ERROR_TEXT if i.level is Level.ERROR else theme.WARNING_TEXT}'>"
                 f"{'✗' if i.level is Level.ERROR else '⚠'} {html.escape(i.message)}</span>" for i in issues]
        self.issues.setText("<br>".join(lines))
