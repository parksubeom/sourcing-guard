"""부적합 방송통신기자재 현황 - 전파인증 축의 RED 소스.

RED 를 내는 축이라 오탐 비용이 가장 크다. 리콜에서 포함 매칭이 137건 오탐을
냈던 것과 같은 이유로, 여기서는 정확 일치만 쓰고 짧은 모델명을 아예 제외한다.
"""

import pathlib
import tempfile

import pytest

from sourcing_guard.noncompliant_index import NoncompliantIndex, _model_is_distinctive
from sourcing_guard.storage import SqliteWatchStore

_ROWS = [
    {"seq": "1", "company": "퓨어엘코스", "cert_number": "PLCL-YK-006",
     "model": "YK-006", "acted_on": "2026-08-31"},
    {"seq": "2", "company": "코어커머스", "cert_number": "CCMS-Q1",
     "model": "Q1", "acted_on": "2026-08-31"},
    {"seq": "3", "company": "모모", "cert_number": "R-R-msg-DECKTS183",
     "model": "DECKTS183", "acted_on": "2026-01-01"},
]


@pytest.fixture
def index():
    db = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    store = SqliteWatchStore(db)
    store.replace_rf_noncompliant(_ROWS, fetched_at="2026-09-02")
    idx = NoncompliantIndex(store)
    idx.load()
    return idx


def test_cert_number_match(index):
    hits = index.find(rf_numbers=["R-R-msg-DECKTS183"], models=[])
    assert len(hits) == 1
    assert hits[0].matched_on == "cert_number"


def test_hyphens_are_ignored(index):
    """명세도 "'-' 유무와 상관없이 조회 가능" 이라 비교도 같은 기준을 쓴다."""
    assert len(index.find(rf_numbers=["RRmsgDECKTS183"], models=[])) == 1


def test_model_match(index):
    hits = index.find(rf_numbers=[], models=["YK-006"])
    assert len(hits) == 1
    assert hits[0].matched_on == "model"


def test_short_model_is_excluded_from_red():
    """'Q1'·'K3' 같은 2~3자 모델명이 표본의 6.7% 다.

    watchlist 의 식별력 규칙("글자가 하나라도 있으면 통과")을 그대로 쓰면
    셀러의 'Q1' 이 무관한 부적합 건을 RED 로 문다. 리콜에서는 같은 상황을 weak
    로 강등했지만, RED 축에는 강등할 등급이 없어 아예 제외한다.
    """
    assert not _model_is_distinctive("Q1")
    assert not _model_is_distinctive("K3")
    assert not _model_is_distinctive("1234")   # 글자가 없다
    assert _model_is_distinctive("YK-006")
    assert _model_is_distinctive("DECKTS183")


def test_short_model_does_not_match(index):
    assert index.find(rf_numbers=[], models=["Q1"]) == []


def test_unrelated_model_does_not_match(index):
    assert index.find(rf_numbers=[], models=["ZZZ9999"]) == []


def test_empty_index_is_reported_as_empty():
    """비어 있으면 조회하지 않은 것으로 다뤄야 한다 (R3)."""
    db = pathlib.Path(tempfile.mkdtemp()) / "e.db"
    idx = NoncompliantIndex(SqliteWatchStore(db))
    assert idx.is_empty()


def test_store_refuses_to_overwrite_with_empty_list():
    """수집이 실패했는데 테이블을 비우면 RED 소스가 조용히 사라진다."""
    db = pathlib.Path(tempfile.mkdtemp()) / "r.db"
    store = SqliteWatchStore(db)
    store.replace_rf_noncompliant(_ROWS, fetched_at="2026-09-02")
    with pytest.raises(ValueError):
        store.replace_rf_noncompliant([], fetched_at="2026-09-02")
    assert store.rf_noncompliant_count() == 3


# --- verifier 배선 ---------------------------------------------------------
def test_noncompliant_match_is_red(index):
    from sourcing_guard.extractor import extract
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.models import FindingKind, Signal
    from sourcing_guard.rra_client import RraClient
    from sourcing_guard.scorer import score
    from sourcing_guard.verifier import RuleBook, verify

    facts = extract("무선 블루투스 스피커\n모델명: YK-006\n제조사: 퓨어엘코스")
    findings = verify(facts, KatsClient(None, None, mock=True), RuleBook(), None,
                      RraClient(mock=True), index)
    result = score(facts, findings)

    assert result.signal is Signal.RED
    hit = next(f for f in findings if f.kind is FindingKind.RF_NONCOMPLIANT)
    assert "퓨어엘코스" in hit.statement_ko
    assert "rra.go.kr" in hit.source_url


def test_unrelated_wireless_product_is_not_red(index):
    from sourcing_guard.extractor import extract
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.models import Signal
    from sourcing_guard.rra_client import RraClient
    from sourcing_guard.scorer import score
    from sourcing_guard.verifier import RuleBook, verify

    facts = extract("블루투스 이어폰\n모델명: ZZZ9999")
    result = score(
        facts,
        verify(facts, KatsClient(None, None, mock=True), RuleBook(), None,
               RraClient(mock=True), index),
    )
    assert result.signal is not Signal.RED
