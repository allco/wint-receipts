"""Start a built binary headless and check that the full UI comes up and the app exits cleanly.

    python scripts/smoke_test.py dist/wint-receipts[.exe | .app]

The app runs offscreen with an empty, temporary config and cache and no Wint credentials, so it
makes no network calls and doesn't touch the user's settings. With WINT_RECEIPTS_SMOKE_TEST set, the
app quits by itself a few seconds after its window is shown. The test passes only if it exits with
code 0 within the time limit. A crash, a traceback, a hang, or a windowed build's error dialog (which
keeps the process alive) all fail.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

TIME_LIMIT_SECONDS = 90  # a one-file build unpacks itself first; that can take a while on CI


def executable(path: Path) -> Path:
    if path.suffix == ".app":  # macOS bundle
        return path / "Contents" / "MacOS" / path.stem
    return path


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    exe = executable(Path(sys.argv[1]).resolve())
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if k not in ("WINT_USER", "WINT_TOKEN")}
        env.update(QT_QPA_PLATFORM="offscreen", WINT_RECEIPTS_SMOKE_TEST="1",
                   XDG_CONFIG_HOME=os.path.join(tmp, "config"), XDG_CACHE_HOME=os.path.join(tmp, "cache"))
        try:
            # communicate() drains the output while waiting, so a chatty app can't block on a full pipe.
            proc = subprocess.run([str(exe)], cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=TIME_LIMIT_SECONDS)
        except subprocess.TimeoutExpired as e:
            print((e.stdout or b"").decode(errors="replace"))
            print(f"smoke test: {exe.name} did not exit within {TIME_LIMIT_SECONDS}s (hang or error dialog)")
            return 1
    out = proc.stdout.decode(errors="replace")
    if proc.returncode != 0 or "Traceback (most recent call last)" in out:
        print(out)
        print(f"smoke test: {exe.name} failed (exit code {proc.returncode})")
        return 1
    print(f"smoke test: {exe.name} started its UI and exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
