# Wint receipts

## AI reads your receipts, you check, Wint books them

**Scan a stack of receipts into one PDF. Claude AI reads each page: date, amount, VAT and category. You check its reading next to the scan and upload the lot to [Wint](https://wint.se).
No manual typing.**

A desktop app (Python + Qt) built around AI receipt recognition, with a person approving every
receipt before it reaches the bookkeeping.

![Review screen: the scan on the left, the AI-read fields on the right](docs/design/03-review.png)

## What the AI does

Every page is read by [Claude](https://www.anthropic.com/claude) through the `claude` CLI, and it
comes back as structured data rather than free text:

| Read from the receipt | Example |
|---|---|
| Purchase date | `2026-10-20`, from formats like *20.10.26* or *2026-10-20* |
| Amount paid incl. VAT | the real total, not the subtotal, a VAT line or the change given |
| Currency | `SEK`, `EUR`, … |
| Supplier and org. number | used only to match your corrections; not shown on the form or sent to Wint |
| VAT per rate | 25 % · 12 % · 6 %, with net amounts when printed |
| **Category** | picked from *your* Wint company's receipt categories |

What it does beyond reading the text:

- **Says when it isn't sure.** Faded print, cut-off totals, handwriting or several candidate totals
  are returned as *uncertain fields*. The app marks those amber, so you know exactly where to look.
- **Knows what it's looking at.** It recognises blank pages (left out of the list), receipt backs
  (skipped).
- **Turns sideways scans upright.** It reports how a page must be turned to read normally, and the
  app turns the page: on screen, and in the PDF page sent to Wint. The *Rotate* buttons still let you
  correct it.
- **Gets checked by the app.** Net + VAT must add up to the total, VAT rates should be Swedish ones,
  dates can't be in the future or in a locked period. Anything off is flagged before you approve.
- **Learns from your corrections.** If you change the category the AI suggested,
  the app writes that down in a plain text file, `learnings.txt` (see [AI learnings](#ai-learnings)).
  The next receipt from the same supplier gets your category, and the AI is shown your corrections too.
- **Shows where it goes wrong.** Every approval can be logged with the fields you corrected, so you
  can see which fields the AI gets wrong most often (see *Recognition log* under Settings).
- **Is fast and cheap.** About 3–7 s and $0.03 per page with Claude Sonnet. Several pages are read
  in parallel while you review the first ones.

### How it works

For each page the app renders the PDF page as an image and runs:

```
claude -p "<prompt>" --output-format json --json-schema <schema> --model sonnet \
  --tools Read --allowedTools Read --restricted --strict-mcp-config --no-session-persistence
```

- The command runs in a temporary directory that contains only that page image. Claude can only read
  the image: no other tools, no settings, no saved session.
- The prompt includes the company's receipt categories, so the suggestion is a real Wint category id.
- `--json-schema` makes the answer match `RECOGNITION_SCHEMA` (`wint_receipts/core/recognize.py`), and
  the app validates it again with pydantic.
- The model is configurable in Settings: `sonnet`, `opus` for the hardest scans, or `haiku`.

## The workflow

1. **Open a PDF.** Drag it onto the window, or use *Open PDF*. Claude starts reading every page right
   away.
2. **Review.** For each page you see the scan next to the recognised fields. Uncertain fields and
   failed checks (VAT arithmetic, future dates, locked periods, missing category, ...) are marked in
   amber or red. Edit, then **Approve** (Ctrl+Enter).
   - Blank pages are left out of the list (*Restore deleted pages* brings them back if Claude was
     wrong). Receipt backs are shown but skipped.
   - Rotated scans are turned upright automatically when the AI reads them. To turn one yourself, use
     **Rotate left / right** under the image (Ctrl+Shift+R /
     Ctrl+R). The turn is used for the AI reading and for the PDF page sent to Wint. Zoom with − / +,
     1:1 and Fit, or the mouse wheel.
   - The form shows only what goes to Wint: date, amount (in **bold**), currency, category and payment
     method.
   - **Representation** receipts get a **Participants** field: tick who took part, from the people
     you've registered in Wint (Wint's receipt address book, most used first, with search). You are
     added automatically, so one guest is enough for the required **2 participants**. They're sent to
     Wint in the receipt's `Persons` field. The guest is suggested: the guests from your last approved
     receipt with the same supplier (remembered in the AI learnings file as a `participants:` line), or
     else your most frequent guest. A suggestion is marked amber "check who was there" until you
     approve. A **Reason** field, prefilled with "collaboration discussion", is sent as `Intent`.
   - **Address book** (toolbar): add, edit or remove the people you can pick, straight in Wint
     (`AddReceiptPerson` / `RemoveReceiptPerson`). Wint has no edit, so editing adds the corrected
     person and then removes the old entry. Not yet tried against the live API.
   - Right-click a page in the list for **Read again with AI**, **Approve**, **Upload to Wint** or
     **Delete page** (`Del`). Select several pages with Ctrl/Shift+click and the menu acts on all of
     them that fit. Deleting doesn't change the PDF file; Ctrl+Z or *Restore deleted pages* brings it
     back.
   - Uploaded pages get their own mark: a slate dot with a ✓, and their Wint receipt number.
3. **Upload.** Each approved receipt is created in Wint with only its own page(s) attached, as a
   JPEG per page (or a PDF, in Settings). Before creating anything, the app checks Wint for the same
   `ClientId` and for a receipt with the same date and amount, and asks if it finds one. The status
   bar shows the progress (*Uploading 2 of 3*) with a *Cancel* link, which stops after the receipt
   being sent. Every upload
   is written to an upload ledger (`uploads.jsonl` in the settings folder), so uploaded pages stay
   marked as uploaded even if a session file is lost. Uploads can be turned off in Settings. **Preview request** shows the exact JSON that would be sent.

Review state is saved next to the PDF as `<file>.pdf.wint.json`, so you can close the app and
continue later. Every receipt has a stable `ClientId`, and the uploader checks it before creating
anything, so a retried upload doesn't create duplicates.

The layout, colours, type, icons, components and interactions are described in
[docs/design.md](docs/design.md).

## Requirements

- Python 3.12 or newer
- The [`claude` CLI](https://docs.claude.com/en/docs/claude-code), installed and logged in. Check with
  `claude --version`.
- A Wint user name and API key. See [Getting credentials](#getting-credentials).

| Platform | Status |
|---|---|
| Linux | Tested (Fedora, Wayland) |
| Windows 10/11 | Should work; not tested yet |
| macOS (Apple Silicon or Intel) | Should work; not tested yet |

## Getting credentials

### Wint API key

The app talks to the Wint API with HTTP Basic auth: a **user name** and an **API key**. You get both
by creating a *custom app* (Wint's name for your own integration) in the Wint web app:

1. Log in at [app.wint.se](https://app.wint.se) as a user who can manage the company's settings.
2. Go to **Inställningar → Integrationer → Lägg till integration** (*Settings → Integrations → Add
   integration*).
3. Choose your own app (a *custom app*, category `OwnApp` in the API). Give it a name such as
   "Wint receipts" and generate an API key for it.
4. Make sure the integration is **activated**.
5. Copy the **API key**, a UUID like `8f6c1c1e-…`, and the app's **user name**. In a verified setup,
   the user name was the company's numeric id, e.g. `12345`.

Steps 3–5 are based on Wint's API (`/api/Settings/Integration/CustomApp`, `GenerateCustomAppKey`), so the
labels in that dialog may differ. If you can't find the option, ask Wint support for an *API key for a
custom integration*.

Treat the key like a password: it acts as your user, for that company. To revoke it, deactivate or
delete the custom app in Wint. The API can also do it (`DELETE /api/auth/key`).

**Check it works**, either way:

- In the app: *Settings → Test connection*. It makes a read-only `GET /api/Auth` and shows the
  company name.
- From a shell, with `WINT_USER` / `WINT_TOKEN` set: `bin/wint -n "check credentials" /api/Auth | jq '{Id, Name}'`.
  The `Id` it returns is the company id.

To create receipts, the user also needs Wint's receipt permissions. `GET /api/Auth` shows them as
`ReceiptCreator` and `ReceiptViewer`.

### claude CLI

Recognition runs through [Claude Code](https://docs.claude.com/en/docs/claude-code)'s `claude`
command, billed to your Claude subscription or Anthropic API account.

1. Install it by following the [installation guide](https://docs.claude.com/en/docs/claude-code/setup).
2. Run `claude` once in a terminal and complete the login it asks for.
3. Check: `claude --version` prints a version, and `claude -p "say ok"` answers.

The app calls the same `claude` command, so no separate key is needed. If `claude` isn't on the `PATH`
the app sees (common on Windows, or when starting it from a desktop launcher), enter its full path in
*Settings → claude command*.

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
PATH*. The app finds `claude.exe` (native installer) or `claude.cmd` (npm) on the `PATH` by itself.
Prefer the native installer: the JSON schema argument passes through `cmd.exe` with the npm shim,
which is more fragile. If the app reports that it can't find the claude CLI, open *Settings → claude
command* and enter the full path from `where.exe claude`.

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

## Command line

```
wint-receipts [PDF]        open the app, optionally with a PDF of scanned receipts
wint-receipts --help
wint-receipts --version
```

Relative paths are resolved from the current folder. A missing file, or one that isn't a PDF, is
reported on the terminal and the app doesn't start.

## Download a release

Ready-built binaries for Linux (x86_64), Windows (x86_64) and macOS (Apple Silicon) are attached to
each [GitHub Release](../../releases), together with a `SHA256SUMS.txt`. They still need the `claude`
CLI installed and logged in on the machine they run on.

| Platform | File | Run |
|---|---|---|
| Linux | `wint-receipts-vX.Y.Z-linux-x86_64` | `chmod +x` it, then start it |
| Windows | `wint-receipts-vX.Y.Z-windows-x86_64.exe` | double-click |
| macOS | `wint-receipts-vX.Y.Z-macos-arm64.zip` | unzip, then right-click `wint-receipts.app` → *Open* |

### Making a release

Releases are built by GitHub Actions (`.github/workflows/release.yml`) when a **semver tag** is
pushed:

```bash
git tag v1.0.0
git push origin v1.0.0
```

For each platform, the workflow runs the tests, builds the binary, and checks that it starts. Then it
creates the release with the three binaries, checksums and generated release notes. A tag with a
suffix, such as `v1.0.0-rc.1`, becomes a pre-release. Tags that aren't semver don't start the workflow.

## Build a binary yourself

PyInstaller bundles Python, Qt and the app into one executable. It doesn't cross-compile, so build
on each platform for that platform. The result still needs the `claude` CLI on the machine it runs
on, and it's a snapshot of the code, so rebuild it after changes.

Linux / macOS:

```bash
scripts/build-binary.sh        # → dist/wint-receipts (Linux, about 96 MB) or dist/wint-receipts.app (macOS)
. ./.CREDENTIALS && dist/wint-receipts
```

Windows (PowerShell):

```powershell
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python scripts\build.py     # → dist\wint-receipts.exe
dist\wint-receipts.exe
```

To build and install in one go (Linux): `scripts/install.sh` runs the tests, builds, checks the
binary starts, and installs it as `~/bin/wint-receipts` (`INSTALL_DIR` to change, `SKIP_TESTS=1` to
skip the tests). It's safe while the app runs; restart it to get the new version.

`python scripts/smoke_test.py <binary>` starts a build headless, without settings or credentials, and
checks that it doesn't crash.

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
- **Logs** live in the cache folder by default: `~/.cache/wint-receipts` on Linux,
  `~/Library/Caches/wint-receipts` on macOS, `%LOCALAPPDATA%\wint-receipts\cache` on Windows.
- **Request log** (on by default): every Wint request is appended as a JSON line to `wint-requests.log`.
- **Recognition log** (on by default): `recognition.log`, one JSON event per line:
  - `recognized`: page, model, DPI, seconds, cost, tokens, and the full recognised fields.
  - `failed`: the error.
  - `approved`: the final values, and which fields you changed from Claude's reading.

  Example: which fields get corrected most?
  `jq -s 'map(select(.event=="approved")) | map(.changed[]) | group_by(.) | map({field: .[0], n: length})' recognition.log`
- **AI learnings** (on by default): the learnings file's path, and an *Open file* button that opens
  it in your text editor.
- **Recognition:** the claude command and model (`sonnet` by default), the render DPI, and how many
  pages to read in parallel.
- **Upload:** the default payment method (otherwise the first one), and the **Enable uploads** switch.
- **Font size:** 0.5×–2.0×, applied immediately.

Where the app keeps its files (`XDG_CONFIG_HOME` / `XDG_CACHE_HOME` override this on any platform):

| | Settings (`config.json`) | Cache (`reference.json`: categories, payment methods) |
|---|---|---|
| Linux | `~/.config/wint-receipts/` | `~/.cache/wint-receipts/` |
| macOS | `~/Library/Application Support/wint-receipts/` | `~/Library/Caches/wint-receipts/` |
| Windows | `%APPDATA%\wint-receipts\` | `%LOCALAPPDATA%\wint-receipts\cache\` |

By default, both logs are written to the folder the app is started from. The exception is the
packaged app on Windows and macOS, which is usually started by double-clicking: it writes them to a
`logs` folder inside its settings folder. You can change both paths in Settings.

## AI learnings

`learnings.txt` lives in the settings folder (e.g. `~/.config/wint-receipts/learnings.txt`). The app
adds a line when you correct the AI before approving a receipt, and reads the file before each AI
reading. It's a plain text file: edit, add or delete lines freely.

```
category: "EasyPark AB" (org 556xxx-xxxx) = "Parkering" [86914]   # learned 2026-10-23
supplier: "EASYPARK" = "EasyPark AB"   # learned 2026-10-23
Receipts from Mr Wok are Representation.
```

- **`category:` lines** are applied by the app itself after each reading, so they always win. They
  match the supplier by org number, or by name (ignoring case, punctuation and "AB").
- **`supplier:` lines** (written by hand) make the app treat two spellings as the same supplier when
  matching category rules.
- **Any other line** is passed to the AI as a hint.
- **`#` lines** are comments.
- A newer correction for the same supplier replaces the old line.

When a learned rule changes a reading, the receipt's *AI notes* say so, e.g. "Category set to
"Parkering" from your earlier correction for EasyPark AB."

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
  learnings.py         AI learnings file: parse, apply, learn
  config.py            settings + credentials (env → keyring)
wint_receipts/app/     PySide6 UI
  main_window.py       page list | page image | receipt form
  receipt_form.py      editable fields and actions
  empty_states.py      illustrated placeholders
  theme.py, icons.py   design colours and the app's own icons
  fonts.py             live font scaling
  image_view.py        zoomable page view + rotate/zoom bar
  settings_dialog.py, workers.py
tests/                 pytest + pytest-qt
scripts/build.py, build-binary.sh, smoke_test.py
.github/workflows/     release builds on semver tags
bin/wint               logged curl wrapper
docs/wintapi.md        Wint API reference
docs/design.md         design notes; docs/design/*.png are screens (Git LFS)
```

## Open items

- Creating receipts was tested with one real upload (see `docs/wintapi.md`); the JPEG attachment format
  hasn't been uploaded for real yet.
- Guests on representation receipts (`Persons`) aren't supported yet.
