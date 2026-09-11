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

from sourcing_guard.recall_index import RecallIndex
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
    # ⚠ 대조 가능 여부는 **진짜 로직을 빌린다** (4-r). 여기서 따로 적으면
    #   조건이 또 갈리고, 그 갈림이 이 결함의 원인이었다.
    can_compare = RecallIndex.can_compare

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
def test_model_name_only_match_across_different_items_is_amber_not_red(strength):
    """**"펜을 검사했는데 왜 블라인드가 뜨나" 가 바로 이 경우다** (4-d-2).

    우리 상품은 모나미 153 볼펜(모나미)이고 리콜은 LED 전등(Greenline)이다.
    맞은 것은 모델명 '153' 하나뿐이고 제조사도 품목도 다르다.

    ⚠ 2026-09-08 까지 이 자리가 RED 를 요구했다. 실측(A-5 · 대상 109건)에서
      RED 5건 중 3건이 이런 우연 충돌이었다 - '레인보우'↔승차용 안전모,
      '진공 청소기'↔전지, 'hope'↔전기자전거. R3-b 가 금지한 "항상 켜지는
      경고" 이고, 빨간불이 반복되면 셀러가 진짜 인증취소도 안 보게 된다.

    ⚠ **버리지는 않는다.** finding 은 그대로 나오고 문구도 R6 대로 "유사 일치
      … 원문 확인이 필요합니다" 다. 바뀌는 것은 **색**이다.
    """
    findings, result = run(PEN, [(rec(), Match(strength, "model_name"))])

    # ⚠ **경계가 여기 있다.** verifier 는 근거를 모으고 RED 로 만든다. 색을
    #   내리는 것은 scorer 다(R1: 판정은 scorer). 그래서 화면이 읽는 것은
    #   `result.findings` 이고, `verify()` 원본은 내려가지 않는다.
    raw = next(x for x in findings if x.kind is FindingKind.RECALL_MATCH)
    assert raw.signal is Signal.RED, "verifier 는 근거 수집만 한다"

    f = next(x for x in result.findings if x.kind is FindingKind.RECALL_MATCH)
    assert f.signal is Signal.AMBER
    assert f.group is FindingGroup.FINDING, "구획은 그대로 - 참고로 밀지 않는다"
    assert "원문 확인이 필요합니다" in f.statement_ko
    assert result.signal is not Signal.RED


@pytest.mark.parametrize("strength", [MatchStrength.EXACT, MatchStrength.STRONG])
def test_certificate_number_match_is_still_red(strength):
    """인증번호가 같은 것은 추정이 아니다."""
    facts = PEN.model_copy(update={"kc_numbers": ["CB067R317-5002"]})
    _findings, result = run(facts, [(rec(), Match(strength, "kc_number"))])
    f = next(x for x in result.findings if x.kind is FindingKind.RECALL_MATCH)

    assert f.signal is Signal.RED
    assert result.signal is Signal.RED


@pytest.mark.parametrize("strength", [MatchStrength.EXACT, MatchStrength.STRONG])
def test_model_name_match_with_the_same_maker_is_red(strength):
    """모델명 + 제조사가 함께 맞으면 우연으로 보기 어렵다."""
    _findings, result = run(
        PEN, [(rec(maker="모나미"), Match(strength, "model_name"))]
    )
    f = next(x for x in result.findings if x.kind is FindingKind.RECALL_MATCH)

    assert f.signal is Signal.RED
    assert result.signal is Signal.RED


@pytest.mark.parametrize("strength", [MatchStrength.EXACT, MatchStrength.STRONG])
def test_model_name_match_with_the_same_item_is_red(strength):
    """모델명 + 품목이 함께 맞으면 우연으로 보기 어렵다.

    리콜 쪽 제품명이 우리가 본 품목을 담고 있으면 같은 물건일 개연이 크다.
    """
    _findings, result = run(
        PEN.model_copy(update={"legal_item_name": "볼펜"}),
        [(rec(product_name="볼펜"), Match(strength, "model_name"))],
    )
    f = next(x for x in result.findings if x.kind is FindingKind.RECALL_MATCH)

    assert f.signal is Signal.RED
    assert result.signal is Signal.RED


def test_the_watchlist_sweep_is_not_touched_by_the_scan_gate():
    """⚠ R6: 알림에서는 **놓친 쪽이 더 비싸다.** 두 경로의 오류 비대칭이 반대다.

    `watchlist.sweep()` 은 `verify()`·`score()` 를 거치지 않는 별개 경로이고
    자기 `MatchStrength` 로 판단한다. 스캔 게이트가 거기 닿지 않는 것이
    의도다 - 두 곳을 한 규칙으로 묶으려는 다음 사람은 R6 을 먼저 읽을 것.
    """
    import inspect

    from sourcing_guard import watchlist

    src = inspect.getsource(watchlist.sweep)
    assert "recall_match_earns_red" not in src
    assert "score(" not in src and "verify(" not in src
    # sweep 은 약한 일치도 기본으로 알린다.
    assert "min_strength: MatchStrength = MatchStrength.WEAK" in inspect.getsource(
        watchlist.sweep
    )


def test_weak_match_is_context_not_a_confirmed_problem():
    """제조사와 제품명 단어만 겹친 것은 '이 상품이 리콜됨' 이 아니다.

    RED 로 두면 무관한 상품에 빨간불이 반복되고, 셀러가 모든 RED 를 무시하게
    된다 - SCoC 오탐(48e7787) 때 세운 논리 그대로다.
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


# ---------------------------------------------------------------------------
# 4-가. 모델명 칸에 품목명이 들어온 경우는 모델명 축을 쓰지 않는다
# ---------------------------------------------------------------------------
def test_a_model_name_that_is_an_item_name_does_not_earn_red():
    """실측 [48] 차량용 핸디 청소기 · `model_name='진공 청소기'`.

    그것으로 리콜 모델명을 대조하면 같은 품목의 아무 리콜에나 걸린다. 실제로
    4건에 걸렸고 그중 셋은 리콜 품목이 `전지(충전지만 해당)` 였다. 4번째는
    리콜 품목이 `진공청소기` 여서 품목 일치를 통과해 RED 가 됐다 - **모델명이
    품목명이므로 그 일치는 정보가 아니다.**

    ⚠ 목록은 등급표(정부 표)의 품목명과 표 자체의 별칭이다. "무엇이 일반명사
      인가" 를 우리가 정하지 않는다 (R1).
    """
    facts = ProductFacts(
        product_name="차량용 무선 휴대용 핸디 청소기 에어건 2in1",
        model_name="진공 청소기",
        legal_item_name="진공청소기",
        category=ItemCategory.ELECTRICAL,
    )
    _findings, result = run(
        facts, [(rec(product_name="진공청소기", model_name="진공 청소기"),
                 Match(MatchStrength.EXACT, "model_name"))]
    )
    f = next(x for x in result.findings if x.kind is FindingKind.RECALL_MATCH)

    assert f.detail["matched_value_names_an_item"] is True
    assert f.signal is Signal.AMBER
    assert result.signal is not Signal.RED
    # 버리지 않는다 - 줄과 문구는 그대로다 (R6).
    assert "원문 확인이 필요합니다" in f.statement_ko


def test_a_real_model_name_with_the_same_item_still_earns_red():
    """게이트가 좁다는 것을 잠근다. 진짜 모델명이면 품목 일치로 RED 다."""
    facts = ProductFacts(
        product_name="테팔 블랙필 무선주전자 KO2998",
        model_name="KO2998",
        legal_item_name="전기주전자",
        category=ItemCategory.ELECTRICAL,
    )
    _findings, result = run(
        facts, [(rec(product_name="전기주전자", model_name="KO2998"),
                 Match(MatchStrength.EXACT, "model_name"))]
    )
    f = next(x for x in result.findings if x.kind is FindingKind.RECALL_MATCH)

    assert f.detail["matched_value_names_an_item"] is False
    assert f.signal is Signal.RED
    assert result.signal is Signal.RED


def test_the_item_name_list_comes_from_the_government_table_not_from_us():
    """우리가 손으로 만든 ALIASES 는 이 목록에 넣지 않는다.

    넣으면 "무엇이 일반명사인가" 를 우리가 정하는 것이 되어 R1 논거가 무너진다.
    """
    from sourcing_guard.item_grades import ALIASES, ItemGradeBook

    book = ItemGradeBook()
    # 표에 있는 이름
    assert book.names_an_item("진공 청소기")
    assert book.names_an_item("스팀청소기")
    # 모델명처럼 생긴 것
    assert not book.names_an_item("KO2998")
    assert not book.names_an_item("레인보우")
    assert not book.names_an_item("153")
    assert not book.names_an_item("")

    # 우리 사전에만 있고 표에는 없는 키는 걸리지 않아야 한다.
    ours_only = [k for k in ALIASES if not book.names_an_item(k)]
    assert ours_only, "ALIASES 가 전부 표에 있으면 이 검사가 무의미하다"
