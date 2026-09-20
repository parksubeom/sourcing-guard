"""시크릿을 문자열에서 지운다 — [⑦-b-1].

⚠⚠ **URL 을 만드는 곳과 남기는 곳을 가른다.** 만들 때는 진짜 키가 들어가고,
  예외·로그에 남길 때는 언제나 `***` 다. 이 파일이 그 경계다.

왜 필요한가 — **실측** (2026-09-14)
-----------------------------------
새는 자리를 재 봤다. 추측하지 않았다:

    httpx.HTTPStatusError / ConnectError / ReadTimeout
        str·repr 에 URL 이 **안 들어간다** → 새지 않는다
        다만 `exc.request.url` 을 우리가 찍으면 샌다
    도매꾹 (키가 쿼리 `aid`)
        `request.url` 에 들어 있다 → 우리가 찍으면 샌다
    국표원 (키가 헤더 `AuthKey`)
        URL 에 아예 없다 → 안 샌다
    HostNotAllowedError
        **str · repr · .url 셋 다 샌다** ← 유일하게 확인된 누출

식약처는 키가 **URL 경로**에 들어가고 HTTPS 도 안 된다. 그래서 호출을 하기
전에 이것부터 만든다 (총괄 ⑦-b-1).

두 겹으로 막는다
---------------
① **아는 값**을 지운다. 우리 키는 우리가 안다 - `.env` 에서 읽어 등록해 두면
   문자열 어디에 있든(경로·쿼리·본문) 정확히 지워진다. 과·부족이 없다.
② **키처럼 보이는 쿼리 이름**을 지운다. ①이 모르는 키(스크립트가 손으로 넣은
   것)를 위한 그물이다.

⚠ ②만으로는 부족하다 - 식약처는 키가 **경로**에 있어 쿼리 이름이 없다.
⚠ ①만으로도 부족하다 - 스크립트가 등록 안 한 키를 쓸 수 있다.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MASK = "***"

#: 등록된 시크릿 값. **원문을 로그에 남기지 않는다** - 이 집합 자체도 찍지 않는다.
_SECRETS: set[str] = set()

#: 키가 담기는 쿼리 이름. 소문자로 비교한다.
#:
#: ⚠ `OC` 는 넣지 않는다. law.go.kr 의 `OC=test` 는 공개 값이고 시크릿이
#:   아니다 - 넣으면 근거 URL 이 `***` 로 가려져 셀러가 못 연다.
_KEY_PARAMS = frozenset({
    "aid",            # 도매꾹
    "servicekey",     # 공공데이터포털 계열
    "authkey",        # 국표원 (지금은 헤더지만 쿼리로 바뀔 수 있다)
    "apikey", "api_key", "key", "token", "access_token", "secret",
})

#: 짧은 값은 키가 아니다. 12자 미만을 지우면 본문이 `***` 투성이가 된다.
_MIN_SECRET_LEN = 12


def register_secret(value: str | None) -> None:
    """이 값이 문자열에 보이면 언제나 지운다.

    ⚠ 짧은 값은 등록하지 않는다. `mock` 같은 값이 등록되면 본문 여기저기가
      가려져 오히려 읽을 수 없게 된다.
    """
    if value and len(value) >= _MIN_SECRET_LEN:
        _SECRETS.add(value)


#: 앱이 들고 있는 시크릿 설정 이름. **여기가 한 곳이다.**
#:
#: ⚠⚠ **이름으로 가리지 않는다. 둘로 나눠 전부 분류한다.**
#:   전에는 `*_key`·`*_token` 이라는 이름 규칙으로 대조했는데, 그러면
#:   `credential` 처럼 **이름이 다른 시크릿**이 조용히 빠진다. 지금은
#:   `SECRET_SETTINGS` 와 `PUBLIC_SETTINGS` 를 양쪽에 두고
#:   "`Settings` 의 모든 필드가 **둘 중 하나에** 있어야 한다" 를 검사한다 -
#:   새 필드를 넣는 순간 **분류를 강제당하므로** 이름을 맞힐 필요가 없다.
#:
#: ⚠ `DOMEGGOOK_API_KEY` · `MFDS_API_KEY` 는 여기 없다. **앱이 안 읽는다** -
#:   `scripts/` 전용이고 각 스크립트가 호출 전에 `register_secret` 을 부른다
#:   (CLAUDE.md R4 - 식약처는 배포본이 부르지 않는다).
SECRET_SETTINGS: tuple[str, ...] = (
    "anthropic_api_key", "gpt_api_key", "kats_service_key", "sync_token",
)

#: 시크릿이 **아닌** 설정. 모델 이름·경로·스위치처럼 로그에 남아도 되는 것.
#:
#: ⚠ `kats_base_url` 은 주소이지 키가 아니다. `extractor_order` 는 벤더 순서다.
#: ⚠ 타임아웃은 **초 단위 숫자**다. 키가 아니고, `/healthz` 가 무엇으로
#:   쟀는지 보여 주려면 밖으로 나가야 한다 (2026-09-20 P1).
PUBLIC_SETTINGS: tuple[str, ...] = (
    "mock_mode", "extractor_model", "gpt_model", "extractor_order",
    "kats_base_url", "watchlist_db_path", "sync_enabled",
    "kats_connect_timeout", "kats_read_timeout",
)


def register_settings_secrets() -> None:
    """`.env` 에서 읽은 앱 키를 전부 등록한다. **앱이 시작할 때 맨 먼저** 부른다.

    ⚠⚠ 등록 전에 던져진 예외는 키를 그대로 담는다. 2026-09-14 까지 이 함수가
      프로덕션에서 **한 번도 안 불렸고**, 마스킹이 `scripts/` 에서만 일하고
      있었다 - `HostNotAllowedError` 가 배포본에서 키를 담을 수 있었다.
    """
    from .config import settings

    for name in SECRET_SETTINGS:
        register_secret(getattr(settings, name, None))


def mask(text: str) -> str:
    """등록된 시크릿을 지운다. 문자열 어디에 있든."""
    if not text:
        return text
    for secret in _SECRETS:
        text = text.replace(secret, MASK)
    return text


def mask_url(url: str) -> str:
    """URL 하나를 남길 수 있는 모양으로.

    ① 등록된 값 지우기 → ② 키처럼 보이는 쿼리 값 지우기.

    ⚠ **경로에 든 키는 ①만 잡는다.** 식약처(`/api/{키}/I0490/json/1/5`)가
      그 모양이라, 그 어댑터는 자기 키를 반드시 `register_secret` 해야 한다.
      어댑터가 그것을 잊지 않게 검사로 잠갔다.
    """
    if not url:
        return url
    url = mask(url)
    try:
        parts = urlsplit(url)
    except ValueError:                       # pragma: no cover - 깨진 URL
        return url
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    scrubbed = [
        (name, MASK if name.lower() in _KEY_PARAMS and value else value)
        for name, value in pairs
    ]
    # ⚠ `safe="*"` 가 없으면 `***` 가 `%2A%2A%2A` 로 나간다. 가려지긴 하지만
    #   눈으로 못 알아보고, 로그를 훑는 사람이 "이게 키인가" 를 다시 묻는다.
    return urlunsplit(parts._replace(query=urlencode(scrubbed, safe="*")))


#: 키가 **파일에 박혔는지** 보는 자국. 커밋 전 검사가 쓴다.
#:
#: ⚠⚠ **모양만으로는 못 가린다.** 처음엔 `[0-9a-f]{40}` 로 잡으려 했는데
#:   **git 해시가 전부 걸렸다**(CLAUDE.md · test_commit_refs 의 옛 해시 97건).
#:   식약처 키도 40자 16진수라 모양이 git 해시와 같다 - 구분할 수 없다.
#:
#:   그래서 모양이 아니라 **자리**를 본다: `키이름 = "긴 리터럴"`. 키가 파일에
#:   박히는 것은 언제나 그 모양이고, 해시는 그 자리에 안 온다.
#:
#: ⚠ 환경변수에서 읽는 줄은 잡지 않는다 - `os.getenv("X_API_KEY")` 는 이름일
#:   뿐 값이 아니다.
_KEY_LITERAL = re.compile(
    r"""(?ix)
    # ⚠ `\b` 를 쓰지 않는다. `KATS_SERVICE_KEY` 의 `_` 는 낱말 문자라
    # `SERVICE` 앞에 경계가 없다 - 실측에서 그 줄을 놓쳤다.
    #
    # ⚠⚠ **이름 목록을 열거하면 우리가 안 적은 이름이 새 나간다** (2026-09-14).
    #   `api_key|service_key|auth_key` 만 적었더니 `FOOD_SAFETY_KEY = "..."` 이
    #   안 걸렸다 - 지금 붙이려는 식약처 키가 정확히 그 이름이 될 자리였다.
    #   이름을 세지 말고 **`key` 로 끝나는 낱말 전부**를 본다.
    (?:[a-z0-9]*[_-]?key|secret|token|aid|passwd|password)
    \s*[:=]\s*
    ["']?(?P<value>[A-Za-z0-9+/=\-_]{16,})["']?
    """
)

#: 식약처는 **키가 URL 경로에 들어간다.** 이름이 없으므로 이름 규칙으로는 못 본다.
#: 모양(40자 16진수)으로 잡으면 git 해시가 전부 걸리므로 **그 호스트의 그 자리**만
#: 본다 - 해시는 이 자리에 오지 않는다.
_KEY_IN_PATH = re.compile(
    r"(?i)foodsafetykorea\.go\.kr/api/(?P<value>[A-Za-z0-9]{16,})/"
)

#: 값이 아닌 것들. 이름·자리표시자·환경변수 참조.
# ⚠ 상수 이름 규칙은 **밑줄을 요구한다**. `[A-Z][A-Z0-9]{5,}` 로 두면
#   대문자 키(`ABCDEFGH12345678…`)까지 건너뛴다 - 도매꾹 키가 그 모양이다.
_NOT_A_VALUE = re.compile(
    r"(?i)^(?:os\.getenv|settings|none|null|true|false|\*+|x+|your|<.*>|"
    r"[A-Z][A-Z0-9]*_[A-Z0-9_]+)$"
)


def looks_like_a_key(text: str) -> list[str]:
    """키 리터럴이 박힌 자리를 돌려준다. 커밋 전에 부른다."""
    out = []
    for rx in (_KEY_LITERAL, _KEY_IN_PATH):
        for m in rx.finditer(text or ""):
            value = m.group("value")
            if value == MASK or _NOT_A_VALUE.match(value):
                continue
            # ⚠ **숫자가 하나도 없으면 키가 아니라 이름이다.** 이름 규칙을 넓히니
            #   `key = _normalize_number` 같은 평범한 변수 대입이 걸렸다(실측 1건).
            #   우리가 받은 키 셋(국표원·도매꾹·식약처)은 전부 숫자를 포함한다.
            #   ⚠ 뒤집으면 - **글자만으로 된 키는 못 본다.** 그런 키를 받으면
            #     여기를 고친다.
            if not any(c.isdigit() for c in value):
                continue
            out.append(value)
    return out
