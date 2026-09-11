"""[4-p] 정부 API 장애를 **관측**한다. 재시도·캐시는 넣지 않는다.

왜
--
2026-09-11 에 safetykorea.kr 가 죽었다 - `curl` 3회 전부 `Connection reset by
peer` / `timeout`. 설계대로 `lookup_failed` 로 떨어지는 것은 맞지만(R3)
**우리도 셀러도 그 사실을 화면에서 알 수 없었다.**

09-08 과 같은 구조다. Claude 크레딧이 바닥나 배포본이 매 스캔마다 휴리스틱으로
떨어졌는데 응답도 화면도 그 사실을 말하지 않아 휴리스틱 결과를 "실물 확인" 으로
보고했다. 투표 18일(9/21~10/5) 동안 정부 API 가 죽으면 같은 일이 난다.

⚠⚠ **"조회했더니 없다" 와 "조회를 못 했다" 는 다르다.** 실증:

    키 있음   kc_verified 22 · expired 6 · revoked 2 · not_found 2  = 32
    키 없음   kc_not_found 32                                        = 32

**합이 같고 그림이 정반대다.** 후자만 보면 "조회했더니 32건이 없더라" 로
읽히는데 실제로는 조회 자체를 못 한 것이다.

⚠ 재시도·캐시를 넣지 않는다. 남의 API 장애로 우리를 죽이지 않는 설계는
  그대로다. 추가하는 것은 관측뿐이다.
"""
from __future__ import annotations

import inspect
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from sourcing_guard.kats_client import KatsClient, KatsHealth
from sourcing_guard.models import Finding, FindingKind, Signal
from sourcing_guard.rra_client import RraClient
from sourcing_guard.scorer import gov_lookup_state


def _f(kind: FindingKind, **detail) -> Finding:
    return Finding(
        kind=kind, signal=Signal.UNKNOWN, statement_ko="어떤 사실",
        source_label="근거", source_url="https://www.safetykorea.kr/",
        checked_at=date(2026, 9, 11), detail=detail,
    )


# ── KatsHealth ─────────────────────────────────────────────────────
def test_failure_rate_is_none_when_nothing_was_called():
    """⚠ 호출 0 에서 0.0 을 주면 **"전부 성공" 으로 읽힌다.**

    실제로는 한 번도 부르지 않은 것이다(목 모드거나 조회할 번호가 없었음).
    """
    h = KatsHealth()
    snap = h.snapshot()
    assert snap["failure_rate"] is None
    assert snap["calls"] == 0 and snap["failures"] == 0
    assert snap["last_success_at"] is None
    # note 가 그 사실을 말해야 한다 - 숫자만 보면 오독한다.
    assert "한 번도" in snap["note"]


def test_failure_rate_and_last_success_move():
    """전에는 `consecutive_failures` 만 셌다.

    ⚠ 한 번씩 실패하고 회복하는 상태는 연속 실패가 0 이라 **정상으로 보인다.**
      실패율이 그것을 드러낸다.
    """
    h = KatsHealth()
    h.record_failure("network", "ReadError")
    h.record_failure("network", "Timeout")
    h.record_success()
    snap = h.snapshot()

    assert snap["calls"] == 3 and snap["failures"] == 2
    assert snap["failure_rate"] == pytest.approx(0.667, abs=0.001)
    assert snap["last_success_at"] is not None
    # 연속 실패는 0 으로 회복했지만 실패율은 남는다 - 이것이 추가한 이유다.
    assert snap["consecutive_failures"] == 0


def test_the_snapshot_says_it_is_process_memory():
    """재배포하면 0 이 된다는 사실이 값과 함께 있어야 한다."""
    assert "프로세스 메모리" in KatsHealth().snapshot()["note"]


_TRANSPORT_ERRORS = [
    httpx.ReadError,        # 2026-09-11 에 실제로 난 것
    httpx.ConnectTimeout,   # 그 직전 전체 수트를 깨뜨린 것
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
]


@pytest.mark.parametrize("exc_cls", _TRANSPORT_ERRORS,
                         ids=[e.__name__ for e in _TRANSPORT_ERRORS])
def test_transport_errors_become_KatsApiError_not_raw_httpx(exc_cls):
    """⚠⚠ **전송 단계 오류가 `KatsApiError` 로 변환되어야 한다.**

    전에는 `self._client.get(...)` 이 `try` **밖**에 있어서 연결 단계 오류가
    httpx 예외 그대로 밖으로 나갔다. 결과가 둘이었다:

        (1) `health.record_failure` 가 안 불려 **관측이 안 된다**
        (2) `verifier` 가 `KatsApiError` 만 잡으므로 `lookup_failed` 경로를
            타지 않고 **스캔이 500 이 된다**

    2026-09-11 에 safetykorea.kr 가 `Connection reset by peer` 를 냈다. 그 순간
    배포본의 **모든 스캔이 500** 이었을 것이다.
    """
    from sourcing_guard import kats_client as kc
    from sourcing_guard.kats_client import KatsApiError

    h = KatsHealth()
    original = kc.health
    kc.health = h
    try:
        def boom(request):
            raise exc_cls("boom")

        client = KatsClient(None, "KEY123", mock=False)
        client._client = httpx.Client(transport=httpx.MockTransport(boom))
        with pytest.raises(KatsApiError) as got:
            client.lookup_certification("CB061R2170-3018")
    finally:
        kc.health = original

    assert got.value.code == "network"
    # 관측이 됐는가 - 이것이 (1) 이다.
    assert h.failures == 1, h.snapshot()
    assert h.snapshot()["failure_rate"] == 1.0
    assert h.last_error_code == "network"


@pytest.mark.parametrize("exc_cls", _TRANSPORT_ERRORS,
                         ids=[e.__name__ for e in _TRANSPORT_ERRORS])
def test_the_scan_survives_a_government_outage(exc_cls):
    """⚠⚠ **정부 API 가 죽어도 스캔은 200 이어야 한다.** 이것이 (2) 다.

    남의 API 장애로 우리를 죽이지 않는 설계가 실제로 지켜지는지 **상태코드로**
    확인한다. 이전에는 500 이었다 - 재현해서 확인했다.
    """
    import logging

    import sourcing_guard.main as m

    def boom(request):
        raise exc_cls("boom")

    k = KatsClient(None, "KEY123", mock=False)
    k._client = httpx.Client(transport=httpx.MockTransport(boom))
    saved_kats, saved_rra = m._kats, m._rra
    m._kats, m._rra = k, RraClient(mock=True)
    logging.disable(logging.CRITICAL)
    try:
        with TestClient(m.app, raise_server_exceptions=False) as c:
            r = c.post("/api/v1/scan", json={
                "page_text": "유아용 블록 완구 대상연령 3세 KC 인증번호 CB061R2170-3018",
            })
    finally:
        logging.disable(logging.NOTSET)
        m._kats, m._rra = saved_kats, saved_rra

    assert r.status_code == 200, r.text[:200]
    # 그리고 **조회를 못 했다는 사실**이 응답에 있어야 한다.
    assert r.json()["meta"]["gov_lookup"]["cert"] == "failed"


def test_the_transport_call_is_inside_the_try_block():
    """소스로도 잠근다 - 다음 리팩터가 `get` 을 밖으로 빼면 여기서 깨진다."""
    src = inspect.getsource(KatsClient._call)
    body = src[src.index("try:"):]
    assert "self._client.get(" in body, (
        "전송이 try 밖으로 나갔다 - 전송 오류가 KatsApiError 로 변환되지 않고 "
        "스캔이 500 이 된다"
    )


# ── gov_lookup_state — 순수 함수 ───────────────────────────────────
@pytest.mark.parametrize("findings,expected", [
    ([], {"cert": "not_attempted", "recall": "not_attempted", "rf": "not_attempted"}),
    ([_f(FindingKind.KC_VERIFIED)],
     {"cert": "ok", "recall": "not_attempted", "rf": "not_attempted"}),
    # ⚠ "조회했더니 없다" 는 **ok** 다. 조회는 성공했다.
    ([_f(FindingKind.KC_NOT_FOUND)],
     {"cert": "ok", "recall": "not_attempted", "rf": "not_attempted"}),
    # ⚠ "조회를 못 했다" 는 failed 다. 위와 갈려야 한다.
    ([_f(FindingKind.LOOKUP_FAILED, scope="인증")],
     {"cert": "failed", "recall": "not_attempted", "rf": "not_attempted"}),
    ([_f(FindingKind.RECALL_CLEAR)],
     {"cert": "not_attempted", "recall": "ok", "rf": "not_attempted"}),
    ([_f(FindingKind.LOOKUP_FAILED, scope="리콜")],
     {"cert": "not_attempted", "recall": "failed", "rf": "not_attempted"}),
    ([_f(FindingKind.RF_CERT_VERIFIED)],
     {"cert": "not_attempted", "recall": "not_attempted", "rf": "ok"}),
    # ⚠ scope 는 "전파" 가 아니라 **"전파인증"** 이다. 처음에 틀렸다.
    ([_f(FindingKind.LOOKUP_FAILED, scope="전파인증")],
     {"cert": "not_attempted", "recall": "not_attempted", "rf": "failed"}),
])
def test_the_three_states_are_distinguished(findings, expected):
    assert gov_lookup_state(findings) == expected


def test_not_found_and_failed_are_never_the_same():
    """⚠⚠ 이 둘을 섞으면 **장애 중에 "인증이 없는 상품" 이 무더기로 만들어진다.**"""
    not_found = gov_lookup_state([_f(FindingKind.KC_NOT_FOUND)])
    failed = gov_lookup_state([_f(FindingKind.LOOKUP_FAILED, scope="인증")])
    assert not_found["cert"] != failed["cert"]
    assert not_found["cert"] == "ok" and failed["cert"] == "failed"


def test_it_is_a_pure_function():
    """`scorer` 는 순수 함수다 - I/O·시각·난수 없음 (CLAUDE.md §6)."""
    src = inspect.getsource(gov_lookup_state)
    for banned in ("httpx", "requests", "open(", "datetime.now", "random",
                   "_store", "settings"):
        assert banned not in src, f"순수성이 깨졌다: {banned}"


# ── 배선 ───────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    import sourcing_guard.main as m

    monkeypatch.setattr(m, "_kats", KatsClient(None, None, mock=True))
    monkeypatch.setattr(m, "_rra", RraClient(mock=True))
    with TestClient(m.app) as c:
        yield c


def test_the_scan_response_says_whether_the_lookup_happened(client):
    """`/healthz` 의 `kats` 는 프로세스 누적값이라 "이 결과" 를 말하지 못한다."""
    body = client.post("/api/v1/scan", json={
        "page_text": "유아용 블록 완구 장난감 대상연령 3세 KC 인증번호 CB061R2170-3018",
    }).json()
    gov = body["meta"]["gov_lookup"]
    assert set(gov) == {"cert", "recall", "rf"}
    assert gov["cert"] == "ok", gov
    # 값은 셋 중 하나여야 한다 - 화면이 그 셋만 다룬다.
    assert set(gov.values()) <= {"ok", "failed", "not_attempted"}


def test_a_page_with_no_number_reports_not_attempted(client):
    """조회할 번호가 없으면 `not_attempted` 다 - 실패가 아니다."""
    body = client.post("/api/v1/scan",
                       json={"page_text": "https://example.com/goods/1"}).json()
    assert body["meta"]["gov_lookup"]["cert"] == "not_attempted"


def test_healthz_exposes_the_failure_rate_and_last_success(client):
    kats = client.get("/healthz").json()["kats"]
    for key in ("failure_rate", "calls", "failures", "last_success_at",
                "consecutive_failures", "last_error_code", "note"):
        assert key in kats, key


# ── 하지 않은 것 ───────────────────────────────────────────────────
def test_no_retry_and_no_cache_were_added():
    """⚠ 남의 API 장애로 우리를 죽이지 않는 설계는 그대로다.

    추가한 것은 **관측**뿐이다. 재시도를 넣으면 장애 중에 응답이 느려지고,
    셀러는 우리가 느린 것으로 읽는다.

    ⚠ 인증 조회 캐시(`CERT_CACHE_TTL_SECONDS`)는 **전부터 있던 것**이고 4-p 가
      넣은 것이 아니다 - 같은 번호를 반복 조회하지 않기 위한 것이며 장애
      대응이 아니다.
    """
    src = inspect.getsource(KatsHealth)
    for banned in ("retry", "backoff", "sleep", "cache"):
        assert banned not in src.lower(), f"KatsHealth 에 {banned} 가 들어왔다"


def test_the_scope_labels_match_the_verifier():
    """⚠⚠ `scope` 문자열이 어긋나면 **실패가 not_attempted 로 잘못 보인다.**

    실제로 틀렸다 - 처음에 `"전파"` 로 적었는데 `verifier` 는 `"전파인증"` 을
    쓴다. 그러면 RF 조회 실패가 "조회 안 함" 으로 보고되고, 장애가 숨는다.

    ⚠ verifier 소스에서 실제 값을 읽어 대조한다. 문자열을 양쪽에 손으로 적으면
      같은 실수가 반복된다.
    """
    import re

    from sourcing_guard import verifier

    src = inspect.getsource(verifier)
    used = set(re.findall(r'_lookup_failed\("([^"]+)"', src))
    assert used == {"인증", "리콜", "전파인증"}, used

    checked = set(re.findall(r'if "([^"]+)" in failed_scopes', inspect.getsource(gov_lookup_state)))
    assert checked == used, (
        f"gov_lookup_state 가 보는 scope 와 verifier 가 쓰는 scope 가 다릅니다.\n"
        f"  verifier: {sorted(used)}\n  scorer  : {sorted(checked)}"
    )
