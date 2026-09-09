"""[C-백] 감시 자동화 — 사람이 버튼을 눌러야 도는 것은 보증이 아니다.

기획서 §6.1 이 유일하게 보증한다고 적은 것은 "나중에 리콜 공표되면 가장 먼저
알린다" 다. 전에는 셀러가 `/watch` 화면에서 버튼을 눌러야만 스윕이 돌았고,
**화면을 안 열어 본 셀러는 리콜이 공표돼도 몰랐다.**

이제 리콜 동기화가 새 레코드를 쓰면 전체 스윕이 돌고 알림이 디스크에 남는다.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from sourcing_guard.kats_client import RecallRecord
from sourcing_guard.models import ProductFacts, WatchItem
from sourcing_guard.storage import SqliteWatchStore


def _recall(**kw) -> RecallRecord:
    base = dict(
        product_name="완구", model_name="ZZ-TEST-9999", maker="테스트상사",
        reason="납 기준 초과", announced_on="20260909",
        detail_url="https://www.safetykorea.kr/recall/1", scope="domestic",
        uid="u-test-1",
    )
    base.update(kw)
    return RecallRecord(**base)


def _item(store: SqliteWatchStore, **kw) -> WatchItem:
    facts = ProductFacts(
        product_name=kw.get("product_name", "테스트 블록"),
        model_name=kw.get("model_name", "ZZ-TEST-9999"),
        maker=kw.get("maker", "테스트상사"),
    )
    return store.add(WatchItem.from_facts(
        id=kw.get("id", "w-test-1"), owner_id=kw.get("owner_id", "owner-1"),
        facts=facts, on=date(2026, 9, 9),
    ))


@pytest.fixture
def app_with_tmp_store(tmp_path, monkeypatch):
    """실제 로컬 DB 를 건드리지 않는다. 리콜 색인도 가짜다."""
    from unittest.mock import MagicMock

    import sourcing_guard.main as m

    store = SqliteWatchStore(tmp_path / "t.db")
    recalls = MagicMock()
    recalls.all_records.return_value = []
    recalls.as_of = "20260909"
    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)

    monkeypatch.setattr(m, "_store", store)
    monkeypatch.setattr(m, "_recalls", recalls)
    monkeypatch.setattr(m, "_kats", kats)
    monkeypatch.setattr(m, "_rra", None)
    return m, store, recalls, kats


# ── 자동 스윕 ────────────────────────────────────────────────────────
def test_a_new_recall_reaches_a_watcher_without_anyone_pressing_a_button(
    app_with_tmp_store,
):
    m, store, recalls, _kats = app_with_tmp_store
    _item(store)
    recalls.all_records.return_value = [_recall()]

    got = m._full_sweep(on=date(2026, 9, 9))

    assert got == {"items": 1, "new_alerts": 1}
    assert store.alert_count() == 1
    saved = store.alerts_for_owner("owner-1")
    assert saved and saved[0].watch_item_id == "w-test-1"


def test_the_index_is_invalidated_before_the_sweep_not_after(app_with_tmp_store):
    """⚠ 순서를 바꾸면 **방금 들어온 레코드를 못 보고 지나간다.**

    조용히 놓치는 알림이고, 그게 이 서비스가 가장 하지 말아야 할 실패다 (R6).
    """
    m, store, recalls, _kats = app_with_tmp_store
    _item(store)

    order: list[str] = []
    recalls.invalidate.side_effect = lambda: order.append("invalidate")

    def _records():
        order.append("all_records")
        return [_recall()]

    recalls.all_records.side_effect = _records
    m._on_recalls_updated()

    assert order[:2] == ["invalidate", "all_records"], order
    assert store.alert_count() == 1


def test_the_same_recall_is_not_counted_twice(app_with_tmp_store):
    """"새 알림 N" 은 **저장된 수**여야 한다. sweep() 이 낸 수가 아니다."""
    m, store, recalls, _kats = app_with_tmp_store
    _item(store)
    recalls.all_records.return_value = [_recall()]

    first = m._full_sweep(on=date(2026, 9, 9))
    second = m._full_sweep(on=date(2026, 9, 10))

    assert first["new_alerts"] == 1
    assert second["new_alerts"] == 0, "같은 리콜을 두 번 셌다"
    assert store.alert_count() == 1


def test_the_sweep_never_calls_the_government_api(app_with_tmp_store):
    """워치 항목이 N개여도 정부 호출은 **0회**다.

    로컬 사본(`RecallIndex`) 위에서 돌기 때문이다. 그래서 전체 스윕을
    자동화해도 부담이 없다 - `run_sweep` docstring 이 적어 둔 그 전환 덕분이다.
    """
    m, store, recalls, kats = app_with_tmp_store
    for i in range(5):
        _item(store, id=f"w-{i}", model_name=f"MDL-{i}")
    recalls.all_records.return_value = [_recall()]

    m._full_sweep(on=date(2026, 9, 9))

    assert kats.search_recalls.call_count == 0
    assert kats.lookup_certification.call_count == 0
    assert kats.lookup_certification_cached.call_count == 0


def test_a_sweep_failure_does_not_stop_the_sync(app_with_tmp_store):
    """남의 API 장애로 우리 루프를 멈추지 않는 것과 같은 원칙이다."""
    m, _store, recalls, _kats = app_with_tmp_store
    recalls.all_records.side_effect = RuntimeError("색인이 깨졌다")

    m._on_recalls_updated()   # 던지지 않아야 한다
    recalls.invalidate.assert_called()


# ── 노출 ────────────────────────────────────────────────────────────
def test_healthz_says_when_we_last_checked(app_with_tmp_store):
    """이 값이 오래 안 움직이면 **약속이 조용히 깨진 것**이다."""
    m, store, recalls, _kats = app_with_tmp_store
    client = TestClient(m.app)

    before = client.get("/healthz").json()["watch_sweep"]
    assert before["last_full_sweep_at"] is None

    _item(store)
    recalls.all_records.return_value = [_recall()]
    m._full_sweep(on=date(2026, 9, 9))

    after = client.get("/healthz").json()["watch_sweep"]
    assert after["last_full_sweep_at"]
    assert after["last_full_sweep_items"] == "1"
    assert after["last_full_sweep_new"] == "1"
    assert after["alerts_stored"] == 1


def test_the_watch_endpoint_carries_the_sweep_and_the_stored_alerts(
    app_with_tmp_store,
):
    """알림을 **저장된 것에서** 낸다 - 화면을 안 열어 본 사이의 것도 있다."""
    m, store, recalls, _kats = app_with_tmp_store
    client = TestClient(m.app)
    _item(store)
    recalls.all_records.return_value = [_recall()]
    m._full_sweep(on=date(2026, 9, 9))

    body = client.get("/api/v1/watch?owner_id=owner-1").json()
    assert set(body) == {"items", "sweep", "alerts"}
    assert len(body["items"]) == 1
    assert len(body["alerts"]) == 1
    assert body["sweep"]["last_full_sweep_new"] == "1"


def test_the_screen_tolerates_both_response_shapes():
    """응답이 배열 → 객체로 바뀌었다. 기존 화면을 깨뜨리지 않는다.

    ⚠ **표시**는 주말 묶음이다 (미완 §6 [C-화면]). 여기서 한 것은 깨짐 방지뿐이다.
    """
    from pathlib import Path

    html = Path("sourcing_guard/static/watch.html").read_text(encoding="utf-8")
    assert "(data && data.items) || data" in html
    # 정적 자산에는 이모지·경고 기호를 쓰지 않는다 (test_no_emoji_anywhere).
    # 이 줄을 넣을 때 실제로 그 검사에 걸렸다.
    assert "\u26a0" not in html


# ── 경계 ────────────────────────────────────────────────────────────
def test_sweep_stays_a_pure_function():
    """저장과 시각 기록은 `main.py` 가 한다. `watchlist.sweep` 은 그대로다."""
    import inspect

    from sourcing_guard import watchlist

    src = inspect.getsource(watchlist.sweep)
    for banned in ("_store", "save_alerts", "set_sync_state", "sqlite"):
        assert banned not in src, f"sweep 이 저장을 한다: {banned}"


def test_the_v1_scope_comment_no_longer_says_on_demand():
    """주석이 코드보다 뒤처지면 다음 사람이 "버튼식" 이라고 믿는다."""
    from pathlib import Path

    src = Path("sourcing_guard/main.py").read_text(encoding="utf-8")
    assert "v1 scope: register + **automatic** sweep + display" in src
    assert "전달(delivery)은 여전히 범위 밖이다" in src
