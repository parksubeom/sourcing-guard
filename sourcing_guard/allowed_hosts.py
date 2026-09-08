"""나가는 요청의 승인 호스트 목록. **코드가 강제한다.**

왜 코드로 옮겼나
----------------
CLAUDE.md R4 가 승인 도메인 표를 두고 있지만 "이 목록은 문서에만 있고 코드가
강제하지 않는다" 고 스스로 적어 뒀다. 그때는 서버가 외부로 나가는 경로가
`kats_client.py` 하나뿐이라 어댑터 계층이 사실상 게이트였고, R4 는 "어댑터가
둘 이상이 되면 호스트 검사를 코드로 옮기는 것을 검토한다" 고 조건을 달았다.

2026-09-08 에 `domeggook_client.py` 가 생겨 어댑터가 둘이 됐다. 조건이
충족됐으므로 옮긴다.

⚠ 목록은 R4 표와 **같아야 한다.** 어긋나면 검사가 깨진다 (test_allowed_hosts).
"""
from __future__ import annotations

from urllib.parse import urlsplit

# R4 표의 호스트. 전부 정부 도메인이거나 셀러 자신의 소싱처 공개 API 다.
#
#   safetykorea.kr   KC 인증 조회 · 리콜 공표 (Open API)      kats_client.py
#   emsit.go.kr      전파인증 번호 조회 (Open API)             예정 rra_client.py
#   rra.go.kr        전파인증 모델명 검색 · 부적합 현황 (HTML)  예정 rra_client.py
#   law.go.kr        고시·별표·부속서 원문 (DRF OpenAPI)        verifier 근거 URL · scripts/
#   domeggook.com    도매꾹·도매매 상품 (공개 Open API 전용)    domeggook_client.py
#
# ⚠ 상거래 사이트 무단 크롤링을 막는 것이 R4 의 목적이다. domeggook.com 은
#   **공개 Open API 만** 쓴다 - HTML 스크래핑은 금지다.
ALLOWED_HOSTS: frozenset[str] = frozenset({
    "safetykorea.kr",
    "emsit.go.kr",
    "rra.go.kr",
    "law.go.kr",
    "domeggook.com",
})


class HostNotAllowedError(RuntimeError):
    """승인 목록에 없는 호스트로 나가려 했다.

    ⚠ 이 예외가 뜨면 **URL 을 고치는 것이 아니라 R4 표를 먼저 고친다.**
      표에 적고, ALLOWED_HOSTS 에 넣고, 왜 필요한지 이 파일 주석에 적는다.
    """

    def __init__(self, url: str, host: str) -> None:
        super().__init__(
            f"승인되지 않은 호스트입니다: {host!r} ({url}). "
            "CLAUDE.md R4 표에 먼저 적고 ALLOWED_HOSTS 에 넣으세요."
        )
        self.url = url
        self.host = host


def host_of(url: str) -> str:
    """URL 의 호스트. 포트·사용자 정보를 뗀 소문자."""
    return (urlsplit(url).hostname or "").lower()


def is_allowed(url: str) -> bool:
    """이 URL 로 나가도 되는가.

    ⚠ **하위 도메인은 접미사로 본다** - `www.domeggook.com` 은
      `domeggook.com` 에 속한다. 다만 `evildomeggook.com` 처럼 앞에 붙은
      것은 아니다. 그래서 정확히 같거나 `.` 로 끝나는 접미사만 인정한다.
    """
    host = host_of(url)
    if not host:
        return False
    return any(
        host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_HOSTS
    )


def ensure_allowed(url: str) -> str:
    """호출 전에 부른다. 승인되지 않았으면 나가기 **전에** 던진다."""
    if not is_allowed(url):
        raise HostNotAllowedError(url, host_of(url))
    return url
