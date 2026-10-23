"""UI flow with recognition and Wint mocked out (pytest-qt, offscreen)."""
import json

import pytest
from PySide6.QtWidgets import QDialog

QDialogAccepted = QDialog.DialogCode.Accepted

from wint_receipts.app import main_window as mw
from wint_receipts.core import recognize
from wint_receipts.core.config import Settings
from wint_receipts.core.models import (
    Category, PageKind, PageStatus, PaymentMethod, Recognition, ReferenceData,
)
from wint_receipts.core.session import session_path

REF = ReferenceData(company_id=1, company_name="Test AB", categories=[Category(id=7, name="Parkering")],
                    payment_methods=[PaymentMethod(id=16978, name="Eget utlägg", type=2)])


def rec_for(index: int) -> Recognition:
    if index == 2:
        return Recognition(page_kind=PageKind.BLANK, notes="empty page")
    return Recognition(page_kind=PageKind.RECEIPT, date="2026-10-20", total=44.85 + index, currency="SEK",
                       supplier_name=f"Shop {index}", vat=[], category_id=7, uncertain_fields=["total"])


@pytest.fixture
def window(qtbot, monkeypatch, sample_pdf):
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    calls = []
    real_render = mw.pdf.render_png
    monkeypatch.setattr(mw.pdf, "render_png", lambda path, index, dpi=200, rotation=0, max_side=None: real_render(path, index, 30, rotation))

    def fake_recognize(png, categories, **kw):
        calls.append(1)
        index = len(calls) - 1  # pages are queued in order; single worker keeps the order
        return recognize.RecognitionResult(rec_for(index), 0.01)

    monkeypatch.setattr(mw.recognize, "recognize_png", fake_recognize)
    w = mw.MainWindow(Settings(parallel_recognitions=1, default_payment_method_id=16978))
    w._reference_loaded("reference", REF)
    qtbot.addWidget(w)
    w.open_pdf(sample_pdf)
    qtbot.waitUntil(lambda: all(p.status is not PageStatus.RECOGNIZING for p in w.session.pages), timeout=10000)
    return w


def test_recognition_fills_pages(window):
    s = window.session
    assert [p.status for p in s.pages] == [PageStatus.NEEDS_REVIEW, PageStatus.NEEDS_REVIEW, PageStatus.SKIPPED]
    # the blank page is left out of the list, but can be restored
    assert s.pages[2].deleted and window.page_list.item(2).isHidden()
    assert "(1)" in window.restore_btn.text()
    assert s.pages[0].draft.payment_method_id == 16978
    assert "44.85" in window.page_list.item(0).text()


def test_approve_edit_and_persist(window, qtbot, sample_pdf):
    window.page_list.setCurrentRow(0)
    window.form.currency.setText("EUR")
    window.form.currency.textEdited.emit("EUR")
    window._approve()
    p0 = window.session.pages[0]
    assert p0.status is PageStatus.APPROVED and p0.draft.currency == "EUR"
    assert window._current_index() == 1  # moved on to the next page needing review
    window._save_now()
    saved = json.loads(session_path(sample_pdf.resolve()).read_text())
    assert saved["pages"][0]["status"] == "approved"


def test_approve_blocked_on_errors(window):
    window.page_list.setCurrentRow(0)
    window.form.amount.setText("")
    window.form.amount.textEdited.emit("")
    window._approve()
    assert window.session.pages[0].status is PageStatus.NEEDS_REVIEW


def test_upload_blocked_when_disabled(window, monkeypatch):
    window.settings = window.settings.model_copy(update={"uploads_enabled": False})
    window.page_list.setCurrentRow(0)
    window._approve()
    shown = []
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a: shown.append(a[2]))
    monkeypatch.setattr(mw.MainWindow, "_client", lambda self, allow_writes=False: pytest.fail("no client"))
    window.upload_act.trigger()  # the toolbar passes `checked`, which must not be taken as `only`
    assert shown and "turned off" in shown[0]


def test_sole_payment_method_used_and_recognition_waits_for_reference(qtbot, monkeypatch, sample_pdf):
    seen_categories = []
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: setattr(self, "_reference_loading", True))
    monkeypatch.setattr(mw.MainWindow, "_load_cached_reference", lambda self: None)
    real_render = mw.pdf.render_png
    monkeypatch.setattr(mw.pdf, "render_png", lambda path, index, dpi=200, rotation=0, max_side=None: real_render(path, index, 30, rotation))

    def fake_recognize(png, categories, **kw):
        seen_categories.append(len(categories))
        return recognize.RecognitionResult(rec_for(0), 0.01)

    monkeypatch.setattr(mw.recognize, "recognize_png", fake_recognize)
    w = mw.MainWindow(Settings(parallel_recognitions=1))  # no default payment method
    qtbot.addWidget(w)
    w._refresh_reference()
    w.open_pdf(sample_pdf)
    assert all(p.status is PageStatus.NEW for p in w.session.pages)  # waiting, not recognising
    w._reference_loaded("reference", REF)
    qtbot.waitUntil(lambda: all(p.status is not PageStatus.RECOGNIZING for p in w.session.pages), timeout=10000)
    assert seen_categories == [1, 1, 1]
    assert all(p.draft.payment_method_id == 16978 for p in w.session.pages)


def test_first_payment_method_preselected_when_several(qtbot, monkeypatch):
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    w = mw.MainWindow(Settings())
    qtbot.addWidget(w)
    w.reference = REF.model_copy(update={"payment_methods": [
        PaymentMethod(id=1, name="Bankkort"), PaymentMethod(id=2, name="Eget utlägg")]})
    assert w._default_payment_method() == 1
    w.settings = Settings(default_payment_method_id=2)
    assert w._default_payment_method() == 2


def test_recognition_log(window, tmp_path):
    lines = [json.loads(x) for x in (tmp_path / "cache" / "wint-receipts" / "recognition.log").read_text().splitlines()]
    assert [e["event"] for e in lines] == ["recognized"] * 3
    assert lines[0]["page"] == 1 and lines[0]["cost_usd"] == 0.01 and lines[0]["recognition"]["total"] == 44.85
    window.page_list.setCurrentRow(0)
    window.form.currency.setText("EUR")
    window.form.currency.textEdited.emit("EUR")
    window._approve()
    approved = json.loads((tmp_path / "cache" / "wint-receipts" / "recognition.log").read_text().splitlines()[-1])
    assert approved["event"] == "approved" and approved["changed"] == ["currency"]
    assert approved["final"]["currency"] == "EUR" and approved["uncertain"] == ["total"]


def test_recognition_failure_logged(qtbot, monkeypatch, sample_pdf, tmp_path):
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    real_render = mw.pdf.render_png
    monkeypatch.setattr(mw.pdf, "render_png", lambda path, index, dpi=200, rotation=0, max_side=None: real_render(path, index, 30, rotation))

    def boom(png, categories, **kw):
        raise recognize.RecognitionError("claude timed out after 300s")

    monkeypatch.setattr(mw.recognize, "recognize_png", boom)
    w = mw.MainWindow(Settings(parallel_recognitions=1))
    qtbot.addWidget(w)
    w.open_pdf(sample_pdf)
    qtbot.waitUntil(lambda: all(p.status is PageStatus.FAILED for p in w.session.pages), timeout=10000)
    lines = [json.loads(x) for x in (tmp_path / "cache" / "wint-receipts" / "recognition.log").read_text().splitlines()]
    assert {e["event"] for e in lines} == {"failed"} and "timed out" in lines[0]["error"]


def test_recognition_log_off(qtbot, monkeypatch, sample_pdf, tmp_path):
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    real_render = mw.pdf.render_png
    monkeypatch.setattr(mw.pdf, "render_png", lambda path, index, dpi=200, rotation=0, max_side=None: real_render(path, index, 30, rotation))
    monkeypatch.setattr(mw.recognize, "recognize_png",
                        lambda png, categories, **kw: recognize.RecognitionResult(rec_for(0), 0.01))
    w = mw.MainWindow(Settings(parallel_recognitions=1, recognition_log_enabled=False))
    qtbot.addWidget(w)
    w._reference_loaded("reference", REF)
    w.open_pdf(sample_pdf)
    qtbot.waitUntil(lambda: all(p.status is not PageStatus.RECOGNIZING for p in w.session.pages), timeout=10000)
    w.page_list.setCurrentRow(0)
    w._approve()
    assert w.session.pages[0].status is PageStatus.APPROVED
    assert not (tmp_path / "cache" / "wint-receipts" / "recognition.log").exists()


def test_font_scale_applies_live_and_cancel_reverts(qtbot):
    from PySide6.QtWidgets import QApplication
    from wint_receipts.app import fonts, settings_dialog

    fonts.apply_font_scale(1.0)
    base = QApplication.font().pointSizeF()
    assert fonts.PRESETS[0] == 0.5 and fonts.PRESETS[-1] == 2.0 and len(fonts.PRESETS) == 16
    dlg = settings_dialog.SettingsDialog(Settings(font_scale=1.0), None)
    qtbot.addWidget(dlg)
    dlg.font_scale.setCurrentIndex(dlg.font_scale.findData(1.5))
    assert QApplication.font().pointSizeF() == pytest.approx(base * 1.5)
    dlg.font_scale.setCurrentIndex(dlg.font_scale.findData(2.0))
    assert QApplication.font().pointSizeF() == pytest.approx(base * 2.0)  # scales from the system font, not cumulative
    dlg.reject()
    assert QApplication.font().pointSizeF() == pytest.approx(base)


def test_form_title_follows_app_font(qtbot):
    from PySide6.QtWidgets import QApplication
    from wint_receipts.app import fonts
    from wint_receipts.app.receipt_form import ReceiptForm

    fonts.apply_font_scale(1.0)
    form = ReceiptForm()
    qtbot.addWidget(form)
    before = form.title.font().pointSizeF()
    fonts.apply_font_scale(2.0)
    QApplication.processEvents()
    assert form.title.font().pointSizeF() == pytest.approx(before * 2.0)
    fonts.apply_font_scale(1.0)


def test_empty_states_and_pane_switching(qtbot, monkeypatch, sample_pdf):
    import threading
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    real_render = mw.pdf.render_png
    monkeypatch.setattr(mw.pdf, "render_png", lambda path, index, dpi=200, rotation=0, max_side=None: real_render(path, index, 30, rotation))
    gate = threading.Event()

    def slow(png, categories, **kw):
        gate.wait(5)
        return recognize.RecognitionResult(rec_for(0), 0.01)

    monkeypatch.setattr(mw.recognize, "recognize_png", slow)
    w = mw.MainWindow(Settings(parallel_recognitions=1))
    qtbot.addWidget(w)
    w._reference_loaded("reference", REF)
    assert (w.list_stack.currentIndex(), w.image_stack.currentIndex(), w.form_stack.currentIndex()) == (0, 0, 0)
    w.open_pdf(sample_pdf)
    assert (w.list_stack.currentIndex(), w.image_stack.currentIndex()) == (1, 1)
    assert w.form_stack.currentIndex() == 1 and "reading" in w.form_waiting.title.text()
    gate.set()
    qtbot.waitUntil(lambda: all(p.status is not PageStatus.RECOGNIZING for p in w.session.pages), timeout=10000)
    w.page_list.setCurrentRow(0)
    assert w.form_stack.currentIndex() == 2  # the real form once a draft exists


def test_drop_pdf_opens_it(qtbot, monkeypatch, sample_pdf):
    from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
    from PySide6.QtGui import QDropEvent
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "_recognize", lambda self, indices, force=False: None)
    w = mw.MainWindow(Settings())
    qtbot.addWidget(w)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(sample_pdf))])
    ev = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    w.dropEvent(ev)
    assert w.session is not None and len(w.session.pages) == 3


def test_font_scale_reaches_main_window_under_style_sheet(qtbot, monkeypatch):
    """Regression: the window style sheet froze widget fonts, so the live change did nothing."""
    from PySide6.QtWidgets import QApplication
    from wint_receipts.app import fonts

    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    fonts.apply_font_scale(1.0)
    base = QApplication.font().pointSizeF()
    w = mw.MainWindow(Settings())
    qtbot.addWidget(w)
    w.show()
    assert w.styleSheet()  # the case that used to break
    fonts.apply_font_scale(2.0)
    QApplication.processEvents()
    for widget in (w.page_list, w.form.date, w.image_empty.body):
        assert widget.font().pointSizeF() == pytest.approx(base * 2.0)
    fonts.apply_font_scale(1.0)


def test_delete_page_hides_it_and_can_be_restored(window, sample_pdf):
    s = window.session
    window._restore_all()  # bring back the auto-removed blank page 3
    window.page_list.setCurrentRow(1)
    window._delete_page()
    assert s.pages[1].deleted and window.page_list.item(1).isHidden()
    assert window._current_index() != 1
    assert window.restore_btn.isVisibleTo(window) and "(1)" in window.restore_btn.text()
    # navigation skips the deleted page
    window.page_list.setCurrentRow(0)
    window._step(1)
    assert window._current_index() == 2
    window._save_now()
    again = mw.open_session(sample_pdf)
    assert again.pages[1].deleted  # survives reopening; the PDF itself still has 3 pages
    window._restore_last()
    assert not s.pages[1].deleted and not window.page_list.item(1).isHidden()
    assert not window.restore_btn.isVisibleTo(window)


def test_delete_releases_attached_pages_and_owner(window):
    s = window.session
    s.pages[0].draft.pages = [0, 1]  # page 2 joined to page 1 (older sessions can have this)
    s.pages[1].status = PageStatus.SKIPPED
    assert s.pages[0].draft.pages == [0, 1]
    window.page_list.setCurrentRow(0)
    window._delete_page()  # deleting the owner frees page 2 again
    assert s.pages[0].deleted and s.pages[1].status is PageStatus.NEEDS_REVIEW
    assert s.pages[0].draft.pages == [0]
    window._restore_all()
    assert not s.pages[0].deleted


def test_uploaded_page_cannot_be_deleted_and_deleted_not_uploaded(window):
    s = window.session
    s.pages[0].wint_receipt_id = 99
    s.pages[0].status = PageStatus.UPLOADED
    window.page_list.setCurrentRow(0)
    window._delete_page()
    assert not s.pages[0].deleted
    s.pages[1].status = PageStatus.APPROVED
    window.page_list.setCurrentRow(1)
    window._delete_page()
    assert window._approved() == []  # a deleted approved page is not uploaded


def test_page_context_menu(window):
    window._restore_all()  # start without the auto-removed blank page
    window.page_list.setCurrentRow(1)
    menu = window._page_menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Read again with AI", "Approve", "Upload to Wint", "Delete page"]
    delete = next(a for a in menu.actions() if a.text() == "Delete page")
    assert delete.isEnabled()
    delete.trigger()
    assert window.session.pages[1].deleted
    menu = window._page_menu()  # now also offers restoring
    restore = [a for a in menu.actions() if a.text().startswith("Restore deleted pages (1)")]
    assert restore
    restore[0].trigger()
    assert not window.session.pages[1].deleted
    window.session.pages[0].wint_receipt_id = 5
    window.session.pages[0].status = PageStatus.UPLOADED
    window.page_list.setCurrentRow(0)
    actions = {a.text(): a for a in window._page_menu().actions() if not a.isSeparator()}
    assert not actions["Delete page"].isEnabled() and not actions["Read again with AI"].isEnabled()  # uploaded


def test_payment_method_prefilled_for_saved_drafts(qtbot, monkeypatch, sample_pdf):
    """Drafts saved without a payment method get the first available one when the PDF is reopened."""
    from wint_receipts.core.models import ReceiptDraft
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    sess = mw.open_session(sample_pdf)
    for p in sess.pages:
        p.draft = ReceiptDraft(amount=10.0, pages=[p.index])  # no payment method
        p.status = PageStatus.NEEDS_REVIEW
    mw.save_session(sess)
    w = mw.MainWindow(Settings())  # no default in settings
    qtbot.addWidget(w)
    w._reference_loaded("reference", REF.model_copy(update={"payment_methods": [
        PaymentMethod(id=1, name="Bankkort"), PaymentMethod(id=2, name="Eget utlägg")]}))
    w.open_pdf(sample_pdf)
    assert [p.draft.payment_method_id for p in w.session.pages] == [1, 1, 1]
    assert w.form.payment.currentData() == 1


def test_rotate_page_is_saved_and_used_for_preview(window, sample_pdf):
    window.page_list.setCurrentRow(0)
    window.image_pane.rotate_right.trigger()
    window.image_pane.rotate_right.trigger()
    window.image_pane.rotate_left.trigger()
    p = window.session.pages[0]
    assert p.rotation == 90
    assert window._rotations() == {0: 90}
    window._save_now()
    assert mw.open_session(sample_pdf).pages[0].rotation == 90
    p.wint_receipt_id, p.status = 5, PageStatus.UPLOADED  # uploaded pages can't be turned any more
    window._rotate(90)
    assert p.rotation == 90


def test_zoom_controls(window):
    window.page_list.setCurrentRow(0)
    pane = window.image_pane
    pane.actual.trigger()
    assert pane.zoom_label.text() == "100%"
    pane.zoom_in.trigger()
    assert pane.zoom_label.text() == "125%"
    pane.zoom_out.trigger()
    pane.zoom_out.trigger()
    assert pane.zoom_label.text() == "80%"
    pane.fit.trigger()
    assert window.image._fit


def test_amount_is_bold_also_when_highlighted(window):
    window.page_list.setCurrentRow(0)  # rec_for marks "total" uncertain → amber highlight on amount
    style = window.form.amount.styleSheet()
    assert "font-weight: 700" in style and "background-color" in style
    assert not hasattr(window.form, "supplier") and not hasattr(window.form, "comment")


def test_category_correction_is_learned_and_reused(qtbot, monkeypatch, sample_pdf, tmp_path):
    """Correct the AI's category once; the next reading of the same supplier gets it right."""
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    real_render = mw.pdf.render_png
    monkeypatch.setattr(mw.pdf, "render_png", lambda path, index, dpi=200, rotation=0, max_side=None: real_render(path, index, 30, rotation))
    prompts = []

    def fake(png, categories, learnings="", **kw):
        prompts.append(learnings)
        return recognize.RecognitionResult(Recognition(page_kind=PageKind.RECEIPT, date="2026-10-20", total=99.0,
                                                       currency="SEK", supplier_name="MR WOK", category_id=7), 0.01)

    monkeypatch.setattr(mw.recognize, "recognize_png", fake)
    ref = REF.model_copy(update={"categories": [Category(id=7, name="Parkering"), Category(id=8, name="Förbrukning")]})
    settings = Settings(parallel_recognitions=1, learnings_file=str(tmp_path / "learnings.txt"))
    w = mw.MainWindow(settings)
    qtbot.addWidget(w)
    w._reference_loaded("reference", ref)
    w.open_pdf(sample_pdf)
    qtbot.waitUntil(lambda: all(p.status is not PageStatus.RECOGNIZING for p in w.session.pages), timeout=10000)
    w.page_list.setCurrentRow(0)
    w.form.category.setCurrentIndex(w.form.category.findData(8))   # the user corrects the category
    w._approve()
    text = (tmp_path / "learnings.txt").read_text()
    assert 'category: "MR WOK" = "Förbrukning" [8]' in text
    w._recognize([1], force=True)  # read another receipt from the same place
    qtbot.waitUntil(lambda: w.session.pages[1].status is not PageStatus.RECOGNIZING, timeout=10000)
    d = w.session.pages[1].draft
    assert d.category_id == 8
    assert "earlier correction" in w.session.pages[1].recognition.notes
    assert "Förbrukning" in prompts[-1]  # the AI is told as well


def test_page_turned_automatically_when_ai_sees_it_sideways(qtbot, monkeypatch, sample_pdf):
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    real_render = mw.pdf.render_png
    seen_rotations = []

    def render(path, index, dpi=200, rotation=0, max_side=None):
        seen_rotations.append(rotation)
        return real_render(path, index, 30, rotation)

    monkeypatch.setattr(mw.pdf, "render_png", render)
    monkeypatch.setattr(mw.recognize, "recognize_png", lambda png, categories, **kw: recognize.RecognitionResult(
        Recognition(page_kind=PageKind.RECEIPT, total=10.0, currency="SEK", rotation_needed=90), 0.01))
    w = mw.MainWindow(Settings(parallel_recognitions=1))
    qtbot.addWidget(w)
    w._reference_loaded("reference", REF)
    w.open_pdf(sample_pdf)
    qtbot.waitUntil(lambda: all(p.status is not PageStatus.RECOGNIZING for p in w.session.pages), timeout=10000)
    p = w.session.pages[0]
    assert p.rotation == 90 and "turned 90°" in p.recognition.notes
    # Reading again starts from the turned page; another 90 from the AI adds up to 180.
    w._recognize([0], force=True)
    qtbot.waitUntil(lambda: w.session.pages[0].status is not PageStatus.RECOGNIZING, timeout=10000)
    assert 90 in seen_rotations and w.session.pages[0].rotation == 180


def test_page_image_renders_off_the_ui_thread(window, qtbot):
    import threading
    ui = threading.get_ident()
    threads = []
    real = mw.pdf.render_png
    mw.pdf.render_png = lambda *a, **kw: (threads.append(threading.get_ident()), real(a[0], a[1], 30))[1]
    try:
        window._display_cache.clear()
        window.page_list.setCurrentRow(1)
        qtbot.waitUntil(lambda: (1, 0) in window._display_cache, timeout=5000)
    finally:
        mw.pdf.render_png = real
    assert threads and ui not in threads
    assert not window.image._item.pixmap().isNull()



def test_people_row_only_for_representation_and_saved(window):
    from wint_receipts.core.models import Person
    from PySide6.QtCore import Qt
    ref = REF.model_copy(update={
        "categories": [Category(id=7, name="Parkering"), Category(id=8, name="Personalrepresentation")],
        "persons": [Person(id=3, name="Cecilia"), Person(id=1, name="Anna", company="A AB")],
        "common_person_ids": [3]})
    window._reference_loaded("reference", ref)
    window.session.pages[0].draft.participants_reviewed = True  # this test picks people by hand
    window.page_list.setCurrentRow(0)
    form = window.form
    assert not form.people_row_visible()
    form.category.setCurrentIndex(form.category.findData(8))
    assert form.people_row_visible()
    assert "at least 2 participants" in form.issues.text()
    texts = [form.people.list.item(i).text() for i in range(form.people.list.count())]
    assert texts == ["Most used", "Cecilia", "Everyone else", "Anna — A AB"]
    form.people.search.setText("anna")
    assert form.people.list.item(1).isHidden() and not form.people.list.item(3).isHidden()
    form.people.list.item(3).setCheckState(Qt.CheckState.Checked)
    p = window.session.pages[0]
    assert [x.name for x in p.draft.persons] == ["Anna"]
    window._approve()
    assert p.status is not PageStatus.APPROVED  # one participant isn't enough
    form.people.search.setText("")
    form.people.list.item(1).setCheckState(Qt.CheckState.Checked)
    assert "participants" not in form.issues.text()
    window.page_list.setCurrentRow(1)
    window.page_list.setCurrentRow(0)  # coming back shows the saved selection
    assert sorted(x.name for x in form.people.selected()) == ["Anna", "Cecilia"]



def test_account_holder_is_added_automatically(window):
    from wint_receipts.core.models import Person
    from PySide6.QtCore import Qt
    me = Person(id=0, name="Ada Lovelace", company="Test AB")
    ref = REF.model_copy(update={"categories": [Category(id=8, name="Representation")],
                                 "persons": [Person(id=3, name="Cecilia")], "common_person_ids": [3], "me": me})
    window._reference_loaded("reference", ref)
    window.session.pages[0].draft.participants_reviewed = True  # this test picks people by hand
    window.page_list.setCurrentRow(0)
    form = window.form
    form.category.setCurrentIndex(form.category.findData(8))
    first = form.people.list.item(0)
    assert "you, added automatically" in first.text() and first.checkState() is Qt.CheckState.Checked
    assert not first.flags() & Qt.ItemFlag.ItemIsUserCheckable  # can't be unticked
    assert "1 so far" in form.issues.text()
    form.people.search.setText("zzz")
    assert not first.isHidden()  # stays visible while searching
    form.people.search.setText("")
    form.people.list.item(2).setCheckState(Qt.CheckState.Checked)  # one guest is enough now
    p = window.session.pages[0]
    assert [x.name for x in p.draft.persons] == ["Ada Lovelace", "Cecilia"]
    assert form.reason.text() == "collaboration discussion" and p.draft.intent == "collaboration discussion"
    window._approve()
    assert p.status is PageStatus.APPROVED


def test_address_book_add_edit_remove(qtbot, monkeypatch):
    from wint_receipts.app import address_book as ab
    from wint_receipts.core.models import Person

    class FakeClient:
        calls = []

        def add_person(self, name, company):
            self.calls.append(("add", name, company)); return 500 + len(self.calls)

        def replace_person(self, pid, name, company):
            self.calls.append(("replace", pid, name, company)); return 700

        def remove_person(self, pid, name=""):
            self.calls.append(("remove", pid))

        def close(self):
            pass

    answers = iter([("Ada", "Analytical AB"), ("Ada Lovelace", "Analytical AB")])
    monkeypatch.setattr(ab.PersonDialog, "exec", lambda self: QDialogAccepted)
    monkeypatch.setattr(ab.PersonDialog, "values", lambda self: next(answers))
    monkeypatch.setattr(ab.QMessageBox, "question", lambda *a: ab.QMessageBox.StandardButton.Yes)
    dlg = ab.AddressBookDialog([Person(id=1, name="Bo")], [1], lambda: FakeClient())
    qtbot.addWidget(dlg)
    dlg._add()
    qtbot.waitUntil(lambda: any(p.name == "Ada" for p in dlg._people), timeout=5000)
    ada_row = next(i for i in range(dlg.list.count()) if dlg.list.item(i).text().startswith("Ada"))
    dlg.list.setCurrentRow(ada_row)
    dlg._edit()
    qtbot.waitUntil(lambda: any(p.name == "Ada Lovelace" for p in dlg._people), timeout=5000)
    assert [p.name for p in dlg._people] == ["Bo", "Ada Lovelace"]
    bo_row = next(i for i in range(dlg.list.count()) if dlg.list.item(i).text().startswith("Bo"))
    dlg.list.setCurrentRow(bo_row)
    assert "most used" in dlg.list.item(bo_row).text()
    dlg._remove()
    qtbot.waitUntil(lambda: [p.name for p in dlg._people] == ["Ada Lovelace"], timeout=5000)
    assert FakeClient.calls == [("add", "Ada", "Analytical AB"), ("replace", 501, "Ada Lovelace", "Analytical AB"),
                                ("remove", 1)]
    assert dlg.changed



def test_read_again_from_menu_and_busy_indicator(qtbot, monkeypatch, sample_pdf):
    import threading
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    real_render = mw.pdf.render_png
    monkeypatch.setattr(mw.pdf, "render_png", lambda path, index, dpi=200, rotation=0, max_side=None: real_render(path, index, 30))
    gate = threading.Event()
    calls = []

    def slow(png, categories, **kw):
        calls.append(1)
        gate.wait(5)
        return recognize.RecognitionResult(rec_for(0), 0.01)

    monkeypatch.setattr(mw.recognize, "recognize_png", slow)
    w = mw.MainWindow(Settings(parallel_recognitions=3))
    qtbot.addWidget(w)
    w._reference_loaded("reference", REF)
    w.open_pdf(sample_pdf)
    assert w.ai_busy.isVisibleTo(w) and "AI is reading 3 pages" in w.ai_busy_label.text()
    gate.set()
    qtbot.waitUntil(lambda: all(p.status is not PageStatus.RECOGNIZING for p in w.session.pages), timeout=10000)
    assert not w.ai_busy.isVisibleTo(w)
    gate.clear()
    w.page_list.setCurrentRow(0)
    read = next(a for a in w._page_menu().actions() if "with AI" in a.text())
    assert read.text() == "Read again with AI" and read.isEnabled()
    read.trigger()
    assert w.session.pages[0].status is PageStatus.RECOGNIZING and "1 page…" in w.ai_busy_label.text()
    gate.set()
    qtbot.waitUntil(lambda: w.session.pages[0].status is not PageStatus.RECOGNIZING, timeout=10000)
    assert len(calls) == 4


def test_read_with_ai_asks_before_reading_again(window, monkeypatch, qtbot):
    asked = []
    queued = []
    monkeypatch.setattr(mw.MainWindow, "_recognize", lambda self, indices, force=False: queued.append((indices, force)))
    s = window.session
    window._restore_all()  # page 3 (blank) back in the list
    s.pages[2].status = PageStatus.NEW
    window._read_with_ai()
    assert queued == [(None, False)] and not asked  # unread pages: just read them, no question
    queued.clear()
    s.pages[2].status = PageStatus.NEEDS_REVIEW
    s.pages[0].status = PageStatus.APPROVED
    for answer, expected in (("unapproved", [1, 2]), ("all", [0, 1, 2]), (None, None)):
        monkeypatch.setattr(mw.MainWindow, "_ask_read_again",
                            lambda self, u, e, a=answer: (asked.append((u, e)), a)[1])
        window._read_with_ai()
        if expected is None:
            assert not queued
        else:
            assert queued.pop() == (expected, True)
    assert asked[-1] == (2, 3)  # 2 not approved, 3 in total



def test_participants_suggested_until_confirmed_and_remembered(qtbot, monkeypatch, sample_pdf, tmp_path):
    from wint_receipts.core.models import Person
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    real_render = mw.pdf.render_png
    monkeypatch.setattr(mw.pdf, "render_png", lambda path, index, dpi=200, rotation=0, max_side=None: real_render(path, index, 30))
    monkeypatch.setattr(mw.recognize, "recognize_png", lambda png, categories, **kw: recognize.RecognitionResult(
        Recognition(page_kind=PageKind.RECEIPT, date="2026-10-20", total=500.0, currency="SEK",
                    supplier_name="Mr Wok", category_id=8), 0.01))
    me = Person(id=0, name="Ada Lovelace", company="Test AB")
    ref = REF.model_copy(update={"categories": [Category(id=8, name="Representation")],
                                 "persons": [Person(id=3, name="Cecilia"), Person(id=1, name="Anna")],
                                 "common_person_ids": [3], "me": me})
    w = mw.MainWindow(Settings(parallel_recognitions=1, learnings_file=str(tmp_path / "learnings.txt")))
    qtbot.addWidget(w)
    w._reference_loaded("reference", ref)
    w.open_pdf(sample_pdf)
    qtbot.waitUntil(lambda: all(p.status is not PageStatus.RECOGNIZING for p in w.session.pages), timeout=10000)
    w.page_list.setCurrentRow(0)
    p, form = w.session.pages[0], w.form
    # no history for Mr Wok yet → the most frequent guest is suggested, and approval waits for Confirm
    assert [x.name for x in p.draft.persons] == ["Ada Lovelace", "Cecilia"] and p.draft.participants_suggested
    assert "check who was there" in form.issues.text() and "Suggested" in form.people.summary.text()
    # the user picks Anna instead (ticking clears the suggestion) and approves → remembered for Mr Wok
    from PySide6.QtCore import Qt
    rows = {form.people.list.item(i).text(): form.people.list.item(i) for i in range(form.people.list.count())}
    rows["Cecilia"].setCheckState(Qt.CheckState.Unchecked)
    rows["Anna"].setCheckState(Qt.CheckState.Checked)
    assert not p.draft.participants_suggested and [x.name for x in p.draft.persons] == ["Ada Lovelace", "Anna"]
    w._approve()
    assert p.status is PageStatus.APPROVED
    assert 'participants: "Mr Wok" = "Anna" [1]' in (tmp_path / "learnings.txt").read_text()
    # the next Mr Wok receipt suggests Anna; approving accepts it as is
    p2 = w.session.pages[1]
    p2.draft.persons, p2.draft.participants_suggested, p2.draft.participants_reviewed = [], False, False
    w.page_list.setCurrentRow(0)
    w.page_list.setCurrentRow(1)
    assert [x.name for x in p2.draft.persons] == ["Ada Lovelace", "Anna"] and p2.draft.participants_suggested
    w._approve()
    assert p2.status is PageStatus.APPROVED
    assert not p2.draft.participants_suggested and p2.draft.participants_reviewed



def test_most_used_categories_on_top_with_a_divider(window):
    ref = REF.model_copy(update={"categories": [Category(id=1, name="Alpha"), Category(id=2, name="Beta"),
                                                Category(id=3, name="Gamma")], "common_category_ids": [3, 1]})
    window._reference_loaded("reference", ref)
    combo = window.form.category
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == ["— choose —", "Gamma", "Alpha", "", "Beta"]  # "" is the divider
    assert combo.findData(2) == 4


def test_uploaded_pages_restored_from_ledger(qtbot, monkeypatch, sample_pdf):
    from wint_receipts.core import config
    from wint_receipts.core.ledger import Ledger
    sess = mw.open_session(sample_pdf)  # a fresh session, as if the old file was deleted
    Ledger(config.ledger_path()).add(pdf_sha256=sess.pdf_sha256, pdf=str(sample_pdf), page=1, client_id="cid-x",
                                     wint_receipt_id=3026953, date="2026-10-18", amount=660.0, currency="SEK")
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "_recognize", lambda self, indices, force=False: None)
    w = mw.MainWindow(Settings())
    qtbot.addWidget(w)
    w.open_pdf(sample_pdf)
    p = w.session.pages[1]
    assert p.status is PageStatus.UPLOADED and p.wint_receipt_id == 3026953 and p.client_id == "cid-x"
    assert w.session.pages[0].status is PageStatus.NEW


def test_upload_skips_pages_already_in_the_ledger(window, monkeypatch):
    from wint_receipts.core import config
    from wint_receipts.core.ledger import Ledger
    s = window.session
    s.pages[0].status = PageStatus.APPROVED
    Ledger(config.ledger_path()).add(pdf_sha256=s.pdf_sha256, pdf=s.pdf_path, page=0, client_id="other-window",
                                     wint_receipt_id=3027387, date="2026-10-13", amount=146.55, currency="SEK")
    shown = []
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a: shown.append(a[2]))
    window._upload_approved()
    assert s.pages[0].status is PageStatus.UPLOADED and s.pages[0].wint_receipt_id == 3027387
    assert "☁ Wint #3027387" in window.page_list.item(0).text()
    assert shown and "No approved receipts" in shown[0]  # nothing left to upload


def test_command_line(tmp_path, sample_pdf, capsys, monkeypatch):
    from wint_receipts.app import main as entry
    monkeypatch.chdir(sample_pdf.parent)
    args, qt = entry.parse_args([sample_pdf.name, "-platform", "offscreen"])
    assert args.pdf == sample_pdf.resolve() and qt == ["-platform", "offscreen"]
    assert entry.parse_args([])[0].pdf is None
    for bad, message in ((str(tmp_path / "missing.pdf"), "no such file"), (str(tmp_path / "config"), "no such file")):
        with pytest.raises(SystemExit):
            entry.parse_args([bad])
        assert message in capsys.readouterr().err
    note = tmp_path / "notes.txt"
    note.write_text("x")
    with pytest.raises(SystemExit):
        entry.parse_args([str(note)])
    assert "not a PDF" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        entry.parse_args(["--version"])
    assert "wint-receipts" in capsys.readouterr().out



def test_menu_approve_and_upload_single_page(window, monkeypatch):
    s = window.session
    window.page_list.setCurrentRow(0)
    actions = {a.text(): a for a in window._page_menu().actions() if not a.isSeparator()}
    assert actions["Approve"].isEnabled() and not actions["Upload to Wint"].isEnabled()
    actions["Approve"].trigger()
    assert s.pages[0].status is PageStatus.APPROVED
    s.pages[1].status = PageStatus.APPROVED  # another approved page that must NOT be uploaded
    window.page_list.setCurrentRow(0)
    actions = {a.text(): a for a in window._page_menu().actions() if not a.isSeparator()}
    assert not actions["Approve"].isEnabled() and actions["Upload to Wint"].isEnabled()
    queued = []
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a: mw.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(mw.MainWindow, "_upload_next", lambda self: queued.append(list(self._upload_queue)))
    actions["Upload to Wint"].trigger()
    assert queued == [[0]]


def test_multi_select_menu_acts_on_each_fitting_page(window, monkeypatch):
    from PySide6.QtCore import QItemSelectionModel
    s = window.session
    window._restore_all()  # bring back the blank page 3
    s.pages[2].status = PageStatus.NEEDS_REVIEW
    s.pages[2].draft = s.pages[0].draft.model_copy(update={"pages": [2]})  # the blank page gets real values
    s.pages[1].status = PageStatus.APPROVED
    lst = window.page_list
    lst.setCurrentRow(0)
    for i in (1, 2):
        lst.selectionModel().select(lst.model().index(i, 0), QItemSelectionModel.SelectionFlag.Select)
    assert window._selected_indices() == [0, 1, 2]
    actions = {a.text(): a for a in window._page_menu().actions() if not a.isSeparator()}
    assert set(actions) >= {"Read with AI (3)", "Approve (2)", "Upload to Wint (1)", "Delete 3 pages"}
    actions["Approve (2)"].trigger()  # pages 1 and 3 (page 2 is already approved)
    assert [p.status for p in s.pages] == [PageStatus.APPROVED] * 3
    actions = {a.text(): a for a in window._page_menu().actions() if not a.isSeparator()}
    assert "Upload to Wint (3)" in actions and not actions["Approve (0)"].isEnabled()
    actions["Delete 3 pages"].trigger()
    assert all(p.deleted for p in s.pages)
    window._restore_all()
    assert not any(p.deleted for p in s.pages)


def test_upload_progress_and_cancel(window, monkeypatch):
    s = window.session
    window._restore_all()
    for p in s.pages:
        p.status = PageStatus.APPROVED
        p.draft = s.pages[0].draft.model_copy(update={"pages": [p.index]})
    window.settings.uploads_enabled = True
    started = []

    class Client:
        def close(self):
            pass

    monkeypatch.setattr(mw.checks, "blocking", lambda issues: [])
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a: mw.QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(window, "_client", lambda allow_writes=False: Client())
    monkeypatch.setattr(window, "_run", lambda job, ok, fail: started.append((job.tag, ok)))
    window._upload_approved()
    assert window.upload_busy.isVisibleTo(window)
    assert window.upload_busy_label.text() == "Uploading 1 of 3 · page 1…"
    index, ok = started[-1]
    ok(index, 5001)
    assert window.upload_busy_bar.value() == 1 and window.upload_busy_label.text() == "Uploading 2 of 3 · page 2…"
    window._cancel_uploads()
    assert "Cancelling" in window.upload_busy_label.text() and not window.upload_cancel_btn.isEnabled()
    index, ok = started[-1]
    ok(index, 5002)  # the receipt in flight still completes and is recorded
    assert len(started) == 2 and not window.upload_busy.isVisibleTo(window)
    assert [p.status for p in s.pages] == [PageStatus.UPLOADED, PageStatus.UPLOADED, PageStatus.APPROVED]
    assert "1 not sent" in window.statusBar().currentMessage()
    assert window.upload_act.isEnabled()
