"""매처 - 후보가 실제로 이 상품을 가리키는지 판정한다.

품목 매칭은 두 단계다. 쿠팡이 카탈로그 중복 상품을 찾을 때 쓰는 구조와 같다:
후보를 넓게 찾고(재현율), 그중 참인 것을 가린다(정밀도).

    1단계  검색   표의 이름이 상품명 안에 있는가 -> 후보 목록
    2단계  매처   각 후보가 정말 이 상품을 가리키는가 -> 참/거짓 + 신뢰도

우리에게 2단계가 없었다. `lookup_all` 이 후보를 뽑으면 첫 번째를 그대로 썼고,
그래서 "안전모 햇빛가리개" 가 안전모로, "고데기 거치대" 가 전기머리인두로
붙었다. 부속어 가드가 원시적인 매처 역할을 했지만 규칙 몇 개로 흩어져 있어,
왜 그렇게 판정했는지 남지 않고 새 신호를 더하기도 어려웠다.

**신호를 한곳에 모으고, 각 신호가 무엇을 근거로 어떻게 판정했는지 남긴다.**
그래야 오답을 볼 때 어느 신호가 잘못 걸렸는지 짚을 수 있다 - 이번 세션에서
오답을 잡아온 방식이 정확히 그것이다.

⚠ 매처는 **거부하는 쪽으로만** 강하다. 참을 만들어내지 않는다. 신호가 없으면
   1단계 결과를 그대로 통과시킨다. 근거 없이 매칭을 늘리면 등급이 뒤집히고,
   그것이 셀러를 위법 상태로 보낸다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Confidence(str, Enum):
    """후보를 얼마나 믿는가.

    지금까지 매칭/미매칭 이분법이었다. 그러면 "안전모인 건 알지만 어느 안전모인지
    모른다" 를 표현할 수 없어, 아는 것까지 버리게 된다.
    """

    CERTAIN = "certain"    # 표의 이름과 그대로 같다
    LIKELY = "likely"      # 표의 이름이 상품명 안에 온전히 있다
    POSSIBLE = "possible"  # 우리가 만든 별칭·접두 확장으로 이었다
    REJECTED = "rejected"  # 신호가 이 후보를 거부했다


# 매칭 경로별 기본 신뢰도. 표는 법령 원문이고 별칭은 우리 추정이라 층이 다르다.
_BASE: dict[str, Confidence] = {
    "exact": Confidence.CERTAIN,
    "contains": Confidence.LIKELY,
    "expand": Confidence.POSSIBLE,
    "alias": Confidence.POSSIBLE,
}


@dataclass
class Signal:
    """매처가 본 신호 하나. 왜 그렇게 판정했는지가 여기 남는다."""

    name: str
    rejects: bool
    detail: str


@dataclass
class Judgement:
    confidence: Confidence
    signals: list[Signal] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.confidence is not Confidence.REJECTED

    @property
    def reason(self) -> str:
        """거부됐으면 그 이유. 통과했으면 무엇으로 이었는지."""
        for s in self.signals:
            if s.rejects:
                return s.detail
        return self.signals[0].detail if self.signals else ""


# 구성품·수량 표기. 쿠팡 매칭 가이드가 "구성품·수량이 다르면 다른 상품" 이라고
# 적고 있고, 실측에서도 그렇다 - "전동칫솔 칫솔헤드 리필팩 4EA" 는 칫솔이
# 아니라 소모품이다.
#
# ⚠ 수량 표기만으로 거부하지 않는다. "선풍기 2개입" 은 선풍기가 맞다.
#   부속·소모품 신호와 **함께 나올 때만** 무게를 싣는다.
_CONSUMABLE_WORDS = ("리필", "교체용", "소모품", "여분", "예비")


# 같은 일을 하는 화학제와 전기기기. 표에는 전기 쪽만 있어서, 화학제가 그
# 품목으로 붙으면 안전인증 대상이 아닌 상품에 의무를 말하게 된다.
#
# '제습제 vs 제습기' 는 접미 한 글자라 chemical_variant_dominates 가 잡는다.
# 이건 낱말이 아예 달라서 따로 적어야 한다.
#
# 실측(도매꾹 239건): '손난로'·'핫팩' 이 나오는 상품 8건 중
#   전기 신호(충전·USB·mAh)가 있는 6건 → 전기손난로가 맞다
#   없는 2건 → "흔드는핫팩 80g 200개", "군용 흔드는 핫팩" = 화학 발열체
# 전기 신호로 정확히 갈렸다.
#
# ⚠ 화학제 낱말이 있다고 거부하지 않는다. 충전식 손난로가 '핫팩' 을 연관
#   검색어로 달고 파는 것이 도매의 전형이다 - 실측 6건이 그랬다.
#   **전기 신호가 하나도 없을 때만** 화학제로 본다.
_CHEMICAL_RIVALS: dict[str, tuple[str, ...]] = {
    # 표의 품목(정규화) -> 그 자리를 차지하는 화학제 낱말
    "전기손난로": ("핫팩", "발열팩", "찜질팩"),
}

# 전기 제품임을 드러내는 표기. 하나라도 있으면 화학제로 보지 않는다.
_ELECTRIC_HINTS = ("충전", "usb", "전기", "리튬", "mah", "ma", "배터리", "전원")


def chemical_rival_wins(raw_name: str, item_name: str) -> bool:
    """표의 전기 품목 자리에 화학제가 있는가.

    원문(정규화 전)에서 본다 - 'mAh' 같은 표기가 정규화로 뭉개지면
    전기 신호를 놓친다.
    """
    words = _CHEMICAL_RIVALS.get(item_name.replace(" ", ""))
    if not words:
        return False
    low = raw_name.lower()
    if not any(w in raw_name for w in words):
        return False
    return not any(h in low for h in _ELECTRIC_HINTS)


def judge(
    *,
    normalized_name: str,
    normalized_key: str,
    matched_by: str,
    names_subject: bool,
    chemical_dominates: bool,
    consumable_hint: bool = False,
    chemical_rival: bool = False,
) -> Judgement:
    """후보 하나를 판정한다.

    호출측(ItemGradeBook)이 이미 계산한 신호를 받는다 - 매처가 정규화 규칙을
    다시 알 필요가 없고, 신호를 더할 때 이 함수의 서명만 늘리면 된다.
    """
    signals: list[Signal] = []

    # (1) 본체를 가리키는가. 부속어·부정어가 키 뒤에 붙으면 본체가 아니다.
    if not names_subject:
        signals.append(Signal(
            "accessory_or_negated", True,
            f"'{normalized_key}' 가 부속품·부정 표현으로만 나옵니다.",
        ))

    # (2) 화학제인가 기기인가. '제습제' 는 '제습기' 가 아니다.
    if chemical_dominates:
        signals.append(Signal(
            "chemical_variant", True,
            f"'{normalized_key[:-1]}제'(화학제)가 더 자주 나옵니다. 기기가 아닙니다.",
        ))

    # (2b) 같은 일을 하는 화학제. '핫팩' 은 '전기손난로' 가 아니다.
    #      낱말이 아예 달라 (2) 의 접미 규칙으로는 안 잡힌다.
    if chemical_rival:
        signals.append(Signal(
            "chemical_rival", True,
            "화학 발열체 표기만 있고 전기 표기가 없습니다. 전기기기가 아닙니다.",
        ))

    # (3) 소모품 표기. 단독으로는 거부하지 않고, 본체 신호가 이미 약할 때만
    #     무게를 싣는다 - "선풍기 2개입" 은 선풍기가 맞다.
    if consumable_hint and not names_subject:
        signals.append(Signal(
            "consumable", True, "소모품·교체용 표기가 있습니다.",
        ))

    if any(s.rejects for s in signals):
        return Judgement(Confidence.REJECTED, signals)

    base = _BASE.get(matched_by, Confidence.POSSIBLE)
    signals.append(Signal(
        "matched_by", False,
        {
            Confidence.CERTAIN: "표의 품목명과 그대로 일치합니다.",
            Confidence.LIKELY: "표의 품목명이 상품명에 그대로 들어 있습니다.",
            Confidence.POSSIBLE: "별칭·접두 확장으로 이었습니다.",
        }[base],
    ))
    return Judgement(base, signals)


def has_consumable_hint(raw_name: str) -> bool:
    """소모품·교체용 표기가 있는가. 정규화 전 원문에서 본다."""
    return any(w in raw_name for w in _CONSUMABLE_WORDS)


def summarize(judgements: list[Judgement]) -> Confidence:
    """살아남은 후보들의 신뢰도 중 가장 높은 것.

    후보가 여럿이면 셀러에게 후보를 다 보여주되(R3), 화면 문구의 강도는 가장
    확실한 후보를 따른다.
    """
    order = [Confidence.CERTAIN, Confidence.LIKELY, Confidence.POSSIBLE]
    alive = [j.confidence for j in judgements if j.accepted]
    for level in order:
        if level in alive:
            return level
    return Confidence.REJECTED
