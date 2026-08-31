"""워치리스트 영속화 계약 테스트.

핵심은 마지막의 재시작 테스트다. 나머지가 다 통과해도 그것이 깨지면
"리콜 공표되면 가장 먼저 알린다"는 약속이 조용히 깨진다 (기획서 §6.1).
"""

from datetime import date

import pytest

from sourcing_guard.models import ItemCategory, ProductFacts, WatchItem, WatchStatus
from sourcing_guard.storage import SqliteWatchStore

TODAY = date(2026, 9, 20)


@pytest.fixture()
def store(tmp_path):
    s = SqliteWatchStore(tmp_path / "w.db")
    yield s
    s.close()


def item(**kw) -> WatchItem:
    base = dict(id="w1", owner_id="u1", model_name="BLK-100", registered_at=TODAY)
    return WatchItem(**{**base, **kw})


def test_add_and_get_roundtrip(store):
    store.add(item(product_name="유아용 블록", kc_numbers=["XU07012345"]))
    got = store.get("w1")
    assert got is not None
    assert got.model_name == "BLK-100"
    assert got.kc_numbers == ["XU07012345"]
    assert got.registered_at == TODAY


def test_get_missing_returns_none(store):
    assert store.get("nope") is None


def test_for_owner_isolates_owners(store):
    store.add(item(id="w1", owner_id="u1"))
    store.add(item(id="w2", owner_id="u2"))
    assert [i.id for i in store.for_owner("u1")] == ["w1"]
    assert [i.id for i in store.for_owner("u2")] == ["w2"]


def test_for_owner_excludes_archived_by_default(store):
    store.add(item(id="w1", owner_id="u1"))
    store.add(item(id="w2", owner_id="u1", status=WatchStatus.ARCHIVED))
    assert [i.id for i in store.for_owner("u1")] == ["w1"]
    assert len(store.for_owner("u1", active_only=False)) == 2


def test_active_items_spans_owners(store):
    store.add(item(id="w1", owner_id="u1"))
    store.add(item(id="w2", owner_id="u2"))
    store.add(item(id="w3", owner_id="u3", status=WatchStatus.ARCHIVED))
    assert {i.id for i in store.active_items()} == {"w1", "w2"}


def test_add_is_idempotent_on_same_id(store):
    store.add(item(product_name="처음"))
    store.add(item(product_name="나중"))
    assert store.count() == 1
    assert store.get("w1").product_name == "나중"


# --- mark_swept ----------------------------------------------------------
def test_mark_swept_records_date_and_fingerprints(store):
    store.add(item())
    store.mark_swept("w1", TODAY, ["fp1", "fp2"])
    got = store.get("w1")
    assert got.last_swept_at == TODAY
    assert got.seen_recall_fingerprints == ["fp1", "fp2"]


def test_mark_swept_accumulates_without_duplicates(store):
    store.add(item())
    store.mark_swept("w1", TODAY, ["fp1"])
    store.mark_swept("w1", date(2026, 9, 21), ["fp1", "fp2"])
    got = store.get("w1")
    assert got.seen_recall_fingerprints == ["fp1", "fp2"]
    assert got.last_swept_at == date(2026, 9, 21)


def test_mark_swept_with_no_alerts_still_records_date(store):
    """알림이 없어도 '언제까지 확인했다'는 남아야 한다."""
    store.add(item())
    store.mark_swept("w1", TODAY, [])
    assert store.get("w1").last_swept_at == TODAY


def test_mark_swept_on_missing_item_is_noop(store):
    store.mark_swept("ghost", TODAY, ["fp1"])
    assert store.count() == 0


# --- 재시작 생존: 이 파일에서 가장 중요한 테스트 --------------------------
def test_items_survive_restart(tmp_path):
    path = tmp_path / "w.db"

    first = SqliteWatchStore(path)
    first.add(item(product_name="유아용 블록", kc_numbers=["XU07012345"]))
    first.mark_swept("w1", TODAY, ["fp1"])
    first.close()

    second = SqliteWatchStore(path)          # 프로세스 재시작 시뮬레이션
    got = second.get("w1")
    assert got is not None, "재시작으로 워치리스트를 잃으면 알림 약속이 깨진다"
    assert got.product_name == "유아용 블록"
    assert got.seen_recall_fingerprints == ["fp1"]
    assert got.last_swept_at == TODAY
    second.close()


def test_ordering_is_stable(store):
    """sweep 의 결정성 계약을 저장 계층에서도 깨지 않는다."""
    for i in ("w3", "w1", "w2"):
        store.add(item(id=i))
    assert [i.id for i in store.for_owner("u1")] == ["w1", "w2", "w3"]
