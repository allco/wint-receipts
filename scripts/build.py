"""Build the app with PyInstaller for the platform this runs on.

    python scripts/build.py            # → dist/wint-receipts (Linux), dist/wint-receipts.exe (Windows),
                                       #   dist/wint-receipts.app (macOS)

PyInstaller doesn't cross-compile: run this on each target platform (CI does, see .github/workflows).
Prints the path of the built artefact as the last line.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "wint-receipts"


def main() -> int:
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME,
        "--collect-data", "pypdfium2_raw",
        "--collect-binaries", "pypdfium2_raw",
        "--copy-metadata", "wint-receipts",
    ]
    if sys.platform == "darwin":
        # A one-folder .app bundle; one-file .app bundles are deprecated in PyInstaller.
        args += ["--onedir", "--osx-bundle-identifier", "io.github.allco.wint-receipts"]
        artefact = ROOT / "dist" / f"{NAME}.app"
    else:
        args += ["--onefile"]
        artefact = ROOT / "dist" / (f"{NAME}.exe" if sys.platform == "win32" else NAME)
    args.append(str(ROOT / "wint_receipts" / "__main__.py"))
    subprocess.run(args, cwd=ROOT, check=True)
    if not artefact.exists():
        print(f"build finished but {artefact} is missing", file=sys.stderr)
        return 1
    print(artefact)
    return 0


if __name__ == "__main__":
    sys.exit(main())
