"""[E-2] 보고서의 숫자가 **지금 재생값과 같은지** 잠근다.

⚠ 이 저장소의 반복 결함이 "문서가 코드보다 앞서 나감" 이다. 사이드카가 낡아
  발표 숫자를 잘못 옮긴 적이 있고(`단건경로_gpt.md` 94/19 → 실제 95/18),
  그래서 문서 숫자는 검사로 묶는다.

⚠⚠ **재생값과 런타임값을 갈라야 한다.** `/healthz` 의 `results.rate` 와 이
  보고서의 값은 이름이 같고 성질이 다르다. 문서가 그 구분을 잃으면 재생값이
  사용 통계로 읽힌다 - 그것이 가장 비싼 오독이다.

⚠ ⓑ(도매꾹 상세)는 **네트워크와 로컬 리콜 DB** 를 쓰므로 여기서 재지 않는다.
  ⓐ 만 재현한다 - ⓐ 는 LLM·네트워크·DB 를 모두 쓰지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_REPORT = _ROOT / "docs/E2_유효결과율_재생_2026-09-09.md"
_SRC = _ROOT / "tests/fixtures/단건경로_claude_235.json"


def _report() -> str:
    return _REPORT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def measured() -> dict:
    """ⓐ 를 지금 코드로 다시 잰다. LLM 0회 · 네트워크 0회."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    from audit_tally import load_scope

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.scorer import has_specific_finding
    from sourcing_guard.verifier import RuleBook, verify

    scope = load_scope()
    rows = json.loads(_SRC.read_text(encoding="utf-8"))
    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = RuleBook()

    out = {k: {"n": 0, "specific": 0} for k in ("대상", "비대상", "애매")}
    for r in rows:
        cls = scope.get(r["name"])
        if cls not in out:
            continue
        try:
            category = ItemCategory(r.get("category") or "unclassified")
        except ValueError:
            category = ItemCategory.UNCLASSIFIED
        facts = ProductFacts(
            product_name=r.get("product_name") or None,
            category=category,
            legal_item_name=r.get("legal") or None,
        )
        findings = verify(facts, kats, rules, raw_text=r["name"])
        out[cls]["n"] += 1
        if has_specific_finding(findings):
            out[cls]["specific"] += 1
    return out


def test_the_report_exists_and_says_it_is_a_replay_not_live_traffic():
    """**라벨이 없는 숫자를 문서에 적지 않는다.**"""
    text = _report()
    assert "재생값" in text and "런타임값" in text, "두 값의 구분이 없다"
    assert "실트래픽이 아니다" in text
    assert "기획서·랜딩에 넣지 않는다" in text
    # 어느 표본·어느 조건인지가 값과 함께 있어야 한다.
    assert "표본 235" in text and "상품명만" in text
    assert "표본 109" in text
    # [E-3] 을 먼저 적용했다는 사실 - 안 적으면 어느 분류 기준의 값인지 모른다.
    assert "recall_weak_match" in text


def test_the_numbers_in_the_report_match_a_fresh_replay(measured):
    """ⓐ 의 숫자가 지금 재생값과 같다."""
    text = _report()
    expected = {
        "대상": (measured["대상"]["specific"], measured["대상"]["n"]),
        "비대상": (measured["비대상"]["specific"], measured["비대상"]["n"]),
        "애매": (measured["애매"]["specific"], measured["애매"]["n"]),
    }
    total = (
        sum(v["specific"] for v in measured.values()),
        sum(v["n"] for v in measured.values()),
    )

    # 보고서 §1 표에서 `126/135` 꼴을 읽는다.
    for label, (part, whole) in expected.items():
        pattern = rf"{label}\s+{part}/\s*{whole}\s*="
        assert re.search(pattern, text), (
            f"보고서의 {label} 값이 재생값 {part}/{whole} 와 다릅니다"
        )
    assert re.search(rf"전체\s+{total[0]}/{total[1]}\s*=", text), (
        f"보고서의 전체 값이 재생값 {total[0]}/{total[1]} 와 다릅니다"
    )


def test_the_replay_uses_no_llm_and_no_network(measured):
    """ⓐ 경로가 외부에 나가지 않는다.

    ⚠ 여기서 깨지면 이 지표가 환경에 따라 갈린다 - [E-1] 이 그 문제였다.
    """
    src = (_ROOT / "scripts/measure_result_rate.py").read_text(encoding="utf-8")
    # ⓐ 는 MagicMock 인증 조회를 쓴다.
    fn = src.split("def measure_new_sample")[1].split("\ndef ")[0]
    assert "MagicMock" in fn
    assert "KatsClient" not in fn and "RecallIndex" not in fn
    # 재현 자체가 돌았다는 것이 곧 네트워크 없이 됐다는 증거다.
    assert measured["대상"]["n"] == 135


def test_the_report_records_what_it_did_not_fix():
    """발견한 결함을 **고치지 않았다는 것**과 판정 요청이 적혀 있다.

    ⚠ 판정은 사람이 한다 (R1 과 별개로 이 프로젝트의 작업 규칙). 보고서가
      후보를 적어 두지 않으면 다음 세션이 같은 것을 다시 발견한다.
    """
    text = _report()
    assert "고치지 않았다" in text and "판정" in text
    # (1) out_of_scope 침묵 경로
    assert "scope_reason" in text and "_GRADE_LOOKUP_OPEN" in text
    # 상세가 지표를 낮췄다는 사실을 숨기지 않았다.
    assert "기대와 반대" in text


def test_the_five_criteria_are_restated():
    """규칙 변경이 없었어도 다섯을 적는다 - 총괄 지시."""
    text = _report()
    for mark in ("①", "②", "③", "④", "⑤"):
        assert mark in text, f"기준 {mark} 가 없다"
