"""FastAPI entrypoint. Chrome extension posts a DOM snapshot here.

CLAUDE.md R4: the server never fetches commerce pages itself.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from datetime import date
from uuid import uuid4

from .config import settings
from .extractor import extract
from .kats_client import KatsClient, health
from .noncompliant_index import NoncompliantIndex
from .rra_client import RraClient
from .models import Finding, RecallAlert, ScanResult, SellerHints, WatchItem
from .scorer import score
from .demos import DEMOS, DEMO_TEXTS
from .ratelimit import RateLimiter, text_fingerprint
from .recall_index import RecallIndex
from .storage import SqliteWatchStore
from .sync import run_sync, sync_loop
from .verifier import RuleBook, verify, verify_rf_by_model
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
                on_updated=_recalls.invalidate,
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


class ScanImage(BaseModel):
    # 중국 도매 상세페이지는 상품정보 표가 통짜 이미지인 경우가 많다.
    # media_type 은 허용 목록으로 제한하고, 개수·크기 상한으로 LLM 비용을 막는다.
    media_type: Literal["image/jpeg", "image/png", "image/webp", "image/gif"]
    data: str = Field(min_length=1, max_length=8_000_000)  # base64, 원본 약 6MB


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
        "limits": _limiter.snapshot(),
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
    facts = extract(req.page_text, req.page_url, images=imgs, allow_llm=allow_llm)
    findings = verify(
        facts, _kats, _rules, _recalls, _rra, _noncompliant,
        hints=req.seller_hints,
    )
    result = score(facts, findings, recall_data_as_of=_recalls.as_of)
    if not allow_llm:
        result.extraction_note = (
            "오늘 분석 한도에 도달해 간이 추출로 처리했습니다. "
            "상품명·제조사가 덜 정확할 수 있으니 결과의 인증번호를 확인해 주세요."
        )
    return result


# ---------------------------------------------------------------------------
# Watchlist (기획서 §3-4단계)
#
# v1 scope: register + on-demand sweep + display. Notification delivery
# (email/Kakao) is explicitly out of scope for the 9/20 submission.
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


@app.get("/api/v1/watch", response_model=list[WatchItem])
def list_watch(owner_id: str) -> list[WatchItem]:
    """이 소유자가 감시 중인 상품 목록."""
    return _store.for_owner(owner_id)


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
    return alerts
