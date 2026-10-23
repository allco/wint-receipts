"""App settings and Wint credentials.

Non-secret settings live in ~/.config/wint-receipts/config.json. The API key lives in the
system keyring. When nothing is saved yet, the user name and key are prefilled from the
WINT_USER / WINT_TOKEN environment variables (the names used in ./.CREDENTIALS).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

KEYRING_SERVICE = "wint-receipts"
ENV_USER = "WINT_USER"
ENV_TOKEN = "WINT_TOKEN"


APP_DIR = "wint-receipts"


def config_dir() -> Path:
    """Per-user settings folder: XDG_CONFIG_HOME if set, else the platform's usual place."""
    if base := os.environ.get("XDG_CONFIG_HOME"):
        return Path(base) / APP_DIR
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR
    return Path.home() / ".config" / APP_DIR


def cache_dir() -> Path:
    if base := os.environ.get("XDG_CACHE_HOME"):
        return Path(base) / APP_DIR
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_DIR / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_DIR
    return Path.home() / ".cache" / APP_DIR


def ledger_path() -> Path:
    """Every upload ever made from this app (see core/ledger.py)."""
    return config_dir() / "uploads.jsonl"


def default_log_dir() -> Path:
    return cache_dir()


class Settings(BaseModel):
    wint_base_url: str = "https://api.wint.se"
    wint_user: str = ""  # company id; the key itself is in the keyring
    request_log: str = Field(default_factory=lambda: str(default_log_dir() / "wint-requests.log"))
    recognition_log: str = Field(default_factory=lambda: str(default_log_dir() / "recognition.log"))
    request_log_enabled: bool = True
    recognition_log_enabled: bool = True
    claude_path: str = "claude"
    claude_model: str = "sonnet"
    recognition_dpi: int = 200
    parallel_recognitions: int = 3
    default_payment_method_id: int | None = None
    uploads_enabled: bool = True
    attachment_format: str = "jpeg"  # "jpeg" (one image per page) or "pdf" (the scan's page as PDF)
    # Corrections the user made, reused in later AI readings (a plain text file; see core/learnings.py).
    learnings_enabled: bool = True
    learnings_file: str = Field(default_factory=lambda: str(config_dir() / "learnings.txt"))
    font_scale: float = 1.5  # multiplies the system UI font size; 0.5–2.0 in the Settings presets

    def request_log_path(self) -> Path | None:
        return Path(self.request_log) if self.request_log_enabled and self.request_log else None

    def learnings_path(self) -> Path | None:
        return Path(self.learnings_file) if self.learnings_enabled and self.learnings_file else None

    def recognition_log_path(self) -> Path | None:
        return Path(self.recognition_log) if self.recognition_log_enabled and self.recognition_log else None

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or config_dir() / "config.json"
        if path.exists():
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        return cls(wint_user=os.environ.get(ENV_USER, ""))

    def save(self, path: Path | None = None) -> None:
        path = path or config_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=2), encoding="utf-8")


@dataclass(frozen=True)
class Credentials:
    user: str
    token: str

    @property
    def complete(self) -> bool:
        return bool(self.user and self.token)


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:  # keyring missing or no backend
        return None


def load_token(user: str) -> str:
    kr = _keyring()
    if kr and user:
        try:
            if token := kr.get_password(KEYRING_SERVICE, user):
                return token
        except Exception:
            pass
    return ""


def save_token(user: str, token: str) -> bool:
    """Store the key in the keyring. Returns False when no keyring backend is available."""
    kr = _keyring()
    if not kr:
        return False
    try:
        kr.set_password(KEYRING_SERVICE, user, token)
        return True
    except Exception:
        return False


def env_credentials() -> Credentials:
    return Credentials(os.environ.get(ENV_USER, ""), os.environ.get(ENV_TOKEN, ""))


def resolve_credentials(settings: Settings) -> Credentials:
    """Saved settings + keyring first; fill any gap from the environment."""
    env = env_credentials()
    user = settings.wint_user or env.user
    token = load_token(user) or (env.token if user == env.user else "")
    return Credentials(user, token)
