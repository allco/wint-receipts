"""Receipt recognition by running the claude CLI on one rendered page image."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .models import Category, Recognition

_NUM_OR_NULL = {"type": ["number", "null"]}
_STR_OR_NULL = {"type": ["string", "null"]}

RECOGNITION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "page_kind": {"type": "string", "enum": ["receipt", "continuation", "blank", "back_side", "not_a_receipt"]},
        "date": {**_STR_OR_NULL, "description": "Purchase date, YYYY-MM-DD"},
        "total": {**_NUM_OR_NULL, "description": "Total amount paid incl. VAT"},
        "currency": {**_STR_OR_NULL, "description": "ISO 4217 code, e.g. SEK"},
        "supplier_name": _STR_OR_NULL,
        "supplier_org_number": _STR_OR_NULL,
        "vat": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"rate": {"type": "number"}, "net": _NUM_OR_NULL, "amount": {"type": "number"}},
                "required": ["rate", "net", "amount"],
                "additionalProperties": False,
            },
        },
        "category_id": {"type": ["integer", "null"]},
        "payment_hint": {"type": "string", "enum": ["card", "cash", "swish", "invoice", "unknown"]},
        "uncertain_fields": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
        "rotation_needed": {"type": "integer", "enum": [0, 90, 180, 270],
                            "description": "Degrees clockwise to turn the image so its text reads upright"},
    },
    "required": [
        "page_kind", "date", "total", "currency", "supplier_name", "supplier_org_number", "vat",
        "category_id", "payment_hint", "uncertain_fields", "notes", "rotation_needed",
    ],
    "additionalProperties": False,
}

PROMPT = """\
Read the image file {image} in the current directory. It is one page of a PDF of scanned receipts
(usually Swedish). Extract the fields in the JSON schema.

Rules:
- page_kind: "receipt" for a receipt or invoice; "continuation" if the page clearly continues the
  receipt on the previous page (no header, starts mid-list); "back_side" for the back of a receipt;
  "blank" for an empty page; otherwise "not_a_receipt". For anything but "receipt", leave the other
  fields null/empty and explain in notes.
- date: the purchase date, YYYY-MM-DD. Swedish receipts often write 2026-10-20 or 20.10.26.
- total: the amount actually paid, including VAT ("Totalt", "Att betala", "Summa"). Not the
  subtotal, not a VAT line, not change given back. Decimal commas are decimal points.
- vat: one line per VAT rate printed (rate in percent, net if printed, VAT amount).
- category_id: pick the best match from this list, or null if none fits:
{categories}
- uncertain_fields: name every field you could not read with confidence (faded print, cut off,
  handwriting, several candidate totals). Do not guess silently; if unreadable, use null and list it.
- notes: anything a reviewer should know, in one or two sentences. Empty string if nothing.
- rotation_needed: how many degrees the image must be turned CLOCKWISE so the receipt's text reads
  normally, left to right: 0 if it already does; 90 if the text runs from bottom to top; 270 if it runs
  from top to bottom; 180 if it is upside down. Still read all fields, whatever the orientation.
"""


class RecognitionError(RuntimeError):
    pass


@dataclass
class RecognitionResult:
    recognition: Recognition
    cost_usd: float | None
    seconds: float | None = None
    num_turns: int | None = None
    usage: dict = field(default_factory=dict)  # token counts as reported by the CLI
    rotation_used: int = 0  # how the page image was turned when the AI read it


LEARNINGS_SECTION = """
The user corrected earlier readings. Follow these when they apply to this receipt:
{learnings}
"""


def build_prompt(image_name: str, categories: Sequence[Category], learnings: str = "") -> str:
    cats = "\n".join(f"  {c.id}: {c.name}" for c in categories) or "  (no categories available; use null)"
    prompt = PROMPT.format(image=image_name, categories=cats)
    if learnings.strip():
        prompt += LEARNINGS_SECTION.format(learnings=learnings.strip())
    return prompt


def resolve_claude(claude_path: str) -> str:
    """Full path of the claude CLI; finds claude.exe / claude.cmd on Windows too."""
    return shutil.which(claude_path) or claude_path


def build_command(claude_path: str, model: str) -> list[str]:
    """The prompt goes to stdin, so its line breaks survive argument quoting on every platform."""
    return [
        claude_path, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(RECOGNITION_SCHEMA),
        "--model", model,
        # Only the Read tool, no settings/hooks/MCP, nothing saved: the run just reads the image.
        "--tools", "Read",
        "--allowedTools", "Read",
        "--restricted",
        "--strict-mcp-config",
        "--no-session-persistence",
    ]


def parse_output(stdout: str) -> RecognitionResult:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RecognitionError(f"claude returned non-JSON output: {stdout[:300]!r}") from e
    if data.get("is_error") or data.get("subtype") != "success":
        raise RecognitionError(f"claude failed: {data.get('subtype')}: {str(data.get('result'))[:300]}")
    structured = data.get("structured_output")
    if structured is None:
        # Fall back to the text result if it is JSON.
        try:
            structured = json.loads(data.get("result") or "")
        except json.JSONDecodeError as e:
            raise RecognitionError("claude returned no structured output") from e
    usage = {k: v for k, v in (data.get("usage") or {}).items() if isinstance(v, int)}
    return RecognitionResult(Recognition.model_validate(structured), data.get("total_cost_usd"),
                             num_turns=data.get("num_turns"), usage=usage)


def recognize_png(
    png: bytes,
    categories: Sequence[Category],
    *,
    claude_path: str = "claude",
    model: str = "sonnet",
    timeout: float = 300,
    learnings: str = "",
) -> RecognitionResult:
    with tempfile.TemporaryDirectory(prefix="wint-page-") as tmp:
        image = Path(tmp) / "page.png"
        image.write_bytes(png)
        cmd = build_command(resolve_claude(claude_path), model)
        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout, input=build_prompt(image.name, categories, learnings))
        except FileNotFoundError as e:
            raise RecognitionError(f"claude CLI not found at {claude_path!r}") from e
        except subprocess.TimeoutExpired as e:
            raise RecognitionError(f"claude timed out after {timeout:.0f}s") from e
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RecognitionError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    result = parse_output(proc.stdout)
    result.seconds = round(time.monotonic() - start, 2)
    return result
