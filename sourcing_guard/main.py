"""FastAPI entrypoint. Chrome extension posts a DOM snapshot here.

CLAUDE.md R4: the server never fetches commerce pages itself.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from datetime import date
from uuid import uuid4

from .config import settings
from .extractor import extract
from .kats_client import KatsClient, health
from .models import RecallAlert, ScanResult, WatchItem
from .scorer import score
from .storage import SqliteWatchStore
from .verifier import RuleBook, verify
from .watchlist import sweep

app = FastAPI(title="안심 소싱 돋보기 API", version="0.1.0")

_kats = KatsClient(settings.kats_base_url, settings.kats_service_key, mock=settings.mock_mode)
_rules = RuleBook()


class ScanRequest(BaseModel):
    page_text: str = Field(min_length=1, max_length=200_000)
    page_url: str | None = None


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
    }


@app.post("/api/v1/scan", response_model=ScanResult)
def scan(req: ScanRequest) -> ScanResult:
    facts = extract(req.page_text, req.page_url)
    findings = verify(facts, _kats, _rules)
    return score(facts, findings)


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
    """Compare this owner's watched items against current recall records."""
    today = date.today()
    items = _store.for_owner(owner_id)
    recalls = []
    for i in items:
        recalls.extend(
            _kats.search_recalls(product_name=i.product_name, model_name=i.model_name)
        )
    alerts = sweep(items, recalls, today=today)

    # 지문을 남겨 다음 스윕에서 같은 리콜을 다시 알리지 않는다. 알림이 없었어도
    # 스윕 일자는 기록한다 — "언제까지 확인했다"가 셀러에게 보이는 정보다.
    by_item: dict[str, list[str]] = {i.id: [] for i in items}
    for a in alerts:
        by_item[a.watch_item_id].append(a.recall_fingerprint)
    for item_id, fps in by_item.items():
        _store.mark_swept(item_id, today, fps)
    return alerts
