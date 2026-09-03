"""부재가 정상인 등급은 감점하지 않는다 (CLAUDE.md R3-b).

정상 상품에 노란불이 반복되면 셀러가 모든 노란불을 무시하게 되고, 그러면
진짜 취소된 인증도 안 보게 된다. 그동안은 "인증 구분을 판별하지 못했습니다"
라서 물러섰던 자리인데, 세부품목 등급표를 붙여 판별이 되니 갈 수 있다.
"""

from __future__ import annotations

from datetime import date

import pytest

from sourcing_guard.models import (
    Finding,
    FindingKind,
    FindingGroup,
    ItemCategory,
    ProductFacts,
    Signal,
)
from sourcing_guard.scorer import _HARD_RED, _PENALTY, _unknown_headline, score
from sourcing_guard.verifier import _ABSENCE_IS_NORMAL, _kc_missing_finding

TODAY = date(2026, 9, 3)


def missing(grade: str | None) -> Finding:
    facts = ProductFacts(product_name="테스트 상품", category=ItemCategory.ELECTRICAL)
    return _kc_missing_finding(facts, TODAY, grade=grade)


# ---------------------------------------------------------------------------
# 등급별로 갈린다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grade", ["안전인증", "안전확인"])
def test_required_grades_stay_amber_and_speak_harder(grade):
    """번호가 반드시 있어야 하는 등급은 일반론보다 세게 말한다.

    2026-09-03 갱신: 의무 문장("{grade} 대상이면 인증번호가 반드시 있어야
    합니다")이 여기서 ITEM_GRADE_MATCHED 로 옮겨졌다. 중복 가드
    (test_no_repeated_facts)가 두 finding 이 같은 문장을 말하는 것을 잡았고,
    등급의 뜻은 품목명·범위 한정과 함께 말하는 등급 finding 이 맡는 것이
    맞다. 이 문장이 하는 일은 "등급을 지목하고 부재를 알린다" 로 좁혀졌다.

    문장이 아예 사라지지는 않았는지는 아래
    test_the_obligation_sentence_survives_somewhere 가 지킨다.
    """
    f = missing(grade)
    assert f.kind is FindingKind.KC_MISSING_BUT_REQUIRED
    assert f.signal is Signal.AMBER
    assert _PENALTY[f.kind] > 0
    # 품목군이 아니라 등급을 지목한다 - 그게 강화다.
    assert f"{grade} 대상으로 조회되는데" in f.statement_ko
    assert "인증번호를 찾지 못했습니다" in f.statement_ko
    # 일반론은 빠졌다.
    assert "안전인증·안전확인 대상이면" not in f.statement_ko


@pytest.mark.parametrize(
    "name, grade",
    [
        ("신일 BLDC 무선 선풍기 14인치", "안전인증"),
        ("모즈온 미니 도킹 보조배터리 5000 C타입", "안전확인"),
    ],
)
def test_the_obligation_sentence_survives_somewhere(name, grade):
    """중복을 없애다가 정보를 잃으면 안 된다.

    의무 문장은 결과 어딘가에 **정확히 한 번** 있어야 한다. 없으면 셀러가
    "번호가 없다" 만 읽고 그것이 문제인지 모른다.
    """
    from sourcing_guard.verifier import _GRADE_MEANING, _item_grade_findings

    graded = _item_grade_findings(name, TODAY)
    texts = [g.statement_ko for g in graded] + [missing(grade).statement_ko]
    hits = [t for t in texts if _GRADE_MEANING[grade] in t]
    assert len(hits) == 1, hits


@pytest.mark.parametrize("grade", sorted(_ABSENCE_IS_NORMAL))
def test_absence_normal_grades_are_not_penalised(grade):
    f = missing(grade)
    assert f.kind is FindingKind.KC_ABSENCE_EXPECTED
    assert _PENALTY[f.kind] == 0
    assert f.kind not in _HARD_RED
    # 시험성적서 요청은 여전히 셀러가 할 일이라 맨 위 구획이다.
    assert f.group is FindingGroup.ACTION


@pytest.mark.parametrize("grade", sorted(_ABSENCE_IS_NORMAL))
def test_absence_normal_copy_never_uses_exemption_language(grade):
    """"인증이 필요 없다" 는 틀리다 - 스스로 확인할 의무가 있다.

    정확한 표현은 "조회 DB 에 번호가 없는 것이 정상" 이다.
    """
    text = missing(grade).statement_ko
    for bad in ("없어도 됩니다", "필요 없습니다", "필요없습니다", "면제",
                "대상이 아닙니다", "안 받아도"):
        assert bad not in text, (bad, text)
    # 2026-09-03 갱신: "정부 조회 DB 에 번호가 없는 것이 정상" 이 여기서
    # ITEM_GRADE_MATCHED 로 옮겨졌다(중복 가드가 잡았다). 여기서는 우리
    # 판단만 밝힌다 - 부재를 문제로 보지 않았다는 것.
    assert "부재가 정상이므로 문제로 보지 않았습니다" in text
    # 등급의 뜻은 등급 finding 에 정확히 한 번 있어야 한다.
    from sourcing_guard.verifier import _GRADE_MEANING
    assert _GRADE_MEANING[grade].endswith("번호가 없는 것이 정상입니다")


def test_unknown_grade_keeps_the_general_explanation():
    f = missing(None)
    assert f.kind is FindingKind.KC_MISSING_BUT_REQUIRED
    assert "안전인증·안전확인 대상이면" in f.statement_ko


# ---------------------------------------------------------------------------
# 갈릴 때는 감점을 빼지 않는다
# ---------------------------------------------------------------------------


def test_split_grades_never_reach_the_absence_path():
    """공기청정기는 안전확인 ↔ 공급자적합성확인 이다.

    느슨한 쪽을 골라 감점을 빼면, 화면에서 세 겹으로 막은 "한쪽 단정" 을
    신호등에서 하는 셈이다. verify() 는 합의 등급만 넘긴다.
    """
    from sourcing_guard.verifier import _item_grade_findings

    graded = _item_grade_findings("HK HAIKE 소형 미니공기청정기", TODAY)
    assert graded and graded[0].kind is FindingKind.ITEM_GRADE_SPLIT
    agreed = next(
        (g.detail.get("grade") for g in graded
         if g.kind is FindingKind.ITEM_GRADE_MATCHED),
        None,
    )
    assert agreed is None
    assert missing(agreed).kind is FindingKind.KC_MISSING_BUT_REQUIRED


# ---------------------------------------------------------------------------
# 감점을 빼도 GREEN 이 되지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("grade", sorted(_ABSENCE_IS_NORMAL))
def test_removing_the_penalty_does_not_produce_green(grade):
    """GREEN 은 두 축의 적극적 증거를 요구한다.

    공급자적합성확인은 조회할 번호가 없어 인증 축을 못 채운다. 부재는
    증거가 아니다 (R3).
    """
    facts = ProductFacts(product_name="테스트 상품", category=ItemCategory.ELECTRICAL)
    findings = [
        missing(grade),
        Finding(
            kind=FindingKind.RECALL_CLEAR, signal=Signal.GREEN,
            statement_ko="리콜 목록에서 일치를 찾지 못했습니다.",
            source_label="국가기술표준원 리콜정보",
            source_url="https://www.safetykorea.kr/recall",
        ),
    ]
    result = score(facts, findings)
    assert result.signal is Signal.UNKNOWN, result.signal


# ---------------------------------------------------------------------------
# 헤드라인이 "번호 없는 게 정상" 을 말한다
# ---------------------------------------------------------------------------


def _headline(kinds: set[FindingKind], grade: str = "공급자적합성확인") -> str:
    return _unknown_headline(kinds, has_extracted=True, absence_grade=grade)


def test_headline_says_the_absence_is_normal():
    """finding 안에만 묶어 두면 첫 줄만 읽는 셀러가 못 본다."""
    text = _headline({FindingKind.KC_ABSENCE_EXPECTED, FindingKind.RECALL_CLEAR})
    assert "인증번호 부재가 정상" in text
    assert "공급자적합성확인" in text
    assert "번호가 없는 것이 정상" in text
    assert "리콜 이력도 확인되지 않았습니다" in text
    # 초록불로 읽히지 않게 한계를 병기한다.
    assert "시험성적서" in text


def test_headline_does_not_claim_recalls_were_checked_when_lookup_failed():
    """대조하지 않은 것을 대조했다고 말할 수 없다 (R3)."""
    text = _headline({FindingKind.KC_ABSENCE_EXPECTED, FindingKind.LOOKUP_FAILED})
    assert "리콜 이력도 확인되지 않았습니다" not in text
    assert "리콜 조회에는 연결하지 못했습니다" in text


def test_headline_appends_our_coverage_limit_instead_of_hiding_it():
    """수록 범위를 감추지 않는다. 다만 셀러의 급한 질문에 먼저 답한다."""
    text = _headline({FindingKind.KC_ABSENCE_EXPECTED, FindingKind.COVERAGE_GAP})
    assert "인증번호 부재가 정상" in text
    assert "유해물질 기준은 아직 수록되지 않았습니다" in text


@pytest.mark.parametrize(
    "kind",
    [FindingKind.OUT_OF_SCOPE, FindingKind.AGE_OUT_OF_CHILD_RANGE],
)
def test_more_settled_judgements_still_win_the_headline(kind):
    """"우리 소관 아님"·"연령 기준 대상 아님" 은 품목 자체에 대한 확정 판단이다."""
    text = _headline({FindingKind.KC_ABSENCE_EXPECTED, kind})
    assert "인증번호 부재가 정상" not in text


def test_headline_falls_back_when_no_grade_is_given():
    text = _unknown_headline(
        {FindingKind.KC_ABSENCE_EXPECTED}, has_extracted=True, absence_grade=None
    )
    assert "인증번호 부재가 정상" not in text
