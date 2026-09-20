"""FastAPI entrypoint. Chrome extension posts a DOM snapshot here.

CLAUDE.md R4: the server never fetches commerce pages itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from contextlib import asynccontextmanager, suppress

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from datetime import date, datetime, timezone
from uuid import uuid4

from .baseline import BASELINE, BASELINE_EXTRACTOR
from .build_info import snapshot as build_snapshot
from .config import settings
from .batch import MAX_ROWS, BatchReport, screen
from .cert_seed import SeedStats, apply_to as apply_cert_seed
from .extractor import extract_traced, stats as extraction_stats
from .kats_client import KatsClient, health
from .noncompliant_index import NoncompliantIndex
from .rra_client import RraClient
from .models import (
    Finding,
    RecallAlert,
    ScanMeta,
    ScanResult,
    SellerHints,
    WatchItem,
)
from .scorer import KST, gov_lookup_state, has_specific_finding, score
from .demos import DEMOS, DEMO_TEXTS
from .demos import preview as demo_preview
from .samples import compare_cut, misses as sample_misses, payload as sample_payload

_log = logging.getLogger(__name__)
from .ratelimit import RateLimiter, text_fingerprint
from .recall_index import RecallIndex
from .storage import SqliteWatchStore
from .sync import run_sync, sync_loop
from .verifier import (
    _grade_book,
    RuleBook,
    split_cert_regimes,
    verify,
    verify_rf_by_model,
)
from .masking import register_settings_secrets
from .watchlist import sweep

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """리콜 동기화 백그라운드 루프.

    시작 시 1회 실행하고 이후 하루 한 번 돈다. 재배포하면 몇 시간 공백이
    생기는데 뜨자마자 한 번 돌면 그 공백이 사라진다 (증분은 400KB 다).

    루프가 죽어도 앱은 계속 뜬다. 정부 API 장애로 스캔까지 멈추면 안 된다.

    ⚠⚠ **맨 먼저 시크릿을 등록한다.** `masking.mask()` 는 등록된 값만 지운다 -
      등록 전에 던져진 예외는 키를 그대로 담는다. 2026-09-14 까지 이 함수가
      **프로덕션에서 한 번도 안 불렸고**, 그 사이 마스킹은 `scripts/` 에서만
      일하고 있었다 (`tests/test_masking.py::test_the_app_registers_its_secrets`).
    """
    register_settings_secrets()

    # ⚠ 캐시는 프로세스 메모리다. **재배포하면 0 이 된다.** 국표원 조회가 죽어
    #   있는 동안 배포하면 데모 셋이 전부 "조회 실패" 로 뜬다. 실조회로 받아 둔
    #   레코드를 조회 시각과 함께 얹어 그 구멍을 막는다 - fresh 가 아니라
    #   **만료된 것으로** 얹으므로, 조회가 살아나면 곧바로 밀려나고 죽어 있으면
    #   화면이 "…조회분으로 표시합니다" 를 단다 (`cert_seed` 모듈 주석).
    global _cert_seed_stats
    _cert_seed_stats = apply_cert_seed(_kats)

    task = None
    if settings.sync_enabled:
        task = asyncio.create_task(
            sync_loop(
                _kats,
                _store,
                # ⚠ 색인 무효화 **다음에 전체 스윕**까지 돈다 (C-백).
                #   순서가 중요하다 - `_on_recalls_updated` 주석 참조.
                on_updated=_on_recalls_updated,
                # 부적합 방송통신기자재 현황. 전파인증 축의 유일한 RED 소스라
                # 여기 안 붙이면 rf_noncompliant 테이블이 영구히 비고
                # RF_NONCOMPLIANT 이 한 번도 뜨지 않는다.
                rra=_rra,
                on_noncompliant_updated=_noncompliant.invalidate,
            )
        )
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="안심 소싱 돋보기 API", version="0.1.0", lifespan=_lifespan)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)

_kats = KatsClient(settings.kats_base_url, settings.kats_service_key, mock=settings.mock_mode)
# 시작 전에는 비어 있다. `_lifespan` 이 채운다 - 0 으로 두면 "아직 안 얹었다" 와
# "얹었는데 0건" 이 같아 보이므로 `/healthz` 를 읽을 때 앱이 떴는지 먼저 본다.
_cert_seed_stats = SeedStats()
# 전파인증 조회. 인증키가 필요 없어 MOCK_MODE 만 따른다.
_rra = RraClient(mock=settings.mock_mode)
_rules = RuleBook()


class ResultStats:
    """**유효 결과율** - 구체적인 것을 하나라도 준 검사의 비율 (E).

    매칭률과 별개로 우리가 움직여야 할 지표다. 매칭률이 올라도 화면이 "확인
    필요" 세 줄뿐이면 셀러에게 준 것이 없다.

    ⚠ **프로세스 메모리다.** 재배포하면 0 이 된다 - 누적 통계가 아니라 "지금 뜬
      이 프로세스가 어떤 결과를 내고 있나" 를 보는 값이다. `ExtractionStats` 와
      같은 성격이고 `/healthz` 가 그 사실을 함께 적는다.

    ⚠ **단건 경로(`/api/v1/scan`)만 센다.** 배치는 `screen()` 이 `BatchRow` 를
      내고 `Finding` 이 없어서 같은 자로 잴 수 없다.
    """

    def __init__(self) -> None:
        self.scans = 0
        self.with_specific = 0

    def record(self, *, specific: bool) -> None:
        self.scans += 1
        self.with_specific += specific

    def snapshot(self) -> dict:
        return {
            "scans": self.scans,
            "with_specific_finding": self.with_specific,
            "rate": (
                round(self.with_specific / self.scans, 3) if self.scans else None
            ),
            "note": "프로세스 메모리 · 단건 경로만 · 재배포하면 0",
        }


_result_stats = ResultStats()


class ScanImage(BaseModel):
    # 중국 도매 상세페이지는 상품정보 표가 통짜 이미지인 경우가 많다.
    # media_type 은 허용 목록으로 제한하고, 개수·크기 상한으로 LLM 비용을 막는다.
    media_type: Literal["image/jpeg", "image/png", "image/webp", "image/gif"]
    data: str = Field(min_length=1, max_length=8_000_000)  # base64, 원본 약 6MB


class BatchRequest(BaseModel):
    """대량 검사. 상품명을 줄바꿈으로 구분해 받는다.

    셀러가 도매매·온채널 엑셀에서 상품명 열을 복사해 붙이면 그것이 곧 200줄
    이다 - 엑셀 파싱 없이도 실사용이 된다.
    """

    # 200줄 x 상품명 200자 여유
    text: str = Field(default="", max_length=60_000)

    @model_validator(mode="after")
    def _need_text(self) -> "BatchRequest":
        if not self.text.strip():
            raise ValueError("검사할 상품명을 한 줄에 하나씩 넣어 주세요.")
        return self


class ScanRequest(BaseModel):
    # page_text 와 images 중 하나 이상 있으면 된다. 이미지만 있는 경우
    # (통짜 이미지 페이지)도 스캔할 수 있어야 한다.
    page_text: str = Field(default="", max_length=200_000)
    page_url: str | None = None
    images: list[ScanImage] = Field(default_factory=list, max_length=4)
    # 셀러가 화면에서 답해 준 사실. 없으면 힌트 도입 전과 같이 동작한다 -
    # 추가 정보이지 필수 입력이 아니다.
    seller_hints: SellerHints = Field(default_factory=SellerHints)

    @model_validator(mode="after")
    def _need_some_input(self) -> "ScanRequest":
        if not self.page_text.strip() and not self.images:
            raise ValueError("page_text 또는 images 중 하나는 있어야 합니다.")
        return self


#: 벤더 → (키, 모델) 접근자. `/healthz` 가 **순서에 든 벤더만** 내보낸다.
#:
#: ⚠ 벤더를 늘리면 여기 한 줄이다. 두 곳에 적으면 한쪽만 고쳐진다 (§6).
_VENDOR_KEY = {
    "gpt": lambda: settings.gpt_api_key,
    "claude": lambda: settings.anthropic_api_key,
}
_VENDOR_MODEL = {
    "gpt": lambda: settings.gpt_model,
    "claude": lambda: settings.extractor_model,
}

_STATIC = Path(__file__).parent / "static"

#: `/static/…` 참조를 찾는다. 셋을 지켜야 한다.
#:
#:   ① 조각(`#mungchi-calm`)은 **쿼리 뒤에** 와야 한다 - `mascot.svg#x?v=1` 이면
#:      조각 이름이 `x?v=1` 이 되어 아이콘이 사라진다.
#:   ② 작은따옴표도 받는다. `index.html` 의 결과 카드가 표정을 런타임에 이어
#:      붙인다(`'/static/mascot.svg#mungchi-' + FACE[sig]`). 큰따옴표만 보면
#:      **그 자산만 버전 없이 남는다** - 검사가 실제로 그것을 잡았다.
#:   ③ 여는 따옴표만 본다. 닫는 따옴표를 짝으로 요구하면 **JS 안의 HTML**
#:      을 놓친다 - `'<use href="/static/mascot.svg#mungchi-' + FACE[sig]` 은
#:      `"` 로 열리고 `'` 로 닫힌다. 실제로 그 한 자산만 버전 없이 남았다.
_STATIC_REF = re.compile(
    r"""(?<=["'])(?P<path>/static/[^"'?\#\s]+)(?P<frag>\#[^"'\s]*)?"""
)

_IMMUTABLE = "public, max-age=31536000, immutable"


@app.middleware("http")
async def _cache_headers(request: Request, call_next):
    """정적 자산은 버전이 붙었을 때만 오래 캐시한다.

    ⚠⚠ **왜 필요한가.** 2026-09-13 배포본(7185d2b)의 `/static/app.css` 에 버전
      쿼리가 없었다. 브라우저가 옛 CSS 를 들고 있으면 **디자인을 고쳐 배포해도
      셀러 화면은 그대로**다. 투표 기간에 그러면 고친 줄도 모르고 지나간다.

    ⚠ 버전이 **없으면 오래 캐시하지 않는다.** 빌드 커밋을 모르는 상태(로컬에
      .git 도 없고 build-arg 도 없는 경우)에서 1년을 캐시하면 되돌릴 방법이
      없다. 모르면 캐시하지 않는 쪽이 안전하다 (R3 와 같은 태도).
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = (
            _IMMUTABLE if request.query_params.get("v") else "no-cache"
        )
    elif "cache-control" not in response.headers:
        # ⚠ **이 앱에서 캐시해도 되는 응답은 버전 붙은 정적 자산뿐이다.**
        #   나머지는 전부 그 순간의 상태다 - 스캔 결과 · 감시 목록 · `/healthz`.
        #   특히 `/healthz` 가 캐시되면 **배포 확인이 옛 커밋을 읽는다**. 지금
        #   고치고 있는 결함이 정확히 그것이라 여기서 같은 구멍을 열어 두지
        #   않는다.
        response.headers["Cache-Control"] = "no-cache"
    return response


#: 머리 배지 자리. HTML 이 `<span class="asof" data-asof></span>` 를 두면
#: 서버가 날짜를 넣고, 모르면 요소째 지운다.
_ASOF_SLOT = re.compile(r'<span class="asof" data-asof>.*?</span>', re.S)


def _fill_as_of(html: str) -> str:
    raw = getattr(_recalls, "as_of", None) or ""
    if not (len(raw) == 8 and raw.isdigit()):
        return _ASOF_SLOT.sub("", html)
    shown = f"{raw[:4]}-{raw[4:6]}-{raw[6:]} 기준"
    return _ASOF_SLOT.sub(
        f'<span class="asof" title="리콜 공표 기준일">{shown}</span>', html)


def _page(name: str) -> HTMLResponse:
    """HTML 을 내면서 정적 자산 참조에 `?v=<build.commit>` 를 박는다.

    ⚠⚠ **HTML 파일에 해시를 하드코딩하지 않는다.** 그러면 배포마다 네 파일을
      손으로 고쳐야 하고, 한 곳을 빼먹으면 그 자산만 옛 것이 남는다 - 가장
      찾기 어려운 종류의 결함이다. 서버가 낼 때 한 곳에서 박는다.

    ⚠ HTML 자체는 `no-cache` 다. HTML 이 캐시되면 그 안의 버전 쿼리도 옛 것이라
      캐시 무효화가 한 바퀴 늦는다.

    ⚠ 커밋을 모르면 쿼리를 **붙이지 않는다.** 지어낸 버전을 박으면 그것이
      바뀌지 않는 한 영원히 옛 자산이 남는다 (R5).
    """
    html = (_STATIC / name).read_text(encoding="utf-8")

    # 머리 오른쪽의 "2026-09-19 기준". **리콜 공표 기준일**이고 모든 화면에
    # 같은 값이어야 한다 (시안 §6).
    #
    # ⚠⚠ 화면마다 fetch 를 붙이지 않는다. 일곱 파일이 각자 물어보면 같은
    #   판단이 일곱 벌이 되고, 한 곳만 고쳐질 때 나머지가 낡은 날짜를 말한다
    #   (§6). 서버가 낼 때 한 곳에서 박는다 - `?v=` 해시와 같은 자리다.
    #
    # ⚠ 값이 없으면 **자리를 통째로 지운다.** 빈 배지를 남기거나 오늘 날짜로
    #   메우면 화면이 없는 사실을 말한다 (R3·R5).
    html = _fill_as_of(html)

    commit = build_snapshot()["commit"]
    if commit:
        html = _STATIC_REF.sub(
            lambda m: f"{m.group('path')}?v={commit}{m.group('frag') or ''}",
            html,
        )
    return HTMLResponse(
        html, headers={"Cache-Control": "no-cache"},
        media_type="text/html; charset=utf-8",
    )


#: 화면 라우트는 GET 과 **HEAD** 를 함께 받는다.
#:
#: ⚠ FastAPI 는 `@app.get` 에 HEAD 를 자동으로 붙이지 않는다(Starlette 의 맨
#:   `Route` 와 다르다). 그래서 `/`·`/scan`·`/batch`·`/watch`·`/healthz` 가
#:   전부 **HEAD 에 405** 였다 - 2026-09-13 배포본에서 실측했다. 제출 링크의
#:   루트가 그러면 가동 감시·링크 미리보기가 본문을 받지 않고 실패로 읽는다.
#:   우리가 만든 것이 아니라 처음부터 그랬고, 아무도 HEAD 를 쳐 보지 않아서
#:   몰랐다.
_PAGE_METHODS = ["GET", "HEAD"]


@app.api_route("/", methods=_PAGE_METHODS, response_class=HTMLResponse, include_in_schema=False)
def landing() -> HTMLResponse:
    """랜딩 (G-1 · 2026-09-12). 심사위원용 서사 + 투표자용 데모 버튼.

    `/` 가 도구에서 소개로 바뀌었다 - 제출 링크는 `/` 그대로 두고, 도구는
    `/scan` 으로 옮겼다 (docs/랜딩페이지_설계.md §1). 데모 버튼은
    `/scan?demo=<tone>` 으로 보내고 그쪽이 자동으로 검사한다 - 투표자 클릭 1번.

    ⚠ 디자인 무관 구조만이다. 로고·색·파비콘은 시피님이 새로 한다.
    """
    return _page("landing.html")


@app.api_route("/scan", methods=_PAGE_METHODS, response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    """단일 페이지 프론트엔드 (도구). 2026-09-12 에 `/` 에서 `/scan` 으로 옮겼다.

    빌드 단계를 두지 않는다. 정적 HTML 하나를 그대로 돌려주면 되고, 그 편이
    투표 기간 18일 무중단에 유리하다 - 깨질 지점이 하나 줄어든다.

    `?demo=<tone>` 을 읽어 서버 데모 문구로 자동 검사한다 (랜딩에서 온 경우).
    """
    return _page("index.html")


@app.api_route("/batch", methods=_PAGE_METHODS, response_class=HTMLResponse, include_in_schema=False)
def batch_page() -> HTMLResponse:
    """대량 검사 화면.

    셀러는 상품을 한 건씩 붙여넣지 않는다 - 도매 플랫폼에서 엑셀을 받아
    수백 건을 한 번에 올린다. API 만 있고 화면이 없으면 그 흐름에 못 들어간다.
    """
    return _page("batch.html")


@app.api_route("/watch", methods=_PAGE_METHODS, response_class=HTMLResponse, include_in_schema=False)
def watch_page() -> HTMLResponse:
    """감시 목록 화면.

    기획서 §3-4단계. 스캔은 시점 판단이라 "지금 안전하다"를 보증할 수 없지만,
    "나중에 리콜 공표되면 놓치지 않는다"는 보증할 수 있다. 그것이 이 서비스가
    유일하게 약속하는 것이고, 그래서 별도 화면을 준다.
    """
    return _page("watch.html")


@app.api_route("/samples", methods=_PAGE_METHODS, response_class=HTMLResponse,
               include_in_schema=False)
def samples_page() -> HTMLResponse:
    """체험 표본 — 실상품 열 개를 우리가 실제로 검사한 결과 그대로.

    ⚠ **전역 내비에 넣지 않았다.** 320px 내비 넘침을 2026-09-18 에 닫았고
      (미완 §1-l), 항목을 여섯째로 늘리면 그것이 되돌아올 수 있다. 랜딩과
      검사 화면에서 링크한다. 넣으려면 `scripts/measure_widths.py` 로 폭
      열넷을 먼저 재고 넣는다.
    """
    return _page("samples.html")


@app.api_route("/misses", methods=_PAGE_METHODS, response_class=HTMLResponse,
               include_in_schema=False)
def misses_page() -> HTMLResponse:
    """「우리가 틀린 것」 — 틀린 것을 내놓는 것이 이 제품의 논리와 맞는다."""
    return _page("misses.html")


@app.api_route("/unknown", methods=_PAGE_METHODS, response_class=HTMLResponse,
               include_in_schema=False)
def unknown_page() -> HTMLResponse:
    """「왜 "모름" 이 나왔나」.

    실측 135건 중 19건(14.1%)이 회색불이다. 심사·투표에서 나올 첫 질문이
    "모른다고만 하는 서비스 아니냐" 이고, 그 답이 코드 안에는 있는데 화면 한
    장에 모여 있지 않았다.

    ⚠ 전역 내비에 안 넣는다 - `/samples` 와 같은 이유다(320px 내비 넘침,
      미완 §1-l). 질문이 실제로 생기는 세 곳에서 건다: 회색불 결과 카드 ·
      랜딩의 "판정은 하지 않습니다" · `/misses` 의 "아무 말도 못 한 것".
    """
    return _page("unknown.html")


@app.api_route("/guide", methods=_PAGE_METHODS, response_class=HTMLResponse, include_in_schema=False)
def guide_page() -> HTMLResponse:
    """[M-5] 카테고리 가이드 — **안내 축이다. 아무것도 판정하지 않는다.**

    도매 카테고리마다 "이 도구가 실제로 무엇을 말할 수 있는지" 를 보여 준다.
    카테고리 이름으로 정한 것이 아니라 그 카테고리 상품명을 배치 경로에
    넣어 **붙은 것만** 옮겼다 (R5).

    ⚠ 숫자는 전부 매칭률이고 정답률이 아니다. 화면이 라벨을 반드시 그린다
      (`tests/test_guide.py`).
    """
    return _page("guide.html")


@app.api_route("/healthz", methods=_PAGE_METHODS)
def healthz() -> dict:
    """우리 프로세스 상태 + 정부 API 상태.

    ⚠ 정부 API 가 죽어도 ok 는 true 로 둔다. Fly 헬스체크가 이 값을 보고
    머신을 재시작시키므로, 남의 API 장애로 우리 서비스를 죽이면 안 된다.
    ok 는 우리 프로세스 상태이고 kats 는 별도 정보다.
    """
    return {
        "ok": True,
        "mock_mode": settings.mock_mode,
        "active_rules": len(_rules.active),
        "draft_rules": len(_rules.drafts),
        "watched_items": _store.count(),
        # ⚠ **배포된 것이 어느 커밋인가.** 필드 유무로 버전을 역추적하는 일이
        #   없게 한다 - 2026-09-11 에 실제로 그래야 했다.
        "build": build_snapshot(),
        "kats": health.snapshot(),
        # ⚠ 시드가 몇 건 얹혔나. **0 이면 재배포 뒤 데모의 인증 축이 죽는다**
        #   (국표원이 죽어 있는 동안). `skipped` 가 0 이 아니면 시드 파일이
        #   깨진 것이고, 걸러진 줄은 조용히 없어진 것이 아니라 여기 센다.
        "cert_seed": _cert_seed_stats.as_dict(),
        "sync": {"enabled": settings.sync_enabled, **_store.sync_snapshot()},
        # ⚠ 저장소가 손상돼 격리됐는지 (4-q). None 이 정상이다 - 값이 있으면
        #   **등록된 워치 항목을 잃었다는 뜻**이고, 그러면 "리콜을 가장 먼저
        #   알린다" 는 약속이 조용히 깨진 상태다 (R6).
        "storage": {
            "path": settings.watchlist_db_path,
            "quarantined_from": _store.quarantined_from,
            "note": (
                "quarantined_from 이 null 이 아니면 DB 손상으로 새로 시작한 "
                "것입니다. 워치 항목이 비어 있으니 격리 파일에서 복구하세요."
            ),
        },
        "limits": _limiter.snapshot(),
        # ⚠ **추출이 실제로 어느 경로로 갔는지 여기서 보여야 한다.**
        #   2026-09-08 에 Claude 크레딧이 소진돼 배포본이 매 스캔마다 400 을
        #   받고 휴리스틱으로 떨어졌는데, 그 사실을 로그를 뒤져서야 알았다.
        #   그 사이 휴리스틱 결과를 "실물 확인" 으로 보고했다. 응답 모양으로
        #   추론하지 말고(ExtractionStats 주석) 이 값을 볼 것.
        #
        #   ⚠ 프로세스 메모리라 재배포하면 0 이 된다. 누적 통계가 아니라
        #     "지금 뜬 이 프로세스가 어느 경로를 쓰고 있나" 를 보는 값이다.
        # 감시 자동화 상태 (C-백). "마지막 sweep 시각 · 새 알림 N".
        # ⚠ 이 값이 오래 안 움직이면 **약속이 조용히 깨진 것**이다 - 셀러는
        #   감시받고 있다고 믿는 채로 감시되지 않는다 (기획서 §6.1).
        "watch_sweep": _sweep_snapshot(),
        # [D-백] 검수 대기열 길이. 늘기만 하면 검수가 안 되고 있다는 신호다.
        "miss_reports": _store.miss_report_snapshot(),
        # 랜딩이 "70.4% · 135건" 과 "0건" 을 **그 자리에서** 그린다
        #   (design/README §10-2 · 하드코딩 금지). 전에는 HTML 에 숫자를 적고
        #   검사가 기준선과 대조했는데, 그것은 같은 숫자를 두 곳에 적는 것이라
        #   한쪽만 고치면 나머지가 거짓말을 계속한다 (§6).
        "baseline": _baseline_snapshot(),
        # 유효 결과율 - 매칭률과 별개로 우리가 움직여야 할 지표다 (E).
        # ⚠ 프로세스 메모리이고 단건 경로만 센다. note 에 그 사실을 적는다.
        "results": _result_stats.snapshot(),
        "extraction": {
            "order": list(settings.extractor_order),
            # ⚠⚠ **순서에 없는 벤더의 준비 상태를 초록으로 적지 않는다.**
            #   2026-09-20 까지 `claude_key: true` 를 냈는데, 그때 키는 있고
            #   **잔액이 0** 이었고 순서에서도 빠져 있었다. `true` 가 "쓸 수
            #   있다" 로 읽힌다 - 쓰지 않는 것의 준비 상태를 말하는 것은 §1-k 와
            #   같은 자리의 거짓말이다 (§9).
            #   그래서 **순서에 든 벤더만** 키·모델을 낸다.
            **{f"{v}_key": bool(_VENDOR_KEY[v]()) for v in settings.extractor_order
               if v in _VENDOR_KEY},
            # ⚠ **모델 이름을 노출한다. 키가 아니다.** 배포본 secret 의
            #   GPT_MODEL 실제 문자열을 밖에서 확인할 방법이 없어서, 발표
            #   숫자의 라벨("gpt-5.4-mini")이 배포본과 같은지 말할 수 없었다.
            #   그 상태를 이 필드로 끝낸다. 화면도 이 값을 읽어 그린다.
            **{f"{v}_model": _VENDOR_MODEL[v]() for v in settings.extractor_order
               if v in _VENDOR_MODEL},
            **extraction_stats.snapshot(),
        },
    }


class MissReport(BaseModel):
    """[D-백] "이 품목이 아닙니다" — 셀러가 등급 카드에서 누른 것.

    ⚠⚠ **신고는 판정을 바꾸지 않는다** (R1). 저장만 한다. 사람이 검수해서
      `새표본235_오답.tsv` 로 옮기고, 그것이 별칭·가드를 고치는 근거가 된다.
      신고 즉시 등급이 사라지면 셀러가 판정기가 되는 것이고, 그것은 없는
      의무를 지우는 쪽으로도 악용된다.

    ⚠ `page_text` 는 스캔과 같은 상한이다. 붙은 품목이 **왜** 오답인지 우리가
      다시 볼 수 있어야 하므로 원문을 그대로 받는다. 개인정보는 셀러가 붙여
      넣은 상세페이지 텍스트라 스캔이 이미 받는 것과 같다.

    ⚠ `extraction_path` 등은 **화면이 `scan.meta` 에서 그대로 넘긴다.** 서버가
      다시 추출하지 않는다 - 그러면 LLM 을 한 번 더 쓰고, 신고 시점의 값과
      달라질 수 있다.
    """

    page_text: str = Field(min_length=1, max_length=200_000)
    matched_items: list[str] = Field(min_length=1, max_length=10)
    # ⚠ 브라우저가 만든 식별자다(owner.js). 같은 셀러가 같은 화면에서 두 번
    #   누른 것을 가리는 데만 쓴다 - 로그인이 아니고 비밀도 아니다. 없으면
    #   멱등 처리를 못 할 뿐 신고는 그대로 저장된다.
    owner_id: str | None = Field(default=None, max_length=64)
    extraction_path: str = Field(max_length=32)
    extractor_vendor: str | None = Field(default=None, max_length=32)
    extractor_model: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class MissReportAck(BaseModel):
    id: str
    reported_at: str
    message: str


@app.post("/api/v1/report-miss", response_model=MissReportAck, status_code=201)
def report_miss(req: MissReport, request: Request, response: Response) -> MissReportAck:
    """오답 신고를 **저장만** 한다. LLM 0회 · 정부 API 0회.

    ⚠ 공개 엔드포인트다. 스캔과 **다른** 버킷으로 분당 10회 - 신고는 드물고,
      스캔 예산을 신고가 갉아먹으면 안 된다.
    """
    client_ip = _client_ip(request)
    if not _report_limiter.allow_request(client_ip):
        raise HTTPException(
            status_code=429,
            detail="신고가 너무 잦습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(_report_limiter.retry_after_seconds(client_ip))},
        )
    # 같은 셀러 · 같은 입력 · 같은 품목이면 같은 신고다.
    #
    # ⚠ 원문을 그대로 키로 쓰지 않는다. 상세페이지 본문이 20만 자까지 오고,
    #   색인에 그것을 통째로 넣을 이유가 없다. 해시로 줄인다.
    # ⚠ 품목은 **정렬**해서 넣는다. 화면이 주는 순서는 서버 후보 순서라
    #   같은 신고에서 바뀔 일이 없지만, 순서가 키를 가르면 "같은 신고" 를
    #   두 번 저장하는 쪽으로 조용히 새 나간다.
    dedupe_key = (
        hashlib.sha256(
            "\u0000".join(
                [req.owner_id or "", text_fingerprint(req.page_text),
                 *sorted(req.matched_items)]
            ).encode("utf-8")
        ).hexdigest()
        if req.owner_id
        else None
    )
    report_id, reported_at, created = _store.save_miss_report(
        uuid4().hex[:12],
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        req.model_dump_json(),
        dedupe_key=dedupe_key,
    )
    if created:
        _log.info("오답 신고 %s · 품목 %s · 경로 %s",
                  report_id, req.matched_items, req.extraction_path)
    else:
        # 두 번째부터는 **저장하지 않았다는 사실**을 남긴다. 조용히 201 을
        # 돌려주면 로그만 보고 "두 번 신고됐다" 로 읽는다.
        _log.info("오답 신고 중복 %s · 품목 %s", report_id, req.matched_items)
    response.status_code = 201 if created else 200
    return MissReportAck(
        id=report_id,
        reported_at=reported_at,
        # ⚠ 단정하지 않는다 (§9). "반영됐다" 가 아니라 "검수하겠다" 다.
        message=(
            "신고가 접수되었습니다. 사람이 검수한 뒤 품목 표에 반영합니다 — 이 결과는 바뀌지 않습니다."
            if created
            else "이미 접수된 신고입니다. 사람이 검수한 뒤 품목 표에 반영합니다 — 이 결과는 바뀌지 않습니다."
        ),
    )


@app.post("/api/v1/sync")
def trigger_sync(
    force_initial: bool = False,
    x_sync_token: str | None = Header(default=None),
) -> dict:
    """리콜 동기화 수동 실행.

    백그라운드 루프의 보조다. 데모 직전에 강제로 최신화하거나, 문제가 생겼을 때
    로그를 보며 돌리기 위해 남긴다.

    토큰이 설정되지 않았으면 403 이다. 미설정을 "인증 없음" 으로 해석하면
    공개된 배포에서 아무나 부를 수 있고, 그러면 정부 API 로 트래픽이 그대로 간다.
    """
    if not settings.sync_token or x_sync_token != settings.sync_token:
        raise HTTPException(status_code=403, detail="유효한 X-Sync-Token 이 필요합니다.")
    # ⚠⚠ **배경 루프와 같은 handler 를 쓴다** (2026-09-18 실측으로 잡았다).
    #
    #   전에는 `on_updated=_recalls.invalidate` 였다 - 색인만 버리고
    #   **전체 스윕을 안 돌렸다.** 그래서 이 경로로 들어온 새 리콜은 워치
    #   항목과 대조되지 않았다. 실측: 수동 동기화로 새 레코드 11건(국내 2 ·
    #   국외 9)이 들어왔는데 `last_full_sweep_at` 이 안 움직였다.
    #
    #   ⚠ 이 docstring 이 "데모 직전에 강제로 최신화" 라고 적은 그 용도가
    #     정확히 위험한 자리다 - 데모 직전에 부르면 새 리콜이 조용히 들어오고
    #     아무에게도 안 알린다. 놓친 알림이 이 서비스가 하는 유일한 약속을
    #     깨뜨린다 (R6 · 기획서 §6.1).
    #
    #   ⚠ 같은 판단을 두 곳에 적지 않는다 (§6). 루프와 이 경로가 **같은 이름**
    #     을 부르고, `tests/test_watch_autosweep.py` 가 그것을 잠근다.
    return run_sync(
        _kats, _store, force_initial=force_initial, on_updated=_on_recalls_updated
    ).to_dict()


@app.get("/api/v1/unknown-reasons", include_in_schema=False)
def unknown_reasons_data() -> dict:
    """회색불 사유 전부. `/unknown` 화면의 **유일한 출처**다.

    ⚠⚠ 화면이 문장을 짓지 않게 하려고 있는 경로다. 사유 문구는 이미
      `scorer` 가 헤드라인으로 쓰고 있고, 여기서 새로 적으면 같은 말이 두
      벌이 된다 - 한쪽만 고쳐질 때 화면이 낡은 말을 한다 (§6).

    ⚠ `unlocks` 는 축 키이고 `unlocks_ko` 가 셀러의 말로 옮긴다. 화면이
      영문 키를 번역하지 않는다.
    """
    from .scorer import unknown_reasons, unlocks_ko

    return {
        "reasons": [
            {
                "key": r.key,
                "title": r.title,
                "body": r.body,
                # 판정 문구도 서버가 준다. 화면이 "열립니다 / 판단했습니다" 를
                # 스스로 고르면 갈래가 늘 때 한쪽만 낡는다 (§6).
                "resolution": r.resolution,
                "verdict": r.verdict_ko,
                "unlocks": list(unlocks_ko(r.unlocks)),
            }
            for r in unknown_reasons()
        ]
    }


@app.get("/api/v1/guide", include_in_schema=False)
def guide_data() -> dict:
    """[M-5] 카테고리 가이드 자료.

    ⚠⚠ **화면에 숫자를 적지 않으려고 있는 경로다.** 카테고리 수·말할 수 있는
      수·라벨 문구까지 전부 여기서 그린다 - HTML 에 적으면 자료가 바뀔 때
      한쪽만 낡는다 (§6 · 랜딩 ④ 와 같은 규칙).
    """
    from .category_guide import rows as _guide_rows, summary as _guide_summary

    return {"summary": _guide_summary(),
            "rows": [r.as_dict() for r in _guide_rows()]}


@app.get("/api/v1/demos", include_in_schema=False)
def demos() -> dict:
    """데모 3종 + 랜딩 히어로의 "예시 결과". 서버가 단일 출처다.

    프론트가 문구를 따로 들고 있으면 서버의 면제 목록과 갈라지고, 상한을
    넘긴 순간 데모 버튼이 429 를 받는다.

    ⚠ 응답이 **배열에서 객체로** 바뀌었다 ([디자인 v2] ⓷). 소비자는
      `landing.html` 하나뿐이지만 `watch` 응답에서 같은 변경을 했을 때
      화면이 조용히 비는 것을 겪었으므로 양쪽을 받게 둔다.

    ⚠ `preview` 는 **랜딩이 `/api/v1/scan` 을 부르지 않게** 하려고 있다.
      부르면 방문마다 LLM 호출이 나가고 투표자가 첫 화면에서 429 를 본다.
      파일이 없으면 `null` 이고, 화면은 그러면 카드를 안 그린다 (R5).
    """
    # ⚠ 대비 한 컷도 여기서 보낸다. 랜딩이 이미 이 하나를 부르므로 왕복이
    #   늘지 않는다 - 첫 화면의 요청 수가 곧 이탈이다.
    return {"items": DEMOS, "preview": demo_preview(), "compare": compare_cut()}


@app.get("/api/v1/misses", include_in_schema=False)
def misses() -> dict:
    """「우리가 틀린 것」. 오답 8 · 애매 4 · 못 맞힌 19 을 그대로 내놓는다.

    ⚠ 수는 `baseline.BASELINE` 과 같아야 한다 - 자료를 만드는 스크립트가
      어긋나면 파일을 만들지 않으므로 여기 오는 수는 언제나 발표 숫자다.
    """
    return sample_misses()


@app.get("/api/v1/samples", include_in_schema=False)
def samples() -> dict:
    """체험 표본 기록본. **우리가 실제로 낸 결과**를 그대로 얼려 둔 것이다.

    ⚠ 이 경로는 LLM·정부 API 를 부르지 않는다. 투표 18일 × 공개 접근 × 10개를
      면제 지문으로 두면 상한 없는 비용이고, 첫 10초에 6초 대기가 붙는다
      (총괄 판정 2026-09-19 §2).

    ⚠ 화면에는 **"지금 다시 검사"** 가 함께 있고 그것은 `/scan?sample=<번호>`
      로 가서 **면제가 아닌 일반 예산 안의** `/api/v1/scan` 을 부른다. 기록만
      보여 준다는 의심에 대한 답이 화면 안에 있어야 한다.
    """
    return sample_payload()


def _client_ip(request: Request) -> str:
    """Fly 는 원 IP 를 헤더로 넘긴다. 없으면 프록시 IP 하나로 뭉쳐 전원이 막힌다."""
    forwarded = request.headers.get("fly-client-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RfLookupRequest(BaseModel):
    model_name: str = Field(min_length=1, max_length=120)


class RfLookupResult(BaseModel):
    model_name: str
    findings: list[Finding]


@app.post("/api/v1/rf-lookup", response_model=RfLookupResult)
def rf_lookup(req: RfLookupRequest, request: Request) -> RfLookupResult:
    """모델명으로 적합성평가(전파인증)를 조회한다. 화면 버튼이 부르는 경로다.

    스캔에서 분리한 이유는 속도다. RRA 검색은 결과가 있으면 실측 12초라
    스캔에 넣으면 무선 상품마다 13초가 되고, 기획서 §8 의 "캐시 히트 3초 이내"
    가 깨진다. ⑦ 의 KC 이미지 확인 버튼과 같은 패턴으로, 셀러가 소요 시간을
    인지한 상태에서 누르게 한다.

    ⚠ 호출 상한 대상이다. 12초짜리 요청이라 반복 호출이 스캔보다 비싸다.
    """
    client_ip = _client_ip(request)
    if not _limiter.allow_request(client_ip):
        raise HTTPException(
            status_code=429,
            detail="요청이 잠시 많습니다. 1분 뒤에 다시 시도해 주세요.",
            headers={"Retry-After": str(_limiter.retry_after_seconds(client_ip))},
        )
    return RfLookupResult(
        model_name=req.model_name,
        findings=verify_rf_by_model(req.model_name, _rra),
    )


@app.post("/api/v1/batch")
def batch(req: BatchRequest, request: Request) -> dict:
    """대량 1차 선별. LLM 을 쓰지 않으므로 200건이 0.1초에 끝난다.

    배치는 **상품명만** 본다. 상세페이지가 없으니 재질·연령을 알 수 없고,
    리콜 모델명 매칭도 약하다. 그래서 결과는 1차 선별이고, 걸러진 것을 단건
    검사로 다시 보는 흐름이다 - 안 본 것을 봤다고 말하지 않는다 (R3).
    """
    client_ip = _client_ip(request)
    if not _limiter.allow_request(client_ip, fingerprint=text_fingerprint(req.text)):
        raise HTTPException(
            status_code=429,
            detail="요청이 잠시 많습니다. 1분 뒤에 다시 시도해 주세요.",
            headers={"Retry-After": str(_limiter.retry_after_seconds(client_ip))},
        )

    book = _grade_book()
    if book is None:
        # 등급표를 못 읽으면 배치가 할 일이 없다. 감추지 않고 알린다.
        raise HTTPException(
            status_code=503,
            detail="품목 등급표를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )
    report = screen(req.text, book)
    return {
        "total": len(report.rows),
        "truncated": report.truncated,
        "max_rows": MAX_ROWS,
        "counts": report.counts,
        "scope_note": (
            "대량 검사는 상품명만 봅니다. 재질·연령·인증번호는 상세페이지에 있으므로, "
            "여기서 걸러진 상품은 단건 검사로 다시 확인하세요."
        ),
        "rows": [
            {
                "line": r.line,
                "product_name": r.product_name,
                "verdict": r.verdict.value,
                "reason": r.reason,
                "grade": r.grade,
                "matched_item": r.matched_item,
                "matched_items": r.matched_items,
                "grade_candidates": r.grade_candidates,
                "cert_numbers": r.cert_numbers,
                "rf_numbers": r.rf_numbers,
            }
            for r in report.review_first
        ],
    }


@app.post("/api/v1/scan", response_model=ScanResult)
def scan(req: ScanRequest, request: Request) -> ScanResult:
    fp = text_fingerprint(req.page_text)
    client_ip = _client_ip(request)

    if not _limiter.allow_request(client_ip, fingerprint=fp):
        raise HTTPException(
            status_code=429,
            detail="요청이 잠시 많습니다. 1분 뒤에 다시 시도해 주세요.",
            headers={"Retry-After": str(_limiter.retry_after_seconds(client_ip))},
        )

    # 상한을 넘겨도 멈추지 않는다. LLM 대신 휴리스틱으로 내리고 그 사실을 적는다.
    allow_llm = _limiter.take_llm_budget(fingerprint=fp)
    imgs = [{"media_type": i.media_type, "data": i.data} for i in req.images]
    # ⚠ **건별 경로를 함께 받는다.** `/healthz` 의 extraction 은 프로세스
    #   누적값이라 "이 스캔" 을 말할 수 없다 - 2026-09-08 사고의 뿌리가 그것이다.
    facts, trace = extract_traced(
        req.page_text, req.page_url, images=imgs, allow_llm=allow_llm
    )
    # 어느 번호가 어느 제도인지 verifier 가 정한다 (4-d-3). verify() 머리에서도
    # 부르지만 **여기서도** 불러야 한다 - score() 에 넘기는 facts 가 화면의
    # "읽은 값" 패널이고, 거기에 전파번호가 KC 번호로 남으면 findings 와
    # 화면이 어긋난다. 멱등이므로 두 번 불러도 같다.
    facts = split_cert_regimes(facts)
    findings = verify(
        facts, _kats, _rules, _recalls, _rra, _noncompliant,
        hints=req.seller_hints,
        # 표지어 게이트 전용. LLM 이 요약하면서 떨어뜨린 '초등'·'EVA'·'물놀이'
        # 를 게이트가 다시 볼 수 있게 한다 - 셀러가 페이지에 적은 사실이다.
        raw_text=req.page_text,
    )
    # 공표일과 갱신 시각을 함께 넘긴다. 공표일만 화면에 적으면 셀러가
    # "3일 전 데이터" 로 읽는데, 주말·공휴일에는 정부 공표가 없어서 공표일이
    # 며칠 전인 것이 정상이다. /healthz 가 이미 주는 값이다.
    #
    # ⚠⚠ **`last_sync_ok_at` 이다. `last_sync_at`(시도 시각)이 아니다.**
    #   2026-09-15~18 에 호출이 사흘 실패하는 동안 화면이 "어제 갱신" 이라고
    #   말했다 - 아무것도 못 받아 온 시도의 시각이었다. 못 받아 왔으면 이 값이
    #   없고, `_sync_label` 이 빈 문자열을 돌려주어 "…갱신" 절이 안 붙는다.
    #
    # ⚠ `today` 는 **KST** 다. 컨테이너가 UTC 라 "오늘 02:06 갱신" 이 떴는데
    #   한국은 11:06 이었다. 여기만 바꾼다 - 스윕(771)·워치(896·968)의
    #   `date.today()` 는 저장·만료 기준이라 손대지 않는다.
    result = score(
        facts,
        findings,
        recall_data_as_of=_recalls.as_of,
        recall_synced_at=_store.get_sync_state("last_sync_ok_at"),
        today=datetime.now(KST).date(),
        # 화면 상단 두 줄이 읽는 값. 하드코딩 금지.
        meta=ScanMeta(
            extracted_by=trace.label_ko,
            extraction_path=trace.path,
            extractor_vendor=trace.vendor,
            extractor_model=trace.model,
            extraction_reason=trace.reason,
            # ⚠ **이 스캔에서 정부 조회가 됐나** (4-p). /healthz 의 kats 는
            #   프로세스 누적값이라 "이 결과" 를 말하지 못한다.
            gov_lookup=gov_lookup_state(findings),
        ),
    )
    # 유효 결과율 (E). 판정에 쓰지 않는다 - 세기만 한다.
    _result_stats.record(specific=has_specific_finding(result.findings))

    if not allow_llm:
        result.extraction_note = (
            "오늘 분석 한도에 도달해 간이 추출로 처리했습니다. "
            "상품명·제조사가 덜 정확할 수 있으니 결과의 인증번호를 확인해 주세요."
        )
    return result


# ---------------------------------------------------------------------------
# Watchlist (기획서 §3-4단계)
#
# v1 scope: register + **automatic** sweep + display. Notification delivery
# (email/Kakao) is explicitly out of scope for the 9/20 submission.
#
# ⚠ 2026-09-09 갱신 (C-백): "on-demand sweep" 이었다. 셀러가 `/watch` 화면에서
#   버튼을 눌러야만 스윕이 돌았고, 그러면 **화면을 안 열어 본 셀러는 리콜이
#   공표돼도 모른다.** §6.1 이 유일하게 보증한다고 적은 것이 "나중에 리콜
#   공표되면 가장 먼저 알린다" 인데 사람이 눌러야 도는 것은 그 보증이 아니다.
#   이제 리콜 동기화가 새 레코드를 쓰면 `_on_recalls_updated` 가 전체 스윕을
#   돌리고 알림을 `recall_alerts` 에 남긴다. 버튼(`/api/v1/watch/sweep`)은
#   그대로 남긴다 - 데모에서 즉시 돌려 보여야 한다.
#
# ⚠ **전달(delivery)은 여전히 범위 밖이다.** 알림을 저장하고 화면에 보이게 한
#   것이지 메일·카카오로 보내는 것이 아니다. [K] 다.
#
# 저장은 SQLite. 재시작으로 워치리스트를 잃으면 셀러는 감시받고 있다고 믿는 채로
# 감시되지 않는다 (기획서 §6.1). 배포 시 WATCHLIST_DB_PATH 를 영구 볼륨으로.
# ---------------------------------------------------------------------------
_store = SqliteWatchStore(settings.watchlist_db_path)
# 부적합 현황 로컬 사본 위의 매칭. 전파인증 축의 유일한 RED 소스다.
_noncompliant = NoncompliantIndex(_store)

# 리콜 로컬 사본 위의 매칭. 스캔과 워치리스트 스윕이 같은 watchlist.match() 를
# 쓰게 하는 지점이다 (이전에는 스캔만 API 검색이라 결과가 갈릴 수 있었다).
_recalls = RecallIndex(_store)

# 호출 상한. 데모 3종은 지문으로 면제한다 - 투표자가 첫 화면에서 버튼을
# 눌렀는데 429 를 보면 그대로 이탈한다 (핸드오프 §9).
_limiter = RateLimiter()
_limiter.register_exempt(*DEMO_TEXTS)
# [D-백] 오답 신고 전용 버킷. 스캔 예산과 섞지 않는다.
_report_limiter = RateLimiter(per_minute=10)


def _full_sweep(*, on: date | None = None) -> dict:
    """**활성 워치 전체**를 리콜 로컬 사본과 대조하고 결과를 남긴다 (C-백).

    리콜 동기화가 새 레코드를 썼을 때 자동으로 돈다. 전에는 셀러가 `/watch`
    화면에서 버튼을 눌러야만 스윕이 돌았다 - 그러면 **화면을 안 열어 본 셀러는
    리콜이 공표돼도 모른다.** 기획서 §6.1 이 유일하게 보증한다고 적은 것이
    "나중에 리콜 공표되면 가장 먼저 알린다" 인데, 사람이 눌러야 도는 것은 그
    보증이 아니다.

    ⚠ **순서가 중요하다.** `_recalls.invalidate()` 를 먼저 부르고 스윕한다.
      순서를 바꾸면 방금 들어온 레코드를 못 보고 지나간다 - 조용히 놓치는
      알림이고, 그게 이 서비스가 가장 하지 말아야 할 실패다 (R6).

    ⚠ **정부 API 를 부르지 않는다.** 스윕은 로컬 사본(`RecallIndex`) 위에서
      돈다. `run_sweep` 의 docstring 이 적어 둔 그 전환 덕분이다 - 워치 항목이
      N개여도 정부 호출은 **0회**다. 그래서 전체 스윕을 자동화해도 부담이 없다.

    ⚠ `sweep()` 은 순수 함수다. 저장과 시각 기록만 여기서 한다.
    """
    today = on or date.today()
    items = list(_store.active_items())
    alerts = sweep(items, _recalls.all_records(), today=today)

    # 지문을 남겨 다음 스윕에서 같은 리콜을 다시 알리지 않는다. 알림이 없었어도
    # 스윕 일자는 기록한다 - "언제까지 확인했다" 가 셀러에게 보이는 정보다.
    by_item: dict[str, list[str]] = {i.id: [] for i in items}
    for a in alerts:
        by_item[a.watch_item_id].append(a.recall_fingerprint)
    for item_id, fps in by_item.items():
        _store.mark_swept(item_id, today, fps)

    # ⚠ **저장된 수를 센다.** `sweep()` 이 낸 수가 아니다 - 같은 리콜을 두 번
    #   세면 "새 알림 N" 이 거짓이 된다.
    new_count = _store.save_alerts(alerts)
    _store.set_sync_state("last_full_sweep_at", datetime.now(timezone.utc)
                          .isoformat(timespec="seconds"))
    _store.set_sync_state("last_full_sweep_items", str(len(items)))
    _store.set_sync_state("last_full_sweep_new", str(new_count))
    if new_count:
        _log.info("전체 스윕: 워치 %d개 · 새 알림 %d건", len(items), new_count)
    return {"items": len(items), "new_alerts": new_count}


def _as_int(raw: str | None) -> int | None:
    """`sync_state` 의 TEXT 값을 숫자로. 값이 없으면 **None 이다.**

    ⚠ 0 으로 채우지 않는다 - "아직 한 번도 안 돌았다" 와 "돌았는데 0건" 은
      다르다. 전자를 0 으로 만들면 스윕이 안 도는 것을 못 본다 (R3).
    """
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _baseline_snapshot() -> dict:
    """발표 숫자 다섯 중 **랜딩이 그리는 둘** + 라벨에 필요한 분모·추출기.

    ⚠ 상한(`ok_upper`)은 내지 않는다. 랜딩에서 뺀 숫자다 - 검수 전 숫자를
      검수된 숫자처럼 읽게 만든 전례가 있어(제출문 82.2%) 화면에 두지 않는다.
      기획서 링크로만 간다 (design/README §10-2).
    """
    b = BASELINE[BASELINE_EXTRACTOR]
    return {
        "extractor": BASELINE_EXTRACTOR,
        "denominator": b["denominator"],
        "ok": b["ok"],
        # 소수 한 자리. 화면이 다시 계산하면 반올림이 갈린다.
        "ok_rate": round(b["ok"] / b["denominator"] * 100, 1),
        "off_target": b["off_target"],
    }


def _sweep_snapshot(owner_id: str | None = None) -> dict:
    """"마지막 대조 · 알림 N". 화면 상단과 `/healthz` 가 읽는 값.

    ⚠⚠ **화면이 읽어야 하는 값과 운영이 읽는 값이 다르다**
      ([C-화면] 실물 확인 · 2026-09-13).

      `last_full_sweep_*` 는 **전체 배치**의 기록이다 - 모든 소유자를 한 번에
      돌고 결과를 전역 한 줄에 적는다. 그것을 셀러 화면 머리말에 그대로 쓰면
      두 가지가 거짓이 된다. 둘 다 잰 것이다:

        ① "새 알림 N" 이 **남의 알림 수**다. 사본 DB 에 소유자 둘을 넣고
           전체 스윕 1회를 돌렸더니, 저장된 알림이 **0건**인 owner-B 의
           머리말이 "새 알림 1" 을 그렸다 - 그 1건은 owner-A 것이다.
           **없는데 있다고 하는 쪽**이라 더 비싸다 (§6).
        ② 버튼(`run_sweep`)은 이 값을 **갱신하지 않는다.** 누르기 전/후
           `last_full_sweep_at` 이 동일했다(항목의 `last_swept_at` 만 움직인다).
           셀러가 "지금 대조하기" 를 눌러도 "마지막 대조" 가 그대로다 -
           이 화면이 약속하는 것이 "언제까지 확인했나" 인데 그것이 틀린다.

      그래서 소유자가 주어지면 **소유자별 값**(`last_swept_at`)을 함께 낸다.
      화면은 소유자별 값만 읽는다. `last_full_sweep_*` 는 지우지 않는다 -
      `/healthz` 가 "배치가 도는가" 를 보는 운영 지표이고, 그것은 전역이
      맞다.

    ⚠ 소유자 없이 부르면(`/healthz`) `last_swept_at` 은 None 이다. 0 이나
      오늘 날짜로 채우지 않는다 - "안 물었다" 와 "없다" 는 다르다 (R3).
    """
    last_swept: str | None = None
    if owner_id is not None:
        days = [i.last_swept_at for i in _store.for_owner(owner_id) if i.last_swept_at]
        last_swept = max(days).isoformat() if days else None
    return {
        # 소유자별 - **화면이 읽는 값이다.**
        "last_swept_at": last_swept,
        # 전역 - 운영 지표. 화면에 그대로 쓰면 위 ①②가 된다.
        "last_full_sweep_at": _store.get_sync_state("last_full_sweep_at"),
        # ⚠ **숫자는 int 로 낸다.** `sync_state` 는 TEXT 저장소라 문자열이
        #   나오는데, 그대로 내보내면 화면이 `"5"` 를 받아 비교·합산에서
        #   조용히 틀린다("5" > "10" 이 참이다). 스키마 검사가 타입까지 본다.
        "last_full_sweep_items": _as_int(_store.get_sync_state("last_full_sweep_items")),
        "last_full_sweep_new": _as_int(_store.get_sync_state("last_full_sweep_new")),
        "alerts_stored": _store.alert_count(owner_id=owner_id),
    }


def _on_recalls_updated() -> None:
    """리콜 사본이 갱신되면 색인을 버리고 **전체 스윕까지** 돈다.

    ⚠ 스윕이 죽어도 동기화는 계속돼야 한다. 남의 API 장애로 우리 루프를 멈추지
      않는 것과 같은 원칙이다.
    """
    _recalls.invalidate()
    try:
        _full_sweep()
    except Exception:  # noqa: BLE001
        _log.exception("전체 스윕 실패 - 동기화는 계속한다")


class WatchRequest(BaseModel):
    owner_id: str
    facts_from_scan: dict


@app.post("/api/v1/watch", response_model=WatchItem)
def register_watch(req: WatchRequest) -> WatchItem:
    from .models import ProductFacts

    facts = ProductFacts(**req.facts_from_scan)
    item = WatchItem.from_facts(
        id=uuid4().hex[:12], owner_id=req.owner_id, facts=facts, on=date.today()
    )
    if not item.is_matchable():
        raise HTTPException(
            422,
            "모델명·인증번호·제조사 중 하나는 있어야 리콜 감시가 가능합니다. "
            "상세페이지에서 추출된 정보가 부족합니다.",
        )
    return _store.add(item)


@app.delete("/api/v1/watch/{item_id}", status_code=204)
def unwatch(item_id: str, owner_id: str) -> Response:
    """감시 해제. **소유자가 맞을 때만** 지운다.

    셀러가 넣은 것을 못 지우는 상태를 없앤다 - 잘못 등록한 항목이 목록에
    영원히 남으면 진짜 알림이 그 사이에 묻힌다 (R6 의 반대 방향 비용이다).

    ⚠ **없는 id 와 남의 id 를 구분하지 않는다.** 둘 다 404 다. 구분하면
      "그 id 는 존재한다" 를 남에게 알려 주는 셈이다. `owner_id` 는 브라우저가
      만든 식별자라 비밀이 아니지만, 그렇다고 목록을 열어 줄 이유도 없다.

    ⚠ 그 항목의 알림도 같이 지운다 (`SqliteWatchStore.remove`).
    """
    if not _store.remove(item_id, owner_id):
        raise HTTPException(404, "감시 목록에서 찾지 못했습니다.")
    return Response(status_code=204)


class WatchListResponse(BaseModel):
    """감시 목록 + **언제까지 확인했나** (C-백).

    ⚠ 응답 모양이 배열에서 객체로 바뀌었다. 화면이 "마지막 sweep 시각" 을
      읽어야 하고, 그것을 헤더나 별도 엔드포인트로 빼면 두 곳을 맞춰야 한다.
      `watch.html` 은 `data.items || data` 로 양쪽을 받게 한 줄만 고쳤다 -
      **표시는 주말 묶음이다**(미완 §6 [C-화면]).
    """

    items: list[WatchItem]
    sweep: dict
    alerts: list[RecallAlert]


@app.get("/api/v1/watch", response_model=WatchListResponse)
def list_watch(owner_id: str) -> WatchListResponse:
    """이 소유자가 감시 중인 상품 목록 + 마지막 스윕 · 저장된 알림.

    ⚠ 알림을 **저장된 것에서** 낸다. 전에는 버튼을 눌러 방금 스윕한 결과만
      화면에 있었고, 화면을 안 열어 본 사이의 알림은 사라졌다.
    """
    return WatchListResponse(
        items=_store.for_owner(owner_id),
        sweep=_sweep_snapshot(owner_id),
        alerts=_store.alerts_for_owner(owner_id),
    )


@app.post("/api/v1/watch/sweep", response_model=list[RecallAlert])
def run_sweep(owner_id: str) -> list[RecallAlert]:
    """이 사용자의 워치 항목을 리콜 로컬 사본과 대조한다.

    이전에는 항목마다 _kats.search_recalls() 를 불렀다. 문제가 두 개였다.

      ① 워치 항목 N개면 정부 API 호출이 N회다. 매일 도는 흐름에서 그대로 부담이
         된다. 로컬 사본을 쓰면 0회다.
      ② 모델명으로 검색한 결과에만 매칭해서, 인증번호로만 일치하는 리콜을
         구조적으로 놓쳤다. match() 가 인증번호를 봐도 그 레코드가 애초에
         응답에 없으면 소용이 없다. 놓친 알림은 이 서비스가 하는 유일한
         약속을 깨뜨린다 (CLAUDE.md R6).

    이제 스캔과 스윕이 같은 로컬 사본 위에서 같은 match() 를 쓴다.
    """
    today = date.today()
    items = _store.for_owner(owner_id)
    alerts = sweep(items, _recalls.all_records(), today=today)

    # 지문을 남겨 다음 스윕에서 같은 리콜을 다시 알리지 않는다. 알림이 없었어도
    # 스윕 일자는 기록한다 — "언제까지 확인했다"가 셀러에게 보이는 정보다.
    by_item: dict[str, list[str]] = {i.id: [] for i in items}
    for a in alerts:
        by_item[a.watch_item_id].append(a.recall_fingerprint)
    for item_id, fps in by_item.items():
        _store.mark_swept(item_id, today, fps)
    # 버튼으로 돈 스윕도 남긴다 - 저장하지 않으면 화면을 닫는 순간 사라진다.
    _store.save_alerts(alerts)
    return alerts
