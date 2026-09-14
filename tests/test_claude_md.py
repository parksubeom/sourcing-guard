"""규칙 문서가 규칙을 실제로 담고 있는지 잠근다 (CLAUDE.md §2).

⚠ 규칙이 문서에만 있고 아무도 안 보면 §6 의 "예정·미구현을 명시한다" 와 같은
  자리가 된다 - 적어 두고 지키지 않는 자리다. 여기서는 **R5-b 가 근거를 달고
  있는지**만 본다. 규칙 본문을 통째로 베껴 잠그면 문구를 다듬을 때마다 깨져서
  아무도 안 보게 되므로, **없어지면 규칙이 근거를 잃는 것**만 고른다.

⚠ 반대 방향도 잰다 - 절만 있고 사례가 사라지면 실패한다. R5-b 는 "고시가
  정한다" 이므로 **어느 판의 고시인지**(행정규칙일련번호)가 빠지면 규칙이
  스스로를 어긴다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_RULES = Path(__file__).resolve().parents[1] / "CLAUDE.md"

#: R5-b 사례의 출처. 2026-09-14 에 lawSearch 로 현행 판을 확인한 값이다
#: (웹 화면의 admRulSeq 2100000135271 은 옛 판이었다).
_SEQ = "2100000263200"


def _section(name: str) -> str:
    """`### <name>` 부터 다음 `### ` 직전까지."""
    text = _RULES.read_text(encoding="utf-8")
    hits = [m for m in re.finditer(r"^### (.+)$", text, re.M)]
    for i, m in enumerate(hits):
        if m.group(1).startswith(name):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
            return text[m.start():end]
    pytest.fail(f"CLAUDE.md 에 '### {name}' 절이 없다")


def test_r5b_exists_between_r5_and_r6():
    """R5-b 는 §2 안, R5 와 R6 사이에 있다."""
    text = _RULES.read_text(encoding="utf-8")
    order = [m.group(1) for m in re.finditer(r"^### (R\d[\w-]*)\.", text, re.M)]
    assert "R5-b" in order, f"R5-b 절이 없다 - 지금 있는 것: {order}"
    assert order.index("R5") < order.index("R5-b") < order.index("R6"), order


def test_r5b_cites_the_notice_it_came_from():
    """규칙이 근거를 달고 있다 - 사례가 사라지면 실패한다."""
    body = _section("R5-b.")
    assert _SEQ in body, (
        f"R5-b 에 행정규칙일련번호 {_SEQ} 가 없다. 규칙이 '고시가 정한다' 인데 "
        "어느 판의 고시인지 안 적으면 규칙이 스스로를 어긴다"
    )
    assert "시행" in body, "R5-b 에 시행일이 없다 - 원문은 개정된다"
    assert "부속서" in body, "R5-b 에 부속서 번호가 없다"


def test_r5b_keeps_the_three_branches():
    """세 갈래가 다 있다 - '모름' 갈래가 빠지면 R3 와 끊긴다."""
    body = _section("R5-b.")
    for mark in ("①", "②", "③"):
        assert mark in body, f"R5-b 의 {mark} 갈래가 없다"
    assert "R3" in body, "R5-b 의 ② 갈래가 R3(모름)를 가리키지 않는다"
