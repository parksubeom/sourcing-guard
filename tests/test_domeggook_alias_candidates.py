"""[M-4] 별칭 후보 발굴 — 어절 규칙, 표 대조, 그리고 **아무것도 자동으로 넣지 않는다**."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

_ROOT = Path(__file__).resolve().parents[1]


def test_tokenize_splits_on_separators_and_strips_brackets_and_numbers():
    from domeggook_alias_candidates import tokenize

    t = tokenize("[도매라인] *땡처리* 워터슈즈/아쿠아샌들, 250mm 2P+사은품 (남녀공용) 1+1")
    assert "도매라인" in t and "땡처리" in t and "워터슈즈" in t and "아쿠아샌들" in t
    assert "250mm" not in t and "2P" not in t and "1+1" not in t     # 숫자·규격은 어절 후보가 아니다
    assert "남녀공용" in t                                              # 노이즈여도 tokenize 는 남긴다
    assert all(len(x) >= 2 for x in t)


def test_tokens_are_eojeol_not_morphemes():
    """형태소 분석기를 쓰지 않는다 - '기모장갑' 과 '장갑' 은 다른 어절이다."""
    from domeggook_alias_candidates import tokenize

    assert tokenize("기모장갑 장갑") == ["기모장갑", "장갑"]


def test_count_tokens_counts_once_per_title_and_keeps_examples():
    from domeggook_alias_candidates import count_tokens

    silent = [("모자", "물놀이 썬캡 물놀이"), ("신발", "물놀이 워터슈즈"), ("가방", "크로스백")]
    freq, cats, ex = count_tokens(silent)
    assert freq["물놀이"] == 2 and cats["물놀이"] == {"모자", "신발"}   # 같은 제목 안 중복은 1회
    assert len(ex["물놀이"]) == 2


def test_in_table_marks_item_names_and_aliases():
    from domeggook_alias_candidates import in_table
    from sourcing_guard.item_grades import ALIASES, ItemGradeBook

    book = ItemGradeBook()
    assert in_table("선글라스", book) == "품목명"
    some_alias = next(iter(ALIASES))
    assert in_table(some_alias, book) in ("별칭", "품목명")
    assert in_table("zzz없는어절zzz", book) == ""


def _code_only(src: str) -> str:
    """docstring·주석을 벗긴 **코드**만. 금지 문자열이 설명 문장에 있으면 걸리는
    자기 문구 함정을 피한다 - 이 검사도 처음에 그렇게 걸렸다(이번 주 네 번째)."""
    import ast, io, tokenize as tk

    tree = ast.parse(src)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(node, clean=False)
            if d and node.body and isinstance(node.body[0], ast.Expr):
                e = node.body[0]
                doc_lines.update(range(e.lineno, e.end_lineno + 1))
    out = []
    for tok in tk.generate_tokens(io.StringIO(src).readline):
        if tok.type == tk.COMMENT or tok.start[0] in doc_lines:
            continue
        out.append(tok.string)
    return " ".join(out)


def test_the_script_never_touches_the_grade_table():
    """⚠⚠ 자동 삽입 금지. 표·별칭을 **쓰는 코드**가 없어야 한다 (설명 문장은 제외)."""
    src = (_ROOT / "scripts/domeggook_alias_candidates.py").read_text(encoding="utf-8")
    code = _code_only(src)
    for banned in ("item_grades.yaml", "ALIASES [", "ALIASES . update", "ALIASES . setdefault",
                   "yaml . dump", "yaml . safe_dump", "ALIASES ="):
        assert banned not in code, f"별칭을 자동으로 쓰려 한다: {banned}"
    # 설명은 있어야 한다 - 이건 원문(docstring 포함)에서 본다.
    assert "자동 삽입 금지" in src and "판정·근거는 사람이 채운다" in src


def test_noise_filter_only_affects_the_candidate_file():
    """노이즈 목록은 읽기 편의다 - 전체 파일에는 남아야 한다."""
    src = (_ROOT / "scripts/domeggook_alias_candidates.py").read_text(encoding="utf-8")
    assert "어절빈도_전체.tsv" in src and "노이즈 미제거" in src
    assert "if t not in _NOISE" in src            # 후보 파일에서만
