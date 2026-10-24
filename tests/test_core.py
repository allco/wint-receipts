import base64
import io
import json
from datetime import date

import httpx
import pypdfium2 as pdfium
import pytest

from wint_receipts.core import checks, config, pdf, recognize, session, upload
from wint_receipts.core.config import Credentials, Settings
from wint_receipts.core.models import (
    Category, PageKind, PageState, PageStatus, ReceiptDraft, Recognition, ReferenceData, VatLine,
)
from wint_receipts.core.wint import Attachment, WintClient, WriteNotAllowed, receipt_post_body


def page_widths(data: bytes) -> list[float]:
    doc = pdfium.PdfDocument(io.BytesIO(data))
    try:
        return [doc[i].get_width() for i in range(len(doc))]
    finally:
        doc.close()


# ---- pdf

def test_page_count_and_render(sample_pdf):
    assert pdf.page_count(sample_pdf) == 3
    png = pdf.render_png(sample_pdf, 1, dpi=72)
    assert png.startswith(b"\x89PNG")


def test_extract_single_and_merged_pages(sample_pdf):
    assert page_widths(pdf.extract_pages(sample_pdf, [1])) == [300]
    assert page_widths(pdf.extract_pages(sample_pdf, [0, 2])) == [200, 400]
    with pytest.raises(ValueError):
        pdf.extract_pages(sample_pdf, [])


# ---- recognition

CLI_OK = {
    "type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.031,
    "structured_output": {
        "page_kind": "receipt", "date": "2026-10-20", "total": 44.85, "currency": "SEK",
        "supplier_name": "EasyPark", "supplier_org_number": None,
        "vat": [{"rate": 25, "net": 35.88, "amount": 8.97}], "description": "Parkering",
        "category_id": 7, "payment_hint": "card", "uncertain_fields": [], "notes": "",
    },
}


def test_parse_output_structured():
    r = recognize.parse_output(json.dumps(CLI_OK))
    assert r.recognition.total == 44.85 and r.recognition.page_kind is PageKind.RECEIPT
    assert r.cost_usd == pytest.approx(0.031)


def test_parse_output_falls_back_to_result_text():
    data = {**CLI_OK, "structured_output": None, "result": json.dumps(CLI_OK["structured_output"])}
    assert recognize.parse_output(json.dumps(data)).recognition.supplier_name == "EasyPark"


@pytest.mark.parametrize("stdout", ["not json", json.dumps({"subtype": "error_max_turns", "is_error": True})])
def test_parse_output_errors(stdout):
    with pytest.raises(recognize.RecognitionError):
        recognize.parse_output(stdout)


def test_command_restricts_tools_and_lists_categories():
    prompt = recognize.build_prompt("page.png", [Category(id=7, name="Parkering")])
    assert "7: Parkering" in prompt and "page.png" in prompt
    cmd = recognize.build_command("claude", "sonnet")
    assert "-p" in cmd and prompt not in cmd  # the prompt goes to stdin
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert "--restricted" in cmd and "--no-session-persistence" in cmd
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == recognize.RECOGNITION_SCHEMA


def test_schema_and_model_agree():
    assert set(recognize.RECOGNITION_SCHEMA["properties"]) == set(Recognition.model_fields)


def test_recognize_png_runs_cli(monkeypatch):
    seen = {}

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, cwd, **kw):
            from pathlib import Path
            assert (Path(cwd) / "page.png").read_bytes() == b"PNG"
            seen["cwd"] = cwd

        def communicate(self, prompt=None, timeout=None):
            assert "page.png" in prompt  # prompt passed on stdin
            assert recognize._running  # registered while it runs, so quitting can stop it
            return json.dumps(CLI_OK), ""

    monkeypatch.setattr(recognize.subprocess, "Popen", FakeProc)
    assert recognize.recognize_png(b"PNG", []).recognition.total == 44.85
    assert not recognize._running


def test_cancel_all_stops_a_running_reading(tmp_path, monkeypatch):
    import sys
    import threading
    import time
    script = tmp_path / "slow_claude.py"
    script.write_text("import time; time.sleep(60)")
    monkeypatch.setattr(recognize, "build_command", lambda path, model: [sys.executable, str(script)])
    errors = []
    t = threading.Thread(target=lambda: errors.append(_try(lambda: recognize.recognize_png(b"PNG", []))))
    t.start()
    for _ in range(100):
        if recognize._running:
            break
        time.sleep(0.05)
    recognize.cancel_all()
    t.join(10)
    assert not t.is_alive() and isinstance(errors[0], recognize.RecognitionError) and "stopped" in str(errors[0])


def _try(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return e


# ---- checks

REF = ReferenceData(company_id=1, company_name="Co", categories=[Category(id=7, name="Parkering")],
                    payment_methods=[], lock_date=date(2026, 6, 30))


def good_draft(**kw) -> ReceiptDraft:
    base = dict(date=date(2026, 10, 20), amount=44.85, currency="SEK", category_id=7, payment_method_id=1,
                vat=[VatLine(rate=25, net=35.88, amount=8.97)], pages=[0])
    return ReceiptDraft(**{**base, **kw})


def test_checks_pass_for_good_draft():
    assert checks.check(good_draft(), REF, today=date(2026, 10, 21)) == []


@pytest.mark.parametrize("kw, field", [
    ({"date": None}, "date"),
    ({"date": date(2026, 11, 1)}, "date"),
    ({"amount": None}, "amount"),
    ({"amount": -3}, "amount"),
    ({"currency": "kr"}, "currency"),
    ({"category_id": None}, "category"),
    ({"category_id": 99}, "category"),
    ({"payment_method_id": None}, "payment_method"),
    ({"pages": []}, "pages"),
])
def test_checks_errors(kw, field):
    issues = checks.check(good_draft(**kw), REF, today=date(2026, 10, 21))
    assert checks.blocking(issues) and field in {i.field for i in issues}


def test_checks_warnings():
    d = good_draft(amount=50.0, date=date(2026, 5, 1), vat=[VatLine(rate=20, net=40, amount=10)])
    rec = Recognition(page_kind=PageKind.RECEIPT, uncertain_fields=["date", "supplier_name"])
    issues = checks.check(d, REF, rec, today=date(2026, 10, 21))
    assert not checks.blocking(issues)
    msgs = " ".join(i.message for i in issues)
    assert "locked period" in msgs and "Unusual VAT rate" in msgs and "wasn't sure about the date" in msgs
    assert "supplier" not in msgs  # not on the form, so no warning about it


def test_checks_vat_sum_mismatch():
    issues = checks.check(good_draft(amount=50.0), REF, today=date(2026, 10, 21))
    assert any("Net + VAT" in i.message for i in issues)


# ---- wint client

def make_client(handler, tmp_path, allow_writes=False):
    log = tmp_path / "requests.log"
    client = WintClient(Credentials("10001", "secret-token"), log_path=log, allow_writes=allow_writes,
                        transport=httpx.MockTransport(handler))
    return client, log


def log_lines(log):
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]


def test_get_is_logged_without_credentials(tmp_path):
    def handler(req):
        assert req.headers["authorization"].startswith("Basic ")
        assert req.headers["x-wint-capabilities"] == "ReceiptPaymentMethodNullability"
        return httpx.Response(200, json={"Id": 10001}, headers={"x-rate-limit-remaining": "998"})

    client, log = make_client(handler, tmp_path)
    assert client.company()["Id"] == 10001
    (entry,) = log_lines(log)
    assert entry["method"] == "GET" and entry["status"] == 200 and entry["rate_limit_remaining"] == 998
    assert "secret-token" not in log.read_text(encoding="utf-8")


def test_writes_refused_by_default_and_logged(tmp_path):
    client, log = make_client(lambda req: pytest.fail("must not send"), tmp_path)
    with pytest.raises(WriteNotAllowed):
        client.create_receipt(good_draft(), [Attachment("a.jpg", "image/jpeg", b"JPG")], "cid")
    (entry,) = log_lines(log)
    assert entry["method"] == "POST" and entry["status"] is None and "refused" in entry["result"]


def test_http_error_is_logged(tmp_path):
    client, log = make_client(lambda req: httpx.Response(401, text=""), tmp_path)
    with pytest.raises(Exception):
        client.company()
    assert log_lines(log)[0]["status"] == 401


def test_receipts_query_repeats_array_keys(tmp_path):
    def handler(req):
        assert req.url.params.get_list("States") == ["Received", "Booked"]
        return httpx.Response(200, json={"Items": []})

    client, _ = make_client(handler, tmp_path)
    client.receipts(States=["Received", "Booked"], Page=1)


def test_reference_data_collects_payment_methods_from_receipts(tmp_path):
    def handler(req):
        if req.url.path == "/api/Auth":
            return httpx.Response(200, json={"Id": 1, "Name": "Co", "ReceiptCategories": [{"Id": 7, "Name": "Parkering"}],
                                             "ReceiptPaymentMethods": {}, "LockDate": "2026-06-30T00:00:00"})
        if req.url.path == "/api/Receipt/AllReceiptPersons":
            return httpx.Response(200, json=[{"Id": 1, "Name": "Anna ", "Company": "A AB"},
                                             {"Id": 2, "Name": "Bo", "Company": None}, {"Id": 3, "Name": "Cecilia"}])
        if req.url.path == "/api/Receipt/CommonReceiptPersons":
            return httpx.Response(200, json=[{"Id": 3, "Name": "Cecilia"}, {"Id": 2, "Name": "Bo"}])
        return httpx.Response(200, json={"Items": [
            {"PaymentMethodId": 16978, "PaymentMethodName": "Eget utlägg", "PaymentMethodType": 2,
             "CreatedByPersonName": "Ada Lovelace", "ReceiptCategoryId": 7},
            {"PaymentMethodId": 16978, "PaymentMethodName": "Eget utlägg", "PaymentMethodType": 2,
             "CreatedByPersonName": "Ada Lovelace", "ReceiptCategoryId": 7},
            {"PaymentMethodId": 16978, "ReceiptCategoryId": 99},
        ]})

    client, _ = make_client(handler, tmp_path)
    ref = client.reference_data()
    assert [m.id for m in ref.payment_methods] == [16978] and ref.payment_methods[0].type == 2
    assert ref.lock_date == date(2026, 6, 30) and ref.categories[0].name == "Parkering"
    assert [p.name for p in ref.persons] == ["Cecilia", "Bo", "Anna"]  # most used first, in Wint's order
    assert ref.common_person_ids == [3, 2] and ref.persons[2].company == "A AB"
    assert ref.me.name == "Ada Lovelace" and ref.me.company == "Co" and ref.me.id == 0
    assert ref.common_category_ids == [7]  # used twice; 99 isn't a receipt category of the company


def test_receipt_post_body():
    body = receipt_post_body(good_draft(supplier_name="EasyPark"), [Attachment("scans-p1.pdf", "application/pdf", b"%PDF-1.7")], "cid-1")
    assert "SupplierName" not in body and "Comment" not in body  # neither is sent to Wint
    assert body["DateTime"] == "2026-10-20T00:00:00" and body["Amount"] == 44.85
    assert body["ReceiptCategoryId"] == 7 and body["PaymentMethodId"] == 1 and body["ClientId"] == "cid-1"
    att = body["Attachments"][0]
    assert base64.b64decode(att["Data"]) == b"%PDF-1.7" and att["ContentType"] == "application/pdf"


# ---- upload

def approved_page(index=1, pages=None) -> PageState:
    return PageState(index=index, status=PageStatus.APPROVED, draft=good_draft(pages=pages or [index]))


def test_upload_sends_only_its_pages(tmp_path, sample_pdf):
    sent = {}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"Items": []})
        sent["body"] = json.loads(req.content)
        return httpx.Response(200, json=555)

    client, _ = make_client(handler, tmp_path, allow_writes=True)
    assert upload.upload_page(client, sample_pdf, approved_page(1, [1, 2]), fmt="pdf") == 555
    att = sent["body"]["Attachments"][0]
    assert page_widths(base64.b64decode(att["Data"])) == [300, 400]
    assert att["FileName"] == "scans-p2-3.pdf"
    from PIL import Image
    assert upload.upload_page(client, sample_pdf, approved_page(1, [1, 2])) == 555  # default: JPEG per page
    atts = sent["body"]["Attachments"]
    assert [a["FileName"] for a in atts] == ["scans-p2.jpg", "scans-p3.jpg"]
    assert all(a["ContentType"] == "image/jpeg" for a in atts)
    sizes = [Image.open(io.BytesIO(base64.b64decode(a["Data"]))).size for a in atts]
    assert sizes[0][0] / sizes[0][1] == pytest.approx(300 / 500, rel=0.02)


def test_upload_is_idempotent_by_client_id(tmp_path, sample_pdf):
    def handler(req):
        assert req.method == "GET", "must not create a duplicate"
        return httpx.Response(200, json={"Items": [{"Id": 42}]})

    client, _ = make_client(handler, tmp_path, allow_writes=True)
    assert upload.upload_page(client, sample_pdf, approved_page()) == 42


def test_upload_requires_approval(tmp_path, sample_pdf):
    client, _ = make_client(lambda req: pytest.fail("no request"), tmp_path, allow_writes=True)
    p = approved_page()
    p.status = PageStatus.NEEDS_REVIEW
    with pytest.raises(ValueError):
        upload.upload_page(client, sample_pdf, p)


# ---- session

def test_session_roundtrip_and_transient_states(sample_pdf):
    s = session.open_session(sample_pdf)
    assert len(s.pages) == 3
    s.pages[0].status = PageStatus.RECOGNIZING
    s.pages[1].status = PageStatus.UPLOADING
    s.pages[2].draft = good_draft(pages=[2])
    session.save_session(s)
    again = session.open_session(sample_pdf)
    assert [p.status for p in again.pages] == [PageStatus.NEW, PageStatus.APPROVED, PageStatus.NEW]
    assert again.pages[2].draft.amount == 44.85
    assert again.pages[0].client_id == s.pages[0].client_id


def test_session_resets_when_pdf_changes(sample_pdf):
    s = session.open_session(sample_pdf)
    s.pages[0].status = PageStatus.APPROVED
    session.save_session(s)
    doc = pdfium.PdfDocument.new()
    doc.new_page(100, 100)
    doc.save(str(sample_pdf))
    doc.close()
    fresh = session.open_session(sample_pdf)
    assert len(fresh.pages) == 1 and fresh.pages[0].status is PageStatus.NEW


# ---- config

def test_credentials_prefill_from_env(monkeypatch):
    monkeypatch.setenv("WINT_USER", "10001")
    monkeypatch.setenv("WINT_TOKEN", "env-token")
    s = Settings.load()
    assert s.wint_user == "10001"
    assert config.resolve_credentials(s) == Credentials("10001", "env-token")


def test_keyring_token_wins_over_env(monkeypatch, isolated_env):
    monkeypatch.setenv("WINT_USER", "10001")
    monkeypatch.setenv("WINT_TOKEN", "env-token")
    assert config.save_token("10001", "saved-token")
    assert config.resolve_credentials(Settings(wint_user="10001")).token == "saved-token"


def test_env_token_not_used_for_other_user(monkeypatch):
    monkeypatch.setenv("WINT_USER", "1")
    monkeypatch.setenv("WINT_TOKEN", "env-token")
    assert config.resolve_credentials(Settings(wint_user="2")).token == ""


def test_settings_save_load():
    Settings(wint_user="5", claude_model="opus", uploads_enabled=True).save()
    s = Settings.load()
    assert (s.wint_user, s.claude_model, s.uploads_enabled) == ("5", "opus", True)


def test_parse_output_keeps_usage_and_turns():
    data = {**CLI_OK, "num_turns": 4, "usage": {"input_tokens": 1200, "output_tokens": 90, "server_tool_use": {}}}
    r = recognize.parse_output(json.dumps(data))
    assert r.num_turns == 4 and r.usage == {"input_tokens": 1200, "output_tokens": 90}


def test_changed_fields():
    from wint_receipts.core import reclog
    rec = Recognition(page_kind=PageKind.RECEIPT, date="2026-10-20", total=44.85, currency="sek",
                      supplier_name="EasyPark", category_id=7)
    same = good_draft(supplier_name="EasyPark")
    assert reclog.changed_fields(rec, same) == []
    edited = good_draft(supplier_name="EasyPark AB", amount=45.0, date=date(2026, 10, 19), category_id=8)
    assert reclog.changed_fields(rec, edited) == ["date", "total", "category_id"]


def test_logs_enabled_by_default_and_can_be_turned_off(tmp_path):
    s = Settings()
    assert s.request_log_path() == tmp_path / "cache" / "wint-receipts" / "wint-requests.log"
    assert s.recognition_log_path() == tmp_path / "cache" / "wint-receipts" / "recognition.log"
    off = Settings(request_log_enabled=False, recognition_log_enabled=False)
    assert off.request_log_path() is None and off.recognition_log_path() is None


@pytest.mark.parametrize("platform, expected", [
    ("linux", ".config/wint-receipts"),
    ("darwin", "Library/Application Support/wint-receipts"),
    ("win32", "Roaming/wint-receipts"),
])
def test_config_dir_per_platform(monkeypatch, tmp_path, platform, expected):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setattr(config.sys, "platform", platform)
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path)
    assert config.config_dir().as_posix().endswith(expected)


def test_logs_go_to_cache_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path)
    assert config.default_log_dir() == tmp_path / ".cache" / "wint-receipts"


def test_render_and_extract_respect_rotation(sample_pdf):
    from PIL import Image
    upright = Image.open(io.BytesIO(pdf.render_png(sample_pdf, 0, dpi=72)))
    turned = Image.open(io.BytesIO(pdf.render_png(sample_pdf, 0, dpi=72, rotation=90)))
    assert (turned.width, turned.height) == (upright.height, upright.width)
    data = pdf.extract_pages(sample_pdf, [0, 1], {1: 90})
    doc = pdfium.PdfDocument(io.BytesIO(data))
    assert [doc[i].get_rotation() for i in range(2)] == [0, 90]
    doc.close()


def test_upload_attaches_rotated_page(tmp_path, sample_pdf):
    sent = {}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"Items": []})
        sent["body"] = json.loads(req.content)
        return httpx.Response(200, json=7)

    client, _ = make_client(handler, tmp_path, allow_writes=True)
    upload.upload_page(client, sample_pdf, approved_page(1), {1: 270}, fmt="pdf")
    doc = pdfium.PdfDocument(io.BytesIO(base64.b64decode(sent["body"]["Attachments"][0]["Data"])))
    assert doc[0].get_rotation() == 270
    doc.close()
    from PIL import Image
    upload.upload_page(client, sample_pdf, approved_page(1), {1: 270})  # JPEG is rendered turned
    w, h = Image.open(io.BytesIO(base64.b64decode(sent["body"]["Attachments"][0]["Data"]))).size
    assert w > h  # 300×500 pt page turned a quarter → landscape


def test_render_max_side_caps_long_edge(sample_pdf):
    from PIL import Image
    im = Image.open(io.BytesIO(pdf.render_png(sample_pdf, 2, dpi=300, max_side=100)))  # page 3 is 400×500 pt
    assert max(im.size) == 100



def test_representation_needs_people_and_sends_them():
    from wint_receipts.core.models import Person
    ref = REF.model_copy(update={"categories": [Category(id=8, name="Representation")]})
    cecilia, bo = Person(id=3, name="Cecilia", company="C AB"), Person(id=2, name="Bo")
    for people in ([], [cecilia]):  # fewer than 2 participants blocks approval
        issues = checks.check(good_draft(category_id=8, persons=people), ref, today=date(2026, 10, 21))
        assert checks.blocking(issues) and any(i.field == "persons" and "at least 2" in i.message for i in issues)
    two = good_draft(category_id=8, persons=[cecilia, bo])
    assert not any(i.field == "persons" for i in checks.check(two, ref, today=date(2026, 10, 21)))
    body = receipt_post_body(two, [], "cid")
    assert body["Persons"] == [{"Id": 3, "Name": "Cecilia", "Company": "C AB"}, {"Id": 2, "Name": "Bo", "Company": ""}]



def test_representation_needs_reason_sent_as_intent():
    from wint_receipts.core.models import Person
    ref = REF.model_copy(update={"categories": [Category(id=8, name="Representation")]})
    people = [Person(id=0, name="Me"), Person(id=3, name="Cecilia")]
    no_reason = good_draft(category_id=8, persons=people)
    assert any(i.field == "intent" for i in checks.check(no_reason, ref, today=date(2026, 10, 21)))
    ok = good_draft(category_id=8, persons=people, intent="collaboration discussion")
    assert not checks.blocking(checks.check(ok, ref, today=date(2026, 10, 21)))
    assert receipt_post_body(ok, [], "cid")["Intent"] == "collaboration discussion"
    assert receipt_post_body(good_draft(), [], "cid")["Intent"] is None


def test_address_book_writes(tmp_path):
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(200, json=901 if req.method == "POST" else None)

    client, log = make_client(handler, tmp_path, allow_writes=True)
    assert client.add_person("Ada", "Analytical AB") == 901
    assert client.replace_person(55, "Ada L", "Analytical AB") == 901
    assert calls == [
        ("POST", "/api/Receipt/AddReceiptPerson", {"Id": 0, "Name": "Ada", "Company": "Analytical AB"}),
        ("POST", "/api/Receipt/AddReceiptPerson", {"Id": 0, "Name": "Ada L", "Company": "Analytical AB"}),
        ("DELETE", "/api/Receipt/RemoveReceiptPerson/55", None),
    ]
    assert [e["method"] for e in log_lines(log)] == ["POST", "POST", "DELETE"]


def test_address_book_writes_refused_without_permission(tmp_path):
    client, _ = make_client(lambda req: pytest.fail("must not send"), tmp_path)
    with pytest.raises(WriteNotAllowed):
        client.add_person("Ada", "")
    with pytest.raises(WriteNotAllowed):
        client.remove_person(1)


def test_upload_stops_on_a_similar_receipt_in_wint(tmp_path, sample_pdf):
    def handler(req):
        if req.method == "GET" and "ClientId" in str(req.url):
            return httpx.Response(200, json={"Items": []})
        if req.method == "GET":
            return httpx.Response(200, json={"Items": [{"Id": 77, "DateTime": "2026-10-20T00:00:00", "Amount": 44.85}]})
        return httpx.Response(200, json=901)

    client, _ = make_client(handler, tmp_path, allow_writes=True)
    with pytest.raises(upload.DuplicateSuspected) as e:
        upload.upload_page(client, sample_pdf, approved_page(1))
    assert e.value.receipts[0]["Id"] == 77
    assert upload.upload_page(client, sample_pdf, approved_page(1), allow_similar=True) == 901


def test_ledger_records_and_finds_uploads(tmp_path):
    from wint_receipts.core.ledger import Ledger
    lg = Ledger(tmp_path / "uploads.jsonl")
    assert lg.entries() == [] and lg.for_page("abc", 0) is None
    lg.add(pdf_sha256="abc", pdf="/x.pdf", page=0, client_id="c1", wint_receipt_id=10, date="2026-10-18",
           amount=660.0, currency="SEK", supplier="Mr Wok", org="556979-1303")
    (tmp_path / "uploads.jsonl").open("a").write("not json\n")  # a damaged line doesn't hide the others
    assert lg.for_page("abc", 0).wint_receipt_id == 10
    assert [e.wint_receipt_id for e in lg.same_receipt("2026-10-18", 660.0)] == [10]
    assert lg.same_receipt("2026-10-18", 660.0, exclude_client_id="c1") == []
