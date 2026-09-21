"""머리글 내비가 **같은 자리**에 있는가 — 높이·개수가 아니라 위치다.

⚠⚠ 2026-09-21 에 이 축이 비어 있어서 놓쳤다. 어제 보고가 *"헤더 masthead
  65px · 내비 5개 — 8장 전부 같음"* 이었는데, **높이와 개수만 재고 위치를
  안 쟀다.** 실제로는 좌표가 셋으로 갈려 있었다 (1440px 실측):

      /  /scan  /watch              내비 좌 681
      /samples  /misses  /unknown   내비 좌 657
      /batch  /guide                내비 좌 833   ← 152px 오른쪽

  CLAUDE.md §6 *"세기 전에 무엇을 셀 것인가를 먼저 적는다"* 가 가리키는 자리다.

⚠ **이 검사는 좌표를 직접 재지 못한다.** 진짜 불변식은 "여덟 장의 내비
  left·right 가 같다" 이고 그것은 브라우저가 있어야 한다(playwright 는
  requirements.txt 에 없다). 여기서는 **좌표를 그렇게 만든 CSS 두 줄**을
  잠근다 - 대리 검사임을 알고 쓴다. 실좌표는 배포 뒤 브라우저로 잰다.

원인 둘 (2026-09-21 로컬 실측 · 고친 뒤 좌표 가짓수 3 → 1):

    (a) `.masthead .container` 가 `justify-content:space-between` 인데
        배지가 없는 화면은 자식이 셋에서 **둘**이 된다 → 내비가 끝으로 밀린다
    (b) `aria-current="page"` 규칙이 `padding:0 0 2px` 로 **좌우 패딩까지**
        지운다 → 활성 링크만 24px 좁아지고 내비 폭이 511/487 로 갈린다
"""

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[1] / "sourcing_guard" / "static" / "app.css"


@pytest.fixture(scope="module")
def css() -> str:
    return CSS.read_text(encoding="utf-8")


def test_the_active_link_keeps_its_horizontal_padding(css):
    """활성 메뉴는 **밑줄**이고(칩이 아니다), 그래서 패딩을 지운다 - 다만
    지워야 하는 것은 세로뿐이다. 좌우까지 지우면 그 링크만 24px 좁아진다.

    ⚠ 반대 방향도 지킨다 - 밑줄이 사라지면 활성 표시가 없어진다.
    """
    rules = re.findall(
        r'nav\.pages a\[aria-current="page"\]\s*\{(.*?)\}', css, re.S)
    assert rules, "활성 메뉴 규칙이 사라졌습니다"

    for body in rules:
        pad = re.search(r"padding\s*:\s*([^;}]+)", body)
        if not pad:
            continue
        parts = pad.group(1).split()
        # padding: <세로> <가로> [<아래>] - 가로가 0 이면 링크가 좁아진다
        assert len(parts) >= 2, (
            f"활성 메뉴 padding 이 한 값입니다({pad.group(1)!r}) - "
            "가로 패딩이 기본 규칙과 갈립니다")
        assert parts[1] not in ("0", "0px"), (
            f"활성 메뉴가 좌우 패딩을 잃었습니다({pad.group(1)!r}). "
            "링크만 24px 좁아져 내비 폭이 화면마다 갈립니다")

    assert re.search(r'nav\.pages a\[aria-current="page"\][^{]*\{[^}]*border-bottom', css, re.S), (
        "활성 메뉴의 밑줄이 없어졌습니다 - 어느 화면인지 표시가 사라집니다")


def test_screens_without_the_date_badge_still_reserve_its_place(css):
    """`/batch`·`/guide` 에 배지를 **달지 않는 것은 설계다** - 그 둘은 리콜을
    대조하지 않으므로 기준일을 달면 대조한 것처럼 읽힌다.

    설계는 그대로 두고 **자리만** 남긴다. 안 남기면 `space-between` 이
    내비를 152px 오른쪽으로 민다 (2026-09-21 실측).
    """
    assert re.search(
        r'\.masthead \.container:not\(:has\(\.asof\)\)::after\s*\{[^}]*width', css, re.S), (
        "배지 없는 화면의 자리 확보가 사라졌습니다 - /batch·/guide 의 내비가 "
        "오른쪽으로 밀립니다")


def test_the_reserved_slot_is_not_read_aloud(css):
    """빈 자리는 `::after` 의 `content:""` 다 - 요소가 아니므로 스크린리더가
    읽을 것이 없다. `aria-hidden` 을 붙일 대상 자체가 없는 편이 안전하다.
    """
    m = re.search(
        r'\.masthead \.container:not\(:has\(\.asof\)\)::after\s*\{(.*?)\}', css, re.S)
    assert m, "자리 확보 규칙이 없습니다"
    assert re.search(r'content\s*:\s*""', m.group(1)), (
        '자리 확보가 `content:""` 가 아닙니다 - 텍스트가 들어가면 읽힙니다')
