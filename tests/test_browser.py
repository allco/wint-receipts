import base64
import sys
import tempfile
from datetime import date

import pypdfium2 as pdfium
import pytest
from PySide6.QtCore import Qt

from wint_receipts.app import browser as br
from wint_receipts.core import browse
from wint_receipts.core.models import Category, ReferenceData


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()


def pdf_bytes(pages=2) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 300)
    import io
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def item(n: int, **kw) -> dict:
    return {"Id": 9000 + n, "SerialNumber": n, "DateTime": f"2026-10-{(n % 28) + 1:02d}T00:00:00", "Amount": 10.0 * n,
            "Currency": "SEK", "CategoryName": "Parkering", "PaymentMethodName": "Eget utlägg", "State": 1,
            "PaymentState": n % 2, "CreatedByPersonName": "Ada", "Persons": [{"Name": "Bob"}],
            "Attachments": [{"Id": 70 + n, "ContentType": "application/pdf", "Data": None}], **kw}


class FakeClient:
    def __init__(self, total=250):
        self.total = total
        self.calls: list[dict] = []
        self.attachment_calls: list[str] = []

    def receipts(self, **params):
        if params.get("IncludeSummary"):
            self.summary_calls = getattr(self, "summary_calls", 0) + 1
            return {"Items": None, "TotalItems": self.total,
                    "SummaryItem": {"TotalAmountSummary": [{"Type": "SEK", "Value": 1234.5}, {"Type": "EUR", "Value": 10}]}}
        self.calls.append(params)
        start = params["Page"] * params["NumPerPage"]
        n = max(0, min(params["NumPerPage"], self.total - start))
        return {"Items": [item(self.total - start - i) for i in range(n)], "TotalItems": self.total}

    def get_json(self, path, note=""):
        self.attachment_calls.append(path)
        return {"Data": base64.b64encode(pdf_bytes()).decode(), "ContentType": "application/pdf"}

    def close(self):
        pass


def test_query_params():
    q = browse.Query(date_from=date(2026, 1, 1), date_to=date(2026, 10, 24), states=[0, 5], category_id=7,
                     paid=False, amount_from=10, sort="amount", descending=False)
    p = q.params(2)
    assert p["CreatedFromDate"] == "2026-01-01" and p["CreatedToDate"] == "2026-10-24T23:59:59"
    assert p["States"] == ["Received", "SentBackToCustomer"] and p["ReceiptCategoryId"] == 7
    assert p["PaymentState"] == "Unpaid" and p["AmountFrom"] == 10 and p["AmountTo"] is None
    assert p["OrderByProperty"] == "Amount" and p["OrderByDescending"] == "false" and p["Page"] == 2
    assert browse.Query().params(0)["States"] is None and browse.Query().params(0)["PaymentState"] is None


def test_row_from_api_and_search():
    r = browse.Row.from_api(item(5, Comment="Lunch with client", Intent="collaboration discussion"))
    assert (r.serial, r.date, r.amount, r.state_name, r.paid, r.persons) == (5, "2026-10-06", 50.0, "Booked", True, ["Bob"])
    assert r.attachments == [(75, "application/pdf")]
    assert r.matches("lunch parkering") and r.matches("50.00") and not r.matches("taxi")


def test_pages_are_cached_until_refresh_or_ttl(monkeypatch):
    c = FakeClient()
    first = browse.fetch_page(c, browse.Query(), 0)
    again = browse.fetch_page(c, browse.Query(), 0)
    assert len(c.calls) == 1 and again.rows == first.rows and first.total == 250
    browse.fetch_page(c, browse.Query(), 0, use_cache=False)
    assert len(c.calls) == 2
    browse.fetch_page(c, browse.Query(sort="amount"), 0)  # another query is another cache entry
    assert len(c.calls) == 3
    monkeypatch.setattr(browse.time, "time", lambda: first.fetched_at + browse.LIST_TTL + 1)
    browse.fetch_page(c, browse.Query(), 0)
    assert len(c.calls) == 4


def test_attachments_cached_as_files():
    c = FakeClient()
    path = browse.fetch_attachment(c, 1, 2)
    assert path.suffix == ".pdf" and path.read_bytes().startswith(b"%PDF")
    assert browse.fetch_attachment(c, 1, 2) == path and len(c.attachment_calls) == 1
    if sys.platform != "win32":  # Windows has no Unix permission bits
        assert (browse.cache_dir().stat().st_mode & 0o777) == 0o700


@pytest.fixture
def window(qtbot):
    client = FakeClient()
    ref = ReferenceData(company_id=1, company_name="Test AB", categories=[Category(id=7, name="Parkering")], payment_methods=[])
    w = br.BrowserWindow(lambda: client, ref)
    qtbot.addWidget(w)
    w.client = client
    w.show()
    qtbot.waitUntil(lambda: len(w.model.rows) >= 100, timeout=5000)
    return w


def test_loads_first_page_with_indicator_and_preview(qtbot, window):
    assert window.model.rows[0].serial == 250
    assert window.client.calls[0]["OrderByProperty"] == "DateTime" and window.client.calls[0]["OrderByDescending"] == "true"
    assert "of 250 receipts" in window.count_label.text()
    qtbot.waitUntil(lambda: window.preview_stack.currentWidget() is window.image, timeout=5000)
    assert "Receipt #250" in window.details.text() and window.attachment_pick.count() == 2
    assert not window.image.rotate_left.isVisible()
    window.reload()
    assert window.busy.isVisible() and window.busy.label.text() == "Loading receipts…"
    qtbot.waitUntil(lambda: not window.busy.isVisible(), timeout=5000)


def test_scrolling_down_loads_more(qtbot, window):
    window.table.scrollToBottom()
    qtbot.waitUntil(lambda: len(window.model.rows) >= 200, timeout=5000)
    assert window.client.calls[-1]["Page"] >= 1


def test_header_click_sorts_on_the_server(qtbot, window):
    window._header_clicked(2)  # Amount
    qtbot.waitUntil(lambda: window.client.calls[-1]["OrderByProperty"] == "Amount", timeout=5000)
    assert window.client.calls[-1]["OrderByDescending"] == "true"
    window._header_clicked(2)
    qtbot.waitUntil(lambda: window.client.calls[-1]["OrderByDescending"] == "false", timeout=5000)
    before = len(window.client.calls)
    window._header_clicked(3)  # Cur: Wint can't sort by it
    assert len(window.client.calls) == before and window.query.sort == "amount"


def test_filters_go_to_the_server_and_search_stays_local(qtbot, window):
    window.category.setCurrentIndex(1)
    window.payment.setCurrentIndex(2)
    window.state.setCurrentIndex(2)
    qtbot.waitUntil(lambda: window.client.calls[-1].get("ReceiptCategoryId") == 7, timeout=5000)
    last = window.client.calls[-1]
    assert last["PaymentState"] == "Unpaid" and last["States"] == ["Received"]
    calls = len(window.client.calls)
    qtbot.waitUntil(lambda: len(window.model.rows) >= 100, timeout=5000)
    window.search.setText("2500.00")
    assert window.proxy.rowCount() == 1 and len(window.client.calls) == calls
    assert "1 match the search" in window.count_label.text()
    calls = len(window.client.calls)
    window.clear_filters()
    qtbot.waitUntil(lambda: len(window.model.rows) >= 100, timeout=5000)
    assert window.query.category_id is None and window.search.text() == ""
    assert len(window.client.calls) == calls  # the unfiltered first page is still in the cache


def test_without_credentials_explains(qtbot):
    w = br.BrowserWindow(lambda: None, None)
    qtbot.addWidget(w)
    assert "Settings" in w.table_message.text()


def test_main_window_opens_one_browser(qtbot, monkeypatch):
    from wint_receipts.app import main_window as mw
    from wint_receipts.core.config import Settings
    monkeypatch.setattr(mw.MainWindow, "_refresh_reference", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "_client", lambda self, allow_writes=False: FakeClient())
    w = mw.MainWindow(Settings())
    qtbot.addWidget(w)
    w._open_browser()
    first = w._browser
    w._open_browser()
    assert w._browser is first and first.windowTitle() == "Receipts in Wint"
    first.close()


def test_totals_for_all_or_the_selection(qtbot, window):
    from PySide6.QtCore import QItemSelectionModel
    qtbot.waitUntil(lambda: "250 receipts: 1 234.50 SEK, 10.00 EUR" in window.totals_label.text(), timeout=5000)
    sm = window.table.selectionModel()
    window.table.selectRow(0)
    sm.select(window.proxy.index(1, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert "2 selected: 4 990.00 SEK" in window.totals_label.text()  # 2500 + 2490
    window.table.selectRow(0)
    assert "250 receipts" in window.totals_label.text()
    window.search.setText("2500.00")
    assert "1 found: 2 500.00 SEK" in window.totals_label.text()


def test_summary_is_cached():
    c = FakeClient()
    first = browse.fetch_summary(c, browse.Query())
    assert first.count == 250 and first.totals == {"SEK": 1234.5, "EUR": 10}
    browse.fetch_summary(c, browse.Query())
    assert c.summary_calls == 1
    browse.fetch_summary(c, browse.Query(), use_cache=False)
    assert c.summary_calls == 2
