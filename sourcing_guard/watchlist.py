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

from .kats_client import RecallRecord, is_cert_number, normalize_kc
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
        [
            r.scope,
            r.uid or "",          # 서버가 주는 안정적인 id. 있으면 이게 가장 정확하다
            r.model_name or "",
            r.product_name or "",
            r.maker or "",
            r.announced_on or "",
        ]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Match:
    strength: MatchStrength
    matched_on: str


def _recall_models(r: RecallRecord) -> list[str]:
    """리콜 레코드가 담고 있는 모델명들을 정규화해서 돌려준다.

    recallModelName 은 콤마로 묶인 목록이다 (설계서 p.11). 통짜 문자열로 비교하면
    'A,B,C' 리콜에서 B 를 감시 중인 셀러가 알림을 받지 못한다. 놓친 알림은 이
    서비스가 하는 유일한 약속을 깨뜨린다 (CLAUDE.md R6).
    """
    raw = r.models or ([r.model_name] if r.model_name else [])
    return [m for m in (normalize_model(x) for x in raw) if m]


def match(item: WatchItem, r: RecallRecord) -> Match | None:
    """Return the strongest match tier, or None.

    Tiers are ordered and mutually exclusive; the first hit wins.
    """
    wm = normalize_model(item.model_name)
    recall_models = _recall_models(r)

    if wm and len(wm) >= _MIN_EXACT_LEN and wm in recall_models:
        return Match(MatchStrength.EXACT, "model_name")

    # 리콜 레코드에 인증번호가 따로 실려 온다 (certNum, 콤마 목록). 모델명 표기가
    # 흔들려도 인증번호가 같으면 확실하다.
    watched_kc = {n for n in (normalize_kc(k) for k in item.kc_numbers) if n}
    if watched_kc:
        # "공급자적합성" 같은 자리표시자는 인증번호가 아니다. 걸러내지 않으면
        # 같은 자리표시자를 가진 서로 다른 상품이 전부 일치로 잡힌다.
        recall_kc = {
            n
            for n in (normalize_kc(c) for c in r.cert_numbers if is_cert_number(c))
            if n
        }
        if watched_kc & recall_kc:
            return Match(MatchStrength.EXACT, "kc_number")
        # 예전 공표는 인증번호를 모델명 칸에 적어 둔 경우가 있다.
        for n in watched_kc:
            if len(n) >= _MIN_EXACT_LEN and any(n in rm for rm in recall_models):
                return Match(MatchStrength.EXACT, "kc_number")

    if wm:
        for rm in recall_models:
            if len(wm) >= _MIN_CONTAIN_LEN or len(rm) >= _MIN_CONTAIN_LEN:
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


def _fmt_date(yyyymmdd: str | None) -> str | None:
    """YYYYMMDD -> '2026-07-23'. 원본 그대로 화면에 내보내면 읽히지 않는다."""
    if not yyyymmdd or len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return None
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _statement(item: WatchItem, r: RecallRecord, m: Match) -> str:
    where = "국내" if r.scope == "domestic" else "해외"
    when = _fmt_date(r.announced_on) or "공표일 미상"
    subject = item.model_name or item.product_name or "등록하신 상품"
    return (
        f"'{subject}' 과(와) {m.strength.label_ko}하는 항목이 "
        f"{where} 리콜 공표({when})에 등록되었습니다. 원문에서 확인해 주세요."
    )
