"""Environment configuration.

CLAUDE.md §6: secrets are read from .env only. Never hardcoded, never logged.

MOCK_MODE defaults to true so the pipeline is runnable — and testable in CI —
without any key at all. Turning it off is a deliberate act.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv(path: Path = _ENV_PATH) -> None:
    """Minimal .env reader. Real environment variables always win.

    Deliberately dependency-free: one less package to install in CI, and the
    format we use here is only KEY=value.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mock_mode: bool
    anthropic_api_key: str | None
    extractor_model: str
    kats_base_url: str | None
    kats_service_key: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        return cls(
            mock_mode=_flag("MOCK_MODE", True),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            extractor_model=os.getenv("EXTRACTOR_MODEL", "claude-sonnet-5"),
            kats_base_url=os.getenv("KATS_BASE_URL") or None,
            kats_service_key=os.getenv("KATS_SERVICE_KEY") or None,
        )


settings = Settings.from_env()
