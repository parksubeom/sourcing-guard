"""Scorer contract tests. Never skip these (CLAUDE.md §7)."""

from datetime import date

import pytest

from sourcing_guard.models import Finding, FindingKind, ItemCategory, ProductFacts, Signal
from sourcing_guard.scorer import score

SRC = {"source_label": "국가기술표준원", "source_url": "https://www.safetykorea.kr/"}


def f(kind: FindingKind, signal: Signal, text: str = "조회 결과입니다.") -> Finding:
    return Finding(kind=kind, signal=signal, statement_ko=text, checked_at=date(2026, 1, 1), **SRC)


def toy() -> ProductFacts:
    return ProductFacts(product_name="블록", category=ItemCategory.CHILDREN_TOY, category_confidence=0.9)


# --- R2: no source, no finding ------------------------------------------
def test_finding_requires_source():
    with pytest.raises(ValueError):
        Finding(kind=FindingKind.KC_VERIFIED, signal=Signal.GREEN,
                statement_ko="조회됨", source_label="", source_url="")


def test_finding_rejects_verdict_language():
    with pytest.raises(ValueError):
        Finding(kind=FindingKind.KC_VERIFIED, signal=Signal.GREEN,
                statement_ko="이 제품은 안전합니다", **SRC)


# --- R1/R3: signal derivation -------------------------------------------
def test_recall_match_is_red():
    r = score(toy(), [f(FindingKind.RECALL_MATCH, Signal.RED)])
    assert r.signal is Signal.RED


def test_unverified_kc_is_red():
    r = score(toy(), [f(FindingKind.KC_NOT_FOUND, Signal.RED)])
    assert r.signal is Signal.RED


def test_silence_is_not_green():
    """No findings at all must never produce GREEN."""
    assert score(toy(), []).signal is Signal.UNKNOWN


def test_green_needs_both_axes():
    only_kc = score(toy(), [f(FindingKind.KC_VERIFIED, Signal.GREEN)])
    assert only_kc.signal is Signal.UNKNOWN

    both = score(toy(), [f(FindingKind.KC_VERIFIED, Signal.GREEN),
                         f(FindingKind.RECALL_CLEAR, Signal.GREEN)])
    assert both.signal is Signal.GREEN


def test_unclassified_never_green():
    facts = ProductFacts(product_name="무언가", category=ItemCategory.UNCLASSIFIED)
    r = score(facts, [f(FindingKind.KC_VERIFIED, Signal.GREEN),
                      f(FindingKind.RECALL_CLEAR, Signal.GREEN)])
    assert r.signal is Signal.UNKNOWN
    assert r.score == 0, "UNKNOWN 옆에 안심시키는 점수를 보여주지 않는다"


def test_coverage_gap_forces_unknown():
    r = score(toy(), [f(FindingKind.KC_VERIFIED, Signal.GREEN),
                      f(FindingKind.RECALL_CLEAR, Signal.GREEN),
                      f(FindingKind.COVERAGE_GAP, Signal.UNKNOWN)])
    assert r.signal is Signal.UNKNOWN
    assert r.coverage_note


# --- determinism ---------------------------------------------------------
def test_scoring_is_deterministic():
    findings = [f(FindingKind.KC_MISSING_BUT_REQUIRED, Signal.AMBER),
                f(FindingKind.HAZARD_RULE_APPLIES, Signal.AMBER)]
    results = {(score(toy(), findings).signal, score(toy(), findings).score) for _ in range(100)}
    assert len(results) == 1
