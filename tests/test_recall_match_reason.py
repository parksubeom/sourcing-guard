"""리콜 일치의 '왜' 를 결과에 싣는다 — 강도별 구획 분리와 근거 링크.

셀러가 실제로 한 질문이 "펜을 검사했는데 왜 블라인드가 뜨나" 였다. 원인은
두 가지였고 둘 다 문장이 답해주지 않았다:

  ① 무엇으로 맞았는지 안 보였다 ("리콜 목록과 일치합니다" 한 줄)
  ② 확정 일치와 유사 일치가 같은 목록·같은 색으로 섞여 있었다

그래서 (1) 무엇이 어느 강도로 무엇과 맞았는지를 문장과 detail 에 싣고,
(2) 약한 일치는 '확인된 문제' 가 아니라 '참고' 구획으로 보낸다. 버리지는
않는다 - 놓친 알림이 이 서비스가 하는 유일한 약속을 깨뜨린다 (R6).
"""

from datetime import date

import pytest

from sourcing_guard.kats_client import (
    RECALL_BOARD_URL,
    KatsClient,
    RecallRecord,
    is_usable_recall_url,
    recall_evidence,
)
from sourcing_guard.models import (
    FindingGroup,
    FindingKind,
    ItemCategory,
    MatchStrength,
    ProductFacts,
    Signal,
)
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify
from sourcing_guard.watchlist import Match

TODAY = date(2026, 9, 1)


class FakeIndex:
    """RecallIndex 대역. find() 가 돌려줄 (레코드, 강도) 를 직접 지정한다."""

    def __init__(self, hits=(), records=()):
        self._hits = list(hits)
        self._records = list(records)
        self.as_of = "20260828"

    def is_empty(self):
        return False

    def all_records(self):
        return self._records

    def find(self, facts, *, today, **kw):
        return self._hits

    def by_maker_exact(self, maker, *, exclude_uids=None):
        return []


def rec(**kw):
    base = dict(
        product_name="LED 전등", model_name="153", maker="Greenline",
        reason="감전 위험", announced_on="20141226",
        detail_url="https://ec.europa.eu/safety-gate-alerts/alertDetail/1009",
        scope="overseas", uid="u1",
    )
    base.update(kw)
    return RecallRecord(**base)


def run(facts, hits):
    findings = verify(facts, KatsClient(None, None, mock=True), RuleBook(), FakeIndex(hits))
    return findings, score(facts, findings, recall_data_as_of="20260828")


PEN = ProductFacts(
    product_name="모나미 153 볼펜 흑색 12개입", model_name="153", maker="모나미",
    category=ItemCategory.CHILDREN_STATIONERY,
)


# ---------------------------------------------------------------------------
# 무엇으로 맞았는가를 문장에 싣는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strength", [MatchStrength.EXACT, MatchStrength.STRONG])
def test_statement_names_what_matched_and_what_was_recalled(strength):
    """우리 쪽 값 · 강도 · 리콜된 제품이 한 문장에 있어야 한다."""
    findings, _ = run(PEN, [(rec(), Match(strength, "model_name"))])
    f = next(x for x in findings if x.kind is FindingKind.RECALL_MATCH)

    assert "모델명" in f.statement_ko
    assert "'153'" in f.statement_ko          # 우리 쪽에서 맞은 값
    assert "LED 전등" in f.statement_ko       # 리콜된 제품 — "펜인데 왜?" 의 답
    assert strength.label_ko in f.statement_ko


def test_detail_carries_strength_and_matched_on():
    """프론트가 구획을 가르는 근거이자, 나중에 오탐을 추적할 자료다."""
    findings, _ = run(PEN, [(rec(), Match(MatchStrength.EXACT, "model_name"))])
    d = next(x for x in findings if x.kind is FindingKind.RECALL_MATCH).detail

    assert d["match_strength"] == "exact"
    assert d["matched_on"] == "model_name"
    assert d["matched_on_ko"] == "모델명"
    assert d["matched_value"] == "153"
    assert d["recalled_product_name"] == "LED 전등"


def test_long_recall_model_lists_are_truncated():
    """리콜 모델명 칸에는 수십 개가 콤마로 묶여 온다. 한 줄을 넘기면 안 된다."""
    huge = ", ".join(f"HRM{i}" for i in range(60))
    findings, _ = run(PEN, [(rec(model_name=huge), Match(MatchStrength.STRONG, "model_name"))])
    f = next(x for x in findings if x.kind is FindingKind.RECALL_MATCH)
    assert "…" in f.statement_ko
    assert len(f.statement_ko) < 300


# ---------------------------------------------------------------------------
# 강도로 구획을 가른다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strength", [MatchStrength.EXACT, MatchStrength.STRONG])
def test_model_and_cert_matches_are_confirmed_problems(strength):
    findings, result = run(PEN, [(rec(), Match(strength, "model_name"))])
    f = next(x for x in findings if x.kind is FindingKind.RECALL_MATCH)

    assert f.signal is Signal.RED
    assert f.group is FindingGroup.FINDING
    assert result.signal is Signal.RED


def test_weak_match_is_context_not_a_confirmed_problem():
    """제조사와 제품명 단어만 겹친 것은 '이 상품이 리콜됨' 이 아니다.

    RED 로 두면 무관한 상품에 빨간불이 반복되고, 셀러가 모든 RED 를 무시하게
    된다 - SCoC 오탐(7a6fd70) 때 세운 논리 그대로다.
    """
    findings, result = run(PEN, [(rec(), Match(MatchStrength.WEAK, "maker+product"))])

    assert not [x for x in findings if x.kind is FindingKind.RECALL_MATCH]
    f = next(x for x in findings if x.kind is FindingKind.RECALL_WEAK_MATCH)
    assert f.signal is Signal.UNKNOWN
    assert f.group is FindingGroup.CONTEXT
    assert result.signal is not Signal.RED
    # 문구가 단정하지 않는다
    assert "참고" in f.statement_ko
    assert "리콜 대상이라는 뜻은" in f.statement_ko


def test_weak_match_is_not_dropped(recwarn):
    """관대하게 잡되 조용히 버리지 않는다 (R6)."""
    findings, _ = run(PEN, [(rec(), Match(MatchStrength.WEAK, "maker+product"))])
    assert [x for x in findings if x.kind is FindingKind.RECALL_WEAK_MATCH]


def test_weak_matches_are_aggregated_into_one_row():
    """수십 줄로 내면 경고가 아니라 소음이다."""
    hits = [
        (rec(uid=f"u{i}", product_name=f"블라인드 {i}", announced_on=f"2026080{i}"),
         Match(MatchStrength.WEAK, "maker+product"))
        for i in range(1, 6)
    ]
    findings, _ = run(PEN, hits)
    weak = [x for x in findings if x.kind is FindingKind.RECALL_WEAK_MATCH]
    assert len(weak) == 1
    assert weak[0].detail["count"] == 5
    assert "20260805" == weak[0].detail["latest_announced_on"]


def test_weak_match_alone_does_not_change_the_score():
    """점수를 깎으면 흔한 단어를 쓴 상품이 전부 노란불이 된다."""
    clean_findings, clean = run(PEN, [])
    _, weak = run(PEN, [(rec(), Match(MatchStrength.WEAK, "maker+product"))])
    assert weak.score == clean.score
    assert weak.signal is clean.signal


# ---------------------------------------------------------------------------
# 약한 일치가 있어도 "모델명·인증번호 일치 없음" 은 참이다
# ---------------------------------------------------------------------------


def test_recall_clear_still_reported_alongside_a_weak_match():
    """문장이 좁혀졌으므로 둘이 동시에 참일 수 있다.

    이전 문장("일치 항목을 찾지 못했습니다")을 그대로 두면 바로 아래 참고
    항목과 앞뒤가 맞지 않는다.
    """
    findings, _ = run(PEN, [(rec(), Match(MatchStrength.WEAK, "maker+product"))])
    clear = next(x for x in findings if x.kind is FindingKind.RECALL_CLEAR)
    assert "모델명·인증번호가 일치하는 항목을" in clear.statement_ko


def test_confirmed_match_suppresses_recall_clear():
    findings, _ = run(PEN, [(rec(), Match(MatchStrength.EXACT, "model_name"))])
    assert not [x for x in findings if x.kind is FindingKind.RECALL_CLEAR]


# ---------------------------------------------------------------------------
# 근거 링크 — 메인페이지는 근거가 아니다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    None, "", "   ",
    "https://www.safetykorea.kr/",              # 호스트 루트
    "https://www.cpsc.gov",                     # 경로 없음
    "http://example.gov/index.html",            # 메인 문서
    "javascript:void(0)",                       # 스킴이 아니다
    "/recall/123",                              # 상대경로
])
def test_rootish_and_broken_urls_are_not_evidence(url):
    assert is_usable_recall_url(url) is False
    label, resolved = recall_evidence(url)
    assert resolved == RECALL_BOARD_URL
    assert label == "국가기술표준원 리콜정보에서 확인"


@pytest.mark.parametrize("url", [
    "https://ec.europa.eu/safety-gate-alerts/alertDetail/10091729?lang=en",
    "https://www.gov.uk/product-safety-alerts/product-recall-honda-2407",
    "https://www.meti.go.jp/product_safety/recall/file/240410-1.html",
    "https://www.safetykorea.kr/?recallUid=3802",     # 루트지만 질의가 대상을 가리킨다
])
def test_deep_links_are_kept(url):
    assert is_usable_recall_url(url) is True
    label, resolved = recall_evidence(url)
    assert resolved == url
    assert label == "리콜 공표 원문"


def test_domestic_recall_without_url_links_to_the_individual_notice():
    """국내 응답에는 상세 URL 필드가 아예 없지만 recallUid 는 전건 있다.

    이전에는 목록 화면으로 보냈다. 메인페이지보다는 낫지만, 셀러가 그 공표를
    목록에서 다시 찾아야 한다 - 국내 리콜 4,243건 전부가 그랬다.

    recallUid 로 개별 상세를 만들 수 있다. 제품안전정보센터 첫 화면이 리콜
    목록을 이 주소로 링크하고, 실측에서 표본 6/6(2026-09-01)·5/5(09-03)이
    HTTP 200 이며 본문에 해당 제품명이 들어 있었다.
    """
    findings, _ = run(
        PEN,
        [(rec(scope="domestic", detail_url=None, uid="10022642"),
          Match(MatchStrength.EXACT, "model_name"))],
    )
    f = next(x for x in findings if x.kind is FindingKind.RECALL_MATCH)
    assert "recallUid=10022642" in f.source_url
    assert f.source_label == "리콜 공표 원문"
    assert f.detail["evidence_is_original"] is True


def test_domestic_recall_without_uid_still_falls_back_to_the_board():
    """uid 마저 없으면 목록으로 보낸다. 메인페이지로는 보내지 않는다."""
    findings, _ = run(
        PEN,
        [(rec(scope="domestic", detail_url=None, uid=None),
          Match(MatchStrength.EXACT, "model_name"))],
    )
    f = next(x for x in findings if x.kind is FindingKind.RECALL_MATCH)
    assert f.source_url == RECALL_BOARD_URL
    assert f.source_label == "국가기술표준원 리콜정보에서 확인"
    assert f.detail["evidence_is_original"] is False


def test_no_finding_points_at_the_bare_main_page():
    """리콜 관련 근거 링크에서 메인페이지가 사라져야 한다."""
    findings, _ = run(PEN, [(rec(detail_url=None), Match(MatchStrength.WEAK, "maker+product"))])
    for f in findings:
        assert f.source_url.rstrip("/") != "https://www.safetykorea.kr"


def test_recall_board_url_is_configured():
    """매핑에서 읽는 값이라 키가 빠지면 빈 문자열이 되고, 그러면 Finding 생성이
    ValueError 로 죽어 스캔 전체가 500 이 된다 (R2 검증). 코드가 아니라 여기서
    막는다 - 주소는 설정에 두고(R5) 존재는 테스트로 고정한다.
    """
    assert RECALL_BOARD_URL.startswith("https://")
    assert "recall" in RECALL_BOARD_URL
