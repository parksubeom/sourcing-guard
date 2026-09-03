"""품목 등급 조회. "이 품목이 안전인증 대상인가" 를 답한다.

인증번호 부재의 의미는 등급에 따라 완전히 다르다 - 안전인증·안전확인 대상이면
번호가 있어야 하고, 공급자적합성확인 대상이면 없는 것이 정상이다 (CLAUDE.md
R3-b). 그동안 이걸 몰라서 전부 kc_tier_unknown 으로 내보냈다.

매칭 순서는 (1) 수식어 제거 (2) 정확 일치 (3) 별칭 (4) 접두 확장 (5) 역방향 포함이다.

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

    ⚠ **어절 단위로만 뗀다.** 부분 문자열로 지우면 '자동' 이 '자동차용' 을
      파괴해서 '자동차용 타이어' 가 '차용 타이어' 가 되고, 그 결과 접두 확장이
      '승용차용 타이어' 로 잘못 붙는다 - 실제로 겪었다.

      한국어 부분 문자열 매칭에는 단어 경계가 없다. 이 세션에서 '차' 가
      '기차놀이' 를 식품으로 판정하게 만든 것과 같은 뿌리다.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name)
    s = _SPEC.sub(" ", s)
    kept = [tok for tok in s.split() if tok not in _MODIFIERS]
    return " ".join(kept).strip() or s.strip()


# 표가 '전기' · '전동' 을 붙이는 습관이 있다 - 전기토스터 · 전기프라이팬 ·
# 전기스탠드. 셀러는 그냥 토스터 · 프라이팬 · 스탠드라고 쓴다.
#
# 양방향으로 본다: 상품명에 붙여보고, 떼어보고. 이 규칙 하나가 별칭 여러 건을
# 대신한다 - 사전을 작게 유지하는 것이 목표다.
_PREFIXES = ("전기", "전동")


def prefix_variants(name: str) -> list[str]:
    """접두어를 붙이거나 뗀 변형들. 원본이 맨 앞이다."""
    out = [name]
    for p in _PREFIXES:
        if name.startswith(p):
            out.append(name[len(p):].strip())
        else:
            out.append(f"{p}{name}")
            out.append(f"{p} {name}")
    return [v for v in out if v]


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


# 역방향 포함 매칭(품목명이 상품명 안에 들어 있는가)에서 키로 쓰지 않는 말.
#
# "신일 BLDC 무선 선풍기 써큘레이터" 처럼 셀러는 브랜드·수식어를 앞뒤에 붙인다.
# 정확 일치만 보면 표에 '선풍기' 가 있어도 못 찾는다. 그래서 품목명이 상품명
# 안에 있는지도 본다 - 다만 아무 말이나 키로 쓰면 등급이 뒤집힌다.
#
# ⚠ 아래 단어들은 여러 품목에 공통으로 들어가 식별력이 없다. 'LED' 를 키로
#   쓰면 펜라이트가 LED등기구(안전인증)에 붙는데 정답은 충전식 휴대전등
#   (안전확인)이다. 리콜 매칭에서 '153' 이 볼펜과 LED 전등을 잇던 것과 같은
#   뿌리다 - 짧고 흔한 토큰은 식별력이 없다.
#
# ⚠ '의자' 는 2글자라 길이 규칙에도 걸리지만 명시해 둔다. 표에 전기이발용의자·
#   전기온열의자·각도조절의자가 따로 있어서, 일반 '의자' 로 붙이면 등급이
#   엉뚱한 항목으로 간다.
_WEAK_CONTAIN_KEYS = {
    "LED", "전지", "코드", "전선", "의자", "매트", "조명", "기구", "전기", "히터",
    "램프", "전등", "케이블", "배터리", "충전", "스위치", "기기", "장치", "용품",
}

# 포함 매칭 키의 최소 길이. 2글자는 우연 충돌이 심하다.
_MIN_CONTAIN_LEN = 3


def split_aliases(item: str) -> list[str]:
    """품목명 하나가 실은 여러 이름인 경우를 쪼갠다.

    표에 '백열등기구·전기스탠드' 처럼 가운뎃점으로 두 이름을 묶어 둔 항목이
    있다. 통째로만 키로 쓰면 셀러가 '고정형 백열등기구' 라고 쓸 때 못 찾는다.
    쪼개서 각각 키로 쓰면 느슨한 일치 없이 잡힌다 - 위험이 없다.

    괄호 안의 범위 한정은 이름이 아니므로 떼고 본다.
    """
    base = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", item)
    parts = [base] + re.split(r"[·ㆍ‧]", base)
    out: list[str] = []
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip(" ,")
        if name and name not in out:
            out.append(name)
    return out


def is_usable_contain_key(normalized: str) -> bool:
    """이 품목명을 '상품명 안에 있는가' 검사의 키로 쓸 수 있는가."""
    if len(normalized) < _MIN_CONTAIN_LEN:
        return False
    return normalized not in {normalize(w) for w in _WEAK_CONTAIN_KEYS}


def _is_subsequence(short: str, long: str) -> bool:
    """short 의 모든 글자가 long 에 순서대로 나타나는가."""
    it = iter(long)
    return all(ch in it for ch in short)


# 접두 확장에서 상품명 쪽이 가져야 하는 최소 길이. 짧으면 아무 데나 걸린다.
_MIN_EXPAND_LEN = 3

# 접두 확장에서 허용하는 최대 삽입 글자 수. 품목명이 상품명보다 이만큼까지만
# 길 수 있다. 너무 크게 두면 '보행차' 가 '보행자 안전 보조 손잡이차' 에 붙는다.
_MAX_EXPAND_GAP = 3


def is_prefix_expansion(query: str, item: str) -> bool:
    """상품명이 품목명의 '수식어 빠진 형태' 인가.

    표는 정식 명칭을 쓰고 셀러는 줄여 쓴다 - '고령자용 보행차' 와
    '고령자용 보행보조차' 는 같은 물건이다. 이 관계만 허용한다.

        허용   보행차   ⊂ 보행보조차     (글자가 순서대로 다 들어 있다)
               정수기   ⊂ 전기정수기
        금지   배터리팩   vs 노트북 컴퓨터  (관계 없음)
               스마트워치 vs 스마트폰      ('스마트' 만 겹치고 끝이 다르다)

    ⚠ 부분열(subsequence) 관계로 판단한다. 지시된 사례 7개로 검증했다 -
      '스마트워치' 는 '워치' 가 '스마트폰' 에 없어 걸리지 않고, '보행차' 는
      보/행/차가 '보행보조차' 에 순서대로 있어 걸린다.

    ⚠ 삽입 글자 수를 제한한다. 제한이 없으면 짧은 질의가 긴 품목명에 무조건
      부분열로 걸린다 - 리콜에서 '153' 이 아무 데나 걸리던 것과 같은 모양이다.
    """
    if len(query) < _MIN_EXPAND_LEN:
        return False
    if not (0 < len(item) - len(query) <= _MAX_EXPAND_GAP):
        return False
    return _is_subsequence(query, item)


@dataclass(frozen=True)
class ItemGrade:
    item: str
    grade: str
    category: str
    division: str
    scope_note: str
    source: str
    matched_by: str          # exact | alias | expand | contains


class ItemGradeBook:
    """세부품목 등급표."""

    def __init__(self, path: Path | None = None) -> None:
        raw = yaml.safe_load((path or _PATH).read_text(encoding="utf-8"))
        self._rows = raw["items"]
        self._by_name: dict[str, dict] = {}
        for row in self._rows:
            for name in split_aliases(row["item"]):
                self._by_name.setdefault(normalize(name), row)

        # 역방향 포함 매칭용. **긴 품목명이 먼저** 와야 한다 -
        # '자전거용 안전모' 가 '안전모' 보다 먼저 걸려야 등급이 정확해진다.
        keys: dict[str, dict] = {}
        for row in self._rows:
            for name in split_aliases(row["item"]):
                key = normalize(name)
                if is_usable_contain_key(key):
                    keys.setdefault(key, row)
        self._contain_keys: list[tuple[str, dict]] = sorted(
            keys.items(), key=lambda pair: -len(pair[0])
        )

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
        for base in (product_name, stripped):
            for candidate in prefix_variants(base):
                row = self._by_name.get(normalize(candidate))
                if row:
                    return self._to_grade(row, "exact")

        # 별칭. 상품명(수식어 제거본)에 키가 들어 있으면 그 법령 어휘로 바꾼다.
        target = normalize(stripped or product_name)
        for key, legal in ALIASES.items():
            if normalize(key) in target:
                row = self._by_name.get(normalize(legal))
                if row:
                    return self._to_grade(row, "alias")

        # 접두 확장. 상품명이 품목명의 수식어 빠진 형태인가.
        #
        # 포함 매칭보다 먼저 본다 - '냉온정수기' 는 '정수기' 로 줄면 '전기정수기'
        # 와 접두 확장 관계이고, 이게 포함 매칭보다 정확하다.
        for base in (stripped, product_name):
            nb = normalize(base)
            if not is_usable_contain_key(nb):
                continue
            for key, row in self._contain_keys:
                if is_prefix_expansion(nb, key):
                    return self._to_grade(row, "expand")

        # 역방향 포함. 품목명이 상품명 안에 들어 있는가.
        #
        # 셀러는 "신일 BLDC 무선 선풍기 써큘레이터" 처럼 브랜드와 수식어를
        # 붙인다. 표의 '선풍기' 가 그 안에 들어 있으면 찾아준다.
        #
        # 긴 것부터 본다 - '자전거용 안전모' 가 '안전모' 보다 먼저 걸려야 한다.
        # 키 자체의 식별력은 is_usable_contain_key 가 거른다.
        for key, row in self._contain_keys:
            if key in target:
                return self._to_grade(row, "contains")
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
