"""경쟁 품목 - 둘 다 표에 있을 때 어느 쪽이 본체인가.

"의자방석" 은 방석이지 의자가 아니다. 그런데 '의자' 를 닫아 두면 방석도 의자도
답을 못 준다 - 실측에서 의자 계열 8건이 전부 미매칭이었다.

닫는 것 말고 다른 길이 있었다. 방석은 **부속품이 아니라 별개 품목**이다 -
부속서 1 기타 제품류가 "쿠션류, 방석류" 를 명시하고, 표에 '의류 이외의
섬유제품'(안전기준준수)이 있다. 그래서 is_accessory 질문으로는 못 가른다.
갈림이 본체 vs 부속품이 아니라 품목 A vs 품목 B 다.

경쟁 관계를 적으면 둘 다 맞출 수 있다.
"""

from sourcing_guard.item_grades import (
    ItemGradeBook,
    is_usable_contain_key,
    normalize,
    rival_wins,
)


def _items(book, name):
    return [g.item for g in book.lookup_all(name)]


def test_chair_resolves_when_no_rival_is_present():
    """경쟁자가 없으면 의자다."""
    book = ItemGradeBook()
    for name in ("무중력의자 리클라이너 실내", "HICKIES 스텐 작업의자 C1"):
        assert "의자" in _items(book, name), name


def test_cushion_does_not_become_a_chair():
    """방석이 의자로 붙으면 등급이 틀린다 - 의자는 안전기준준수, 방석은 섬유제품이다."""
    book = ItemGradeBook()
    for name in (
        "메모리폼 의자방석 쿠션방석",
        "5존케어 입체방석 의자방석",
        "쿨 여름 사각방석 의자 쿠션",
    ):
        assert "의자" not in _items(book, name), name


def test_electric_cushion_still_wins_by_its_own_name():
    """'전기방석' 은 표에 그 이름으로 있다. 경쟁 규칙보다 앞선다."""
    book = ItemGradeBook()
    got = _items(book, "국산 8단 전기방석 전기요 전기장판 전기매트")
    assert "전기방석" in got


def test_rival_rule_names_what_it_yields_to():
    """양보 대상이 표에 실제로 있어야 한다. 없으면 조용히 미매칭이 된다."""
    book = ItemGradeBook()
    target = rival_wins(normalize("의자방석 쿠션"), "의자")
    assert target == "의류 이외의 섬유제품"
    assert book._by_name.get(normalize(target)), "양보 대상이 표에 없다"


def test_short_key_is_allowed_only_when_a_rival_rule_guards_it():
    """길이 규칙의 목적은 우연 충돌을 막는 것이다.

    경쟁 규칙이 그 자리를 지키면 짧아도 열 수 있다. 규칙 없는 짧은 말은
    여전히 막힌다 - 예외를 넓히면 'LED' 가 다시 들어온다.
    """
    assert is_usable_contain_key(normalize("의자"))     # 규칙이 있다
    assert not is_usable_contain_key(normalize("전지"))  # 규칙이 없다


def test_rivals_are_only_declared_between_items_that_both_exist():
    """한쪽이 비대상이면 경쟁이 아니라 그냥 오답이고, 부속어 신호가 처리한다."""
    from sourcing_guard.item_grades import _RIVAL_ITEMS

    book = ItemGradeBook()
    for key, (_, target) in _RIVAL_ITEMS.items():
        assert book._by_name.get(normalize(key)), f"{key} 가 표에 없다"
        assert book._by_name.get(normalize(target)), f"{target} 가 표에 없다"


# ---------------------------------------------------------------------------
# 양보는 대상에 착지한다
# ---------------------------------------------------------------------------


def test_the_yield_lands_on_its_declared_target():
    """경쟁에서 진 뒤 양보 대상이 실제로 붙어야 한다.

    2026-09-04: 처음 적용했을 때는 착지하지 않고 미매칭이 됐다. 매처의 본체
    검사(names_subject)를 **목적지 품목명**으로 하고 있었기 때문이다 -
    상품명에 '의류 이외의 섬유제품' 이라는 말이 있을 리 없으니 항상 거부됐다.

    별칭 단계가 같은 함정을 이미 알고 있었다("본체 검사는 별칭 키로 한다.
    목적지 품목명은 상품명에 없는 것이 정상이다"). 경쟁 단계만 그 처리가
    빠져 있었고, 경쟁 키('의자')로 검사하도록 고쳤다.

    ⚠ 이 검사는 한 번 뒤집힌 것이다. 그 전에는 "착지하지 않는다" 를 박아
      두었는데, 현 동작을 박아둔 검사가 남으면 다음 사람이 그게 정답이라고
      읽는다. 고치면서 뒤집었다.
    """
    book = ItemGradeBook()
    for name in (
        "메모리폼 크로스오버 4D방석 메모리폼 의자방석 쿠션방석 사무실방석 쿠션",
        "5존케어 4D메모리 입체방석 의자방석 쿠션방석 사무실방석 쿠션",
        "쿨 여름 메모리 사각방석 의자 사무실 쿠션 40cm 방석 식탁 복유럽",
    ):
        got = _items(book, name)
        assert "의류 이외의 섬유제품" in got, (name, got)
        assert "의자" not in got, (name, got)


def test_the_yield_target_carries_its_own_grade():
    """양보 대상의 등급이 붙어야 셀러가 답을 받는다.

    방석은 안전기준준수 대상이라 "인증·신고 절차가 없어 조회 DB 에 번호가
    없는 것이 정상" 이다. 미매칭이면 "판별 못 함" 이 되어 그 답을 못 준다.
    """
    book = ItemGradeBook()
    got = book.lookup_all("메모리폼 의자방석 쿠션방석 사무실방석")
    one = next(g for g in got if g.item == "의류 이외의 섬유제품")
    assert one.grade == "안전기준준수"


def test_the_subject_check_uses_the_rival_key_not_the_target():
    """목적지로 본체 검사를 하면 양보가 영원히 착지하지 않는다."""
    from sourcing_guard.item_grades import names_the_subject

    name = normalize("메모리폼 의자방석 쿠션방석")
    # 목적지 이름은 상품명에 없다 - 이것으로 검사하면 항상 거부다.
    assert not names_the_subject(name, normalize("의류 이외의 섬유제품"))
    # 경쟁 키는 상품명에 있다.
    assert names_the_subject(name, normalize("의자"))
