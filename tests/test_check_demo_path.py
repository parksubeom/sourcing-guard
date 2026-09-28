"""시연 점검 스크립트가 **말한 실호출 예산**이 실제 입력과 맞는가.

`scripts/check_demo_path.py` 머리 주석이 「KC 2 · GPT 2」라고 단정한다. 그 수는
**두 입력이 각각 인증번호를 하나만 가진다**는 전제 위에 서 있다. 입력을 바꾸면
전제가 조용히 깨지고, 예산이 두 배가 돼도 스크립트는 아무 말도 안 한다.

⚠ 스크립트 자신도 `/healthz` 전/후 차로 실제 소비량을 찍는다. 이 검사는 그것과
  방향이 반대다 - 저쪽은 **쓴 뒤에** 세고, 이쪽은 **쓰기 전에** 막는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_demo_path.py"
SAMPLES = ROOT / "sourcing_guard" / "data" / "experience_samples.json"
INDEX = ROOT / "sourcing_guard" / "static" / "index.html"

#: 인증번호 모양. 넓게 잡는다 - **더 많이 세는 쪽으로 틀리는 것이 안전하다**
#: (예산이 초과되는 것보다 검사가 한 번 더 걸리는 편이 싸다).
_KC = re.compile(r"\b[A-Za-z]{1,4}\d{3,}[A-Za-z0-9]*(?:-\d+[A-Za-z]?)?\b")


def _const(name: str) -> str:
    src = SCRIPT.read_text(encoding="utf-8")
    m = re.search(rf'^{name} = \(?\s*(.+?)\n(?:\)|\S)', src, re.S | re.M)
    assert m, f"{name} 을 못 찾았다"
    return "".join(re.findall(r'"([^"]*)"', m.group(0)))


def _samples() -> list[dict]:
    return json.loads(SAMPLES.read_text(encoding="utf-8"))["items"]


def test_live_sample_exists_and_its_recorded_signal_matches():
    """④ 가 비교하는 「기록본 신호」가 실제 기록본과 같아야 한다."""
    want_id = _const("LIVE_SAMPLE")
    want_sig = _const("LIVE_SAMPLE_SIGNAL")
    hit = [s for s in _samples() if s.get("cert_number") == want_id]
    assert len(hit) == 1, f"체험표본에 {want_id} 가 {len(hit)}개다"
    got = (hit[0].get("result") or {}).get("signal")
    assert got == want_sig, f"기록본 신호는 {got} 인데 스크립트는 {want_sig} 를 기대한다"


def test_live_sample_text_has_exactly_one_cert_number():
    """번호가 둘이면 KC 조회가 조용히 2회가 된다 — 예산이 깨진다."""
    want_id = _const("LIVE_SAMPLE")
    text = [s for s in _samples() if s.get("cert_number") == want_id][0]["text"]
    nums = {n.upper() for n in _KC.findall(text)}
    assert want_id.upper() in nums, f"표본 글에 {want_id} 가 없다"
    assert len(nums) == 1, f"인증번호 후보가 {sorted(nums)} — 하나여야 한다"


def test_live_text_is_the_screen_placeholder():
    """⑤ 가 고른 이유가 「화면 placeholder 와 같은 문장」이다. 갈리면 이유가 거짓."""
    text = _const("LIVE_TEXT")
    m = re.search(r'<textarea id="pt" placeholder="([^"]+)"', INDEX.read_text(encoding="utf-8"))
    assert m, "입력란 placeholder 를 못 찾았다"
    assert m.group(1) == "예) " + text, f"placeholder {m.group(1)!r} ≠ 예) + LIVE_TEXT"


def test_live_text_has_exactly_one_cert_number():
    nums = {n.upper() for n in _KC.findall(_const("LIVE_TEXT"))}
    assert len(nums) == 1, f"인증번호 후보가 {sorted(nums)} — 하나여야 한다"


def test_budget_line_matches_the_two_inputs():
    """머리 주석의 합계가 입력 수와 맞는가. 문서와 코드가 갈리는 자리를 잠근다."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "합계                KC 2 · GPT 2" in src, "예산 줄이 바뀌었다"
    # 실호출을 내는 단계는 ④⑤ **둘뿐**이다. 셋이 되면 위 줄이 거짓이 된다.
    assert src.count('if args.live:') == 2, "실호출 단계 수가 2 가 아니다"
