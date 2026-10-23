import os
from pathlib import Path

import pypdfium2 as pdfium
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Keep tests away from the real config, cache, keyring and credentials."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("WINT_USER", raising=False)
    monkeypatch.delenv("WINT_TOKEN", raising=False)
    store: dict[tuple[str, str], str] = {}

    class FakeKeyring:
        @staticmethod
        def get_password(service, user):
            return store.get((service, user))

        @staticmethod
        def set_password(service, user, token):
            store[(service, user)] = token

    from wint_receipts.core import config

    monkeypatch.setattr(config, "_keyring", lambda: FakeKeyring)
    return store


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """A 3-page PDF with pages of distinct sizes, so extracted pages can be identified."""
    doc = pdfium.PdfDocument.new()
    for w in (200, 300, 400):
        doc.new_page(w, 500)
    path = tmp_path / "scans.pdf"
    doc.save(str(path))
    doc.close()
    return path
