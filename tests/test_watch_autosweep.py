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
    assert after["last_full_sweep_items"] == 1
    assert after["last_full_sweep_new"] == 1
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
    assert body["sweep"]["last_full_sweep_new"] == 1


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
    #   `last_swept_at` 은 **소유자별**이고 머리말이 읽는 값이다 - 전역
    #   `last_full_sweep_*` 를 화면이 읽으면 남의 알림 수가 뜬다 ([C-화면]).
    for key in ("last_swept_at", "last_full_sweep_at", "last_full_sweep_items",
                "last_full_sweep_new", "alerts_stored"):
        assert key in body["sweep"], f"{key} 가 없다: {sorted(body['sweep'])}"

    # ⚠ **타입까지 본다.** 배포본에서 `"5"`·`"1"` 이 나왔다 - `sync_state` 가
    #   TEXT 저장소라 문자열이 그대로 새 나갔다. 화면이 그걸 받으면 비교·합산이
    #   조용히 틀린다(`"5" > "10"` 이 참이다).
    sweep = body["sweep"]
    for key in ("last_full_sweep_items", "last_full_sweep_new", "alerts_stored"):
        assert sweep[key] is None or isinstance(sweep[key], int), (
            f"{key} 가 {type(sweep[key]).__name__} 이다 - int 여야 한다: {sweep[key]!r}"
        )
    # 시각은 문자열(ISO)이고 값이 없으면 None 이다.
    for key in ("last_full_sweep_at", "last_swept_at"):
        assert sweep[key] is None or isinstance(sweep[key], str), (
            f"{key} 가 {type(sweep[key]).__name__} 이다"
        )


def test_the_readme_describes_the_automatic_sweep():
    """README 가 "버튼을 눌러야 돈다" 로 남아 있으면 안 된다.

    ⚠ 문서가 코드보다 앞서 나가는 것이 이 저장소의 반복 결함이다. 자동 스윕은
      기획서 §6.1 이 보증한다고 적은 것의 실행부이므로 README 가 말해야 한다.
    """
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    # ⚠ **한 줄에 매여 있었다.** 2026-09-14 에 README 를 셀러용으로 다시 쓰면서
    #   `main.py` 행의 문구가 바뀌자, 사실이 README 안에 남아 있는데도 걸렸다.
    #   어디에 적혔는지가 아니라 **적혔는지**를 본다.
    assert "자동" in readme and "스윕" in readme, "자동 스윕이 README 에 없다"

    # ① 셀러가 읽는 자리. 개발자 표에만 있으면 "내가 눌러야 하나" 에 답이 없다.
    row = next((ln for ln in readme.splitlines() if "| 감시 목록 |" in ln), "")
    assert row, "README 에서 감시 목록 행을 못 찾았다"
    assert "자동" in row and "매일" in row, row

    # ② 개발자가 읽는 자리. 응답 모양이 바뀐 적이 있어 함께 잠근다.
    dev = next((ln for ln in readme.splitlines() if "`main.py`" in ln), "")
    assert dev, "README 에서 main.py 행을 못 찾았다"
    assert "자동 스윕" in dev, dev
    assert "{items, sweep, alerts}" in dev, "GET 응답 모양이 적혀 있지 않다"


# ── [C-화면] 실물 확인에서 잰 결함 넷 (2026-09-13) ──────────────────
#
# RED 데모 상품(모형완구 기차놀이 · CB067R317-5002)을 /watch 에 등록하고
# "지금 대조하기" 를 눌렀다. `alerts[]` 는 실제로 생겼다. 그런데 **화면이
# 그것을 잘못 말했다** - 아래 넷이 그 실측이다.
def test_the_header_numbers_belong_to_this_owner_not_to_everyone(
    app_with_tmp_store,
):
    """⚠⚠ **남의 알림 수가 내 화면에 뜨던 것.**

    `last_full_sweep_new` 는 전체 배치가 전 소유자를 돌고 적은 **전역** 수다.
    화면 머리말은 "감시 N건 · … · 새 알림 N" 이라 셀러는 그것을 자기 것으로
    읽는다. 실측: 저장된 알림이 0건인 owner-2 의 머리말이 "새 알림 1" 을
    그렸고, 그 1건은 owner-1 것이었다.

    **없는데 있다고 하는 쪽**이라 반대 방향보다 비싸다 (§6).
    """
    m, store, recalls, _kats = app_with_tmp_store
    _item(store, id="w-a", owner_id="owner-1")                       # 리콜에 걸린다
    _item(store, id="w-b", owner_id="owner-2", model_name="NO-HIT-0001")
    recalls.all_records.return_value = [_recall()]
    m._full_sweep(on=date(2026, 9, 9))

    a = m._sweep_snapshot("owner-1")
    b = m._sweep_snapshot("owner-2")

    # 전역 값은 둘 다 같다 - 그래서 화면이 그것을 읽으면 안 된다.
    assert a["last_full_sweep_new"] == b["last_full_sweep_new"] == 1
    # 소유자별 값은 갈린다. 화면은 이것을 읽는다.
    assert a["alerts_stored"] == 1
    assert b["alerts_stored"] == 0


def test_pressing_the_button_moves_the_date_the_screen_shows(app_with_tmp_store):
    """⚠ 셀러가 "지금 대조하기" 를 눌렀는데 "마지막 대조" 가 안 움직이던 것.

    버튼(`run_sweep`)은 항목의 `last_swept_at` 만 갱신하고 전역
    `last_full_sweep_at` 은 건드리지 않는다(전체 배치가 아니므로 그게 맞다).
    화면이 전역 값을 읽고 있어서, 이 화면이 하는 유일한 약속 - "언제까지
    확인했나" - 가 틀렸다.
    """
    m, store, recalls, _kats = app_with_tmp_store
    _item(store, id="w-a", owner_id="owner-1")
    recalls.all_records.return_value = []

    assert m._sweep_snapshot("owner-1")["last_swept_at"] is None  # 아직 안 돌았다
    m.run_sweep("owner-1")

    snap = m._sweep_snapshot("owner-1")
    assert snap["last_swept_at"] == date.today().isoformat()
    # 전역 값은 여전히 비어 있다 - 버튼은 전체 배치가 아니다. 그게 맞다.
    assert snap["last_full_sweep_at"] is None


def test_the_sweep_response_is_always_a_subset_of_the_stored_alerts(
    app_with_tmp_store,
):
    """화면이 **저장본만** 그리게 바꿨다. 그 전제를 여기서 잠근다.

    버튼 응답을 화면에서 버리는 것이 안전한 이유는 `run_sweep` 이
    `save_alerts` 를 부른 **뒤에** 응답하기 때문이다. 순서가 바뀌면 방금 잡힌
    알림이 화면에서 사라진다 - 놓친 알림이고 R6 이 막으려던 바로 그것이다.
    """
    m, store, recalls, _kats = app_with_tmp_store
    _item(store, id="w-a", owner_id="owner-1")
    recalls.all_records.return_value = [_recall()]

    returned = m.run_sweep("owner-1")
    stored = {a.recall_fingerprint for a in store.alerts_for_owner("owner-1")}

    assert returned, "리콜에 걸리는 입력인데 스윕이 빈 목록을 줬다"
    assert {a.recall_fingerprint for a in returned} <= stored


def test_the_watch_screen_reads_owner_scoped_values_and_draws_each_alert_once():
    """화면 원본이 전역 값을 다시 읽지 않는지, 알림을 두 곳에서 채우지 않는지."""
    html = Path("sourcing_guard/static/watch.html").read_text(encoding="utf-8")
    body = re.sub(r"//[^\n]*", "", html)  # 주석은 근거 기록이라 검사 대상이 아니다

    # 머리말은 소유자별 값만 읽는다.
    assert "sweep.last_swept_at" in body
    assert "sweep.alerts_stored" in body
    assert "last_full_sweep_at" not in body, "화면이 전역 시각을 다시 읽는다"
    assert "last_full_sweep_new" not in body, "화면이 남의 알림 수를 다시 읽는다"

    # 알림 목록의 소유자는 load() 하나다. 스윕 응답으로 또 채우면 두 줄이 된다.
    #
    # ⚠ **쓰는 자리만 센다.** 처음에 `freshAlerts[` 를 통째로 셌다가 걸렸다 -
    #   itemRow 의 **읽기**(`freshAlerts[it.id] || []`)까지 세어 3 이 나왔다.
    #   읽기는 몇 곳이든 상관없다. 문제는 채우는 곳이 둘인 것이다.
    writes = re.findall(r"freshAlerts\[[^\]]+\]\s*=", body)
    assert len(writes) == 1, f"freshAlerts 를 {len(writes)} 곳에서 채운다"

    # 공표일(YYYYMMDD)을 사람이 읽는 모양으로 낸다.
    assert 'if (/^\\d{8}$/.test(t))' in body


# ── ②-a 감시 해제 (2026-09-14) ──────────────────────────────────────
#
# 셀러가 넣은 것을 못 지우는 상태를 없앤다. 잘못 등록한 항목이 목록에 영원히
# 남으면 진짜 알림이 그 사이에 묻힌다 - R6 이 막으려는 것의 반대 방향 비용이다.


def _client_with_store(tmp_path, monkeypatch):
    import sourcing_guard.main as m
    from fastapi.testclient import TestClient

    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.recall_index import RecallIndex
    from sourcing_guard.rra_client import RraClient
    from sourcing_guard.storage import SqliteWatchStore

    store = SqliteWatchStore(str(tmp_path / "w.db"))
    monkeypatch.setattr(m, "_store", store)
    monkeypatch.setattr(m, "_recalls", RecallIndex(store))
    monkeypatch.setattr(m, "_kats", KatsClient(None, None, mock=True))
    monkeypatch.setattr(m, "_rra", RraClient(mock=True))
    return TestClient(m.app), store


def _register(client, owner: str, **facts) -> str:
    body = {"product_name": "감시 해제 시험 상품", "model_name": "DEL-1", **facts}
    r = client.post("/api/v1/watch",
                    json={"owner_id": owner, "facts_from_scan": body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_unwatch_removes_only_my_own_item(tmp_path, monkeypatch):
    """남의 id 와 없는 id 를 **구분하지 않는다** - 둘 다 404.

    구분하면 "그 id 는 존재한다" 를 남에게 알려 주는 셈이다.
    """
    client, _ = _client_with_store(tmp_path, monkeypatch)
    item_id = _register(client, "own-A")

    assert client.delete(f"/api/v1/watch/{item_id}?owner_id=own-B").status_code == 404
    assert client.delete("/api/v1/watch/nope?owner_id=own-A").status_code == 404
    # 남의 시도로 사라지지 않았다
    assert len(client.get("/api/v1/watch?owner_id=own-A").json()["items"]) == 1

    assert client.delete(f"/api/v1/watch/{item_id}?owner_id=own-A").status_code == 204
    assert client.get("/api/v1/watch?owner_id=own-A").json()["items"] == []


def test_unwatch_takes_the_alerts_with_it(tmp_path, monkeypatch):
    """알림을 남기면 주인 없는 행이 되어 `alert_count` 가 계속 센다."""
    from datetime import date

    from sourcing_guard.models import MatchStrength, RecallAlert

    client, store = _client_with_store(tmp_path, monkeypatch)
    item_id = _register(client, "own-A")
    store.save_alerts([
        RecallAlert(
            watch_item_id=item_id, recall_fingerprint="fp-1",
            strength=MatchStrength.WEAK, matched_on="model_name",
            statement_ko="유사 일치하는 항목이 공표되었습니다. 원문 확인이 필요합니다.",
            source_label="국가기술표준원", source_url="https://www.safetykorea.kr/",
            detected_at=date(2026, 9, 13),
        )
    ])
    assert store.alert_count() == 1
    assert len(client.get("/api/v1/watch?owner_id=own-A").json()["alerts"]) == 1

    assert client.delete(f"/api/v1/watch/{item_id}?owner_id=own-A").status_code == 204
    assert store.alert_count() == 0, "주인 없는 알림 행이 남았다"


def test_the_watch_screen_offers_the_button(pages=None):
    """화면에 유령 버튼이 아니라 **실제로 부르는** 버튼이 있어야 한다."""
    html = (Path(__file__).resolve().parents[1] / "sourcing_guard" / "static"
            / "watch.html").read_text(encoding="utf-8")
    assert "data-unwatch" in html and "감시 해제" in html
    assert 'method: "DELETE"' in html
    # 서버가 지웠는지 **확인한 뒤** 목록을 다시 그린다. 화면에서 먼저 지우면
    # 실패했을 때 "사라진 줄 알았는데 있는" 상태가 된다.
    body = html[html.index("function wireUnwatch("):]
    body = body[: body.index("\n  }")]
    assert "r.status !== 204" in body
    assert "load()" in body
    # 되돌릴 수 없으므로 한 번 묻는다.
    assert "window.confirm" in body


def test_the_manual_sync_sweeps_too_not_just_invalidates():
    """⚠⚠ **수동 동기화도 스윕한다** (2026-09-18 실측으로 잡았다).

    `POST /api/v1/sync` 가 `on_updated=_recalls.invalidate` 를 넘기고 있었다 -
    색인만 버리고 **전체 스윕을 안 돌렸다.** 그래서 이 경로로 들어온 새 리콜은
    워치 항목과 대조되지 않았다.

    실측: 수동 동기화로 새 레코드 11건(국내 2 · 국외 9)이 들어왔는데
    `last_full_sweep_at` 이 2026-09-15 에서 안 움직였다.

    ⚠ 그 엔드포인트의 docstring 이 적은 용도("데모 직전에 강제로 최신화")가
      정확히 위험한 자리다 - 데모 직전에 부르면 새 리콜이 조용히 들어오고
      아무에게도 안 알린다. **놓친 알림이 우리가 하는 유일한 약속을 깨뜨린다**
      (R6 · 기획서 §6.1).

    ⚠ 같은 판단을 두 곳에 적지 않는다 (§6). 루프와 수동 경로가 **같은 이름**을
      부르는지를 본다 - 이름이 갈리면 한쪽만 고쳐도 나머지가 조용히 틀린다.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "sourcing_guard/main.py").read_text(
        encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))

    # 배경 루프가 쓰는 이름.
    loop = re.search(r"sync_loop\((.*?)\n\s*\)\n", code, re.S)
    assert loop, "sync_loop 호출을 못 찾았다 - main.py 모양이 바뀌었다"
    assert "on_updated=_on_recalls_updated" in loop.group(1), loop.group(1)[:200]

    # 수동 경로가 **같은 이름**을 쓰는가.
    manual = re.search(r"def trigger_sync\(.*?\n\n\n", code, re.S)
    assert manual, "trigger_sync 를 못 찾았다"
    body = manual.group(0)
    assert "on_updated=_on_recalls_updated" in body, (
        "수동 동기화가 전체 스윕을 안 돌린다 - 이 경로로 들어온 리콜은 "
        "워치 항목과 대조되지 않는다 (R6)"
    )
    assert "on_updated=_recalls.invalidate" not in body, (
        "색인 무효화만 넘기고 있다 - 스윕이 빠진다")
