"""4-d-1. 소관 안내는 **덮지 않고 병기**한다.

실측 (A-5 · 대상 109건): `out_of_scope` 한 줄이 나머지 전부를 덮어 **5건이
통째로 침묵했다.** 원인은 상품이 아니라 **셀러 공지 배너**였다.

    [필독] "3W CLINIC 화장품" 제품 쿠팡 판매 금지 …
    3W CLINIC 화장품 제품 외의 상품은 해당사항없음

전기오븐·전기주전자 5개(같은 셀러)의 `desc.notice` 에 이 문구가 있고, 추출기가
`substances_mentioned` 에 '화장품' 을 담자 스캔이 통째로 멈췄다. 셀러가
상세페이지를 붙여 넣으면 이 배너도 같이 오므로 **측정 잡음이 아니라 실제 실패
모양**이다.

가르는 기준은 **등급표 부착 여부**다. 화장품·식품에는 전안법 세부품목 등급이
붙지 않고, 전기오븐에는 붙는다.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts, Signal
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify

_KATS = KatsClient(None, None, mock=True)
_RULES = RuleBook()


def _run(facts: ProductFacts):
    findings = verify(facts, _KATS, _RULES, None)
    return findings, score(facts, findings)


def _kinds(findings) -> list[str]:
    return [f.kind.value for f in findings]


# ── 병기 ─────────────────────────────────────────────────────────────
def test_a_seller_banner_mentioning_cosmetics_no_longer_silences_the_scan():
    """실측 재현: 전기오븐 상품에 화장품 배너가 있다.

    전에는 finding 이 `out_of_scope` 한 줄만 남았다.
    """
    facts = ProductFacts(
        product_name="리빙센스1203 대용량 광파 오븐렌지 12L 전기오븐",
        substances_mentioned=["3W CLINIC 화장품", "화장품"],
        category=ItemCategory.ELECTRICAL,
    )
    findings, result = _run(facts)
    kinds = _kinds(findings)

    assert "item_grade_matched" in kinds, "등급이 사라졌다 - 그 결함 그대로다"
    assert "out_of_scope" in kinds, "소관 안내는 남아 있어야 한다"
    assert kinds != ["out_of_scope"]
    # 등급 후보에 전기오븐이 있다.
    items = [c["item"] for f in findings for c in (f.detail or {}).get("candidates", [])]
    assert "전기오븐기기" in items, items


def test_the_co_listed_line_says_the_page_mentions_it_not_that_the_product_is_it():
    """§9 단정 금지. 상품이 타 소관이라고 말하지 않는다."""
    facts = ProductFacts(
        product_name="리빙센스1203 대용량 광파 오븐렌지 12L 전기오븐",
        substances_mentioned=["화장품"],
        category=ItemCategory.ELECTRICAL,
    )
    findings, _ = _run(facts)
    line = next(f for f in findings if f.kind is FindingKind.OUT_OF_SCOPE)
    assert line.detail["standalone"] is False
    assert "이 페이지에 다른 소관" in line.statement_ko
    assert "범위 밖입니다" in line.statement_ko
    # 상품 자체를 제외 대상으로 단정하는 단독 문구가 아니다.
    assert "이 품목은 어린이제품 공통안전기준 적용 대상에서 제외됩니다" not in line.statement_ko


def test_co_listed_out_of_scope_does_not_take_over_signal_or_headline():
    """다섯 곳이 각자 덮고 있었다. 입구에서 한 번 가른다."""
    facts = ProductFacts(
        product_name="리빙센스1203 대용량 광파 오븐렌지 12L 전기오븐",
        substances_mentioned=["화장품"],
        category=ItemCategory.ELECTRICAL,
    )
    _findings, result = _run(facts)
    assert "본 서비스 범위 밖" not in result.headline
    assert result.coverage_note is None or "규제 범위 밖" not in result.coverage_note
    # 감시 권유가 소관 밖 이유로 꺼지지 않는다.
    assert "리콜을 대조하는 범위 밖" not in result.watch_suggestion.reason


# ── 단독 ─────────────────────────────────────────────────────────────
def test_a_real_cosmetic_still_short_circuits_to_a_single_finding():
    """등급이 안 붙으면 지금처럼 단독이다."""
    facts = ProductFacts(
        product_name="코시앙 클렌징폼",
        substances_mentioned=["화장품책임판매업자", "EWG"],
        category=ItemCategory.UNCLASSIFIED,
    )
    findings, result = _run(facts)
    assert _kinds(findings) == ["out_of_scope"]
    line = findings[0]
    assert line.detail["standalone"] is True
    assert "이 품목은 어린이제품 공통안전기준 적용 대상에서 제외됩니다" in line.statement_ko
    assert result.signal is Signal.UNKNOWN
    assert "본 서비스 범위 밖" in result.headline
    assert result.watch_suggestion.can_watch is False


def test_no_out_of_scope_marker_means_no_line_at_all():
    facts = ProductFacts(
        product_name="리빙센스1203 대용량 광파 오븐렌지 12L 전기오븐",
        category=ItemCategory.ELECTRICAL,
    )
    findings, _ = _run(facts)
    assert "out_of_scope" not in _kinds(findings)


# ── scorer 경계 ──────────────────────────────────────────────────────
def test_scorer_reads_the_flag_and_does_not_decide_it_itself():
    """verifier 가 사실(등급이 붙었나)을 적고 scorer 가 신호를 정한다 (R1).

    같은 findings 를 flag 만 바꿔 넣으면 신호가 갈린다 - scorer 가 그 값을
    실제로 읽고 있다는 뜻이다.
    """
    from datetime import date

    from sourcing_guard.models import Finding

    facts = ProductFacts(product_name="전기오븐", category=ItemCategory.ELECTRICAL)
    base = Finding(
        kind=FindingKind.RECALL_CLEAR, signal=Signal.GREEN,
        statement_ko="리콜 목록에서 일치 항목을 찾지 못했습니다.",
        source_label="제품안전정보센터", source_url="https://www.safetykorea.kr/",
        checked_at=date.today(),
    )

    def oos(standalone: bool) -> Finding:
        return Finding(
            kind=FindingKind.OUT_OF_SCOPE, signal=Signal.UNKNOWN,
            statement_ko="안내",
            source_label="어린이제품 공통안전기준 1. 적용범위",
            source_url="https://law.go.kr/행정규칙/어린이제품공통안전기준",
            detail={"reason": "화장품 (화장품법 / 식약처 소관)",
                    "standalone": standalone},
            checked_at=date.today(),
        )

    solo = score(facts, [base, oos(True)])
    both = score(facts, [base, oos(False)])
    assert "본 서비스 범위 밖" in solo.headline
    assert "본 서비스 범위 밖" not in both.headline
    # 화면에서는 두 경우 다 그 줄이 남는다.
    assert any(f.kind is FindingKind.OUT_OF_SCOPE for f in both.findings)
