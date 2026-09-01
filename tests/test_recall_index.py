"""로컬 리콜 사본 위의 매칭.

여기서 매칭 두뇌가 하나로 합쳐진다. 이전에는 스캔이 API 검색, 워치리스트 스윕이
로컬 watchlist.match() 로 서로 다른 방법을 썼다 — 같은 상품이 스캔에선 안 걸리고
스윕에선 걸릴 수 있는 상태였다.
"""

import json
from dataclasses import asdict
from datetime import date

import pytest

from sourcing_guard.kats_client import RecallRecord
from sourcing_guard.models import (
    ItemCategory,
    MatchStrength,
    ProductFacts,
    WatchItem,
)
from sourcing_guard.recall_index import RecallIndex
from sourcing_guard.storage import SqliteWatchStore
from sourcing_guard.watchlist import match

TODAY = date(2026, 9, 1)


def rec(uid, *, model="BLK-100", cert="CB061R2170-3018", product="완구",
        maker="안심완구", on="20260723", scope="domestic"):
    return RecallRecord(
        product_name=product,
        model_name=model,
        maker=maker,
        reason="프탈레이트계 가소제 기준치 초과",
        announced_on=on,
        detail_url=None,
        scope=scope,
        models=[model],
        cert_numbers=[cert] if cert else [],
        uid=uid,
    )


@pytest.fixture
def index(tmp_path):
    store = SqliteWatchStore(tmp_path / "t.db")

    def load(*records):
        rows = [
            {"uid": r.uid, "published_on": r.announced_on,
             "payload": json.dumps(asdict(r), ensure_ascii=False)}
            for r in records
        ]
        by_scope: dict[str, list] = {}
        for r, row in zip(records, rows):
            by_scope.setdefault(r.scope, []).append(row)
        for scope, scope_rows in by_scope.items():
            store.upsert_recalls(scope_rows, scope=scope, fetched_at="2026-09-01T00:00:00+00:00")
        idx = RecallIndex(store)
        idx.invalidate()
        return idx

    return load


# ---------------------------------------------------------------------------
# 매칭 통합 — 스캔과 스윕이 같은 규칙을 써야 한다
# ---------------------------------------------------------------------------


def test_scan_and_sweep_agree_on_the_same_product(index):
    """같은 상품이 스캔에선 안 걸리고 스윕에선 걸리는 일이 없어야 한다."""
    r = rec("1")
    idx = index(r)

    facts = ProductFacts(
        product_name="유아용 블록", model_name="BLK-100",
        kc_numbers=["CB061R2170-3018"], category=ItemCategory.CHILDREN_TOY,
    )

    scan_hits = idx.find(facts, today=TODAY)
    sweep_match = match(
        WatchItem.from_facts(id="w", owner_id="o", facts=facts, on=TODAY), r
    )

    assert len(scan_hits) == 1
    assert sweep_match is not None
    # 강도까지 같아야 한다. 다르면 화면에 붙는 문구가 갈린다.
    assert scan_hits[0][1].strength is sweep_match.strength


def test_cert_number_match_survives_a_different_model_name(index):
    """모델명 표기가 흔들려도 인증번호가 같으면 잡아야 한다.

    API 의 recallModelName 검색으로는 못 잡던 경로다.
    """
    idx = index(rec("1", model="전혀 다른 이름"))
    facts = ProductFacts(
        product_name="유아용 블록", model_name="BLK-100",
        kc_numbers=["CB061R2170-3018"], category=ItemCategory.CHILDREN_TOY,
    )
    hits = idx.find(facts, today=TODAY)

    assert len(hits) == 1
    assert hits[0][1].strength is MatchStrength.EXACT


def test_placeholder_cert_numbers_do_not_match(index):
    """'공급자적합성' 같은 자리표시자를 인증번호로 취급하면 서로 다른 상품이 엮인다."""
    idx = index(rec("1", model="다른모델", cert="공급자적합성", maker="다른회사",
                    product="다른제품"))
    facts = ProductFacts(
        product_name="유아용 블록", model_name="BLK-100",
        kc_numbers=["공급자적합성"], category=ItemCategory.CHILDREN_TOY,
    )
    assert idx.find(facts, today=TODAY) == []


def test_hits_are_sorted_strongest_first(index):
    idx = index(
        rec("weak", model="완전히다름", cert=None, maker="안심완구", product="완구"),
        rec("exact", model="BLK-100", cert="CB061R2170-3018"),
    )
    facts = ProductFacts(
        product_name="완구", model_name="BLK-100",
        kc_numbers=["CB061R2170-3018"], maker="안심완구",
        category=ItemCategory.CHILDREN_TOY,
    )
    hits = idx.find(facts, today=TODAY)

    assert hits, "일치가 하나도 없으면 정렬을 검증할 수 없습니다"
    assert hits[0][1].strength is MatchStrength.EXACT


def test_unmatchable_facts_yield_nothing(index):
    """모델명도 인증번호도 없으면 매칭 근거가 없다."""
    idx = index(rec("1"))
    facts = ProductFacts(category=ItemCategory.CHILDREN_TOY)
    assert idx.find(facts, today=TODAY) == []


# ---------------------------------------------------------------------------
# 캐시 기준일 — "리콜 이력 없음" 이라는 문장의 유효기간
# ---------------------------------------------------------------------------


def test_as_of_is_the_latest_published_date(index):
    idx = index(rec("1", on="20260723"), rec("2", on="20260828", scope="overseas"))
    assert idx.as_of == "20260828"


def test_empty_index_is_reported_as_empty(tmp_path):
    idx = RecallIndex(SqliteWatchStore(tmp_path / "t.db"))
    assert idx.is_empty() is True
    assert idx.as_of is None


def test_invalidate_picks_up_newly_synced_records(index, tmp_path):
    """동기화 후 invalidate 를 안 부르면 재시작 전까지 옛 사본으로 대조한다."""
    store = SqliteWatchStore(tmp_path / "t2.db")
    idx = RecallIndex(store)
    assert idx.is_empty()

    r = rec("1")
    store.upsert_recalls(
        [{"uid": r.uid, "published_on": r.announced_on,
          "payload": json.dumps(asdict(r), ensure_ascii=False)}],
        scope="domestic", fetched_at="2026-09-01T00:00:00+00:00",
    )
    assert idx.is_empty(), "무효화 전에는 옛 사본을 봐야 합니다"

    idx.invalidate()
    assert idx.is_empty() is False
    assert idx.as_of == "20260723"


def test_corrupt_payload_is_skipped_not_fatal(tmp_path):
    """저장 스키마가 달라져도 스캔 전체가 죽으면 안 된다."""
    store = SqliteWatchStore(tmp_path / "t.db")
    store.upsert_recalls(
        [{"uid": "bad", "published_on": "20260723", "payload": "{이건 JSON 이 아니다"}],
        scope="domestic", fetched_at="2026-09-01T00:00:00+00:00",
    )
    idx = RecallIndex(store)
    assert idx.is_empty() is True


# ---------------------------------------------------------------------------
# 신선도 표기 — 로컬 사본의 대가를 숨기지 않는다
# ---------------------------------------------------------------------------


def test_recall_clear_states_the_cutoff_date(index):
    """'리콜 이력 없음' 에는 유효기간이 있다.

    로컬 사본이라 오늘 공표된 리콜은 다음 동기화 전까지 안 잡힌다. 기준일을
    안 적으면 셀러가 그 문장을 '지금 이 순간' 으로 읽는다.
    """
    from sourcing_guard.kats_client import CertLookup
    from sourcing_guard.models import FindingKind
    from sourcing_guard.verifier import RuleBook, verify

    class NoCertClient:
        def lookup_certification_cached(self, kc_number):
            return CertLookup(record=None, fetched_at="2026-09-01T00:00:00+00:00")

    idx = index(rec("1", model="전혀다른모델", cert=None, maker="다른회사",
                    product="다른제품", on="20260828"))
    facts = ProductFacts(
        product_name="유아용 블록", model_name="BLK-100",
        category=ItemCategory.CHILDREN_TOY,
    )
    findings = verify(facts, NoCertClient(), RuleBook(), idx)
    clear = next(f for f in findings if f.kind is FindingKind.RECALL_CLEAR)

    assert "2026-08-28 공표분까지" in clear.statement_ko
    assert clear.detail["recall_data_as_of"] == "20260828"


def test_scan_result_carries_the_cutoff_date(index):
    """프론트가 그리기만 하면 되도록 API 응답에 실어 보낸다."""
    from sourcing_guard.scorer import score

    idx = index(rec("1", on="20260828"))
    facts = ProductFacts(model_name="BLK-100", category=ItemCategory.CHILDREN_TOY)
    result = score(facts, [], recall_data_as_of=idx.as_of)

    assert result.recall_data_as_of == "20260828"


# ---------------------------------------------------------------------------
# 스윕도 같은 로컬 사본을 쓴다
# ---------------------------------------------------------------------------


def test_sweep_uses_the_same_records_as_scan(index):
    """스캔과 스윕이 같은 사본·같은 match() 를 써야 결과가 갈리지 않는다.

    이전에는 스윕이 워치 항목마다 search_recalls() 를 불렀고, 모델명으로 검색한
    결과에만 매칭해서 인증번호로만 일치하는 리콜을 구조적으로 놓쳤다.
    """
    from sourcing_guard.watchlist import sweep

    # 모델명은 전혀 다르고 인증번호만 같은 리콜. API 모델명 검색으로는 안 잡힌다.
    idx = index(rec("1", model="전혀 다른 이름", cert="CB061R2170-3018"))

    facts = ProductFacts(
        product_name="유아용 블록", model_name="BLK-100",
        kc_numbers=["CB061R2170-3018"], category=ItemCategory.CHILDREN_TOY,
    )
    item = WatchItem.from_facts(id="w1", owner_id="o", facts=facts, on=TODAY)

    scan_hits = idx.find(facts, today=TODAY)
    alerts = sweep([item], idx.all_records(), today=TODAY)

    assert len(scan_hits) == 1
    assert len(alerts) == 1
    assert alerts[0].strength is scan_hits[0][1].strength


def test_sweep_makes_no_api_calls(index):
    """워치 항목 N개면 정부 API 호출이 N회였다. 로컬 사본으로 0회가 된다."""
    import inspect

    from sourcing_guard import main

    # docstring 과 주석을 걷어내고 코드만 본다. 이 함수의 docstring 이 왜
    # search_recalls 를 걷어냈는지 설명하느라 그 이름을 담고 있어서, 문자열만
    # 찾으면 스스로에게 걸린다.
    src = inspect.getsource(main.run_sweep)
    body = src.split('"""')[-1]
    code = "\n".join(
        ln for ln in body.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "search_recalls" not in code, "스윕이 다시 정부 API 를 부르고 있습니다"
    assert "_recalls.all_records()" in code
