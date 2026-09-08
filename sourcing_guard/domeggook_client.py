"""도매꾹·도매매 Open API 어댑터. **원문 dict 를 그대로 돌려준다.**

CLAUDE.md R4 가 승인한 유일한 상거래 경로다:

    https://www.domeggook.com/ssl/api/   (공개 Open API 전용)

⚠ **HTML 스크래핑은 금지다.** 검색 결과·상품 페이지 HTML 을 읽지 않는다.
  2026-09-04 에 실상품 표본을 만들 때 검색 HTML 을 읽었지만 그것은 조사용
  일회성이었고 프로덕션 경로가 아니다 (R4).

⚠ **등록된 IP 는 이 PC 의 공인 IP 다.** 도매꾹은 키 발급 시 호출 IP 를
  등록받고, 등록되지 않은 IP 에서의 호출은 거부된다. **401/403 이 나면
  키가 아니라 IP 변경부터 의심할 것** - 공유기 재시작·통신사 IP 재할당·
  다른 네트워크(테더링·카페 와이파이)면 바뀐다.

⚠ **배포본 코드에 연결하지 않는다.** 위 IP 제약 때문에 배포본에서 부르려면
  나가는 IP 가 고정이어야 한다. Fly 는 static egress IP 를 유료로 준다
  (docs/배포_Fly.io.md 참조). 확정 전까지 이 모듈은 `scripts/` 안에서만
  쓴다 - `main.py` 는 import 하지 않는다.

쿼터 (「OPEN API 이용 방법」 원문)
--------------------------------
    최대접속 허용량은 분당 180회, 하루 15,000회입니다. 이 허용량을 넘어서는
    경우에는 접속을 자동차단하여 HTTP Response Code 429 를 반환합니다.

    출처: https://openapi.domeggook.com/main/guide/start

분당 180회는 0.33초에 한 번이다. 우리는 **0.4초 이상** 간격을 둔다 - 여유를
두는 이유는 재시도가 없기 때문이다(아래).

⚠ **429 는 재시도하지 않는다.** 기록하고 멈춘다. 자동차단 상태에서 다시
  때리면 차단이 길어질 뿐이고, 2026-09-07 에 같은 측정을 두 프로세스가
  동시에 돌려 429 를 맞은 사고가 있었다 (CLAUDE.md §6).
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .allowed_hosts import ensure_allowed

_BASE = "https://www.domeggook.com/ssl/api/"

# 참조.md 가 권장하는 버전. 응답 필드가 버전마다 다르므로 고정한다.
_VER_LIST = "4.1"
_VER_VIEW = "4.6"

# `multiple=true` 의 상한. 참조.md: "최대 100개".
MAX_VIEW_BATCH = 100

# 분당 180회 = 0.33초/회. 재시도가 없으므로 여유를 둔다.
MIN_INTERVAL_SECONDS = 0.4

# 참조.md: 존재하지 않는 상품은 **40번 오류**다.
#
# ⚠ 이것은 예외가 아니라 **결과**다. 상품이 사라진 것도 우리가 알아야 하는
#   사실이고(표본이 9/6 것이라 사라진 상품이 있다), 예외로 던지면 수집이
#   중간에 멈춘다.
ERROR_CODE_NOT_FOUND = "40"


class DomeggookApiError(RuntimeError):
    """호출 자체가 실패했다. 40번(상품 없음)은 여기 오지 않는다."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DomeggookRateLimited(DomeggookApiError):
    """429. **재시도하지 않는다** - 자동차단 상태다."""


class DomeggookClient:
    """검색과 상세 조회 둘만 한다. 가공은 다른 모듈이 한다."""

    def __init__(
        self,
        api_key: str,
        *,
        market: str = "dome",
        min_interval: float = MIN_INTERVAL_SECONDS,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("도매꾹 API 키가 없습니다 (.env DOMEGGOOK_API_KEY)")
        self._key = api_key
        self._market = market
        self._min_interval = min_interval
        self._timeout = timeout
        self._last_call = 0.0
        self.calls = 0

    # ── 내부 ────────────────────────────────────────────────────────
    def _sleep_if_needed(self) -> None:
        gap = time.monotonic() - self._last_call
        if self._last_call and gap < self._min_interval:
            time.sleep(self._min_interval - gap)

    def _get(self, params: dict[str, Any]) -> dict:
        """원문 JSON 을 dict 로. 키는 쿼리(`aid`)로 보낸다.

        ⚠ 키를 로그·예외 메시지에 남기지 않는다. httpx 가 예외에 URL 을
          담을 수 있으므로 URL 을 문자열로 조립하지 않고 params 로 넘긴다.
        """
        ensure_allowed(_BASE)
        self._sleep_if_needed()
        query = {"aid": self._key, "om": "json", **params}
        try:
            res = httpx.get(_BASE, params=query, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise DomeggookApiError(f"도매꾹 호출 실패: {type(exc).__name__}") from None
        finally:
            self._last_call = time.monotonic()
            self.calls += 1

        if res.status_code == 429:
            raise DomeggookRateLimited(
                "429 - 분당 180회 · 하루 15,000회 한도를 넘어 자동차단됐습니다. "
                "재시도하지 않습니다.",
                status=429,
            )
        if res.status_code in (401, 403):
            raise DomeggookApiError(
                f"{res.status_code} - 인증 거부. **등록된 호출 IP 가 바뀌었는지 "
                "먼저 확인하세요** (도매꾹은 발급 시 IP 를 등록받습니다).",
                status=res.status_code,
            )
        if res.status_code != 200:
            raise DomeggookApiError(
                f"HTTP {res.status_code}", status=res.status_code
            )
        try:
            return res.json()
        except ValueError:
            raise DomeggookApiError("JSON 이 아닌 응답을 받았습니다") from None

    # ── 공개 ────────────────────────────────────────────────────────
    def search(self, kw: str, *, sz: int = 50, pg: int = 1) -> dict:
        """상품 리스트. 원문 dict 그대로.

        ⚠ 판매중지·판매종료·품절·단종은 **결과에 나오지 않는다** (참조.md).
          0건이 "그런 상품이 없다" 가 아니라 "지금 판매중이 아니다" 일 수 있다.

        ⚠ `kw` 검색이 형태소를 어떻게 분해하는지 우리는 모른다. 채택 판정은
          API 에 기대지 않고 `list.item.title` 을 우리가 비교한다.
        """
        if not 1 <= sz <= 200:
            raise ValueError("sz 는 1~200 입니다 (참조.md)")
        return self._get({
            "ver": _VER_LIST,
            "mode": "getItemList",
            "market": self._market,
            "kw": kw,
            "sz": sz,
            "pg": pg,
        })

    def view(self, nos: list[int]) -> dict:
        """상품 상세. `multiple=true` 로 최대 100개. 원문 dict 그대로.

        ⚠ 100개를 넘기면 자르지 않고 던진다 - 조용히 잘리면 수집 건수가
          맞지 않는데 그것을 알아채기 어렵다. 자르는 것은 부르는 쪽 일이다.

        ⚠ `safetyCert.type` / `.name` 은 읽지 않는다 - 폐기 예정 필드다.
          `certType` / `certName` 을 쓴다 (참조.md).
        """
        if not nos:
            raise ValueError("상품번호가 비었습니다")
        if len(nos) > MAX_VIEW_BATCH:
            raise ValueError(
                f"한 번에 {MAX_VIEW_BATCH}개까지입니다 (받은 것 {len(nos)}개). "
                "부르는 쪽에서 잘라 주세요."
            )
        return self._get({
            "ver": _VER_VIEW,
            "mode": "getItemView",
            "multiple": "true",
            "no": ",".join(str(n) for n in nos),
        })
