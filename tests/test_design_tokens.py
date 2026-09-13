"""[제출-2 단계 1~3] 디자인 토큰이 **두 파일에서 갈리지 않는지** 잠근다.

`design/tokens.css` 가 정본이고 `app.css` 는 그것을 옮겨 온 것이다. 같은 값을
두 곳에 적었으므로 **한쪽만 고치면 화면과 견본이 어긋난다** (CLAUDE.md 6절
"같은 판단을 두 곳에 적지 마라" 의 CSS 판).

⚠ 합치지 않은 이유: `design/` 은 견본(브라우저로 바로 여는 것)이고 `app.css` 는
  배포본이 서빙하는 것이다. 견본이 배포 경로에 의존하면 디자이너가 못 연다.
  그래서 **두 벌을 두되 검사로 묶는다.**
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TOKENS = _ROOT / "design/tokens.css"
_APP = _ROOT / "sourcing_guard/static/app.css"
_STATIC = _ROOT / "sourcing_guard/static"
_SCREENS = ("index.html", "landing.html", "batch.html", "watch.html")

_VAR = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;}]+)")


def _strip_comments(text: str) -> str:
    """`/* … */` 를 걷어낸다.

    ⚠⚠ 두 파일의 **머리 주석이 `:root{ … }` 를 설명 문장으로 담는다**
      ("app.css 의 `:root{ … }` 블록을 이 파일의 :root 블록으로 바꾼다").
      안 걷으면 첫 `:root{` 가 주석이라 변수를 0개로 센다 - 윈도우 세션이
      토큰을 대조할 때 겪은 것과 **같은 함정**이다(작업로그 09-13 §2.2).
    """
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _vars_in_root(text: str) -> dict[str, str]:
    """줄 맨 앞의 `:root{…}` 블록. 다크(`  :root:not(...)`)는 들여써 있어 안 걸린다."""
    body = _strip_comments(text)
    m = re.search(r"^:root\{", body, re.M)
    assert m, ":root 블록을 못 찾았다"
    j = body.index("}", m.end())
    out = {v.group(1): v.group(2).strip() for v in _VAR.finditer(body[m.end():j])}
    assert out, ":root 블록에서 변수를 하나도 못 읽었다 - 파서를 의심하라"
    return out


def test_app_css_carries_every_token_with_the_same_value():
    """⚠⚠ 정본(`design/tokens.css`)의 `:root` 값이 `app.css` 와 같아야 한다."""
    want = _vars_in_root(_TOKENS.read_text(encoding="utf-8"))
    got = _vars_in_root(_APP.read_text(encoding="utf-8"))
    missing = sorted(k for k in want if k not in got)
    assert not missing, f"app.css 에 없는 토큰: {missing}"
    diff = {k: (want[k], got[k]) for k in want if got[k] != want[k]}
    assert not diff, (
        "값이 갈렸다 - `design/tokens.css` 가 정본이다:\n  "
        + "\n  ".join(f"{k}: 정본 {a} · app {b}" for k, (a, b) in diff.items())
    )


def test_no_old_variable_name_disappeared():
    """⚠ 이름이 하나 빠지면 **그 규칙만 조용히 무효**가 되고 화면이 반쯤 망가진다.

    실측(2026-09-13): 교체 전 app.css 43개 중 빠진 이름 **0** · 새 이름 24.
    """
    text = _strip_comments(_APP.read_text(encoding="utf-8"))
    # ⚠ 폴백이 있으면(`var(--x, 기본값)`) 선언이 없어도 규칙이 살아 있다.
    #   결함은 **폴백 없는** 것만이다.
    no_fallback = set(re.findall(r"var\((--[a-z0-9-]+)\s*\)", text))
    declared = set(re.findall(r"(--[a-z0-9-]+)\s*:", text))
    undeclared = sorted(no_fallback - declared)
    assert not undeclared, (
        f"선언 없이(폴백도 없이) 쓰는 변수: {undeclared}\n"
        "CSS 는 정의 안 된 var() 가 든 **선언을 통째로 무효**로 만든다 - "
        "그 규칙이 화면에서 조용히 사라진다"
    )


def test_the_signal_colours_exist_and_unknown_stays_grey():
    """신호등 색이 있고 **UNKNOWN 은 회색**이다 (R3 · 회색은 모름이다)."""
    v = _vars_in_root(_APP.read_text(encoding="utf-8"))
    for name in ("--signal-green", "--signal-amber", "--signal-red", "--signal-unknown"):
        assert name in v, f"{name} 이 없다"
    grey = v["--signal-unknown"].lower()
    # 회색 = R·G·B 가 서로 가깝다. 초록·주황·빨강 계열이면 안 된다.
    m = re.fullmatch(r"#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})", grey)
    assert m, f"--signal-unknown 이 6자리 hex 가 아니다: {grey}"
    r, g, b = (int(x, 16) for x in m.groups())
    assert max(r, g, b) - min(r, g, b) <= 24, (
        f"--signal-unknown 이 회색이 아니다 ({grey}) - 회색불은 '모름' 이고 "
        "색을 주면 판정으로 읽힌다 (R3)"
    )


@pytest.mark.parametrize("name", _SCREENS)
def test_every_screen_links_the_fonts_and_favicon(name: str):
    """네 화면이 같은 폰트·파비콘을 쓴다 (README 8-3)."""
    html = (_STATIC / name).read_text(encoding="utf-8")
    assert "fonts.googleapis.com/css2?family=Gowun+Dodum" in html, f"{name}: 폰트 링크 없음"
    assert 'href="/static/favicon.svg"' in html, f"{name}: 파비콘 없음"
    # ⚠ 폰트는 app.css 보다 **먼저** 요청돼야 한다 - 나중이면 첫 그림에서 기본
    #   서체로 한 번 그려졌다가 바뀐다.
    assert html.index("fonts.googleapis.com") < html.index("app.css"), (
        f"{name}: 폰트 링크가 app.css 뒤에 있다"
    )


def test_the_favicon_is_actually_there():
    assert (_STATIC / "favicon.svg").is_file(), "favicon.svg 가 static 에 없다"
    assert (_STATIC / "favicon.svg").read_text(encoding="utf-8").lstrip().startswith("<svg")


def test_the_page_background_and_card_are_different():
    """페이지는 크림, 카드는 흰색으로 갈린다 (README 8-2).

    ⚠ 같으면 카드가 배경에 묻혀 결과 영역의 경계가 사라진다.
    """
    v = _vars_in_root(_APP.read_text(encoding="utf-8"))
    assert "--bg-page" in v and "--bg-canvas" in v
    assert v["--bg-page"].lower() != v["--bg-canvas"].lower()
    assert "background:var(--bg-page)" in _APP.read_text(encoding="utf-8")
