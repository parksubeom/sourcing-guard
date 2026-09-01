

# --- 인증번호 없을 때 직접 검색 링크 (허점 1-B) ----------------------------
def test_missing_cert_offers_a_direct_search_link():
    """인증번호가 없으면 제품명·제조사로 직접 검색하는 링크를 연다.

    아마존·구매대행 상품은 KC 번호가 없는 게 정상이다. '모르겠습니다' 로 끝내지
    않고 셀러가 정부 사이트에서 직접 확인할 경로를 준다. 우리가 대신 '인증 없음'
    을 단정하지 않는다 (R3).
    """
    from sourcing_guard.models import ProductFacts, ItemCategory, FindingKind
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.verifier import RuleBook, verify

    facts = ProductFacts(
        product_name="colourmotor 페인트 마커",
        maker="colourmotor",
        category=ItemCategory.CHILDREN_STATIONERY,
    )
    findings = verify(facts, KatsClient(None, None, mock=True), RuleBook(), None)
    missing = [f for f in findings if f.kind is FindingKind.KC_MISSING_BUT_REQUIRED]
    assert missing, "인증번호 없는 규제 품목에 안내가 없습니다"
    f = missing[0]
    assert "itemSearch" in f.source_url
    assert "colourmotor" in f.statement_ko  # 검색어를 문구에 안내
    assert f.detail.get("search_term") == "colourmotor"


def test_item_search_url_is_stable_without_a_term():
    """검색어가 없어도 링크는 안 깨진다 (순수 링크 기본)."""
    from sourcing_guard.kats_client import item_search_url

    assert item_search_url().startswith("https://www.safetykorea.kr")
    assert item_search_url("colourmotor").startswith("https://www.safetykorea.kr")


def test_item_search_link_carries_no_query_string():
    """검색어를 링크에 붙이지 않는다.

    프로덕션 실측(2026-09-01): 이 페이지는 검색어 파라미터를 무시한다
    (searchWord·itemName·keyword·prdtNm·certNum 전부 응답 동일). 붙이면
    "검색 결과로 직행한다" 는 기대만 만들고 실제로는 첫 화면이 열린다.

    pageNo·categoryCode3 은 GET 으로 먹지만 쓰지 않는다 - 임의 페이지 또는
    빈 목록으로 셀러를 보내게 된다. 근거는 kats_field_map.yaml 참조.
    """
    from sourcing_guard.kats_client import item_search_url

    for term in [None, "", "컬러모터", "CB061R2170-3018", "완구"]:
        url = item_search_url(term)
        assert "?" not in url, f"검색어가 링크에 붙었습니다: {url}"
        assert url == item_search_url(), "검색어에 따라 링크가 달라지면 안 됩니다"
