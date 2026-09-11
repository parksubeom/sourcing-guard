"""**"이 문자열은 값이 아니다" 를 판단하는 유일한 자리.**

CLAUDE.md §6: 같은 판단을 두 곳에 적지 마라. 조건이 갈리면 한쪽만 고쳐도 나머지가
거짓말을 계속한다.

2026-09-12 에 이 판단이 **여섯 곳**에 흩어져 있었다:

    domeggook_adapter.NOT_A_VALUE          "해당없음" 류
    domeggook_fields._PLACEHOLDER_CORE     "상세설명참조" 류
    watchlist._MODEL_PLACEHOLDERS          위 둘 + 색상명·필드라벨·숫자
    watchlist._MAKER_PLACEHOLDERS          위 둘 + "회사정보없음" 류
    kats_client.CERT_PLACEHOLDERS          위 둘 + "공급자적합성"·"비대상"
    LLM 추출                               **아무 데서도 안 걸렸다**

그래서 뒤처진 것이 LLM 경로였다 - 실측(도매꾹 상세 109): `model_name` 이 값 아닌
문자열인 줄 **34건**. 그 값으로 `RecallIndex.can_compare()` 가 True 가 되어 리콜
대조를 했다고 말했다. 사본에 같은 문자열이 있으면 **가짜 일치**다 (R3).

⚠⚠ **4-r 과 같은 뿌리다.** 4-r 은 "대조하지 않고 대조했다고 말한 것" 이었고, 이것은
  "값이 아닌 문자열을 값으로 읽어 대조한 것" 이다. 둘 다 "오류 표시가 없으면 성공"
  의 친척이다 - 우리가 이해하지 못한 입력은 값이 아니다.

## 층이 둘이다

    층 1  "값이 아니다"        ← **이 모듈.** 어느 필드든 공통
    층 2  "모델명/업체명/인증번호가 아니다"  ← 각 도메인. 층 1 을 부르고 자기 것만 더한다

층 2 를 여기로 합치지 않는다. 색상명 `BLACK` 은 **값이긴 하지만 모델명이 아니다** -
다른 판단이다. 합치면 `materials=["BLACK"]` 같은 정당한 값이 사라진다.

⚠ `data/kats_field_map.yaml` 의 `cert_state_not_stated` 는 **그대로 둔다.** 그쪽은
  `certState` 전용이고, "필드명·값을 코드에 하드코딩하지 않고 매핑에서 주입한다" 는
  원칙(R5 · §6)이 걸려 있다. 목록이 이 모듈과 같아 보이지만 소유자가 다르다 -
  설계서가 정하는 값이다.

## R6 과 무관하다

워치리스트의 오류 비대칭(R6: 놓친 알림이 더 비싸다)은 **매칭 강도**에 걸리는 것이지
자리표시자 판정이 아니다. "해당없음" 을 모델명으로 받아 관대하게 매칭하는 것은
관대함이 아니라 **엉뚱한 상품과의 일치**다 - 약한 일치로도 세면 안 된다. 그래서
`watchlist` 도 이 모듈을 부른다.

## 항목을 추가할 때

**출처를 적는다 (R5).** 어느 실측에서 나왔는지 - 없으면 넣지 않는다.
"그럴 것 같은" 문자열을 이 기회에 끼워 넣으면 정당한 값을 잃는다.
"""

from __future__ import annotations

import re

#: 정규화(공백 제거·소문자) 후 이 집합에 있으면 값이 아니다.
#:
#: ⚠ 각 항목의 출처를 함께 적는다. 출처 없는 문자열은 넣지 않는다 (R5).
NOT_A_VALUE: frozenset[str] = frozenset({
    # ── 미입력 표기 ────────────────────────────────────────────────
    # 도매꾹 실측 2026-09-12 · 190건 중 model="해당없음" 71 · manufacturer 2
    "해당없음",
    "해당사항없음",
    # SafetyKorea 설계서 p.10 · kats_field_map.cert_state_not_stated 와 같은 값
    "없음",
    "n/a",
    "na",
    # 도매꾹 미입력 기본값. 참조.md §6 이 "`-` 이면 없는 것으로" 라 적는다
    "-",
    # 워치리스트 실측(2026-09-01 · 리콜 사본) model 칸
    "미상",
    "미기재",
    # ── 본문으로 미루는 표기 ───────────────────────────────────────
    # 도매꾹 고시 항목 desc 실측 2026-09-08 · 100건
    "상세설명참조",
    "상세정보별도표기",
    "상세페이지참조",
    "상품상세참조",
    "본문참조",
    # 실측 2026-09-12 · 도매꾹 상품번호 21114291 (model·maker 에 홑말로만)
    "상세페이지",
    "상세설명",
    "상세참조",
    "본문",
})

#: 조각 구분자. 고시 항목은 `품명 / 모델명` 꼴로 두 값을 이어 적는다.
_SPLIT = re.compile(r"[/·,]")
#: 공백 · 괄호 · 강조 기호를 지운다. 도매꾹은 `[상세정보 별도표기]` 처럼 대괄호를
#: 씌워 적는다 - 실측(2026-09-08 · 100건). 이 규칙은 `domeggook_fields._STRIP` 에
#: 있던 것을 옮겨 온 것이고, 옮기지 않았다가 검사에서 걸렸다.
_STRIP = re.compile(r"[\s\[\]()（）<>「」『』·*~]+")


def normalize(value: str) -> str:
    """비교용 정규화. 공백·괄호·강조 기호를 지우고 소문자로."""
    return _STRIP.sub("", value or "").lower()


def is_not_a_value(value: str | None) -> bool:
    """값이 있으나 내용이 없는가.

    슬래시로 이은 항목(`상세설명참조 / 상세설명참조`)은 **조각 전부가** 값이
    아닐 때만 참이다. 한쪽에 실제 모델명이 있으면 내용이 있다.

    >>> is_not_a_value("해당없음"), is_not_a_value("K2018")
    (True, False)
    >>> is_not_a_value("블록 완구 / BLK-100")      # 한쪽이 값이다
    False
    >>> is_not_a_value("N/A")                      # 전체를 먼저 본다
    True

    ⚠ **전체 문자열을 먼저 본다.** 조각부터 보면 `N/A` 가 `N`·`A` 로 쪼개져
      통과한다 - 실제로 그렇게 짰다가 걸렸다. 구분자가 자리표시자 안에 있을 수
      있다는 것을 잊으면 안 된다.
    """
    if value is None:
        return True
    whole = normalize(str(value))
    if not whole or whole in NOT_A_VALUE:
        return True
    parts = [p for p in _SPLIT.split(str(value)) if p.strip()]
    if not parts:
        return True
    return all(normalize(p) in NOT_A_VALUE or not normalize(p) for p in parts)


def clean(value: object) -> str | None:
    """값이면 양끝 공백만 지운 문자열, 아니면 `None`.

    ⚠ 내용을 바꾸지 않는다 - 자리표시자를 `None` 으로 만들 뿐이다. 원문 표기를
      고치는 것은 우리 일이 아니다 (R5).
    """
    if value is None:
        return None
    s = str(value).strip()
    return None if (not s or is_not_a_value(s)) else s


def clean_list(values: object) -> list[str]:
    """리스트에서 값 아닌 조각을 뺀다. 순서와 중복은 그대로."""
    if not isinstance(values, (list, tuple)):
        return []
    out = []
    for v in values:
        c = clean(v)
        if c is not None:
            out.append(c)
    return out
