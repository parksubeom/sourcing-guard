"""국표원 조회 타임아웃 — **설정으로 빼되 기본 동작은 그대로다** (P1).

왜 있나
-------
배포본(fly nrt)에서 조회가 실패하는데 **차단이 아니라 시간을 꽉 채우고
포기하는 모양**이었다. 그런데 `ConnectTimeout` 과 `ReadTimeout` 이 둘 다
`network` 하나로 뭉개져 있어 둘을 가를 수 없었다:

    연결이 안 된다   시간을 늘려도 소용없다. 경로 문제다
    응답이 느리다    시간을 늘리면 된다

그 구분이 플랫폼을 옮길지 말지를 정한다. 그래서 나눴다.

⚠ 재시도는 넣지 않았다 - `kats_client.py` 의 "남의 API 장애로 우리를 죽이지
  않는 설계는 그대로다. 추가하는 것은 **관측**뿐이다" 를 지킨다.
"""

from __future__ import annotations

import httpx
import pytest

from sourcing_guard.config import Settings, _env_float
from sourcing_guard.kats_client import KatsClient, _network_code


def test_the_default_is_exactly_what_it_was():
    """⚠⚠ **이 변경은 동작을 바꾸는 것이 아니다.**

    아무것도 설정하지 않으면 전과 같은 8초여야 한다. 기본값이 바뀌면 이
    커밋이 조용히 운영 동작을 바꾼 것이 된다.
    """
    c = KatsClient(None, None, mock=True)
    t = c._timeout
    assert (t.connect, t.read, t.write, t.pool) == (8.0, 8.0, 8.0, 8.0)


def test_the_two_can_be_set_apart():
    c = KatsClient(None, None, mock=True, connect_timeout=10.0, read_timeout=30.0)
    t = c._timeout
    assert t.connect == 10.0 and t.read == 30.0
    # ⚠ write·pool 은 `timeout` 을 따른다 - 재는 대상이 아니다.
    assert t.write == 8.0 and t.pool == 8.0


@pytest.mark.parametrize("env,want", [
    ("", 8.0),          # 안 주면 기본
    ("   ", 8.0),       # 공백만이어도 기본
    ("abc", 8.0),       # 오타여도 **앱이 떠야 한다**
    ("0", 8.0),         # 0 은 "즉시 포기" 라 사고다
    ("-5", 8.0),
    ("30", 30.0),
    ("2.5", 2.5),
])
def test_a_bad_number_falls_back_instead_of_killing_the_app(monkeypatch, env, want):
    """⚠ 조회 하나가 느린 것과 **서비스가 안 뜨는 것**은 값이 다르다.

    대신 조용히 떨어진 것을 `/healthz` 가 보여 준다 - 설정값을 그대로 낸다.
    """
    monkeypatch.setenv("KATS_READ_TIMEOUT", env)
    assert _env_float("KATS_READ_TIMEOUT", 8.0) == want


def test_the_settings_reach_the_client(monkeypatch):
    """설정을 만들어 놓고 안 넘기면 아무 일도 안 일어난다 - 실제로 그랬다."""
    import inspect

    from sourcing_guard import main

    src = inspect.getsource(main)
    i = src.index("_kats = KatsClient(")
    block = src[i:i + 500]
    assert "settings.kats_connect_timeout" in block, "connect 설정을 안 넘긴다"
    assert "settings.kats_read_timeout" in block, "read 설정을 안 넘긴다"


def test_the_failure_code_says_which_kind_it_was():
    """⚠⚠ 이 구분이 P1 의 답 자체다.

    ⚠ `ConnectTimeout` 은 `TimeoutException` 의 하위다. 순서를 바꾸면 전부
      `network.read` 가 된다 - 반대 방향으로 단정한다.
    """
    assert _network_code(httpx.ConnectTimeout("x")) == "network.connect"
    assert _network_code(httpx.ConnectError("x")) == "network.connect"
    assert _network_code(httpx.ReadTimeout("x")) == "network.read"
    assert _network_code(httpx.PoolTimeout("x")) == "network.pool"
    # 모르는 것은 그대로 둔다 - 없는 구분을 만들지 않는다 (R3).
    assert _network_code(ValueError("x")) == "network"
    assert _network_code(httpx.HTTPError("x")) == "network"


def test_healthz_shows_what_we_measured_with():
    """⚠ 환경변수를 잘못 적으면 기본값으로 떨어진다. 그 상태로 재면 "올렸다고
    믿는 값" 으로 재게 된다 - 회차마다 이 값을 읽는다.
    """
    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    with TestClient(app) as c:
        k = c.get("/healthz").json()["kats"]
    assert "connect_timeout" in k and "read_timeout" in k


def test_no_retry_was_added():
    """`kats_client` 주석이 허용한 것은 **관측**뿐이다."""
    import inspect

    from sourcing_guard import kats_client

    src = inspect.getsource(kats_client)
    for banned in ("for attempt in", "max_retries", "Retry(", "backoff", "time.sleep"):
        assert banned not in src, f"재시도로 보이는 것이 들어왔다: {banned}"
