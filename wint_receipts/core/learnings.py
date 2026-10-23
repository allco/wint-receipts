"""What the user taught the AI: a plain text file of corrections, applied to later readings.

The file is meant to be read and edited by people. Two kinds of lines are understood:

    category: "EasyPark AB" (org 556626-7893) = "Parkering" [86914]
    supplier: "EASYPARK" = "EasyPark AB"

Category rules are applied by the app itself after each AI reading, so they always win. Supplier
rules rename what the AI read. Every other non-comment line is free text that goes to the AI as a
hint, e.g. `Receipts from Mr Wok are Representation.` Lines starting with `#` are comments.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HEADER = """\
# Wint receipts: AI learnings
#
# The app adds a line here when you correct the AI before approving a receipt, and uses these
# lines the next time it reads a receipt. Edit or delete lines freely.
#
#   category: "<supplier>" (org <org number>) = "<category>" [<category id>]
#       → receipts from that supplier get that category, whatever the AI suggests
#   supplier: "<as the AI read it>" = "<correct name>"
#       → the supplier name is corrected
#   any other line → passed to the AI as a hint, e.g.: Receipts from Mr Wok are Representation.
"""

_CATEGORY = re.compile(
    r'^category:\s*"(?P<supplier>[^"]*)"\s*(?:\(org\s*(?P<org>[^)]*)\))?\s*=\s*"(?P<name>[^"]*)"\s*\[(?P<id>\d+)\]')
_SUPPLIER = re.compile(r'^supplier:\s*"(?P<read>[^"]*)"\s*=\s*"(?P<correct>[^"]*)"')
_COMPANY_SUFFIX = re.compile(r"\b(ab|aktiebolag|hb|kb|ltd|inc|oy|as|a/s|gmbh)\b\.?", re.I)

_lock = threading.Lock()


def supplier_key(name: str | None) -> str:
    """Comparable form of a supplier name: case, punctuation and company suffixes ignored."""
    s = _COMPANY_SUFFIX.sub(" ", (name or "").lower())
    return re.sub(r"[^0-9a-zåäöéü]+", "", s)


def org_key(org: str | None) -> str:
    return re.sub(r"\D", "", org or "")


@dataclass
class CategoryRule:
    supplier: str
    org: str
    category_id: int
    category_name: str


@dataclass
class Applied:
    supplier_name: str | None
    category_id: int | None
    notes: list[str] = field(default_factory=list)


class Learnings:
    def __init__(self, path: Path):
        self.path = path
        self.lines: list[str] = []
        self.load()

    # ---- file

    def load(self) -> None:
        try:
            self.lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            self.lines = []

    def save(self) -> None:
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            body = self.lines if any(l.startswith("# Wint receipts") for l in self.lines) else \
                HEADER.splitlines() + [""] + self.lines
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
            tmp.replace(self.path)
        self.load()

    # ---- parsed views

    def category_rules(self) -> list[CategoryRule]:
        rules = []
        for line in self.lines:
            if m := _CATEGORY.match(line.strip()):
                rules.append(CategoryRule(m["supplier"], m["org"] or "", int(m["id"]), m["name"]))
        return rules

    def supplier_aliases(self) -> dict[str, str]:
        return {supplier_key(m["read"]): m["correct"] for line in self.lines
                if (m := _SUPPLIER.match(line.strip())) and m["correct"]}

    def hints(self) -> list[str]:
        return [l.strip() for l in self.lines
                if l.strip() and not l.lstrip().startswith("#")
                and not _CATEGORY.match(l.strip()) and not _SUPPLIER.match(l.strip())]

    def prompt_section(self) -> str:
        """Text for the AI prompt: the user's corrections and hints, most recent last."""
        out = [f'- "{r.supplier}" → category {r.category_id} ("{r.category_name}")' for r in self.category_rules()]
        out += [f'- the supplier read as "{k}" is really "{v}"' for k, v in self.supplier_aliases().items()]
        out += [f"- {h}" for h in self.hints()]
        return "\n".join(out[-200:])

    # ---- using them

    def apply(self, supplier_name: str | None, org_number: str | None, category_id: int | None) -> Applied:
        """Correct an AI reading with what the user taught before."""
        result = Applied(supplier_name, category_id)
        alias = self.supplier_aliases().get(supplier_key(supplier_name))
        if alias and alias != supplier_name:
            result.supplier_name = alias
            result.notes.append(f'Supplier name "{supplier_name}" corrected to "{alias}" from your earlier correction.')
        key, org = supplier_key(result.supplier_name), org_key(org_number)
        for rule in reversed(self.category_rules()):  # the latest rule wins
            if (org and org_key(rule.org) == org) or (key and supplier_key(rule.supplier) == key):
                if rule.category_id != category_id:
                    result.notes.append(f'Category set to "{rule.category_name}" from your earlier correction '
                                        f'for {rule.supplier}.')
                result.category_id = rule.category_id
                break
        return result

    # ---- learning

    def learn_category(self, supplier: str, org: str | None, category_id: int, category_name: str) -> str:
        line = f'category: "{supplier}"' + (f" (org {org})" if org else "") + \
               f' = "{category_name}" [{category_id}]   # learned {date.today().isoformat()}'
        key, okey = supplier_key(supplier), org_key(org)
        self._replace_or_append(line, lambda l: (m := _CATEGORY.match(l.strip())) is not None and (
            (okey and org_key(m["org"]) == okey) or supplier_key(m["supplier"]) == key))
        return line

    def learn_supplier(self, read: str, correct: str) -> str:
        line = f'supplier: "{read}" = "{correct}"   # learned {date.today().isoformat()}'
        key = supplier_key(read)
        self._replace_or_append(line, lambda l: (m := _SUPPLIER.match(l.strip())) is not None
                                and supplier_key(m["read"]) == key)
        return line

    def _replace_or_append(self, line: str, same) -> None:
        self.load()  # pick up edits made in a text editor meanwhile
        self.lines = [l for l in self.lines if not same(l)] + [line]
        self.save()
