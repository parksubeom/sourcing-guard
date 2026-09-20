"""정부 API 조회가 실패했을 때 verifier 가 무엇을 말하는가.

"조회했는데 없음" 과 "조회를 못 함" 은 셀러에게 완전히 다른 정보다. 후자를
전자로 표시하면 우리가 확인하지 못한 것을 확인한 것처럼 말하는 게 된다.
"""

import pytest

from sourcing_guard.kats_client import CertLookup, KatsApiError, health
from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts, Signal
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify


class FailingClient:
    """인증 조회가 실패하는 클라이언트. 캐시도 비어 있는 상황이다."""

    def __init__(self, code: str = "5000") -> None:
        self.code = code

    def lookup_certification_cached(self, kc_number):
        raise KatsApiError(self.code, "테스트 실패")


class CertOnlyClient(FailingClient):
    """인증 조회는 되는 클라이언트. 리콜은 로컬 인덱스가 담당한다."""

    def lookup_certification_cached(self, kc_number):
        return CertLookup(record=None, fetched_at="2026-09-01T00:00:00+00:00")


class EmptyRecallIndex:
    """로컬 사본이 아직 없는 상태 (초기 적재 전)."""

    as_of = None

    def is_empty(self):
        return True

    def find(self, facts, *, today, min_strength=None):
        return []


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
    findings = verify(FACTS, FailingClient(), RuleBook(), EmptyRecallIndex())
    kinds = {f.kind for f in findings}
    assert FindingKind.LOOKUP_FAILED in kinds


def test_failed_lookup_never_becomes_kc_not_found():
    """조회를 못 한 것을 '조회했는데 없다' 로 표시하면 안 된다.

    KC_NOT_FOUND 는 AMBER 를 달고 나가는데, 그건 정부 DB 를 실제로 확인했다는
    뜻이다. 확인하지 못했으면서 확인한 것처럼 말하게 된다.
    """
    findings = verify(FACTS, FailingClient(), RuleBook(), EmptyRecallIndex())
    kinds = {f.kind for f in findings}
    assert FindingKind.KC_NOT_FOUND not in kinds
    assert FindingKind.KC_VERIFIED not in kinds


def test_failed_recall_lookup_never_claims_recall_clear():
    """'일치 항목을 찾지 못했다' 는 조회에 성공했을 때만 할 수 있는 말이다."""
    findings = verify(FACTS, CertOnlyClient(), RuleBook(), EmptyRecallIndex())
    kinds = {f.kind for f in findings}
    assert FindingKind.RECALL_CLEAR not in kinds
    assert FindingKind.LOOKUP_FAILED in kinds


def test_lookup_failure_yields_unknown_signal():
    findings = verify(FACTS, FailingClient(), RuleBook(), EmptyRecallIndex())
    result = score(FACTS, findings)
    assert result.signal is Signal.UNKNOWN
    assert result.score == 0


def test_wording_splits_our_fault_from_someone_elses():
    """우리 설정 문제와 남의 장애는 **다른 말**이어야 한다.

    ⚠⚠ 2026-09-20 에 갈리는 **방향이 바뀌었다** (P2). 전에는

        우리 잘못  "다시 시도" 를 안 한다
        남의 장애  "잠시 후 다시 시도해 주세요"

    였는데 남의 장애 쪽이 **원인 단정**이었다. 우리는 그것이 잠시인지 모른다 -
    P1 이 `network.connect` 까지 좁혔지만 도쿄만인지 국외 전반인지는 안 쟀고,
    9/18 에 스스로 풀린 기록도 있다. 지금은 이렇게 갈린다:

        우리 잘못  "조회 서비스 설정을 점검하고 있습니다"   아는 것은 말한다
        남의 장애  아무 원인도 안 말한다                  모르는 것은 안 말한다

    문구 전체의 소유자는 `tests/test_lookup_honesty.py` 다 - 여기서는
    **갈린다는 것**만 본다 (§6).
    """
    ours = verify(FACTS, FailingClient("4001"), RuleBook(), EmptyRecallIndex())
    ours_text = next(f.statement_ko for f in ours if f.kind is FindingKind.LOOKUP_FAILED)
    assert "설정을 점검하고 있습니다" in ours_text
    assert "다시 시도" not in ours_text

    health.record_success()
    theirs = verify(FACTS, FailingClient("5000"), RuleBook(), EmptyRecallIndex())
    theirs_text = next(f.statement_ko for f in theirs if f.kind is FindingKind.LOOKUP_FAILED)
    assert "설정을 점검" not in theirs_text, "남의 장애를 우리 설정 문제로 말한다"
    assert "일시적" not in theirs_text and "잠시 후" not in theirs_text, "원인을 단정한다"
    # 반대 방향 - 갈라 놓고 둘 다 빈 말이 되면 안 된다.
    for text in (ours_text, theirs_text):
        assert "연결하지 못했습니다" in text and "직접 조회하실 수 있습니다" in text


def test_every_lookup_failure_finding_carries_a_source():
    """근거 없는 출력은 존재할 수 없다 (CLAUDE.md R2)."""
    findings = verify(FACTS, FailingClient(), RuleBook(), EmptyRecallIndex())
    for f in findings:
        assert f.source_url and f.source_label
