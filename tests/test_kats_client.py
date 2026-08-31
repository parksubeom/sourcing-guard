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


# ---------------------------------------------------------------------------
# A: certState 분류 (설계서 p.5 / p.8)
# ---------------------------------------------------------------------------
from sourcing_guard.kats_client import (  # noqa: E402
    CertState,
    classify_cert_state,
    split_list_field,
)
import yaml  # noqa: E402
from pathlib import Path  # noqa: E402

_CFG = yaml.safe_load(
    (Path("sourcing_guard/data/kats_field_map.yaml")).read_text(encoding="utf-8")
)
_STATES = _CFG["cert_states"]


def test_cert_states_cover_all_ten_spec_values():
    """설계서 3.2.1 의 certState 열거값은 10가지다. 누락되면 UNKNOWN 으로 떨어진다."""
    spec = {
        "적합",
        "안전인증취소",
        "개선명령",
        "안전인증표시 사용금지 2개월",
        "안전인증표시 사용금지 4개월",
        "안전확인신고 효력상실",
        "안전확인신고표시 사용금지 2개월",
        "반납",
        "청문실시",
        "기간만료",
    }
    mapped = {v for values in _STATES.values() for v in values}
    assert mapped == spec, f"차이: {spec ^ mapped}"
    assert len(mapped) == 10


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("적합", CertState.OK),
        ("안전인증취소", CertState.REVOKED),
        ("안전확인신고 효력상실", CertState.REVOKED),
        ("기간만료", CertState.REVOKED),
        ("반납", CertState.REVOKED),
        ("안전인증표시 사용금지 2개월", CertState.SUSPENDED),
        ("안전인증표시 사용금지 4개월", CertState.SUSPENDED),
        ("안전확인신고표시 사용금지 2개월", CertState.SUSPENDED),
        ("개선명령", CertState.UNDER_ACTION),
        ("청문실시", CertState.UNDER_ACTION),
    ],
)
def test_classify_each_spec_state(raw, expected):
    assert classify_cert_state(raw, _STATES) is expected


@pytest.mark.parametrize("raw", [None, "", "적 합", "적합 ", "알수없는상태"])
def test_unmapped_state_is_unknown_never_ok(raw):
    """공백이 끼거나 표기가 다르면 '적합'으로 추측하지 않는다 (CLAUDE.md R3).

    '적합 ' 처럼 뒤에 공백만 있는 경우는 strip 으로 살리고, 가운데 공백이 낀
    '적 합' 은 다른 값으로 본다.
    """
    result = classify_cert_state(raw, _STATES)
    if raw == "적합 ":
        assert result is CertState.OK
    else:
        assert result is not CertState.OK


# ---------------------------------------------------------------------------
# B: 콤마 목록 분해 (설계서 p.11, p.14)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, []),
        ("", []),
        ("BLK-100", ["BLK-100"]),
        ("A,B,C", ["A", "B", "C"]),
        (" A , B ,, C ", ["A", "B", "C"]),
        ("공급자적합성", ["공급자적합성"]),
    ],
)
def test_split_list_field(raw, expected):
    assert split_list_field(raw) == expected


# ---------------------------------------------------------------------------
# C: 국내/국외 필드 의미 차이 (설계서 p.14 vs p.17)
# ---------------------------------------------------------------------------
def test_domestic_and_overseas_action_guide_come_from_different_fields():
    """accidentCaseDscr 은 국내에서 위해정보, 국외에서 소비자 행동요령이다.

    같은 이름이므로 하드코딩하면 국외 리콜에 엉뚱한 문구가 표시된다.
    """
    dom = _CFG["operations"]["recall_domestic"]["fields"]
    ovs = _CFG["operations"]["recall_overseas"]["fields"]

    assert dom["action_guide"] == "publishActionDscr"
    assert ovs["action_guide"] == "accidentCaseDscr"
    assert dom["reason"] == "harmDscr"
    assert ovs["reason"] == "violateDscr"
    assert dom["action_guide"] != ovs["action_guide"]


def test_mock_mode_surfaces_revoked_certificate():
    """목 모드에도 취소된 인증이 있어야 이 경로가 개발 중에 실제로 걸린다."""
    client = KatsClient(None, None, mock=True)
    rec = client.lookup_certification("CB123A123-1234")
    assert rec is not None
    assert rec.state is CertState.REVOKED
    assert rec.status == "안전인증취소"
