# Wint receipts

A desktop app (Python + Qt) that turns a PDF of scanned receipts (one receipt per page) into
receipts in [Wint](https://wint.se):

1. **Open a PDF.** Drag it onto the window, or use *Open PDF*. Each page is rendered and sent to the
   [`claude` CLI](https://docs.claude.com/en/docs/claude-code), which reads the receipt and returns
   structured JSON: date, total, currency, supplier, VAT lines, a suggested category, and the fields
   it wasn't sure about.
2. **Review.** For each page you see the scan next to the recognised fields. Uncertain fields and
   failed checks (VAT arithmetic, future dates, locked periods, missing category, ...) are marked in
   amber or red. Edit, then **Approve** (Ctrl+Enter).
   - A receipt that runs over two pages can be merged with **Attach to previous**.
   - Blank pages are left out of the list (*Restore deleted pages* brings them back if Claude was
     wrong). Receipt backs are shown but skipped.
   - Right-click a page in the list → **Delete page** (or press `Del`) to remove it from the review.
     The PDF file isn't changed. Ctrl+Z, or *Restore deleted pages*, brings it back.
3. **Upload.** Each approved receipt is created in Wint with only its own page(s) as the PDF
   attachment. **Uploads are disabled by default** until the create-receipt API has been tested.
   Until then, **Preview request** shows the exact JSON that would be sent.

Review state is saved next to the PDF as `<file>.pdf.wint.json`, so you can close the app and
continue later. Every receipt has a stable `ClientId`, and the uploader checks it before creating
anything, so a retried upload doesn't create duplicates.

## Requirements

- Python 3.12 or newer
- The [`claude` CLI](https://docs.claude.com/en/docs/claude-code), installed and logged in. Check with
  `claude --version`.
- A Wint API key: in the Wint web app, *Settings → Integrations → custom app*. The user name is your
  company id.

| Platform | Status |
|---|---|
| Linux | Tested (Fedora, Wayland) |
| Windows 10/11 | Should work; not tested yet |
| macOS (Apple Silicon or Intel) | Should work; not tested yet |

## Run from source

### Linux and macOS

```bash
git clone git@github.com:allco/wint-receipts.git && cd wint-receipts
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/wint-receipts [scans.pdf]
```

On macOS, use the `python3` from [python.org](https://www.python.org/downloads/) or Homebrew
(`brew install python`). Apple's bundled Python may be too old.

### Windows (PowerShell)

```powershell
git clone git@github.com:allco/wint-receipts.git; cd wint-receipts
py -3 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\wint-receipts [scans.pdf]
```

Install Python from [python.org](https://www.python.org/downloads/) and tick *Add python.exe to
PATH*. If the app reports that it can't find the claude CLI, open *Settings → claude command* and enter
the full path from `where.exe claude`, e.g. `C:\Users\you\AppData\Roaming\npm\claude.cmd`.

### Wint credentials

You can enter the user name and API key in *Settings*: they're stored in the system keyring (Secret
Service / GNOME Keyring on Linux, Keychain on macOS, Credential Manager on Windows). To prefill them
instead, set `WINT_USER` and `WINT_TOKEN` before starting the app.

Linux / macOS, using a git-ignored `.CREDENTIALS` file:

```bash
printf 'export WINT_USER=%s\nexport WINT_TOKEN=%s\n' '<company id>' '<api key uuid>' > .CREDENTIALS
. ./.CREDENTIALS && .venv/bin/wint-receipts
```

Windows:

```powershell
$env:WINT_USER = "<company id>"; $env:WINT_TOKEN = "<api key uuid>"
.venv\Scripts\wint-receipts
```

## Single binary

PyInstaller bundles Python, Qt and the app into one executable. It doesn't cross-compile, so build
on each platform for that platform. The result still needs the `claude` CLI on the machine it runs
on, and it's a snapshot of the code, so rebuild it after changes.

Linux / macOS:

```bash
scripts/build-binary.sh        # → dist/wint-receipts (about 96 MB)
. ./.CREDENTIALS && dist/wint-receipts
```

Windows (PowerShell):

```powershell
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed --name wint-receipts `
  --collect-data pypdfium2_raw --collect-binaries pypdfium2_raw wint_receipts\__main__.py
dist\wint-receipts.exe
```

Platform notes:

- **Linux:** a binary built on a new distribution (e.g. Fedora 44) needs an equally new glibc. To run
  it on older systems, build on the oldest distribution you want to support.
- **macOS:** the binary isn't signed, so the first time, right-click it → *Open* to get past
  Gatekeeper. Apple Silicon and Intel need separate builds.
- **Windows:** SmartScreen may warn about an unknown publisher; choose *More info → Run anyway*.

## Settings

*Settings…* (Ctrl+,) holds:

- **Wint user name and API key.** They're prefilled from `WINT_USER` / `WINT_TOKEN`, and *Fill from
  environment* re-reads them. On save, the key goes into the system keyring, never a file. *Test
  connection* makes a read-only `GET /api/Auth`.
- **Request log** (on by default): every Wint request is appended as a JSON line to `wint-requests.log`.
- **Recognition log** (on by default): `recognition.log`, one JSON event per line:
  - `recognized`: page, model, DPI, seconds, cost, tokens, and the full recognised fields.
  - `failed`: the error.
  - `approved`: the final values, and which fields you changed from Claude's reading.

  Example: which fields get corrected most?
  `jq -s 'map(select(.event=="approved")) | map(.changed[]) | group_by(.) | map({field: .[0], n: length})' recognition.log`
- **Recognition:** the claude command and model (`sonnet` by default), the render DPI, and how many
  pages to read in parallel.
- **Upload:** the default payment method (otherwise the first one), and the **Enable uploads** switch.
- **Font size:** 0.5×–2.0×, applied immediately.

Non-secret settings are stored in `~/.config/wint-receipts/config.json`, on every platform for now
(on Windows that's `%USERPROFILE%\.config\wint-receipts`). Categories and payment methods are cached in
`~/.cache/wint-receipts/reference.json`. `XDG_CONFIG_HOME` / `XDG_CACHE_HOME` move them. Both logs are
written to the folder the app is started from, unless you change the path in Settings. If you start a
binary by double-clicking it, set the log paths explicitly.

## How recognition works

For each page the app runs:

```
claude -p "<prompt>" --output-format json --json-schema <schema> --model sonnet \
  --tools Read --allowedTools Read --restricted --strict-mcp-config --no-session-persistence
```

The command runs in a temporary directory containing only the page image. Claude can only read that
image. Nothing else is allowed, and no session is saved. The prompt includes the company's receipt
categories, so Claude can suggest one. The schema is `RECOGNITION_SCHEMA` in
`wint_receipts/core/recognize.py`. A typical page takes 3–7 s and costs about $0.03 with Sonnet.

## Wint API

`docs/wintapi.md` is a reference for the Wint REST API, generated from its public OpenAPI spec and
annotated by hand: authentication, paging, enums, the receipt lifecycle, and the full endpoint and
schema listing.

`bin/wint` is a small curl wrapper for manual API calls (bash, so Linux/macOS only). It reads credentials from `.CREDENTIALS`,
logs every request to `wint-requests.log`, and refuses anything other than GET unless
`WINT_ALLOW_WRITE=1` is set.

```bash
bin/wint -n "why this call" /api/Auth
bin/wint -o receipt.json /api/Receipt/123456
```

## Tests

```bash
.venv/bin/pytest
```

Wint and the claude CLI are mocked, so the tests never touch the live API. The UI tests run
offscreen with pytest-qt.

## Layout

```
wint_receipts/core/    UI-free logic
  models.py            pydantic models: Recognition, ReceiptDraft, PageState, Session, ReferenceData
  pdf.py               split / render pages (pypdfium2)
  recognize.py         claude CLI call + JSON schema
  checks.py            sanity checks (VAT, dates, required fields)
  wint.py              Wint client (reads; writes only with allow_writes=True), request log
  upload.py            create one receipt per approved page, idempotent by ClientId
  session.py           per-PDF state next to the PDF
  reclog.py            recognition log
  config.py            settings + credentials (env → keyring)
wint_receipts/app/     PySide6 UI
  main_window.py       page list | page image | receipt form
  receipt_form.py      editable fields and actions
  empty_states.py      illustrated placeholders
  theme.py, icons.py   design colours and the app's own icons
  fonts.py             live font scaling
  settings_dialog.py, image_view.py, workers.py
tests/                 pytest + pytest-qt
scripts/build-binary.sh
bin/wint               logged curl wrapper
docs/wintapi.md        Wint API reference
```

## Open items

- `POST /api/Receipt` hasn't been tested against the live API yet. Still to confirm: the required
  fields, `Attachments` vs `Images`, and whether a receipt must be signed afterwards
  (`POST /api/Receipt/Sign/{id}`). After that, adjust `receipt_post_body()` and `upload_page()`, and
  turn uploads on.
- Guests on representation receipts (`Persons`) aren't supported yet.
