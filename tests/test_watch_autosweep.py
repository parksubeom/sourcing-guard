"""[C-백] 감시 자동화 — 사람이 버튼을 눌러야 도는 것은 보증이 아니다.

기획서 §6.1 이 유일하게 보증한다고 적은 것은 "나중에 리콜 공표되면 가장 먼저
알린다" 다. 전에는 셀러가 `/watch` 화면에서 버튼을 눌러야만 스윕이 돌았고,
**화면을 안 열어 본 셀러는 리콜이 공표돼도 몰랐다.**

이제 리콜 동기화가 새 레코드를 쓰면 전체 스윕이 돌고 알림이 디스크에 남는다.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

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


# ── [C-백 마감] 응답 스키마와 문서 ──────────────────────────────────
def test_the_watch_response_schema_is_pinned():
    """`GET /api/v1/watch` 의 모양을 잠근다.

    ⚠ 이 응답은 **배열 → 객체**로 바뀌었다(C-백). 소비자는 `watch.html`
      하나뿐이고 양쪽을 받게 고쳤지만, 모양이 또 바뀌면 화면이 조용히 빈다.
      필드를 지우거나 이름을 바꾸는 변경은 여기서 깨져야 한다.
    """
    from sourcing_guard.main import WatchListResponse, app

    fields = WatchListResponse.model_fields
    assert set(fields) == {"items", "sweep", "alerts"}, sorted(fields)

    # 실제 응답도 같은 모양이어야 한다 - 스키마만 맞고 핸들러가 다르면 무의미.
    with TestClient(app) as client:
        body = client.get("/api/v1/watch", params={"owner_id": "schema-probe"}).json()
    assert set(body) == {"items", "sweep", "alerts"}
    assert isinstance(body["items"], list)
    assert isinstance(body["alerts"], list)
    assert isinstance(body["sweep"], dict)
    # sweep 은 "마지막 스윕 시각 · 워치 수 · 새 알림 N · 쌓인 알림" 을 말해야 한다.
    # ⚠ 키 이름을 여기 적어 두는 이유는 화면이 이 이름으로 읽기 때문이다.
    #   처음에 `items`/`new_alerts` 로 적었다가 틀렸다 - 실제는 아래다.
    for key in ("last_full_sweep_at", "last_full_sweep_items",
                "last_full_sweep_new", "alerts_stored"):
        assert key in body["sweep"], f"{key} 가 없다: {sorted(body['sweep'])}"


def test_the_readme_describes_the_automatic_sweep():
    """README 가 "버튼을 눌러야 돈다" 로 남아 있으면 안 된다.

    ⚠ 문서가 코드보다 앞서 나가는 것이 이 저장소의 반복 결함이다. 자동 스윕은
      기획서 §6.1 이 보증한다고 적은 것의 실행부이므로 README 가 말해야 한다.
    """
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    row = next((ln for ln in readme.splitlines() if "`main.py`" in ln), "")
    assert row, "README 에서 main.py 행을 못 찾았다"
    assert "자동" in row and "스윕" in row, row
    assert "{items, sweep, alerts}" in row, "GET 응답 모양이 적혀 있지 않다"


def test_the_hackathon2_snapshot_cannot_run():
    """`해커톤2/` 가 **실행 불가능한 초기 뼈대**임을 기록해 둔다.

    ⚠ 심사위원이 파일 목록을 보면 `/api/v1/watch` 가 두 곳에 있는 것으로
      읽힌다. 지우는 것은 시피님 확인 뒤이므로(미완 §5) 지금은 "돌지 않는다" 는
      사실만 잠근다 - 누가 실수로 살려 놓으면 여기서 깨진다.

    ⚠ 이 검사가 깨지면 **디렉터리를 지웠는지 먼저 확인할 것.** 지웠으면 이
      검사도 함께 지운다.
    """
    root = Path(__file__).resolve().parents[1]
    old = root / "해커톤2"
    if not old.is_dir():
        pytest.skip("해커톤2/ 가 이미 정리됐다 - 이 검사도 지울 것")

    # 상대 import 인데 패키지가 아니다.
    assert not (old / "__init__.py").exists()
    main_src = (old / "main.py").read_text(encoding="utf-8")
    assert "from .config import settings" in main_src

    # main.py 가 필요로 하는 모듈 대부분이 이 디렉터리에 없다.
    needed = set(re.findall(r"from \.([a-z_]+) import", main_src))
    present = {p.stem for p in old.glob("*.py")}
    assert needed - present, "필요 모듈이 다 있다 - 돌 수 있게 됐나"

    # pytest 가 수집하지 않는다.
    ini = (root / "pytest.ini").read_text(encoding="utf-8")
    assert "testpaths = tests" in ini
