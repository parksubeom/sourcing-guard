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
    """⚠⚠ **주석을 걷고 본다.**

    2026-09-21 에 `test_the_icon_box_owns_its_size_in_one_place` 가 자기
    **감사 주석**을 보고 통과했다 - 규칙 위 주석에 "전역 `box-sizing:border-box`
    를 안 받는다" 라고 적어 뒀고, 정작 선언을 지워도 그 글자가 남아서
    가드가 아무것도 못 봤다. CLAUDE.md §6 이 이름 붙인 자리다.

    ⚠ 주석 제거를 여기서 새로 쓰지 않는다 - 오너는 `tests/srccheck.markup_only`
      하나다 (`test_srccheck` 가 그것을 잡는다).
    """
    from tests.srccheck import markup_only

    return markup_only(CSS.read_text(encoding="utf-8"))


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

    ⚠⚠ **폭을 픽셀로 적지 않는다.** 2026-09-21 에 배지 문구가
      "2026-09-17 기준" → "리콜 2026-09-17 기준" 이 되자 124 → 153 으로
      움직였다. 숫자를 적어 두면 문구가 한 글자만 바뀌어도 어긋나고, 그 수는
      글꼴·기기에 따라 달라진다 (CLAUDE.md §6 "320px 은 상수가 아니다").
      **같은 모양의 글자를 넣고 숨겨서 글꼴이 폭을 정하게 한다.**
    """
    m = re.search(
        r'\.masthead \.container:not\(:has\(\.asof\)\)::after\s*\{(.*?)\}', css, re.S)
    assert m, ("배지 없는 화면의 자리 확보가 사라졌습니다 - /batch·/guide 의 "
               "내비가 오른쪽으로 밀립니다")
    body = m.group(1)
    assert re.search(r'content\s*:\s*"[^"]+"', body), (
        "자리표시자에 글자가 없습니다 - 폭이 0 이 됩니다")
    assert not re.search(r"(?<!padding-)(?<!-)\bwidth\s*:\s*\d", body), (
        f"자리 폭을 픽셀로 적었습니다 - 문구가 바뀌면 어긋납니다: {body.strip()[:80]}")


def test_the_placeholder_says_the_same_shape_as_the_real_badge(css):
    """⚠⚠ **자리표시자와 배지 문구는 같은 모양이어야 한다.**

    폭이 글자에서 나오므로, `main._fill_as_of` 가 내는 형식이 바뀌면 여기도
    바뀌어야 한다. 두 곳에 적힌 같은 판단이라 검사로 묶는다 (§6).
    """
    import re as _re
    from pathlib import Path as _P

    main = (_P(__file__).resolve().parents[1] / "sourcing_guard" / "main.py").read_text(
        encoding="utf-8")
    fmt = _re.search(r'shown = f"([^"]+)"', main)
    assert fmt, "_fill_as_of 의 배지 형식을 못 찾았습니다"
    # f-string 의 치환 자리를 숫자 자리로 바꾼다: "리콜 {…}-{…}-{…} 기준"
    shape = _re.sub(r"\{[^}]*\}", "0", fmt.group(1))          # "리콜 0-0-0 기준"
    head, tail = shape.split("0", 1)[0], shape.rsplit("0", 1)[-1]

    ph = _re.search(
        r'\.masthead \.container:not\(:has\(\.asof\)\)::after\s*\{[^}]*content\s*:\s*"([^"]+)"',
        css, _re.S)
    assert ph, "자리표시자 글자를 못 찾았습니다"
    got = ph.group(1)
    assert got.startswith(head) and got.endswith(tail), (
        f"자리표시자가 배지와 다른 모양입니다\n  배지 {shape!r}\n  자리 {got!r}")
    assert len(_re.findall(r"\d", got)) == 8, (
        f"날짜 자릿수가 다릅니다 - 폭이 어긋납니다: {got!r}")


def test_the_reserved_slot_is_not_read_aloud(css):
    """자리표시자에는 **날짜처럼 보이는 글자**가 들어 있다. 스크린리더가 읽으면
    있지도 않은 기준일을 말하는 셈이라 `visibility:hidden` 으로 감춘다 -
    `display:none` 은 자리까지 없애 버려서 안 된다.
    """
    m = re.search(
        r'\.masthead \.container:not\(:has\(\.asof\)\)::after\s*\{(.*?)\}', css, re.S)
    assert m, "자리 확보 규칙이 없습니다"
    body = m.group(1)
    assert re.search(r"visibility\s*:\s*hidden", body), (
        "자리표시자가 안 숨겨졌습니다 - 없는 기준일을 읽습니다")
    assert not re.search(r"display\s*:\s*none", body), (
        "display:none 은 자리까지 없앱니다")


def test_the_icon_box_owns_its_size_in_one_place(css):
    """⚠ 자리표시자가 배지의 **아이콘 자리**까지 비워야 폭이 맞는다.

    아이콘 폭·간격을 두 곳에 적으면 한쪽만 고쳐질 때 내비가 어긋난다 -
    실제로 2px 모자랐다. 토큰 하나로 묶는다 (§6).

    ⚠ 의사요소는 전역 `box-sizing:border-box` 를 안 받는다. 테두리가 밖으로
      붙어 겉폭이 토큰보다 커지므로 **명시**한다.
    """
    assert re.search(r"--asof-icon\s*:", css), "아이콘 폭 토큰이 없습니다"
    assert re.search(r"--asof-gap\s*:", css), "아이콘 간격 토큰이 없습니다"
    before = re.search(r"\.asof::before\s*\{(.*?)\}", css, re.S)
    assert before and "box-sizing:border-box" in before.group(1).replace(" ", ""), (
        "아이콘이 border-box 가 아닙니다 - 테두리만큼 자리표시자가 모자랍니다")
    after = re.search(
        r'\.masthead \.container:not\(:has\(\.asof\)\)::after\s*\{(.*?)\}', css, re.S)
    assert "--asof-icon" in after.group(1) and "--asof-gap" in after.group(1), (
        "자리표시자가 아이콘 토큰을 안 씁니다 - 값을 두 곳에 적은 것입니다")


def test_the_badge_box_is_described_in_one_place(css):
    """⚠⚠ **폭이 글자에서 나오므로 글꼴도 묶여야 한다.**

    2026-09-21 에 아이콘만 토큰으로 묶고 `font-size`·`line-height` 는 배지와
    자리표시자 두 곳에 따로 적었다. `.asof` 만 15px 로 바꾸면 자리표시자는
    14px 로 남아 폭이 어긋나는데 **앞선 검사 넷 중 어느 것도 그걸 안 물었다** -
    문자열은 보지만 글꼴은 안 봤다. 같은 실수를 같은 자리에서 두 번 했다.
    """
    for name in ("--asof-font", "--asof-line"):
        assert re.search(rf"{name}\s*:", css), f"{name} 토큰이 없습니다"

    for sel, label in (
        (r"\.asof\s*\{(.*?)\}", "배지"),
        (r'\.masthead \.container:not\(:has\(\.asof\)\)::after\s*\{(.*?)\}', "자리표시자"),
    ):
        m = re.search(sel, css, re.S)
        assert m, f"{label} 규칙을 못 찾았습니다"
        body = m.group(1)
        for prop, token in (("font-size", "--asof-font"), ("line-height", "--asof-line")):
            decl = re.search(rf"{prop}\s*:\s*([^;}}]+)", body)
            assert decl, f"{label}: {prop} 선언이 없습니다"
            assert token in decl.group(1), (
                f"글꼴이 두 곳에 따로 적혀 있습니다 - {label} 의 {prop} 가 "
                f"{decl.group(1).strip()!r} 입니다. 토큰 {token} 을 쓰세요")
