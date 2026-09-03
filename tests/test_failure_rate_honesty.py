"""부적합률을 다룰 때 비율만 보여주지 않는다.

기획서 초안에서 "해외직구 부적합률 19%, 국내 5% — 4배" 라고 썼다가 고쳤다.
국표원 조사는 계절·이슈 품목을 **표적 조사**한 것이라 무작위 표본이 아니고,
국내 5% 는 유통제품 평균이라 조사 설계가 다르다. 직접 비교하면 과장이 된다.

품목별 수치는 더 위험하다. "속눈썹 열 성형기 88%" 는 **8개 중 7개**다.
비율만 보여주면 표본 8개짜리가 통계처럼 읽힌다.

이 파일은 그 실수가 문서와 코드에서 되살아나지 않게 막는다.
"""

from pathlib import Path

import sourcing_guard

_DOC = Path(sourcing_guard.__file__).parent.parent / "01_기획서_안심소싱돋보기.md"


def _proposal() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_proposal_flags_the_targeted_sampling():
    """표적 조사임을 밝히지 않으면 19% 가 전체 평균으로 읽힌다."""
    text = _proposal()
    assert "표적 조사" in text
    assert "무작위 표본이 아니라" in text or "무작위 표본이 아닌" in text


def test_proposal_does_not_claim_a_direct_multiple():
    """'해외직구가 국내의 4배' 같은 직접 비교는 조사 설계가 달라 성립하지 않는다."""
    text = _proposal()
    for phrase in ("4배입니다", "네 배입니다"):
        assert phrase not in text, f"직접 비교 표현이 되살아났다: {phrase}"


def test_item_failure_rates_carry_sample_sizes():
    """품목별 수치는 표본 크기와 함께 제시해야 한다.

    표본 8개짜리 88% 를 비율만 적으면 통계로 오독된다.
    """
    text = _proposal()
    # 표본 컬럼이 있는 표로 제시하고 있는지
    assert "| 품목 | 부적합 | 표본 |" in text
    # 대표 사례의 분자·분모가 모두 문서에 있어야 한다
    for numerator, denominator in (("7", "8"), ("15", "37")):
        assert f"| {numerator} | {denominator} |" in text


def test_rule_db_failure_rate_requires_a_sample():
    """규칙 DB 에 부적합률을 담을 때도 표본 없이 비율만 두면 안 된다.

    아직 failure_rate 필드를 쓰는 룰이 없지만, 생기는 순간 이 가드가 걸린다.
    """
    import yaml

    path = Path(sourcing_guard.__file__).parent / "data" / "hazard_rules.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = doc["rules"] if isinstance(doc, dict) and "rules" in doc else doc

    for rule in rules:
        rate = rule.get("failure_rate")
        if rate is None:
            continue
        assert "sample" in rate, f"{rule['id']}: 부적합률에 표본 크기가 없다"
        assert "source" in rate, f"{rule['id']}: 부적합률에 출처가 없다"
