"""등급 갈림 화면. 셀러가 실제로 받는 메시지를 검사한다.

여기서 R3-b 의 핵심 결정이 나온다. 공기청정기는 표에 안전확인과
공급자적합성확인 양쪽에 있고, 한쪽은 "번호가 반드시 있어야 함", 다른 쪽은
"번호 없는 것이 정상" 이다. 문구를 잘못 쓰면 셀러가 위법 상태로 팔거나
정상 상품을 포기한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sourcing_guard.models import Finding, FindingGroup, FindingKind, Signal
from sourcing_guard.scorer import _PENALTY, _HARD_RED
from sourcing_guard.verifier import _GRADE_MEANING, _item_grade_findings

TODAY = date(2026, 9, 3)
FRONT = Path(__file__).resolve().parents[1] / "sourcing_guard" / "static" / "index.html"


def one(name: str) -> Finding:
    found = _item_grade_findings(name, TODAY)
    assert len(found) == 1, found
    return found[0]


# ---------------------------------------------------------------------------
# 합의 등급이 있으면 그대로 말한다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, grade",
    [
        ("신일 BLDC 무선 선풍기 14인치", "안전인증"),
        ("모즈온 미니 도킹 보조배터리 5000 C타입", "안전확인"),
    ],
)
def test_agreed_grade_is_stated_plainly(name, grade):
    f = one(name)
    assert f.kind is FindingKind.ITEM_GRADE_MATCHED
    assert grade in f.statement_ko
    assert f.detail["grade"] == grade
    # 등급이 뜻하는 바를 함께 적는다. 등급만 말하면 셀러가 할 일이 안 정해진다.
    assert _GRADE_MEANING[grade] in f.statement_ko


def test_several_candidates_with_the_same_grade_still_speak_plainly():
    """후보가 셋이어도 등급이 같으면 오히려 확실해진다 - 어느 품목이든 같은 의무다."""
    f = one("키친아트 큐티 멀티쿠커 MS-D10")
    assert f.kind is FindingKind.ITEM_GRADE_MATCHED
    assert len(f.detail["candidates"]) >= 2
    assert f.detail["grade"] == "안전인증"


# ---------------------------------------------------------------------------
# 갈리면 후보를 다 내고, 한쪽을 고르지 않는다
# ---------------------------------------------------------------------------

SPLIT_CASES = [
    ("HK HAIKE 13급 원룸 소형 미니공기청정기", {"안전확인", "공급자적합성확인"}),
    ("간편부착 바트 무선 센서라이트 LED센서등 건전지형", {"안전인증", "안전확인"}),
]


@pytest.mark.parametrize("name, grades", SPLIT_CASES)
def test_split_lists_every_candidate(name, grades):
    f = one(name)
    assert f.kind is FindingKind.ITEM_GRADE_SPLIT
    assert set(f.detail["grades"]) == grades
    for g in grades:
        assert g in f.statement_ko, f.statement_ko


@pytest.mark.parametrize("name, grades", SPLIT_CASES)
def test_split_explains_what_each_grade_means(name, grades):
    """등급 이름만 나열하면 셀러가 뜻을 모른다. 두 뜻이 정반대라 특히 그렇다."""
    f = one(name)
    for g in grades:
        assert _GRADE_MEANING[g] in f.statement_ko, (g, f.statement_ko)


@pytest.mark.parametrize("name, _g", SPLIT_CASES)
def test_split_never_picks_the_looser_grade(name, _g):
    """느슨한 쪽을 골라 "번호 없어도 됩니다" 라고 하면 위법을 권하는 셈이다 (R3).

    특히 공급자적합성확인 쪽으로 단정하면, 실제로 안전확인 대상인 상품을
    번호 없이 팔게 만든다.
    """
    f = one(name)
    forbidden = ("없어도 됩니다", "없어도 무관", "필요 없습니다", "필요없습니다",
                 "대상이 아닙니다", "면제", "괜찮습니다")
    for bad in forbidden:
        assert bad not in f.statement_ko, (bad, f.statement_ko)
    # 확인을 요청하고, 단정하지 않는다고 밝힌다.
    assert "공급처에 확인" in f.statement_ko
    assert "단정하지 않습니다" in f.statement_ko


def test_split_keeps_the_server_order_so_the_screen_cannot_reorder():
    """강한 순(정확→포함→확장→별칭)을 유지한다.

    화면이 순서를 바꾸면 느슨한 등급이 위로 올라올 수 있다. 순서를 서버가
    정하고 화면은 그대로 그린다.
    """
    f = one("HK HAIKE 13급 원룸 소형 미니공기청정기")
    got = [c["grade"] for c in f.detail["candidates"]]
    assert got == ["안전확인", "공급자적합성확인"], got


# ---------------------------------------------------------------------------
# 등급을 알아낸 것은 사실 확인이지 위험이 아니다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", [FindingKind.ITEM_GRADE_MATCHED, FindingKind.ITEM_GRADE_SPLIT]
)
def test_grade_findings_do_not_move_the_signal(kind):
    assert _PENALTY[kind] == 0
    assert kind not in _HARD_RED
    # 셀러가 확인할 것이므로 맨 위 구획이다.
    assert Finding(
        kind=kind, signal=Signal.UNKNOWN, statement_ko="확인",
        source_label="근거", source_url="https://law.go.kr/",
    ).group is FindingGroup.ACTION


def test_items_absent_from_the_table_fall_back_to_tier_unknown():
    """등급표에 없으면 빈 목록을 준다. 부르는 쪽이 기존 경로로 넘어간다."""
    assert _item_grade_findings("곰돌이 인형 키링 9종", TODAY) == []
    assert _item_grade_findings(None, TODAY) == []


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------


def test_screen_renders_candidates_as_a_list_not_inside_the_sentence():
    src = FRONT.read_text(encoding="utf-8")
    assert "function gradeRow(f)" in src
    assert 'f.kind === "item_grade_split"' in src
    assert 'f.kind === "item_grade_matched"' in src


def test_screen_asks_whether_the_product_is_the_main_item_or_an_accessory():
    """남은 오답은 전부 부속품이 본체 품목명을 달고 있는 모양이다.

    상품명 밖의 정보가 없으면 가릴 수 없으니 셀러에게 묻는다. 판정하지
    않고 답을 받는다 (R1).
    """
    src = FRONT.read_text(encoding="utf-8")
    assert "function partRow(f)" in src
    assert 'data-part="main"' in src
    assert 'data-part="accessory"' in src


def test_accessory_answer_does_not_claim_children_parts_are_exempt():
    """「어린이제품 안전 특별법」 제2조 1호가 "부분품이나 부속품" 을 포함한다.

    부속품이라고 답했다고 "대상이 아닙니다" 로 끝내면 어린이용 부속품에
    틀린 면제를 말한다.

    2026-09-03 갱신: 이 문구가 화면 JS 에서 **서버 문장**으로 옮겨졌다.
    부속품 답을 서버로 올려야 인증 부재 경고(AMBER)까지 빠지기 때문이다.
    화면 템플릿을 보던 검사를 실제로 전달되는 문장을 보도록 바꿨다 -
    옮기면서 문구를 잃지 않았는지가 이 검사의 요지이고, 서버 출력을 보는
    쪽이 더 강하다.
    """
    from sourcing_guard.models import ItemCategory, ProductFacts, SellerHints
    from sourcing_guard.verifier import _item_grade_findings

    # ⚠ 예전 예("무타공 전기면도기 … 거치대 면도기 홀더")는 이름이 독립
    #   부속품명('홀더')으로 끝나서 names_a_standalone_accessory 가 매칭 자체를
    #   막는다. 힌트 경로를 재려면 여전히 붙는 이름이어야 한다.
    found = _item_grade_findings(
        "전기 면도기 거치대 꽂이 걸이 홀더 치약 정리 보관 수납 걸기 "
        "화장실걸이 욕실용품 전동칫솔 인테리어",
        TODAY,
        hints=SellerHints(is_accessory=True),
    )
    assert len(found) == 1
    text = found[0].statement_ko
    assert "어린이제품 안전 특별법" in text
    assert "제2조 1호" in text
    assert "부분품" in text
    # 셀러가 말한 것임을 밝힌다 - 우리 판정으로 보이면 안 된다.
    assert "셀러가 부속품으로 확인하셨습니다" in text
    assert found[0].detail["declared_by"] == "seller"
    # "대상이 아닙니다" 로 끝내지 않는다.
    assert "대상이 아닙니다" not in text


# ---------------------------------------------------------------------------
# 등급을 알아냈으면 일반론을 위에 두지 않는다
# ---------------------------------------------------------------------------

_GENERIC_TIERS = "안전인증·안전확인 대상이면 인증번호가 있어야 하고"


def _missing(name: str, *, grade: str | None) -> str:
    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import _kc_missing_finding

    facts = ProductFacts(product_name=name, category=ItemCategory.ELECTRICAL)
    return _kc_missing_finding(facts, TODAY, grade=grade).statement_ko


def test_generic_tier_sentence_is_dropped_once_the_grade_is_known():
    """특정된 답이 바로 아래 붙는데 일반론을 먼저 두면 같은 말을 두 번 읽는다."""
    known = _missing("HK HAIKE 소형 미니공기청정기", grade="안전확인")
    assert _GENERIC_TIERS not in known


def test_the_other_two_jobs_survive():
    """이 문장이 하는 일 셋 중 ②만 뺀다.

      ① "인증번호를 찾지 못했습니다"        유지
      ② "안전인증·안전확인 대상이면…"       등급을 알아냈으면 뺀다
      ③ 정부 사이트 직접 검색 링크          유지
    """
    known = _missing("HK HAIKE 소형 미니공기청정기", grade="안전확인")
    assert "인증번호를 찾지 못했습니다" in known
    assert "직접 검색" in known  # 정부 사이트 직접 검색 링크 안내
    assert "공급처에" in known


def test_generic_tier_sentence_stays_when_the_grade_is_unknown():
    """등급을 모르면 일반론이 셀러가 가진 유일한 단서다."""
    unknown = _missing("곰돌이 인형 키링 9종", grade=None)
    assert _GENERIC_TIERS in unknown


# ---------------------------------------------------------------------------
# [O] category 게이트 부분 개방 — unclassified 는 열고 out_of_scope 는 막는다
# ---------------------------------------------------------------------------


def test_unclassified_still_gets_the_grade_table():
    """LLM 이 품목군을 몰라도 등급표는 조회한다.

    등급표는 품목명으로 찾는 결정론적 경로이고 facts.category 와 독립이다.
    상품명에 '무릎보호대' 가 있으면 표에서 찾을 수 있다.

    ⚠ **우리가 확실히 아는 것을 LLM 이 몰랐다는 이유로 버리는 것은 R3 정신과
      반대다.** R3 은 "모르면 UNKNOWN" 이지 "LLM 이 모르면 아는 것도 버려라"
      가 아니다.

    실측(단건 경로 30건): category 게이트에 10건(33%)이 막혀 있었다 -
    unclassified 7 · out_of_scope 3. 개방 후 2건이 회복되고 오답은 0건이었다.
    """
    from unittest.mock import MagicMock

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    facts = ProductFacts(product_name="킥보드 보호 헬멧 로봇 플라워",
                         category=ItemCategory.UNCLASSIFIED)
    got = [
        c["item"]
        for x in verify(facts, kats, RuleBook())
        for c in (x.detail or {}).get("candidates", [])
    ]
    assert "자전거용 안전모" in got


def test_out_of_scope_never_gets_the_grade_table():
    """"우리 소관 아님" 에는 전안법 등급을 붙이지 않는다.

    정수기컵(식약처 식품용 기구)·목발형 보행기(의료기기)에 등급을 말하면
    오답이고 셀러에게 **없는 의무를 만든다**.
    """
    from unittest.mock import MagicMock

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    for name in ("나도컵 꼬깔컵 생수컵 정수기컵 2000매 디스펜서",
                 "목발형 접이식 보행기 깁스 보조 지팡이 이동",
                 "자동차 시트커버 여름 메쉬 차량용 등받이 방석"):
        facts = ProductFacts(product_name=name, category=ItemCategory.OUT_OF_SCOPE)
        got = [
            c["item"]
            for x in verify(facts, kats, RuleBook())
            for c in (x.detail or {}).get("candidates", [])
        ]
        assert got == [], (name, got)


def test_opening_the_gate_does_not_demand_a_certificate():
    """등급을 냈다고 인증번호를 요구하지는 않는다.

    _cert_required_here 는 facts.category 를 키로 쓰므로 unclassified 에서는
    False 다. 등급 finding 자신이 "공급처에 인증 구분을 요청하세요" 라고 말하고,
    우리가 "번호가 있어야 한다" 로 단정하지 않는다 (R3-b).
    """
    from unittest.mock import MagicMock

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    facts = ProductFacts(product_name="킥보드 보호 헬멧 로봇 플라워",
                         category=ItemCategory.UNCLASSIFIED)
    kinds = [x.kind.value for x in verify(facts, kats, RuleBook())]
    assert "kc_missing_but_required" not in kinds


def test_a_child_marker_in_the_name_opens_the_catch_all_conditionally():
    """[판정 3 · 2026-09-12] '초등학생 책가방' 이 이제 답을 받는다.

    ⚠⚠ **이 검사는 2026-09-11 에 정반대였다.** 그때 이름은
      `test_a_child_marker_alone_yields_neither_a_grade_nor_the_catch_all`
      이었고 "현재 동작의 기록" 이라 적었다. 그 docstring 이 스스로
      "바꾸려면 표지어를 연령 표기로 승격시켜야 하고, 그건 우리가
      '어린이제품이다' 를 판정하는 쪽으로 한 걸음 가는 일" 이라고 걱정했다.

    **승격시키지 않는 방법으로 열었다.** `target_age` 는 그대로 None 이고
    문구가 조건문이다 - "이 상품이 만 13세 이하 어린이용이라면". 우리가
    어린이제품이라고 말하지 않는다 (R1). 법 내용 자체는 확정된 것이고,
    불확실한 것은 이 상품이 그 법의 대상인가다. 그 불확실을 문장 안에 둔다.

    왜 열었나: `target_age` 가 도매꾹 상세 109 에서 1건뿐이라 연령 표기만
    입구로 두면 축이 안 열린다. 원인은 추출기가 아니라 셀러가 안 적는 것이다.
    """
    from unittest.mock import MagicMock

    from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    facts = ProductFacts(
        product_name="EVERYGOOD 학생용 대용량 책가방 백팩 초등학생 선물 추천",
        category=ItemCategory.UNCLASSIFIED,
        target_age=None,
    )
    found = verify(facts, kats, RuleBook())
    kinds = [f.kind for f in found]

    assert FindingKind.ITEM_GRADE_MATCHED not in kinds   # 품목은 여전히 모른다
    assert FindingKind.CHILD_CATCH_ALL in kinds          # 포괄 규정은 받는다

    catch = next(f for f in found if f.kind is FindingKind.CHILD_CATCH_ALL)
    # ⚠ 어느 입구로 들어왔는지 센다. 출력 모양으로 추론하지 않는다 (R7 by_vendor).
    assert catch.detail["entry"] == "product_name_marker"
    assert catch.detail["markers"] == ["초등"]
    assert catch.detail["target_age"] is None, "표지어를 연령 표기로 승격시켰다"
    # ⚠⚠ 문구 셋을 잠근다 (총괄 판정 2026-09-12).
    #
    #   이 finding 은 SPECIFIC(유효 결과)로 세어진다. 법은 확정이고 근거 URL 이
    #   있으며, 근거가 **셀러 자신이 상품명에 쓴 표기**이기 때문이다. 그러면
    #   문장이 그 근거와 그 한계를 스스로 말해야 한다.
    assert "표기를 근거로" in catch.statement_ko, "근거가 상품명 표기임을 안 밝힌다"
    assert "라면" in catch.statement_ko, "조건문이 아니다"
    # §9 - 단정 금지. "대상입니다" 가 아니라 "대상일 수 있습니다".
    assert "대상일 수 있습니다" in catch.statement_ko
    assert "대상입니다" not in catch.statement_ko, "표지어만으로 대상이라고 단정했다"
    assert "어린이제품입니다" not in catch.statement_ko
    # 대상연령을 아직 모르므로 확인 요청은 남는다.
    assert FindingKind.INFO_REQUEST in kinds

    # 대상연령이 표기되면 같은 규정을 **단정문**으로 받는다.
    facts_aged = facts.model_copy(
        update={"target_age": "만 7세 이상", "category": ItemCategory.CHILDREN_TEXTILE}
    )
    aged = verify(facts_aged, kats, RuleBook())
    catch_aged = next(f for f in aged if f.kind is FindingKind.CHILD_CATCH_ALL)
    assert catch_aged.detail["entry"] == "target_age"
    assert catch_aged.detail["markers"] == []
    assert "어린이제품입니다" in catch_aged.statement_ko
    # ⚠ 반대 방향도 잠근다 - 연령 표기 경로까지 조건문으로 약해지면 셀러가
    #   적어 준 사실을 우리가 안 믿는 것이 된다.
    assert "대상입니다" in catch_aged.statement_ko
    assert "표기를 근거로" not in catch_aged.statement_ko


def test_the_marker_path_is_a_specific_result_and_says_why():
    """[판정 · 2026-09-12] 표지어 경로 `child_catch_all` 은 **SPECIFIC 이다.**

    셋을 나란히 놓으면 갈린다:

        recall_weak_match   우리가 말하는 **사실**이 불확실하다(우연 일치)   NON
        scope_undetermined  어느 법인지 **모른다**                          NON
        child_catch_all     법은 **확정**이고 근거 URL 이 있다. 불확실한 것은
        (표지어)            대상 여부이고, 그 근거는 **셀러 자신이 상품명에
                            쓴 표기**다                                    SPECIFIC

    "이 상품명은 어린이용으로 표기됐고, 그 경우 어린이제품법 포괄규정이
    적용된다" 는 이 상품에 대한 구체적이고 근거 있는 사실이다. 지표에서 빼면
    **실제로 준 것을 안 줬다고 세는 것**이다.

    ⚠ kind 는 하나로 둔다. 갈래는 `detail.entry` 다 - [4-o] 의 FindingKind 표를
      또 건드리지 않는다.
    """
    from sourcing_guard.models import SPECIFIC_FINDING_KINDS, FindingKind

    assert FindingKind.CHILD_CATCH_ALL in SPECIFIC_FINDING_KINDS
    assert FindingKind.RECALL_WEAK_MATCH not in SPECIFIC_FINDING_KINDS
    assert FindingKind.SCOPE_UNDETERMINED not in SPECIFIC_FINDING_KINDS


def test_a_child_marker_that_modifies_another_item_does_not_open_it():
    """[판정 3] 표지어가 **다른 품목을 수식**하면 열지 않는다.

    실측(새표본235)에서 게이트를 열었을 때 비대상 오염이 딱 하나 나왔다:

        [115] 안전벨트락 스토퍼 고정 클립 임산부 **어린이 카시트** 홀더

    카시트는 자동차관리법 소관이다. '카시트' 는 새표본235 6건 · 도매꾹190
    5건이고 **열한 건 전부 비대상**이라 제외어로 안전하다.
    """
    from unittest.mock import MagicMock

    from sourcing_guard.item_grades import CHILD_MARKER_EXCLUSIONS, has_child_marker
    from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    facts = ProductFacts(
        product_name="안전벨트락 스토퍼 고정 클립 임산부 어린이 카시트 홀더",
        category=ItemCategory.UNCLASSIFIED,
    )
    kinds = [f.kind for f in verify(facts, kats, RuleBook())]
    assert FindingKind.CHILD_CATCH_ALL not in kinds

    # ⚠⚠ **반대 방향도 잰다** (§6). 제외어를 '자동차'·'차량' 으로 넓히면
    #   정답을 죽인다 - 실측으로 확인한 세 줄이다. 짧은 일반어를 넣지 않는다.
    for word in ("자동차", "차량"):
        assert word not in CHILD_MARKER_EXCLUSIONS, (
            f"'{word}' 는 제외어가 될 수 없다 - 놀이방매트 '자동차도로'·"
            "'차량용 청소기' 같은 정상 대상이 함께 죽는다"
        )
    assert has_child_marker("놀이방매트 아기바닥 자동차도로 장판보온 유아용쿠션")

    # 소유자가 하나다 - 별칭 게이트와 포괄 규정 게이트가 같은 함수를 본다.
    assert has_child_marker("안전벨트락 … 어린이 카시트 홀더") is False


def test_a_split_grade_does_not_claim_a_missing_certificate():
    """[판정 4 · 2026-09-12] 품목이 갈리면 인증번호 부재를 해석하지 않는다.

    전에는 갈릴 때 `agreed=None` 으로 떨어져 일반형 `kc_missing_but_required`
    가 함께 붙었다. 화면이 **같은 말을 두 번** 했다 - 실물 [5] 발열무릎담요
    (전기방석이 안전인증과 공급자적합성확인으로 갈린다):

        kc_missing_but_required  "…인증번호를 찾지 못했습니다. 안전인증·안전확인
                                  대상이면 있어야 하고, 공급자적합성확인 대상이면
                                  없는 것이 정상입니다."
        item_grade_split         "…갈리지 않습니다. 안전인증 대상이면 … 공급자
                                  적합성확인 대상이면 …"

    ⚠⚠ 더 나쁜 것은 **틀을 씌운 것**이다. "찾지 못했습니다" 는 있어야 할 것이
      없다는 틀인데, 갈리는 동안 우리는 **있어야 하는지조차 모른다.** 부재의
      의미를 모르면서 부재를 지적하는 것은 R3 이 막는 자리다.
    """
    from unittest.mock import MagicMock

    from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts
    from sourcing_guard.verifier import (
        SPLIT_CERT_CLAUSE,
        SPLIT_CLOSING,
        RuleBook,
        verify,
    )

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    facts = ProductFacts(
        product_name="USB 포켓 발열무릎담요 플란넬 양털 극세사 대형 무릎담요",
        category=ItemCategory.ELECTRICAL,
    )
    found = verify(facts, kats, RuleBook())
    kinds = [f.kind for f in found]

    split = next((f for f in found if f.kind is FindingKind.ITEM_GRADE_SPLIT), None)
    assert split is not None, "이 상품은 전기방석 두 등급으로 갈려야 한다"
    assert len(split.detail["grades"]) > 1
    assert FindingKind.KC_MISSING_BUT_REQUIRED not in kinds

    # 갈림 finding 이 인증번호 축을 스스로 말한다 - 새 kind 를 만들지 않았다.
    assert SPLIT_CERT_CLAUSE.strip() in split.statement_ko
    # ⚠ **마무리 문장 앞에** 들어가야 읽힌다. 뒤에 덧붙으면 "단정하지 않습니다"
    #   다음에 "해석하지 않습니다" 가 와서 같은 말을 두 번 하게 된다.
    assert split.statement_ko.index(SPLIT_CERT_CLAUSE.strip()) < split.statement_ko.index(
        SPLIT_CLOSING
    )
    # 갈림이 한 번만 나간다 (중복 방지 검사가 같은 객체를 보는지).
    assert kinds.count(FindingKind.ITEM_GRADE_SPLIT) == 1


def test_a_settled_grade_still_says_the_certificate_is_missing():
    """⚠⚠ 반대 방향. **확정일 때는 그대로다** (§6 - 가드의 반대 방향도 잰다).

    갈림에서 뺐다고 확정에서도 빼면, 안전인증 대상인데 번호가 없는 상품에
    아무 말도 안 하게 된다 - 그건 판정 4 가 고치려던 것의 정반대다.
    """
    from unittest.mock import MagicMock

    from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    for name in ("전기 온수매트 싱글 온열매트", "가정용 전기주전자 커피포트"):
        facts = ProductFacts(product_name=name, category=ItemCategory.ELECTRICAL)
        found = verify(facts, kats, RuleBook())
        kinds = [f.kind for f in found]
        if FindingKind.ITEM_GRADE_SPLIT in kinds:
            continue  # 갈리는 줄은 이 검사의 대상이 아니다
        assert FindingKind.KC_MISSING_BUT_REQUIRED in kinds, name


def test_the_two_marker_gates_read_different_inputs_on_purpose():
    """⚠⚠ 같은 신호(어린이 표지어)를 두 게이트가 **다른 입력**에서 읽는다.

    실수가 아니다. 재고 정했다 (2026-09-12).

        별칭      등급표 **조회**를 넓힌다 → 틀려도 확인 화면이 뜬다 → 원본까지
        포괄 규정  **의무를 새로 만든다**  → 틀리면 없는 의무 → 상품명만

    통일하고 싶어지면 **먼저 재라.** 별칭 쪽을 상품명으로 좁혀 본 측정:

        다섯 기준   ① 95 → 93 · ③ 113 → 112
        도매꾹 상세  정답 89 → 86 · 미매칭 16 → 19

    잃는 3건이 전부 진짜 상품이었다 - [179] 산리오 필통(학용품보관) ·
    [181] 초등필통 · [200] EVA 실내화. 셋 다 LLM 이 정리한 상품명에서 표지어가
    떨어졌고, 원본에는 있었다.
    """
    import inspect

    from sourcing_guard import item_grades, verifier
    from tests.srccheck import code_only

    alias_gate = code_only(inspect.getsource(item_grades.ItemGradeBook.lookup_all))
    # ⚠ `code_only` 는 토큰을 공백으로 이어 붙이므로 간격이 늘어난다. 두 이름이
    #   **gate_text 를 만드는 같은 줄에** 있는지만 본다.
    gate_line = next(
        (ln for ln in alias_gate.splitlines() if "gate_text =" in ln), ""
    )
    assert "product_name" in gate_line and "raw_text" in gate_line, (
        "별칭 게이트가 원본을 안 본다 - 좁히면 진짜 상품 3건을 잃는다. "
        "바꾸려면 다섯 기준과 도매꾹 상세 109 를 먼저 재라"
    )

    catch_gate = code_only(inspect.getsource(verifier.verify))
    assert "has_child_marker ( facts . product_name )" in catch_gate, (
        "포괄 규정 게이트가 상품명 말고 다른 것을 본다 - 본문을 열면 도매꾹 109 의 "
        "오탐 16건(차량용 청소기·전기그릴 광고 문구)이 들어온다"
    )
    # ⚠ 근거가 주석에 남아 있어야 한다. 없으면 다음 사람이 "중복" 으로 보고 합친다.
    assert "일부러 다르다" in inspect.getsource(verifier.verify)


def test_suppressing_the_missing_cert_drops_amber_to_unknown_not_green():
    """[판정 4 · 방향 고정] 갈림에서 인증부재를 빼면 **AMBER → UNKNOWN** 이다.

    ⚠⚠ 실물 표본에 **갈림 + AMBER 조합이 없다.** 하나뿐인 갈림 줄
      ([5] 발열무릎담요)은 `coverage_gap` 때문에 이미 UNKNOWN 이었다
      (`scorer._signal_for` 가 COVERAGE_GAP 을 AMBER 집합보다 먼저 본다).

      그래서 이 검사는 **합성 finding 으로 방향만 고정**한다. 실물 표본이
      생기면 그때 실측으로 바꾼다 (미완).

    왜 UNKNOWN 이 옳은가: 갈리는 동안 우리는 인증번호가 **있어야 하는지조차
    모른다.** 모르는 것을 "확인 필요"(AMBER)로 올리면 셀러가 할 수 있는 일이
    없는 경고를 받는다. 모르면 UNKNOWN 이다 (R3).

    ⚠ **GREEN 으로는 절대 안 내려간다.** 초록불은 두 축의 적극적 증거를
      요구하고(`KC_VERIFIED` + `RECALL_CLEAR`), 갈림 줄에는 그것이 없다.
      이것이 이 고침에서 가장 비싼 오류였을 것이다 (R3-b).
    """
    from datetime import date

    from sourcing_guard.models import (
        Finding,
        FindingKind,
        ItemCategory,
        ProductFacts,
        Signal,
    )
    from sourcing_guard.scorer import score

    today = date(2026, 9, 12)
    facts = ProductFacts(product_name="전기방석", category=ItemCategory.ELECTRICAL)

    def _f(kind: FindingKind, signal: Signal) -> Finding:
        return Finding(
            kind=kind,
            signal=signal,
            statement_ko="(검사용)",
            source_label="검사",
            source_url="https://www.safetykorea.kr/",
            checked_at=today,
        )

    # ⚠ COVERAGE_GAP 을 일부러 빼서 AMBER 가 실제로 나올 수 있는 상태를 만든다.
    split_only = [
        _f(FindingKind.ITEM_GRADE_SPLIT, Signal.UNKNOWN),
        _f(FindingKind.RECALL_CLEAR, Signal.GREEN),
    ]
    with_missing = split_only + [
        _f(FindingKind.KC_MISSING_BUT_REQUIRED, Signal.AMBER)
    ]

    assert score(facts, with_missing, today=today).signal is Signal.AMBER
    after = score(facts, split_only, today=today).signal
    assert after is Signal.UNKNOWN
    assert after is not Signal.GREEN, "부재 지적을 뺀 것이 초록불이 되면 안 된다"
