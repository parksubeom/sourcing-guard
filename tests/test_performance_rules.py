"""성능·구조 요건을 담는 방식.

유해물질은 "납 90mg/kg" 처럼 값 하나로 떨어진다. 성능 요건은 아니다 -
부속서 53(운동용 안전모) 원문의 기준이 "가속도계를 무게중심 반경 10mm 이내에
설치하고 6kHz 로 샘플링해 CFC 1000 으로 필터링" 같은 **시험 절차 규격**이라,
값을 보여줘도 셀러가 쓸 수 없다.

그래서 값 대신 어떤 시험을 통과해야 하는지와, 정부 조사에서 이 품목이 어떻게
나왔는지를 담는다. 화면에서 하는 일은 유해물질과 같다 - "이걸 확인하라".
"""

from pathlib import Path

import pytest
import yaml

import sourcing_guard
from sourcing_guard.verifier import HazardRule, RuleBook, _performance_statement

_SRC = Path(sourcing_guard.__file__).parent / "data" / "hazard_rules.yaml"


def _rules() -> list[dict]:
    doc = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    return doc["rules"] if isinstance(doc, dict) else doc


def test_existing_substance_rules_are_untouched():
    """requirement_type 이 없으면 substance 로 간주한다 - 기존 57건은 그대로다."""
    for rule in _rules():
        if rule["id"].startswith(("KC-COMMON-", "KC-ANNEX")):
            assert rule.get("requirement_type", "substance") == "substance", rule["id"]

    # 활성 룰에 성능 요건이 섞이는 것은 정상이다 - 생활용품 부속서를 승격하면
    # 안전모·레이저가 performance 로 들어온다. 어린이제품 쪽만 불변을 요구한다.
    book = RuleBook()
    for rule in book.active:
        if rule.id.startswith(("KC-COMMON-", "KC-ANNEX")):
            assert rule.requirement_type == "substance", rule.id


def test_performance_rules_carry_no_limit_value():
    """성능 요건에 값을 담으면 안 된다 - 시험 절차 규격이라 셀러가 쓸 수 없다."""
    for rule in _rules():
        if rule.get("requirement_type") != "performance":
            continue
        assert rule["limit_value"] is None, rule["id"]
        assert rule["unit"] is None, rule["id"]


def test_performance_statement_names_the_tests_not_the_numbers():
    rule = HazardRule(
        id="x", substance="승차용 안전모 안전요건", aliases=(), applies_to=("household",),
        limit_value=None, unit=None,
        legal_basis="전기용품 및 생활용품 안전관리법 (안전확인대상생활용품)",
        source_url="u", requirement_type="performance",
        test_items=("충격흡수성", "관통성"),
    )
    text = _performance_statement(rule)
    assert "충격흡수성" in text and "관통성" in text
    assert "시험성적서를 요구하세요" in text


def test_failure_rate_is_shown_with_its_sample():
    """비율만 보여주면 표본 8개짜리가 통계처럼 읽힌다 (기획서 §2.2 에서 겪은 실수)."""
    rule = HazardRule(
        id="x", substance="t", aliases=(), applies_to=("household",),
        limit_value=None, unit=None, legal_basis="전기용품 및 생활용품 안전관리법",
        source_url="u", requirement_type="performance",
        failure_rate={"sample": "10개 중 7개", "source": "국표원 조사 2026-04"},
    )
    text = _performance_statement(rule)
    assert "10개 중 7개" in text
    assert "70%" not in text          # 비율로 환산해 보여주지 않는다
    assert "표적 조사" in text          # 조사 성격을 밝힌다


def test_every_failure_rate_has_sample_and_source():
    """test_failure_rate_honesty 와 같은 계약. 여기서도 지킨다."""
    for rule in _rules():
        rate = rule.get("failure_rate")
        if rate is None:
            continue
        assert rate.get("sample"), rule["id"]
        assert rate.get("source"), rule["id"]


def test_annex_number_implies_a_cited_clause():
    """부속서 번호를 적었으면 조문도 함께 적어야 한다.

    번호를 추측으로 채우면 R5 위반이다. 원문을 실제로 열었다면 몇 절인지도
    알기 마련이므로, 둘을 한 쌍으로 요구해 추측을 걸러낸다.

    ⚠ 원문 확인과 verified 승격은 **다른 단계**다. 원문을 읽어 번호를 채우는
    것은 기계가 하고, 승격은 사람이 원문을 눈으로 대조한 뒤에 한다(R5).
    그래서 annex_no 가 있어도 status 는 draft 일 수 있다.
    """
    for rule in _rules():
        if rule.get("requirement_type") != "performance":
            continue
        if rule.get("annex_no") is None:
            continue
        assert "부속서" in rule["clause"], f"{rule['id']}: 부속서 번호만 있고 조문이 없다"
        assert rule["annex_no"] in rule["clause"], (
            f"{rule['id']}: annex_no({rule['annex_no']})와 clause 가 어긋난다"
        )
