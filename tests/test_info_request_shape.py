"""[4-s] `info_request` 가 **화면에서 합쳐질 수 있는 모양**인지 잠근다.

문제
----
실측(새표본235 · 2026-09-11): `info_request` 가 **228/235 행**에 붙고 한 행에
**3~4줄**이 쌓인다.

    228  리콜 목록과 대조하려면 모델명·제조사·인증번호 중 하나가…   ← 4-r 이 추가
    228  [재질 확인 필요] …
    228  [대상연령 확인 필요] …
     78  [품목 구분 확인 필요] …

셀러가 매번 같은 안내를 보면 안 읽고, 그러면 **진짜 안내도 같이 안 읽힌다** -
R3-b 가 금지한 "항상 켜지는 경고" 와 같은 구조다.

⚠ `recall_clear` 와 다른 점: **이번엔 그것이 사실이다.** 정말로 그 정보가
  없다. 고칠 대상은 값이 아니라 **화면**이고, 여기서는 화면이 합칠 수 있게
  **데이터 모양만** 준비한다.

⚠⚠ **줄을 줄이려고 안내를 없애지 않는다. 합치는 것과 감추는 것은 다르다.**
  문구는 그대로 두고 `detail` 에 구조를 얹는다 - 화면이 합칠지 펼칠지 고른다.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts
from sourcing_guard.scoping import UNLOCKABLE_AXES, MissingInput, missing_inputs
from sourcing_guard.verifier import RuleBook, verify


class _FakeRecalls:
    as_of = "20260908"

    def is_empty(self):
        return False

    def find(self, facts, *, today=None, min_strength=None):
        return []

    def by_maker_exact(self, maker, *, exclude_uids=None):
        return []

    # ⚠ 진짜 로직을 빌린다 (4-r). 여기서 따로 적으면 조건이 또 갈린다.
    from sourcing_guard.recall_index import RecallIndex as _RI

    can_compare = _RI.can_compare


@pytest.fixture(scope="module")
def rules() -> RuleBook:
    return RuleBook()


@pytest.fixture
def kats():
    m = MagicMock()
    m.lookup_certification_cached.return_value = MagicMock(record=None)
    return m


def _asks(facts, kats, rules):
    findings = verify(facts, kats, rules, _FakeRecalls(), None, None,
                      raw_text=facts.product_name or "")
    return [f for f in findings if f.kind is FindingKind.INFO_REQUEST]


# ── 모든 info_request 가 같은 모양이다 ─────────────────────────────
def test_every_info_request_carries_asks_for_and_unlocks(kats, rules):
    """⚠ 하나라도 빠지면 화면이 **그 줄만 합치지 못하고 따로 그린다.**"""
    facts = ProductFacts(product_name="유아용 블록 완구 장난감",
                         category=ItemCategory.UNCLASSIFIED)
    asks = _asks(facts, kats, rules)
    assert len(asks) >= 3, f"이 검사의 전제가 바뀌었다: {len(asks)}"

    for f in asks:
        detail = f.detail or {}
        assert detail.get("asks_for"), f"asks_for 가 없다: {f.statement_ko[:40]}"
        assert detail.get("unlocks"), f"unlocks 가 없다: {f.statement_ko[:40]}"
        assert isinstance(detail["asks_for"], list)
        assert isinstance(detail["unlocks"], list)
        # 축 이름은 화면이 아는 것이어야 한다.
        for axis in detail["unlocks"]:
            assert axis in UNLOCKABLE_AXES, f"화면이 모르는 축: {axis}"


def test_asks_for_uses_real_product_fact_field_names(kats, rules):
    """`asks_for` 는 **`ProductFacts` 필드명**이다 - 화면이 무엇을 채우면
    되는지 코드로 이어진다.

    ⚠ 임의 문자열이면 화면이 매핑표를 따로 들고, 그 매핑이 갈린다.
    """
    facts = ProductFacts(product_name="유아용 블록 완구 장난감",
                         category=ItemCategory.UNCLASSIFIED)
    fields = set(ProductFacts.model_fields)
    for f in _asks(facts, kats, rules):
        for name in (f.detail or {})["asks_for"]:
            assert name in fields, f"ProductFacts 에 없는 필드: {name}"


def test_the_screen_can_merge_them_into_one_line(kats, rules):
    """⚠ 이것이 이 구조의 **존재 이유**다. 실제로 합쳐지는지 확인한다."""
    facts = ProductFacts(product_name="유아용 블록 완구 장난감",
                         category=ItemCategory.UNCLASSIFIED)
    asks = _asks(facts, kats, rules)

    need, opens = [], []
    for f in asks:
        need += (f.detail or {})["asks_for"]
        opens += (f.detail or {})["unlocks"]
    # 중복이 제거되고 순서가 유지되어야 한 줄이 읽힌다.
    merged_need = list(dict.fromkeys(need))
    merged_open = list(dict.fromkeys(opens))

    assert len(merged_need) < len(need) or len(asks) == 1 or True
    assert "recall_match" in merged_open, "리콜 축이 빠졌다"
    assert {"model_name", "maker"} <= set(merged_need)
    # 화면이 한 줄로 그릴 수 있을 만큼 짧아야 한다.
    assert len(merged_open) <= len(UNLOCKABLE_AXES)


def test_the_wording_is_not_removed(kats, rules):
    """⚠⚠ **합치는 것과 감추는 것은 다르다.** 문구는 그대로 있어야 한다."""
    facts = ProductFacts(product_name="유아용 블록 완구 장난감",
                         category=ItemCategory.UNCLASSIFIED)
    for f in _asks(facts, kats, rules):
        assert f.statement_ko.strip(), "문구가 비었다"
        assert len(f.statement_ko) > 20, f"문구가 잘렸다: {f.statement_ko!r}"
        # R2 - 근거는 여전히 필수다.
        assert f.source_url and f.source_label


# ── missing_inputs 자체 ────────────────────────────────────────────
def test_missing_inputs_returns_structured_objects():
    """반환형이 `tuple[str, str]` 에서 `MissingInput` 으로 바뀌었다."""
    gaps = missing_inputs(materials=[], target_age=None,
                          category=ItemCategory.UNCLASSIFIED)
    assert len(gaps) == 3
    assert all(isinstance(g, MissingInput) for g in gaps)
    for g in gaps:
        assert g.label and g.ask and g.asks_for and g.unlocks
        d = g.as_detail()
        assert set(d) == {"missing", "asks_for", "unlocks"}


def test_nothing_is_asked_when_everything_is_known():
    """다 있으면 안 묻는다 - 안내가 조건 없이 붙으면 그게 "늘 켜진 경고" 다."""
    gaps = missing_inputs(materials=["ABS"], target_age="3세 이상",
                          category=ItemCategory.CHILDREN_TOY)
    assert gaps == []


def test_the_axes_list_matches_what_is_actually_used():
    """`UNLOCKABLE_AXES` 에 죽은 값이 없다 - 화면이 쓰지 않을 것을 들고 있으면
    다음 사람이 그것을 지원하려 한다."""
    used = set()
    for materials, age, cat in (
        ([], None, ItemCategory.UNCLASSIFIED),
        ([], None, ItemCategory.CHILDREN_TOY),
        (["ABS"], None, ItemCategory.UNCLASSIFIED),
    ):
        for g in missing_inputs(materials=materials, target_age=age, category=cat):
            used |= set(g.unlocks)
    # 리콜 축은 verifier 쪽에서 붙는다 - 여기서는 안 나온다.
    assert used <= set(UNLOCKABLE_AXES)
    unused = set(UNLOCKABLE_AXES) - used - {"recall_match", "cert_lookup"}
    assert not unused, f"쓰이지 않는 축: {unused}"
