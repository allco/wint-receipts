#!/usr/bin/env bash
# Build the app for this platform with PyInstaller (Linux: dist/wint-receipts, macOS: dist/wint-receipts.app).
# The target machine still needs the `claude` CLI on PATH (or set its path in Settings).
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/pip install -q -e . pyinstaller

artefact=$(.venv/bin/python scripts/build.py | tail -1)
ls -ldh "$artefact"
