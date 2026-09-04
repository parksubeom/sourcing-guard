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
