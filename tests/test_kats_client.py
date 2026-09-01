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
    extract_cert_numbers,
    extract_model_hints,
    is_cert_number,
    is_state_not_stated,
    split_list_field,
)
import yaml  # noqa: E402
from pathlib import Path  # noqa: E402

_CFG = yaml.safe_load(
    (Path("sourcing_guard/data/kats_field_map.yaml")).read_text(encoding="utf-8")
)
_STATES = _CFG["cert_states"]


def test_cert_states_cover_all_ten_spec_values():
    """설계서 3.2.1 의 certState 열거값 10가지를 빠짐없이 덮는다.

    누락되면 UNKNOWN 으로 떨어져 진짜 취소된 인증을 놓친다.

    실데이터에는 설계서에 없는 값도 있다("취소" — 2026-09-01 실측, 20만건 중 3건).
    그래서 '정확히 10개' 가 아니라 '10개를 모두 포함' 으로 검증한다. 설계서 밖의
    값을 추가하는 것은 막지 않되, 설계서 값이 빠지는 것은 막는다.
    """
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
    # 자리표시자 목록은 상태가 아니므로 제외한다.
    buckets = {k: v for k, v in _STATES.items() if k != "cert_state_not_stated"}
    mapped = {v for values in buckets.values() for v in values}
    missing = spec - mapped
    assert not missing, f"설계서 상태값이 매핑에서 빠졌습니다: {missing}"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("적합", CertState.OK),
        ("안전인증취소", CertState.REVOKED),
        ("안전확인신고 효력상실", CertState.REVOKED),
        # 기간만료·반납은 행정 사유라 REVOKED 가 아니다. 완구 인증 144,738건 중
        # 96,275건(67%)이 기간만료여서 RED 로 두면 정상 상품 대부분에 빨간불이
        # 뜬다 (2026-09-01 실연동 실측, CLAUDE.md R3-b).
        ("기간만료", CertState.EXPIRED),
        ("반납", CertState.EXPIRED),
        ("안전인증표시 사용금지 2개월", CertState.SUSPENDED),
        ("안전인증표시 사용금지 4개월", CertState.SUSPENDED),
        ("안전확인신고표시 사용금지 2개월", CertState.SUSPENDED),
        ("개선명령", CertState.UNDER_ACTION),
        ("청문실시", CertState.UNDER_ACTION),
    ],
)
def test_classify_each_spec_state(raw, expected):
    assert classify_cert_state(raw, _STATES) is expected


def test_expired_and_returned_are_not_red():
    """기간만료·반납에 RED 를 주면 정상 상품에 빨간불이 반복된다 (CLAUDE.md R3-b).

    RED 는 정부 DB 가 문제를 적어둔 경우에만 준다. 실제 사유를 보면 갈린다 —
    처벌은 법 조항이 적히고("어린이제품법 21조1항2호_시판품 부적합"),
    반납은 "반납_인증기관은 FITI 시험연구원으로 변경됨" 같은 행정 사유다.

    셀러가 오탐 RED 에 익숙해지면 진짜 취소된 인증도 안 보게 되어,
    애초에 고치려던 문제로 돌아간다.
    """
    from sourcing_guard.models import FindingKind
    from sourcing_guard.scorer import _HARD_RED

    assert FindingKind.KC_EXPIRED not in _HARD_RED
    for raw in ("기간만료", "반납"):
        assert classify_cert_state(raw, _STATES) is CertState.EXPIRED
        assert classify_cert_state(raw, _STATES) is not CertState.REVOKED


def test_punitive_states_stay_red():
    """행정 사유를 내리는 것이 처벌까지 무르게 하면 안 된다."""
    from sourcing_guard.models import FindingKind
    from sourcing_guard.scorer import _HARD_RED

    assert FindingKind.KC_REVOKED in _HARD_RED
    assert FindingKind.KC_SUSPENDED in _HARD_RED
    for raw in ("안전인증취소", "안전확인신고 효력상실"):
        assert classify_cert_state(raw, _STATES) is CertState.REVOKED


def test_bare_cancel_is_revoked_not_unknown():
    """설계서에 없지만 실재하는 "취소" 를 UNKNOWN 으로 두면 조용히 통과한다.

    certChgReason 이 None 이라 안전인증취소와 같은지 확답은 못 한다. 그러나
    셀러가 "취소" 를 보고 확인하는 것은 손해가 아닌 반면, 놓치는 것은 이
    프로젝트가 가장 비싸다고 규정한 오류다 (2026-09-01 실측: 20만건 중 3건).
    """
    from sourcing_guard.models import FindingKind
    from sourcing_guard.scorer import _HARD_RED

    assert classify_cert_state("취소", _STATES) is CertState.REVOKED
    assert FindingKind.KC_REVOKED in _HARD_RED


@pytest.mark.parametrize("raw", ["-", "없음", "해당없음", "해당사항없음", "N/A"])
def test_placeholder_state_is_not_stated(raw):
    """certState 가 "-" 인 것은 상태가 아니라 값이 비었다는 뜻이다 (완구 43건)."""
    assert is_state_not_stated(raw, _STATES) is True
    assert classify_cert_state(raw, _STATES) is CertState.UNKNOWN


@pytest.mark.parametrize("raw", ["적합", "안전인증취소", "기간만료", "알수없는상태"])
def test_real_states_are_not_treated_as_missing(raw):
    assert is_state_not_stated(raw, _STATES) is False


def test_unmapped_state_is_logged_but_placeholder_is_not(caplog):
    """새 상태값이 조용히 UNKNOWN 으로 떨어지면 나중에 알아챌 수 없다.

    자리표시자는 이미 아는 값이라 로그를 남기지 않는다 — 43건이 매번 경고를
    찍으면 진짜 새 상태값이 묻힌다.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="sourcing_guard.kats_client"):
        classify_cert_state("듣도보도못한상태", _STATES)
    assert "듣도보도못한상태" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sourcing_guard.kats_client"):
        classify_cert_state("-", _STATES)
    assert caplog.text == ""


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


# ---------------------------------------------------------------------------
# 근거 링크(R2)는 설계서에 실린 인증번호별 주소 하나만 쓴다
# ---------------------------------------------------------------------------
from sourcing_guard.kats_client import cert_evidence_url  # noqa: E402


def _py_files_containing(needle: str) -> list[str]:
    return [
        f.name
        for f in Path("sourcing_guard").rglob("*.py")
        if needle in f.read_text(encoding="utf-8")
    ]


def test_evidence_url_is_per_certificate():
    url = cert_evidence_url("JU071047-12002C")
    assert "searchPop" in url
    assert "certNum=JU071047-12002C" in url


def test_evidence_url_normalises_the_number():
    """화면 문구와 링크가 같은 대상을 가리켜야 한다."""
    assert cert_evidence_url("인증번호: ju071047-12002c") == cert_evidence_url("JU071047-12002C")


def test_undocumented_endpoint_is_not_used_in_code():
    """`release/certDetail` 은 설계서에 없는 주소다.

    실측으로 200 이 뜨더라도 문서화되지 않은 엔드포인트는 예고 없이 바뀌고,
    파라미터가 없어 특정 인증번호를 가리키지 못한다 (CLAUDE.md R5).
    되돌리려는 시도를 이 테스트가 막는다.
    """
    offenders = _py_files_containing("safetykorea.kr/release/certDetail")
    assert not offenders, f"설계서에 없는 주소를 쓰는 파일: {offenders}"


def test_get_hostile_search_url_is_not_used_as_evidence():
    """`release/certificationsearch` 는 GET 에 405 를 돌려준다 (실측).

    설계서 p.18 에 실려 있지만 셀러가 클릭하면 오류 화면을 보므로 근거 링크로
    쓸 수 없다. 매핑의 unusable_urls 에 기록용으로만 남긴다.
    """
    assert "cert_search" not in _CFG.get("public_urls", {})
    assert "cert_search_405_on_get" in _CFG.get("unusable_urls", {})
    offenders = _py_files_containing("safetykorea.kr/release/certificationsearch")
    assert not offenders, f"405 주소를 근거 링크로 쓰는 파일: {offenders}"


# ---------------------------------------------------------------------------
# 인증번호 패턴 — 리콜 실데이터 약 1,700건(2026-09-01)으로 확정.
# 덤프: docs/리콜_certNum_모델명_원문덤프_2026-09-01.tsv
#       docs/리콜_certNum_품목군별_2026-09-01.tsv
# ---------------------------------------------------------------------------

# 실인증번호. 조회로 실재를 확인한 것들이다.
REAL_CERT_NUMBERS = [
    "CB061R2170-3018",     # 도매꾹 슬라임. 접두 2글자
    "JU071047-12002C",     # 설계서 예시. 하이픈 뒤 접미 1글자
    "CA011R021-4001",      # 안전인증취소
    "B363R871-5002",       # 접두 1글자 (B계열 — 학용품 리콜의 36%)
    "A123T001-0200",       # 접두 1글자
    "B361H490-5003CH",     # 하이픈 뒤 접미 2글자
    "cb064a3166-2004chC",  # 전부 소문자 + 끝에 대문자
    "Cb061m003-5001",      # 대소문자 혼합
]


@pytest.mark.parametrize("num", REAL_CERT_NUMBERS)
def test_extractor_finds_every_real_cert_number(num):
    """셀러가 붙여넣은 번호를 못 찾으면 조회 자체를 시도하지 않는다.

    이전 정규식은 [A-Z]{2} 를 가정해 B 계열과 소문자 표기를 통째로 놓쳤다.
    그러면 멀쩡한 인증번호가 '표기 없음' 으로 처리된다.
    """
    from sourcing_guard.extractor import extract

    facts = extract(f"유아용 블록 완구 장난감 KC 인증번호 {num} 대상연령 3세", None)
    assert num in facts.kc_numbers, f"추출 실패: {num}"


@pytest.mark.parametrize("num", REAL_CERT_NUMBERS)
def test_cert_number_survives_recall_field_extraction(num):
    """리콜 certNum 필드에 잡음이 섞여 와도 번호는 살아남아야 한다."""
    assert extract_cert_numbers(f"({num})") == [normalize_kc(num)]


def test_extractor_and_client_share_one_pattern():
    """두 곳에 정규식을 따로 두면 한쪽만 고쳐져 갈라진다."""
    import inspect

    from sourcing_guard import extractor
    from sourcing_guard.kats_client import CERT_NUMBER_RE

    assert extractor.CERT_NUMBER_RE is CERT_NUMBER_RE

    # 주석이 아니라 코드 형태를 겨냥한다. 위 주석이 [A-Z]{2} 를 설명하느라
    # 그 문자열을 담고 있어서, 문자열만 찾으면 스스로에게 걸린다.
    src = "\n".join(
        ln for ln in inspect.getsource(extractor).splitlines()
        if not ln.lstrip().startswith("#")
    )
    assert "re.compile" not in src, "추출기에 자체 정규식이 되살아났습니다"
    assert "[A-Z]{2}" not in src, "추출기에 자체 인증번호 패턴이 되살아났습니다"


@pytest.mark.parametrize(
    "raw,numbers,models",
    [
        # 부품별로 괄호 라벨이 앞에 붙는 형태 (전기용품)
        ("(배터리) ZU10282-19001, (충전기)SU07706-17003",
         ["ZU10282-19001", "SU07706-17003"], ["배터리", "충전기"]),
        # 모델명 : 인증번호 쌍. 쌍으로 묶지 않고 각각 후보에 넣는다 (v1 범위)
        ("- WF24A95** : HU072172-21013 / WF25B96** : HU072172-22017",
         ["HU072172-21013", "HU072172-22017"], ["WF24A95**", "WF25B96**"]),
        # HTML 조각이 그대로 온다 (완구 certNum 96건)
        ("CB064R3345-1003 <br (인증모델: 반짝반짝 달님이)>",
         ["CB064R3345-1003"], ["반짝반짝 달님이"]),
        # 슬래시 구분 + 중첩 괄호
        ("CB067R644-4001/CB064R1686-8001A (인증모델 : RC미니카(New 배틀미니 레이서))",
         ["CB067R644-4001", "CB064R1686-8001A"], ["RC미니카(New 배틀미니 레이서)"]),
        # 콤마 구분 다중 번호
        ("B361H490-5003CH,B441R284-7001A,B361R774-8001A",
         ["B361H490-5003CH", "B441R284-7001A", "B361R774-8001A"], []),
        # 판매 채널 표시는 모델명이 아니다 (실데이터 9건)
        ("(온라인)CB061R6936-2001", ["CB061R6936-2001"], []),
        # 값이 비어 있는 자리표시자
        ("-<br>(인증모델: -)", [], []),
    ],
)
def test_whitelist_extraction_on_real_recall_values(raw, numbers, models):
    """구분자를 열거해 자르지 않고 인증번호를 찾아낸다.

    실데이터의 구분자는 콤마만이 아니라 슬래시·괄호·<br>·줄바꿈·공백이 섞여
    있고 새 형태가 계속 나온다. 화이트리스트 추출은 구분자가 늘어도 안 깨진다.
    """
    assert extract_cert_numbers(raw) == numbers
    assert extract_model_hints(raw) == models


@pytest.mark.parametrize(
    "raw", ["비대상", "공급자적합성대상", "공급자적합성", "(제품에 표시 없음)",
            "(인증모델: )", "-", "0505-502-0100", "듣도보도못한신종자리표시자"],
)
def test_values_without_a_cert_number_are_placeholders(raw):
    """완전 일치 목록만 쓰면 새 자리표시자가 나올 때마다 통과한다.

    실제로 "비대상"(54건) "공급자적합성대상"(19건)이 목록에 없어 통과하고 있었다.
    자리표시자를 인증번호로 취급하면 같은 값을 가진 서로 다른 상품이 전부
    일치로 잡힌다.
    """
    assert is_cert_number(raw) is False
    assert extract_cert_numbers(raw) == []


@pytest.mark.parametrize("num", REAL_CERT_NUMBERS)
def test_real_cert_numbers_are_not_placeholders(num):
    assert is_cert_number(num) is True


# ---------------------------------------------------------------------------
# 정부 API 실패 추적. 우리 설정 문제와 일시 장애를 갈라야 한다.
# ---------------------------------------------------------------------------


def test_health_counts_consecutive_failures_and_resets_on_success():
    from sourcing_guard.kats_client import KatsHealth

    h = KatsHealth()
    assert h.consecutive_failures == 0

    h.record_failure("5000", "Internal Server Error")
    h.record_failure("5000", "Internal Server Error")
    assert h.consecutive_failures == 2
    assert h.last_error_code == "5000"
    assert h.last_error_at is not None

    h.record_success()
    assert h.consecutive_failures == 0
    # 마지막 오류 코드는 남긴다. 방금 무슨 일이 있었는지 알 수 있어야 한다.
    assert h.last_error_code == "5000"


@pytest.mark.parametrize("code,is_ours", [
    ("4000", True),   # 인증키 무효
    ("4001", True),   # IP 미등록
    ("4005", True),   # 파라미터 오류
    ("5000", False),  # 정부 서버 장애
    ("network", False),
])
def test_operator_fault_is_distinguished(code, is_ours):
    """우리 설정 문제에 대고 '다시 시도하세요' 라고 하면 거짓말이다.

    고치기 전엔 계속 실패한다. 이 구분이 화면 문구를 가른다.
    """
    from sourcing_guard.kats_client import KatsHealth

    h = KatsHealth()
    h.record_failure(code)
    assert h.is_operator_fault() is is_ours


def test_healthz_never_reports_not_ok_on_kats_failure():
    """정부 API 가 죽었다고 우리 서비스를 죽이면 안 된다.

    Fly 헬스체크가 ok 를 보고 머신을 재시작시킨다. ok 는 우리 프로세스 상태이고
    kats 는 별도 정보다.
    """
    from fastapi.testclient import TestClient

    from sourcing_guard.kats_client import health
    from sourcing_guard.main import app

    health.record_failure("4001", "Invalid IP")
    try:
        body = TestClient(app).get("/healthz").json()
        assert body["ok"] is True
        assert body["kats"]["last_error_code"] == "4001"
        assert body["kats"]["consecutive_failures"] >= 1
    finally:
        health.record_success()
        health.last_error_code = None
        health.last_error_at = None
