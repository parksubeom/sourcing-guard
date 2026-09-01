"""Deterministic scoring. No LLM, no I/O, no clock, no randomness.

CLAUDE.md R1: this is the ONLY place a verdict is produced.
CLAUDE.md R3: absence of data yields UNKNOWN, never GREEN.
"""

from __future__ import annotations

from .models import Finding, FindingKind, ProductFacts, ScanResult, Signal, ItemCategory

# Weights are intentionally boring and auditable. Any change must be
# accompanied by a test case explaining the new behaviour.
_PENALTY: dict[FindingKind, int] = {
    FindingKind.RECALL_MATCH: 100,
    FindingKind.KC_NOT_FOUND: 45,
    FindingKind.KC_REVOKED: 100,
    FindingKind.KC_EXPIRED: 30,
    FindingKind.KC_SUSPENDED: 100,
    FindingKind.KC_UNDER_ACTION: 40,
    FindingKind.KC_MISSING_BUT_REQUIRED: 45,
    FindingKind.HAZARD_RULE_APPLIES: 20,
    FindingKind.SUBSTANCE_MENTIONED: 25,
    FindingKind.COVERAGE_GAP: 0,
    FindingKind.LOOKUP_FAILED: 0,
    FindingKind.KC_TIER_UNKNOWN: 0,
    FindingKind.KC_VERIFIED: 0,
    FindingKind.RECALL_CLEAR: 0,
}

_HARD_RED = {
    # RED 는 정부 DB 가 문제를 적어둔 경우에만 준다. 부재는 증거가 아니다.
    #
    # KC_EXPIRED 도 여기 없다. 기간만료·반납은 정부 DB 가 "문제가 있다" 고 적은
    # 것이 아니라 인증의 수명이 끝났다고 적은 것이다. 완구 인증의 67% 가
    # 기간만료여서(2026-09-01 실측) RED 로 두면 정상 상품 대부분에 빨간불이 뜬다.
    #
    # KC_NOT_FOUND 는 여기 없다. 전안법은 위해도 4단계이고 가장 낮은
    # 공급자적합성확인(SCoC) 대상은 제조·수입자가 스스로 시험해 확인하므로
    # 조회 DB 에 번호가 없는 것이 정상이다. 미조회를 RED 로 두면 정상 상품에
    # 반복해서 빨간불이 뜨고, 셀러가 모든 RED 를 무시하게 된다. 그러면 진짜
    # 취소된 인증도 안 보게 된다.
    FindingKind.RECALL_MATCH,
    FindingKind.KC_REVOKED,
    FindingKind.KC_SUSPENDED,
}

_REGULATED = {
    ItemCategory.CHILDREN_TOY,
    ItemCategory.CHILDREN_STATIONERY,
    ItemCategory.CHILDREN_TEXTILE,
    ItemCategory.ELECTRICAL,
}


def score(
    facts: ProductFacts,
    findings: list[Finding],
    *,
    recall_data_as_of: str | None = None,
) -> ScanResult:
    """Combine findings into a display score and a signal.

    The score is a UI affordance, not a legal judgement. The signal is what
    matters and it is derived from findings, never from the score alone.
    """
    kinds = {f.kind for f in findings}

    penalty = sum(_PENALTY[f.kind] for f in findings)
    value = max(0, 100 - penalty)

    signal = _signal_for(facts, kinds)
    if signal is Signal.UNKNOWN:
        # Do not present a reassuring number next to "we don't know".
        value = 0

    return ScanResult(
        signal=signal,
        score=value,
        facts=facts,
        findings=findings,
        coverage_note=_coverage_note(facts, kinds),
        recall_data_as_of=recall_data_as_of,
    )


def _signal_for(facts: ProductFacts, kinds: set[FindingKind]) -> Signal:
    if kinds & _HARD_RED:
        return Signal.RED

    # 조회를 못 했으면 아무것도 확인하지 못한 것이다. GREEN 이 나오면 확인하지
    # 못한 것을 확인한 것처럼 말하게 된다. 지금은 RECALL_CLEAR 가 안 붙어서
    # 자동으로 막히지만, 나중에 GREEN 조건을 완화할 때를 대비해 명시로 막는다.
    if FindingKind.LOOKUP_FAILED in kinds:
        return Signal.UNKNOWN

    # R3: an unclassified item means we do not know which rules apply.
    if facts.category is ItemCategory.UNCLASSIFIED:
        return Signal.UNKNOWN
    if FindingKind.COVERAGE_GAP in kinds:
        return Signal.UNKNOWN

    if kinds & {
        FindingKind.KC_NOT_FOUND,
        FindingKind.KC_EXPIRED,
        FindingKind.KC_UNDER_ACTION,
        FindingKind.KC_MISSING_BUT_REQUIRED,
        FindingKind.SUBSTANCE_MENTIONED,
        FindingKind.HAZARD_RULE_APPLIES,
    }:
        return Signal.AMBER

    # GREEN requires positive evidence on BOTH axes. Silence is not evidence.
    if {FindingKind.KC_VERIFIED, FindingKind.RECALL_CLEAR} <= kinds:
        return Signal.GREEN

    return Signal.UNKNOWN


def _coverage_note(facts: ProductFacts, kinds: set[FindingKind]) -> str | None:
    if facts.category is ItemCategory.UNCLASSIFIED:
        return "품목군을 특정하지 못해 적용 기준을 확정할 수 없습니다."
    if FindingKind.COVERAGE_GAP in kinds:
        return (
            f"현재 규칙 DB는 이 품목군({facts.category.value})의 유해물질 기준을 "
            "아직 수록하지 않았습니다. 인증·리콜 조회 결과만 반영되었습니다."
        )
    if facts.category not in _REGULATED:
        return "안전인증 의무 대상 여부는 별도 확인이 필요합니다."
    return None
