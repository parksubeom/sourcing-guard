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
from .kats_client import KatsClient
from .models import RecallAlert, ScanResult, WatchItem
from .scorer import score
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
    return {
        "ok": True,
        "mock_mode": settings.mock_mode,
        "active_rules": len(_rules.active),
        "draft_rules": len(_rules.drafts),
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
# TODO(v1): replace _WATCH with SQLite behind the WatchRepository protocol.
# In-memory storage is fine for the demo but loses data on restart, which is
# unacceptable once sellers rely on the alerting promise.
# ---------------------------------------------------------------------------
_WATCH: dict[str, WatchItem] = {}


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
    _WATCH[item.id] = item
    return item


@app.post("/api/v1/watch/sweep", response_model=list[RecallAlert])
def run_sweep(owner_id: str) -> list[RecallAlert]:
    """Compare this owner's watched items against current recall records."""
    items = [i for i in _WATCH.values() if i.owner_id == owner_id]
    recalls = []
    for i in items:
        recalls.extend(
            _kats.search_recalls(product_name=i.product_name, model_name=i.model_name)
        )
    alerts = sweep(items, recalls, today=date.today())
    for a in alerts:  # suppress repeats on the next sweep
        _WATCH[a.watch_item_id].seen_recall_fingerprints.append(a.recall_fingerprint)
    return alerts
