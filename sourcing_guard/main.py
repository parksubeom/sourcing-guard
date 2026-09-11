"""FastAPI entrypoint. Chrome extension posts a DOM snapshot here.

CLAUDE.md R4: the server never fetches commerce pages itself.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from datetime import date, datetime, timezone
from uuid import uuid4

from .config import settings
from .batch import MAX_ROWS, BatchReport, screen
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
from .scorer import gov_lookup_state, has_specific_finding, score
from .demos import DEMOS, DEMO_TEXTS

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
from .watchlist import sweep

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """리콜 동기화 백그라운드 루프.

    시작 시 1회 실행하고 이후 하루 한 번 돈다. 재배포하면 몇 시간 공백이
    생기는데 뜨자마자 한 번 돌면 그 공백이 사라진다 (증분은 400KB 다).

    루프가 죽어도 앱은 계속 뜬다. 정부 API 장애로 스캔까지 멈추면 안 된다.
    """
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


_STATIC = Path(__file__).parent / "static"


@app.get("/", response_class=FileResponse, include_in_schema=False)
def index() -> FileResponse:
    """단일 페이지 프론트엔드.

    빌드 단계를 두지 않는다. 정적 HTML 하나를 그대로 돌려주면 되고, 그 편이
    투표 기간 18일 무중단에 유리하다 - 깨질 지점이 하나 줄어든다.
    """
    return FileResponse(_STATIC / "index.html", media_type="text/html; charset=utf-8")


@app.get("/batch", response_class=FileResponse, include_in_schema=False)
def batch_page() -> FileResponse:
    """대량 검사 화면.

    셀러는 상품을 한 건씩 붙여넣지 않는다 - 도매 플랫폼에서 엑셀을 받아
    수백 건을 한 번에 올린다. API 만 있고 화면이 없으면 그 흐름에 못 들어간다.
    """
    return FileResponse(_STATIC / "batch.html", media_type="text/html; charset=utf-8")


@app.get("/watch", response_class=FileResponse, include_in_schema=False)
def watch_page() -> FileResponse:
    """감시 목록 화면.

    기획서 §3-4단계. 스캔은 시점 판단이라 "지금 안전하다"를 보증할 수 없지만,
    "나중에 리콜 공표되면 놓치지 않는다"는 보증할 수 있다. 그것이 이 서비스가
    유일하게 약속하는 것이고, 그래서 별도 화면을 준다.
    """
    return FileResponse(_STATIC / "watch.html", media_type="text/html; charset=utf-8")


@app.get("/healthz")
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
        "kats": health.snapshot(),
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
        # 유효 결과율 - 매칭률과 별개로 우리가 움직여야 할 지표다 (E).
        # ⚠ 프로세스 메모리이고 단건 경로만 센다. note 에 그 사실을 적는다.
        "results": _result_stats.snapshot(),
        "extraction": {
            "order": list(settings.extractor_order),
            "claude_key": bool(settings.anthropic_api_key),
            "gpt_key": bool(settings.gpt_api_key),
            # ⚠ **모델 이름을 노출한다. 키가 아니다.** 배포본 secret 의
            #   GPT_MODEL 실제 문자열을 밖에서 확인할 방법이 없어서, 발표
            #   숫자의 라벨("gpt-5.4-mini")이 배포본과 같은지 말할 수 없었다.
            #   그 상태를 이 두 필드로 끝낸다. 화면도 이 값을 읽어 그린다.
            "claude_model": settings.extractor_model,
            "gpt_model": settings.gpt_model,
            **extraction_stats.snapshot(),
        },
    }


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
    return run_sync(
        _kats, _store, force_initial=force_initial, on_updated=_recalls.invalidate
    ).to_dict()


@app.get("/api/v1/demos", include_in_schema=False)
def demos() -> list[dict]:
    """데모 3종. 서버가 단일 출처다.

    프론트가 문구를 따로 들고 있으면 서버의 면제 목록과 갈라지고, 상한을
    넘긴 순간 데모 버튼이 429 를 받는다.
    """
    return DEMOS


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
    result = score(
        facts,
        findings,
        recall_data_as_of=_recalls.as_of,
        recall_synced_at=_store.get_sync_state("last_sync_at"),
        today=date.today(),
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


def _sweep_snapshot(owner_id: str | None = None) -> dict:
    """"마지막 sweep 시각 · 새 알림 N". 화면 상단이 읽는 값 (주말 배선)."""
    return {
        "last_full_sweep_at": _store.get_sync_state("last_full_sweep_at"),
        "last_full_sweep_items": _store.get_sync_state("last_full_sweep_items"),
        "last_full_sweep_new": _store.get_sync_state("last_full_sweep_new"),
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
