"""Start a built binary headless and check it keeps running (no import errors, no crash at startup).

    python scripts/smoke_test.py dist/wint-receipts[.exe | .app]

Runs offscreen with an empty, temporary config/cache and no Wint credentials, so it makes no
network calls and doesn't touch the user's settings. Exit 0 = still running after the wait.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WAIT_SECONDS = 15


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
        env.update(QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=f"{tmp}/config", XDG_CACHE_HOME=f"{tmp}/cache")
        proc = subprocess.Popen([str(exe)], cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.5)
        if proc.poll() is None:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
            text = out.decode(errors="replace")
            if "Traceback (most recent call last)" in text:
                print(text)
                print("smoke test: started, but printed a traceback")
                return 1
            print(f"smoke test: {exe.name} ran for {WAIT_SECONDS}s without crashing")
            return 0
        out, _ = proc.communicate()
        print(out.decode(errors="replace"))
        print(f"smoke test: {exe.name} exited early with code {proc.returncode}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
