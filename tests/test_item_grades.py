"""품목 등급 조회 - "이 품목이 안전인증 대상인가".

인증번호 부재의 의미는 등급에 따라 완전히 다르다 (CLAUDE.md R3-b). 그동안
이걸 몰라서 전부 kc_tier_unknown 으로 내보냈다.

⚠ 이 파일의 핵심은 **어절 매칭을 쓰지 않는다**는 것이다. 'LED 5W 초소형
  펜라이트' 를 어절로 맞추면 'LED' 하나로 LED등기구(안전인증)에 붙는데,
  정답은 충전식 휴대전등(안전확인)이라 등급이 뒤집힌다. 리콜 매칭에서 '153'
  이 볼펜과 LED 전등을 잇던 것과 같은 뿌리다.
"""

from pathlib import Path

import pytest

from sourcing_guard.item_grades import (
    ALIASES,
    _SHORT_KEY_EXCEPTIONS,
    ItemGradeBook,
    normalize,
    strip_modifiers,
)
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
    banned = {"LED", "전등", "가방", "의자", "충전", "전기", "무선", "조명", "매트"}
    for key in ALIASES:
        assert normalize(key) not in {normalize(b) for b in banned}, f"흔한 키: {key}"
        if len(normalize(key)) < 3:
            # 짧아도 그 물건에만 쓰이는 말은 허용한다. 기준은 "짧다" 가 아니라
            # "흔하다" 이고, 리콜 37,313건으로 실측해 예외 목록에 넣었다.
            assert key in _SHORT_KEY_EXCEPTIONS, f"근거 없는 짧은 키: {key}"


def test_short_key_exceptions_are_documented():
    """2글자 키 예외는 실측 근거가 코드에 남아 있어야 한다."""
    from pathlib import Path

    src = Path("sourcing_guard/item_grades.py").read_text(encoding="utf-8")
    for key in _SHORT_KEY_EXCEPTIONS:
        assert key in src
    # 위험하다고 측정된 것은 예외에 들어가면 안 된다
    assert not _SHORT_KEY_EXCEPTIONS & {"매트", "의자", "조명", "전등"}


def test_alias_dictionary_stays_small():
    """564건 전부에 별칭을 붙이려 하면 대부분 쓰이지 않는 항목에 시간을 쓴다.

    골든셋·데모에 나오는 것부터 시작하고 실제 상품을 넣어보며 늘린다.
    """
    assert len(ALIASES) <= 40, f"사전이 {len(ALIASES)}건까지 커졌다 - 실제로 쓰이는지 확인하라"


def test_alias_targets_exist_in_the_table(book):
    """사전이 표에 없는 법령 어휘를 가리키면 조용히 아무것도 안 한다.

    값은 문자열 하나이거나 여러 후보의 튜플이다 - 원문이 갈라 두지 않은
    말('센서등')을 한쪽으로 단정하지 않기 위해 튜플을 허용한다.
    """
    for key, legal in ALIASES.items():
        targets = (legal,) if isinstance(legal, str) else legal
        assert targets, f"{key} : 가리키는 품목이 없다"
        for name in targets:
            assert book._by_name.get(normalize(name)), f"{key} -> {name} : 표에 없다"


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


# ---------------------------------------------------------------------------
# 사람이 검수해서 잡은 오답들 (실상품 표본 30건)
#
# 매칭률만 보면 안 된다. 40% -> 45% 로 올라도 그중 3건이 오답이면 손해다.
# 아래는 시피님이 검수표를 눈으로 훑어 짚어준 것들이다.
# ---------------------------------------------------------------------------


def test_alias_never_beats_the_decree(book):
    """표는 법령 원문이고 별칭은 우리 추정이다. 추정이 원문을 이기면 안 된다.

    '미니 무선 탁상용 무드등 선풍기 가습기' 가 LED등기구로 갔었다 - '무드등'
    별칭이 표에 그대로 있는 '선풍기'·'가습기' 를 이겼기 때문이다.
    """
    found = book.lookup_all("미니 무선 탁상용 무드등 선풍기 가습기 화이트 에어쿨러")
    items = [g.item for g in found]
    assert "선풍기" in items and "가습기" in items
    assert found[0].matched_by in ("exact", "contains")
    assert ItemGradeBook.grades_agree(found) == "안전인증"


@pytest.mark.parametrize(
    "name,want_item,want_grade",
    [
        # 조명은 원문 정의로 갈린다. 등급이 안전인증 vs 안전확인으로 뒤집히면
        # 셀러에게 잘못된 의무를 말하게 된다.
        ("캠핑용 LED 랜턴 충전식 방수 텐트등", "충전식 휴대전등", "안전확인"),
        ("캠핑랜턴 감성 캠핑 LED 충전식 텐트 랜턴", "충전식 휴대전등", "안전확인"),
        ("스노우맨 줄조명 알전구 LED 앵두전구", "체인형 조명기구", "안전확인"),
        ("앵두 자두전구 20구 USB 알조명 텐트장식", "체인형 조명기구", "안전확인"),
        # 벽·천장 고정은 LED등기구다
        ("LED 센서등 인체감지 무선 현관 계단", "LED등기구", "안전인증"),
    ],
)
def test_lighting_items_resolve_by_the_decree_definition(book, name, want_item, want_grade):
    """LED등기구는 천장·벽 설치용이다. 손에 드는 랜턴은 충전식 휴대전등이다."""
    g = book.lookup(name)
    assert g is not None, f"{name} 를 못 맞춘다"
    assert g.item == want_item, f"{name} → {g.item} (기대 {want_item})"
    assert g.grade == want_grade


def test_multiple_candidates_are_all_returned(book):
    """도매 상품명은 연관 검색어를 다 붙인다. 하나를 고르면 틀릴 수 있다 (R3)."""
    found = book.lookup_all("미니 무선 탁상용 무드등 선풍기 가습기")
    assert len(found) >= 2


def test_agreeing_grades_make_it_certain(book):
    """후보가 여럿이어도 등급이 같으면 오히려 확실해진다."""
    found = book.lookup_all("미니 무선 탁상용 무드등 선풍기 가습기")
    assert ItemGradeBook.grades_agree(found) == "안전인증"


def test_modifier_stripping_does_not_break_table_names(book):
    """수식어가 품목명의 일부인 경우를 놓치면 안 된다.

    표에 '헤드셋' 은 없고 '무선 헤드셋' 만 있다. '무선' 을 떼는 순간 못 찾게
    되므로, 원본과 제거본을 둘 다 본다.
    """
    for name in ("무선 헤드셋", "휴대용 레이저용품", "실내용 바닥재",
                 "가정용 압력냄비", "충전식 휴대전등"):
        g = book.lookup(name)
        assert g is not None and g.matched_by == "exact", f"{name} 가 깨졌다"


# ---------------------------------------------------------------------------
# 같은 이름이 여러 등급에 걸리면 한쪽을 단정하지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, grades",
    [
        # 표에 같은 이름으로 두 등급이 있다. 하나만 답하면 인증번호 부재의
        # 의미가 뒤집힌다 - 공급자적합성확인이면 없는 것이 정상이다 (R3-b).
        ("소형 미니 공기청정기", {"안전확인", "공급자적합성확인"}),
        ("USB 온열 전기방석", {"안전인증", "공급자적합성확인"}),
        # 전자회로 유무로 갈리는 조명. 상품명만으로는 알 수 없다.
        ("LED 전기스탠드 책상", {"안전인증", "안전확인"}),
    ],
)
def test_names_spanning_two_grades_return_both(book, name, grades):
    found = book.lookup_all(name)
    assert grades <= {g.grade for g in found}, [
        (g.item, g.grade) for g in found
    ]
    assert ItemGradeBook.grades_agree(found) is None, "갈리는데 하나로 답했다"


def test_same_name_at_two_grades_is_not_deduplicated(book):
    """'주서' 는 이름이 같고 등급만 다르다. 이름으로 중복을 지우면 한쪽이 사라진다."""
    found = [g for g in book.lookup_all("주서") if g.item == "주서"]
    assert {g.grade for g in found} == {"안전인증", "안전확인"}


# ---------------------------------------------------------------------------
# 수식어를 뗀 형태로 포함 검사를 하면 없던 낱말이 생긴다
# ---------------------------------------------------------------------------


def test_stripping_a_middle_word_must_not_weld_neighbours():
    """normalize 가 띄어쓰기를 지우므로 가운데 토큰을 빼면 양옆이 붙는다.

    "2.1A충전기 가정용 충전기" 에서 '가정용' 을 떼면 "…충전기충전기…" 가
    되어 표의 '전기충전기'(교류 30V 초과 250V 이하 - 벽 콘센트에 꽂는 것)에
    붙었다. 휴대폰 충전기가 그 품목일 리 없다.
    """
    welded = normalize(strip_modifiers("2.1A충전기 가정용 충전기 C타입"))
    assert "전기충전기" in welded, "전제가 깨졌다 - 이 검사의 의미가 없어진다"

    book = ItemGradeBook()
    found = book.lookup_all("충전기 2.1A충전기 가정용 충전기 C타입 USB충전기")
    assert "전기충전기" not in [g.item for g in found]


def test_lighting_words_the_decree_does_not_split_are_left_undecided():
    """'센서등' 은 원문에 없는 셀러 말이고 전원 방식에 따라 등급이 갈린다.

    별표 1 은 상시전원 일반조명기구(안전인증), 별표 2 는 그밖의 조명기구
    (안전확인)다. 건전지형·태양광 센서등을 LED등기구로 보내면 안전확인
    대상에 안전인증 의무를 말하게 된다.
    """
    book = ItemGradeBook()
    for name in ("무선 센서라이트 LED센서등 건전지형", "태양광정원등 센서등 가로등"):
        found = book.lookup_all(name)
        items = {g.item for g in found}
        assert {"LED등기구", "충전식 휴대전등"} <= items, items
        assert ItemGradeBook.grades_agree(found) is None


# ---------------------------------------------------------------------------
# "표에 없음" 을 "대상 아님" 으로 말하지 않는다
# ---------------------------------------------------------------------------


def test_unmatched_copy_never_claims_the_product_is_out_of_scope():
    """561건에 이름이 없어도 대상일 수 있다. 근거는 docs 에 적어 두었다.

    (1) 어린이제품은 열거되지 않아도 대상이다 - 「어린이제품 안전 특별법」
        제2조 12호가 공급자적합성확인대상을 "안전인증·안전확인 대상을 제외한
        어린이제품" 으로 정하고, 제25조 3항이 "고시된 안전기준이 없는"
        어린이제품도 국제기준을 준용해 확인하게 한다.
    (2) 별표 7 에 포괄 품목이 있다 - 부속서 1 기타 제품류(쿠션류·방석류·덮개),
        부속서 24 기타류("및 이와 유사한 용도의 제품"), 기타 가구류.

    그래서 등급을 못 가렸을 때의 문구가 면제를 말하면 안 된다. 실제로 이
    문구를 "안전관리 대상이 아닙니다" 로 바꾸려다 원문을 읽고 취소했다.
    """
    forbidden = ("대상이 아닙", "대상 아님", "필요 없습니다", "필요없습니다",
                 "해당하지 않습니다", "면제")
    for category in ItemCategory:
        copy = _tier_unknown_statement(category)
        for bad in forbidden:
            assert bad not in copy, f"{category}: '{bad}' 가 들어 있다 - {copy}"


def test_the_original_text_evidence_is_written_down():
    """근거를 코드 밖에 두면 다음 세션이 같은 판단을 다시 한다.

    이 저장소의 반복 결함이 문서와 코드가 어긋나는 것이었다. 정정 근거를
    문서에 묶고, 문서가 사라지면 검사가 깨지게 한다.
    """
    doc = Path(__file__).resolve().parents[1] / "docs" / "표에_없음은_비대상이_아니다.md"
    text = doc.read_text(encoding="utf-8")
    for cite in ("제2조 12호", "제25조 3항", "부속서 1", "부속서 5",
                 "부속서 6", "부속서 24", "식품위생법"):
        assert cite in text, f"{cite} 인용이 사라졌다"
