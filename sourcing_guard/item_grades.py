"""품목 등급 조회. "이 품목이 안전인증 대상인가" 를 답한다.

인증번호 부재의 의미는 등급에 따라 완전히 다르다 - 안전인증·안전확인 대상이면
번호가 있어야 하고, 공급자적합성확인 대상이면 없는 것이 정상이다 (CLAUDE.md
R3-b). 그동안 이걸 몰라서 전부 kc_tier_unknown 으로 내보냈다.

매칭 순서는 (1) 수식어 제거 (2) 별칭 사전 (3) 정확 일치다.

⚠ 어절 매칭은 쓰지 않는다. 'LED 5W 초소형 펜라이트' 를 어절로 맞추면 'LED'
  하나로 LED등기구(안전인증)에 붙는데, 정답은 충전식 휴대전등(안전확인)이라
  등급이 뒤집힌다. 리콜 매칭에서 '153' 이 볼펜과 LED 전등을 잇던 것과 같은
  뿌리다 - 짧고 흔한 토큰은 식별력이 없다.

⚠ 별칭 키도 같은 기준을 따른다. 2~3글자 흔한 단어를 키로 쓰지 않는다
  ('LED' '전등' '가방'). 테스트가 이를 강제한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

_PATH = Path(__file__).parent / "data" / "item_grades.yaml"

# 상품명에 붙지만 품목을 가리지 않는 말. 떼고 나서 별칭 사전을 본다.
#
# 이걸 먼저 해야 사전이 쓸데없이 커지지 않는다 - 'LED 5W 초소형 펜라이트' 를
# 통째로 키에 넣으면 '휴대용 LED 펜라이트' 는 또 못 맞춘다.
_MODIFIERS = (
    # 크기·형태
    "초소형", "소형", "대형", "중형", "미니", "슬림", "컴팩트", "휴대용", "휴대",
    "접이식", "폴딩", "원터치", "자동", "수동", "무선", "유선", "충전식", "건전지식",
    # 마케팅
    "프리미엄", "고급", "정품", "신상", "특가", "세트", "세트상품", "1+1",
    "다용도", "가정용", "업소용", "산업용", "실내용", "실외용", "야외용",
)

# 규격 표기. 5W · 220V · 3.5mm · 12색 · 100매 같은 것.
_SPEC = re.compile(
    r"\b\d+(?:\.\d+)?\s*"
    r"(?:W|kW|V|kV|A|mA|Hz|kHz|mm|cm|m|kg|g|ml|L|㎸A|kVA|인치|색|매|구|단|개|피스|P)\b",
    re.IGNORECASE,
)


def strip_modifiers(name: str) -> str:
    """상품명에서 수식어와 규격 표기를 뗀다.

    'LED 5W 초소형 펜라이트' -> 'LED 펜라이트'
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name)
    s = _SPEC.sub(" ", s)
    for word in _MODIFIERS:
        s = s.replace(word, " ")
    return re.sub(r"\s+", " ", s).strip()


def normalize(name: str) -> str:
    """비교용 정규화. 공백·기호를 지우고 대문자로."""
    s = unicodedata.normalize("NFKC", name or "").upper()
    return re.sub(r"[^0-9A-Z가-힣]", "", s)


# 셀러 어휘 -> 법령 어휘.
#
# ⚠ 작게 유지한다. 564건 전부에 별칭을 붙이려 하면 대부분 쓰이지 않는 항목에
#   시간을 쓴다. 골든셋·데모에 나오는 것부터 시작하고 실제 상품을 넣어보며 늘린다.
#
# ⚠ 키는 4글자 이상이거나, 짧더라도 그 도메인에서만 쓰이는 말이어야 한다.
#   'LED' 나 '전등' 같은 짧고 흔한 키를 넣으면 등급이 뒤집힌다.
ALIASES: dict[str, str] = {
    # 조명 - 손에 드는 것과 천장에 다는 것은 등급이 다르다
    "펜라이트": "충전식 휴대전등",
    "손전등": "충전식 휴대전등",
    "플래시라이트": "충전식 휴대전등",
    "후레쉬": "충전식 휴대전등",
    # 음향
    "이어폰": "무선 헤드셋",
    "무선이어폰": "무선 헤드셋",
    "블루투스이어폰": "무선 헤드셋",
    # 전원
    "충전기": "직류전원장치",
    "어댑터": "직류전원장치",
    "전원어댑터": "직류전원장치",
}


@dataclass(frozen=True)
class ItemGrade:
    item: str
    grade: str
    category: str
    division: str
    scope_note: str
    source: str
    matched_by: str          # exact | alias


class ItemGradeBook:
    """세부품목 등급표."""

    def __init__(self, path: Path | None = None) -> None:
        raw = yaml.safe_load((path or _PATH).read_text(encoding="utf-8"))
        self._rows = raw["items"]
        self._by_name: dict[str, dict] = {}
        for row in self._rows:
            self._by_name.setdefault(normalize(row["item"]), row)

    def __len__(self) -> int:
        return len(self._rows)

    def lookup(self, product_name: str | None) -> ItemGrade | None:
        """상품명으로 세부품목을 찾는다. 못 찾으면 None.

        못 찾는 것을 억지로 맞추지 않는다 - 틀린 등급을 말하는 것보다 모른다고
        하는 편이 낫다 (R3). 호출부는 None 을 받으면 품목군까지만 안내한다.
        """
        if not product_name:
            return None

        stripped = strip_modifiers(product_name)
        for candidate, how in ((product_name, "exact"), (stripped, "exact")):
            row = self._by_name.get(normalize(candidate))
            if row:
                return self._to_grade(row, how)

        # 별칭. 상품명(수식어 제거본)에 키가 들어 있으면 그 법령 어휘로 바꾼다.
        target = normalize(stripped or product_name)
        for key, legal in ALIASES.items():
            if normalize(key) in target:
                row = self._by_name.get(normalize(legal))
                if row:
                    return self._to_grade(row, "alias")
        return None

    @staticmethod
    def _to_grade(row: dict, how: str) -> ItemGrade:
        return ItemGrade(
            item=row["item"],
            grade=row["grade"],
            category=row["category"],
            division=row.get("division", ""),
            scope_note=row.get("scope_note", ""),
            source=row["source"],
            matched_by=how,
        )
