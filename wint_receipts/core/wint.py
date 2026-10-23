"""Wint API client. Reads freely; every write needs allow_writes=True on the client.

Each request is appended as one JSON line to the request log, in the same format as bin/wint.
See docs/wintapi.md.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import Credentials
from .models import ME_ID, Category, PaymentMethod, Person, ReceiptDraft, ReferenceData

CAPABILITIES = {"X-Wint-Capabilities": "ReceiptPaymentMethodNullability"}


class WintError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class WriteNotAllowed(WintError):
    pass


class WintClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        base_url: str = "https://api.wint.se",
        log_path: Path | None = None,
        allow_writes: bool = False,
        transport: httpx.BaseTransport | None = None,
    ):
        self.allow_writes = allow_writes
        self.log_path = log_path
        self._log_lock = threading.Lock()
        self._http = httpx.Client(
            base_url=base_url,
            auth=(credentials.user, credentials.token),
            headers={"Accept": "application/json", **CAPABILITIES},
            timeout=60,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    # ---- plumbing

    def _log(self, entry: dict[str, Any]) -> None:
        if not self.log_path:
            return
        line = json.dumps(entry, ensure_ascii=False)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_lock, self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def request(self, method: str, path: str, *, note: str = "", json_body: Any = None) -> httpx.Response:
        method = method.upper()
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        url = str(self._http.base_url.join(path))
        if method != "GET" and not self.allow_writes:
            self._log({"ts": ts, "method": method, "url": url, "status": None,
                       "result": "refused (write not allowed)", "note": note})
            raise WriteNotAllowed(f"{method} {path} refused: writes are disabled")
        start = time.monotonic()
        try:
            resp = self._http.request(method, path, json=json_body)
        except httpx.HTTPError as e:
            self._log({"ts": ts, "method": method, "url": url, "status": None,
                       "result": f"http error: {e}", "note": note})
            raise WintError(f"{method} {path}: {e}") from e
        ok = resp.is_success
        remaining = resp.headers.get("x-rate-limit-remaining")
        self._log({
            "ts": ts, "method": method, "url": url, "status": resp.status_code,
            "bytes": len(resp.content), "seconds": round(time.monotonic() - start, 3),
            "rate_limit_remaining": int(remaining) if remaining and remaining.isdigit() else None,
            "result": "ok" if ok else f"error: {resp.text[:300]}", "note": note,
        })
        if not ok:
            raise WintError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}", resp.status_code)
        return resp

    def get_json(self, path: str, note: str = "") -> Any:
        resp = self.request("GET", path, note=note)
        return resp.json() if resp.content else None

    # ---- reads

    def company(self) -> dict:
        return self.get_json("/api/Auth", note="load company")

    def receipts(self, **params: Any) -> dict:
        """GET /api/Receipt with filter params; arrays become repeated keys."""
        query = httpx.QueryParams([(k, str(x)) for k, v in params.items() if v is not None
                                   for x in (v if isinstance(v, (list, tuple)) else [v])])
        path = "/api/Receipt" + (f"?{query}" if query else "")
        return self.get_json(path, note="list receipts")

    def find_by_client_id(self, client_id: str) -> list[dict]:
        return (self.receipts(ClientId=client_id, NumPerPage=10) or {}).get("Items") or []

    def find_similar(self, day: date, amount: float) -> list[dict]:
        start = datetime.combine(day, datetime.min.time())
        data = self.receipts(AmountFrom=amount - 0.01, AmountTo=amount + 0.01, NumPerPage=50)
        return [r for r in (data or {}).get("Items") or [] if str(r.get("DateTime", "")).startswith(start.date().isoformat())]

    def reference_data(self) -> ReferenceData:
        c = self.company()
        categories = [Category(id=x["Id"], name=x["Name"]) for x in c.get("ReceiptCategories") or []]
        # The company-level map can be empty, so also collect methods seen on recent receipts.
        methods: dict[int, PaymentMethod] = {}
        for person_methods in (c.get("ReceiptPaymentMethods") or {}).values():
            for m in person_methods or []:
                if m.get("IsActive", True):
                    methods[m["Id"]] = PaymentMethod(id=m["Id"], name=m.get("Name") or str(m["Id"]), type=_enum_int(m.get("Type")))
        recent = self.receipts(NumPerPage=100, OrderByProperty="DateTime", OrderByDescending="true")
        creators: dict[str, int] = {}
        for r in (recent or {}).get("Items") or []:
            if name := (r.get("CreatedByPersonName") or "").strip():
                creators[name] = creators.get(name, 0) + 1
            mid = r.get("PaymentMethodId")
            if mid and mid not in methods:
                methods[mid] = PaymentMethod(id=mid, name=r.get("PaymentMethodName") or str(mid), type=_enum_int(r.get("PaymentMethodType")))
        lock = c.get("LockDate")
        everyone = [_person(p) for p in self.get_json("/api/Receipt/AllReceiptPersons", note="load receipt persons") or []]
        common = [_person(p) for p in self.get_json("/api/Receipt/CommonReceiptPersons", note="load common receipt persons") or []]
        common_ids = [p.id for p in common]
        known = {p.id for p in everyone}
        everyone += [p for p in common if p.id not in known]
        return ReferenceData(
            company_id=c["Id"], company_name=c.get("Name") or "",
            categories=sorted(categories, key=lambda x: x.name.lower()),
            payment_methods=sorted(methods.values(), key=lambda x: x.name.lower()),
            lock_date=date.fromisoformat(lock[:10]) if lock else None,
            no_vat=bool(c.get("NoVat")),
            persons=sorted(everyone, key=lambda p: (p.id not in common_ids,
                                                    common_ids.index(p.id) if p.id in common_ids else 0,
                                                    p.name.lower())),
            common_person_ids=common_ids,
            # Whoever creates the company's receipts most often: the account holder.
            me=Person(id=ME_ID, name=max(creators, key=creators.get), company=c.get("Name") or "") if creators else None,
        )

    # ---- writes (UNTESTED against the live API — see docs/wintapi.md)

    def create_receipt(self, draft: ReceiptDraft, attachment_pdf: bytes, client_id: str, file_name: str) -> int:
        body = receipt_post_body(draft, attachment_pdf, client_id, file_name)
        resp = self.request("POST", "/api/Receipt", json_body=body, note=f"create receipt client_id={client_id}")
        return int(resp.json())


def _person(p: dict) -> Person:
    return Person(id=p["Id"], name=(p.get("Name") or "").strip(), company=(p.get("Company") or "").strip())


def _enum_int(v: Any) -> int | None:
    return v if isinstance(v, int) else None


def receipt_post_body(draft: ReceiptDraft, attachment_pdf: bytes, client_id: str, file_name: str) -> dict:
    """ReceiptPost JSON. Field names are PascalCase as in the v1 spec."""
    if draft.date is None or draft.amount is None:
        raise ValueError("date and amount are required")
    return {
        "ClientId": client_id,
        "DateTime": datetime.combine(draft.date, datetime.min.time()).isoformat(),
        "Amount": round(draft.amount, 2),
        "Currency": draft.currency,
        "ReceiptCategoryId": draft.category_id,
        "PaymentMethodId": draft.payment_method_id,
        "Dimensions": [],
        # Participants (representation): ReceiptPost.Persons, "People the receipt concerns"; untested on create.
        "Persons": [{"Id": p.id, "Name": p.name, "Company": p.company} for p in draft.persons],
        "Intent": draft.intent or None,
        "Attachments": [{
            "FileName": file_name,
            "ContentType": "application/pdf",
            "Data": base64.b64encode(attachment_pdf).decode("ascii"),
        }],
    }
