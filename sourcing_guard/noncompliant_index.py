"""부적합 방송통신기자재 현황 인덱스.

전파인증 축에서 **RED 자격이 있는 유일한 소스**다. 부적합사유·행정처분이
명시되어 "정부 DB 가 적극적으로 문제를 적어둔" 조건을 만족한다 (CLAUDE.md R3-b).
적합성평가 DB 미조회는 자기적합확인 여지가 있어 AMBER 지만, 여기 걸린 것은
정부가 문제를 확인한 것이다.

리콜 인덱스와 같은 구조를 쓴다. 다만 규모가 작아(2,748건) 메모리에 통째로 둔다.

⚠ 인증번호 칸에 두 제도가 섞여 있다 - R-R-msg-DECKTS183(적합성평가)과
   PLCL-YK-006·CCMS-Q1(자기적합확인 관리번호). 목록 하나로 둘 다 대조된다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .storage import SqliteWatchStore
from .watchlist import normalize_model

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NoncompliantHit:
    company: str | None
    cert_number: str | None
    model: str | None
    acted_on: str | None
    matched_on: str  # "cert_number" | "model"


# RED 를 내는 축이라 리콜보다 엄격하게 잡는다.
#
# watchlist 의 _exact_is_distinctive 는 "글자가 하나라도 있으면 통과" 인데,
# 부적합 목록에는 'Q1' 'K3' 'M-3' 같은 2~3자 모델명이 표본의 6.7% 있다. 그
# 기준을 그대로 쓰면 셀러의 'Q1' 이 무관한 부적합 건을 RED 로 문다. 리콜에서는
# 같은 상황을 weak 로 강등했지만, 여기는 강등할 등급이 없어 아예 제외한다.
_MIN_MODEL_LEN_FOR_RED = 4


def _model_is_distinctive(model: str) -> bool:
    return len(model) >= _MIN_MODEL_LEN_FOR_RED and any(c.isalpha() for c in model)


def _normalize_number(raw: str | None) -> str:
    """인증번호 비교용 정규화. 하이픈·공백·대소문자를 무시한다.

    명세도 "'-' 유무와 상관없이 조회 가능" 이라고 적고 있어, 우리 비교도 같은
    기준을 쓴다.
    """
    return "".join(ch for ch in (raw or "") if ch.isalnum()).upper()


class NoncompliantIndex:
    """부적합 현황 로컬 사본 위의 매칭.

    비어 있으면 `is_empty()` 가 참이고, 호출측은 조회하지 않은 것으로 다뤄야
    한다. 대조하지 않은 것을 대조했다고 말할 수 없다 (R3).
    """

    def __init__(self, store: SqliteWatchStore) -> None:
        self._store = store
        self._by_number: dict[str, dict] = {}
        self._by_model: dict[str, list[dict]] = {}
        self._loaded = False

    def load(self) -> int:
        rows = self._store.rf_noncompliant_rows()
        by_number: dict[str, dict] = {}
        by_model: dict[str, list[dict]] = {}
        for row in rows:
            key = _normalize_number(row.get("cert_number"))
            if key:
                by_number[key] = row
            model = normalize_model(row.get("model"))
            if model and _model_is_distinctive(model):
                by_model.setdefault(model, []).append(row)
        self._by_number, self._by_model = by_number, by_model
        self._loaded = True
        _log.info("부적합 현황 인덱스 적재: %d건", len(rows))
        return len(rows)

    def invalidate(self) -> None:
        self._loaded = False

    def is_empty(self) -> bool:
        if not self._loaded:
            self.load()
        return not self._by_number and not self._by_model

    def find(self, *, rf_numbers: list[str], models: list[str]) -> list[NoncompliantHit]:
        """인증번호 또는 모델명 정확 일치만 본다.

        포함 매칭을 쓰지 않는 이유: RED 를 내는 축이라 오탐 비용이 가장 크다.
        리콜 쪽에서 포함 매칭이 137건 오탐을 냈던 것과 같은 이유다.
        """
        if not self._loaded:
            self.load()

        hits: list[NoncompliantHit] = []
        seen: set[str] = set()

        for number in rf_numbers:
            row = self._by_number.get(_normalize_number(number))
            if row and row["seq"] not in seen:
                seen.add(row["seq"])
                hits.append(_to_hit(row, "cert_number"))

        for model in models:
            key = normalize_model(model)
            if not key or not _model_is_distinctive(key):
                continue
            for row in self._by_model.get(key, []):
                if row["seq"] not in seen:
                    seen.add(row["seq"])
                    hits.append(_to_hit(row, "model"))
        return hits


def _to_hit(row: dict, matched_on: str) -> NoncompliantHit:
    return NoncompliantHit(
        company=row.get("company"),
        cert_number=row.get("cert_number"),
        model=row.get("model"),
        acted_on=row.get("acted_on"),
        matched_on=matched_on,
    )
