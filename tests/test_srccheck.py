"""주석 제거의 **오너가 하나**인지, 그리고 그것이 URL 을 안 지우는지.

왜 있나
-------
금지 문자열·중복을 찾는 검사는 그 문자열을 **자기 주석에 적게 되어 있다** -
왜 금지인지 설명해야 하기 때문이다. `tests/srccheck.py` 는 그 함정 하나만을
위해 존재하고 머리 주석에 다섯 건이 열거돼 있다.

⚠⚠ 그런데 2026-09-20 까지 파이썬용 `code_only` 하나뿐이라 **마크업 쪽은 검사
  파일마다 정규식을 새로 썼다.** 실측으로 다섯 벌이었다
  (`test_design_tokens` · `test_experience_samples` · `test_frontend` 셋).
  규칙을 적은 주석이 그 규칙에 걸리는 것을 막는 규칙 자체가 다섯 벌이면
  그것이 §6 위반이다.
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
#: ⚠⚠ 총괄 지적은 "다섯 벌" 이었는데 **실측은 열둘(파일 기준)** 이다. 세 보고
#:   적는다 - 잰 수와 다른 수를 옮기지 않는다.
#:
#: ⚠ 이 목록은 **옮길 일감**이지 면제가 아니다. 기존 것들은 줄머리 `//` 만
#:   지워서 URL 함정에는 안 걸린다(그래서 오늘 급하지 않다). 그러나 같은
#:   판단이 열두 곳에 있으면 한 곳만 고쳐질 때 나머지가 조용히 거짓말한다.
#:
#: ⚠ **줄이는 방향으로만 바꾼다.** 새 이름을 여기 더하려면 그 파일이 왜
#:   `markup_only` 를 못 쓰는지 적어야 한다.
_STILL_OWN_THEIR_REGEX = {
    "test_frontend.py",          # 남은 한 자리 (세 자리 중 둘은 옮겼다)
    "test_guide.py",
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

    ⚠⚠ 이 검사는 **늘어나는 것만** 막는다. 이미 있는 열둘은 옮길 일감이고
      `_STILL_OWN_THEIR_REGEX` 에 적혀 있다 - 줄이는 방향으로만 바꾼다.
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
