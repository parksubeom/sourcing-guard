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


def test_is_empty_and_size_are_the_same_question(index):
    """⚠⚠ **`is_empty()` ⟺ `size == 0`. 이 동치가 rf 게이트를 닫고 있다.**

    `scorer._verified_counts` 는 RF finding 이 있으면 부적합 건수를 싣는다.
    그런데 `verifier.py:617` 은 인덱스가 비면 부적합 **대조를 건너뛰고도**
    뒤에서 `RF_WIRELESS_UNVERIFIED` 를 붙일 수 있다 - 그때 건수가 실리면
    "대조하지 않은 것을 대조했다" 가 된다 (4-r 과 같은 종류).

    지금은 안 실린다. 인덱스가 비면 `size` 가 0 이고 `(0 or None)` 이 None
    이기 때문이다. **두 함수가 서로를 모르는 채 우연히 맞물려 있다.**

    ⚠ verifier 에 "부적합을 실제로 대조했다" 는 finding 을 새로 넣어 닫는 길도
      있지만 **그러지 않는다** (2026-09-21 총괄). 범위가 넓어진다.
      **이 검사가 그 자리를 대신 지킨다** - 누가 `size` 를 "원본 행 수" 로
      바꾸거나 `is_empty` 를 다르게 정의하면 여기서 깨진다.

    ⚠ 이 동치를 **진짜 객체**로 재는 것은 여기뿐이다. tests/ 안의 다른
      `is_empty` 는 전부 가짜 객체다.
    """
    db = pathlib.Path(tempfile.mkdtemp()) / "eq.db"
    empty = NoncompliantIndex(SqliteWatchStore(db))
    assert empty.is_empty() and empty.size == 0

    assert not index.is_empty() and index.size > 0

    # ⚠⚠ **행이 있는데 닿을 수 없는 경우**를 반드시 같이 잰다.
    #   2026-09-21 에 위 두 줄만 두고 반대 방향을 재 보니 **셋 중 둘이 안 물었다** -
    #   `size = len(rows)` 로 바꿔도, `is_empty` 를 번호만 보게 바꿔도 통과했다.
    #   표본의 모든 행이 번호로 닿아서 세 정의가 우연히 같은 수를 냈기 때문이다.
    #   번호도 없고 변별력 있는 모델명도 없는 행을 넣어야 정의가 갈린다.
    class _Unreachable:
        def rf_noncompliant_rows(self):
            return [{"cert_number": "", "model": "Q1"}]   # 둘 다 못 쓴다

    ghost = NoncompliantIndex(_Unreachable())
    assert ghost.size == 0, "닿을 수 없는 행을 셌습니다 - 원본 행 수를 쓴 것입니다"
    assert ghost.is_empty(), "닿을 수 없는데 비지 않았다고 합니다"

    # 번호는 없고 모델명으로만 닿는 행. `is_empty` 가 번호만 보면 여기서 깨진다.
    class _ModelOnly:
        def rf_noncompliant_rows(self):
            return [{"cert_number": "", "model": "DECKTS183"}]

    model_only = NoncompliantIndex(_ModelOnly())
    assert model_only.size == 1
    assert not model_only.is_empty(), (
        "모델명으로 닿는 행이 있는데 비었다고 합니다 - is_empty 가 번호만 봅니다")


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


# ---------------------------------------------------------------------------
# 동기화 배선 — 안 부르면 RED 소스가 영구히 빈다
#
# sync_noncompliant 가 정의만 되고 호출되는 곳이 없었다. 그러면 rf_noncompliant
# 테이블이 계속 0건이고, NoncompliantIndex.is_empty() 가 참이라 verifier 가
# 부적합 블록을 통째로 건너뛴다 - RF_NONCOMPLIANT 이 한 번도 안 뜬다.
# 테스트는 인덱스를 직접 채워서 통과하니 이 구멍을 못 잡았다.
# ---------------------------------------------------------------------------


def test_sync_loop_syncs_noncompliant_when_rra_is_given():
    import asyncio

    from sourcing_guard import sync as sync_mod

    called = {"recalls": 0, "noncompliant": 0}

    def fake_run_sync(*a, **kw):
        called["recalls"] += 1

    def fake_sync_noncompliant(rra, store, *, on_updated=None, **kw):
        called["noncompliant"] += 1
        if on_updated:
            on_updated()
        return {"ok": True, "count": 2748}

    async def drive(monkey):
        task = asyncio.create_task(
            sync_mod.sync_loop(object(), object(), interval=3600,
                               rra=object(), on_noncompliant_updated=lambda: None)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setattr(sync_mod, "run_sync", fake_run_sync)
    mp.setattr(sync_mod, "sync_noncompliant", fake_sync_noncompliant)
    try:
        asyncio.run(drive(mp))
    finally:
        mp.undo()

    assert called["recalls"] == 1
    assert called["noncompliant"] == 1, "부적합 현황이 동기화되지 않으면 RED 소스가 빈다"


def test_sync_loop_skips_noncompliant_without_rra():
    """rra 를 안 주면 건너뛴다 - 리콜만 돌리는 기존 호출부가 깨지면 안 된다."""
    import asyncio

    from sourcing_guard import sync as sync_mod

    called = {"noncompliant": 0}

    async def drive():
        task = asyncio.create_task(sync_mod.sync_loop(object(), object(), interval=3600))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setattr(sync_mod, "run_sync", lambda *a, **kw: None)
    mp.setattr(sync_mod, "sync_noncompliant",
               lambda *a, **kw: called.__setitem__("noncompliant", called["noncompliant"] + 1))
    try:
        asyncio.run(drive())
    finally:
        mp.undo()

    assert called["noncompliant"] == 0


def test_healthz_exposes_the_noncompliant_count():
    """0 이면 RED 가 한 번도 안 뜬다. 조용히 비어 있는 걸 healthz 가 말해야 한다."""
    from fastapi.testclient import TestClient

    from sourcing_guard import main as main_mod

    body = TestClient(main_mod.app).get("/healthz").json()
    rf = body["sync"]["rf_noncompliant"]
    assert "count" in rf and "synced_at" in rf
