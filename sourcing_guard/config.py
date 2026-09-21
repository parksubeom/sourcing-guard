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
    # ⚠⚠ **빈 값은 "설정 안 함" 으로 읽는다 (2026-09-12).**
    #
    #   `.env.example` 이 `SYNC_ENABLED=` 를 빈 채로 배포하면서 주석에는
    #   "기본값은 MOCK_MODE 가 false 이면 켬" 이라고 적어 뒀다. 그런데 전에는
    #   빈 문자열이 `None` 이 아니라서 기본값을 건너뛰고 **False** 가 됐다 -
    #   안내대로 복사한 사람은 **리콜 동기화가 꺼진 줄도 모른다.**
    #
    #   조용히 꺼지는 것이 이 서비스에서 가장 비싼 실패다 (R6).
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    """숫자 환경변수. **못 읽으면 기본값으로 떨어진다.**

    ⚠ 빈 문자열·오타로 앱이 안 뜨면 그게 더 나쁘다 - 조회 하나가 느린 것과
      서비스가 안 뜨는 것은 값이 다르다. 대신 기본값으로 조용히 떨어진 것을
      `/healthz` 가 보여 준다(설정값을 그대로 낸다).
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return v if v > 0 else default


def _csv(name: str, default: str) -> tuple[str, ...]:
    """쉼표 목록. **비어 있으면 기본값이다.**

    ⚠ `os.getenv(name, default)` 로는 안 된다. 기본값은 키가 **없을 때만** 쓰이고,
      `EXTRACTOR_ORDER=` 처럼 **있는데 빈** 경우에는 안 쓰인다. `.env.example` 이
      바로 그 모양으로 "비워 두는 것이 정상" 이라고 안내한다.
    """
    parsed = tuple(v.strip().lower() for v in (os.getenv(name) or "").split(",") if v.strip())
    return parsed or tuple(v.strip().lower() for v in default.split(",") if v.strip())


@dataclass(frozen=True)
class Settings:
    mock_mode: bool
    anthropic_api_key: str | None
    extractor_model: str
    # ── 추출기 두 벌 (2026-09-08, CLAUDE.md R7 개정) ──
    #
    # Claude 크레딧이 소진돼 배포본이 매 스캔마다 400 을 받고 휴리스틱으로
    # 떨어지고 있었다. 추출이 죽으면 product_name·legal_item_name·category
    # 세 필드가 비고, 그러면 등급표 조회가 원본 상품명으로 돌아간다 -
    # 발표 숫자(단건 83.7%)가 화면과 어긋난다.
    #
    # ⚠ **기본값은 claude,gpt 다.** gpt 를 앞에 세우는 것은 장애 우회이고,
    #   fly secret 으로만 건다. 장애 상태를 코드 기본값으로 굳히면 충전 후
    #   env 를 안 바꿨을 때 GPT 가 영구 1순위가 된다 - 그러면 발표 숫자의
    #   기준 추출기가 조용히 바뀐다.
    gpt_api_key: str | None
    gpt_model: str
    extractor_order: tuple[str, ...]
    kats_base_url: str | None
    kats_service_key: str | None
    # 국표원 조회 타임아웃. **connect 와 read 를 나눈다** (2026-09-20 P1).
    #
    # ⚠⚠ 나누는 이유가 측정이다. 지금까지 둘이 한 값이라 "연결이 안 되는 것" 과
    #   "연결은 되는데 응답이 느린 것" 을 **가를 수 없었다.** 그 구분이
    #   fly 를 떠날지 말지를 정한다:
    #
    #       연결이 안 된다   시간을 늘려도 소용없다. 경로 문제다
    #       응답이 느리다    시간을 늘리면 된다
    #
    # ⚠ 기본값 8.0 은 **지금과 같은 동작**이다. 아무것도 설정하지 않으면
    #   전과 똑같이 돌아야 한다 - 이 변경은 동작을 바꾸는 것이 아니다.
    kats_connect_timeout: float
    kats_read_timeout: float
    watchlist_db_path: str
    sync_enabled: bool
    sync_token: str | None
    #: 링크 미리보기(og:url·og:image·canonical)가 **절대 주소**를 요구한다.
    #: 상대 경로를 넣으면 카카오·슬랙이 이미지를 못 가져간다.
    #: ⚠ 나가는 주소가 아니다 - HTML 에 적을 뿐이라 R4 허용 호스트와 무관하다.
    public_base_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        return cls(
            mock_mode=_flag("MOCK_MODE", True),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            extractor_model=os.getenv("EXTRACTOR_MODEL", "claude-sonnet-5"),
            gpt_api_key=os.getenv("GPT_API_KEY") or None,
            # ⚠ 실제 /v1/models 목록에서 고른 이름이다. 추측이 아니다 (R5).
            #   추출은 짧은 입력·짧은 JSON 출력이라 mini 급으로 충분한지
            #   대조 측정으로 확인한다.
            gpt_model=os.getenv("GPT_MODEL", "gpt-5.4-mini"),
            # ⚠⚠ **추출기는 GPT 한 벌이다 (2026-09-20 개정 · CLAUDE.md R7).**
            #   2026-09-19 에 Anthropic 잔액이 0 이 되어 2순위가 다시 죽었다.
            #   **죽은 2순위는 안전망이 아니라 문서의 거짓말**이라 목록에서 뺀다.
            #   R7 이 지키려던 것은 벤더 수가 아니라 **떨어진 것을 화면이
            #   말하는가** 였고, 그 관측은 그대로다 (`ScanMeta.extraction_path`
            #   와 메타 푸터. 2026-09-20 실측으로 확인했다).
            #   ⚠ `_call_claude` 코드는 지우지 않았다. 되살리려면 이 환경변수에
            #     `gpt,claude` 한 줄 + 잔액이면 된다.
            #   ⚠ 빈 값도 기본값으로 떨어진다 - `_csv` 주석 참조. 전에는
            #     `EXTRACTOR_ORDER=` 가 **빈 순서**가 되어 추출기가 하나도 없었다.
            extractor_order=_csv("EXTRACTOR_ORDER", "gpt"),
            kats_base_url=os.getenv("KATS_BASE_URL") or None,
            kats_service_key=os.getenv("KATS_SERVICE_KEY") or None,
            kats_connect_timeout=_env_float("KATS_CONNECT_TIMEOUT", 8.0),
            kats_read_timeout=_env_float("KATS_READ_TIMEOUT", 8.0),
            # 배포 시 반드시 영구 볼륨 경로를 지정한다. 컨테이너 기본 파일시스템에
            # 두면 재배포마다 워치리스트가 사라진다 (기획서 §6.1).
            watchlist_db_path=os.getenv("WATCHLIST_DB_PATH", "data/watchlist.db"),
            # 목 모드에서는 돌 이유가 없다(수집할 실데이터가 없다). 테스트도
            # 백그라운드 태스크 없이 뜨게 된다.
            sync_enabled=_flag("SYNC_ENABLED", not _flag("MOCK_MODE", True)),
            # 수동 트리거 인증. 비어 있으면 엔드포인트가 403 을 돌려준다 —
            # 토큰 미설정을 "인증 없음" 으로 해석하면 아무나 부를 수 있다.
            sync_token=os.getenv("SYNC_TOKEN") or None,
            public_base_url=(os.getenv("PUBLIC_BASE_URL")
                             or "https://sourcing-guard.fly.dev").rstrip("/"),
        )


settings = Settings.from_env()
