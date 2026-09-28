"""입력란 글자 크기의 **바닥은 16px** — iOS 사파리가 확대하지 않게.

2026-09-28 에 `textarea` 가 15px 이었다. iOS 사파리는 16px 미만인 입력 요소에
포커스하면 **페이지를 통째로 확대하고 손을 떼도 되돌리지 않는다.** 셀러가
상세페이지를 붙여넣으려고 입력란을 누른 순간 화면이 커지고 가로로 밀린다 -
그게 우리 주 입력란(`#pt`)과 대량 검사 입력란(`#bt`)이었다.

⚠ **데스크톱 사파리에는 그 동작이 없다.** WebKit 으로 8개 화면 × 2폭을 재도
  크로미움과 16칸 전부 같았다(오류 0 · 가로넘침 0). 눌러 보는 경로까지 재도
  같았다. 기기에서만 나는 결함이라 브라우저 대조로는 안 잡힌다 - 그래서
  **소스에 가드를 둔다.**

⚠ 같은 파일이 이미 `.gd-tools input[type=search]` 에 16px 을 박아 두고 있었다.
  한 군데만 고쳐 두면 다음 입력란이 또 걸린다 (§6 「같은 판단을 두 곳에」).

⚠⚠ 이 검사는 **선언된 값**을 본다. 계산된 값과 다를 수 있다 - 실측에서 검색
  입력란은 16px 로 선언돼 있는데 계산값은 17px 이었다(더 큰 쪽이라 무해).
  선언이 16 미만이면 계산도 대개 그렇다는 것에 기댄다. 브라우저에서 재는 것은
  `scripts/check_demo_path.py` 같은 실측 쪽 일이다.
"""
from __future__ import annotations

import re
from pathlib import Path

_CSS = (Path(__file__).resolve().parents[1]
        / "sourcing_guard" / "static" / "app.css").read_text(encoding="utf-8")

#: 포커스를 받아 iOS 확대를 부르는 요소. `button` 은 확대를 안 부른다.
#
# ⚠⚠ `\b(input|textarea|select)\b` 로 썼다가 **`.input-note` 에 걸렸다** -
#   입력란 옆 설명 문구이고 폼 요소가 아니다. `\b` 는 `.` 과 `-` 에서 끊기므로
#   클래스 이름 속 낱말을 요소 이름으로 읽는다. 「가드는 재려는 그것을 재는지
#   먼저 확인한다」(§6) 가 이 자리다 - 가드를 만들자마자 가드가 틀렸다.
#
#   그래서 **앞뒤를 직접 본다**: 앞이 `.`·`#`·`-`·글자면 요소가 아니고,
#   뒤가 `-`·글자면 다른 이름이다. `input[type=search]` 의 `[` 는 통과시킨다.
_CONTROL = re.compile(r"(?<![.#\w-])(textarea|select|input)(?![\w-])")
_FLOOR_PX = 16


def _rules(css: str) -> list[tuple[str, str]]:
    """(선택자, 본문) 목록. **주석을 먼저 걷는다** — 이 규칙을 설명한 주석이
    규칙 대신 잡히는 것이 저장소에서 열네 번 난 함정이다 (§6①).

    ⚠ `@media` 같은 감싸는 블록은 선택자가 아니다. `{` 바로 앞 줄만 본다.
    """
    css = re.sub(r"/\*[\s\S]*?\*/", " ", css)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def test_no_form_control_is_smaller_than_the_ios_zoom_floor():
    found, bad = [], []
    for sel, body in _rules(_CSS):
        if not _CONTROL.search(sel) or "@" in sel:
            continue
        for m in re.finditer(r"font-size\s*:\s*([\d.]+)px", body):
            found.append((sel, float(m.group(1))))
            if float(m.group(1)) < _FLOOR_PX:
                bad.append(f"{sel.strip()[:60]} → {m.group(1)}px")
    # ⚠ **몇 개를 봤는지 같이 단정한다.** 0개를 보고 통과하면 검사가 아니다 (§6).
    assert found, "폼 요소의 font-size 선언을 하나도 못 찾았다 - 검사가 눈이 멀었다"
    assert not bad, (
        f"iOS 사파리가 확대한다 ({_FLOOR_PX}px 미만): {bad}")


def test_the_main_inputs_are_covered_by_that_rule():
    """`#pt`·`#bt` 를 덮는 `textarea` 규칙이 실재하는가.

    ⚠ 위 검사는 「16 미만이 없다」만 본다 - 규칙 자체가 사라져도 통과한다.
      실제로 덮는 선언이 있는지 따로 센다.
    """
    sizes = [px for sel, body in _rules(_CSS) if sel.strip() == "textarea"
             for px in re.findall(r"font-size\s*:\s*([\d.]+)px", body)]
    assert sizes == ["16"], f"textarea 의 font-size 선언이 {sizes} 다 - 하나여야 하고 16px 이어야 한다"


def test_the_floor_is_written_where_someone_would_lower_it():
    """왜 16 인지가 **그 자리에** 있어야 한다. 커밋 메시지에만 있으면 규칙이 아니다 (§6)."""
    head = _CSS[:_CSS.index("textarea{")]
    tail = head[-900:]
    assert "16px" in tail and ("사파리" in tail or "iOS" in tail), (
        "textarea 규칙 위에 16px 바닥의 이유가 없다 - 다음 사람이 15px 로 되돌린다")
