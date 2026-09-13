"""디자인 참조의 축 수를 **코드에 묶는다** ([제출-2 3/3] · 2026-09-13).

`design/` 의 참조 마크업이 오래 "축 넷(품목 등급 · 인증 · 유해물질 · 리콜)" 으로
적혀 있었다. 실제 `scorer._axes` 가 주는 것은 **셋**이고, 품목 등급은 축이 아니라
첫 finding 이다. 참조에 넷을 그려 두면 화면이 **오지 않을 축의 자리를 비워 두고**,
셀러는 그 빈칸을 "조회 실패" 로 읽는다.

이 프로젝트에서 반복되는 결함이 **문서가 코드보다 앞서 나가는 것**이라, 숫자를
문서에 다시 적는 대신 코드에서 세서 비교한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from sourcing_guard.models import Finding, FindingKind, Signal
from sourcing_guard.scorer import _axes

_DESIGN = Path("design")
_REFS = ("README.md", "result-card.html", "loading.html")


def _axes_block(html: str, name: str) -> str:
    """`.axes` 컨테이너 **안쪽**만 잘라낸다.

    ⚠ 처음에 `<div class="axes">(.*?)</div>` 로 잡았다가 걸렸다 - 비탐욕
      매칭이 **첫 칸의 닫는 태그**에서 멈춰 칸을 1개로 셌다. 중첩된 div 는
      정규식으로 못 센다. 여는 줄의 들여쓰기와 같은 `</div>` 줄까지 읽는다.
    """
    lines = html.splitlines()
    for i, line in enumerate(lines):
        if '<div class="axes">' in line:
            indent = len(line) - len(line.lstrip())
            for j in range(i + 1, len(lines)):
                cur = lines[j]
                if cur.strip() == "</div>" and len(cur) - len(cur.lstrip()) == indent:
                    return "\n".join(lines[i + 1 : j])
            raise AssertionError(f"{name}: .axes 블록이 안 닫힌다")
    raise AssertionError(f"{name}: .axes 블록을 못 찾았다")


def _axis_names() -> list[str]:
    """`scorer` 가 실제로 내는 축 이름. 여기가 단일 출처다."""
    return [a["name"] for a in _axes([], None)]


def test_the_server_still_sends_exactly_three_axes():
    """축 수가 바뀌면 참조·화면·이 검사를 **함께** 옮긴다는 신호다."""
    assert _axis_names() == ["인증 조회", "리콜 대조", "유해물질"], _axis_names()


def test_the_item_grade_is_a_finding_not_an_axis():
    """품목 등급을 축으로 되돌리면 여기서 깨진다.

    ⚠ 등급 finding 을 넣어도 축은 셋 그대로여야 한다.
    """
    grade = Finding(
        kind=FindingKind.ITEM_GRADE_MATCHED, signal=Signal.UNKNOWN,
        statement_ko="세부품목 등급표에서 조회됩니다",
        source_url="https://www.law.go.kr/", source_label="운용요령 별표",
    )
    assert len(_axes([grade], None)) == 3
    assert "품목" not in " ".join(a["name"] for a in _axes([grade], None))


def test_the_design_references_do_not_say_four_axes():
    """참조가 "축 넷" 으로 되돌아가면 깨진다."""
    for name in _REFS:
        text = (_DESIGN / name).read_text(encoding="utf-8")
        # "넷이 아니다" 처럼 **부정문**으로 적힌 줄은 근거 기록이라 통과시킨다.
        for line in text.splitlines():
            if "축 넷" in line and "아니" not in line and "적혀" not in line:
                raise AssertionError(f"{name}: 축을 넷으로 적었다 — {line.strip()[:90]}")


def test_the_reference_markup_draws_exactly_as_many_axis_cells_as_the_code_sends():
    """참조 마크업의 **칸 수**를 코드에서 센 수와 맞춘다.

    글로만 "셋" 이라 적고 칸은 넷을 그려 두면 다음 사람이 칸을 보고 넷이라
    믿는다 - 문서가 코드보다 앞서 나가는 그 결함의 다른 얼굴이다.
    """
    n = len(_axis_names())
    for name in ("result-card.html", "loading.html"):
        html = (_DESIGN / name).read_text(encoding="utf-8")
        cells = re.findall(r"<div><span", _axes_block(html, name))
        assert len(cells) == n, f"{name}: 축 칸이 {len(cells)}개 — 코드는 {n}개를 준다"
        # grid 열 수도 같아야 한다. 칸만 줄이고 열을 넷으로 두면 빈칸이 남는다.
        assert f"repeat({n},minmax(0,1fr))" in html, f"{name}: .axes grid 열이 {n}이 아니다"


def test_the_real_screen_and_the_reference_use_the_same_axis_names():
    """참조와 배포되는 화면이 다른 이름을 쓰면 참조가 참조가 아니다."""
    index = Path("sourcing_guard/static/index.html").read_text(encoding="utf-8")
    block = re.search(r'<div class="sk-axes[^"]*"[^>]*>(.*?)</div>\s*\n\s*</div>', index, re.S)
    assert block, "index.html 의 스켈레톤 축 블록을 못 찾았다"
    on_screen = re.findall(r"<span>([^<]+)</span>", block.group(1))
    assert on_screen == _axis_names(), (on_screen, _axis_names())
