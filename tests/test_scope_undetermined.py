"""[판정 1] `out_of_scope` 인데 아무 말도 못 하던 경로에 이유를 붙인다.

문제
----
`facts.category is OUT_OF_SCOPE` 이고 `scope_reason`(코드가 찾은 근거)이 없으면
**양쪽이 다 막혔다**:

    단독 OUT_OF_SCOPE 안내   `scope_reason` 이 없어서 안 나간다
    등급표 조회              `_GRADE_LOOKUP_OPEN` 에 out_of_scope 가 없어 안 돈다

그래서 화면에 우리 질문(`info_request`)만 남았다. A-5 실측에서 상세 109 중
2건이 그렇게 침묵했다 — [146] 방수매트 · [165] 미술 앞치마.

왜 이렇게 풀었나
----------------
4-e 는 **등급 게이트를 여는 쪽**으로 풀려다 애매 부착이 1 → 2 로 늘어
되돌렸다(미완 4-e′). 26번(종이호일)과 146·165 를 가를 신호를 찾지 못했다.
이 출구는 게이트를 건드리지 않고 **침묵의 이유만** 말한다.

⚠⚠ 이 finding 은 `NON_SPECIFIC_FINDING_KINDS` 다. 아무것도 못 준 줄이 "유효"
  로 뒤집히면 지표가 부푼다 — `recall_clear` · `recall_weak_match` 를 뺀 것과
  정확히 같은 이유다.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from sourcing_guard.models import (
    NON_SPECIFIC_FINDING_KINDS,
    SPECIFIC_FINDING_KINDS,
    FindingKind,
    ItemCategory,
    ProductFacts,
    Signal,
)
from sourcing_guard.scorer import has_specific_finding, score
from sourcing_guard.verifier import RuleBook, verify


@pytest.fixture(scope="module")
def rules() -> RuleBook:
    return RuleBook()


@pytest.fixture
def kats():
    m = MagicMock()
    m.lookup_certification_cached.return_value = MagicMock(record=None)
    return m


def _verify(pn: str, category: ItemCategory, kats, rules, **kw):
    facts = ProductFacts(product_name=pn, category=category, **kw)
    return facts, verify(facts, kats, rules, raw_text=pn)


# ── 침묵이 끝났다 ───────────────────────────────────────────────────
@pytest.mark.parametrize("pn", [
    "무독성 사계절 다용도 방수매트 김장매트 180cm 특대형",   # A-5 [146]
    "일회용 방수 미술 물감 앞치마+팔토시(2개) 세트",        # A-5 [165]
])
def test_the_two_silent_rows_now_get_a_reason(pn, kats, rules):
    """실측에서 침묵했던 두 줄이 이유를 받는다."""
    _facts, findings = _verify(pn, ItemCategory.OUT_OF_SCOPE, kats, rules)
    kinds = {f.kind for f in findings}
    assert FindingKind.SCOPE_UNDETERMINED in kinds, sorted(k.value for k in kinds)


def test_the_statement_speaks_to_the_seller_not_about_our_internals(kats, rules):
    """"추출기가 헷갈렸다" 는 화면에 쓸 말이 아니다."""
    _facts, findings = _verify("무독성 방수매트 김장매트", ItemCategory.OUT_OF_SCOPE,
                               kats, rules)
    f = next(x for x in findings if x.kind is FindingKind.SCOPE_UNDETERMINED)

    # 우리 내부 사정을 노출하지 않는다.
    for word in ("추출기", "LLM", "분류기", "헷갈", "category"):
        assert word not in f.statement_ko, f"내부 사정이 노출됐다: {word}"

    # ⚠⚠ **두 가능성을 나란히 적는다. 소관 쪽으로 단정하지 않는다.**
    #
    #   첫 문구는 "다른 법의 소관일 가능성이 있어 … 판단하지 않았습니다" 였다.
    #   그런데 이 finding 이 붙는 12건 중 **2건이 대상으로 검수된 줄**이었다 -
    #   [CU] 핏미업 러닝벨트 · [202] 지압슬리퍼. 그 줄에서 "다른 법 소관" 은
    #   틀린 정보이고 셀러를 전안법에서 멀어지게 한다.
    assert "찾지 못했습니다" in f.statement_ko
    assert "다른 법의 소관일 수도" in f.statement_ko
    assert "이 표가 놓친 것일 수도" in f.statement_ko
    assert "특정하지 못했습니다" in f.statement_ko

    # ⚠ 소관 쪽으로 기울지 않는다 - 두 갈래가 대등해야 한다.
    assert "가능성이 있어" not in f.statement_ko, (
        "소관 쪽으로 단정하는 옛 문구가 돌아왔다"
    )

    # ⚠ 어느 법인지 모르면 법 이름을 열거하지 않는다 (R5).
    for law in ("식약처", "식품의약품안전처", "산업통상자원부", "화장품법",
                "식품위생법", "약사법", "의료기기법"):
        assert law not in f.statement_ko, f"모르는 것을 말하고 있다: {law}"


def test_the_finding_has_a_real_legal_basis_url(kats, rules):
    """R2 — 근거 URL 이 있고, 그 원문이 **이 도구의 범위**를 말한다.

    ⚠ 조항 번호를 새로 지어내지 않았다 (R5). `verifier._GRADE_SOURCE` 가 이미
      쓰는 표기를 그대로 재사용한다 - `item_grades.yaml` 561건이 그 별표에서
      나왔으므로, "이 표에 없으면 등급을 말하지 않는다" 의 근거로 정확하다.

    ⚠ 2026-09-11 에 DRF OpenAPI 로 실재를 확인했다 - 행정규칙 ID 34911 ·
      국가기술표준원 · 시행 20260826 · 조문 111개 · 본문에 "별표 1" 19회.
      ⚠ 웹 URL 은 프레임셋이라 `curl` 로는 본문 텍스트가 안 나온다(19자).
        200 이 왔다고 본문을 봤다고 하지 않는다.
    """
    from sourcing_guard.verifier import _GRADE_SOURCE

    _facts, findings = _verify("무독성 방수매트 김장매트", ItemCategory.OUT_OF_SCOPE,
                               kats, rules)
    f = next(x for x in findings if x.kind is FindingKind.SCOPE_UNDETERMINED)

    assert f.source_url == _GRADE_SOURCE[1]
    assert f.source_label == _GRADE_SOURCE[0]
    assert "law.go.kr" in f.source_url
    assert "운용요령" in f.source_label and "별표" in f.source_label
    # 등급표가 같은 원문에서 나왔다는 것이 이 근거의 정당성이다.
    from sourcing_guard.item_grades import ItemGradeBook

    book = ItemGradeBook()
    assert book, "등급표가 비었다 - 이 검사의 전제가 바뀌었다"


# ── 지표가 움직이지 않는다 ──────────────────────────────────────────
def test_it_is_not_counted_as_a_specific_finding(kats, rules):
    """⚠⚠ 아무것도 못 준 줄이 "유효" 로 뒤집히면 지표가 부푼다."""
    assert FindingKind.SCOPE_UNDETERMINED in NON_SPECIFIC_FINDING_KINDS
    assert FindingKind.SCOPE_UNDETERMINED not in SPECIFIC_FINDING_KINDS

    _facts, findings = _verify("무독성 방수매트 김장매트", ItemCategory.OUT_OF_SCOPE,
                               kats, rules)
    # 이 줄은 등급도 인증도 못 받았다 - 여전히 "구체적인 것 없음" 이어야 한다.
    assert not has_specific_finding(findings), sorted(f.kind.value for f in findings)


def test_the_classification_is_still_complete_and_disjoint():
    """합 = 전체 · 겹침 0 을 계속 지킨다 (종류가 31 로 늘었다)."""
    everything = set(FindingKind)
    assert SPECIFIC_FINDING_KINDS | NON_SPECIFIC_FINDING_KINDS == everything
    assert not (SPECIFIC_FINDING_KINDS & NON_SPECIFIC_FINDING_KINDS)
    assert len(everything) == 31


def test_the_signal_does_not_move(kats, rules):
    """§9 — 신호등을 건드리지 않는다. UNKNOWN 이고 그대로다."""
    facts, findings = _verify("무독성 방수매트 김장매트", ItemCategory.OUT_OF_SCOPE,
                              kats, rules)
    f = next(x for x in findings if x.kind is FindingKind.SCOPE_UNDETERMINED)
    assert f.signal is Signal.UNKNOWN

    with_it = score(facts, findings)
    without = score(facts, [x for x in findings
                            if x.kind is not FindingKind.SCOPE_UNDETERMINED])
    assert with_it.signal is without.signal, "이 finding 이 신호를 바꾼다"


# ── 경계 ────────────────────────────────────────────────────────────
def test_it_does_not_appear_when_the_code_found_a_reason(kats, rules):
    """`scope_reason` 이 있으면 붙이지 않는다.

    그때는 (단독이거나 병기된) OUT_OF_SCOPE 안내가 나간다. 둘을 같이 내면
    "확인했다" 와 "확인 못 했다" 가 한 화면에 같이 뜬다.
    """
    from sourcing_guard.verifier import out_of_scope_reason

    # 코드가 확실히 잡는 하드 신호를 넣는다.
    pn = "수분크림 화장품책임판매업자 표기 제품"
    reason = out_of_scope_reason(pn, None)
    assert reason, "이 검사의 전제가 바뀌었다 - 코드가 근거를 못 찾는다"

    _facts, findings = _verify(pn, ItemCategory.OUT_OF_SCOPE, kats, rules)
    kinds = {f.kind for f in findings}
    assert FindingKind.SCOPE_UNDETERMINED not in kinds
    assert FindingKind.OUT_OF_SCOPE in kinds


@pytest.mark.parametrize("category", [
    ItemCategory.CHILDREN_TOY,
    ItemCategory.ELECTRICAL,
    ItemCategory.HOUSEHOLD,
    ItemCategory.UNCLASSIFIED,
])
def test_it_does_not_appear_for_other_categories(category, kats, rules):
    """`out_of_scope` 가 아닌 분류에는 붙지 않는다.

    ⚠ `UNCLASSIFIED` 도 포함이다. "판별 못 함" 과 "타 소관 가능성" 은 다른
      말이고, 섞으면 판별 실패가 소관 문제로 읽힌다.
    """
    _facts, findings = _verify("전기 방석 온열 매트", category, kats, rules)
    kinds = {f.kind for f in findings}
    assert FindingKind.SCOPE_UNDETERMINED not in kinds


def test_the_grade_gate_was_not_touched():
    """⚠ 4-e 를 되돌린 게이트를 건드리지 않았다.

    여기서 깨지면 애매 부착이 늘었는지 먼저 볼 것 (미완 4-e′).

    ⚠ `_GRADE_LOOKUP_OPEN` 은 `verify()` **안의 지역 변수**라 import 할 수
      없다. 그래서 소스로 확인한다 - 처음에 import 로 짰다가 ImportError 를
      봤다.
    """
    import inspect

    from sourcing_guard import verifier

    src = inspect.getsource(verifier.verify)
    gate = src.split("_GRADE_LOOKUP_OPEN = (")[1].split(")")[0]
    assert "UNCLASSIFIED" in gate
    assert "OUT_OF_SCOPE" not in gate, (
        "out_of_scope 가 등급표 게이트에 들어왔다 - 4-e 를 다시 연 것인가"
    )


def test_every_finding_kind_has_a_penalty_entry():
    """⚠⚠ `_PENALTY` 에 없는 kind 는 `score()` 에서 **KeyError** 가 된다.

    2026-09-11 에 `SCOPE_UNDETERMINED` 를 추가하며 실제로 겪었다. 그 finding 이
    나오는 모든 스캔이 500 이 됐을 것이다.

    ⚠ `scorer` 는 **임포트 시점에** 같은 것을 단정한다 - 검사를 안 돌려도 앱이
      부팅할 때 터지므로 배포본이 500 을 내기 전에 드러난다. 이 검사는 그
      단정이 사라지지 않게 잠근다.

    ⚠ `.get(kind, 0)` 으로 바꾸지 말 것. KeyError 는 없어지지만 감점이 필요한
      kind 를 추가했을 때 **조용히 0** 이 되어 위험을 놓치는 쪽으로 틀린다.
    """
    import inspect

    from sourcing_guard import scorer

    assert set(FindingKind) == set(scorer._PENALTY), sorted(
        k.value for k in set(FindingKind) - set(scorer._PENALTY)
    )
    # 임포트 시점 단정이 살아 있는지 - 소스로 확인한다.
    src = inspect.getsource(scorer)
    assert "_MISSING_PENALTY" in src and "raise RuntimeError" in src
    assert "_PENALTY[f.kind]" in src, "get(…, 0) 으로 바뀌었다 - 조용히 틀린다"


def test_the_detail_records_the_extractor_verdict_not_ours(kats, rules):
    """R1 — 추출기 분류를 그대로 남긴다. 우리 판정이 아니다."""
    _facts, findings = _verify("무독성 방수매트 김장매트", ItemCategory.OUT_OF_SCOPE,
                               kats, rules)
    f = next(x for x in findings if x.kind is FindingKind.SCOPE_UNDETERMINED)
    assert f.detail["extractor_category"] == "out_of_scope"
    assert f.detail["scope_reason_found"] is False
    # 판정 필드를 두지 않는다.
    for banned in ("risk_score", "is_safe", "verdict", "is_legal"):
        assert banned not in f.detail


# ── 판정: 대상 줄에도 틀리지 않아야 한다 ────────────────────────────
@pytest.mark.parametrize("pn,note", [
    ("[CU] 핏미업 러닝벨트 힙색 슬링백 벨트백 스포츠 러닝", "부속서 1 기타 제품류"),
    ("지압슬리퍼 사무실 실내화 다이어트 슬리퍼", "신발류"),
])
def test_the_statement_is_not_false_on_rows_that_are_actually_in_scope(pn, note, kats, rules):
    """**대상으로 검수된 줄에도 틀리지 않는다.**

    추출기가 `out_of_scope` 로 오분류한 줄이 실측 12건 중 2건이었다. 그 줄은
    "이 표가 놓친" 쪽이므로, 두 갈래를 나란히 적은 문구는 참이다.

    ⚠ 소관 쪽으로 단정하면 셀러를 전안법에서 멀어지게 한다 - 없는 의무를
      만드는 것의 거울이고, 우리 오류 비대칭에서 더 비싼 쪽이다.
    """
    _facts, findings = _verify(pn, ItemCategory.OUT_OF_SCOPE, kats, rules)
    f = next(x for x in findings if x.kind is FindingKind.SCOPE_UNDETERMINED)
    # 두 갈래가 모두 있어야 이 줄에서 참이 된다.
    assert "다른 법의 소관일 수도" in f.statement_ko
    assert "이 표가 놓친 것일 수도" in f.statement_ko, note


def test_it_says_something_coverage_gap_does_not(kats, rules):
    """`coverage_gap` 과 중복이 아니다.

    ⚠ "판단하지 못했습니다" 로 일반화하면 `coverage_gap` 과 같은 말이 된다 -
      침묵 줄에는 이미 그것이 붙어 있다. 이 finding 의 몫은 **두 갈래를
      명시하는 것**이고, 그것이 실제 우리 앎의 상태다 (R3).
    """
    _facts, findings = _verify("무독성 방수매트 김장매트", ItemCategory.OUT_OF_SCOPE,
                               kats, rules)
    kinds = {f.kind for f in findings}
    assert FindingKind.COVERAGE_GAP in kinds, "이 검사의 전제가 바뀌었다"

    gap = next(x for x in findings if x.kind is FindingKind.COVERAGE_GAP)
    ours = next(x for x in findings if x.kind is FindingKind.SCOPE_UNDETERMINED)
    # 두 갈래를 말하는 것은 우리 쪽뿐이다.
    assert "다른 법의 소관일 수도" not in gap.statement_ko
    assert "다른 법의 소관일 수도" in ours.statement_ko


def test_self_limitation_is_allowed_but_internals_are_not(kats, rules):
    """"우리 표가 놓쳤을 수도" 는 자기 한계 표기이지 내부 사정 노출이 아니다.

    금지되는 것은 "추출기가 헷갈렸다" 처럼 **우리 구현을 셀러에게 설명하는
    것**이고, "우리 표에 없다" 는 셀러가 다음 행동을 정하는 데 쓰는 사실이다.
    그 구분을 코드에도 적어 뒀는지 확인한다.
    """
    import inspect

    from sourcing_guard import verifier

    src = inspect.getsource(verifier.verify)
    assert "자기 한계 표기" in src, "구분이 주석에 없다"

    _facts, findings = _verify("무독성 방수매트 김장매트", ItemCategory.OUT_OF_SCOPE,
                               kats, rules)
    f = next(x for x in findings if x.kind is FindingKind.SCOPE_UNDETERMINED)
    for word in ("추출기", "LLM", "분류기", "헷갈", "category", "scope_reason"):
        assert word not in f.statement_ko
