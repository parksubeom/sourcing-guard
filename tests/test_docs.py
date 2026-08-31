"""제출 서류에 대한 회귀 테스트.

기획서는 심사위원이 읽는 문서다. 틀린 기준치가 남아 있으면 코드가 아무리
정확해도 발표에서 그 숫자를 공개하게 된다. 문서도 테스트 대상으로 둔다.
"""

from pathlib import Path

import pytest
import yaml

PROPOSAL = Path("01_기획서_안심소싱돋보기.md")
RULES = Path("sourcing_guard/data/hazard_rules.yaml")


@pytest.fixture(scope="module")
def proposal() -> str:
    return PROPOSAL.read_text(encoding="utf-8")


@pytest.mark.parametrize("retired", ["300mg/kg", "300 mg/kg"])
def test_proposal_does_not_cite_the_retired_lead_limit(proposal, retired):
    """'납 300 mg/kg' 은 완구 부속서의 옛 기준치이며 100 으로 개정됐다.

    공통안전기준의 납 기준은 용출 90 / 함유량 100(페인트·표면코팅 90)이다.
    초기 기획안이 300 을 반복해서 적고 있었다.
    """
    assert retired not in proposal, (
        f"기획서에 폐지된 기준치 '{retired}' 가 있습니다. "
        "공통안전기준의 납 기준은 용출 90 / 함유량 100 입니다."
    )


def test_proposal_limits_match_the_rule_book(proposal):
    """기획서가 인용한 수치는 규칙 DB 와 같은 출처에서 와야 한다.

    문서와 코드가 각자 숫자를 들고 있으면 한쪽만 고쳐지고 조용히 갈라진다.
    실제로 '납 300' 이 그렇게 남아 있었다.
    """
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}

    expected = {
        "KC-COMMON-3.1.1-PB": (90, "납 용출"),
        "KC-COMMON-3.1.2-PB": (100, "총 납 함유량"),
        "KC-COMMON-3.1.3-PHT": (0.1, "프탈레이트 총합"),
    }
    for rule_id, (value, label) in expected.items():
        assert by_id[rule_id]["limit_value"] == value, label

    for cited in ("90mg/kg", "100mg/kg", "0.1%"):
        assert cited in proposal, f"기획서에 '{cited}' 인용이 없습니다"


def test_no_rule_is_promoted_without_a_reviewer():
    """verified 승격은 사람이 원문을 대조한 기록과 함께여야 한다 (CLAUDE.md R5)."""
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    bad = [
        r["id"]
        for r in raw["rules"]
        if r.get("status") == "verified" and not (r.get("verified_by") and r.get("verified_at"))
    ]
    assert not bad, f"검수자 기록 없이 verified 로 승격된 룰: {bad}"
