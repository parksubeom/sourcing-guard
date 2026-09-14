"""[D-백] 오답 신고 — 저장만 한다. **판정을 바꾸지 않는다** (R1).

셀러가 등급 카드에서 "이 품목이 아닙니다" 를 누르면 원문·붙은 품목·추출 경로·
시각을 워치리스트와 같은 SQLite 볼륨에 쌓는다. 사람이 검수해서
`새표본235_오답.tsv` 로 옮기고, 그것이 별칭·가드를 고치는 근거가 된다.

⚠ 신고 즉시 등급이 사라지면 셀러가 판정기가 된다 - 없는 의무를 지우는 쪽으로
  악용된다. 그래서 이 파일의 첫 검사가 "신고 전후 스캔 결과가 같다" 다.
"""
from __future__ import annotations

import inspect
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import sourcing_guard.main as m
from sourcing_guard.kats_client import KatsClient
from sourcing_guard.ratelimit import RateLimiter
from sourcing_guard.recall_index import RecallIndex
from sourcing_guard.rra_client import RraClient
from sourcing_guard.storage import SqliteWatchStore

_ROOT = Path(__file__).resolve().parents[1]
_TEXT = "유아용 블록 완구 장난감 대상연령 3세 이상 합성수지제"


@pytest.fixture
def store(tmp_path, monkeypatch) -> SqliteWatchStore:
    """임시 DB. 실제 data/watchlist.db 에 신고를 쌓지 않는다."""
    s = SqliteWatchStore(str(tmp_path / "w.db"))
    monkeypatch.setattr(m, "_store", s)
    monkeypatch.setattr(m, "_recalls", RecallIndex(s))      # 비어 있음 → 결정적
    monkeypatch.setattr(m, "_kats", KatsClient(None, None, mock=True))
    monkeypatch.setattr(m, "_rra", RraClient(mock=True))
    return s


@pytest.fixture
def client(store):
    with TestClient(m.app) as c:
        yield c


def _report(client, **over):
    body = {
        "page_text": _TEXT,
        "matched_items": ["완구"],
        "extraction_path": "llm",
        "extractor_vendor": "gpt",
        "extractor_model": "gpt-5.4-mini",
    }
    body.update(over)
    return client.post("/api/v1/report-miss", json=body)


# ── R1: 신고는 판정을 바꾸지 않는다 ──────────────────────────────
def test_a_report_does_not_change_the_next_scan(client):
    before = client.post("/api/v1/scan", json={"page_text": _TEXT}).json()
    assert _report(client).status_code == 201
    after = client.post("/api/v1/scan", json={"page_text": _TEXT}).json()

    strip = lambda r: {k: v for k, v in r.items() if k not in ("meta", "recall_data_as_of")}
    assert strip(before) == strip(after), "신고가 판정을 바꿨다 (R1)"
    # 붙은 품목도 그대로다 - 신고한 '완구' 가 사라지면 셀러가 판정기가 된 것이다.
    items = lambda r: sorted(
        c["item"] for f in r["findings"] for c in (f.get("detail") or {}).get("candidates", [])
    )
    assert items(before) == items(after)


def test_the_handler_does_not_extract_verify_or_score():
    """소스로도 잠근다 - 저장만 한다."""
    src = inspect.getsource(m.report_miss)
    # ⚠ 호출 **모양**으로 본다. 처음에 "extract" 낱말로 걸었더니 로그 줄의
    #   `req.extraction_path` 에 걸렸다 - 가드가 자기 문구에 걸리는 그 패턴이다.
    for banned in ("extract(", "extract_traced(", "verify(", "score(",
                   "lookup_certification", "_recalls.", "_kats.", "_rra."):
        assert banned not in src, f"신고 핸들러가 {banned!r} 를 부른다 - 저장만 해야 한다"


# ── 저장 · 응답 ────────────────────────────────────────────────────
def test_the_report_is_stored_with_what_the_reviewer_needs(client, store):
    r = _report(client, note="이건 필통이다")
    assert r.status_code == 201, r.text
    ack = r.json()
    assert re.fullmatch(r"[0-9a-f]{12}", ack["id"])
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", ack["reported_at"])

    rows = store.miss_reports()
    assert len(rows) == 1
    rid, at, payload = rows[0]
    assert rid == ack["id"] and at == ack["reported_at"]
    d = json.loads(payload)
    # 검수자가 다시 볼 것 넷 - 원문 · 붙은 품목 · 추출 경로 · (시각은 열에)
    assert d["page_text"] == _TEXT
    assert d["matched_items"] == ["완구"]
    assert d["extraction_path"] == "llm" and d["extractor_vendor"] == "gpt"
    assert d["note"] == "이건 필통이다"


def test_client_ip_is_used_for_the_limit_but_never_stored(client, store):
    _report(client)
    _, _, payload = store.miss_reports()[0]
    assert "ip" not in payload.lower() and "testclient" not in payload.lower()
    # 저장 함수 시그니처에도 ip 자리가 없다.
    assert "ip" not in inspect.signature(store.save_miss_report).parameters


def test_the_ack_wording_does_not_promise(client):
    """§9 — "반영됐다" 가 아니라 "검수하겠다" 이고, 결과가 안 바뀜을 말한다."""
    msg = _report(client).json()["message"]
    assert "바뀌지 않습니다" in msg
    assert "검수" in msg
    for banned in ("반영되었습니다", "수정되었습니다", "안전", "합법"):
        assert banned not in msg


# ── 입력 검증 ──────────────────────────────────────────────────────
@pytest.mark.parametrize("over", [
    {"matched_items": []},                      # 뭐가 틀렸는지 없으면 검수할 수 없다
    {"page_text": ""},
    {"page_text": "x" * 200_001},               # 스캔과 같은 상한
    {"note": "y" * 501},
    {"matched_items": ["a"] * 11},
])
def test_bad_input_is_rejected(client, over):
    assert _report(client, **over).status_code == 422


# ── 레이트리밋 — 스캔과 다른 버킷 ─────────────────────────────────
def test_reports_are_limited_separately_from_scans(client, monkeypatch):
    monkeypatch.setattr(m, "_report_limiter", RateLimiter(per_minute=1))
    assert _report(client).status_code == 201
    blocked = _report(client)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    # 신고 한도가 찼어도 스캔은 된다 - 버킷이 다르다.
    assert client.post("/api/v1/scan", json={"page_text": _TEXT}).status_code == 200


# ── 같은 볼륨 · /healthz ───────────────────────────────────────────
def test_the_table_lives_in_the_watchlist_db(store):
    names = {r[0] for r in store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"miss_reports", "watch_items", "recalls"} <= names, names


def test_healthz_shows_the_review_queue_length(client):
    h0 = client.get("/healthz").json()["miss_reports"]
    assert h0 == {"total": 0, "last_reported_at": None}
    _report(client); _report(client)
    h1 = client.get("/healthz").json()["miss_reports"]
    assert h1["total"] == 2 and h1["last_reported_at"]


# ── 내보내기 — 오답표와 같은 4열 ──────────────────────────────────
def test_export_matches_the_audit_tsv_shape(client, store, tmp_path):
    sys.path.insert(0, str(_ROOT / "scripts"))
    from export_miss_reports import rows_for

    _report(client, page_text="첫 줄 상품명\t탭 포함\n둘째 줄", matched_items=["완구", "블록"],
            note="탭\t과\n줄바꿈")
    _report(client, page_text="나비 NV92 무선 전동 클리너", matched_items=["진공청소기"])

    lines = rows_for(store)
    data = [ln for ln in lines if ln and not ln.startswith("#")]
    assert len(data) == 2
    for ln in data:
        cols = ln.split("\t")
        assert len(cols) == 4, cols
        assert cols[2] == "", "유형 칸은 비어 있어야 한다 - 사람이 채운다 (R1)"
        assert "\n" not in ln
    first = data[0].split("\t")
    assert first[0] == "첫 줄 상품명 탭 포함"           # 첫 줄만 · 탭은 공백
    assert first[1] == "완구;블록"
    assert first[3] == "탭 과 줄바꿈"
    # 출처 주석이 데이터 행 바로 앞에 있다.
    idx = lines.index(data[0])
    assert lines[idx - 1].startswith("# id=") and "path=llm" in lines[idx - 1]

    # 오답표와 같은 로더 규약(# 주석 무시 · 탭 4열)으로 읽힌다.
    audit = (_ROOT / "tests/fixtures/새표본235_오답.tsv").read_text(encoding="utf-8")
    audit_cols = {len(ln.split("\t")) for ln in audit.splitlines() if ln and not ln.startswith("#")}
    assert audit_cols == {4}, "오답표 형식이 바뀌었다 - 내보내기도 맞출 것"


# ── ②-b 멱등: 두 번 눌러도 검수 대기열은 한 줄 ────────────────────
#
# ⚠ 검수 대기열이다. 같은 줄이 두 개면 사람이 두 번 읽고, `/healthz` 의
#   `miss_reports.total` 이 실제 신고 수보다 크게 떠서 "쌓였다" 를 잘못 읽는다.


def test_pressing_twice_stores_one_row(client):
    """같은 (소유자 · 입력 텍스트 · 품목) 두 번째는 200 + 기존 id."""
    first = _report(client, owner_id="own-A")
    second = _report(client, owner_id="own-A")
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["reported_at"] == second.json()["reported_at"]
    assert client.get("/healthz").json()["miss_reports"]["total"] == 1


@pytest.mark.parametrize("over", [
    {"matched_items": ["커피메이커"]},      # 품목이 다르면 다른 신고
    {"page_text": _TEXT + " 재질 ABS"},     # 입력이 다르면 다른 신고
    {"owner_id": "own-B"},                  # 셀러가 다르면 다른 신고
])
def test_a_different_key_is_a_different_report(client, over):
    assert _report(client, owner_id="own-A").status_code == 201
    assert _report(client, **{"owner_id": "own-A", **over}).status_code == 201
    assert client.get("/healthz").json()["miss_reports"]["total"] == 2


def test_item_order_does_not_split_the_key(client):
    """후보 순서가 키를 가르면 같은 신고가 두 줄이 된다."""
    assert _report(client, owner_id="own-A",
                   matched_items=["완구", "블록완구"]).status_code == 201
    assert _report(client, owner_id="own-A",
                   matched_items=["블록완구", "완구"]).status_code == 200
    assert client.get("/healthz").json()["miss_reports"]["total"] == 1


def test_without_an_owner_nothing_is_deduplicated(client):
    """옛 화면(소유자를 안 보내는)도 그대로 저장된다 - 막지 않는다."""
    assert _report(client).status_code == 201
    assert _report(client).status_code == 201
    assert client.get("/healthz").json()["miss_reports"]["total"] == 2


def test_the_key_is_a_hash_not_the_page_text(client, store):
    """20만 자 원문을 색인에 통째로 넣지 않는다."""
    _report(client, owner_id="own-A")
    key = store._conn.execute(
        "SELECT dedupe_key FROM miss_reports"
    ).fetchone()["dedupe_key"]
    assert key and len(key) == 64 and _TEXT not in key


def test_an_old_database_gains_the_column_without_being_quarantined(tmp_path):
    """배포본 DB 에는 `dedupe_key` 가 없다. 열다가 격리되면 안 된다.

    ⚠ **열 추가가 스키마보다 먼저다.** 유니크 색인이 없는 열을 가리키면 그
      자리에서 `no such column` 으로 던지고(실측), 그 예외는 `__init__` 에서
      **DB 손상으로 읽혀 격리**된다 - 워치 항목이 통째로 사라진다.
    """
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE miss_reports (id TEXT PRIMARY KEY, reported_at TEXT NOT NULL,"
        " payload TEXT NOT NULL);"
    )
    conn.execute("INSERT INTO miss_reports VALUES ('old1','2026-09-10T00:00:00+00:00','{}')")
    conn.execute("INSERT INTO miss_reports VALUES ('old2','2026-09-11T00:00:00+00:00','{}')")
    conn.commit()
    conn.close()

    s = SqliteWatchStore(str(db))
    assert s.quarantined_from is None, "옛 DB 를 손상으로 읽고 격리했다"
    # 옛 신고는 그대로다. NULL 은 유니크 색인에서 서로 다른 값이라 둘 다 남는다.
    assert len(s.miss_reports()) == 2
    assert "dedupe_key" in {
        r[1] for r in s._conn.execute("PRAGMA table_info(miss_reports)")
    }
    assert s.save_miss_report("n1", "2026-09-14T00:00:00+00:00", "{}",
                              dedupe_key="k1")[2] is True
    assert s.save_miss_report("n2", "2026-09-14T00:00:01+00:00", "{}",
                              dedupe_key="k1") == ("n1", "2026-09-14T00:00:00+00:00", False)
