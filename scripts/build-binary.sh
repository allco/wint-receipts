#!/usr/bin/env bash
# Build a single-file Linux executable at dist/wint-receipts with PyInstaller.
# The target machine still needs the `claude` CLI on PATH (or set its path in Settings).
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/pip install -q -e . pyinstaller

.venv/bin/pyinstaller --noconfirm --clean --onefile --windowed \
  --name wint-receipts \
  --collect-data pypdfium2_raw \
  --collect-binaries pypdfium2_raw \
  wint_receipts/__main__.py

ls -lh dist/wint-receipts
