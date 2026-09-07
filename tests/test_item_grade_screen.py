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


def test_a_child_marker_alone_yields_neither_a_grade_nor_the_catch_all():
    """'초등학생 책가방' 화면에 실제로 무엇이 남는지 사실로 적어 둔다.

    ⚠ ALIASES_IF_NO_CHILD_MARKER 를 만들 때 "품목을 안 붙여도 어린이제품
      포괄 규정이 받는다" 고 적었는데 **틀렸다.** catch-all 은
      age is CHILD_PRODUCT 를 요구하고, 그 값은 페이지가 대상연령을
      표기했을 때만 채워진다. '초등학생' 은 용도 설명이라 추출이
      target_age 로 옮기지 않는다 - verifier 주석이 "UNKNOWN 에는 안
      붙인다" 라고 이미 못박아 둔 의도된 동작이다.

    그래서 이 검사는 "고쳐야 할 결함" 이 아니라 **현재 동작의 기록**이다.
    바꾸려면 표지어를 연령 표기로 승격시켜야 하고, 그건 우리가
    "어린이제품이다" 를 판정하는 쪽으로 한 걸음 가는 일이라 별도 결정이다.
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
    kinds = [f.kind for f in verify(facts, kats, RuleBook())]

    assert FindingKind.ITEM_GRADE_MATCHED not in kinds
    assert FindingKind.CHILD_CATCH_ALL not in kinds
    # 남는 것은 확인 요청이다 - 셀러가 대상연령을 채우면 그때 갈린다.
    assert FindingKind.INFO_REQUEST in kinds

    # 대상연령이 표기되면 포괄 규정이 받는다.
    facts_aged = facts.model_copy(
        update={"target_age": "만 7세 이상", "category": ItemCategory.CHILDREN_TEXTILE}
    )
    kinds_aged = [f.kind for f in verify(facts_aged, kats, RuleBook())]
    assert FindingKind.CHILD_CATCH_ALL in kinds_aged
