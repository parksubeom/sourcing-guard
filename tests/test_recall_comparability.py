"""[4-r] **대조하지 않고 대조했다고 말하지 않는다.**

문제
----
`verifier` 가 `recall_clear` 를 붙일 조건을 `RecallIndex` 와 **따로 적었고**,
두 조건이 달랐다:

    verifier      facts.product_name or facts.model_name
    RecallIndex   model_name or kc_numbers or (maker and product_name)

`product_name` 만 있으면 `find()` 는 대조를 **안 하고** 빈 목록을 주는데
`verifier` 는 "리콜 목록에서 일치 항목을 찾지 못했습니다" 를 붙였다. `_axes`
에는 **"리콜 대조함 ✅"** 이 떴다. 둘 다 대조했다는 주장이고 대조는 없었다 (R3).

규모 (실측 · 2026-09-11)
------------------------
    새표본235 · 상품명만   233/233 = **100.0%**
    도매꾹109 · 상품명만   87/109 = 79.8%
    도매꾹109 · 상세       0/108 = 0.0%   (상세엔 maker 가 있다)

**크롬 확장이 상품명만 보내는 경로다.**

고친 방법
---------
`RecallIndex.can_compare()` 한 곳에서만 판단하고 `verifier` 는 그것을 부른다.
**조건을 두 곳에 적어서 갈린 것이 원인이므로 고치는 방법도 한 곳이어야 한다.**

⚠ 대체 문구는 **새 kind 가 아니라 `info_request`** 다. "무엇을 더 넣어라" 를
  말하는 자리는 이미 거기다 - 새 kind 를 만들면 [4-o] 표 9자리를 또 건드린다.
"""
from __future__ import annotations

import inspect
import re
from datetime import date
from unittest.mock import MagicMock

import pytest

from sourcing_guard import verifier as verifier_mod
from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts, WatchItem
from sourcing_guard.recall_index import RecallIndex
from sourcing_guard.scorer import _axes
from sourcing_guard.verifier import RuleBook, verify


class _FakeStore:
    """리콜 한 건을 담은 가짜 저장소. 실 DB·네트워크를 쓰지 않는다."""

    def recall_payloads(self, *, scope: str | None = None) -> list[str]:
        import json

        return [json.dumps({
            "product_name": "무관한 리콜 · 산업용 절단기",
            "model_name": "ZZ-9999-NOMATCH", "maker": "무관제조",
            "reason": "감전 위험", "announced_on": "20260901",
            "detail_url": "https://www.safetykorea.kr/recall/1",
            "scope": "domestic", "models": ["ZZ-9999-NOMATCH"],
            "cert_numbers": [], "uid": "fake-1",
        })]

    def latest_published_on(self) -> str | None:
        return "20260908"


@pytest.fixture(scope="module")
def rules() -> RuleBook:
    return RuleBook()


@pytest.fixture
def recalls() -> RecallIndex:
    return RecallIndex(_FakeStore())


@pytest.fixture
def kats():
    m = MagicMock()
    m.lookup_certification_cached.return_value = MagicMock(record=None)
    return m


_TODAY = date(2026, 9, 11)

_CASES = [
    ("상품명만", dict(product_name="유아용 블록 완구"), False),
    ("상품명+제조사", dict(product_name="유아용 블록 완구", maker="레고코리아"), True),
    ("모델명", dict(product_name="유아용 블록 완구", model_name="ABC-123"), True),
    ("인증번호", dict(product_name="유아용 블록 완구",
                     kc_numbers=["CB061R2170-3018"]), True),
    ("아무것도 없음", dict(), False),
]


@pytest.mark.parametrize("label,kw,expected", _CASES,
                         ids=[c[0] for c in _CASES])
def test_can_compare_matches_is_matchable(label, kw, expected, recalls):
    """`can_compare` 가 `WatchItem.is_matchable` 과 같은 답을 준다.

    ⚠ 둘이 갈리면 이 결함이 되돌아온다.
    """
    facts = ProductFacts(category=ItemCategory.CHILDREN_TOY, **kw)
    assert recalls.can_compare(facts, today=_TODAY) is expected
    probe = WatchItem.from_facts(id="p", owner_id="p", facts=facts, on=_TODAY)
    assert recalls.can_compare(facts, today=_TODAY) == probe.is_matchable()


@pytest.mark.parametrize("label,kw,can", _CASES, ids=[c[0] for c in _CASES])
def test_recall_clear_only_when_we_actually_compared(label, kw, can, recalls, kats, rules):
    """⚠⚠ **대조 못 했으면 `recall_clear` 가 붙지 않는다.**"""
    facts = ProductFacts(category=ItemCategory.CHILDREN_TOY, **kw)
    findings = verify(facts, kats, rules, recalls, None, None,
                      raw_text=kw.get("product_name", ""))
    kinds = {f.kind for f in findings}
    if can:
        assert FindingKind.RECALL_CLEAR in kinds, label
    else:
        assert FindingKind.RECALL_CLEAR not in kinds, (
            f"{label}: 대조 못 했는데 '일치 항목 없음' 을 말한다"
        )


def test_when_we_cannot_compare_we_say_what_is_missing(recalls, kats, rules):
    """대체 문구는 **새 kind 가 아니라 `info_request`** 다."""
    facts = ProductFacts(product_name="유아용 블록 완구",
                         category=ItemCategory.CHILDREN_TOY)
    findings = verify(facts, kats, rules, recalls, None, None,
                      raw_text="유아용 블록 완구")
    asks = [f for f in findings
            if f.kind is FindingKind.INFO_REQUEST
            and (f.detail or {}).get("missing_for") == "recall_match"]
    assert asks, "대조 못 한 이유를 말하지 않는다"
    text = asks[0].statement_ko
    # 셀러가 무엇을 하면 되는지 말해야 한다.
    assert "모델명" in text and "제조사" in text and "인증번호" in text
    assert "대조하지 않았습니다" in text
    # §9 — 단정하지 않는다.
    for banned in ("안전", "합법", "판매 가능", "이상 없"):
        assert banned not in text


@pytest.mark.parametrize("label,kw,can", _CASES, ids=[c[0] for c in _CASES])
def test_the_axis_does_not_claim_a_comparison_that_did_not_happen(
    label, kw, can, recalls, kats, rules
):
    """⚠ `_axes` 의 "리콜 대조함 ✅" 이 **거짓 안심의 절반**이었다."""
    facts = ProductFacts(category=ItemCategory.CHILDREN_TOY, **kw)
    findings = verify(facts, kats, rules, recalls, None, None,
                      raw_text=kw.get("product_name", ""))
    axis = next(a for a in _axes(findings, recalls.as_of, today=_TODAY)
                if a["key"] == "recall")
    if can:
        assert axis["done"] is True, label
    else:
        assert axis["done"] is False, f"{label}: 대조 안 했는데 축이 완료로 뜬다"
        assert axis["label"] != "대조함", label


def test_the_condition_lives_in_one_place_only():
    """⚠⚠ **조건을 두 곳에 적는 것을 막는다.** 그것이 이 결함의 원인이었다."""
    src = inspect.getsource(verify)
    # verifier 가 대조 가능 여부를 직접 판단하면 안 된다.
    assert "recalls.can_compare(" in src, "can_compare 를 부르지 않는다"

    # 리콜 분기 근처에서 매칭 필드 조합을 다시 적는지 본다.
    for line in src.splitlines():
        if "recall" not in line.lower():
            continue
        if "can_compare" in line or line.strip().startswith("#"):
            continue
        combo = sum(1 for f in ("model_name", "kc_numbers", "maker") if f in line)
        assert combo < 2, (
            f"verifier 가 대조 가능 조건을 다시 적고 있다: {line.strip()!r}"
        )


def test_the_batch_path_never_claims_a_recall_comparison():
    """배치는 상품명만 쓴다 - **같은 거짓말이 없는지** 실물로 확인한다.

    ⚠ 단건만 고치고 배치를 놓치면 같은 거짓말이 다른 화면에 남는다.
    """
    from pathlib import Path

    from sourcing_guard.batch import screen
    from sourcing_guard.item_grades import ItemGradeBook

    import dataclasses
    import json

    report = screen("유아용 블록 완구\n전기 방석 온열 매트\n지압슬리퍼",
                    ItemGradeBook())
    blob = json.dumps(dataclasses.asdict(report), ensure_ascii=False, default=str)
    for word in ("리콜", "recall", "대조"):
        assert word not in blob, f"배치 응답이 '{word}' 를 말한다"

    # 화면도 마찬가지다.
    html = (Path(__file__).resolve().parents[1]
            / "sourcing_guard/static/batch.html").read_text(encoding="utf-8")
    assert "리콜" not in html, "배치 화면이 리콜을 말한다 - 배치는 대조하지 않는다"
