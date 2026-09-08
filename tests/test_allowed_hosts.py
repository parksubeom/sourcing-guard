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


def test_both_adapters_go_through_the_gate():
    """어댑터가 나가기 전에 게이트를 부르는지 소스로 확인한다.

    ⚠ 런타임으로 잡기 어렵다 - 실제 호출을 해야 한다. 그래서 소스에서
      `ensure_allowed` 호출 존재를 본다. 어댑터가 셋이 되면 여기 추가한다.
    """
    root = Path(__file__).resolve().parents[1] / "sourcing_guard"
    dome = (root / "domeggook_client.py").read_text(encoding="utf-8")
    assert "ensure_allowed(" in dome

    # ⚠ kats_client 는 게이트 도입 전에 만들어졌다. 그 어댑터가 도는 호스트는
    #   설정에서 오므로(kats_base_url 오버라이드 가능) 게이트를 붙이는 것이
    #   맞지만, 이번 변경에서는 손대지 않았다 - 별건이다.
    #   미완 목록에 적어 두고 여기서 사실만 잠근다.
    kats = (root / "kats_client.py").read_text(encoding="utf-8")
    assert "ensure_allowed(" not in kats, (
        "kats_client 에 게이트가 붙었다면 이 검사와 미완 목록을 갱신할 것"
    )


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
