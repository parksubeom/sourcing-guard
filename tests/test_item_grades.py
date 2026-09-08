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
    chemical_variant_dominates,
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


def test_table_covers_all_three_regimes(book):
    """전기용품만 넣었을 때 골든셋·데모 19건 중 3건만 대상이었다.

    휴지통·토트백·키링처럼 셀러가 실제로 소싱하는 것이 전부 생활용품이라
    빠졌다. 별표 4~7 을 받아 채웠다.

    ⚠ children 이 나중에 늘었다. 새 표본 235건에서 어린이제품이 35건(15%)
      인데 완구·학용품·유아용품이 561건 표에 아예 없었다 - 매칭 규칙 문제가
      아니라 커버리지 공백이었다.
    """
    cats = {row["category"] for row in book._rows}
    assert cats == {"electrical", "household", "children"}
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
    """561건 전부에 별칭을 붙이려 하면 대부분 쓰이지 않는 항목에 시간을 쓴다.

    붙이는 기준은 하나다 - **실측 표본에서 실제로 못 맞춘 것만** 넣는다.
    표본은 tests/fixtures/실상품30.txt 와 도매꾹239.txt 다. 상한을 올릴 때는
    새 별칭이 그 표본의 어느 건에서 왔는지 말할 수 있어야 한다.

    상한 이력: 40 (실상품 30건 기준) → 70 (도매꾹 239건 추가). 239건에서
    못 맞춘 107건을 원문과 대조해 53건이 표에 있는 품목임을 확인하고,
    그중 보조배터리·건조대·토스터·청소기·고데기·제모기·안마기·믹서기 계열을
    넣었다.
    """
    assert len(ALIASES) <= 90, f"사전이 {len(ALIASES)}건까지 커졌다 - 실제로 쓰이는지 확인하라"
    # ⚠ 상한을 70 → 90 으로 올렸다. 새로 든 8건은 우리 추정이 아니라
    #   **KC인증 DB 에서 캔 것**이다(docs/인증DB_탐침결과.md). productName 이
    #   "<법령 품목명>(<통칭>)" 으로 등록돼 있어 정부가 이미 적어 둔 사전을
    #   옮긴 것이고, 한 건씩 새표본235 로 재서 오답 0 인 것만 남겼다.
    #   손으로 짐작한 별칭과 성격이 다르다.


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


# ---------------------------------------------------------------------------
# 부속품은 본체가 아니다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        # 도매에서 부속품은 본체 품목명을 그대로 달고 팔린다. 실측 오답이
        # 전부 이 모양이었다 - 거치대는 고데기가 아니다.
        "생활더봄 무타공 욕실 헤어드라이기 고데기 거치대 홀더 2 color",
        "핸디캐디 주방 정리 밥솥 에어프라이어 토스터기 선반",
        "셀링온 전동 칫솔거치대",
        "욕실 전동칫솔 거치대 칫솔홀더 받침대 DD-11019",
        "(소형/대형) 스탠드 선풍기 커버 망 보관 방수 덮개",
        "리브리움 전자레인지선반 밥솥다이 밥통수납장 슬림오븐 주방렌지대",
        "이동식 화분 원목 인테리어 공기청정기 받침대 다용도 받침대 식물 원예",
        # 부정 표현. "고데기없이 웨이브" 는 고데기가 아니다.
        "히피펌 물결펌 롤 고데기없이 웨이브 42cm 12pcs",
    ],
)
def test_accessories_do_not_match_the_main_item(book, name):
    assert book.lookup_all(name) == [], [g.item for g in book.lookup_all(name)]


@pytest.mark.parametrize(
    "name, expect",
    [
        # ⚠ 부속어가 있다고 통째로 막으면 본체를 놓친다. 출현 단위로만 뺀다.
        ("NEO2M 간편세척 습도조절 세라믹 볼 필터 대용량 저소음 초음파 가습기", "가습기"),
        ("나오테크4070 방수 음파전동칫솔 본체1리필2", "전동칫솔"),
        ("우산 양산 양우산 자동우산 3단자동우산 골프우산 암막우산 케이스", "우산"),
        ("문걸이형 미니빨래 건조대", "간이 빨래걸이"),
    ],
)
def test_the_guard_does_not_eat_real_products(book, name, expect):
    assert expect in [g.item for g in book.lookup_all(name)]


# ---------------------------------------------------------------------------
# 보조배터리는 「전지」다 - 원문이 갈라 준다
# ---------------------------------------------------------------------------


def test_power_banks_resolve_to_the_battery_item_not_the_cell_item():
    """별표 1·2 비고가 소비자 판매용을 「전지」로 보낸다.

    별표 1 10.나 단전지(안전인증) 비고 1 은 그 품목을 "스마트폰, 노트북
    컴퓨터에 적용되는 에너지밀도 700 Wh/L 이상, 최대 충전전압 4.4 V 이상의
    단전지(리튬계)" 로 한정한다 - 완제품에 들어가는 셀 부품이다.

    같은 비고 2(별표 2 에도 같은 문구가 있다)는 "일상생활에서 전지를
    사용하는 자에게 판매되는 단전지(리튬계)는 전지(리튬계)로 간주" 한다.
    보조배터리는 셀을 묶은 팩이라 애초에 단전지가 아니고, 소비자 판매용
    이므로 두 경로가 모두 별표 2 파.전지 ① 전지(안전확인)로 모인다.
    """
    book = ItemGradeBook()
    for name in ("모즈온 미니 도킹 보조배터리 5000 C타입 8핀",
                 "USB 충전식 보조베터리 10000mAh",
                 "충전식 손난로 파워뱅크 6000mAh"):
        items = [(g.item, g.grade) for g in book.lookup_all(name)]
        assert ("전지", "안전확인") in items, items
        assert not any(i in ("단전지", "리튬이차단전지") for i, _ in items), items


# ---------------------------------------------------------------------------
# 접미 한 글자가 화학제와 기기를 가른다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        # 염화칼슘 제습제다. 표의 '제습기'(전기기기)가 아니다.
        "대용량 500ml 옷걸이 제습제 곰팡이방지 제습기 옷장용제습제 차량용제습제 습기제거",
        "옷걸이 제습제 곰팡이방지 제습기 옷장용제습제 신발장제습제 차량용제습제 습기제거제",
        "옷걸이 제습제 250g 곰팡이방지 제습기 염화칼슘제습제 신발장제습제 차량용제습제",
    ],
)
def test_chemical_products_do_not_match_the_appliance(book, name):
    assert "제습기" not in [g.item for g in book.lookup_all(name)]


@pytest.mark.parametrize(
    "name, expect",
    [
        ("ADP T8 미니 제습기", "제습기"),
        ("미니제습기 지니큐 펠티어방식 제습기", "제습기"),
        # 쉼표가 지워지면 '가습'+'제습 기능' 이 들러붙어 '가습제' 가 생긴다.
        # 존재 검사를 쓰면 이 상품이 죽는다 - 그래서 개수를 비교한다.
        ("가습기 대용량 (가습, 제습 기능 있음)", "가습기"),
    ],
)
def test_the_rule_does_not_kill_real_appliances(book, name, expect):
    assert expect in [g.item for g in book.lookup_all(name)]


def test_the_rule_compares_counts_not_mere_presence():
    """존재 검사는 낱말 경계가 지워져 생긴 '제' 형태에 걸린다.

    실측(41,800건)에서 어간+'제' 가 나타난 짝은 셋뿐이고, 그중 '가습제' 14건은
    전부 "공기청정기(가습, 제습기능 있음)" 이었다 - 쉼표가 지워져 생긴 것이다.
    """
    assert chemical_variant_dominates(normalize("옷걸이 제습제 제습기 차량용제습제"), "제습기")
    assert not chemical_variant_dominates(normalize("가습기 (가습, 제습 기능)"), "가습기")
    assert not chemical_variant_dominates(normalize("미니 제습기 제습기"), "제습기")
    # '기' 로 끝나지 않거나 어간이 한 글자면 보지 않는다.
    assert not chemical_variant_dominates(normalize("전기면도기 면도제"), "전기면도기")


# ---------------------------------------------------------------------------
# 같은 일을 하는 화학제는 전기 품목이 아니다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        # 흔드는 핫팩은 화학 발열체다. 표의 '전기손난로'(공급자적합성확인)가
        # 아니고, 붙이면 안전관리 대상이 아닌 상품에 의무를 말하게 된다.
        "핫팩 [아이러버] 흔드는핫팩 80g 200개 붙이는 핫팩 400개 대용량 100개 손난로 찜질팩",
        "프리미엄 홍일병 대용량 핫팩 100g 캠핑 군인 손난로 군용 흔드는 핫팩 1매 포켓용핫팩",
    ],
)
def test_chemical_hot_packs_are_not_electric_hand_warmers(book, name):
    assert "전기손난로" not in [g.item for g in book.lookup_all(name)]


@pytest.mark.parametrize(
    "name",
    [
        # 충전식 손난로가 '핫팩' 을 연관 검색어로 다는 것이 도매의 전형이다.
        # 화학제 낱말이 있다고 거부하면 정답 6건이 함께 죽는다.
        "아이리스 손난로 보조배터리 대용량 10000mA USB 충전식 BP12 멀티 핸드워머 핫팩",
        "고용량 레트로 핸드워머 손난로 10000mA USB 충전식 Q2 KC인증 대량구매 핫팩",
        "[당일출고] 6000mAH 충전식 손난로 판촉물 충전손난로 보조배터리 파워뱅크",
    ],
)
def test_rechargeable_hand_warmers_survive_the_hot_pack_word(book, name):
    assert "전기손난로" in [g.item for g in book.lookup_all(name)]


def test_the_rival_rule_needs_an_electric_hint_to_be_bypassed():
    """전기 신호가 하나라도 있으면 화학제로 보지 않는다.

    실측(도매꾹 239건)에서 '손난로'·'핫팩' 8건이 전기 표기 유무로 정확히
    갈렸다 - 있는 6건은 전기, 없는 2건은 화학이다.
    """
    from sourcing_guard.matcher import chemical_rival_wins

    assert chemical_rival_wins("흔드는 핫팩 200개 손난로", "전기손난로")
    assert not chemical_rival_wins("USB 충전식 손난로 핫팩", "전기손난로")
    # 화학제 낱말이 없으면 아예 보지 않는다.
    assert not chemical_rival_wins("USB 충전식 손난로", "전기손난로")
    # 다른 품목에는 적용되지 않는다.
    assert not chemical_rival_wins("흔드는 핫팩", "선풍기")


# ---------------------------------------------------------------------------
# 법령 품목명 - LLM 이 이름을 내고 표가 검증한다
# ---------------------------------------------------------------------------


def test_legal_item_name_is_looked_up_in_the_table():
    """LLM 이 옮긴 이름이 표에 있으면 매칭된다.

    손으로 만든 별칭이 한계에 왔다. 세 숫자를 구분한다 -
    튜닝 표본(도매꾹239) 매칭률 71% / 새 표본(235) 매칭률 24% /
    새 표본 검수 정답률 20%(발표 숫자). 별칭이 첫
    표본에서 만들어졌으니 새 상품에는 안 통한다. 문제가 문자열이 아니라
    의미라서, LLM 을 번역기로 쓰고 표를 검증자로 둔다.
    """
    from datetime import date

    from sourcing_guard.verifier import _item_grade_findings

    found = _item_grade_findings(
        "코웨이 정수기 렌탈 냉온정", date(2026, 9, 4), legal_name="전기정수기"
    )
    items = [c["item"] for f in found for c in f.detail.get("candidates", [])]
    assert "전기정수기" in items


def test_a_made_up_legal_name_is_thrown_away():
    """표가 검증자다. 표에 없는 이름은 버려진다 - LLM 이 등급을 지어낼 수 없다 (R1).

    실측(새 표본 30건): LLM 이 이름을 답한 11건 중 9건이 표에 없어 버려졌다.
    """
    from datetime import date

    from sourcing_guard.verifier import _item_grade_findings

    found = _item_grade_findings(
        "무엇인지 알 수 없는 물건", date(2026, 9, 4), legal_name="존재하지않는품목명"
    )
    assert found == []


def test_the_table_qualifier_is_bridged_on_the_legal_name_path():
    """표가 법령 수식을 붙인 형태까지 조회한다 - LLM 답에만.

    표 561건 중 75건(13%)에 수식이 붙어 있다 - '무선스피커 시스템'·
    '전기오븐기기'·'형광등기구'. LLM 이 자연스럽게 답하면 이 75건은 영원히
    안 맞는다. 검증자가 자기 표기법을 강요하는 것이지 LLM 이 틀린 게 아니다.

    수식이 붙는 자리가 셋이라 부분 문자열만으로는 부족하다:
        뒤   무선스피커 ⊂ 무선스피커**시스템**
        앞   안전모     ⊂ **자전거용**안전모
        가운데 전기그릴 ⊂ 전기**거치식**그릴
    """
    from datetime import date

    from sourcing_guard.verifier import _item_grade_findings

    for legal, want in (
        ("무선스피커", "무선스피커 시스템"),
        ("전기오븐", "전기오븐기기"),
        ("전기그릴", "전기거치식그릴"),
        ("안전모", "자전거용 안전모"),
    ):
        found = _item_grade_findings("아무 상품", date(2026, 9, 4), legal_name=legal)
        items = [c["item"] for f in found for c in f.detail.get("candidates", [])]
        assert want in items, f"'{legal}' → '{want}' 가 안 걸린다"


def test_a_bridged_candidate_is_only_possible():
    """표기가 정확히 같지 않았으면 possible 이다.

    표의 수식을 우리가 넘겨 짚은 것이므로 likely 로 올리지 않는다. 정확
    일치는 likely 로 남는다 - 둘을 같은 신뢰도로 두면 오답이 나올 때 어느
    쪽에서 왔는지 못 가린다.
    """
    from datetime import date

    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()

    bridged = book.lookup_legal_name("무선스피커")
    assert [g.matched_by for g in bridged] == ["legal_name_contains"]

    exact = book.lookup_legal_name("전기정수기")
    assert [g.matched_by for g in exact] == ["legal_name"]

    # 정확 일치가 있으면 포함으로 더 긁어오지 않는다 - '전지' 가 표에 있으니
    # '건전지'·'충전지' 류를 함께 담지 않는다.
    assert len(book.lookup_legal_name("전지")) == 1

    del date  # 이 검사는 표만 본다


def test_the_containment_relaxation_never_touches_the_seller_name_path():
    """포함 완화는 LLM 답 전용이다. 셀러 상품명에는 쓰지 않는다.

    ⚠ 위험도가 다르다. 셀러 상품명에는 브랜드·수식어·연관검색어·부속품이
      섞여 있어 포함이 물면 엉뚱한 품목이 걸린다. LLM 답은 이미 정리된
      품목명 하나라 포함이 물 것이 표의 수식뿐이다.

      이 검사가 없으면 다음 사람이 "포함이 되던데" 하고 상품명 경로에도
      열게 된다. 그 경로는 137건 오탐 사고를 낸 자리다.
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()

    # 상품명 경로로는 '무선스피커 시스템' 이 안 걸린다.
    by_name = [g.item for g in book.lookup_all("무선스피커")]
    assert "무선스피커 시스템" not in by_name

    # 같은 문자열을 LLM 답으로 주면 걸린다.
    by_legal = [g.item for g in book.lookup_legal_name("무선스피커")]
    assert by_legal == ["무선스피커 시스템"]


def test_no_finding_is_built_from_an_empty_candidate_list():
    """후보가 0이면 finding 을 만들지 않는다.

    ⚠ 회귀 가드. legal_name 조회를 빈 검사 **뒤에** 놓았다가, 표에 없는 이름이
      오면 후보 0으로 "갈립니다" finding 이 나오고 부속품 분기의 found[0] 이
      IndexError 가 됐다. 순서가 조회 → 빈 검사여야 한다.
    """
    from datetime import date

    from sourcing_guard.models import SellerHints
    from sourcing_guard.verifier import _item_grade_findings

    for hints in (None, SellerHints(is_accessory=True), SellerHints(power_source="mains")):
        found = _item_grade_findings(
            "무엇인지 알 수 없는 물건",
            date(2026, 9, 4),
            hints=hints,
            legal_name="존재하지않는품목명",
        )
        for f in found:
            assert f.detail.get("candidates") != [], f"{hints} : 후보 0인 finding"


def test_the_legal_name_path_is_a_fallback_not_an_addition():
    """규칙 경로가 후보를 냈으면 법령 경로를 얹지 않는다.

    더 구체적인 답이 있는데 상위 개념의 형제를 얹는 것이 이상하다. 킥보드
    헬멧에서 규칙이 '자전거용 안전모' 를 맞췄는데 LLM 답 '안전모' 로
    스키용·야구용까지 6개가 붙어, 셀러가 자기 상품이 아닌 것을 읽었다.

    contains 경로가 이미 쓰는 "긴 이름 우선"을 경로 사이로 넓힌 것이다.
    """
    from datetime import date

    from sourcing_guard.verifier import _item_grade_findings

    raw = "[21st ScooTer] 21세기 킥보드 보호 헬멧 로봇 플라워"
    without = _item_grade_findings(raw, date(2026, 9, 5))
    with_legal = _item_grade_findings(raw, date(2026, 9, 5), legal_name="안전모")
    assert [f.detail["candidates"] for f in without] == [
        f.detail["candidates"] for f in with_legal
    ], "규칙이 답을 냈는데 법령 경로가 후보를 얹었다"


def test_the_fallback_condition_is_zero_candidates_not_weak_ones():
    """조건은 '규칙 경로가 0건' 이지 '규칙 경로가 약하다' 가 아니다.

    ⚠ 두 경로를 신뢰도로 비교하기 시작하면 어느 쪽이 옳은지 우리가 판정하게
      되는데, 그건 우리가 할 수 있는 일이 아니다 (R1). 규칙이 possible 로
      하나만 찾았어도 법령 경로를 얹지 않는다.
    """
    import inspect

    from sourcing_guard import verifier

    src = inspect.getsource(verifier._item_grade_findings)
    head = src[: src.index("if not found:")]
    assert "lookup_legal_name(legal_name, haystack=_hay) if not found else ()" in head, (
        "폴백 조건이 바뀌었다"
    )
    for smell in ("confidence ==", 'confidence ==\n', "possible\" in", "certain\" in"):
        assert smell not in head, f"신뢰도로 두 경로를 비교하고 있다: {smell}"


# ---------------------------------------------------------------------------
# 어린이제품 등급표 - 자료만 넣고 판정에는 아직 연결하지 않았다
# ---------------------------------------------------------------------------


def _child_table() -> dict:
    from pathlib import Path

    import yaml

    return yaml.safe_load(
        (Path("sourcing_guard/data/child_item_grades.yaml")).read_text(encoding="utf-8")
    )


def test_child_table_has_the_thirty_five_items_from_the_three_appendices():
    """시행규칙 별표 1·2·3 의 품목 수를 잠근다.

    561건 표는 전기·생활용품뿐이라 완구·학용품·유아용품이 아예 없었다.
    새 표본 235건에서 어린이제품이 35건(15%)이라 커버리지 공백이 컸다.
    """
    from collections import Counter

    items = _child_table()["items"]
    assert len(items) == 35
    assert Counter(i["grade"] for i in items) == {
        "안전확인": 17,
        "공급자적합성확인": 14,
        "안전인증": 4,
    }
    names = {i["item"] for i in items}
    for must in ("완구", "학용품", "유모차", "보행기", "어린이용 자전거"):
        assert must in names


def test_child_table_uses_the_same_schema_as_the_five_sixty_one():
    """스키마가 같아야 나중에 합칠 때 변환이 없다."""
    from pathlib import Path

    import yaml

    adult = yaml.safe_load(
        Path("sourcing_guard/data/item_grades.yaml").read_text(encoding="utf-8")
    )["items"]
    child = _child_table()["items"]
    assert set(child[0]) == set(adult[0])


def test_the_catch_all_rule_is_a_field_not_a_comment():
    """포괄 규정을 데이터로 남긴다 - 화면이 그대로 쓸 수 있어야 한다.

    전기·생활용품에서는 "표에 없음 = 비대상이 아니다" 를 우리가 추론했지만,
    어린이제품은 시행규칙 별표 3 제2호가 문장으로 적고 있다. 그래서 목록에
    없어도 "판별 못 함" 이 아니라 확정된 답을 줄 수 있다.
    """
    ca = _child_table()["catch_all"]
    assert ca["grade"] == "공급자적합성확인"
    assert ca["standard"] == "어린이제품 공통안전기준"
    assert "별표 3 제2호" in ca["source"]
    assert ca["source_text"] == (
        "개별 안전기준이 없는 공급자적합성확인대상어린이제품은 "
        "어린이제품 공통안전기준을 적용한다."
    )
    # ⚠ 단정하지 않는다 (R3-b). "대상이 아닙니다" 로 끝내면 안 된다.
    assert "빠지지 않습니다" in ca["statement_ko"]
    assert "안전합니다" not in ca["statement_ko"]


def test_the_child_table_is_wired_into_one_shared_index():
    """어린이제품 표를 561건과 **같은 색인에** 넣었다.

    ⚠ 이 검사는 앞서 "아직 연결하지 않았다" 를 잠그고 있던 자리다. 연결하면서
      뒤집었다 - 현 동작을 박아둔 검사가 남으면 다음 사람이 그게 정답이라고
      읽는다.

    나누지 않고 합친 근거는 실측이다:
        이름이 정확히 같은데 등급이 다름   0건
        어린이 쪽이 구체형인 관계        16건  (유아용 의자 ⊃ 의자)
    나누면 "어느 표를 볼지" 를 먼저 판정해야 하는데, 그건 상품이 어린이제품
    인지 우리가 단정하는 일이 된다.
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    assert len(book) == 561 + 35
    names = {r["item"] for r in book._rows}
    assert {"완구", "학용품", "유모차"} <= names          # 어린이제품
    assert {"의자", "전기장판"} <= names                  # 전기·생활용품
    assert book.child_catch_all["grade"] == "공급자적합성확인"


def test_short_child_names_are_not_containment_keys():
    """유모차·보행기·학용품 은 역방향 포함 키로 쓰지 않는다.

    ⚠ 실측: 그대로 합치면 235건에서 +7 걸리는데 6건이 오답이고, 합의였던
      5건이 오답 갈림으로 바뀐다. 오답 11건을 전부 이 3글자 셋이 만들었다.

          유모차 컵홀더 · 유모차 고리 · 유모차 모기장 · 기저귀 가방
          목발형 보행기(성인 보행보조기) · 보행기튜브(물놀이 튜브) 3건

      도매 상품명에서 부속품이 본체 이름을 그대로 달기 때문이고, 이미 있던
      원칙("짧고 흔한 토큰은 식별력이 없다")에 그대로 해당한다.
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    for raw in ("내맘대로 360도 회전 유모차 자전거 컵홀더 음료 커피 물통",
                "목발형 접이식 보행기 깁스 보조 지팡이 이동",
                "런웨이브 보행기튜브/플라밍고/독수리/물놀이튜브"):
        assert not [g for g in book.lookup_all(raw)
                    if g.item in {"유모차", "보행기", "학용품"}], raw

    # 정확 일치로는 여전히 걸린다 - 키에서 뺀 것이지 표에서 뺀 것이 아니다.
    assert [g.item for g in book.lookup_all("유모차")] == ["유모차"]


# ---------------------------------------------------------------------------
# 포괄 규정 - 어린이제품인 것이 확인됐는데 목록에 없을 때만
# ---------------------------------------------------------------------------


def _verify(name, *, age=None, category=None):
    from unittest.mock import MagicMock

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = MagicMock()
    rules.covers.return_value = True
    rules.matching.return_value = []
    facts = ProductFacts(
        product_name=name,
        category=category or ItemCategory.CHILDREN_TOY,
        target_age=age,
    )
    return [f.kind.value for f in verify(facts, kats, rules)]


def test_the_catch_all_speaks_only_when_the_page_declared_a_child_age():
    """조건 (1) 어린이제품인 것이 표기로 확인됐을 때만.

    ⚠ 연령 표기가 없으면 붙이지 않는다. 어린이제품인지 모르는 상태에서
      "어린이제품이면 공통안전기준이 적용됩니다" 를 말하면 모든 상품에 붙는
      소음이 되고, 그러면 셀러가 이 문장을 읽지 않게 된다.

    ⚠ 우리 추측이 아니라 셀러 페이지가 말한 사실이다 - UNKNOWN 은 UNKNOWN 이다 (R3).
    """
    assert "child_catch_all" in _verify("랜덤 뽑기 굿즈 캡슐", age="3세 이상")
    assert "child_catch_all" not in _verify("랜덤 뽑기 굿즈 캡슐", age=None)
    assert "child_catch_all" not in _verify("랜덤 뽑기 굿즈 캡슐", age="만 15세 이상")


def test_the_catch_all_stays_quiet_when_the_item_is_in_the_table():
    """조건 (2) 목록에서 찾았으면 그 등급이 답이다.

    '어린이용 킥보드' 는 시행규칙 별표 3 에 있으므로 공급자적합성확인으로
    특정된다. 거기에 포괄 규정을 겹쳐 말하면 같은 사실을 두 번 말하게 된다.
    """
    kinds = _verify("어린이용 킥보드", age="3세 이상")
    assert "item_grade_matched" in kinds
    assert "child_catch_all" not in kinds


def test_the_catch_all_does_not_claim_the_product_is_exempt():
    """"대상이 아닙니다" 로 끝내지 않는다 (R3-b · CLAUDE.md §9)."""
    from unittest.mock import MagicMock

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = MagicMock()
    rules.covers.return_value = True
    rules.matching.return_value = []
    facts = ProductFacts(
        product_name="랜덤 뽑기 굿즈 캡슐",
        category=ItemCategory.CHILDREN_TOY,
        target_age="3세 이상",
    )
    found = [f for f in verify(facts, kats, rules) if f.kind.value == "child_catch_all"]
    assert len(found) == 1
    f = found[0]
    assert "빠지지 않습니다" in f.statement_ko
    for banned in ("안전합니다", "합법", "대상이 아닙니다", "판매 가능"):
        assert banned not in f.statement_ko
    # R2 - 근거 없는 출력은 없다.
    assert "별표 3 제2호" in f.source_label
    assert f.source_url.startswith("https://")
    assert f.detail["source_text"].startswith("개별 안전기준이 없는")


def test_only_the_measured_school_supply_alias_is_present():
    """부속서 11 서문의 16개 이름 중 실측으로 오답 0 인 것만 넣었다.

    ⚠ 별칭이지 등급표 행이 아니다. 부속서는 안전기준이고 품목 목록은
      시행규칙 별표다 - 부속서 이름을 표에 행으로 넣으면 그 구분이 무너지고,
      matched_by 가 exact 급이 되어 실제보다 세게 말하게 된다.

    ⚠ 나머지를 뺀 것은 "안전해서" 가 아니라 **안 재봐서**다.
        지우개  맞음 4 / 오답 4 (택배송장지우개·얼룩지우개) → 기준 오답 0
        파스텔  성인용 튜브에 걸린다 - 색 이름이라 식별력이 없다
        나머지 13개는 이 표본에서 한 건도 안 걸렸다
    """
    from sourcing_guard.item_grades import ALIASES

    assert ALIASES.get("크레파스") == "학용품"
    # ⚠ '색연필' 은 2026-09-06 에 들어왔다 - 인증 DB 가 "학용품(연필류 및
    #   연필심)" 으로 등록해 뒀고 표본에서 +7 건 전부 정답이었다.
    for not_measured in ("지우개", "파스텔", "연필류", "그림물감",
                         "스케치북", "색종이", "연필깎이", "마킹펜류"):
        assert not_measured not in ALIASES, (
            f"'{not_measured}' 는 실측 없이 들어왔다"
        )


def test_the_school_supply_alias_lands_as_possible_not_exact():
    """별칭이므로 possible 이다 - 표의 품목명이 아니라는 사실이 남아야 한다."""
    from sourcing_guard.item_grades import ItemGradeBook

    got = ItemGradeBook().lookup_all("단색 크레파스 12개입 문교 유아 색칠 교구")
    assert [(g.item, g.grade, g.matched_by, g.confidence) for g in got] == [
        ("학용품", "안전확인", "alias", "possible")
    ]


def test_kickboard_is_not_a_containment_key():
    """'킥보드' 는 표본에서 오답 7건을 만들었다 - 전수 검수 오답 13건의 절반이 넘는다.

    표본에 킥보드 **본체가 0건**인데 부속품·호환표기로 계속 걸렸다:
        유모차 컵홀더(킥보드 호환) · 무릎보호대(인라인 킥보드) · 후미등 ·
        헬멧 · 이름표 · 방한장갑 ×2

    ⚠ 표에서 뺀 것이 아니라 **포함 키에서만** 뺐다. 정확 일치와 '전동킥보드'
      는 살아 있어야 한다 - 킥보드 본체 상품이 오면 여전히 걸려야 하고,
      이득 손실이 0 이라는 근거가 그것이다.
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    for raw in ("집게 업그레이드 2 in 1유모차 컵홀더 자전거 킥보드 오토바이 호환",
                "USB충전식 방수 자전거 킥보드 안전 후미등",
                "[ABC0532] 핸드워머 자전거 킥보드 방한장갑 핸드머프"):
        assert not [g for g in book.lookup_all(raw) if g.item == "킥보드"], raw

    # ⚠ **2026-09-08 에 '전동킥보드' 가 빠졌다.** 예전에는 prefix_variants 가
    #   '킥보드' 에 '전동' 을 붙여 표의 '전동킥보드' 를 함께 냈다. 동력 표지
    #   가드를 넣으면서 그 경로가 닫혔다.
    #
    #   **가드가 옳게 막았다.** 상품명에 '킥보드' 뿐이면 발로 미는 킥보드일
    #   수 있고, 그때 '전동킥보드'(안전확인 대상)를 붙이면 없는 의무를
    #   만든다. 표에 '킥보드'·'전동킥보드' 가 따로 있는 이유가 그것이다.
    #
    #   이 검사의 원래 취지("포함 키에서 뺐지만 정확 일치는 살아 있다")는
    #   '킥보드' 한 건으로 그대로 확인된다.
    assert [g.item for g in book.lookup_all("킥보드")] == ["킥보드"]
    assert [g.item for g in book.lookup_all("전동킥보드 접이식 성인용")] == ["전동킥보드"]
    # 표지어가 있으면 전동 쪽도 함께 나온다.
    assert "전동킥보드" in [
        g.item for g in book.lookup_all("킥보드 충전식 접이식", raw_text="킥보드 충전식 접이식")
    ]


def test_knee_pad_alias_lands_on_the_child_sports_gear_item():
    """무릎보호대 → 어린이용 스포츠 보호용품. 근거는 안전확인 부속서 3 원문.

        서문      "보호장구(롤러스포츠용에 한함)"
        1부 적용범위 "보호대란, 인라인스케이트, 롤러스케이트, 스케이트보드,
                    자전거 등을 탈 때 … 손, 손목, 팔꿈치, **무릎**에 입는 …
                    상해로부터 보호하거나 상해를 경감시킬 목적으로 사용되는 보호대"
        3.3       무릎 보호대 정의

    ⚠ 키가 '보호대' 가 아니라 '무릎보호대' 다 - '모서리보호대' 가 걸리면 안 된다.
    ⚠ 팔꿈치·손목·손 보호대는 넣지 않았다. 부속서에 함께 열거돼 있지만 표본에
      0건이라 못 쟀다. 크레파스 때와 같다 - 안전한 것이 아니라 모르는 것이다.
    """
    from sourcing_guard.item_grades import ALIASES, ItemGradeBook

    book = ItemGradeBook()
    got = book.lookup_all("주니어 어린이 초등학생 쿠션무릎보호대 (2p 1set) / 인라인 킥보드")
    assert [(g.item, g.grade, g.matched_by, g.confidence) for g in got] == [
        ("어린이용 스포츠 보호용품(보호 장구 및 안전모)", "안전확인", "alias", "possible")
    ]

    assert not book.lookup_all("모서리보호대 코너가드 아기보호 충격방지 안전쿠션 문 벽 기둥 캡")

    # ⚠ '무릎담요' 는 이제 별개 별칭으로 전기방석에 붙는다 - 인증 DB 의
    #   "전기방석(전기무릎담요)" 3건이 근거다. 예전에는 이 줄이 아무것도 안 붙는
    #   것을 잠갔는데 지금은 전기방석이 정답이다. 단언을 "이 줄에 스포츠
    #   보호용품이 붙지 않는다" 로 좁힌다.
    blanket = book.lookup_all(
        "[겨울필수템] USB 포켓 발열무릎담요 플란넬 양털 극세사 대형 무릎담요"
    )
    assert all("스포츠 보호용품" not in g.item for g in blanket)
    assert [g.item for g in blanket] == ["전기방석", "전기방석"]

    for not_measured in ("보호대", "팔꿈치보호대", "손목보호대", "손보호대"):
        assert not_measured not in ALIASES, f"'{not_measured}' 는 실측 없이 들어왔다"


def test_the_audited_wrong_answers_are_the_only_ones_left():
    """새표본235 의 매칭이 검수 파일과 어긋나지 않는지 잠근다.

    ⚠ 발표에 쓰는 숫자는 매칭률이 아니라 **정답률**이다.
    ⚠ 분모는 235 가 아니라 **안전관리대상 136** 이다 (새표본235_대상분류.tsv).
    ⚠ 발표 숫자는 **단건 경로**다 (데모가 단건이다). 이 검사는 배치를 잠근다.
        배치 · 상품명만 · 대상 135    정답 111 (82.2%) · 애매 2 · 오답 1
        단건 · 상품명만 · 대상 135    정답 113 (83.7%) · 애매 2 · 오답 1  ← 발표
        전체 매칭 116/235

    ⚠ 2026-09-07~08 101 → 116: 안전기준준수 부속서 1(가정용 섬유제품)
      [표 1] 세부분류를 옮겼다 (docs/부속서1_가정용섬유제품_종류표.md).
        기타 제품류  "가방, 쿠션류, 방석류, **모기장**, 커튼, 수의, 덮개 등"
        중의류       "… 셔츠, **타올**, **장갑** … **헤어밴드**, 가발, 귀마개, **토시** 등"
      모기장 +5 · 가방 +5 · 장갑·토시·헤어밴드·타월 +6. 오답 증가 0건.
      부속서 1 이 만 14세 이상이라 어린이 표지어가 없을 때만 연다
      (ALIASES_IF_NO_CHILD_MARKER).

    이 검사가 실패하면 매칭이 바뀐 것이다 - 검수 파일을 다시 만들 것.
    """
    import pathlib

    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    rows = [l.strip() for l in
            pathlib.Path("tests/fixtures/새표본235.txt").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    # ⚠ 집계는 **공용 헬퍼 하나**를 쓴다 (scripts/audit_tally.py). 2026-09-08
    #   까지 같은 일을 하는 구현이 셋이었고 서로 달라서 기획서에 77.8% 를
    #   적었는데 실제는 77.0% 였다.
    import sys

    sys.path.insert(0, "scripts")
    from audit_tally import load_audit, tally

    wrong, vague = load_audit()
    results = {r: sorted({g.item for g in book.lookup_all(r)}) for r in rows}
    got = tally(results)

    assert got["matched_all"] == 116, got
    assert got["ok"] == 111, got
    assert got["vague"] == 2, got
    assert got["wrong"] == 1, got

    # 검수 파일에 적힌 줄은 **아직 그 품목이 붙고 있어야** 한다 - 다른 품목이
    # 붙어 고쳐졌으면 [고쳐짐]·[검수했고 정답] 절로 옮기거나 사유를 적을 것.
    #
    # ⚠ 145번 곰돌이비치타월은 예외로 남겨 뒀다. 지금은 '의류' 가 붙어
    #   고쳐졌지만, '물놀이' 가 다시 튜브를 붙이면 오답이므로 가드로 필요하다.
    #   그 사유를 파일 안에 적어 뒀고, 여기서는 사유 문구의 존재로 확인한다.
    audit_text = pathlib.Path("tests/fixtures/새표본235_오답.tsv").read_text(encoding="utf-8")
    for name in set(wrong) | set(vague):
        if name not in results or results[name]:
            continue
        assert "가드로 남긴다" in audit_text, name


def test_knee_pad_alias_needs_a_child_marker_in_the_product_name():
    """표의 품목명이 '어린이용' 이므로 별칭도 그 범위를 넘지 않아야 한다.

    ⚠ 이건 "못 재서 미룬 것" 이 아니라 **별칭이 표의 범위보다 넓었던 것**이다.
      부속서 3 서문이 "만 13세 이하의 어린이가 … 사용되는" 이라고 못박는다.
      표본에 성인용 보호대가 0건이라는 것은 오답이 안 난다는 뜻이지 별칭이
      맞다는 뜻이 아니다.

    조건은 셀러 답이 아니라 **상품명에 이미 적힌 표지어**다 - 질문이 늘지 않는다.
    """
    from sourcing_guard.item_grades import ALIASES, ItemGradeBook

    book = ItemGradeBook()
    for raw in ("주니어 어린이 초등학생 쿠션무릎보호대 (2p 1set) / 인라인 킥보드",
                "키즈 무릎보호대 인라인 세트"):
        assert [g.item for g in book.lookup_all(raw)] == [
            "어린이용 스포츠 보호용품(보호 장구 및 안전모)"
        ], raw
    for raw in ("성인용 무릎보호대 작업용 니패드 2p",
                "스포츠 무릎보호대 등산 러닝 관절보호"):
        assert not book.lookup_all(raw), raw

    # ⚠ '무릎담요' 는 별개 별칭이다 - 인증 DB 의 "전기방석(전기무릎담요)" 3건에서
    #   왔다. 예전에는 이 줄이 아무것도 안 붙는 것을 잠갔는데, 지금은 전기방석이
    #   붙는 것이 정답이다. 단언을 "무릎보호대 별칭이 안 붙는다" 로 좁혔다.
    blanket = book.lookup_all("[겨울필수템] USB 포켓 발열무릎담요 플란넬 양털 극세사")
    assert all("스포츠 보호용품" not in g.item for g in blanket)

    # 무조건 별칭에는 없어야 한다.
    assert "무릎보호대" not in ALIASES


def test_water_play_alias_has_no_age_gate_on_purpose():
    """물놀이기구에는 표지어 조건을 걸지 않는다 - 걸면 정답을 죽인다.

    '공기주입물놀이기구' 는 어린이제품이 아니라 생활용품(운용요령 별표 4)이고,
    안전인증 부속서 7 서문이 "수영장, 강가, 해수욕장 등 물에서 놀이를 하거나
    수영을 배울 때 사용자의 부양을 도울 목적으로 사용되는 기구" 라고만 적어
    **연령 범위를 두지 않는다**. 성인용 튜브도 대상이다.
    """
    from sourcing_guard.item_grades import ALIASES_IF_CHILD_MARKED, ItemGradeBook

    book = ItemGradeBook()
    for raw in ("특대형 성인용 파인애플 튜브 여름/바다/계곡/휴가철 물놀이 튜브",
                "프리미엄 클래식 파스텔 튜브 파도타기 물놀이 용품 성인용 튜브"):
        assert [g.item for g in book.lookup_all(raw)] == ["공기주입물놀이기구"], raw

    assert "물놀이" not in ALIASES_IF_CHILD_MARKED


def test_the_proposal_never_quotes_an_unaudited_rate_bare():
    """제출 문서가 검수 전 숫자를 설명 없이 내밀지 않는지 잠근다.

    ⚠ 71% 는 별칭을 만들 때 쓴 표본(도매꾹239)의 매칭률이고, 24% 는 새 표본의
      **검수 전** 매칭률이다. 둘 다 발표 숫자가 아니다.

    ⚠ 발표 숫자는 **분모와 경로를 함께** 쓴다 - "안전관리대상 135 중 74.1%,
      단건 경로, 입력은 상품명만". 하나라도 빠지면 분모를 유리하게 바꾼 것이
      된다.

    ⚠ 2026-09-07: 전체 235 기준 매칭률(40.9%)을 함께 적던 것을 **실측 오부착**
      으로 바꿨다. 40.9% 는 "대상 아닌 것에 안 붙인다" 를 재는 값이 아니라
      그냥 다른 분모의 매칭률이었다. 비대상 100건을 실제로 돌려 0건·2건을
      얻었고 그것만 적는다 (docs/비대상_오부착_실측_2026-09-07.md).
    """
    import pathlib

    doc = pathlib.Path("01_기획서_안심소싱돋보기.md").read_text(encoding="utf-8")
    # ⚠ **두 숫자를 함께 적는다 (2026-09-09).** 83.7% 도 미검수 14 를 품은
    #   상한이었다. GPT 를 재면서 우리 숫자에도 같은 기준을 걸기로 했으므로
    #   (커밋 `9a49ff2`) 기획서 형식도 그래야 한다 - 검수 전 값을 검수된 값처럼
    #   쓰지 않는다. 검수가 끝나면 두 값이 하나로 합쳐진다(미완 3-b).
    #
    #   값 자체는 `test_docs` 가 원자료에서 재계산해 대조한다. 여기서는
    #   **형식**만 잠근다 - 한 숫자만 남으면 걸린다.
    assert "73.3%" in doc, "검수된 정답이 빠졌다"
    assert "83.7%" in doc, "상한이 빠졌다"
    assert "검수 완료 정답" in doc and "미검수 포함 상한" in doc
    # 애매 부착도 적는다 - 분모 밖이라고 빼면 4-e 같은 변경이 조용히 지나간다.
    assert "애매     47건 →" in doc
    assert "0건 부착" in doc
    # 조건 없는 숫자를 쓰지 않는다 - 경로와 분모를 함께 적는다.
    assert "조건 없는 숫자를 쓰지 않습니다" in doc
    assert "단건 경로 · 상품명만 · 대상 135 중" in doc
    assert "배치 경로 · 대상 135 중" in doc
    if "71%" in doc:
        assert "만들 때 쓴 표본에서만 잘 듣는다" in doc
    # 분모를 사람이 정했다는 사실을 밝힌다 (R3-b).
    assert '화면에는 "비대상입니다"를 출력하지 않습니다' in doc


def test_standalone_accessory_at_the_end_blocks_the_match():
    """상품명이 독립 부속품명으로 **끝나면** 파는 물건이 그것이다.

    ⚠ 인접 가드(names_the_subject)와 다르다. 저쪽은 키 바로 뒤만 보고 이건
      이름 끝을 본다. "에어프라이어 토스터기 선반" 은 '선반' 이 키 바로 뒤에
      없어서 인접 가드가 못 잡았다.

    실측(새표본235): 오답 3건을 힌트 없이 잡았다 - 유모차 컵홀더→스마트폰,
    다리미판 행거 지지대→스팀다리미, 전기면도기 거치대→전기면도기.
    도매꾹239 에서도 오답 1건을 잡았다(170→169).
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    for raw in ("핸디캐디 주방 정리 밥솥 에어프라이어 토스터기 선반",
                "유모차 컵홀더 스마트폰 핸드폰 거치대 2in1 유모차 홀더",
                "장갑 높이조절 스탠드 스팀 다리미판 행거 지지대",
                "무타공 전기면도기 스테인레스 거치대 면도기 홀더 욕실걸이"):
        assert book.lookup_all(raw) == [], (raw, [g.item for g in book.lookup_all(raw)])

    # ⚠ 커버·케이스·필터·리필은 넣지 않았다. 본체와 함께 팔리는 포장·구성품이다.
    assert [g.item for g in book.lookup_all("18색 우드 색연필 틴케이스")] == ["학용품"]

    # ⚠ 품목명 자체가 그 말로 끝나면 예외다 - 표에 '간이 빨래걸이' 가 있다.
    assert [g.item for g in book.lookup_all("실내 빨래걸이")] == ["간이 빨래걸이"]


def test_the_particle_guard_keeps_goods_words_alive():
    """'<품목명>용 <다른 물건>' 은 부속품이다. 다만 '용품' 은 예외다.

    예외가 없으면 "물놀이 용품 성인용 튜브" 가 죽는다 - '물놀이용품' 은
    "물놀이를 위한 물건" 이라는 한 낱말이지 "<물놀이>용 <품>" 이 아니다.
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    assert book.lookup_all("사각 종이호일 다용도 에어프라이어용 대용량 화이트") == []
    assert [g.item for g in book.lookup_all(
        "프리미엄 클래식 파스텔 튜브 파도타기 물놀이 용품 성인용 튜브"
    )] == ["공기주입물놀이기구"]


def test_cert_db_sourced_aliases_land_where_measured():
    """KC인증 DB 에서 캔 별칭이 실측대로 붙는지 잠근다.

    productName 이 "<법령 품목명>(<통칭>)" 으로 등록돼 있다 -
    "전기오븐기기(에어프라이어)" 224건, "학용품(필통)" 19건.
    우리 추정이 아니라 정부가 적어 둔 사전이다 (docs/인증DB_탐침결과.md).
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    cases = {
        "에어프라이어 / 사은품 선물용": ["전기오븐기기"],
        "특대형 와이드그릴 전기그릴 전기후라이팬 전기팬": ["전기거치식그릴", "전기휴대형그릴"],
        "아크로 S5 포터블 블루투스 스피커 C-Type": ["앰프 내장형 스피커"],
        "8800 조선문방구 12색 색연필 슬림 노크식": ["학용품"],
        "하이라이트펜 스틱 층층이 고체 형광펜 볼펜": ["학용품"],
        "모나미 18종 행복특가 문구세트": ["학용품"],
    }
    for raw, want in cases.items():
        assert [g.item for g in book.lookup_all(raw)] == want, raw

    # ⚠ 넣지 않은 것 - 인증 DB 에 있지만 표본에서 오답을 냈다.
    from sourcing_guard.item_grades import ALIASES
    assert "로봇청소기" not in ALIASES   # '문턱 도어턱받침' 7건에 붙는다
    assert "훈증기" not in ALIASES       # '모기훈증기 … 리필' 에 붙는다


def test_appendix24_mat_aliases_do_not_go_to_bed_mattress():
    """매트류(화학)와 침대 매트리스(생활)는 별표 7 의 **다른 행**이다.

    ⚠ 인증 DB 에서 '매트' 를 치면 "안전기준준수대상 생활용품 > 생활 >
      침대 매트리스" 가 1,177건 나온다. 우리가 찾는 행이 아니다 - 함정이다.
      부속서 24 가 적은 매트류는 "요가매트, 돗자리매트, 주방매트, 욕실 바닥
      매트 등" 이다.
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    for raw in ("퍼즐매트 EVA 우드 매트 층간소음방지 거실 놀이방 베란다",
                "놀이방매트 층간소음방지 pvc놀이 유아거실바닥 어린이안전 아기방",
                "무독성 사계절 다용도 방수매트 김장매트 180cm 특대형"):
        got = [g.item for g in book.lookup_all(raw)]
        assert got == ["매트류"], (raw, got)
        assert "침대 매트리스" not in got


def test_plastic_gate_keeps_us_from_asserting_a_material_we_do_not_know():
    """부속서 24 는 "주 재질이 합성수지로 구성되는 제품에 한함" 이라고 적었다.

    ⚠ 실측이 이 게이트를 요구했다. '슬리퍼'·'실내화' 를 조건 없이 열면 표본에서
      8건이 붙는데 그중 5건이 우리가 **'애매' 로 분류한** 린넨·왕골·모직
      실내화다. 붙이면 우리가 모르는 것을 안다고 말하게 된다.

    ⚠ 매트류에는 이 게이트를 걸지 않았다 - 게이트 없이도 오답 0 · 애매 부착
      0 이었다. 못 잰 것을 근거로 게이트를 설계하지 않는다.
    """
    from sourcing_guard.item_grades import ALIASES, ItemGradeBook

    book = ItemGradeBook()
    assert [g.item for g in book.lookup_all(
        "가벼운 물빠짐 치즈욕실화 EVA소재 슬리퍼 실내화")] == ["신발류"]
    for raw in ("2500배송 모직 린넨 거실 실내화 여름 남성 여성 사무실 슬리퍼",
                "2500배송 고양이 왕골 슬리퍼 여름 샌들 린넨 마 실내화 거실화",
                "지압슬리퍼 사무실 실내화 다이어트 슬리퍼"):
        assert book.lookup_all(raw) == [], raw

    # 무조건 별칭에는 없어야 한다.
    for k in ("슬리퍼", "실내화", "거실화"):
        assert k not in ALIASES

    # ⚠ '욕실화' 는 절대 넣지 않는다 - "욕실 화장실" 이 정규화되면 '욕실화장실'
    #   이 되어 '욕실화' 를 담는다. 낱말 용접이다.
    assert "욕실화" not in ALIASES
    from sourcing_guard.item_grades import ALIASES_IF_PLASTIC
    assert "욕실화" not in ALIASES_IF_PLASTIC
    assert book.lookup_all("8in1 전동 무선 청소솔 자동 브러쉬 욕실 화장실 바닥 솔") == []


def test_marker_gates_also_read_the_raw_page_text():
    """표지어 게이트만 원본을 함께 본다.

    표지어(초등·EVA·물놀이)는 **셀러가 페이지에 적은 사실**이다. LLM 이
    요약하면서 떨어뜨린 것을 복구하는 것은 값을 지어내는 것이 아니다 -
    원본에 '초등' 이 있는데 요약본에 없다고 학용품을 안 붙이면 우리가 아는
    것을 버리는 것이고 R3 정신과 반대다.

    실측(단건 경로 135건): 68.9% → 71.1%, 오답 1 그대로, 대상 밖 부착 0.
    회복된 3건 - 초등필통 → 학용품, EVA 슬리퍼 2건 → 신발류.

    ⚠ 09-04 에 "원본 병행" 을 재봤을 때는 이득이 0 이었다. 그때는 조건부
      별칭이 없었다 - 전제가 바뀌었다.
    """
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    # LLM 요약본에는 표지어가 없다.
    assert book.lookup_all("메쉬필통") == []
    assert book.lookup_all("치즈욕실화 슬리퍼 실내화") == []

    # 원본을 게이트에 함께 주면 걸린다.
    assert [g.item for g in book.lookup_all(
        "메쉬필통",
        raw_text="메쉬필통 메시필통 초등필통 중학생필통 초등학생필통",
    )] == ["학용품"]
    assert [g.item for g in book.lookup_all(
        "치즈욕실화 슬리퍼 실내화",
        raw_text="가벼운 물빠짐 치즈욕실화 EVA소재 슬리퍼 실내화",
    )] == ["신발류"]


def test_raw_text_never_reaches_the_subject_check():
    """매처의 본체 검사에는 원본을 넣지 않는다.

    ⚠ 09-04 경쟁 양보 버그가 정확히 그 자리였다 - 검사 입력을 잘못 바꿔
      후보가 전부 거부됐다. 게이트 조건만이다.

    원본에 부속어가 있어도 요약본이 본체를 가리키면 매칭은 유지되고, 반대로
    원본에 품목명이 있어도 요약본에 없으면 **매칭이 생기지 않는다** -
    원본은 게이트 조건에만 쓰이기 때문이다.
    """
    import inspect

    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    # 원본에만 '전기주전자' 가 있다. 게이트용이므로 매칭이 생기면 안 된다.
    assert book.lookup_all("무언가", raw_text="전기주전자 1.8L 무선포트") == []

    src = inspect.getsource(ItemGradeBook.lookup_all)
    body = src[src.index("gate_text"):]
    assert "names_the_subject(intact" not in body or "raw_text" not in body.split(
        "names_the_subject(intact"
    )[0].split("gate_text")[-1]
    # 게이트 문자열이 별칭 조건 셋에만 쓰이는지 본다.
    assert src.count("gate_text") == 3   # 정의 1 + 어린이 1 + 합성수지 1


def test_a_two_letter_legal_answer_is_not_widened_into_other_items():
    """2글자 법령 답은 확장하지 않는다. 상위어가 하위 품목으로 승격한다.

    ⚠ 실측 사고다. 비대상 100건 측정에서 오답 2건이 정확히 여기서 나왔다 -
      '인덕션냄비 4중바닥 스텐냄비'(21·23번). LLM 은 '냄비' 라고 **정확히**
      답했는데 우리가 그 2글자를 '전기냄비'·'가정용 압력냄비' 로 벌렸다.
      스테인리스 냄비는 식품용 기구(식약처)이고 전기제품도 압력식도 아니다.

    ⚠ 이 방향 자체는 필요하다 - 표 561건 중 75건에 법령 수식이 붙어 있어
      '무선스피커' → '무선스피커 시스템' 을 못 따라잡으면 그 75건은 영원히
      안 맞는다. 2글자에서만 수식이 아니라 **다른 품목**이 걸린다.

    ⚠ 정확 일치는 이 가드 앞에 있으므로 '완구'·'의류'·'침대' 처럼 표에
      그 이름 그대로 있는 2글자 품목은 잃지 않는다. 가드가 자르는 것은
      확장뿐이다.
    """
    from sourcing_guard.item_grades import ItemGradeBook, _MIN_CONTAIN_LEN

    assert _MIN_CONTAIN_LEN == 3

    book = ItemGradeBook()

    for short in ("냄비", "매트", "신발", "가전"):
        assert book.lookup_legal_name(short) == [], short

    # 정확 일치는 2글자여도 살아 있다.
    for exact in ("완구", "의류", "침대"):
        got = book.lookup_legal_name(exact)
        assert [g.matched_by for g in got] == ["legal_name"], (exact, got)

    # 3글자 이상의 확장은 그대로다.
    assert [g.matched_by for g in book.lookup_legal_name("무선스피커")] == [
        "legal_name_contains"
    ]
    # 여럿이 걸리면 갈림으로 확인을 요청하는 것이 정확한 동작이다 (R3).
    assert len(book.lookup_legal_name("안전모")) > 1


def test_the_adult_bag_table_closes_when_a_child_marker_is_present():
    """부속서 1 은 만 14세 이상이다. 표지어가 있으면 붙이지 않는다.

    ⚠ ALIASES_IF_CHILD_MARKED 의 **반대 방향**이다. 저쪽은 표의 품목이
      '어린이용~' 이라 표지어가 있어야 열리고, 이쪽은 표의 품목이 만 14세
      이상이라 표지어가 있으면 닫힌다.

    ⚠ 어린이용 가방이 어느 품목인지는 「공급자적합성확인대상 어린이제품의
      안전기준」 부속서를 봐야 알 수 있고 아직 원문을 못 봤다. 확인 전에
      '아동용 섬유제품' 으로 짐작해 매핑하지 않는다 (R5). 품목을 안 붙이면
      어린이제품 포괄 규정이 받는다 - 회색으로 남는 것이 맞다.
    """
    from sourcing_guard.item_grades import ALIASES_IF_NO_CHILD_MARKER, ItemGradeBook

    book = ItemGradeBook()

    # 표지어 없음 → 부속서 1 이 열린다.
    for raw in ("[CU] 에어핏 트레일 러닝 조끼 백팩 마라톤 런닝 등산 트래킹 자전거",
                "핏미업 러닝벨트 힙색 슬링백 벨트백 스포츠 러닝 자전거 등산 가방"):
        assert [g.item for g in book.lookup_all(raw)] == ["의류 이외의 섬유제품"], raw

    # 표지어 있음 → 닫힌다.
    for raw in ("EVERYGOOD 학생용 대용량 책가방 백팩 초등학생 선물 추천",
                "키즈 백팩 어린이 가방"):
        assert not book.lookup_all(raw), raw

    # 기저귀 가방은 보호자가 드는 물건이라 표지어와 무관하게 열린다.
    for raw in ("아기 기저귀 가방 백팩 출산가방 유모차 보냉백",
                "(올라이프) 접이식 기저귀 가방 아기침대 휴대용 기저귀가방"):
        assert [g.item for g in book.lookup_all(raw)] == ["의류 이외의 섬유제품"], raw

    # ⚠ '가방'·'책가방' 을 넣지 않은 이유를 잠근다 - 실측에서 '책가방' 은
    #   "책가방 걸이"·"책가방 장식" 같은 열쇠고리 4건에 붙었다.
    assert "가방" not in ALIASES_IF_NO_CHILD_MARKER
    assert "책가방" not in ALIASES_IF_NO_CHILD_MARKER
    for raw in ("귀여운 파차 열쇠고리 실리콘 2원 책가방 열쇠고리 도매 만화 열쇠고리",
                "열쇠고리 산리오 인형 책가방 장식 자동차 열쇠고리 정교함"):
        assert not book.lookup_all(raw), raw


def test_a_power_prefix_is_not_added_without_evidence_in_the_text():
    """표가 붙인 '전기'·'전동' 을 원문 근거 없이 따라가지 않는다.

    ⚠ 실측 사고다. `_PREFIXES` 를 **양방향**으로 쓰면 '프라이팬' 에 '전기' 를
      붙여 표의 '전기프라이팬' 에 맞춘다. 그러면 무쇠 프라이팬(식품용 기구·
      식약처)과 1회용 면도기가 전기제품이 된다. GPT 전수 측정에서 비대상
      2건이 정확히 그렇게 붙었다:

        19  IH 인덕션 후라이팬 무쇠팬 …  → 전기프라이팬  (법령 포함 확장)
        227 면도기 1회용면도기 …        → 전기면도기    (prefix_variants)

    ⚠ 두 경로가 다르다. 227번은 `prefix_variants` 가 만든 **가짜 정확 일치**
      이고, `how="exact"` 라 부속어·본체 검사가 전부 꺼져 다른 가드가 받아
      주지 못한다. 그래서 두 곳 모두에 걸었다.

    ⚠ **떼는 방향은 조건 없이 유지한다.** 셀러가 '전기' 라 적은 것을 우리가
      의심할 이유가 없다.

    ⚠ 원문을 함께 보는 것은 막는 판단을 **완화하는** 쪽이다 - LLM 이 요약에서
      '전기' 를 떨어뜨렸을 때 정답을 죽이지 않기 위해서다. [Q] 가 금지한
      것은 매처 본체 검사에 원본을 겹쳐 넣는 것이고 여기는 게이트 조건이다.
    """
    from sourcing_guard.item_grades import (
        _POWER_MARKERS,
        ItemGradeBook,
        has_power_marker,
        prefix_variants,
    )

    book = ItemGradeBook()

    # 막혀야 하는 것 - 동력 표지가 없다.
    assert not book.lookup_all(
        "면도기", raw_text="[ABC0749] 면도기 1회용면도기 면도기일회용 개별OPP포장"
    )
    assert not book.lookup_all(
        "IH 인덕션 후라이팬 무쇠팬 궁중팬",
        raw_text="IH 인덕션 후라이팬 무쇠팬 궁중팬 볶음팬 프라이팬",
    )
    # 법령 경로도 같다.
    assert not book.lookup_legal_name("프라이팬", haystack="IH 인덕션 무쇠팬")
    assert not book.lookup_legal_name("면도기", haystack="1회용면도기 개별포장")

    # 표지어가 있으면 살아 있다.
    for name, want in (
        ("USB 선풍기 미니", "선풍기"),
        ("충전식 랜턴", "충전식 휴대전등"),
        ("전동 칫솔", "전동칫솔"),
        ("220V 전기포트", "전기주전자"),
    ):
        got = [g.item for g in book.lookup_all(name, raw_text=name)]
        assert want in got, (name, got)

    # 떼는 방향은 조건 없이 유지된다.
    assert [g.item for g in book.lookup_all("전기토스터")] == ["전기토스터"]

    # ⚠ **요약이 '전기' 를 잃어도 원문이 살린다.** 이 두 줄이 가드의 핵심이다.
    assert [
        g.item for g in book.lookup_all("주전자", raw_text="스탠리 무선 전기 주전자 1.7L")
    ] == ["전기주전자"]
    assert not book.lookup_all("주전자", raw_text="전통 무쇠 주전자 찻주전자 선물세트")

    # haystack 을 안 주면 예전대로 무조건 붙인다 - 표 어휘 정렬 자리를 안 깬다.
    assert "전기면도기" in prefix_variants("면도기")
    assert "전기면도기" not in prefix_variants("면도기", haystack="1회용 면도기")

    # ⚠ 목록이 두 갈래다 - 실측 9개와 추정 추가 5개. 주석이 그것을 갈라
    #   적어야 한다. "실측" 이라 적힌 것은 실측이어야 한다.
    import pathlib as _p

    src = _p.Path("sourcing_guard/item_grades.py").read_text(encoding="utf-8")
    assert "(1) 실측 9개" in src and "(2) 추정 추가 5개" in src
    for measured in ("전기", "전동", "무선", "충전", "USB", "BLDC", "DC",
                     "배터리", "건전지"):
        assert measured in _POWER_MARKERS, measured
    # 한 글자는 넣지 않았다.
    assert "W" not in _POWER_MARKERS and "V" not in _POWER_MARKERS
    # 'DC' 는 두 글자라 실측했다 - 474건에서 BLDC 안 2건뿐, 단독 0건.
    assert "단독 'DC' 출현은 0건" in src
    assert has_power_marker("BLDC 써큘레이터")
    assert not has_power_marker("무쇠 프라이팬 궁중팬")
