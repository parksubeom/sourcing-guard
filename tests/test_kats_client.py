"""KATS 어댑터 계약 테스트.

설계서 v2.0 대조 결과가 코드에 제대로 반영됐는지 확인한다. 네트워크는 쓰지
않는다 (CLAUDE.md §7) — httpx MockTransport 로 요청/응답을 가로챈다.
"""

import httpx
import pytest

from sourcing_guard.kats_client import (
    KatsApiError,
    KatsClient,
    normalize_kc,
)

CERT_ROW = {
    "certNum": "CB123A123-1234",
    "certState": "적합",
    "productName": "유아용섬유제품",
    "modelName": "아동배낭",
    "makerName": "아이테스트",
}

RECALL_ROW = {
    "recallProductName": "가정용섬유제품(책가방)",
    "recallModelName": "HKAK31101S-00",
    "makerName": "㈜이랜드월드패션사업부",
    "harmDscr": "제품 결함 설명",
    "publishDate": "20130418",
}


def client_with(handler) -> KatsClient:
    c = KatsClient(base_url=None, service_key="KEY123", mock=False)
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def ok(rows) -> httpx.Response:
    return httpx.Response(200, json={"resultCode": "2000", "resultMsg": "Success", "resultData": rows})


# --- 인증: 헤더와 요청 형태 ------------------------------------------------
def test_auth_key_goes_in_header_not_query():
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["url"] = str(request.url)
        return ok([CERT_ROW])

    client_with(handler).lookup_certification("CB123A123-1234")
    assert seen["headers"]["authkey"] == "KEY123"
    assert "KEY123" not in seen["url"], "인증키가 URL 에 남으면 액세스 로그에 유출된다"


def test_base_url_comes_from_field_map():
    """호스트는 설계서 고정값이라 .env 없이도 동작해야 한다."""
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return ok([CERT_ROW])

    client_with(handler).lookup_certification("CB123A123-1234")
    assert seen["url"].startswith("http://www.safetykorea.kr/openapi/api/cert/certificationList.json")


def test_certification_sends_condition_key_pair():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return ok([CERT_ROW])

    client_with(handler).lookup_certification("CB123A123-1234")
    assert seen["params"]["conditionKey"] == "certNum"
    assert seen["params"]["conditionValue"] == "CB123A123-1234"


def test_certification_parses_result_data():
    rec = client_with(lambda r: ok([CERT_ROW])).lookup_certification("CB123A123-1234")
    assert rec is not None
    assert rec.cert_number == "CB123A123-1234"
    assert rec.model_name == "아동배낭"
    assert rec.maker == "아이테스트"
    assert rec.status == "적합"


def test_detail_url_uses_spec_search_pop():
    """설계서 p.18 의 인증키 불필요 팝업 URL 이어야 근거 링크로 쓸 수 있다."""
    rec = client_with(lambda r: ok([CERT_ROW])).lookup_certification("CB123A123-1234")
    assert rec.detail_url == "http://www.safetykorea.kr/search/searchPop?certNum=CB123A123-1234"


# --- 리콜 ----------------------------------------------------------------
def test_recall_searches_by_model_when_available():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return ok([])

    client_with(handler).search_recalls(product_name="책가방", model_name="HKAK31101S-00")
    assert {s["conditionKey"] for s in seen} == {"recallModelName"}
    assert {s["conditionValue"] for s in seen} == {"HKAK31101S-00"}


def test_recall_falls_back_to_product_name():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return ok([])

    client_with(handler).search_recalls(product_name="책가방", model_name=None)
    assert {s["conditionKey"] for s in seen} == {"recallProductName"}


def test_recall_queries_domestic_and_overseas():
    seen = []

    def handler(request):
        seen.append(str(request.url.path))
        return ok([])

    client_with(handler).search_recalls(product_name=None, model_name="BLK-100")
    assert "/openapi/api/recall/recallList.json" in seen
    assert "/openapi/api/recall/fRecallList.json" in seen


def test_domestic_recall_maps_harm_dscr_as_reason():
    def handler(request):
        return ok([RECALL_ROW] if "fRecall" not in str(request.url) else [])

    out = client_with(handler).search_recalls(product_name=None, model_name="HKAK31101S-00")
    assert len(out) == 1
    assert out[0].reason == "제품 결함 설명"
    assert out[0].announced_on == "20130418"
    assert out[0].scope == "domestic"


def test_overseas_recall_maps_violate_dscr_as_reason():
    """국외는 위해내용 필드명이 다르다 (violateDscr). 국내 필드명을 쓰면 비어버린다."""
    row = {
        "recallProductName": "뮤직박스완구",
        "recallModelName": "Acrobats1",
        "makerName": "회사정보없음",
        "violateDscr": "질식 위험이 있음",
        "publishDate": "20120427",
        "recallUrl": "https://example.org/notice",
    }

    def handler(request):
        return ok([row] if "fRecall" in str(request.url) else [])

    out = client_with(handler).search_recalls(product_name=None, model_name="Acrobats1")
    assert len(out) == 1
    assert out[0].reason == "질식 위험이 있음"
    assert out[0].detail_url == "https://example.org/notice"
    assert out[0].scope == "overseas"


# --- 결과 코드 -------------------------------------------------------------
def test_no_data_is_empty_not_error():
    def handler(request):
        return httpx.Response(200, json={"resultCode": "2004", "resultMsg": "No Data"})

    assert client_with(handler).lookup_certification("CB000-0000") is None


@pytest.mark.parametrize("code", ["4000", "4001", "4005", "5000"])
def test_failure_codes_raise_instead_of_looking_empty(code):
    """HTTP 200 이어도 실패다. 조용히 넘기면 인증/IP 문제가 '미조회'로 둔갑하고
    멀쩡한 인증번호에 RED 가 뜬다."""

    def handler(request):
        return httpx.Response(200, json={"resultCode": code, "resultMsg": "nope"})

    with pytest.raises(KatsApiError) as e:
        client_with(handler).lookup_certification("CB123A123-1234")
    assert e.value.code == code


def test_invalid_ip_error_explains_the_fix():
    def handler(request):
        return httpx.Response(200, json={"resultCode": "4001", "resultMsg": "Invalid IP"})

    with pytest.raises(KatsApiError, match="IP"):
        client_with(handler).lookup_certification("CB123A123-1234")


# --- 정규화 ----------------------------------------------------------------
@pytest.mark.parametrize(
    "raw", ["CB123A123-1234", "인증번호:CB123A123-1234", "ＣＢ123Ａ123-1234", " cb123a123-1234 "]
)
def test_normalize_kc_collapses_variants(raw):
    assert normalize_kc(raw) == "CB123A123-1234"
