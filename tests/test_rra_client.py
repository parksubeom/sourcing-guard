"""전파인증(적합성평가) 조회 어댑터 테스트.

네트워크를 타지 않는다 (conftest 가 목 모드를 강제). 실측으로 확인된 함정
셋이 코드에 반영돼 있는지를 고정한다:
  1. 인코딩 이원화 - 검색 목록 EUC-KR / 팝업 UTF-8
  2. 한글 질의는 EUC-KR 퍼센트 인코딩 (UTF-8 이면 에러가 아니라 0건)
  3. 파생모델은 콤마가 아니라 공백 구분
"""

import pytest

from sourcing_guard.rra_client import (
    RfCertState,
    RraClient,
    _euc_kr_query,
    extract_rf_numbers,
    is_rf_number,
    rf_evidence_url,
    split_derived_models,
)


@pytest.mark.parametrize(
    "number,valid",
    [
        ("R-C-GRm-A05418", True),
        ("R-R-LGE-WU922M2604", True),
        ("R-I-ABC-XYZ123", True),
        ("KCC-REM-MJT-MJT", True),
        ("R-I-", False),
        ("그냥글자", False),
    ],
)
def test_rf_number_format(number, valid):
    assert is_rf_number(number) is valid


def test_kc_number_is_not_mistaken_for_rf_number():
    """전안법 KC 번호와 전파법 인증번호는 별개 제도다. 섞이면 엉뚱한 곳에 조회한다."""
    assert not is_rf_number("CB061R2170-3018")
    assert extract_rf_numbers("KC인증 CB061R2170-3018 / 전파인증 R-C-GRm-A05418") == [
        "R-C-GRm-A05418"
    ]


def test_format_check_guards_the_0001_ambiguity():
    """emsit 의 0001 은 '번호가 없다' 와 '번호가 아니다' 를 구분하지 못한다."""
    client = RraClient(mock=True)
    assert client.lookup_number("아무말") is None
    assert client.lookup_number("CB061R2170-3018") is None


def test_derived_models_are_space_separated():
    """실측 36건에서 콤마·슬래시·세미콜론은 0건, 전부 공백이었다."""
    assert split_derived_models("WU922MC WU922MN WU922MW WU922MB") == [
        "WU922MC", "WU922MN", "WU922MW", "WU922MB",
    ]


def test_derived_models_missing_tag_is_not_an_error():
    """파생모델이 없으면 태그가 통째로 빠진다(빈 태그가 아님)."""
    assert split_derived_models(None) == []
    assert split_derived_models("") == []


def test_derived_models_drop_one_char_fragments():
    """짧은 조각은 우연 충돌이 심하다 (watchlist 식별력 규칙과 같은 취지)."""
    assert "A" not in split_derived_models("A WU922MC")


def test_korean_query_is_euc_kr_encoded():
    """폼이 accept-charset=euc-kr 이다. UTF-8 로 보내면 에러가 아니라 0건이 온다.

    firm=삼성전자 실측: UTF-8 0건 / EUC-KR 10건.
    """
    query = _euc_kr_query({"firm": "삼성전자"})
    assert query == "firm=%BB%EF%BC%BA%C0%FC%C0%DA"
    assert "%EC%82%BC" not in query


def test_ascii_query_is_unchanged():
    assert _euc_kr_query({"model_no": "A05418", "category": "C"}) == (
        "model_no=A05418&category=C"
    )


def test_search_and_popup_declare_different_encodings():
    """검색 목록은 EUC-KR, 팝업은 UTF-8 이다. 한 클라이언트 안에서 갈라야 한다."""
    from sourcing_guard.rra_client import _PUBLIC

    assert _PUBLIC["encoding"] == "euc-kr"
    assert _PUBLIC["operations"]["detail_popup"]["encoding"] == "utf-8"


def test_mock_lookup_returns_full_record():
    record = RraClient(mock=True).lookup_number("KCC-REM-MJT-MJT")
    assert record is not None
    assert record.state is RfCertState.VERIFIED
    assert record.equipment == "SSD"
    # 기본 + 파생이 모두 매칭 후보가 된다 - 셀러 상품이 파생모델일 수 있다.
    assert "MITS3016GN1-S" in record.all_models
    assert "MITS3002GN1-S" in record.all_models


def test_evidence_url_is_the_public_search_page():
    """근거 링크(R2)는 인증키가 필요 없는 공개 페이지여야 한다."""
    url = rf_evidence_url()
    assert url.startswith("https://www.rra.go.kr")
    assert "A_c_search" in url


def test_referer_header_is_always_sent():
    """RRA 공개 검색의 게이트는 Referer 헤더의 존재 하나다 (실측)."""
    client = RraClient(mock=True)
    assert client._client.headers.get("Referer", "").startswith("https://www.rra.go.kr")


# --- verifier 배선 ---------------------------------------------------------
def _run(text: str):
    from sourcing_guard.extractor import extract
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.scorer import score
    from sourcing_guard.verifier import RuleBook, verify

    facts = extract(text)
    findings = verify(facts, KatsClient(None, None, mock=True), RuleBook(), None,
                      RraClient(mock=True))
    return facts, findings, score(facts, findings)


def test_wireless_without_number_asks_for_confirmation():
    """무선 표기만 있고 번호가 없는 것이 구매대행 상품의 가장 흔한 경우다."""
    from sourcing_guard.models import FindingKind

    facts, findings, _ = _run("블루투스 무선 이어폰\n제조사: 하마하마무역")
    assert facts.wireless_hints
    kinds = {f.kind for f in findings}
    assert FindingKind.RF_WIRELESS_UNVERIFIED in kinds


def test_wireless_finding_states_a_fact_not_a_verdict():
    """'무선 표기가 있다' 는 사실이고 '전파인증 대상이다' 는 판정이다 (R1).

    대상 여부는 고시 별표 1 이 정하며 우리가 판별하지 않는다.
    """
    from sourcing_guard.models import FindingKind

    _, findings, _ = _run("블루투스 무선 이어폰")
    rf = next(f for f in findings if f.kind is FindingKind.RF_WIRELESS_UNVERIFIED)
    assert "무선 기능 표기" in rf.statement_ko
    assert "대상입니다" not in rf.statement_ko


def test_rf_number_is_looked_up():
    from sourcing_guard.models import FindingKind

    facts, findings, _ = _run("무선 기기\n전파인증: KCC-REM-MJT-MJT\n블루투스")
    assert facts.rf_numbers == ["KCC-REM-MJT-MJT"]
    rf = next(f for f in findings if f.kind is FindingKind.RF_CERT_VERIFIED)
    assert "SSD" in rf.statement_ko          # 기자재명칭이 화면에 나온다
    assert "rra.go.kr" in rf.source_url      # 근거 링크(R2)


def test_non_wireless_product_gets_no_rf_finding():
    """무선이 아닌 상품에 전파인증을 요구하면 오탐이다."""
    _, findings, _ = _run("어린이 블록 완구\n재질: ABS\n대상연령: 3세 이상")
    assert not [f for f in findings if f.kind.value.startswith("rf_")]


def test_rf_not_found_is_amber_not_red():
    """미조회를 RED 로 두면 자기적합확인 대상에 오탐이 난다 (R3-b).

    전안법 SCoC 에서 겪은 것과 같은 구조다.
    """
    from sourcing_guard.models import FindingKind, Signal
    from sourcing_guard.scorer import _HARD_RED

    assert FindingKind.RF_CERT_NOT_FOUND not in _HARD_RED
    assert FindingKind.RF_WIRELESS_UNVERIFIED not in _HARD_RED

    _, findings, _ = _run("무선 기기\n전파인증: R-C-ZZZ-NOTREAL999\n블루투스")
    rf = next(f for f in findings if f.kind is FindingKind.RF_CERT_NOT_FOUND)
    assert rf.signal is Signal.AMBER
    assert "자기적합확인" in rf.statement_ko


# --- 모델명 검색 배선 -------------------------------------------------------
#
# 번호가 없는 구매대행 상품이 대부분이라 이 경로가 전파인증 축의 주력이다.
# emsit 은 mtlCefNo 만 받으므로 여기서는 쓸 수 없다.


@pytest.mark.parametrize("model,ok", [
    # 실측(2026-09-02) 총 페이지 수를 근거로 갈랐다.
    ("100", False),        # 숫자만 3자 - 6,491페이지
    ("1000", False),       # 숫자만 4자 - 1,747페이지
    ("A1", False),         # 2자 - 1,579페이지
    ("AB", False),         # 2자 - 906페이지
    ("ABC", False),        # 3자 - 41페이지
    ("M-1000", False),     # 길이 5인데 글자가 하나 - 66페이지
    ("GP-500", True),      # 길이 5 + 글자 2 - 3페이지
    ("TS183", True),
    ("A05418", True),      # 글자 하나여도 길이 6이면 괜찮다 - 1페이지
    ("SM-R900", True),
    ("WU922MS", True),
    ("", False),
    (None, False),
])
def test_search_gate_matches_the_measured_blowup(model, ok):
    """식별력 없는 질의는 아예 던지지 않는다.

    목록이 부분문자열 매칭이라 '100' 은 6,491페이지를 문다. watchlist 의
    강등(④)과 달리 여기는 중간 단계가 없어 질의 자체를 막아야 한다.
    """
    from sourcing_guard.rra_client import is_searchable_model

    assert is_searchable_model(model) is ok


def test_models_match_uses_base_and_derived():
    """셀러가 적은 것이 파생모델일 수 있다 (실측: WU922MS 의 파생 4종)."""
    from sourcing_guard.rra_client import RfCertRecord, models_match

    rec = RfCertRecord(cert_number="R-R-LGE-WU922M2604", base_model="WU922MS",
                       derived_models=("WU922MC", "WU922MN"))
    assert models_match("WU922MS", rec)
    assert models_match("wu922mc", rec)      # 파생 + 대소문자 무시
    assert models_match("WU-922-MN", rec)    # 하이픈 무시
    assert not models_match("WU922MX", rec)
    assert not models_match("", rec)


def test_models_match_is_exact_not_containment():
    """포함 매칭을 쓰면 남의 인증을 이 상품 것으로 말하게 된다.

    '인증이 있다' 는 안심시키는 방향이라 가장 비싼 오류다. 정확 일치에서
    빠지면 미조회(AMBER)로 가는데 그건 확인을 권하는 안전한 실패다.
    """
    from sourcing_guard.rra_client import RfCertRecord, models_match

    rec = RfCertRecord(cert_number="R-C-X-ABC1000", base_model="ABC1000")
    assert not models_match("ABC100", rec)
    assert not models_match("ABC10001", rec)


def test_search_sends_empty_category_not_C():
    """category=C 로 고정하면 적합등록(R-R-)을 통째로 놓친다.

    실측: category=C&model_no=WU922MS -> 0건, category=&model_no=WU922MS -> 1건.
    소비자 무선기기 주류가 적합등록이라 주력 경로가 조용히 0건이 된다.
    """
    import inspect

    from sourcing_guard import rra_client

    src = inspect.getsource(rra_client.RraClient.search_by_model)
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert '"category": ""' in body
    assert '"category": "C"' not in body


def test_model_cache_avoids_repeat_requests():
    """검색 한 번이 12초다. 캐시가 없으면 같은 상품마다 RRA 를 그만큼 두드린다."""
    from sourcing_guard.rra_client import ModelSearchCache, RfCertRecord

    cache = ModelSearchCache()
    assert cache.get("WU922MS") is None
    cache.put("WU922MS", [RfCertRecord(cert_number="R-R-X-Y")], "2026-09-02")
    hit = cache.get("WU922MS")
    assert hit is not None and len(hit[1]) == 1


def test_expired_cache_entry_is_a_miss():
    from sourcing_guard.rra_client import ModelSearchCache

    # ttl=0 은 경계라 통과한다(`>` 비교). 만료를 확실히 재려면 음수를 준다 -
    # CertCache 와 같은 비교식이다.
    cache = ModelSearchCache(ttl_seconds=-1)
    cache.put("X", [], "2026-09-02")
    assert cache.get("X") is None


def test_popup_parses_number_and_derived_models():
    """목록에 인증번호가 없어 팝업이 유일한 출처다. 파생모델도 여기서 온다."""
    from sourcing_guard.rra_client import _parse_popup

    html = """<table>
      <tr><th>상호</th><td>엘지전자(주)</td></tr>
      <tr><th>기기명칭</th><td>전기냉수기</td></tr>
      <tr><th>모델명</th><td>WU922MS</td></tr>
      <tr><th>파생모델명</th><td>WU922MC WU922MN</td></tr>
      <tr><th>인증번호</th><td>R-R-LGE-WU922M2604</td></tr>
      <tr><th>제조국가</th><td>대한민국</td></tr>
    </table>"""
    rec = _parse_popup(html)
    assert rec is not None
    assert rec.cert_number == "R-R-LGE-WU922M2604"
    assert rec.base_model == "WU922MS"
    assert rec.derived_models == ("WU922MC", "WU922MN")
    assert "WU922MN" in rec.all_models


def _rf_run(text: str, rra=None):
    from sourcing_guard.extractor import extract
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.verifier import RuleBook, verify

    facts = extract(text)
    return facts, verify(facts, KatsClient(None, None, mock=True), RuleBook(), None,
                         rra if rra is not None else RraClient(mock=True))


def test_model_search_reports_how_it_matched():
    """번호로 찾았는지 모델명으로 찾았는지를 문장에 적는다.

    모델명 검색은 부분일치 목록을 재대조한 결과라, 셀러가 어느 축으로 걸렸는지
    알아야 스스로 가릴 수 있다 (리콜에서 matched_on 을 실은 것과 같은 이유).
    """
    from sourcing_guard.models import FindingKind

    _, findings = _rf_run("블루투스 무선 기기\n모델명: A05418")
    rf = next(f for f in findings if f.kind is FindingKind.RF_CERT_VERIFIED)
    assert rf.detail["matched_on"] == "model"
    assert "모델명으로 조회" in rf.statement_ko


def test_derived_model_is_found_by_search():
    """셀러가 적은 것이 파생모델이어도 잡아야 한다."""
    from sourcing_guard.models import FindingKind

    _, findings = _rf_run("무선 기기 블루투스\n모델명: MITS3002GN1-S")
    assert any(f.kind is FindingKind.RF_CERT_VERIFIED for f in findings)


def test_searched_but_not_found_is_amber():
    """0건이면 미조회(AMBER)다 - 자기적합확인 여지가 있어 RED 가 아니다 (R3-b)."""
    from sourcing_guard.models import FindingKind, Signal

    _, findings = _rf_run("블루투스 무선 스피커\n모델명: ZZZ9999X")
    rf = next(f for f in findings if f.kind is FindingKind.RF_CERT_NOT_FOUND)
    assert rf.signal is Signal.AMBER
    assert "자기적합확인" in rf.statement_ko


def test_unsearchable_model_falls_back_to_the_advisory():
    """식별력이 없으면 질의를 던지지 않고 안내로 남는다."""
    from sourcing_guard.models import FindingKind

    _, findings = _rf_run("블루투스 이어폰\n모델명: A1")
    kinds = {f.kind for f in findings}
    assert FindingKind.RF_WIRELESS_UNVERIFIED in kinds
    assert FindingKind.RF_CERT_NOT_FOUND not in kinds


def test_search_failure_is_lookup_failed_not_no_cert():
    """못 연 것과 없는 것은 다르다 (R3). 조용히 '인증 없음' 으로 흘리면 안 된다."""
    from sourcing_guard.models import FindingKind
    from sourcing_guard.rra_client import RraApiError

    class Failing(RraClient):
        def search_certs_by_model(self, model):
            raise RraApiError("network", "ReadTimeout")

    _, findings = _rf_run("블루투스 무선 기기\n모델명: A05418", rra=Failing(mock=True))
    kinds = {f.kind for f in findings}
    assert FindingKind.LOOKUP_FAILED in kinds
    assert FindingKind.RF_CERT_NOT_FOUND not in kinds


def test_number_takes_priority_over_model_search():
    """번호가 있으면 emsit 이 우선이다 - 구조화 응답이고 resultCode 가 명확하다."""
    from sourcing_guard.models import FindingKind

    _, findings = _rf_run("무선 기기\n전파인증: KCC-REM-MJT-MJT\n모델명: A05418\n블루투스")
    verified = [f for f in findings if f.kind is FindingKind.RF_CERT_VERIFIED]
    assert len(verified) == 1
    assert verified[0].detail["matched_on"] == "number"
