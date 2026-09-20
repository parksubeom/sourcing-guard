"""소스 텍스트를 검사하는 검사들이 **자기 설명 문장에 걸리지 않게** 한다.

금지 문자열을 찾는 검사는 그 문자열을 자기 주석에 적게 되어 있다 - 왜 금지인지
설명해야 하기 때문이다. 이 함정에 이 프로젝트에서만 다섯 번 걸렸다:

    watch.html 의 주석 안 `⚠`      → test_no_emoji_anywhere
    주석 안 `glob("작업로그`         → 자기 AST 검사
    로그 줄의 `extract`             → 보고-누락 핸들러 가드
    docstring 의 `item_grades.yaml` → 별칭 채굴기 가드
    주석 안 `_PLACEHOLDER_CORE`      → 자리표시자 소유자 가드 (2026-09-12)

⚠ 여기 모아 두는 이유는 CLAUDE.md §6 "같은 판단을 두 곳에 적지 마라" 다. 전에는
  `test_domeggook_alias_candidates.py` 안에만 있어서 다음 검사가 다시 걸렸다.
"""
from __future__ import annotations

import ast
import io
import re
import textwrap
import tokenize as tk


def code_only(src: str) -> str:
    """docstring·주석을 벗긴 **코드**만 돌려준다.

    토큰을 공백으로 이어 붙이므로 호출부는 `"ALIASES . update"` 처럼 **띄어 쓴
    모양**으로 찾아야 한다. 원본 간격을 보존하지 않는 것은 의도다 - `f(x)` 와
    `f( x )` 가 같은 문자열이 된다.

    ⚠ `inspect.getsource` 로 **메서드**를 넘기면 들여쓰기가 남아 `ast.parse` 가
      IndentationError 를 낸다. 먼저 편다 - 파일 전체를 넘길 때는 아무것도
      바뀌지 않는다.
    """
    src = textwrap.dedent(src)
    tree = ast.parse(src)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d and node.body and isinstance(node.body[0], ast.Expr):
                e = node.body[0]
                doc_lines.update(range(e.lineno, e.end_lineno + 1))
    out: list[str] = []
    for tok in tk.generate_tokens(io.StringIO(src).readline):
        if tok.type == tk.COMMENT or tok.start[0] in doc_lines:
            continue
        out.append(tok.string)
    return " ".join(out)


#: 마크업·JS 주석. **파이썬은 `code_only`, 마크업은 이것**이다.
#:
#: ⚠⚠ 왜 여기 모으나: 2026-09-20 에 같은 함정에 하루 세 번 걸렸는데, 그때마다
#:   검사 파일 안에 정규식을 새로 썼다. 실측으로 **다섯 벌**이었다 -
#:   `test_design_tokens` · `test_experience_samples` · `test_frontend` 셋.
#:   규칙을 적은 주석이 그 규칙에 걸리는 것을 막는 규칙 자체가 다섯 벌이면
#:   그것이 §6 위반이다.
#:
#: ⚠⚠ **`//` 를 줄 끝까지 지우면 `https://` 가 사라진다.** 그러면 금지어가 URL
#:   뒤에 숨어 검사가 **조용히 통과**한다 - "Claude" 가 "Claude Code" 에 걸려
#:   런타임 벤더 주장이 한 번도 안 잠겨 있던 것과 같은 모양이다.
#:   그래서 **앞이 공백이거나 줄머리일 때만** 주석으로 본다.
#:
#: ⚠ `(?<![:/])` 만으로는 모자랐다(실측). `http://a//b` 의 **경로 안 `//`** 는
#:   앞이 `a` 라 그 조건을 통과해, 그 뒤가 통째로 지워졌다 - 지우는 방향만
#:   다를 뿐 같은 종류의 조용한 제거다.
_BLOCK_COMMENT = re.compile(r"<!--.*?-->|/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"(?:(?<=^)|(?<=\s))//[^\n]*", re.M)


#: 이모지·기호 구간. **화면 어디에도 쓰지 않는다** - 상태는 색·아이콘·글자로
#: 말한다.
#:
#: ⚠⚠ 판단이 세 곳에 있었다 - `test_no_emoji_anywhere` 가 구간을 적고,
#:   `test_watch_autosweep` 이 `⚠` 하나만 따로 적고, 2026-09-20 에
#:   `misses.json` 의 설명글을 재려다 네 번째를 쓸 뻔했다. 오너는 여기다 (§6).
#:
#: ⚠ `⚠`(U+26A0)는 `0x2600-0x27BF` 안에 있다. 구간을 좁히면 우리가 주석에 제일
#:   많이 쓰는 그 기호가 화면에 나가도 안 걸린다.
_EMOJI_RANGES = ((0x1F300, 0x1FAFF), (0x2600, 0x27BF))


def emoji_chars(text: str) -> list[str]:
    """`text` 안의 이모지·기호를 **찾은 순서대로** 돌려준다. 없으면 빈 목록."""
    return [c for c in text
            if any(lo <= ord(c) <= hi for lo, hi in _EMOJI_RANGES)]


def markup_only(src: str) -> str:
    """HTML·CSS·JS 에서 **주석을 뺀 것**. 화면에 실제로 나가는 것만 남는다.

    금지 문자열·중복 검사는 이것을 통해서 본다. 주석까지 보면 "이 낱말을 쓰지
    마라" 라고 적은 주석이 그 검사에 걸린다.

    ⚠ 원본 간격과 줄 수를 **보존한다**(주석 자리를 공백으로 바꾸지 않고 지운다
      것이 아니라 빈 문자열로 만든다). 줄 번호가 필요한 호출부는 없다.

    ⚠ `https://` 는 살아남는다 - 위 `_LINE_COMMENT` 주석 참조. 그 보장이
      `tests/test_srccheck.py` 에 잠겨 있다.
    """
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", src))
