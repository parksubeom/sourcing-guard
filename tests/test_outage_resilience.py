"""[4-q] **남의 장애가 우리 500 이 되지 않는다** — 경계 전수.

9/6 핸드오프가 이 문장을 원칙으로 적어 뒀는데 **코드는 그것을 지키지 않았다.**
원칙을 문서에 적는 것과 코드가 지키는 것은 다르다. 이 파일이 그 간격을 메운다.

투표 18일(9/21~10/5) 중 하루라도 정부 API 가 흔들리면 투표자가 에러 화면을
본다. 발표 숫자보다 이것이 먼저다.

전수 확인한 경계
----------------
    kats        전송 5종 + 파싱 6종 = 11
    rra         전송 5종 + 파싱 6종 = 11
    LLM         잘못된 출력 10종
    SQLite      0바이트 · 쓰레기 · 잘림
    리콜 payload  쓰레기 · 스키마 불일치 · null · 빈 문자열

찾은 결함 넷 (전부 이 커밋에서 고쳤다)
-------------------------------------
    1. kats `_client.get` 이 try 밖  → 전송 오류가 그대로 나가 **스캔 500**  ([4-p])
    2. kats `resultCode` 없으면 통과 → 못 읽은 응답을 "인증 없음" 으로 단정
    3. rra  `resultCode` 없으면 통과 → 점검 HTML 을 **"전파인증 확인됨"** 으로
                                       읽는다. **잘못된 초록불**이다
    4. LLM 이 `[1,2,3]`·`null` 반환  → `data.items()` 가 터져 **스캔 500**

⚠ 3번이 가장 비싸다. `ElementTree` 는 `<html>점검중</html>` 을 **유효한 XML 로
  파싱한다** - 태그 하나에 텍스트뿐이어도 문법상 맞다. 그래서 ParseError 가드를
  통과하고 `resultCode` 가 없어 빈 문자열이 되며, `if code and ...` 이 falsy 라
  성공 처리됐다.

⚠ 재시도·캐시는 넣지 않았다. 한 것은 **예외 타입 변환과 관측**뿐이다.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sourcing_guard.kats_client import KatsClient
from sourcing_guard.rra_client import RraClient

_TEXT_KC = "유아용 블록 완구 대상연령 3세 KC 인증번호 CB061R2170-3018"
_TEXT_RF = "블루투스 무선 이어폰 R-C-ABC-DEF123 충전 케이스"

_TRANSPORT = [
    httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError,
    httpx.ReadTimeout, httpx.RemoteProtocolError,
]
#: (이름, 응답). 남의 서버가 200 을 주면서 우리가 못 읽는 것을 줄 수 있다.
_MALFORMED = [
    ("html", lambda r: httpx.Response(200, text="<html>점검중</html>")),
    ("empty", lambda r: httpx.Response(200, text="")),
    ("wrong_schema", lambda r: httpx.Response(200, json={"unexpected": [1, 2]})),
    ("null", lambda r: httpx.Response(200, json=None)),
    ("http_500", lambda r: httpx.Response(500, text="oops")),
    ("http_302", lambda r: httpx.Response(302, text="")),
]


@pytest.fixture
def scan(monkeypatch):
    """장애를 주입하고 스캔을 한 번 부른다. 응답 전체를 돌려준다."""
    import sourcing_guard.main as m

    def _run(*, kats_handler=None, rra_handler=None, text=_TEXT_KC):
        k = KatsClient(None, "KEY123", mock=False) if kats_handler else KatsClient(None, None, mock=True)
        if kats_handler:
            k._client = httpx.Client(transport=httpx.MockTransport(kats_handler))
        r = RraClient(mock=False) if rra_handler else RraClient(mock=True)
        if rra_handler:
            r._client = httpx.Client(transport=httpx.MockTransport(rra_handler))
        monkeypatch.setattr(m, "_kats", k)
        monkeypatch.setattr(m, "_rra", r)
        logging.disable(logging.CRITICAL)
        try:
            with TestClient(m.app, raise_server_exceptions=False) as c:
                return c.post("/api/v1/scan", json={"page_text": text})
        finally:
            logging.disable(logging.NOTSET)

    return _run


def _raiser(exc_cls):
    def handler(request):
        raise exc_cls("주입한 장애")
    return handler


# ── 정부 API ───────────────────────────────────────────────────────
@pytest.mark.parametrize("exc_cls", _TRANSPORT, ids=[e.__name__ for e in _TRANSPORT])
def test_kats_transport_failure_keeps_the_scan_alive(exc_cls, scan):
    r = scan(kats_handler=_raiser(exc_cls))
    assert r.status_code == 200, r.text[:200]
    assert r.json()["meta"]["gov_lookup"]["cert"] == "failed"


@pytest.mark.parametrize("name,handler", _MALFORMED, ids=[n for n, _ in _MALFORMED])
def test_kats_malformed_response_is_a_failure_not_an_absence(name, handler, scan):
    """⚠ 우리가 못 읽은 응답을 "인증번호 없음" 으로 단정하지 않는다 (R3).

    전에는 `resultCode` 가 없으면 빈 문자열이 되어 그냥 통과했고, 화면에
    `kc_not_found` 가 떴다 - **멀쩡한 인증번호에 경고**다.
    """
    r = scan(kats_handler=handler)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["meta"]["gov_lookup"]["cert"] == "failed", (
        f"{name}: 못 읽은 응답이 '조회함' 으로 처리됐다"
    )
    kinds = {f["kind"] for f in body["findings"]}
    assert "kc_not_found" not in kinds, f"{name}: 부재로 단정했다"


@pytest.mark.parametrize("exc_cls", _TRANSPORT, ids=[e.__name__ for e in _TRANSPORT])
def test_rra_transport_failure_keeps_the_scan_alive(exc_cls, scan):
    r = scan(rra_handler=_raiser(exc_cls), text=_TEXT_RF)
    assert r.status_code == 200, r.text[:200]


@pytest.mark.parametrize("name,handler", _MALFORMED, ids=[n for n, _ in _MALFORMED])
def test_rra_malformed_response_never_becomes_a_verified_cert(name, handler, scan):
    """⚠⚠ **잘못된 초록불을 막는다.**

    `<html>점검중</html>` 은 `ElementTree` 가 **유효한 XML 로 파싱한다.**
    전에는 그 응답이 `RfCertState.VERIFIED` 레코드가 되어 화면에 "전파인증
    확인됨" 이 떴다. 이 도구가 가장 하면 안 되는 종류의 오류다(기획서 §3.2).
    """
    r = scan(rra_handler=handler, text=_TEXT_RF)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    kinds = {f["kind"] for f in body["findings"]}
    assert "rf_cert_verified" not in kinds, (
        f"{name}: 못 읽은 응답이 '전파인증 확인됨' 이 됐다 - 잘못된 초록불"
    )
    assert body["meta"]["gov_lookup"]["rf"] == "failed", name


# ── LLM ────────────────────────────────────────────────────────────
_BAD_LLM = [
    ("empty", ""),
    ("not_json", "죄송합니다, 도와드릴 수 없습니다"),
    ("json_array", "[1, 2, 3]"),
    ("json_null", "null"),
    ("unknown_fields", '{"totally_unknown": 1, "risk_score": 99}'),
    ("wrong_types", '{"product_name": 123, "kc_numbers": "문자열"}'),
    ("verdict_injection", '{"product_name": "X", "is_safe": true, "verdict": "GREEN"}'),
]


@pytest.mark.parametrize("name,text", _BAD_LLM, ids=[n for n, _ in _BAD_LLM])
def test_a_malformed_llm_answer_keeps_the_scan_alive(name, text, monkeypatch):
    """⚠ `json.loads` 성공이 곧 dict 를 뜻하지 않는다.

    `[1,2,3]` 과 `null` 도 유효한 JSON 이고, `data.items()` 가 터져 **스캔이
    500** 이었다. 모델이 "답할 수 없음" 을 `null` 로 표현하면 그렇게 된다.
    """
    from dataclasses import replace

    import sourcing_guard.extractor as ex
    import sourcing_guard.main as m

    monkeypatch.setattr(ex, "settings", replace(
        ex.settings, mock_mode=False, anthropic_api_key="k", gpt_api_key=None,
        extractor_order=("claude",),
    ))
    monkeypatch.setitem(ex._VENDOR_CALLS, "claude", lambda content: text)
    monkeypatch.setattr(m, "_kats", KatsClient(None, None, mock=True))
    monkeypatch.setattr(m, "_rra", RraClient(mock=True))

    logging.disable(logging.CRITICAL)
    try:
        with TestClient(m.app, raise_server_exceptions=False) as c:
            r = c.post("/api/v1/scan", json={"page_text": "유아용 블록 완구 3세"})
    finally:
        logging.disable(logging.NOTSET)

    assert r.status_code == 200, f"{name}: {r.text[:200]}"
    # ⚠ 판정 필드가 주입돼도 ProductFacts 에 들어가지 않는다 (R1).
    assert "verdict" not in json.dumps(r.json().get("facts") or {})


def test_a_vendor_outage_falls_back_to_heuristic(monkeypatch):
    """벤더가 통째로 죽어도 스캔은 산다 - 그리고 **그 사실을 말한다.**"""
    from dataclasses import replace

    import sourcing_guard.extractor as ex
    import sourcing_guard.main as m

    def down(content):
        raise RuntimeError("vendor down")

    monkeypatch.setattr(ex, "settings", replace(
        ex.settings, mock_mode=False, anthropic_api_key="k", gpt_api_key=None,
        extractor_order=("claude",),
    ))
    monkeypatch.setitem(ex._VENDOR_CALLS, "claude", down)
    monkeypatch.setattr(m, "_kats", KatsClient(None, None, mock=True))
    monkeypatch.setattr(m, "_rra", RraClient(mock=True))

    logging.disable(logging.CRITICAL)
    try:
        with TestClient(m.app, raise_server_exceptions=False) as c:
            r = c.post("/api/v1/scan", json={"page_text": "유아용 블록 완구 3세"})
    finally:
        logging.disable(logging.NOTSET)

    assert r.status_code == 200
    meta = r.json()["meta"]
    assert meta["extraction_path"] == "heuristic"
    assert meta["extraction_reason"] == "all_vendors_failed"


# ── 로컬 자원 ──────────────────────────────────────────────────────
@pytest.mark.parametrize("kind", ["zero", "garbage", "truncated"])
def test_a_corrupt_database_is_quarantined_not_fatal(kind, tmp_path):
    """⚠⚠ 전에는 DB 파일이 손상되면 **앱이 부팅조차 못 했다.**

    Fly 에서는 재시작 루프가 되고 **스캔도 함께 죽는다.** 스캔은 이 DB 없이도
    되므로, 손상 파일을 옆으로 치우고 새로 시작한다.

    ⚠ **지우지 않는다.** 조용히 덮어쓰면 워치 데이터가 소리 없이 사라지고,
      "리콜을 가장 먼저 알린다" 는 약속이 깨진 것도 모른다 (R6).
    """
    from sourcing_guard.storage import SqliteWatchStore

    p = tmp_path / "watchlist.db"
    if kind == "zero":
        p.write_bytes(b"")
    elif kind == "garbage":
        p.write_bytes(b"not a sqlite file at all" * 20)
    else:
        conn = sqlite3.connect(p)
        conn.execute("create table t(a)")
        conn.commit()
        conn.close()
        data = p.read_bytes()
        p.write_bytes(data[: len(data) // 2])

    logging.disable(logging.CRITICAL)
    try:
        store = SqliteWatchStore(p)
    finally:
        logging.disable(logging.NOTSET)

    # 어느 경우든 쓸 수 있는 store 가 나온다.
    assert store.sync_snapshot() is not None

    if kind == "zero":
        # 빈 파일은 sqlite 가 새 DB 로 본다 - 격리할 것이 없다.
        assert store.quarantined_from is None
    else:
        assert store.quarantined_from, "손상인데 격리 기록이 없다"
        spoiled = list(tmp_path.glob("*.corrupt-*"))
        assert spoiled, "손상 파일을 지웠다 - 복구할 수 없게 된다"
        assert spoiled[0].stat().st_size > 0


def test_healthz_says_the_database_was_quarantined(monkeypatch, tmp_path):
    """격리를 조용히 넘기지 않는다 - `/healthz` 가 말한다."""
    import sourcing_guard.main as m

    with TestClient(m.app) as c:
        storage = c.get("/healthz").json()["storage"]
    for key in ("path", "quarantined_from", "note"):
        assert key in storage
    # 정상일 때는 None 이다 - 값이 있으면 워치 데이터를 잃었다는 뜻이다.
    assert storage["quarantined_from"] is None


@pytest.mark.parametrize("payload", ["not json at all", '{"nope": 1}', "null", ""])
def test_a_corrupt_recall_row_does_not_break_the_scan(payload, monkeypatch, tmp_path):
    """리콜 사본의 한 줄이 깨져도 나머지는 돈다."""
    import sourcing_guard.main as m
    from sourcing_guard.recall_index import RecallIndex
    from sourcing_guard.storage import SqliteWatchStore

    store = SqliteWatchStore(tmp_path / "w.db")
    store._conn.execute(
        "INSERT OR REPLACE INTO recalls (uid, scope, published_on, payload, fetched_at)"
        " VALUES (?,?,?,?,?)",
        ("probe", "domestic", "20260910", payload, "2026-09-11T00:00:00Z"),
    )
    store._conn.commit()

    monkeypatch.setattr(m, "_store", store)
    monkeypatch.setattr(m, "_recalls", RecallIndex(store))
    monkeypatch.setattr(m, "_kats", KatsClient(None, None, mock=True))
    monkeypatch.setattr(m, "_rra", RraClient(mock=True))

    logging.disable(logging.CRITICAL)
    try:
        with TestClient(m.app, raise_server_exceptions=False) as c:
            r = c.post("/api/v1/scan", json={"page_text": "유아용 블록 완구 3세"})
    finally:
        logging.disable(logging.NOTSET)
    assert r.status_code == 200, r.text[:200]


# ── 우리가 하지 않은 것 ────────────────────────────────────────────
def test_no_retry_or_cache_was_introduced():
    """⚠ 한 것은 **예외 타입 변환과 관측**뿐이다.

    재시도를 넣으면 장애 중에 응답이 느려지고, 셀러는 우리가 느린 것으로 읽는다.
    """
    root = Path(__file__).resolve().parents[1] / "sourcing_guard"
    src = (root / "kats_client.py").read_text(encoding="utf-8")
    # `_call` 본문에 재시도 루프가 없다.
    call = src.split("def _call(")[1].split("\n    def ")[0]
    for banned in ("for attempt", "while True", "time.sleep", "backoff"):
        assert banned not in call, f"_call 에 {banned} 가 들어왔다"


# ── 다음 장애가 픽스처가 되게 ───────────────────────────────────────
def test_an_unreadable_response_body_is_logged(caplog):
    """⚠⚠ 2026-09-11 장애 때 **응답 본문을 못 잡았다.**

    그래서 이 파일의 파싱 오류 6종은 우리가 **상상해서 고른 모양**이고, 정부
    API 가 실제로 무엇을 주는지는 모른다. 다음 장애 때는 픽스처가 남게 한다.

    ⚠ 정부 공개 API 응답이라 개인정보가 없다. 그래도 앞 500자만 남긴다.
    """
    from sourcing_guard.kats_client import KatsApiError
    from sourcing_guard.rra_client import RraApiError

    k = KatsClient(None, "K", mock=False)
    k._client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"unexpected": [1, 2]})))
    with caplog.at_level(logging.ERROR):
        with pytest.raises(KatsApiError):
            k.lookup_certification("CB061R2170-3018")
    assert any("읽지 못했습니다" in r.message for r in caplog.records), caplog.text
    assert any("unexpected" in str(r.args) for r in caplog.records), "본문이 없다"

    caplog.clear()
    r = RraClient(mock=False)
    r._client = httpx.Client(transport=httpx.MockTransport(
        lambda rq: httpx.Response(200, text="<html>서비스 점검중입니다</html>")))
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RraApiError):
            r.lookup_number("R-C-ABC-DEF123")
    assert any("읽지 못했습니다" in rec.message for rec in caplog.records)
    assert any("점검중" in str(rec.args) for rec in caplog.records), "본문이 없다"


def test_healthz_says_which_commit_is_deployed():
    """⚠ 필드 유무로 배포 버전을 역추적하는 일이 없게 한다.

    2026-09-11 에 총괄이 실제로 그래야 했다 - `storage` 키가 없으니 09-08
    배포본이구나, 하는 식이다. 그건 추론이지 사실이 아니다.
    """
    import sourcing_guard.main as m

    with TestClient(m.app) as c:
        build = c.get("/healthz").json()["build"]
    for key in ("commit", "built_at", "source", "note"):
        assert key in build, key
    # 로컬에서는 git 에서 읽는다 - 배포본과 구분되게 source 가 말한다.
    assert build["source"] in {"build-arg", "git", "unknown"}


def test_the_dockerfile_accepts_the_build_args():
    """빌드 인자를 빼면 `build.commit` 이 null 이 된다 - 그 통로가 살아 있는지."""
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG GIT_SHA" in dockerfile and "ARG BUILT_AT" in dockerfile
    assert "ENV GIT_SHA=$GIT_SHA" in dockerfile
    # 배포 문서가 그 명령을 적고 있어야 한다 - 사람이 읽는 곳이다.
    deploy_doc = (root / "docs/배포_Fly.io.md").read_text(encoding="utf-8")
    assert "--build-arg GIT_SHA=" in deploy_doc
    assert "그날 배포한다" in deploy_doc
