"""4-e. `category=out_of_scope` 라도 등급표는 조회한다 — 단 `legal` 폴백은 끈다.

도매꾹 고시 `type`(주방용품 등)이 추출기의 `category` 를 `out_of_scope` 로
밀어내는 일이 있고, **고시 품목분류와 전안법 품목군은 다른 분류다.** 실측:

    [165] 일회용 방수 미술 물감 앞치마+팔토시   고시 type=주방용품
          상품명만 조건 → children_textile · '앞치마' 등급 + 유해물질 규칙 15건
          상세 조건     → category=out_of_scope · 게이트에 막혀 **전부 사라짐**
    [146] 무독성 사계절 다용도 방수매트 김장매트  같은 모양

⚠ 게이트를 그냥 열면 **비대상에 등급이 붙는다.** 실측: GPT 가
  `커피머신클리너 세정제` 의 `legal_item_name` 을 `커피메이커` 로 뽑았고,
  `lookup_legal_name` 의 확장 폴백이 그것을 표의 `커피메이커` 로 넓힌다
  (비대상 부착 0 → 1). 그래서 폴백만 끈다.

  추출기가 "다른 소관" 이라고 본 상품에서 LLM 의 법령 품목 답을 표에 맞춰
  넓히는 것은 **두 신호가 서로 반대인데 넓히는 쪽을 택하는 것**이고 R3 방향이
  아니다.
"""
from __future__ import annotations

from datetime import date

from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import ItemCategory, ProductFacts
from sourcing_guard.verifier import RuleBook, verify

_KATS = KatsClient(None, None, mock=True)
_RULES = RuleBook()


def _items(facts: ProductFacts) -> list[str]:
    findings = verify(facts, _KATS, _RULES, None)
    return [c["item"] for f in findings
            for c in (f.detail or {}).get("candidates", [])]


def test_the_product_name_path_is_open_even_when_the_extractor_says_out_of_scope():
    """[165] 재현. 상품명으로 표에서 찾은 것은 버리지 않는다."""
    facts = ProductFacts(
        product_name="일회용 방수 미술 물감 앞치마+팔토시(2개) 세트",
        category=ItemCategory.OUT_OF_SCOPE,
    )
    assert _items(facts), "상품명 경로가 막혀 있다 - [165] 가 그대로다"


def test_the_legal_name_fallback_is_closed_when_the_extractor_says_out_of_scope():
    """[커피머신클리너] 재현. 오부착 1건의 출처가 이 폴백이다."""
    cleaner = "커피머신클리너 세정제 세척 석회질제거 청소 석회제거제 세제"

    # 폴백이 살아 있으면 '커피메이커' 가 붙는다 - 다른 category 로 확인한다.
    open_fallback = ProductFacts(
        product_name=cleaner, legal_item_name="커피메이커",
        category=ItemCategory.ELECTRICAL,
    )
    assert "커피메이커" in _items(open_fallback), (
        "이 검사의 전제가 바뀌었다 - 폴백이 원래 무엇을 하는지 확인할 것"
    )

    # out_of_scope 에서는 같은 입력이 아무것도 붙지 않는다.
    closed = ProductFacts(
        product_name=cleaner, legal_item_name="커피메이커",
        category=ItemCategory.OUT_OF_SCOPE,
    )
    assert _items(closed) == [], "비대상에 등급이 붙는다"


def test_the_fallback_still_works_for_every_other_category():
    """폴백을 통째로 끈 것이 아니다. out_of_scope 에서만 끈다."""
    for cat in (ItemCategory.ELECTRICAL, ItemCategory.UNCLASSIFIED):
        facts = ProductFacts(
            product_name="코웨이 정수기 렌탈 냉온정",
            legal_item_name="전기정수기",
            category=cat,
        )
        assert "전기정수기" in _items(facts), cat


def test_the_stale_comment_cases_do_not_reproduce():
    """옛 주석이 이 게이트의 오답 사례로 든 둘이 실제로는 안 붙는다.

    ⚠ 낡은 근거를 그대로 두면 다음 사람이 그것을 믿는다. 그래서 코드 주석에
      적고 여기서 잠근다 - 재현되면 이 검사가 깨지고 그때 다시 판단한다.
    """
    for name in (
        "한모금컵 두모금컵 세모금컵 500매 정수기컵 미니컵 생수컵 일회용컵",
        "목발형 접이식 보행기 깁스 보조 지팡이 이동",
    ):
        facts = ProductFacts(product_name=name,
                             category=ItemCategory.OUT_OF_SCOPE)
        assert _items(facts) == [], name


def test_the_grade_lookup_is_local_so_the_probe_costs_no_network():
    """(0)에서 미리 보는 것이 네트워크를 쓰지 않는지.

    `verify()` 가 소관 단독 판정을 위해 등급표를 미리 조회한다(4-d-1). 그것이
    네트워크를 쓰면 타 소관 상품마다 헛호출이 난다.
    """
    from sourcing_guard.verifier import _item_grade_findings

    # kats·recalls·rra 를 아예 넘기지 않고도 돈다.
    found = _item_grade_findings("전기오븐", date(2026, 9, 8))
    assert isinstance(found, list)
