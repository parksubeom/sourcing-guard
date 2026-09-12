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
