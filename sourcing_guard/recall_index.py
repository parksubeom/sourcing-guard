"""로컬 리콜 사본 위의 매칭.

왜 로컬인가 (핸드오프 §8):
  투표 기간에 공개 트래픽이 정부 API 를 직접 때리지 않게 한다. 그리고 API 가
  죽어도 리콜 대조는 계속된다.

왜 API 검색보다 정확한가:
  API 의 recallModelName 검색은 서버가 통짜 문자열로 부분 매칭하는 것이라,
  우리가 실데이터로 만든 콤마·슬래시·괄호 분해와 자리표시자 필터가 적용되지
  않았다. 로컬 매칭은 watchlist.match() 를 그대로 쓰므로 그게 전부 살아난다.

여기서 매칭 두뇌가 하나로 합쳐진다:
  이전에는 스캔이 API 검색, 워치리스트 스윕이 로컬 match() 로 서로 다른 방법을
  썼다. 같은 상품이 스캔에선 안 걸리고 스윕에선 걸릴 수 있는 상태였다. 이제
  둘 다 watchlist.match() 하나를 쓴다.

신선도 대가:
  로컬 사본이라 리콜 반영이 최대 하루 늦는다. 오늘 공표된 리콜은 다음 동기화
  전까지 안 잡힌다. 숨기면 안 되는 트레이드오프라 ScanResult.recall_data_as_of
  로 기준일을 함께 내보낸다.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date

from .kats_client import RecallRecord
from .models import MatchStrength, ProductFacts, WatchItem
from .storage import SqliteWatchStore
from .watchlist import Match, match

_log = logging.getLogger(__name__)


def _to_record(payload: str) -> RecallRecord | None:
    try:
        d = json.loads(payload)
    except (ValueError, TypeError):
        return None
    try:
        return RecallRecord(**d)
    except TypeError:
        # 저장 당시와 필드가 달라진 경우. 조용히 버리지 않고 남긴다.
        _log.warning("리콜 레코드 복원 실패 - 스키마가 달라졌을 수 있습니다")
        return None


class RecallIndex:
    """리콜 로컬 사본을 메모리에 올려두고 매칭한다.

    리콜은 하루 한 번 갱신되므로 요청마다 SQLite 를 읽을 이유가 없다.
    동기화가 끝나면 invalidate() 로 다시 읽는다.
    """

    def __init__(self, store: SqliteWatchStore) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._records: list[RecallRecord] | None = None
        self._as_of: str | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._records = None
            self._as_of = None

    def _load(self) -> list[RecallRecord]:
        if self._records is not None:
            return self._records
        with self._lock:
            if self._records is not None:
                return self._records
            records = []
            for payload in self._store.recall_payloads():
                r = _to_record(payload)
                if r is not None:
                    records.append(r)
            self._records = records
            self._as_of = self._store.latest_published_on()
            _log.info("리콜 인덱스 적재: %d건 (기준 %s)", len(records), self._as_of)
            return self._records

    @property
    def as_of(self) -> str | None:
        """가장 최근 공표일 (YYYYMMDD). "리콜 이력 없음" 의 유효기간이다."""
        self._load()
        return self._as_of

    def is_empty(self) -> bool:
        return not self._load()

    def find(
        self,
        facts: ProductFacts,
        *,
        today: date,
        min_strength: MatchStrength = MatchStrength.WEAK,
    ) -> list[tuple[RecallRecord, Match]]:
        """상품 사실과 일치하는 리콜을 강한 순으로 돌려준다.

        스윕과 같은 match() 를 쓴다. 매칭 규칙이 두 벌로 갈라지지 않게 하려고
        ProductFacts 를 임시 WatchItem 으로 감싼다 — 저장하지 않는다.
        """
        records = self._load()
        if not records:
            return []

        probe = WatchItem.from_facts(
            id="__scan__", owner_id="__scan__", facts=facts, on=today
        )
        if not probe.is_matchable():
            return []

        order = {MatchStrength.WEAK: 0, MatchStrength.STRONG: 1, MatchStrength.EXACT: 2}
        floor = order[min_strength]

        hits: list[tuple[RecallRecord, Match]] = []
        for r in records:
            m = match(probe, r)
            if m is not None and order[m.strength] >= floor:
                hits.append((r, m))

        hits.sort(key=lambda pair: (-order[pair[1].strength], pair[0].uid or ""))
        return hits
