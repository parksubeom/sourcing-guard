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


# ── 기준선 표가 코드와 갈리지 않게 ──────────────────────────────
def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_the_baseline_table_matches_the_code():
    """⚠⚠ **R7 의 기준선 표는 `baseline.py` 를 옮겨 적은 것이다.**

    같은 판단이 두 곳에 있으므로 갈릴 수 있고, 실제로 갈렸다 - 2026-09-14
    ⑦-c 검수로 다섯 숫자가 움직였는데(95→104 · 18→0 · 113→104) **CLAUDE.md 만
    옛 값을 들고 있었고, 그것을 상시 지침으로 읽으며 반나절을 일했다.**

    §6: "같은 판단을 두 곳에 적지 마라. 갈릴 수 있는 판단은 소유자를 하나
    정하고 나머지는 그것을 부른다." 소유자는 `baseline.py` 다.

    ⚠⚠ **"사람이 읽는 사본이라 부를 수 없다" 는 결론이 아니다.** 사람이 읽는
      사본도 **생성물이 될 수 있다** - 마커 사이를 스크립트가 렌더하고, 검사는
      "다시 생성했을 때 diff 가 0 인가" 를 본다:

          <!-- BASELINE:BEGIN -->  …  <!-- BASELINE:END -->

      지금(검사) 두 곳에 손으로 적고 어긋나면 **어긋난 뒤에** 알려 준다.
      생성이면 한 곳에만 적고 **어긋날 수가 없다.** 마커 사이만 갈아 끼우므로
      §6 의 "주석이 자산이다" 도 안 어긴다.

    ⚠ 지금은 검사로 묶는다 - 프리즈가 가깝고 이 검사는 실제로 문다.
      생성 블록은 **본선 과제**로 `docs/미완_목록.md` 에 적어 뒀다.
    """
    from sourcing_guard.baseline import BASELINE, BASELINE_EXTRACTOR

    b = BASELINE[BASELINE_EXTRACTOR]
    body = _flat(_section("R7."))

    def pct(n: int) -> str:
        return f"{n / b['denominator'] * 100:.1f}%"

    wanted = (
        f"분모 {b['denominator']}",
        f"① 검수된 정답 {b['ok']} ({pct(b['ok'])})",
        f"② 미검수 {b['unreviewed']}",
        f"③ 상한 {b['ok_upper']} ({pct(b['ok_upper'])})",
        f"애매 {b['vague']} · 오답 {b['wrong']} · 미매칭 {b['missed']}",
        f"④ 비대상 부착 {b['off_target']}",
        f"⑤ 애매 부착 {b['on_vague']}",
    )
    missing = [w for w in wanted if w not in body]
    assert not missing, (
        "CLAUDE.md 의 기준선 표가 baseline.py 와 다르다. 표를 고쳐라 - "
        f"없는 줄: {missing}"
    )


def test_the_baseline_table_names_the_reference_extractor():
    """어느 추출기 기준인지 표에 적혀 있어야 한다 (R7)."""
    from sourcing_guard.baseline import BASELINE_EXTRACTOR

    body = _section("R7.")
    assert BASELINE_EXTRACTOR.upper() in body or BASELINE_EXTRACTOR in body
