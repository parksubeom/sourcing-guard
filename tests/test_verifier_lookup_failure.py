"""정부 API 조회가 실패했을 때 verifier 가 무엇을 말하는가.

"조회했는데 없음" 과 "조회를 못 함" 은 셀러에게 완전히 다른 정보다. 후자를
전자로 표시하면 우리가 확인하지 못한 것을 확인한 것처럼 말하는 게 된다.
"""

import pytest

from sourcing_guard.kats_client import KatsApiError, health
from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts, Signal
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify


class FailingClient:
    """모든 조회가 실패하는 클라이언트."""

    def __init__(self, code: str = "5000") -> None:
        self.code = code

    def lookup_certification(self, kc_number):
        raise KatsApiError(self.code, "테스트 실패")

    def search_recalls(self, **kwargs):
        raise KatsApiError(self.code, "테스트 실패")


class RecallOnlyFailingClient(FailingClient):
    """인증 조회는 되는데 리콜 조회만 실패하는 경우."""

    def lookup_certification(self, kc_number):
        return None


@pytest.fixture(autouse=True)
def _reset_health():
    yield
    health.record_success()
    health.last_error_code = None
    health.last_error_at = None


FACTS = ProductFacts(
    product_name="유아용 블록",
    model_name="BLK-100",
    kc_numbers=["CB061R2170-3018"],
    category=ItemCategory.CHILDREN_TOY,
)


def test_lookup_failure_produces_a_finding_not_silence():
    findings = verify(FACTS, FailingClient(), RuleBook())
    kinds = {f.kind for f in findings}
    assert FindingKind.LOOKUP_FAILED in kinds


def test_failed_lookup_never_becomes_kc_not_found():
    """조회를 못 한 것을 '조회했는데 없다' 로 표시하면 안 된다.

    KC_NOT_FOUND 는 AMBER 를 달고 나가는데, 그건 정부 DB 를 실제로 확인했다는
    뜻이다. 확인하지 못했으면서 확인한 것처럼 말하게 된다.
    """
    findings = verify(FACTS, FailingClient(), RuleBook())
    kinds = {f.kind for f in findings}
    assert FindingKind.KC_NOT_FOUND not in kinds
    assert FindingKind.KC_VERIFIED not in kinds


def test_failed_recall_lookup_never_claims_recall_clear():
    """'일치 항목을 찾지 못했다' 는 조회에 성공했을 때만 할 수 있는 말이다."""
    findings = verify(FACTS, RecallOnlyFailingClient(), RuleBook())
    kinds = {f.kind for f in findings}
    assert FindingKind.RECALL_CLEAR not in kinds
    assert FindingKind.LOOKUP_FAILED in kinds


def test_lookup_failure_yields_unknown_signal():
    findings = verify(FACTS, FailingClient(), RuleBook())
    result = score(FACTS, findings)
    assert result.signal is Signal.UNKNOWN
    assert result.score == 0


def test_wording_splits_our_fault_from_a_transient_outage():
    """키 무효·IP 미등록에 '다시 시도해 주세요' 는 거짓말이다.

    우리가 고치기 전엔 계속 실패한다. 그건 로그로 올리고 화면엔 확인이
    완료되지 않았다는 사실만 말한다.
    """
    ours = verify(FACTS, FailingClient("4001"), RuleBook())
    ours_text = next(f.statement_ko for f in ours if f.kind is FindingKind.LOOKUP_FAILED)
    assert "다시 시도" not in ours_text

    health.record_success()
    theirs = verify(FACTS, FailingClient("5000"), RuleBook())
    theirs_text = next(f.statement_ko for f in theirs if f.kind is FindingKind.LOOKUP_FAILED)
    assert "다시 시도해 주세요" in theirs_text


def test_every_lookup_failure_finding_carries_a_source():
    """근거 없는 출력은 존재할 수 없다 (CLAUDE.md R2)."""
    findings = verify(FACTS, FailingClient(), RuleBook())
    for f in findings:
        assert f.source_url and f.source_label
