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
    watchlist_db_path: str
    sync_enabled: bool
    sync_token: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        return cls(
            mock_mode=_flag("MOCK_MODE", True),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            extractor_model=os.getenv("EXTRACTOR_MODEL", "claude-sonnet-5"),
            kats_base_url=os.getenv("KATS_BASE_URL") or None,
            kats_service_key=os.getenv("KATS_SERVICE_KEY") or None,
            # 배포 시 반드시 영구 볼륨 경로를 지정한다. 컨테이너 기본 파일시스템에
            # 두면 재배포마다 워치리스트가 사라진다 (기획서 §6.1).
            watchlist_db_path=os.getenv("WATCHLIST_DB_PATH", "data/watchlist.db"),
            # 목 모드에서는 돌 이유가 없다(수집할 실데이터가 없다). 테스트도
            # 백그라운드 태스크 없이 뜨게 된다.
            sync_enabled=_flag("SYNC_ENABLED", not _flag("MOCK_MODE", True)),
            # 수동 트리거 인증. 비어 있으면 엔드포인트가 403 을 돌려준다 —
            # 토큰 미설정을 "인증 없음" 으로 해석하면 아무나 부를 수 있다.
            sync_token=os.getenv("SYNC_TOKEN") or None,
        )


settings = Settings.from_env()
