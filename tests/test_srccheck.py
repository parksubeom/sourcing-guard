"""주석 제거의 **오너가 하나**인지, 그리고 그것이 URL 을 안 지우는지.

왜 있나
-------
금지 문자열·중복을 찾는 검사는 그 문자열을 **자기 주석에 적게 되어 있다** -
왜 금지인지 설명해야 하기 때문이다. `tests/srccheck.py` 는 그 함정 하나만을
위해 존재하고 머리 주석에 다섯 건이 열거돼 있다.

⚠⚠ 그런데 2026-09-20 까지 파이썬용 `code_only` 하나뿐이라 **마크업 쪽은 검사
  파일마다 정규식을 새로 썼다.** 실측으로 다섯 벌이었다
  규칙을 적은 주석이 그 규칙에 걸리는 것을 막는 **규칙 자체가 여러 벌**이면
  그것이 §6 위반이다. 옮긴 것과 남은 것은 `_STILL_OWN_THEIR_REGEX` 가 센다 -
  여기 수를 적지 않는다(적으면 그 수가 낡는다).
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.srccheck import code_only, markup_only

_TESTS = Path(__file__).resolve().parent


def test_the_stripper_keeps_urls():
    """⚠⚠ **`//` 를 줄 끝까지 지우면 `https://` 가 사라진다.**

    그러면 금지어가 URL 뒤에 숨어 검사가 **조용히 통과**한다 - "Claude" 가
    "Claude Code" 에 걸려 런타임 벤더 주장이 한 번도 안 잠겨 있던 것과 같다.
    """
    kept = markup_only('<a href="https://law.go.kr/x">안전합니다</a>')
    assert "https://law.go.kr/x" in kept, "URL 이 사라졌다"
    assert "안전합니다" in kept, "URL 뒤 금지어가 사라졌다 - 검사가 조용히 통과한다"


def test_the_stripper_keeps_text_after_a_url_path_slash():
    """⚠ `(?<![:/])` 만으로는 모자랐다 (실측).

    `http://a//b` 의 **경로 안 `//`** 는 앞이 `a` 라 그 조건을 통과해, 그 뒤가
    통째로 지워졌다. 지우는 방향만 다를 뿐 같은 종류의 조용한 제거다.
    """
    kept = markup_only('fetch("http://a//b"); 안전합니다')
    assert "안전합니다" in kept, "URL 경로의 // 뒤가 지워졌다"


def test_the_stripper_removes_every_comment_style():
    for src in ('<!-- 안전합니다 --><p>x</p>',
                '/* 안전합니다 */ .x{color:red}',
                'var x = 1; // 안전합니다',
                '  // 안전합니다',
                '//안전합니다'):
        assert "안전합니다" not in markup_only(src), src


#: 아직 자기 정규식을 쓰는 검사 파일. **여기 있는 것만 봐준다.**
#:
#: ⚠⚠ 총괄 지적은 "다섯 벌" 이었고 처음 재 보니 **파일 열하나**였다(자리로는
#:   열넷). 내가 보고에 "열둘" 이라 적은 적이 있는데 그것도 틀렸다 - 세 보고
#:   적는 규칙을 적으면서 내가 안 셌다.
#:   **수를 산문에 다시 적지 않는다.** 이 집합이 곧 수다.
#:
#: ⚠ 이 목록은 **옮길 일감**이지 면제가 아니다. 기존 것들은 줄머리 `//` 만
#:   지워서 URL 함정에는 안 걸린다(그래서 급하지 않다). 그러나 같은 판단이
#:   여러 곳에 있으면 한 곳만 고쳐질 때 나머지가 조용히 거짓말한다.
#:
#: ⚠ **줄이는 방향으로만 바꾼다.** 이름을 지우면 통과하고, 더하려면 그 파일이
#:   왜 `markup_only` 를 못 쓰는지 적어야 한다.
#:   2026-09-20 화면 말 다듬기에서 `test_guide.py` 를 옮겼다.
_STILL_OWN_THEIR_REGEX = {
    "test_frontend.py",          # 남은 한 자리 (세 자리 중 둘은 옮겼다)
    "test_item_grades.py",
    "test_landing.py",
    "test_landing_empty_values.py",
    "test_landing_preview.py",
    "test_landing_why.py",
    "test_no_repeated_facts.py",
    "test_static_cache_and_font.py",
    "test_watch_autosweep.py",
    "test_watchlist.py",
}


def test_no_new_test_file_writes_its_own_comment_regex():
    """⚠ 검사 파일 안에서 주석 정규식을 **새로 쓰지 않는다.**

    쓰면 이 규칙이 또 한 벌 늘고, 그 파일은 URL 함정을 자기 힘으로 피해야
    한다. 오너는 `tests/srccheck.markup_only` 다.

    ⚠⚠ 이 검사는 **늘어나는 것만** 막는다. 남은 것은
      `_STILL_OWN_THEIR_REGEX` 가 들고 있고 **줄이는 방향으로만** 바뀐다.
    """
    found = set()
    for path in sorted(_TESTS.glob("test_*.py")):
        if path.name == "test_srccheck.py":
            continue
        src = code_only(path.read_text(encoding="utf-8"))
        for pattern in ('"<!--', "'<!--", r'"^\s*//', r"/\*.*?\*/"):
            if pattern in src:
                found.add(path.name)
    new = found - _STILL_OWN_THEIR_REGEX
    assert not new, (
        "주석 제거 정규식을 새로 쓴 파일이 있습니다. "
        "`from tests.srccheck import markup_only` 를 쓰세요:\n  "
        + "\n  ".join(sorted(new)))

    gone = _STILL_OWN_THEIR_REGEX - found
    assert not gone, (
        "옮긴 파일이 목록에 남아 있습니다. 지우세요(목록은 줄어야 합니다):\n  "
        + "\n  ".join(sorted(gone)))


def test_the_owner_is_documented_where_the_trap_is_listed():
    """다음 사람이 함정 목록을 읽을 때 오너 이름이 같이 보여야 한다."""
    head = (_TESTS / "srccheck.py").read_text(encoding="utf-8")
    assert "markup_only" in head
    assert "code_only" in head
    assert re.search(r"https://", head), "URL 함정이 안 적혀 있다"


def test_a_file_rewriting_script_checks_its_own_output():
    """⚠⚠ 파일을 제자리에서 고쳐 쓰는 코드는 **쓴 뒤에 성한지 스스로 단정**한다.

    2026-09-20 에 `s.index(":root{")` 가 머리 주석 안의 `:root{` 를 먼저 물어
    `design/tokens.css` 와 `app.css` 의 머리를 부쉈다. 두 파일을 대조하는
    검사가 있었지만 **둘이 똑같이 부서져서 통과했다.**

    그래서 토큰 파일의 성함을 여기서 직접 본다 - 대조가 아니라 **모양**이다.
    """
    import re as _re

    root = _TESTS.parent
    for path in (root / "design/tokens.css", root / "sourcing_guard/static/app.css"):
        src = path.read_text(encoding="utf-8")
        assert src.lstrip().startswith("/*"), f"{path.name}: 머리 주석이 사라졌다"
        opens = len(_re.findall(r"^:root\{", src, _re.M))
        assert opens == 1, f"{path.name}: 줄머리 :root 블록이 {opens}개다 (1이어야 한다)"
        body = markup_only(src)
        i = _re.search(r"^:root\{", body, _re.M).end()
        block = body[i:body.index("}", i)]
        n = len(_re.findall(r"--[a-z0-9-]+\s*:", block))
        assert n >= 50, f"{path.name}: :root 변수가 {n}개다 - 블록이 잘렸다"
