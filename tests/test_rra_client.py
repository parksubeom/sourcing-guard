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
