"""제출 서류에 대한 회귀 테스트.

기획서는 심사위원이 읽는 문서다. 틀린 기준치가 남아 있으면 코드가 아무리
정확해도 발표에서 그 숫자를 공개하게 된다. 문서도 테스트 대상으로 둔다.
"""

from pathlib import Path

import pytest
import yaml

from sourcing_guard.models import FindingKind
from sourcing_guard.scorer import _HARD_RED

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


def _table_row(proposal: str, signal: str) -> str:
    """기획서 §3 신호등 표에서 한 행을 뽑는다."""
    rows = [ln for ln in proposal.splitlines() if ln.startswith(f"| {signal} ")]
    assert len(rows) == 1, f"{signal} 행을 특정하지 못했습니다: {len(rows)}건"
    return rows[0]


def test_proposal_traffic_light_matches_the_scorer(proposal):
    """기획서의 신호등 표는 scorer 의 실제 동작과 같아야 한다 (CLAUDE.md R3-b).

    RED 는 정부 DB 가 문제를 적어둔 경우에만 준다. 미조회는 AMBER 다.
    전안법 위해도 최하단인 공급자적합성확인(SCoC) 대상은 제조·수입자가 스스로
    시험해 확인하므로 조회 DB 에 번호가 없는 것이 정상이기 때문이다.

    §6.1 은 이 내용으로 고쳐졌는데 §3 표만 "미조회 → RED" 로 남아 있었다.
    심사위원이 읽는 문서라 코드가 아무리 정확해도 발표에서 틀린 동작을 설명하게 된다.
    """
    assert FindingKind.KC_NOT_FOUND not in _HARD_RED, (
        "scorer 가 미조회를 RED 로 되돌렸습니다. 기획서 §3 표와 §6.1 도 함께 고치세요 (R3-b)."
    )

    red = _table_row(proposal, "🔴 RED")
    assert "미조회" not in red, (
        f"기획서 RED 행이 미조회를 RED 로 적고 있습니다 (코드는 AMBER): {red}"
    )

    amber = _table_row(proposal, "🟡 AMBER")
    assert "미조회" in amber, (
        f"기획서 AMBER 행에 미조회가 없습니다: {amber}"
    )


def test_proposal_phthalate_count_matches_the_rule_book(proposal):
    """기획서가 인용한 프탈레이트 물질 수는 규칙 DB 가 실제로 담은 수와 같아야 한다.

    확보한 원문(2020년판)은 6종이다. 현행 고시를 인용한 2차 자료에는 DIBP 가
    더해져 7종이라는 기술이 있으나 원문 미확인이다 (docs/규칙DB_검수목록.md §2).
    기획서가 7종이라고 단정하면 검증 안 된 값을 제출 서류에 싣는 것이다 (R5).
    """
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}
    covered = len(by_id["KC-COMMON-3.1.3-PHT"]["substances_covered"])

    assert f"프탈레이트 {covered}종" in proposal, (
        f"규칙 DB 는 프탈레이트 {covered}종을 담고 있는데 기획서 표기가 다릅니다. "
        "원문에서 확인한 수만 적으세요 (R5)."
    )


def test_no_rule_is_promoted_without_a_reviewer():
    """verified 승격은 사람이 원문을 대조한 기록과 함께여야 한다 (CLAUDE.md R5)."""
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    bad = [
        r["id"]
        for r in raw["rules"]
        if r.get("status") == "verified" and not (r.get("verified_by") and r.get("verified_at"))
    ]
    assert not bad, f"검수자 기록 없이 verified 로 승격된 룰: {bad}"
