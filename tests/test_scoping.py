

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


# ---------------------------------------------------------------------------
# 공통안전기준 값을 최종 적용값처럼 말하지 않는다
#
# 규칙 DB 에 지금 들어 있는 17건은 전부 공통안전기준이다. 품목별 부속서(완구 6·
# 학용품 11·유아용 섬유제품 1)가 같은 물질에 더 엄격한 값을 정하는 경우가 있어,
# 공통기준 값만 보여주면 셀러에게 실제보다 느슨한 수치를 준다. "모른다" 가
# 아니라 "틀렸다" 라서 문장으로 한계를 밝힌다.
#
# 부속서가 수록되면 이 테스트가 먼저 실패한다 - 그때 문구를 다시 볼 것.
# ---------------------------------------------------------------------------


def test_common_standard_is_not_presented_as_the_final_limit():
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    facts = ProductFacts(
        product_name="유아 순면 배냇저고리",
        category=ItemCategory.CHILDREN_TEXTILE,
        target_age="0~6개월",
    )
    hits = [
        f for f in verify(facts, KatsClient(None, None, mock=True), RuleBook())
        if f.kind is FindingKind.HAZARD_RULE_APPLIES
    ]
    assert hits, "유아용 섬유제품에 유해물질 기준 안내가 하나도 없다"
    for f in hits:
        assert "공통안전기준" in f.statement_ko
        assert "부속서" in f.statement_ko


def test_rule_db_holds_only_common_standards_for_now():
    """부속서가 들어오면 여기가 먼저 실패한다.

    그때 할 일: status: draft 로 넣고(§5), 사람 검수 후 verified 로 승격하고,
    verifier 의 "품목별 부속서가 더 엄격한 값을" 문구를 다시 볼 것.
    """
    from pathlib import Path

    import yaml

    import sourcing_guard

    path = Path(sourcing_guard.__file__).parent / "data" / "hazard_rules.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = doc["rules"] if isinstance(doc, dict) and "rules" in doc else doc
    bases = {r.get("legal_basis", "") for r in rules}
    assert all("공통안전기준" in b for b in bases), (
        f"부속서 근거가 들어왔다: {sorted(b for b in bases if '공통안전기준' not in b)}. "
        "verifier 의 부속서 단서 문구와 이 테스트를 갱신할 것."
    )
