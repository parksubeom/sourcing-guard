"""품목 등급 조회 - "이 품목이 안전인증 대상인가".

인증번호 부재의 의미는 등급에 따라 완전히 다르다 (CLAUDE.md R3-b). 그동안
이걸 몰라서 전부 kc_tier_unknown 으로 내보냈다.

⚠ 이 파일의 핵심은 **어절 매칭을 쓰지 않는다**는 것이다. 'LED 5W 초소형
  펜라이트' 를 어절로 맞추면 'LED' 하나로 LED등기구(안전인증)에 붙는데,
  정답은 충전식 휴대전등(안전확인)이라 등급이 뒤집힌다. 리콜 매칭에서 '153'
  이 볼펜과 LED 전등을 잇던 것과 같은 뿌리다.
"""

import pytest

from sourcing_guard.item_grades import ALIASES, ItemGradeBook, normalize, strip_modifiers
from sourcing_guard.models import ItemCategory
from sourcing_guard.verifier import _tier_unknown_statement


@pytest.fixture(scope="module")
def book() -> ItemGradeBook:
    return ItemGradeBook()


# ---------------------------------------------------------------------------
# 표 자체
# ---------------------------------------------------------------------------


def test_table_covers_both_electrical_and_household(book):
    """전기용품만 넣었을 때 골든셋·데모 19건 중 3건만 대상이었다.

    휴지통·토트백·키링처럼 셀러가 실제로 소싱하는 것이 전부 생활용품이라
    빠졌다. 별표 4~7 을 받아 채웠다.
    """
    cats = {row["category"] for row in book._rows}
    assert cats == {"electrical", "household"}
    assert len(book) > 500


def test_scope_notes_survive(book):
    """직류전원장치의 '정격출력이 1 kVA 이하인 것에 한정' 을 빼면
    1kVA 초과 제품에 잘못된 등급을 말하게 된다."""
    g = book.lookup("직류전원장치")
    assert g is not None
    assert g.grade == "안전인증"
    assert "1 kVA 이하" in g.scope_note


def test_no_kc_standard_numbers_in_the_table(book):
    """KC 규격번호는 넣지 않는다.

    이 별표에 없기도 하고, 있더라도 셀러가 그 번호로 할 수 있는 일이 없다 -
    시험기관이 시험을 설계할 때 쓰는 규격 코드지 소싱 판단 정보가 아니다.
    """
    for row in book._rows:
        assert "kc_number" not in row
        assert not any(k.startswith("KC 6") for k in str(row.get("item", "")).split())


# ---------------------------------------------------------------------------
# (b) 수식어 제거 -> (a) 별칭. 이 순서여야 사전이 커지지 않는다.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,want",
    [
        ("LED 5W 초소형 펜라이트", "LED 펜라이트"),
        ("슬림 원터치 휴지통", "휴지통"),
        ("무선 이어폰", "이어폰"),
        ("휴대용 자바라 의자", "자바라 의자"),
    ],
)
def test_modifiers_and_specs_are_stripped(raw, want):
    assert strip_modifiers(raw) == want


def test_penlight_resolves_to_the_right_grade(book):
    """어절 매칭이 틀렸던 바로 그 건.

    'LED' 하나로 붙으면 LED등기구(안전인증)가 되는데, 펜라이트는 손에 드는
    것이라 충전식 휴대전등(안전확인)이다. 등급이 뒤집히면 셀러에게 "인증번호가
    있어야 한다" 고 잘못 말하게 된다.
    """
    g = book.lookup("LED 5W 초소형 펜라이트")
    assert g is not None
    assert g.item == "충전식 휴대전등"
    assert g.grade == "안전확인"
    assert g.matched_by == "alias"


def test_exact_match_still_works(book):
    g = book.lookup("승차용 안전모")
    assert g is not None and g.grade == "안전확인" and g.matched_by == "exact"


# ---------------------------------------------------------------------------
# 별칭 사전은 작고, 키는 식별력이 있어야 한다
# ---------------------------------------------------------------------------


def test_alias_keys_are_not_short_common_words():
    """짧고 흔한 토큰은 식별력이 없다.

    'LED' 나 '전등' 을 키로 넣으면 LED조명·LED램프·백열등기구가 전부 걸려
    등급이 뒤집힌다. 리콜 오탐에서 배운 기준을 그대로 적용한다.
    """
    banned = {"LED", "전등", "가방", "의자", "충전", "전기", "무선", "조명"}
    for key in ALIASES:
        assert normalize(key) not in {normalize(b) for b in banned}, f"흔한 키: {key}"
        assert len(normalize(key)) >= 3, f"너무 짧은 키: {key}"


def test_alias_dictionary_stays_small():
    """564건 전부에 별칭을 붙이려 하면 대부분 쓰이지 않는 항목에 시간을 쓴다.

    골든셋·데모에 나오는 것부터 시작하고 실제 상품을 넣어보며 늘린다.
    """
    assert len(ALIASES) <= 40, f"사전이 {len(ALIASES)}건까지 커졌다 - 실제로 쓰이는지 확인하라"


def test_alias_targets_exist_in_the_table(book):
    """사전이 표에 없는 법령 어휘를 가리키면 조용히 아무것도 안 한다."""
    for key, legal in ALIASES.items():
        assert book._by_name.get(normalize(legal)), f"{key} -> {legal} : 표에 없다"


# ---------------------------------------------------------------------------
# 못 맞추면 억지로 맞추지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["곰돌이 인형 키링 9종", "캔버스 토트백", "완구 매직액체 슬라임 장난감"])
def test_unmatched_products_return_none(book, name):
    """틀린 등급을 말하는 것보다 모른다고 하는 편이 낫다 (R3).

    키링·토트백은 실제로 이 표에 없다 - 안전관리 대상 품목이 아니다.
    """
    assert book.lookup(name) is None


# ---------------------------------------------------------------------------
# 세부품목을 못 맞춰도 품목군까지는 말한다
# ---------------------------------------------------------------------------


def test_tier_statement_names_the_grade_system_per_category():
    """"판별하지 못했습니다" 로 끝내면 셀러가 다음에 할 일이 없다."""
    elec = _tier_unknown_statement(ItemCategory.ELECTRICAL)
    assert "전기용품으로 보입니다" in elec
    assert "세 등급" in elec
    assert "공급처에 어느 등급인지 확인" in elec

    house = _tier_unknown_statement(ItemCategory.HOUSEHOLD)
    assert "생활용품으로 보입니다" in house
    assert "네 등급" in house
    assert "안전기준준수" in house


def test_tier_statement_falls_back_when_the_category_is_unknown():
    """품목군도 모르면 아는 척하지 않는다."""
    text = _tier_unknown_statement(ItemCategory.UNCLASSIFIED)
    assert "판별하지 못했습니다" in text
    assert "보입니다" not in text
