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
from sourcing_guard.scorer import GOV_LOOKUP_STATES, gov_lookup_state


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
    h.record_failure("network", "ReadError", path="user_cert")
    h.record_failure("network", "Timeout", path="user_cert")
    h.record_success("user_cert")
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

    # ⚠ 2026-09-20 에 `network` 이 셋으로 갈렸다(P1) - `network.connect` ·
    #   `network.read` · `network`. **이 검사가 가진 것은 "전송 오류가
    #   KatsApiError 로 변환되고 관측되는가" 이지 코드 문자열이 아니다.**
    #   갈래의 소유자는 `test_kats_timeout.test_the_failure_code_says_which_kind_it_was`
    #   다 - 여기에 다시 적으면 한쪽만 고쳐질 때 나머지가 낡는다 (§6).
    assert got.value.code.startswith("network"), got.value.code
    # 관측이 됐는가 - 이것이 (1) 이다.
    assert h.failures == 1, h.snapshot()
    assert h.snapshot()["failure_rate"] == 1.0
    assert h.last_error_code == got.value.code
    # ⚠ 반대 방향 - `OPERATOR_FAULT_CODES` 에 들어가면 안 된다. 남의 장애를
    #   우리 설정 잘못으로 세면 `/healthz` 가 거짓말을 한다.
    from sourcing_guard.kats_client import OPERATOR_FAULT_CODES

    assert got.value.code not in OPERATOR_FAULT_CODES
    assert not h.operator_fault() if hasattr(h, "operator_fault") else True


@pytest.mark.parametrize("exc_cls", _TRANSPORT_ERRORS,
                         ids=[e.__name__ for e in _TRANSPORT_ERRORS])
def test_the_scan_survives_a_government_outage(exc_cls, monkeypatch):
    """⚠⚠ **정부 API 가 죽어도 스캔은 200 이어야 한다.** 이것이 (2) 다.

    남의 API 장애로 우리를 죽이지 않는 설계가 실제로 지켜지는지 **상태코드로**
    확인한다. 이전에는 500 이었다 - 재현해서 확인했다.
    """
    import logging

    import sourcing_guard.main as m

    def boom(request):
        raise exc_cls("boom")

    # ⚠ 시드를 끈다. 이 검사는 **캐시조차 없는** 세계를 재는 것이다 - 시드가
    #   얹히면 `stale` 로 답하고(그것도 맞는 동작이다) 이 경로를 안 탄다.
    #   시드가 있는 세계는 `test_outage_resilience` 가 따로 잰다.
    monkeypatch.setattr(m, "apply_cert_seed", lambda *a, **kw: m.SeedStats())

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
    # 값은 **넷** 중 하나여야 한다 - 화면이 그 넷만 다룬다.
    # ⚠ `stale` 이 2026-09-19 에 늘었다. 캐시로 답한 것을 `ok` 로 세면 화면
    #   바닥이 "정부 조회 인증 성공" 을 찍는데 근거 줄은 "연결하지 못해
    #   …조회분으로 표시합니다" 라 서로 반대를 말한다.
    #   화면의 대응표는 `static/index.html` 의 `LOOKUP` 이다 - 여기 넷과 같아야
    #   한다(아래 검사가 대조한다).
    assert set(gov.values()) <= set(GOV_LOOKUP_STATES)


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


# ---------------------------------------------------------------------------
# 경로별 계수 — 「무엇의 실패율인가」에 답할 수 있어야 한다
# ---------------------------------------------------------------------------


def test_the_health_counts_each_call_path_apart():
    """`_call()` 을 **네 갈래**가 공유한다. 합쳐 세면 무엇의 실패율인지 못 말한다.

    실제로 그 오독이 문서에 남았다 - `docs/미완_목록.md:3049` 가
    「9회 중 3회 실패(0.333) → **셀러 셋 중 하나**가 조회 실패를 본다」고
    적었는데, 그 실패는 **동기화의 domestic 호출**이었을 수 있다.

    주의(중요): 합계(`calls`·`failures`)는 **그대로 둔다.** 기존 감시와 검사가
      본다. 경로별은 더하는 것이지 대체가 아니다.
    """
    from sourcing_guard.kats_client import CALL_PATHS, KatsHealth

    h = KatsHealth()
    h.record_success("user_cert")
    h.record_failure("http", "502", path="sync_incremental")
    h.record_failure("http", "502", path="sync_incremental")
    h.record_success("sync_incremental")

    snap = h.snapshot()
    assert snap["calls"] == 4 and snap["failures"] == 2, snap
    assert snap["failure_rate"] == 0.5

    bp = snap["by_path"]
    assert set(bp) == set(CALL_PATHS), set(bp) ^ set(CALL_PATHS)
    assert bp["user_cert"] == {"calls": 1, "failures": 0, "failure_rate": 0.0,
                               "last_success_at": h.last_success_at}
    assert bp["sync_incremental"]["calls"] == 3
    assert bp["sync_incremental"]["failures"] == 2
    assert bp["sync_incremental"]["failure_rate"] == 0.667
    # 한 번도 안 부른 경로는 **비율이 None** 이다. 0.0 으로 두면 "전부 성공" 으로
    # 읽히는데 실제로는 부른 적이 없다 (4-p 와 같은 규칙).
    assert bp["sync_full"]["calls"] == 0
    assert bp["sync_full"]["failure_rate"] is None


def test_every_rate_ships_with_its_denominator():
    """비율 옆에 **분모**가 같이 나온다.

    `verifier.py:195` 가 룰 DB 에 대해 세운 규칙이다 - 「비율만 두면 표본
    여덟 개짜리가 통계처럼 읽히므로 표본을 반드시 함께 담는다」. `/healthz`
    만 그 규칙 밖이었다.
    """
    from sourcing_guard.kats_client import KatsHealth

    snap = KatsHealth().snapshot()
    assert {"calls", "failures", "failure_rate"} <= set(snap)
    for path, v in snap["by_path"].items():
        assert {"calls", "failures", "failure_rate"} <= set(v), (path, v)


def test_a_new_call_site_cannot_forget_the_path_label():
    """표지를 빠뜨리면 **TypeError 로 즉시 걸린다.** 기본값을 두지 않는다.

    기본값이 있으면 새 호출부가 조용히 엉뚱한 통에 쌓인다 - 그게 우리가
    고치려던 바로 그 병이다.
    """
    import inspect

    from sourcing_guard.kats_client import KatsClient, KatsHealth

    for fn in (KatsHealth.record_success, KatsHealth.record_failure, KatsClient._call):
        sig = inspect.signature(fn)
        p = sig.parameters["path"]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__} 의 path 에 기본값이 있다"


def test_no_call_site_is_left_unlabelled():
    """`_call(` 을 부르는 **모든** 자리가 `path=` 를 준다.

    주의(중요): 주석을 걷고 본다 - 이 규칙을 설명한 주석이 검사에 걸린다.
    """
    import re
    from pathlib import Path

    from tests.srccheck import code_only

    src = code_only((Path(__file__).resolve().parents[1]
                     / "sourcing_guard" / "kats_client.py").read_text(encoding="utf-8"))
    calls = list(re.finditer(r"self\s*\.\s*_call\s*\(", src))
    assert len(calls) >= 5, f"_call 호출부가 {len(calls)}곳뿐이다 - 못 찾고 있다"
    for m in calls:
        # 호출 끝까지 훑어 path= 가 있는지
        depth, i = 0, m.end() - 1
        while i < len(src):
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = src[m.end():i]
        assert "path =" in body or "path=" in body, f"표지 없는 호출: …{body[:60]}"
