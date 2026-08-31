"""Watchlist sweep — deterministic recall matching (기획서 §3-4단계).

No LLM here (CLAUDE.md R1). Matching is string normalisation plus explicit
tiers, so an alert can always be explained to a seller in one sentence.

Storage is abstracted behind WatchRepository so v1 can ship on SQLite and
move later without touching the matching rules.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Protocol

from .kats_client import RecallRecord, normalize_kc
from .models import MatchStrength, RecallAlert, WatchItem, WatchStatus

# Model names shorter than this produce too many coincidental hits
# ("A1", "100") to be worth alerting on.
_MIN_EXACT_LEN = 3
_MIN_CONTAIN_LEN = 5
_MIN_TOKEN_OVERLAP = 2

_STOPWORDS = {
    "세트", "정품", "무료배송", "당일발송", "신상", "특가", "대용량", "고급",
    "SET", "NEW", "HOT", "FREE",
}


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------
def normalize_model(raw: str | None) -> str:
    """Collapse a model string to comparable form.

    Sourcing pages write the same model as 'BLK-100', 'ＢＬＫ 100', 'blk100'.
    """
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw).upper()
    return re.sub(r"[^A-Z0-9가-힣]", "", s)


def tokenize_name(raw: str | None) -> set[str]:
    if not raw:
        return set()
    s = unicodedata.normalize("NFKC", raw).upper()
    tokens = {t for t in re.split(r"[^A-Z0-9가-힣]+", s) if len(t) >= 2}
    return tokens - _STOPWORDS


def recall_fingerprint(r: RecallRecord) -> str:
    """Stable id for a recall notice, so repeat sweeps do not re-alert."""
    parts = "|".join(
        [r.scope, r.model_name or "", r.product_name or "", r.maker or "", r.announced_on or ""]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Match:
    strength: MatchStrength
    matched_on: str


def match(item: WatchItem, r: RecallRecord) -> Match | None:
    """Return the strongest match tier, or None.

    Tiers are ordered and mutually exclusive; the first hit wins.
    """
    wm, rm = normalize_model(item.model_name), normalize_model(r.model_name)

    if wm and rm and len(wm) >= _MIN_EXACT_LEN and wm == rm:
        return Match(MatchStrength.EXACT, "model_name")

    # A recall notice sometimes carries the cert number inside the model field.
    if item.kc_numbers and rm:
        for kc in item.kc_numbers:
            n = normalize_kc(kc)
            if n and len(n) >= _MIN_EXACT_LEN and n in rm:
                return Match(MatchStrength.EXACT, "kc_number")

    if wm and rm and (len(wm) >= _MIN_CONTAIN_LEN or len(rm) >= _MIN_CONTAIN_LEN):
        if wm in rm or rm in wm:
            return Match(MatchStrength.STRONG, "model_name")

    if item.maker and r.maker:
        if normalize_model(item.maker) == normalize_model(r.maker):
            overlap = tokenize_name(item.product_name) & tokenize_name(r.product_name)
            if len(overlap) >= _MIN_TOKEN_OVERLAP:
                return Match(MatchStrength.WEAK, "maker+product")

    return None


# ---------------------------------------------------------------------------
# sweep
# ---------------------------------------------------------------------------
class WatchRepository(Protocol):
    """저장소 계약. sweep() 자체는 이걸 쓰지 않는다 — 순수 함수로 남기려고
    호출자가 데이터를 넣어주고 결과를 저장한다. 구현은 storage.SqliteWatchStore.
    """

    def add(self, item: WatchItem) -> WatchItem: ...
    def get(self, item_id: str) -> WatchItem | None: ...
    def active_items(self) -> Iterable[WatchItem]: ...
    def for_owner(self, owner_id: str, *, active_only: bool = True) -> list[WatchItem]: ...
    def mark_swept(self, item_id: str, on: date, new_fingerprints: list[str]) -> None: ...


def sweep(
    items: Iterable[WatchItem],
    recalls: Iterable[RecallRecord],
    *,
    today: date,
    min_strength: MatchStrength = MatchStrength.WEAK,
) -> list[RecallAlert]:
    """Compare watched items against a day's recall records.

    Pure function: caller supplies the data and persists the result. Same
    inputs always yield the same alerts, in the same order.
    """
    order = {MatchStrength.WEAK: 0, MatchStrength.STRONG: 1, MatchStrength.EXACT: 2}
    floor = order[min_strength]
    recalls = list(recalls)

    alerts: list[RecallAlert] = []
    for item in items:
        if item.status is not WatchStatus.ACTIVE or not item.is_matchable():
            continue
        seen = set(item.seen_recall_fingerprints)
        for r in recalls:
            fp = recall_fingerprint(r)
            if fp in seen:
                continue
            m = match(item, r)
            if m is None or order[m.strength] < floor:
                continue
            alerts.append(
                RecallAlert(
                    watch_item_id=item.id,
                    recall_fingerprint=fp,
                    strength=m.strength,
                    matched_on=m.matched_on,
                    statement_ko=_statement(item, r, m),
                    source_label="국가기술표준원 리콜정보",
                    source_url=r.detail_url or "https://www.safetykorea.kr/",
                    announced_on=r.announced_on,
                    reason=r.reason,
                    detected_at=today,
                )
            )
            seen.add(fp)
    return alerts


def _statement(item: WatchItem, r: RecallRecord, m: Match) -> str:
    where = "국내" if r.scope == "domestic" else "해외"
    when = r.announced_on or "일자 미상"
    subject = item.model_name or item.product_name or "등록하신 상품"
    return (
        f"'{subject}' 과(와) {m.strength.label_ko}하는 항목이 "
        f"{where} 리콜 공표({when})에 등록되었습니다. 원문에서 확인해 주세요."
    )
