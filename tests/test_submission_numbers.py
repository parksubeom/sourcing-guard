"""[제출-1] 제출문·기획서·랜딩의 숫자가 **한 원자료에서** 나오는지 잠근다.

세 문서가 따로 숫자를 들고 있으면 반드시 갈린다. 실제로 세 번 갈렸다:

    2026-09-11  제출문에 `71.1% / 40.9%` (9/7 시절 값)가 남아 있었다
    2026-09-12  랜딩 ④ 가 Claude 기준 73.3% 인데 화면은 GPT 로 돌았다
    2026-09-13  제출문이 배치를 **상한 하나로만** 적었다 - "대량 검사 경로는
                82.2%" 인데 82.2 는 `ok_upper` 이고 검수된 정답은 71.1% 다

셋 다 **문서가 코드보다 앞서 나간 것**이고, 이 저장소의 반복 결함이다.
정본은 `scripts/audit_tally.py` 의 `BASELINE` · `BASELINE_BATCH` 하나다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DRAFT = _ROOT / "docs/제출문_초안.md"
_LANDING = _ROOT / "sourcing_guard/static/landing.html"
_PROPOSAL = _ROOT / "00_프로젝트_핸드오프.md"

#: 폼 제한. 세 항목 × 세 길이.
#: ⚠ **폼의 실제 계산 방식은 아직 모른다**(로그인 확인 전). 우리 계산은
#:   공백 포함이라 보수적으로 큰 쪽이다 - 폼이 공백을 빼면 여유가 더 있다.
LIMITS = (200, 500, 1000)


def _baseline():
    sys.path.insert(0, str(_ROOT / "scripts"))
    from audit_tally import BASELINE, BASELINE_BATCH, BASELINE_EXTRACTOR

    return BASELINE[BASELINE_EXTRACTOR], BASELINE_BATCH


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.1f}%"


def test_the_batch_baseline_reproduces():
    """⚠ 기준선 표가 실제 재생값과 같은지 먼저 본다.

    표만 고치고 코드를 안 고치면 표가 거짓말을 한다.
    """
    sys.path.insert(0, str(_ROOT / "scripts"))
    import os

    cwd = os.getcwd()
    os.chdir(_ROOT)
    try:
        from audit_tally import BASELINE_BATCH, batch_tally

        got = batch_tally()
    finally:
        os.chdir(cwd)
    for key, want in BASELINE_BATCH.items():
        assert got[key] == want, (
            f"배치 기준선 {key} 가 {want} 인데 재생값은 {got[key]} 다. "
            f"규칙이 바뀌었으면 표와 제출문을 함께 옮겨라"
        )


def test_the_draft_reports_both_numbers_for_both_paths():
    """⚠⚠ **단건도 배치도 두 값을 적는다.**

    제출문 자신이 "검수 전 숫자를 검수된 숫자처럼 쓰지 않는다" 고 선언한다.
    2026-09-13 까지 배치만 상한 하나였다 - 선언 바로 다음 문장이 선언을 어겼다.
    """
    single, batch = _baseline()
    body = _DRAFT.read_text(encoding="utf-8")

    for label, b in (("단건", single), ("배치", batch)):
        ok = f"{b['ok']}건({_pct(b['ok'], b['denominator'])})".replace("건(", "건 (")
        upper = f"{b['ok_upper']}건"
        assert re.search(rf"{b['ok']}건\s*\(?\s*{re.escape(_pct(b['ok'], b['denominator']))}", body), (
            f"{label} 의 **검수된 정답** {b['ok']}건({_pct(b['ok'], b['denominator'])}) 이 제출문에 없다"
        )
        assert re.search(rf"{b['ok_upper']}건", body), f"{label} 의 상한 {upper} 이 제출문에 없다"
        assert _pct(b["ok_upper"], b["denominator"]) in body


def test_the_draft_says_the_batch_number_is_an_upper_bound_too():
    """배치 숫자에 "상한" 이라는 말이 붙어 있어야 한다.

    ⚠ 숫자만 둘 적고 어느 쪽이 상한인지 안 쓰면 읽는 사람이 큰 쪽을 정답률로
      읽는다 - 랜딩 71% 와 같은 함정이다 (판정 5).
    """
    body = _DRAFT.read_text(encoding="utf-8")
    _, batch = _baseline()
    m = re.search(rf"상한\s*{batch['ok_upper']}건", body)
    assert m, "배치 상한에 '상한' 이라는 말이 없다"


def test_every_variant_fits_its_form_limit():
    """⚠ 글자 수가 제한을 넘으면 폼에서 **잘린다.**

    2026-09-13 에 'AI 활용 방식' 1000자판이 실제 1,138자였다. 표에는 964 라
    적혀 있었다 - 손으로 센 값이 174자 어긋나 있었다. 이제 세는 것은 스크립트고
    넘으면 이 검사가 실패한다.
    """
    sys.path.insert(0, str(_ROOT / "scripts"))
    from count_submission_chars import _ITEMS, variants

    doc = _DRAFT.read_text(encoding="utf-8")
    over = []
    for title in _ITEMS:
        for limit, got in variants(doc, title).items():
            assert limit in LIMITS, f"모르는 길이 {limit}자판이 생겼다"
            if got > limit:
                over.append(f"{title} {limit}자판 = {got}자 ({got - limit} 초과)")
    assert not over, "폼에서 잘린다:\n  " + "\n  ".join(over)


def test_no_retired_rate_survives_in_the_text_that_gets_submitted():
    """제출되는 **답변 본문**에 은퇴한 정답률이 없어야 한다.

    ⚠ 검사 범위가 답변 본문뿐인 것이 중요하다. 제출문에는 정정 이력을 적는
      주석이 있고 **거기에는 옛 값이 일부러 있다**("이 자리에 71.1%/40.9% 가
      남아 있었다"). 문서 전체를 훑으면 그 기록에 걸린다 - 이 함정에 이
      저장소에서 여섯 번째로 걸렸다(`tests/srccheck.py` 머리 주석).

    ⚠ 살아 있는 값은 은퇴 목록에서 뺀다. `71.1%` 는 2026-09-13 부터 **배치의
      검수된 정답률**이다 - 같은 문자열이 죽었다 살아났다.
    """
    import re as _re

    single, batch = _baseline()
    alive = {
        _pct(single["ok"], single["denominator"]),
        _pct(single["ok_upper"], single["denominator"]),
        _pct(batch["ok"], batch["denominator"]),
        _pct(batch["ok_upper"], batch["denominator"]),
    }
    retired = {"73.3%", "40.9%", "77.8%", "68.4%", "84.4%", "71.1%"} - alive

    doc = _DRAFT.read_text(encoding="utf-8")
    bodies = _re.findall(r"^### \d+자\n(.*?)(?=^### |^## |\Z)", doc, _re.S | _re.M)
    assert bodies, "답변 본문을 못 찾았다 - 제출문 구조가 바뀌었다"
    joined = "\n".join(bodies)
    for old in sorted(retired):
        assert old not in joined, (
            f"제출되는 본문에 은퇴한 값 {old} 가 있다. 살아 있는 값은 {sorted(alive)}"
        )


@pytest.mark.parametrize("path", [_LANDING])
def test_the_landing_reads_the_same_baseline(path: Path):
    """랜딩 ④ 는 `test_landing.py` 가 기준선과 대조한다. 여기서는 **존재**만 본다.

    ⚠ 같은 단정을 두 파일에 적지 않는다 (§6). 이 검사는 "랜딩이 그 가드를
      가지고 있는가" 만 확인한다.
    """
    guard = (_ROOT / "tests/test_landing.py").read_text(encoding="utf-8")
    assert "BASELINE_EXTRACTOR" in guard, "랜딩 가드가 기준선을 안 본다"
    assert path.exists()


def test_the_draft_names_the_extractors_we_actually_use():
    """⚠⚠ **제출문이 사실과 달랐다 (2026-09-14).**

    §3 「사용한 AI 도구」가 "모델을 Claude 하나로 통일" 을 세 번 적고 GPT 를
    한 번도 안 적었다. 실제 기본값은 `gpt,claude` 이고 기준 추출기는
    `gpt-5.4-mini` 다 (CLAUDE.md R7). **대회 제출문에 사실과 다른 문장**이었고,
    심사 유의사항은 쓴 도구를 밝히라고 요구한다.

    R7 은 "납품 문서에 두 벤더를 함께 적는다" 고 이미 적어 뒀다 - 여기가
    그것을 지키는지 보는 자리다.

    ⚠ 범위는 **제출되는 답변 본문**이다. 문서 전체를 보면 정정 이력 주석이
      통과시킨다 - 실제로 처음 판이 그래서 안 물었다.
    """
    from sourcing_guard.baseline import BASELINE_EXTRACTOR
    from sourcing_guard.config import settings

    for label, body in _answer_bodies().items():
        if "AI 도구" not in label:
            continue
        assert settings.gpt_model in body, (
            f"{label}: 기준 추출기 모델 {settings.gpt_model} 이 없다")
        assert "Claude" in body, f"{label}: 2순위 벤더가 없다"
        assert BASELINE_EXTRACTOR.upper() in body, f"{label}: 어느 쪽이 기준인지 없다"
        # ⚠ **벤더 이름을 빼고 막는다.** "Claude 하나로 통일" 만 막으면
        #   "GPT 하나로 통일" 로 바꿔 적어도 통과한다 - 우리가 겪은 거짓은
        #   벤더 이름이 아니라 **"하나뿐"** 이라는 주장이었다.
        for gone in ("하나로 통일", "모델은 Claude 하나", "단일 모델", "Claude 단일"):
            assert gone not in body, f"{label}: 사실과 다른 문장이 돌아왔다 {gone!r}"


def test_the_draft_discloses_the_second_transfer_path():
    """⚠ 벤더가 둘이면 **국외 전송 경로도 둘**이다 (R7).

    B2B 납품 심사에서 답해야 하는 항목이라 이득만 적고 대가를 빼면 안 된다.
    """
    joined = "\n".join(b for k, b in _answer_bodies().items() if "AI 도구" in k)
    assert "경로가 둘" in joined, "전송 경로가 둘이라는 사실이 안 적혀 있다"
    assert "상세페이지 텍스트" in joined, "무엇을 보내는지 안 적혀 있다"


def _answer_bodies() -> dict[str, str]:
    """제출되는 답변 본문만. `## <항목>` 아래 `### N자` 절들.

    ⚠ 문서 전체를 보면 정정 이력 주석이 검사를 통과시킨다 - 이 저장소에서
      여러 번 걸린 자리다.
    """
    doc = _DRAFT.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(r"^## \d+\. (.+?)\n(.*?)(?=^## |\Z)", doc, re.S | re.M):
        title, chunk = m.group(1).strip(), m.group(2)
        bodies = re.findall(r"^### (\d+자)\n(.*?)(?=^### |\Z)", chunk, re.S | re.M)
        for n, b in bodies:
            out[f"{title} {n}"] = b
    assert out, "답변 본문을 못 찾았다 - 제출문 구조가 바뀌었다"
    return out
