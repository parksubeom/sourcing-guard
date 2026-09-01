"""품목 범위와 연령 표기 해석.

두 가지를 판별한다. 둘 다 "어떤 기준을 적용할지" 를 정하는 스위치이고,
지금까지 추출만 되고 아무 판단에도 쓰이지 않았다.

1. 이 품목이 우리 소관인가 (`ItemCategory.OUT_OF_SCOPE`)
   "우리가 판별 못 함" 과 "우리 소관이 아님" 은 다르다. 셀러에게는 후자가
   훨씬 유용하다. 어린이제품 공통안전기준 1항이 제외 대상을 명시한다.

2. 어린이제품 대상 연령인가 (`AgeScope`)
   공통안전기준은 **만 13세 이하**에 적용된다. 이 한 줄이 규칙 DB 전체를
   적용할지 말지를 가른다.

주된 용도가 완구가 아니면(액세서리·문구·생활용품에 캐릭터·인형이 붙은 형태)
완구로 단정하지 않는다. 대상 고객이 어린이로 명시된 경우에만 완구 기준을
안내한다. 우리는 품목을 판정하지 않고, 판정에 필요한 정보가 없으면 그 사실을
말한다 (CLAUDE.md R1, R3).
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum

from .models import ItemCategory

# 공통안전기준 1항 — 적용 대상에서 제외되는 물품. 다른 부처 소관이거나
# 별도 법령 체계를 따른다. 값은 (표시 사유, 판별 힌트) 순.
OUT_OF_SCOPE_HINTS: dict[str, tuple[str, ...]] = {
    "식품 (식품위생법 / 식약처 소관)": (
        "커피", "원두", "드립백", "차", "티백", "과자", "젤리", "음료", "식품",
        "소금", "죽염", "후추", "향신료", "설탕",
        "coffee", "arabica", "食品", "咖啡",
    ),
    "화장품 (화장품법 / 식약처 소관)": (
        "화장품", "스킨", "토너", "로션", "에센스", "크림", "앰플", "세럼",
        "마스크팩", "클렌징", "클렌징폼", "립스틱", "선크림",
        "ewg", "화장품책임판매업자", "화장품제조업자",
        "cosmetic", "化妆品",
    ),
    "의약품·의약외품 (약사법 / 식약처 소관)": (
        "의약품", "의약외품", "영양제", "비타민", "medicine", "药品",
    ),
    "의료기기 (의료기기법 / 식약처 소관)": (
        "의료기기", "혈압계", "체온계", "medical device", "医疗器械",
    ),
    "식품용 기구·용기·포장 (식품위생법)": (
        "식품용기", "밀폐용기", "도시락통", "젖병",
    ),
}

# 공통안전기준 적용 상한. 만 13세 이하.
CHILD_AGE_MAX = 13


class AgeScope(str, Enum):
    CHILD_PRODUCT = "child_product"            # 만 13세 이하 대상
    DECLARED_NOT_CHILD = "declared_not_child"  # 14세 이상으로 표기됨
    UNKNOWN = "unknown"                         # 표기 없음 또는 해석 실패

    @property
    def label_ko(self) -> str:
        return {
            "child_product": "어린이제품 대상 연령",
            "declared_not_child": "어린이제품 대상 아님(표기 기준)",
            "unknown": "연령 표기 없음",
        }[self.value]


_MONTHS = re.compile(r"(\d+)\s*(?:개월|个月|months?)")
_YEARS = re.compile(r"(?:만\s*)?(\d+)\s*(?:세|살|歳|岁|years?)")


def classify_age(raw: str | None) -> AgeScope:
    """사용연령 표기를 해석한다.

    도매 페이지는 "만 14세 이상", "36개월 미만", "3세~6세" 처럼 제각각이다.
    표기가 없으면 UNKNOWN 이다. 어린이제품이 아니라고 추측하지 않는다 (R3).
    """
    if not raw or not raw.strip():
        return AgeScope.UNKNOWN

    s = unicodedata.normalize("NFKC", raw).lower()

    if _MONTHS.search(s):  # 개월 표기는 전부 어린이제품 범위 안이다.
        return AgeScope.CHILD_PRODUCT

    years = [int(m) for m in _YEARS.findall(s)]
    if not years:
        return AgeScope.UNKNOWN

    lower_bound = min(years)
    if "이상" in s or "+" in s or "over" in s:
        return (
            AgeScope.DECLARED_NOT_CHILD
            if lower_bound > CHILD_AGE_MAX
            else AgeScope.CHILD_PRODUCT
        )
    return AgeScope.CHILD_PRODUCT if lower_bound <= CHILD_AGE_MAX else AgeScope.DECLARED_NOT_CHILD


def out_of_scope_reason(*parts: str | None) -> str | None:
    """제품명·본문에서 우리 소관 밖임이 드러나면 그 사유를 돌려준다."""
    haystack = " ".join(p for p in parts if p).lower()
    if not haystack:
        return None
    for reason, hints in OUT_OF_SCOPE_HINTS.items():
        if any(h.lower() in haystack for h in hints):
            return reason
    return None


CHILDREN_CATEGORIES = {
    ItemCategory.CHILDREN_TOY,
    ItemCategory.CHILDREN_STATIONERY,
    ItemCategory.CHILDREN_TEXTILE,
}


def missing_inputs(
    *, materials: list[str], target_age: str | None, category: ItemCategory
) -> list[tuple[str, str]]:
    """판정에 필요한데 페이지에 없는 정보와, 공급처에 물을 문구.

    "모르겠습니다" 로 끝내지 않고 무엇을 물어야 하는지까지 준다. 소싱 단계에서
    셀러가 실제로 할 수 있는 행동은 공급처에 묻는 것뿐이다.
    """
    gaps: list[tuple[str, str]] = []
    if not materials:
        gaps.append((
            "재질",
            "재질(합성수지 종류, 도장·코팅 유무)을 확인해 주세요. "
            "합성수지제는 프탈레이트 기준이, 도장면은 유해원소 용출 기준이 적용됩니다.",
        ))
    if not target_age or not target_age.strip():
        gaps.append((
            "대상연령",
            "대상연령(또는 권장 사용연령) 표기를 확인해 주세요. "
            "만 13세 이하이면 어린이제품 공통안전기준이 적용됩니다.",
        ))
    if category is ItemCategory.UNCLASSIFIED:
        gaps.append((
            "품목 구분",
            "어떤 안전기준 품목에 해당하는지 확인해 주세요. "
            "안전인증·안전확인·공급자적합성확인 중 어디인지에 따라 의무가 달라집니다.",
        ))
    return gaps
