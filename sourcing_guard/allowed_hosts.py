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
#   openapi.foodsafetykorea.go.kr
#                    식약처 회수·판매중지 (I0490)              **scripts/ 전용**
#
# ⚠ 상거래 사이트 무단 크롤링을 막는 것이 R4 의 목적이다. domeggook.com 은
#   **공개 Open API 만** 쓴다 - HTML 스크래핑은 금지다.
#
# ⚠⚠ **식약처는 `scripts/` 안에서만 부른다.** 배포본 앱은 이 호스트로 나가지
#   않는다 - 키가 URL **경로**에 들어가고 HTTPS 가 안 된다(실측: https →
#   connection reset · http → 200). 배포본이 매일 부르면 키가 평문으로, 그것도
#   로그·예외에 URL 째로 남는다. 받아서 **로컬 사본**을 만들고 앱은 사본만 읽는다.
#   `ALLOWED_HOSTS` 는 "나가도 되는 곳" 목록이지 "앱이 부른다" 는 뜻이 아니다 -
#   그 구분은 R4 표 비고와 `tests/test_allowed_hosts.py` 가 지킨다.
ALLOWED_HOSTS: frozenset[str] = frozenset({
    "safetykorea.kr",
    "emsit.go.kr",
    "rra.go.kr",
    "law.go.kr",
    "domeggook.com",
    "openapi.foodsafetykorea.go.kr",
})


class HostNotAllowedError(RuntimeError):
    """승인 목록에 없는 호스트로 나가려 했다.

    ⚠ 이 예외가 뜨면 **URL 을 고치는 것이 아니라 R4 표를 먼저 고친다.**
      표에 적고, ALLOWED_HOSTS 에 넣고, 왜 필요한지 이 파일 주석에 적는다.


    ⚠⚠ **URL 을 마스킹해서 담는다 (2026-09-14 · ⑦-b-1).**

      실측으로 확인한 **유일한 누출 자리**였다 - `str` · `repr` · `.url`
      셋 다 키를 그대로 들고 있었다. httpx 예외는 메시지에 URL 을 안 담지만
      이 예외는 담는다. 식약처처럼 키가 **경로**에 들어가는 API 가 붙으면
      예외 한 번에 키가 로그로 나간다.

      ⚠ `self.url` 에도 **원문을 두지 않는다.** 두면 부르는 쪽이 그것을 찍고,
        그 순간 마스킹한 의미가 없어진다.
    """

    def __init__(self, url: str, host: str) -> None:
        from .masking import mask_url

        safe = mask_url(url)
        super().__init__(
            f"승인되지 않은 호스트입니다: {host!r} ({safe}). "
            "CLAUDE.md R4 표에 먼저 적고 ALLOWED_HOSTS 에 넣으세요."
        )
        self.url = safe
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
