"""미검수 목록 파일이 **재생값과 어긋나면 실패한다.**

⚠⚠ 이 검사가 없어서 파일이 낡았다. 2026-09-11 판이 20줄이었는데 재생의 ②는
  18 이었다 - 애매 줄 2건을 섞었기 때문이다. 파일이 "검수할 것이 20개" 라고
  다섯 달 동안 말할 수 있었다.

CLAUDE.md §6: 손으로 유지하는 목록은 반드시 낡는다. 재생에서 뽑고 검사로 묶는다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CURRENT = _ROOT / "tests/fixtures/미검수_gpt_2026-09-12.tsv"
_SUPERSEDED = _ROOT / "tests/fixtures/미검수_gpt.tsv"


def _sections(path: Path) -> dict[str, list[str]]:
    """`# ── [이름] …` 로 갈린 절 → 데이터 줄 목록."""
    out: dict[str, list[str]] = {}
    cur = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"#\s*──\s*\[([^\]]+)\]", line)
        if m:
            cur = m.group(1)
            out.setdefault(cur, [])
            continue
        if line.startswith("#") or not line.strip():
            continue
        if cur:
            out[cur].append(line)
    return out


def test_the_unreviewed_file_matches_a_fresh_replay():
    """⚠⚠ **② 미검수 절의 줄 수 == 재생의 `unreviewed`.**

    다르면 규칙이 바뀌어 미검수 집합이 움직였는데 파일이 안 따라온 것이다.
    고치는 법: `python scripts/export_unreviewed.py --out <파일>`
    """
    sys.path.insert(0, str(_ROOT / "scripts"))
    from audit_tally import BASELINE, BASELINE_EXTRACTOR

    sections = _sections(_CURRENT)
    assert "② 미검수" in sections, "② 절이 없다 - 파일 모양이 바뀌었다"

    expected = BASELINE[BASELINE_EXTRACTOR]["unreviewed"]
    got = len(sections["② 미검수"])
    assert got == expected, (
        f"미검수 파일이 {got}줄인데 기준선 ② 는 {expected} 다. "
        f"규칙이 바뀌었으면 다시 뽑아라: "
        f"python scripts/export_unreviewed.py --out {_CURRENT.name}"
    )


def test_the_file_matches_the_script_output_row_for_row():
    """줄 수만 맞고 **내용이 다른** 경우를 막는다.

    ⚠ 줄 수 검사만 두면 한 줄이 빠지고 다른 줄이 들어와도 통과한다.
    """
    sys.path.insert(0, str(_ROOT / "scripts"))
    import os

    cwd = os.getcwd()
    os.chdir(_ROOT)
    try:
        from export_unreviewed import collect

        fresh = collect()
    finally:
        os.chdir(cwd)

    sections = _sections(_CURRENT)
    on_file = {ln.split("\t")[0] for sec in sections.values() for ln in sec}
    from_script = {r["name"] for r in fresh}
    assert on_file == from_script, (
        f"파일에만 있는 줄 {sorted(on_file - from_script)} · "
        f"스크립트에만 있는 줄 {sorted(from_script - on_file)}"
    )


def test_the_appendix_keeps_the_pairs_that_are_not_in_the_second_criterion():
    """애매·비대상 줄의 미검수 쌍을 **빼지 않고 부록으로 남긴다.**

    ⚠ ② 분모는 대상 135 라 애매 줄은 ② 에 안 들어간다. 그렇다고 파일에서
      빼면 **검수 대기가 조용히 사라진다** - 화면에는 뜨고 ⑤ 로 세어진다.
    """
    sections = _sections(_CURRENT)
    assert "부록" in sections
    for line in sections["부록"]:
        assert line.split("\t")[4] != "대상", "대상 줄이 부록에 있다 - ② 로 가야 한다"
    for line in sections["② 미검수"]:
        assert line.split("\t")[4] == "대상"


def test_the_old_file_says_it_was_superseded():
    """옛 파일을 지우지 않고 **대체됨**을 적는다 - 그 날의 기록이다.

    ⚠ 지우면 "왜 20이었나" 에 답할 수 없다. 남기되 쓰지 못하게 한다.
    """
    head = _SUPERSEDED.read_text(encoding="utf-8")[:1200]
    assert "대체됨" in head and "20줄 시점" in head
    assert _CURRENT.name in head, "정본 파일 이름이 없다"


@pytest.mark.parametrize("path", [_CURRENT])
def test_every_row_is_still_unjudged(path: Path):
    """판정 칸이 비어 있어야 한다 - 채워지면 오답/정답 파일로 옮긴다.

    ⚠ 판정을 이 파일에 적고 끝내면 재생이 그것을 못 본다. 집계는
      `새표본235_오답.tsv` 와 검수 쌍 목록만 읽는다.
    """
    for sec in _sections(path).values():
        for line in sec:
            cols = line.split("\t")
            assert cols[-1].strip() == "", f"판정이 적혔다 - 옮겨라: {cols[0][:40]}"
