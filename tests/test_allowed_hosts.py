"""나가는 호스트 목록을 코드가 강제하는지 잠근다 (CLAUDE.md R4).

⚠ 전에는 R4 표가 "문서에만 있고 코드가 강제하지 않는다" 고 스스로 적고,
  "어댑터가 둘 이상이 되면 호스트 검사를 코드로 옮기는 것을 검토한다" 는
  조건을 달아 뒀다. 2026-09-08 에 `domeggook_client.py` 가 생겨 어댑터가
  둘이 됐으므로 옮겼다.

⚠ R4 표와 ALLOWED_HOSTS 가 **같아야 한다.** 어긋나면 여기서 깨진다 - 문서와
  코드가 갈라지는 것이 이 저장소의 반복 결함이다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from sourcing_guard.allowed_hosts import (
    ALLOWED_HOSTS,
    HostNotAllowedError,
    ensure_allowed,
    host_of,
    is_allowed,
)


def test_the_list_matches_the_r4_table():
    """CLAUDE.md R4 표의 호스트와 코드 상수가 같다."""
    rules = (Path(__file__).resolve().parents[1] / "CLAUDE.md").read_text(encoding="utf-8")
    # R4 표는 `| \`호스트\` | 용도 | 쓰는 곳 |` 꼴이다.
    in_table = set(re.findall(r"^\| `([a-z0-9.]+\.[a-z]{2,})` \|", rules, re.M))
    assert in_table, "R4 표에서 호스트를 못 읽었다 - 표 형식이 바뀌었나"
    assert in_table == set(ALLOWED_HOSTS), (
        f"표에만 있는 것 {in_table - set(ALLOWED_HOSTS)} · "
        f"코드에만 있는 것 {set(ALLOWED_HOSTS) - in_table}"
    )


def test_subdomains_pass_but_lookalikes_do_not():
    """하위 도메인은 통과, 앞에 붙인 이름은 막는다."""
    assert is_allowed("https://www.domeggook.com/ssl/api/?aid=x")
    assert is_allowed("https://domeggook.com/")
    assert is_allowed("https://safetykorea.kr/openapi/api/cert")
    assert is_allowed("https://www.law.go.kr/DRF/lawService.do")

    # ⚠ 접미사 검사를 문자열 endswith 로만 하면 여기서 뚫린다.
    assert not is_allowed("https://evildomeggook.com/api")
    assert not is_allowed("https://domeggook.com.attacker.net/")
    assert not is_allowed("https://example.com/")
    assert not is_allowed("not-a-url")


def test_ensure_allowed_raises_before_going_out():
    """승인되지 않은 호스트는 나가기 전에 던진다."""
    with pytest.raises(HostNotAllowedError) as got:
        ensure_allowed("https://example.com/x")
    # 예외 메시지가 무엇을 해야 하는지 말해 준다 - URL 을 고치는 게 아니다.
    assert "R4" in str(got.value)
    assert host_of("https://example.com/x") == "example.com"


def test_every_adapter_goes_through_the_gate():
    """어댑터가 나가기 전에 게이트를 부르는지 소스로 확인한다.

    ⚠⚠ **2026-09-11 까지 `rra_client.py` 가 빠져 있었다 (4-q).** 이 주석이
      "어댑터가 넷이 되면 여기 추가한다" 라고 적어 뒀는데 그때 이미 **셋**
      이었고, R4 표에는 `emsit.go.kr`·`rra.go.kr` 이 있었다. 목록을 손으로
      적으면 이런 일이 난다 - 그래서 이제 **파일을 훑어 자동으로 찾는다.**

    소스 검사인 이유는 실제 호출 없이 "부르는가" 를 확인해야 하기 때문이고,
    아래 런타임 검사가 그 짝이다.
    """
    root = Path(__file__).resolve().parents[1] / "sourcing_guard"
    # 나가는 어댑터를 **자동으로 찾는다.**
    #
    # ⚠ `httpx.Client(` 만 보면 안 된다 - `domeggook_client` 는 모듈 함수
    #   `httpx.get(...)` 을 직접 쓴다. 실제로 그렇게 짰다가 2개만 잡혔다.
    _MARKERS = ("httpx.Client(", "httpx.get(", "httpx.post(", "httpx.request(")
    adapters = sorted(
        p.name for p in root.glob("*.py")
        if any(mark in p.read_text(encoding="utf-8") for mark in _MARKERS)
    )
    assert adapters, "어댑터를 하나도 못 찾았다 - 검사 전제가 바뀌었나"
    for name in adapters:
        src = (root / name).read_text(encoding="utf-8")
        assert "ensure_allowed(" in src, (
            f"{name} 이 httpx 로 나가는데 R4 게이트가 없다"
        )
    # 알고 있는 어댑터 수. 늘면 위 자동 탐색이 새 파일을 잡았다는 뜻이다.
    assert len(adapters) == 3, f"어댑터가 바뀌었습니다: {adapters}"


def test_kats_client_is_blocked_when_the_base_url_is_overridden_badly():
    """**런타임으로도 확인한다.** `KATS_BASE_URL` 오버라이드가 구멍이었다.

    이 어댑터의 호스트는 설정에서 온다. env 를 잘못 넣으면 승인되지 않은
    호스트로 나갈 수 있었고, 게이트 도입 전에는 코드가 막지 않았다.

    ⚠ 던지는 것은 `KatsApiError` 가 **아니다.** 설정 오류를 조회 실패로
      삼키면 UNKNOWN 으로 반올림되고, 잘못된 호스트를 부르고 있다는 사실이
      화면에서 사라진다.
    """
    import httpx

    from sourcing_guard.kats_client import KatsApiError, KatsClient

    called = []

    def handler(request):
        called.append(str(request.url))
        return httpx.Response(200, json={"resultCode": "2000", "resultData": []})

    client = KatsClient("https://evil.example.com/api", "KEY123", mock=False)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(HostNotAllowedError):
        client.lookup_certification("CB061R2170-3018")
    assert called == [], "게이트가 나간 뒤에 걸렸다 - 나가기 전이어야 한다"

    # 기본값(매핑 파일의 safetykorea.kr)은 통과한다.
    ok_client = KatsClient(None, "KEY123", mock=False)
    ok_client._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert ok_client.lookup_certification("CB061R2170-3018") is None
    assert called and "safetykorea.kr" in called[0]
    assert KatsApiError is not HostNotAllowedError


def test_the_domeggook_client_is_not_wired_into_the_deployed_app():
    """배포본이 도매꾹을 부르지 않는다.

    ⚠ 도매꾹은 **호출 IP 를 등록받는다.** Fly 의 나가는 IP 는 고정이 아니므로
      배포본에서 부르면 401/403 이 난다. 고정 egress IP 를 확정하고 등록
      신청을 마친 뒤에 연결한다 (docs/배포_Fly.io.md).

    ⚠ 이 검사가 깨지면 "고정 IP 를 확정했는가" 를 먼저 물을 것.
    """
    root = Path(__file__).resolve().parents[1] / "sourcing_guard"
    main = (root / "main.py").read_text(encoding="utf-8")
    assert "domeggook" not in main.lower(), (
        "main.py 가 도매꾹을 부른다 - 고정 egress IP 를 확정했는가"
    )
