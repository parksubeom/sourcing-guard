"""[M-3] 커버리지 지도 — 집계는 순수 함수, 라벨은 매칭률, 축 판정은 관찰로만."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sourcing_guard.batch import BatchRow, RowVerdict  # noqa: E402


def _row(i, *, grade=None, items=(), verdict=RowVerdict.UNDECIDED, reason=""):
    return BatchRow(line=i, product_name=f"p{i}", grade=grade, matched_items=list(items),
                    verdict=verdict, reason=reason)


def test_summarize_counts_matched_silent_and_top_items():
    from domeggook_coverage_map import summarize

    rows = [
        _row(1, grade="안전확인", items=["완구"], verdict=RowVerdict.CERT_REQUIRED),
        _row(2, grade="안전확인", items=["완구", "물놀이기구"], verdict=RowVerdict.CHECK_SUPPLIER),
        _row(3, reason="상품명만으로 품목을 특정하지 못했습니다."),
        _row(4, verdict=RowVerdict.OUT_OF_SCOPE, reason="타 소관"),
    ]
    s = summarize(rows)
    assert s["n"] == 4 and s["matched"] == 2 and s["silent"] == 2
    assert s["matched_pct"] == 50.0 and s["silent_pct"] == 50.0
    assert s["top_items"][0] == ("완구", 2)
    assert s["silent_verdicts"] == {"undecided": 1, "out_of_scope": 1}
    assert s["axis_observed"] is True


def test_axis_is_observed_not_named():
    """카테고리 이름이 아니라 **붙었는가**로만 축을 말한다 (R5·R3)."""
    from domeggook_coverage_map import summarize

    assert summarize([_row(1), _row(2)])["axis_observed"] is False
    assert summarize([_row(1, items=["전기방석"])])["axis_observed"] is True
    src = (Path(__file__).resolve().parents[1] / "scripts/domeggook_coverage_map.py").read_text(encoding="utf-8")
    for banned in ("식품" + " in name", "비대상 =", "is_out_of_scope("):
        assert banned not in src, "카테고리 이름으로 축을 판정하고 있다"


def test_empty_category_does_not_divide_by_zero():
    from domeggook_coverage_map import summarize

    s = summarize([])
    assert s == {"n": 0, "matched": 0, "matched_pct": 0.0, "top_items": [], "silent": 0,
                 "silent_pct": 0.0, "silent_verdicts": {}, "silent_reasons": {}, "axis_observed": False}


def test_read_titles_groups_by_code_and_skips_comments(tmp_path):
    from domeggook_coverage_map import read_titles

    p = tmp_path / "상품명.tsv"
    p.write_text("# 라벨\n09_03_00_00_00\t완구/매트\t1\t블록 완구\n09_03_00_00_00\t완구/매트\t2\t튜브\n"
                 "12_08_00_00_00\t주방용품\t3\t프라이팬\n", encoding="utf-8")
    g = read_titles(p)
    assert g["09_03_00_00_00"] == ("완구/매트", ["블록 완구", "튜브"])
    assert g["12_08_00_00_00"] == ("주방용품", ["프라이팬"])


def test_the_label_says_matching_rate_not_accuracy():
    from domeggook_coverage_map import LABEL

    assert "매칭률" in LABEL and "검수 없음" in LABEL
    assert "정답률" not in LABEL
    src = (Path(__file__).resolve().parents[1] / "scripts/domeggook_coverage_map.py").read_text(encoding="utf-8")
    assert "기획서·랜딩" in src and "LLM 0회" in src
