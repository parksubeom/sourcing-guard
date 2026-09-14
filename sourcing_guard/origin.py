"""상세페이지의 제조국 표기를 읽는다 — [⑦-d] 원산지 대조.

⚠⚠ **추출 프롬프트를 건드리지 않는다.** `ProductFacts` 에 제조국 필드를
  더하면 프롬프트가 바뀌고, 그러면 R7 대로 **새표본 235건을 다시 재야 한다**
  (LLM 235회). 제조국 표기는 `제조국: 중국` 처럼 형식이 고정돼 있어 결정적
  코드로 읽을 수 있다 - `CERT_NUMBER_RE` 가 인증번호를 읽는 것과 같은 자리다.

⚠⚠ **"다르다" 를 말하려면 양쪽을 다 알아야 한다.**
  한쪽이라도 못 읽으면 아무 말도 하지 않는다. 없는 것을 문제로 만들지 않는
  다는 것이 이 파일의 규칙이고, CLAUDE.md §6 의 "없는데 있다고 하는 쪽이
  있는데 없다고 하는 쪽보다 비싸다" 가 그대로 적용된다 - 잘못된 불일치
  한 줄이 정상 상품을 의심하게 만든다.

실측 (도매꾹 상세텍스트 2026-09-08 · 379건)

    154  수입산_아시아_중국        ← 도매꾹 코드형. 마지막 칸이 나라다
     66  또는 원산지 : 상세정보 별도표기   ← 값이 아니다
     41  상세정보 별도표기
     29  중국
      9  국산
      3  수입산_유럽_프랑스
      2  중국oem · CHINA
      2  국산_충청남도_보령시      ← 마지막 칸이 나라가 아니다(시·군)
"""

from __future__ import annotations

import re

from .placeholders import is_not_a_value

#: 표기 앞의 이름. 도매꾹 상세는 "제조국 또는 원산지" 로 온다.
_LABEL = re.compile(
    r"(?:제조\s*국가?|원산지|생산지)(?:\s*또는\s*원산지)?\s*[:：]?\s*"
    r"(?P<value>[^\n\r,·|/\]]{1,30})"
)

#: 관찰된 표기 → 나라 이름. **관찰된 것만 넣는다** (R5 · 크레파스 원칙).
#:
#: ⚠ 여기 없는 말은 "모르는 나라" 이고, 모르면 불일치를 말하지 않는다.
#:   목록을 넓히는 것이 아니라 **모를 때 침묵하는 것**이 이 표의 안전장치다.
_COUNTRY: dict[str, str] = {
    "중국": "중국", "china": "중국", "중국산": "중국", "중국oem": "중국",
    "한국": "대한민국", "대한민국": "대한민국", "국산": "대한민국",
    "국내": "대한민국", "국내산": "대한민국", "korea": "대한민국",
    "베트남": "베트남", "vietnam": "베트남",
    "일본": "일본", "japan": "일본",
    "미국": "미국", "usa": "미국",
    "대만": "대만", "taiwan": "대만",
    "프랑스": "프랑스", "france": "프랑스",
    "독일": "독일", "germany": "독일",
    "인도": "인도", "india": "인도",
    "태국": "태국", "thailand": "태국",
    "인도네시아": "인도네시아", "말레이시아": "말레이시아",
    "방글라데시": "방글라데시", "캄보디아": "캄보디아", "미얀마": "미얀마",
    "이탈리아": "이탈리아", "스페인": "스페인", "영국": "영국",
}


def normalize_country(raw: str | None) -> str | None:
    """표기 하나를 나라 이름으로. **모르면 None** 이다.

    ⚠ 모르는 말을 그대로 돌려주지 않는다. 그러면 '상세정보 별도표기' 와
      '중국' 이 서로 다른 나라가 되어 가짜 불일치가 된다.
    """
    if not raw:
        return None
    text = raw.strip().strip(".:·-()[]{}\"'")
    if not text or is_not_a_value(text):
        return None
    # 도매꾹 코드형 `수입산_아시아_중국`. 칸을 뒤에서부터 본다 -
    # `국산_충청남도_보령시` 는 마지막 칸이 시·군이라 앞으로 더 가야 한다.
    for part in reversed(re.split(r"[_/\\|]+", text)):
        key = part.strip().lower().replace(" ", "")
        if key in _COUNTRY:
            return _COUNTRY[key]
    key = text.lower().replace(" ", "")
    return _COUNTRY.get(key)


def page_origin(*parts: str | None) -> str | None:
    """상세페이지 본문에서 제조국 표기를 찾아 나라 이름으로.

    ⚠ **여러 개면 하나로 모을 수 없으면 None 이다.** 상세페이지에 '제조국:
      중국' 과 '원산지: 대한민국' 이 같이 오는 경우가 있다(세트 상품·부속품).
      그때 하나를 골라 정부 DB 와 비교하면 우리가 고른 쪽을 답으로 만드는
      것이고, 그건 판정이다 (R1).
    """
    found: set[str] = set()
    for text in parts:
        if not text:
            continue
        for m in _LABEL.finditer(text):
            c = normalize_country(m.group("value"))
            if c:
                found.add(c)
    return found.pop() if len(found) == 1 else None
