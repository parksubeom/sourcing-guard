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

from dataclasses import dataclass

import re
import unicodedata
from enum import Enum

from .models import ItemCategory

# 공통안전기준 1항 — 적용 대상에서 제외되는 물품. 다른 부처 소관이거나
# 별도 법령 체계를 따른다. 값은 (표시 사유, 판별 힌트) 순.
OUT_OF_SCOPE_HINTS: dict[str, tuple[str, ...]] = {
    # ⚠ 한두 글자 일반 명사를 넣지 않는다. 한국어 부분 문자열 매칭에는 단어
    #   경계가 없어서 "차" 가 기차놀이·자동차·유아차에, "크림" 이 아이스크림·
    #   크림색에 걸린다. OUT_OF_SCOPE 는 인증·리콜 검증을 통째로 건너뛰므로
    #   오탐 하나가 리콜된 완구를 놓치게 만든다 — 실제로 겪었다. 데모용
    #   '모형완구 기차놀이' 가 "차" 때문에 식품으로 판정돼 RED 가 사라졌다.
    #
    #   남기는 기준: 그 도메인에서만 쓰이는 표기이거나, 다른 품목 이름에
    #   섞일 여지가 없을 만큼 긴 복합어.
    "식품 (식품위생법 / 식약처 소관)": (
        "드립백", "티백", "식품위생법", "건강기능식품", "죽염", "천일염",
        "향신료", "원두커피", "인스턴트커피", "통후추",
        "arabica", "食品",
    ),
    "화장품 (화장품법 / 식약처 소관)": (
        "화장품", "마스크팩", "클렌징폼", "클렌징오일", "립스틱", "선크림",
        "ewg", "화장품책임판매업자", "화장품제조업자", "기능성화장품",
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


# 소관 안이라는 적극적 증거. 소관 밖 힌트가 함께 걸려도 단락하지 않는다 —
# 힌트를 걷어낸 뒤에도 남을 오탐에 대한 안전망이다.
IN_SCOPE_MARKERS = ("완구", "장난감", "어린이", "유아", "아동", "학용품", "toy")


def out_of_scope_reason(*parts: str | None) -> str | None:
    """제품명·본문에서 우리 소관 밖임이 드러나면 그 사유를 돌려준다.

    소관 안이라는 적극적 증거(완구·어린이 등)가 있으면 판정하지 않는다.
    OUT_OF_SCOPE 는 인증·리콜 검증을 통째로 건너뛰므로, 애매하면 검증하는
    쪽이 안전하다. 놓친 리콜이 불필요한 안내보다 비싸다 (CLAUDE.md R6).
    """
    haystack = " ".join(p for p in parts if p).lower()
    if not haystack:
        return None
    if any(m in haystack for m in IN_SCOPE_MARKERS):
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


@dataclass(frozen=True)
class MissingInput:
    """"무엇을 넣으면 무엇이 가능해지는가" (4-s · 2026-09-11).

    ⚠⚠ **화면이 여러 줄을 합쳐 한 줄로 그릴 수 있어야 한다.**

      실측(새표본235): `info_request` 가 **228/235 행**에 붙고 한 행에 **3~4줄**
      이 쌓인다. 셀러가 매번 같은 안내를 보면 안 읽고, 그러면 진짜 안내도 같이
      안 읽힌다 - R3-b 가 금지한 "항상 켜지는 경고" 와 같은 구조다.

      축마다 한 줄씩 쌓지 말고 화면이 이렇게 합칠 수 있게 한다:

          모델명·제조사를 넣으면 리콜 대조와 인증 조회가 가능합니다

    ⚠ **줄을 줄이려고 안내를 없애지 않는다. 합치는 것과 감추는 것은 다르다.**
      문구(`ask`)는 그대로 두고 구조만 얹는다 - 화면이 합칠지 펼칠지 고른다.

    필드
        label     화면 머리말. 기존 문구가 쓰던 것
        ask       공급처에 물을 말. 그대로 유지한다
        asks_for  **셀러가 넣을 것.** `ProductFacts` 필드명을 쓴다
        unlocks   **그것이 열어 주는 축.** 화면이 "무엇이 가능해지는지" 를 말한다
    """

    label: str
    ask: str
    asks_for: tuple[str, ...]
    unlocks: tuple[str, ...]

    def as_detail(self) -> dict:
        """`Finding.detail` 에 담을 모양. 화면이 이것을 읽어 합친다."""
        return {
            "missing": self.label,
            "asks_for": list(self.asks_for),
            "unlocks": list(self.unlocks),
        }


#: 축 이름. 화면 문구는 화면이 정하고 여기서는 **식별자만** 준다.
#: ⚠ 값을 늘리면 화면이 모르는 축이 생긴다 - 화면과 함께 늘릴 것.
#:
#: ⚠ **굵기는 지금 정하지 않는다** (2026-09-11 판정). 넷으로 나눈 것이 화면이
#:   원하는 단위인지는 화면을 만들어 봐야 안다 - 화면 없이 정하면 또 갈린다.
#:   주말 묶음에서 조정한다.
#:
#: ⚠⚠ **`cert_lookup` 을 여는 `info_request` 는 만들지 않는다** (2026-09-11 판정).
#:
#:   인증번호가 없는 것은 두 가지다:
#:     (가) 셀러가 안 적었다
#:     (나) **그 등급은 번호가 없는 것이 정상이다** (공급자적합성확인·안전기준준수)
#:
#:   (나)에 "인증번호를 넣으세요" 를 띄우면 **없는 의무를 만든다** - R3-b 가
#:   막으려는 그것이다. 실제로 그 경우는 `kc_absence_expected` 가 "부재가
#:   정상" 이라고 말하고 있다.
#:
#:   번호가 **필요한** 등급(안전인증·안전확인)으로 확정됐는데 번호가 없는
#:   경우에만 물을 수 있는데, 그 경우는 이미 `kc_missing_but_required` 가
#:   말한다. 그래서 이 축은 **열 자리가 없다.**
#:
#:   ⚠ 식별자는 남겨 둔다 - 화면이 다른 맥락에서 쓸 수 있고, 지우면 다음
#:     사람이 "왜 인증 축만 없나" 를 다시 묻는다.
UNLOCKABLE_AXES = ("recall_match", "cert_lookup", "hazard_rule", "item_grade")


def missing_inputs(
    *, materials: list[str], target_age: str | None, category: ItemCategory
) -> list[MissingInput]:
    """판정에 필요한데 페이지에 없는 정보와, 공급처에 물을 문구.

    "모르겠습니다" 로 끝내지 않고 무엇을 물어야 하는지까지 준다. 소싱 단계에서
    셀러가 실제로 할 수 있는 행동은 공급처에 묻는 것뿐이다.

    ⚠ 반환형이 `tuple[str, str]` 에서 `MissingInput` 으로 바뀌었다 (4-s).
      이유는 위 클래스 주석 참조.
    """
    gaps: list[MissingInput] = []
    if not materials:
        gaps.append(MissingInput(
            label="재질",
            ask="재질(합성수지 종류, 도장·코팅 유무)을 확인해 주세요. "
                "합성수지제는 프탈레이트 기준이, 도장면은 유해원소 용출 기준이 적용됩니다.",
            asks_for=("materials",),
            unlocks=("hazard_rule",),
        ))
    if not target_age or not target_age.strip():
        gaps.append(MissingInput(
            label="대상연령",
            ask="대상연령(또는 권장 사용연령) 표기를 확인해 주세요. "
                "만 13세 이하이면 어린이제품 공통안전기준이 적용됩니다.",
            asks_for=("target_age",),
            # 연령이 정해져야 어린이제품 기준 적용 여부가 정해지고, 그것이
            # 등급·유해물질 양쪽을 가른다.
            unlocks=("item_grade", "hazard_rule"),
        ))
    if category is ItemCategory.UNCLASSIFIED:
        gaps.append(MissingInput(
            label="품목 구분",
            ask="어떤 안전기준 품목에 해당하는지 확인해 주세요. "
                "안전인증·안전확인·공급자적합성확인 중 어디인지에 따라 의무가 달라집니다.",
            asks_for=("legal_item_name",),
            unlocks=("item_grade",),
        ))
    return gaps
