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


# --- 셀러 관점 헤드라인 ----------------------------------------------------
def test_every_signal_has_a_sourcing_headline():
    """네 신호 모두 '소싱해도 되나?' 에 답하는 한 줄을 가져야 한다."""
    from sourcing_guard.scorer import _HEADLINE
    from sourcing_guard.models import Signal

    for sig in Signal:
        assert sig in _HEADLINE and _HEADLINE[sig].strip()


def test_green_headline_never_promises_safety():
    """GREEN 은 '판매자 제공 정보 기준' 을 명시해 안전 보증으로 읽히지 않는다 (§6.1).

    이 단서가 사라지면 사후 리콜 책임이 우리에게 온다. 사업 모델의 전제다.
    """
    from sourcing_guard.scorer import _HEADLINE
    from sourcing_guard.models import Signal

    green = _HEADLINE[Signal.GREEN]
    assert "판매자 제공 정보" in green
    assert "시험성적서" in green
    # 안전을 단정하는 표현이 없어야 한다
    for word in ("안전합니다", "문제없습니다", "이상 없음", "합법"):
        assert word not in green


def test_out_of_scope_headline_points_to_the_right_authority():
    """소관 밖은 '공급처 확인' 이 아니라 '다른 부처 소관' 이라고 말해야 한다."""
    from sourcing_guard.models import ProductFacts
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.verifier import RuleBook, verify

    facts = ProductFacts(
        product_name="약산성 클렌징폼", substances_mentioned=["화장품책임판매업자"]
    )
    result = score(facts, verify(facts, KatsClient(None, None, mock=True), RuleBook(), None))
    assert "소관" in result.headline
    assert "공급처에 아래 항목" not in result.headline


# --- 워치리스트 제안: GREEN 의 약점을 잇는 다리 (허점 2) --------------------
def test_green_suggests_watching_because_it_is_time_bound():
    """GREEN 은 시점 판단이라 가장 약한 신호다. 워치리스트로 유효기간을 잇는다."""
    from sourcing_guard.scorer import _watch_suggestion
    from sourcing_guard.models import Signal, ProductFacts

    facts = ProductFacts(product_name="히터", model_name="SH-100", kc_numbers=["JU071047-12002C"])
    w = _watch_suggestion(facts, Signal.GREEN, set())
    assert w.can_watch
    assert "조회 시점" in w.reason and "가장 먼저" in w.reason


def test_out_of_scope_does_not_suggest_watching():
    """우리가 리콜을 대조하지 않는 품목은 감시를 권하지 않는다 - 지킬 수 없는 약속."""
    from sourcing_guard.scorer import _watch_suggestion
    from sourcing_guard.models import Signal, ProductFacts, FindingKind

    facts = ProductFacts(product_name="클렌징폼", model_name="CF-1")
    w = _watch_suggestion(facts, Signal.UNKNOWN, {FindingKind.OUT_OF_SCOPE})
    assert not w.can_watch


def test_no_clue_means_no_watch_offer():
    """모델명·인증번호·제조사가 없으면 감시할 수 없다 (WatchItem.is_matchable 과 일치)."""
    from sourcing_guard.scorer import _watch_suggestion
    from sourcing_guard.models import Signal, ProductFacts

    facts = ProductFacts(product_name="이름만 있는 상품")
    w = _watch_suggestion(facts, Signal.GREEN, set())
    assert not w.can_watch


def test_every_signal_has_a_watch_reason():
    from sourcing_guard.scorer import _WATCH_REASON
    from sourcing_guard.models import Signal

    for sig in Signal:
        assert sig in _WATCH_REASON and _WATCH_REASON[sig].strip()


def test_watch_suggestion_matchability_matches_watchitem():
    """스캔의 can_watch 와 실제 등록의 is_matchable 이 어긋나면 안 된다.

    스캔에서 '감시 가능' 이라 했는데 등록에서 422 가 나면 사용자를 배신한다.
    """
    from sourcing_guard.scorer import _watch_suggestion
    from sourcing_guard.models import Signal, ProductFacts, WatchItem
    from datetime import date

    for facts in [
        ProductFacts(product_name="A", model_name="MDL-100"),
        ProductFacts(product_name="B", kc_numbers=["CB061R2170-3018"]),
        ProductFacts(product_name="C", maker="어느제조사"),
        ProductFacts(product_name="이름만"),
    ]:
        w = _watch_suggestion(facts, Signal.GREEN, set())
        item = WatchItem.from_facts(id="x", owner_id="o", facts=facts, on=date.today())
        assert w.can_watch == item.is_matchable(), f"불일치: {facts.product_name}"


# --- "우리가 읽은 것" 표시 (신뢰) ------------------------------------------
def test_extracted_shows_what_we_read_with_cert_link():
    """판정 위에 추출 결과를 보여줘야 셀러가 '제대로 읽었네' 를 믿는다.

    인증번호에는 정부 조회 링크를 붙여, 그 번호가 맞는지 직접 확인하게 한다.
    """
    from sourcing_guard.scorer import _extracted_fields
    from sourcing_guard.models import ProductFacts, ItemCategory

    facts = ProductFacts(
        product_name="도시락 슬라임", model_name="매직액체", maker="(주)대양무역",
        kc_numbers=["CB061R2170-3018"], materials=["PVC"],
        category=ItemCategory.CHILDREN_TOY, target_age="3세 이상",
    )
    fields = _extracted_fields(facts)
    by_label = {f.label: f for f in fields}

    assert by_label["제품명"].value == "도시락 슬라임"
    assert by_label["품목 구분"].value == "완구"          # 코드값 아닌 한국어
    cert = by_label["인증번호"]
    assert cert.value == "CB061R2170-3018"
    assert "searchPop" in cert.link and "CB061R2170-3018" in cert.link


def test_extracted_omits_empty_fields():
    """못 읽은 것을 읽은 것처럼 채우지 않는다 (R3)."""
    from sourcing_guard.scorer import _extracted_fields
    from sourcing_guard.models import ProductFacts

    fields = _extracted_fields(ProductFacts(product_name="이름만 있음"))
    labels = {f.label for f in fields}
    assert labels == {"제품명"}       # 나머지는 빈 값이라 빠진다


def test_extracted_number_matches_what_was_looked_up():
    """화면에 보이는 인증번호가 조회에 쓴 번호와 같아야 한다.

    다르면 '이 번호를 조회했다' 는 말이 거짓이 된다.
    """
    from sourcing_guard.scorer import _extracted_fields
    from sourcing_guard.models import ProductFacts

    facts = ProductFacts(product_name="x", kc_numbers=["B363R871-5002"])
    cert = next(f for f in _extracted_fields(facts) if f.label == "인증번호")
    assert "B363R871-5002" in cert.link
