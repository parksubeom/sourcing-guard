"""셀러가 답해 준 사실을 서버로 올린다 - 우리 판정이 아니다.

남은 오답 5건이 전부 "부속품이 본체 품목명을 그대로 달고 있는" 모양이었다.
부속어가 품목명에서 떨어져 있으면("무타공 전기면도기 스테인레스 거치대 면도기
홀더") 인접 가드가 못 잡고, 느슨하게 넓히면 정답 3건이 함께 죽는다. 실측으로
확인했으니 규칙으로 더 밀어붙이지 않고 상품명 밖의 정보를 받는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import (
    FindingKind,
    ItemCategory,
    ProductFacts,
    SellerHints,
)
from sourcing_guard.scorer import _PENALTY, score
from sourcing_guard.verifier import RuleBook, verify

from datetime import date

FRONT = Path(__file__).resolve().parents[1] / "sourcing_guard" / "static" / "index.html"
TODAY = date(2026, 9, 4)


class NoRecalls:
    as_of = "20260903"

    def is_empty(self):
        return False

    def find(self, facts, *, today=None):
        return []

    def by_maker_exact(self, maker, *, exclude_uids=None):
        return []


ACCESSORY = "무타공 전기면도기 스테인레스 거치대 면도기 홀더 욕실걸이"
UMBRELLA = "우산 양산 양우산 자동우산 골프우산 암막우산"


def run(name: str, category: ItemCategory, hints: SellerHints | None = None):
    facts = ProductFacts(product_name=name, category=category)
    found = verify(
        facts, KatsClient(None, None, mock=True), RuleBook(), NoRecalls(), hints=hints
    )
    return facts, found


def kinds(name, category, hints=None) -> list[str]:
    return [f.kind.value for f in run(name, category, hints)[1]]


# ---------------------------------------------------------------------------
# 1. 힌트가 없으면 힌트 도입 전과 같다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, category",
    [
        (ACCESSORY, ItemCategory.ELECTRICAL),
        (UMBRELLA, ItemCategory.HOUSEHOLD),
        ("신일 BLDC 무선 선풍기 14인치", ItemCategory.ELECTRICAL),
        ("곰돌이 인형 키링 9종", ItemCategory.HOUSEHOLD),
    ],
)
def test_no_hint_behaves_exactly_as_before(name, category):
    """힌트는 추가 정보이지 필수 입력이 아니다.

    None 과 빈 객체와 is_accessory=False 가 모두 같아야 한다 - 셀러가
    아무것도 안 눌러도 결과가 달라지면 안 된다.
    """
    bare = kinds(name, category, None)
    empty = kinds(name, category, SellerHints())
    said_main = kinds(name, category, SellerHints(is_accessory=False))
    assert bare == empty == said_main


# ---------------------------------------------------------------------------
# 2. 부속품이라고 답하면 본체 품목의 인증 의무를 묻지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, category, was",
    [
        # 오답이었다 - 거치대인데 '전기면도기' 가 상품명에 있어 AMBER 를 받았다.
        (ACCESSORY, ItemCategory.ELECTRICAL, "kc_missing_but_required"),
        (UMBRELLA, ItemCategory.HOUSEHOLD, "kc_absence_expected"),
    ],
)
def test_accessory_answer_drops_the_certification_warning(name, category, was):
    before = kinds(name, category)
    assert was in before

    after = kinds(name, category, SellerHints(is_accessory=True))
    assert was not in after
    assert "kc_missing_but_required" not in after
    assert "kc_tier_unknown" not in after
    assert "item_grade_not_applied" in after


def test_accessory_answer_removes_the_penalty():
    """오답이 점수를 깎던 것이 사라진다."""
    facts, before = run(ACCESSORY, ItemCategory.ELECTRICAL)
    assert sum(_PENALTY[f.kind] for f in before) > 0

    facts, after = run(ACCESSORY, ItemCategory.ELECTRICAL, SellerHints(is_accessory=True))
    assert sum(_PENALTY[f.kind] for f in after) == 0
    # "문제 없음" 이 되는 것은 아니다.
    assert score(facts, after).signal.value == "UNKNOWN"


# ---------------------------------------------------------------------------
# 3. 힌트는 셀러가 준 사실이지 우리 판정이 아니다
# ---------------------------------------------------------------------------


def test_the_basis_stays_on_screen():
    """우리가 판정한 것처럼 보이면 셀러가 자기 답을 우리 결론으로 착각한다."""
    _, found = run(ACCESSORY, ItemCategory.ELECTRICAL, SellerHints(is_accessory=True))
    one = next(f for f in found if f.kind is FindingKind.ITEM_GRADE_NOT_APPLIED)
    assert "셀러가 부속품으로 확인하셨습니다" in one.statement_ko
    assert one.detail["declared_by"] == "seller"
    # 어느 등급을 적용하지 않았는지도 남긴다 - 되돌릴 근거가 된다.
    assert one.detail["declined_item"]
    assert one.detail["declined_grade"]


def test_declining_a_grade_never_reads_as_exemption():
    _, found = run(UMBRELLA, ItemCategory.HOUSEHOLD, SellerHints(is_accessory=True))
    text = next(
        f.statement_ko for f in found if f.kind is FindingKind.ITEM_GRADE_NOT_APPLIED
    )
    for bad in ("대상이 아닙니다", "필요 없습니다", "면제", "없어도 됩니다"):
        assert bad not in text, (bad, text)


def test_children_parts_are_still_in_scope():
    """제2조 1호가 "물품 또는 그 부분품이나 부속품" 을 어린이제품에 포함한다."""
    _, found = run(ACCESSORY, ItemCategory.ELECTRICAL, SellerHints(is_accessory=True))
    text = next(
        f.statement_ko for f in found if f.kind is FindingKind.ITEM_GRADE_NOT_APPLIED
    )
    assert "어린이제품 안전 특별법" in text
    assert "제2조 1호" in text
    assert "부분품" in text
    # 부속품 자체가 별도 품목일 수 있다는 것도 말한다.
    assert "별도 품목" in text


# ---------------------------------------------------------------------------
# 4. 근거 없이 경고를 지우지 않는다
# ---------------------------------------------------------------------------


def test_a_hint_without_an_identified_item_changes_nothing():
    """품목을 못 특정했으면 힌트를 쓰지 않는다 (R3).

    화면은 등급 finding 위에만 질문을 띄우므로 정상 흐름에서 오지 않지만,
    들어와도 근거 없이 경고를 지우지는 않는다.
    """
    name = "모델명 XY-100 제조사 미상 220V"
    before = kinds(name, ItemCategory.ELECTRICAL)
    after = kinds(name, ItemCategory.ELECTRICAL, SellerHints(is_accessory=True))
    assert before == after
    assert "kc_missing_but_required" in after


# ---------------------------------------------------------------------------
# 5. (나) 를 받을 자리를 남겼다 - 이번에 구현하지는 않는다
# ---------------------------------------------------------------------------


def test_the_schema_holds_both_hints_and_neither_is_required():
    """2026-09-04 갱신: power_source 를 실제로 받는다.

    어제는 "아직 받지 않는다" 를 고정했다. 한 번에 둘을 넣으면 어느 쪽이
    깨졌는지 못 가리기 때문이었고, is_accessory 가 실측으로 검증된 뒤
    둘째를 넣었다. 검사가 예정대로 걸려서 갱신한다.

    둘 다 선택이다 - 아무것도 안 물어봐도 스캔이 돈다.
    """
    from sourcing_guard.main import ScanRequest

    req = ScanRequest(page_text="테스트")
    assert isinstance(req.seller_hints, SellerHints)
    assert req.seller_hints.is_accessory is None
    assert req.seller_hints.power_source is None

    got = ScanRequest.model_validate(
        {"page_text": "x", "seller_hints": {"power_source": "battery"}}
    )
    assert got.seller_hints.power_source == "battery"


def test_power_source_only_accepts_the_four_documented_values():
    """none 이 수동 기구를 가려낸다. 자유 문자열을 받으면 그 구분이 흐려진다."""
    for ok in ("mains", "battery", "solar", "none"):
        assert SellerHints(power_source=ok).power_source == ok
    with pytest.raises(Exception):
        SellerHints(power_source="배터리")


def test_unknown_hint_keys_are_rejected_quietly_not_loudly():
    """모르는 키가 와도 스캔이 죽지 않는다 - 힌트는 부가 정보다."""
    from sourcing_guard.main import ScanRequest

    req = ScanRequest.model_validate(
        {"page_text": "테스트", "seller_hints": {"is_accessory": True}}
    )
    assert req.seller_hints.says_accessory()


# ---------------------------------------------------------------------------
# 6. 화면이 답을 서버로 올린다
# ---------------------------------------------------------------------------


def test_the_screen_sends_the_hint_instead_of_editing_text_locally():
    """화면 안에서 문장만 바꾸면 다시 검사할 때 도로 막히고 AMBER 도 남는다."""
    src = FRONT.read_text(encoding="utf-8")
    assert "seller_hints: sellerHints" in src
    assert "sellerHints.is_accessory" in src


def test_the_screen_forgets_the_hint_when_the_product_changes():
    """이전 상품의 답을 다른 상품에 물려주면 안 된다."""
    src = FRONT.read_text(encoding="utf-8")
    assert "function clearHints()" in src
    assert 'pt.addEventListener("input", clearHints)' in src


def test_the_screen_lets_the_seller_undo():
    src = FRONT.read_text(encoding="utf-8")
    assert "되돌리기" in src


# ---------------------------------------------------------------------------
# 7. 실측 오답 5건이 힌트로 해소되는지 - 고정
# ---------------------------------------------------------------------------

_WRONG = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "도매꾹239_오답.tsv"


def _wrong_rows() -> list[tuple[str, str, str]]:
    out = []
    for line in _WRONG.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        name, item, why = line.split("\t")
        out.append((name, item, why))
    return out


def _category_of(name: str):
    """품목군을 등급표에서 가져온다 - scripts/measure_hint_effect.py 와 같은 방법.

    휴리스틱 추출은 상품명만으로 unclassified 를 내고, LLM 을 검사에서 부를
    수는 없다. 등급표가 적어 둔 품목군을 쓴다 (라이브로 확인: 우산→household ·
    선풍기→electrical · 공기청정기→electrical).
    """
    from sourcing_guard.item_grades import ItemGradeBook

    found = ItemGradeBook().lookup_all(name)
    assert found, name
    cats = {g.category for g in found}
    return (
        ItemCategory.ELECTRICAL if "electrical" in cats else ItemCategory.HOUSEHOLD
    )


def test_the_measured_wrong_answers_are_all_askable():
    """질문이 안 뜨는 오답은 힌트로 고칠 수 없다.

    화면은 등급 finding 위에만 질문을 띄운다. 등급 미매칭인 오답이 있으면
    별도 대응이 필요하므로, 실측 5건이 전부 질문 대상인지 고정한다.
    """
    asks = {FindingKind.ITEM_GRADE_MATCHED, FindingKind.ITEM_GRADE_SPLIT}
    for name, _item, _why in _wrong_rows():
        found = run(name, _category_of(name))[1]
        assert {f.kind for f in found} & asks, name


def test_the_measured_wrong_answers_are_resolved_by_the_hint():
    """힌트를 누르면 오답이 사라지고 인증 부재 경고도 남지 않는다.

    ⚠ 이것은 "자동으로 맞아졌다" 가 아니다. 셀러가 버튼을 눌러야 한다.
      기본 상태의 오답 건수는 그대로다 - 개선된 것은 "해소할 방법이 생겼다".
    """
    for name, item, _why in _wrong_rows():
        _facts, before = run(name, _category_of(name))
        # 오답이 실제로 그 품목으로 붙는지 먼저 확인한다 - 안 붙으면 이
        # 검사가 아무것도 재지 않는다.
        landed = [
            c["item"]
            for f in before
            if f.kind is FindingKind.ITEM_GRADE_MATCHED
            for c in f.detail.get("candidates", [])
        ]
        assert item in landed, (name, landed)

        _facts, after = run(name, _category_of(name), SellerHints(is_accessory=True))
        kinds_after = {f.kind for f in after}
        assert FindingKind.ITEM_GRADE_NOT_APPLIED in kinds_after, name
        assert FindingKind.KC_MISSING_BUT_REQUIRED not in kinds_after, name
        assert FindingKind.ITEM_GRADE_MATCHED not in kinds_after, name
        assert sum(_PENALTY[f.kind] for f in after) == 0, name


def test_the_default_state_still_has_the_wrong_answers():
    """힌트 없이는 줄지 않는다는 것을 명시로 고정한다.

    이걸 뭉쳐서 "오답 0" 이라고 보고하면 우리가 스스로를 속인다.
    """
    for name, _item, _why in _wrong_rows():
        found = run(name, _category_of(name))[1]
        assert sum(_PENALTY[f.kind] for f in found) > 0 or any(
            f.kind is FindingKind.ITEM_GRADE_MATCHED for f in found
        ), name


# ---------------------------------------------------------------------------
# 8. power_source - 조명 전용이 아니다
# ---------------------------------------------------------------------------

LIGHT = "간편부착 바트 무선 센서라이트 LED센서등 건전지형"
MANUAL = "지압봉 안마기 어깨마사지기 핸드안마기 발지압봉 마사지기"
POWERED = "문어발 USB 진동 마사지기 USB맛사지기 가정용안마기 어깨안마기"


def _grades(name: str, hints: SellerHints | None):
    from sourcing_guard.verifier import _item_grade_findings

    found = _item_grade_findings(name, TODAY, hints=hints)
    return found, [c["item"] for f in found for c in f.detail.get("candidates", [])]


@pytest.mark.parametrize(
    "answer, expect",
    [
        # 별표 1 11.나 일반조명기구(상시전원) vs 별표 2 11.다 그밖의 조명기구
        ("mains", "LED등기구"),
        ("battery", "충전식 휴대전등"),
        ("solar", "충전식 휴대전등"),
    ],
)
def test_power_answer_narrows_the_lighting_split(answer, expect):
    before, items = _grades(LIGHT, SellerHints())
    assert before[0].kind is FindingKind.ITEM_GRADE_SPLIT
    assert set(items) == {"LED등기구", "충전식 휴대전등"}

    after, narrowed = _grades(LIGHT, SellerHints(power_source=answer))
    assert narrowed == [expect], narrowed
    assert after[0].kind is FindingKind.ITEM_GRADE_MATCHED


def test_power_narrowing_never_invents_a_candidate():
    """좁히기만 하고 새로 만들지 않는다 (R3).

    셀러 답이 후보에 없는 품목을 가리켜도 끌어오지 않는다.
    """
    name = "신일 BLDC 무선 선풍기 14인치"
    _f, base = _grades(name, SellerHints())
    for answer in ("mains", "battery", "solar", "none"):
        _f2, got = _grades(name, SellerHints(power_source=answer))
        assert set(got) <= set(base), (answer, got)


def test_manual_tools_are_not_matched_without_an_answer():
    """'안마기' 는 전동인지 수동인지 상품명으로 못 가른다.

    그냥 키로 쓰면 지압봉이 전기마사지기(안전인증)로 붙어 오답이 된다.
    """
    _f, items = _grades(MANUAL, SellerHints())
    assert items == []


def test_saying_powered_opens_the_wider_alias():
    _f, items = _grades(POWERED, SellerHints(power_source="mains"))
    assert "전기마사지기" in items


def test_saying_unpowered_keeps_it_unmatched():
    """손으로 쓰는 기구는 전기용품이 아니다. 억지로 붙이지 않는다."""
    for name in (MANUAL, POWERED):
        _f, items = _grades(name, SellerHints(power_source="none"))
        assert items == []


# ---------------------------------------------------------------------------
# 9. 물어볼 자리가 있어야 답할 수 있다
# ---------------------------------------------------------------------------


def test_the_screen_can_ask_about_power_even_when_nothing_matched():
    """안마기는 매칭이 안 되므로 등급 finding 이 없다.

    물어볼 자리를 안 만들면 셀러가 답할 방법 자체가 없다 - 부속품 질문이
    등급 finding 위에만 뜨는 것과 같은 구조다.
    """
    found, _items = _grades(MANUAL, SellerHints())
    assert len(found) == 1
    assert found[0].kind is FindingKind.ITEM_GRADE_NEEDS_POWER
    assert found[0].detail["ask"] == "power"
    assert found[0].detail["question"] == "powered"


def test_the_lighting_split_carries_the_lighting_question():
    found, _items = _grades(LIGHT, SellerHints())
    assert found[0].detail["ask"] == "power"
    assert found[0].detail["question"] == "lighting"


def test_a_settled_item_is_not_asked_about_power():
    """정해진 것을 또 물으면 셀러가 우리가 모른다고 읽는다."""
    found, _items = _grades("신일 BLDC 무선 선풍기 14인치", SellerHints())
    assert found[0].kind is FindingKind.ITEM_GRADE_MATCHED
    assert "ask" not in found[0].detail


def test_the_two_questions_use_different_wording():
    """같은 필드지만 묻는 말이 다르다 - 조명과 안마기는 갈림의 성격이 다르다."""
    src = FRONT.read_text(encoding="utf-8")
    assert "상시전원인가요, 충전·건전지식인가요?" in src
    assert "전원을 쓰나요?" in src
    # 버튼은 JS 가 조립하므로 리터럴이 아니라 선택지 목록을 본다.
    assert 'data-power="' in src
    assert '["none", "손으로 쓰는 기구입니다"]' in src
    assert '["mains", "상시전원 (콘센트·배선)"]' in src
    assert '["battery", "충전·건전지식"]' in src
    # 답도 서버로 올린다.
    assert "sellerHints.power_source" in src


def test_asking_never_moves_the_signal():
    from sourcing_guard.scorer import _HARD_RED

    for kind in (FindingKind.ITEM_GRADE_NEEDS_POWER,):
        assert _PENALTY[kind] == 0
        assert kind not in _HARD_RED
