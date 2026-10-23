#!/usr/bin/env bash
# Build the app, check it, and install it as ~/bin/wint-receipts (or $INSTALL_DIR). Linux.
#
#   scripts/install.sh            # tests → build → smoke test → install → smoke test the installed copy
#   SKIP_TESTS=1 scripts/install.sh
#
# Safe while the app is running: the running instance keeps its old copy until it's restarted.
set -euo pipefail
cd "$(dirname "$0")/.."

dest="${INSTALL_DIR:-$HOME/bin}/wint-receipts"

[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/pip install -q -e '.[dev]' pyinstaller

if [[ -z "${SKIP_TESTS:-}" ]]; then
  QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider
fi

artefact=$(.venv/bin/python scripts/build.py | tail -1)
env -u WINT_USER -u WINT_TOKEN .venv/bin/python scripts/smoke_test.py "$artefact"

mkdir -p "$(dirname "$dest")"
install -m 755 "$artefact" "$dest"
cmp "$artefact" "$dest"
env -u WINT_USER -u WINT_TOKEN .venv/bin/python scripts/smoke_test.py "$dest"

running=$(pgrep -f "$dest" | grep -v "^$$\$" || true)
echo "installed $dest ($(du -h "$dest" | cut -f1), $(git rev-parse --short HEAD 2>/dev/null || echo '?'))"
[[ -n "$running" ]] && echo "note: the app is running; restart it to use the new version" || true
