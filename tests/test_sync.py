"""리콜 로컬 동기화.

동기화 실패가 앱을 죽이면 안 된다. 정부 API 가 죽어도 스캔은 계속돼야 한다.
그리고 놓친 리콜은 이 서비스가 하는 유일한 약속을 깨뜨린다 (CLAUDE.md R6).
"""

from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import pytest

from sourcing_guard.kats_client import KatsApiError, RecallRecord
from sourcing_guard.storage import SqliteWatchStore
from sourcing_guard.sync import month_windows, run_sync


def rec(uid: str, *, on: str = "20260723", scope: str = "domestic", model: str = "M-1"):
    return RecallRecord(
        product_name="완구",
        model_name=model,
        maker="제조사",
        reason="사유",
        announced_on=on,
        detail_url=None,
        scope=scope,
        models=[model],
        cert_numbers=["CB061R2170-3018"],
        uid=uid,
    )


@dataclass
class StubClient:
    """전량/증분 응답을 지정하고 호출을 기록한다."""

    full: dict = field(default_factory=dict)
    monthly: dict = field(default_factory=dict)
    fail_scopes: set = field(default_factory=set)
    calls: list = field(default_factory=list)

    def recalls_all(self, *, overseas: bool = False):
        scope = "overseas" if overseas else "domestic"
        self.calls.append(("all", scope))
        if scope in self.fail_scopes:
            raise KatsApiError("5000", "테스트 실패")
        return self.full.get(scope, [])

    def recalls_published_on(self, date_prefix: str, *, overseas: bool = False):
        scope = "overseas" if overseas else "domestic"
        self.calls.append((date_prefix, scope))
        if scope in self.fail_scopes:
            raise KatsApiError("5000", "테스트 실패")
        return self.monthly.get((scope, date_prefix), [])


@pytest.fixture
def store(tmp_path: Path):
    return SqliteWatchStore(tmp_path / "t.db")


# ---------------------------------------------------------------------------
# 월 윈도우 — 월초에 전월 마지막 공표를 놓치면 안 된다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("today,expected", [
    (date(2026, 9, 1), ["202609", "202608"]),
    (date(2026, 9, 30), ["202609", "202608"]),
    (date(2026, 1, 1), ["202601", "202512"]),   # 연도 경계
    (date(2026, 3, 1), ["202603", "202602"]),
])
def test_month_windows_always_include_previous_month(today, expected):
    """당월만 받으면 1일에 전월 마지막 공표를 놓친다."""
    assert month_windows(today) == expected


# ---------------------------------------------------------------------------
# 초기 적재와 증분
# ---------------------------------------------------------------------------


def test_first_run_is_initial_and_uses_full_dump(store):
    # min_plausible=0: 이 테스트의 관심사는 "첫 실행은 전량 조회" 다.
    # 건수 임계값은 test_thin_full_load_rolls_back_both_rows_and_flag 가 본다.
    client = StubClient(full={"domestic": [rec("1"), rec("2")],
                              "overseas": [rec("3", scope="overseas")]})
    report = run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    assert report.mode == "initial"
    assert report.ok
    assert {c[0] for c in client.calls} == {"all"}
    assert store.recall_count("domestic") == 2
    assert store.recall_count("overseas") == 1


def test_second_run_is_incremental_and_uses_month_prefix(store):
    client = StubClient(full={"domestic": [rec("1")], "overseas": []})
    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)
    client.calls.clear()

    # min_plausible=0: 이 테스트의 관심사는 "완료 표시가 있으면 증분" 이다.
    # 불완전 적재 복구는 test_incomplete_load_is_redone_even_if_marked_complete 가 본다.
    report = run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    assert report.mode == "incremental"
    # all=% 는 설계서 밖 사용법이라 초기 적재 1회에만 쓴다.
    assert "all" not in {c[0] for c in client.calls}
    assert {c[0] for c in client.calls} == {"202609", "202608"}


def test_new_records_are_detected_by_uid_not_by_date(store):
    """국내 응답은 정렬 보장이 없고 소량 공표가 매달 끼어든다.

    날짜로 비교하면, 이미 받은 날짜에 뒤늦게 추가된 건을 놓친다.
    """
    client = StubClient(full={"domestic": [rec("1", on="20260723")], "overseas": []})
    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    # 같은 날짜에 새 uid 가 추가된 상황
    client.monthly[("domestic", "202609")] = [
        rec("1", on="20260723"),
        rec("99", on="20260723"),
    ]
    report = run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    assert report.new["domestic"] == 1
    assert store.recall_count("domestic") == 2


def test_records_without_uid_are_skipped(store):
    """uid 가 없으면 신규 판정을 할 수 없다. 저장하면 매번 새 것으로 보인다."""
    no_uid = rec("x")
    object.__setattr__(no_uid, "uid", None)
    client = StubClient(full={"domestic": [rec("1"), no_uid], "overseas": []})

    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)
    assert store.recall_count("domestic") == 1


# ---------------------------------------------------------------------------
# 실패해도 앱은 산다
# ---------------------------------------------------------------------------


def test_api_failure_never_raises(store):
    client = StubClient(fail_scopes={"domestic", "overseas"})
    report = run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)   # 예외가 나면 실패

    assert report.ok is False
    assert len(report.errors) == 2


def test_partial_failure_does_not_mark_initial_load_complete(store):
    """반쪽 적재를 완료로 기록하면 다음 실행이 증분으로 넘어가 빈 구간이 영구히 남는다."""
    client = StubClient(full={"domestic": [rec("1")]}, fail_scopes={"overseas"})
    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    assert store.get_sync_state("initial_load_at") is None

    # 복구되면 다시 초기 적재를 시도해야 한다.
    client.fail_scopes.clear()
    client.full["overseas"] = [rec("2", scope="overseas")]
    report = run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    assert report.mode == "initial"
    assert store.get_sync_state("initial_load_at") is not None


def test_failure_is_recorded_for_the_operator(store):
    client = StubClient(fail_scopes={"domestic", "overseas"})
    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    assert store.get_sync_state("last_sync_error")
    assert store.get_sync_state("last_sync_at")


def test_successful_run_clears_the_previous_error(store):
    client = StubClient(fail_scopes={"domestic", "overseas"})
    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)
    assert store.get_sync_state("last_sync_error")

    client.fail_scopes.clear()
    client.full = {"domestic": [rec("1")], "overseas": []}
    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    assert store.get_sync_state("last_sync_error") == ""


def test_force_initial_redoes_the_full_load(store):
    client = StubClient(full={"domestic": [rec("1")], "overseas": []})
    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)
    client.calls.clear()

    report = run_sync(client, store, force_initial=True, today=date(2026, 9, 1), min_plausible=0)

    assert report.mode == "initial"
    assert {c[0] for c in client.calls} == {"all"}


# ---------------------------------------------------------------------------
# 캐시 기준일 — 3단계에서 화면에 표시할 값
# ---------------------------------------------------------------------------


def test_snapshot_reports_latest_published_date(store):
    client = StubClient(full={
        "domestic": [rec("1", on="20260723"), rec("2", on="20260811")],
        "overseas": [rec("3", on="20260828", scope="overseas")],
    })
    run_sync(client, store, today=date(2026, 9, 1), min_plausible=0)

    snap = store.sync_snapshot()
    assert snap["latest_published_on"] == "20260828"
    assert snap["recalls"] == {"domestic": 2, "overseas": 1}
    assert snap["initial_load_at"]


# ---------------------------------------------------------------------------
# 수동 트리거 — 백그라운드 루프의 보조
# ---------------------------------------------------------------------------


def test_manual_sync_is_forbidden_without_a_token(monkeypatch):
    """토큰 미설정을 '인증 없음' 으로 해석하면 공개 배포에서 아무나 부를 수 있다.

    그러면 정부 API 로 트래픽이 그대로 간다.
    """
    from fastapi.testclient import TestClient

    from sourcing_guard import main

    # Settings 는 frozen dataclass 다. 필드를 바꾸지 말고 인스턴스를 갈아끼운다.
    monkeypatch.setattr(main, "settings", replace(main.settings, sync_token=None))
    with TestClient(main.app) as client:
        assert client.post("/api/v1/sync").status_code == 403
        assert client.post("/api/v1/sync", headers={"X-Sync-Token": "anything"}).status_code == 403


def test_manual_sync_rejects_a_wrong_token(monkeypatch):
    from fastapi.testclient import TestClient

    from sourcing_guard import main

    monkeypatch.setattr(main, "settings", replace(main.settings, sync_token="right-token"))
    with TestClient(main.app) as client:
        assert client.post("/api/v1/sync", headers={"X-Sync-Token": "wrong-token"}).status_code == 403


def test_healthz_exposes_sync_state():
    """운영자가 동기화가 도는지, 마지막이 언제였는지 볼 수 있어야 한다."""
    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    with TestClient(app) as client:
        body = client.get("/healthz").json()

    assert "sync" in body
    for key in ("enabled", "initial_load_at", "last_sync_at", "last_sync_error",
                "recalls", "latest_published_on"):
        assert key in body["sync"], key
    # 동기화가 실패해도 서비스는 살아 있어야 한다.
    assert body["ok"] is True


def test_incomplete_load_is_redone_even_if_marked_complete(store):
    """적재 완료 표시와 실제 데이터가 어긋나면 전량을 다시 받는다.

    실제로 겪었다 - initial_load_at 은 찍혀 있는데 recalls 가 255건(증분분)만
    있었다. 그 상태에서는 다음 실행도 증분이라 영원히 복구되지 않고, 그동안
    스캔은 조용히 "리콜 이력 없음" 을 돌려준다 (R6).
    """
    from sourcing_guard.sync import MIN_PLAUSIBLE_RECALLS

    # 완료로 기록만 해두고 데이터는 거의 없는 상태를 만든다.
    store.set_sync_state("initial_load_at", "2026-09-01T00:00:00+00:00")
    client = StubClient(full={"domestic": [rec("1")], "overseas": []})
    store.upsert_recalls(
        [{"uid": "old", "published_on": "20260101", "payload": "{}"}],
        scope="domestic", fetched_at="2026-09-01T00:00:00+00:00",
    )
    assert store.recall_count() < MIN_PLAUSIBLE_RECALLS

    report = run_sync(client, store, today=date(2026, 9, 1))

    assert report.mode == "initial", "증분으로 돌아 복구되지 않습니다"
    assert {c[0] for c in client.calls} == {"all"}


def test_a_healthy_full_load_still_goes_incremental(store):
    """정상 적재분까지 매번 다시 받으면 정부 서버에 매일 38MB 를 요청하게 된다."""
    from sourcing_guard.sync import MIN_PLAUSIBLE_RECALLS

    store.set_sync_state("initial_load_at", "2026-09-01T00:00:00+00:00")
    store.upsert_recalls(
        [{"uid": f"u{i}", "published_on": "20260101", "payload": "{}"}
         for i in range(MIN_PLAUSIBLE_RECALLS + 1)],
        scope="domestic", fetched_at="2026-09-01T00:00:00+00:00",
    )
    client = StubClient()

    report = run_sync(client, store, today=date(2026, 9, 1))

    assert report.mode == "incremental"
    assert "all" not in {c[0] for c in client.calls}


# ---------------------------------------------------------------------------
# 반쪽 적재가 완료로 기록되지 않게 — 근본 원인
#
# 정부 API 가 2004(No Data)나 빈 resultData 를 돌려주면 _call 이 [] 를 반환한다.
# 그건 오류가 아니라서 호출부가 성공으로 읽고, 0건 적재가 완료로 기록됐다.
# 그 뒤로는 증분만 돌아 255건(당월+전월)이 쌓였고, 스캔은 조용히
# "리콜 이력 없음" 을 돌려줬다. 실제로 겪은 상태다.
# ---------------------------------------------------------------------------


class EmptyClient:
    """API 가 빈 목록을 돌려주는 경우. 예외가 아니라 정상 응답이다."""

    def recalls_all(self, *, overseas=False):
        return []

    def recalls_published_on(self, date_prefix, *, overseas=False):
        return []


def test_empty_api_response_is_not_recorded_as_complete(store):
    report = run_sync(EmptyClient(), store, today=date(2026, 9, 1))

    assert store.get_sync_state("initial_load_at") is None, "0건이 완료로 기록됐습니다"
    assert report.ok is False
    assert store.recall_count() == 0


def test_thin_full_load_rolls_back_both_rows_and_flag(store):
    """적재와 완료 표시는 한 트랜잭션이다. 하나만 남으면 상태가 갈린다."""
    client = StubClient(full={"domestic": [rec("1"), rec("2")], "overseas": [rec("3", scope="overseas")]})

    report = run_sync(client, store, today=date(2026, 9, 1), min_plausible=1000)

    assert store.get_sync_state("initial_load_at") is None
    assert store.recall_count() == 0, "완료로 못 찍을 적재분이 남았습니다"
    assert report.ok is False


def test_full_load_writes_rows_and_flag_together(store):
    client = StubClient(
        full={"domestic": [rec(str(i)) for i in range(30)],
              "overseas": [rec(f"o{i}", scope="overseas") for i in range(30)]}
    )

    report = run_sync(client, store, today=date(2026, 9, 1), min_plausible=10)

    assert report.ok
    assert store.recall_count() == 60
    assert store.get_sync_state("initial_load_at")
    assert report.new == {"domestic": 30, "overseas": 30}


def test_half_finished_load_is_not_marked_complete(store):
    """한 스코프만 성공하면 아무것도 쓰지 않는다."""
    client = StubClient(full={"domestic": [rec(str(i)) for i in range(30)]},
                        fail_scopes={"overseas"})

    run_sync(client, store, today=date(2026, 9, 1), min_plausible=10)

    assert store.get_sync_state("initial_load_at") is None
    assert store.recall_count() == 0


# ---------------------------------------------------------------------------
# 갱신 후 인덱스 무효화 — "처음 본 uid" 가 아니라 "무언가 썼는가"
#
# 제조사 필드를 바꾸고 전량 재적재했는데, 이미 알던 레코드라 new=0 이 나와
# invalidate 가 안 불렸다. 디스크는 새 값인데 서빙 인덱스가 옛 값을 계속
# 들고 있었다 - 프로덕션에서 '이케아' 조회가 옛 기준 28건을 돌려줬다.
# ---------------------------------------------------------------------------


def test_index_is_invalidated_when_known_records_are_rewritten(monkeypatch, tmp_path):
    """새 uid 가 없어도 갱신했으면 인덱스를 다시 읽혀야 한다.

    정부가 기존 공표 내용을 정정하면 uid 는 그대로다. new=0 을 조건으로 두면
    정정된 내용이 앱 재시작 전까지 반영되지 않는다.
    """
    from sourcing_guard import sync as sync_mod

    calls = []

    class Store:
        def get_sync_state(self, key):
            return "2026-09-01T00:00:00+00:00" if key == "initial_load_at" else None

        def set_sync_state(self, key, value):
            pass

        def recall_count(self):
            return 37313

        def known_recall_uids(self, scope):
            return set()

        def commit_full_load(self, batches, **kw):
            # 전부 이미 알던 uid — 신규 0건
            return {scope: 0 for scope in batches}

    class Kats:
        def recalls_all(self, *, overseas=False):
            return [_rec(uid="1")]

        def recalls_published_on(self, window, *, overseas=False):
            return [_rec(uid="1")]

    def _rec(uid):
        from sourcing_guard.kats_client import RecallRecord

        return RecallRecord(
            product_name="완구", model_name="A-1", maker="이케아", reason="기준 초과",
            announced_on="20260801", detail_url="https://www.safetykorea.kr/x",
            scope="domestic", uid=uid,
        )

    report = sync_mod.run_sync(
        Kats(), Store(), force_initial=True, on_updated=lambda: calls.append(1)
    )
    assert not any(report.new.values()), "이 시나리오는 신규 0건이어야 의미가 있다"
    assert calls, "갱신했는데 인덱스 무효화가 호출되지 않았습니다"


def test_invalidate_condition_is_not_based_on_new_uids():
    """구현이 다시 report.new 기준으로 돌아가지 않게 고정한다."""
    from pathlib import Path

    src = Path("sourcing_guard/sync.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "any(report.new.values())" not in body
