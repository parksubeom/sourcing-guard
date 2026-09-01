"""Scorer contract tests. Never skip these (CLAUDE.md §7)."""

from datetime import date

import pytest

from sourcing_guard.models import Finding, FindingKind, ItemCategory, ProductFacts, Signal
from sourcing_guard.scorer import _HARD_RED, score

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


def test_unverified_kc_is_amber_not_red():
    """미조회는 RED 가 아니다. 부재는 위반의 증거가 아니기 때문이다.

    전안법은 위해도 4단계이고, 가장 낮은 공급자적합성확인(SCoC) 대상은
    제조·수입자가 스스로 시험해 확인하므로 정부 조회 DB 에 번호가 없는 것이
    정상이다. 미조회를 RED 로 두면 정상 상품에 반복해서 빨간불이 뜨고,
    셀러가 모든 RED 를 무시하게 된다.
    """
    r = score(toy(), [f(FindingKind.KC_NOT_FOUND, Signal.AMBER)])
    assert r.signal is Signal.AMBER


def test_red_requires_positive_evidence_from_the_government_db():
    """RED 는 정부 DB 가 문제를 적어둔 경우에만 나온다."""
    from sourcing_guard.scorer import _HARD_RED

    assert _HARD_RED == {
        FindingKind.RECALL_MATCH,
        FindingKind.KC_REVOKED,
        FindingKind.KC_SUSPENDED,
    }
    assert FindingKind.KC_NOT_FOUND not in _HARD_RED
    assert FindingKind.KC_MISSING_BUT_REQUIRED not in _HARD_RED


def test_tier_unknown_blocks_green():
    """인증 구분을 모르면 인증번호 유무를 해석할 수 없다 (R3)."""
    r = score(toy(), [f(FindingKind.KC_VERIFIED, Signal.GREEN),
                      f(FindingKind.RECALL_CLEAR, Signal.GREEN),
                      f(FindingKind.KC_TIER_UNKNOWN, Signal.UNKNOWN)])
    assert r.signal is not Signal.RED


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


# --- A: certState -- 조회 성공은 유효성이 아니다 (설계서 p.5) ---------------
def test_revoked_cert_is_red_even_with_clean_recall():
    """취소된 인증에 초록불이 뜨면 안 된다. 셀러를 잘못 안심시키는 오류다."""
    r = score(toy(), [f(FindingKind.KC_REVOKED, Signal.RED),
                      f(FindingKind.RECALL_CLEAR, Signal.GREEN)])
    assert r.signal is Signal.RED


def test_suspended_cert_is_red():
    """표시 사용금지는 그 인증으로 판매 표시를 유지할 수 없으므로 취소와 동급."""
    r = score(toy(), [f(FindingKind.KC_SUSPENDED, Signal.RED),
                      f(FindingKind.RECALL_CLEAR, Signal.GREEN)])
    assert r.signal is Signal.RED


def test_cert_under_action_is_amber_not_red():
    r = score(toy(), [f(FindingKind.KC_UNDER_ACTION, Signal.AMBER),
                      f(FindingKind.RECALL_CLEAR, Signal.GREEN)])
    assert r.signal is Signal.AMBER


def test_every_finding_kind_has_a_penalty():
    """새 FindingKind 를 추가하고 가중치를 빠뜨리면 score() 가 KeyError 로 죽는다."""
    from sourcing_guard.scorer import _PENALTY

    missing = [k.value for k in FindingKind if k not in _PENALTY]
    assert not missing, f"_PENALTY 에 빠진 kind: {missing}"


# ---------------------------------------------------------------------------
# 조회 실패 — "조회했는데 없음" 과 "조회를 못 함" 은 다른 정보다.
# ---------------------------------------------------------------------------


def _finding(kind, signal):
    return Finding(
        kind=kind,
        signal=signal,
        statement_ko="테스트",
        source_label="국가기술표준원",
        source_url="https://www.safetykorea.kr/",
    )


def test_lookup_failure_never_yields_green():
    """조회를 못 했으면 아무것도 확인하지 못한 것이다.

    지금은 RECALL_CLEAR 가 안 붙어서 자동으로 막히지만, 나중에 누가 GREEN
    조건을 완화하면 조용히 뚫린다. 확인하지 못한 것을 확인한 것처럼 말하는
    것은 이 서비스에서 가장 비싼 오류다.
    """
    facts = ProductFacts(category=ItemCategory.CHILDREN_TOY)
    result = score(
        facts,
        [
            _finding(FindingKind.KC_VERIFIED, Signal.GREEN),
            _finding(FindingKind.RECALL_CLEAR, Signal.GREEN),
            _finding(FindingKind.LOOKUP_FAILED, Signal.UNKNOWN),
        ],
    )
    assert result.signal is Signal.UNKNOWN
    assert result.score == 0


def test_lookup_failure_does_not_mask_a_red():
    """조회 실패가 이미 확인된 문제를 덮으면 안 된다."""
    facts = ProductFacts(category=ItemCategory.CHILDREN_TOY)
    result = score(
        facts,
        [
            _finding(FindingKind.RECALL_MATCH, Signal.RED),
            _finding(FindingKind.LOOKUP_FAILED, Signal.UNKNOWN),
        ],
    )
    assert result.signal is Signal.RED


def test_lookup_failed_is_not_in_hard_red():
    """조회 실패는 상품의 문제가 아니라 우리 쪽 사정이다."""
    assert FindingKind.LOOKUP_FAILED not in _HARD_RED


# ---------------------------------------------------------------------------
# 유해물질 기준 "적용" 과 "언급" 을 가른다.
#
# 이 두 케이스가 계약이다. 나중에 누가 GREEN 조건을 만지면 여기가 잡아야 한다.
#
# 왜 갈랐나 (2026-09-02, 카나리아 승격 1건으로 발견):
#   HAZARD_RULE_APPLIES 를 AMBER 로 두면 완구·학용품·아동섬유가 무엇을 해도
#   노란불이 된다. 규칙 DB 가 커버하는 순간 GREEN 에 도달하는 경로가 사라진다.
#   항상 켜지는 경고는 꺼진 경고와 같고, 그러면 셀러가 진짜 노란불도 무시한다
#   (SCoC 오탐 7a6fd70 때 세운 논리 그대로).
# ---------------------------------------------------------------------------


REGULATED_FACTS = ProductFacts(category=ItemCategory.CHILDREN_TOY)


def test_hazard_rule_applying_does_not_block_green():
    """계약 ①: 적합 + 리콜없음 + 규제품목군 + 물질언급 없음 -> GREEN.

    "이 품목군에 납 기준이 걸린다" 는 적용 범위 안내이지 문제 지적이 아니다.
    """
    result = score(
        REGULATED_FACTS,
        [
            _finding(FindingKind.KC_VERIFIED, Signal.GREEN),
            _finding(FindingKind.RECALL_CLEAR, Signal.GREEN),
            _finding(FindingKind.HAZARD_RULE_APPLIES, Signal.UNKNOWN),
        ],
    )
    assert result.signal is Signal.GREEN


def test_substance_mentioned_turns_it_amber():
    """계약 ②: 같은 조건에 상세페이지 물질 언급이 더해지면 -> AMBER.

    "PVC 재질" 이라고 적힌 완구를 초록불로 통과시키면, 프탈레이트가 걸리는
    재질을 명시했는데 안심시키는 것이 된다. 기획서 §3 의 AMBER 정의
    ("규제 물질 언급 감지")와 일치한다.
    """
    result = score(
        REGULATED_FACTS,
        [
            _finding(FindingKind.KC_VERIFIED, Signal.GREEN),
            _finding(FindingKind.RECALL_CLEAR, Signal.GREEN),
            _finding(FindingKind.HAZARD_RULE_APPLIES, Signal.UNKNOWN),
            _finding(FindingKind.SUBSTANCE_MENTIONED, Signal.AMBER),
        ],
    )
    assert result.signal is Signal.AMBER


def test_green_always_states_what_was_not_checked():
    """초록불은 "안 걸린다"는 보증이 아니다 (기획서 §6.1).

    우리는 상세페이지 텍스트를 읽고 단속은 실물을 수거해 시험한다. 그 간극을
    화면이 말해야 한다. 점검 범위 없는 초록불은 잘못 안심시킨다.
    """
    result = score(
        REGULATED_FACTS,
        [
            _finding(FindingKind.KC_VERIFIED, Signal.GREEN),
            _finding(FindingKind.RECALL_CLEAR, Signal.GREEN),
            _finding(FindingKind.HAZARD_RULE_APPLIES, Signal.UNKNOWN),
        ],
    )
    assert result.signal is Signal.GREEN
    assert result.coverage_note, "초록불에 점검 범위가 병기되지 않았습니다"
    assert "시험성적서" in result.coverage_note
    # 단정 표현은 쓰지 않는다 (CLAUDE.md §9)
    for banned in ("안전합니다", "합법입니다", "판매 가능합니다"):
        assert banned not in result.coverage_note


def test_hazard_rule_alone_is_not_in_the_amber_set():
    """회귀 가드: AMBER 집합에 되돌려 놓으면 GREEN 이 다시 사라진다."""
    import inspect

    from sourcing_guard import scorer

    src = inspect.getsource(scorer._signal_for)
    amber_block = src.split("kinds & {")[1].split("}")[0]
    assert "HAZARD_RULE_APPLIES" not in amber_block
    assert "SUBSTANCE_MENTIONED" in amber_block


def test_green_is_not_scored_to_zero_by_applicable_rules():
    """룰마다 finding 이 하나씩 붙는다. 완구 14건, 아동섬유 17건이다.

    가중치가 있으면 GREEN 이 무조건 0점이 된다 - "확인된 문제 없음" 과 "0점" 은
    모순이다. 룰이 많다고 위험한 것이 아니라 그 품목군에 기준이 많은 것뿐이다.
    """
    findings = [
        _finding(FindingKind.KC_VERIFIED, Signal.GREEN),
        _finding(FindingKind.RECALL_CLEAR, Signal.GREEN),
    ]
    findings += [
        _finding(FindingKind.HAZARD_RULE_APPLIES, Signal.UNKNOWN) for _ in range(17)
    ]
    result = score(REGULATED_FACTS, findings)

    assert result.signal is Signal.GREEN
    assert result.score == 100, "적용 룰 개수가 점수를 깎고 있습니다"
