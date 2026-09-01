"""같은 제조사의 다른 리콜 — 참고 정보 축 하나만 남긴 이유.

로컬 사본 37,313건으로 축 세 개를 실측했다 (2026-09-01).

  제조사 정확 일치   13~63건      ← 셀러에게 보여줄 만한 숫자. 이것만 쓴다
  제조사 포함 일치   1,600건+     어떤 질의에도. '코리아' 303 '산업' 131 '무역' 54
  품목군            671~1,370건  버킷이 11종뿐. 완구 671 · 전기용품 1,370
  재질              2,181건/2건   어휘 불일치. 프탈레이트 3,259 vs ABS 2

137건 오탐(ee7011c)에서 배운 것이 그대로 적용된다 - 넓히면 소음이 되고,
소음이 된 경고는 꺼진 경고와 같다.
"""

from datetime import date

import pytest

from sourcing_guard.kats_client import KatsClient, RecallRecord
from sourcing_guard.models import (
    Finding,
    FindingGroup,
    FindingKind,
    ItemCategory,
    ProductFacts,
    Signal,
)
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify

TODAY = date(2026, 9, 1)


class FakeIndex:
    """RecallIndex 대역. by_maker_exact 만 실제 규칙으로 돈다."""

    def __init__(self, records: list[RecallRecord]) -> None:
        self._records = records
        self.as_of = "20260828"

    def is_empty(self) -> bool:
        return not self._records

    def all_records(self) -> list[RecallRecord]:
        return self._records

    def find(self, facts, *, today, **kw):
        return []

    def by_maker_exact(self, maker, *, exclude_uids=None):
        from sourcing_guard.recall_index import RecallIndex

        return RecallIndex.by_maker_exact(self, maker, exclude_uids=exclude_uids)

    def _load(self):
        return self._records


def rec(maker: str, *, uid: str = "1", product: str = "다른 상품", on: str = "20260801"):
    return RecallRecord(
        product_name=product, model_name="OTHER-1", maker=maker, reason="기준 초과",
        announced_on=on, detail_url="https://www.safetykorea.kr/x", scope="domestic", uid=uid,
    )


def _run(facts: ProductFacts, records: list[RecallRecord]):
    findings = verify(facts, KatsClient(None, None, mock=True), RuleBook(), FakeIndex(records))
    return findings, score(facts, findings, recall_data_as_of="20260828")


# ---------------------------------------------------------------------------
# 정확 일치만
# ---------------------------------------------------------------------------


def test_same_maker_is_reported_with_a_count():
    facts = ProductFacts(product_name="어린이 의자", maker="이케아",
                         model_name="LATT-1", category=ItemCategory.CHILDREN_TOY)
    findings, _ = _run(facts, [rec("이케아", uid="1"), rec("이케아", uid="2"), rec("한샘", uid="3")])
    f = next(x for x in findings if x.kind is FindingKind.MAKER_OTHER_RECALLS)
    assert f.detail["count"] == 2
    assert f.detail["match"] == "maker_exact"


@pytest.mark.parametrize(
    "recall_maker",
    # 실측에서 포함 매칭을 폭발시킨 이름들. 정확 일치는 이것들을 잡지 않는다.
    ["(주)이케아코리아", "이케아재팬주식회사", "코리아이케아", "이케아 재팬 주식회사"],
)
def test_partial_maker_names_are_not_counted(recall_maker):
    """포함 매칭 금지. '코리아' 하나로 303건이 걸리던 것이 이 축의 실패 방식이다."""
    facts = ProductFacts(product_name="어린이 의자", maker="이케아",
                         model_name="LATT-1", category=ItemCategory.CHILDREN_TOY)
    findings, _ = _run(facts, [rec(recall_maker)])
    assert not [x for x in findings if x.kind is FindingKind.MAKER_OTHER_RECALLS]


@pytest.mark.parametrize("maker", ["深圳市特格尔科技有限公司", "-", "ΤΙ-ΤΙΝ", "乐金生活健康贸易（上海）有限公司"])
def test_makers_that_normalise_to_nothing_are_excluded(maker):
    """정규화하면 빈 문자열이 되는 업체명은 후보에서 뺀다.

    사본의 42.7%(15,937건)가 여기 해당한다. 비교에 쓰면 서로 무관한 업체가
    전부 같은 업체가 된다 - 137건 오탐과 같은 모양이다.
    """
    facts = ProductFacts(product_name="목걸이 장신구", maker=maker,
                         model_name="NK-1", category=ItemCategory.CHILDREN_TOY)
    findings, _ = _run(facts, [rec("-"), rec("深圳市特格尔科技有限公司", uid="2")])
    assert not [x for x in findings if x.kind is FindingKind.MAKER_OTHER_RECALLS]


def test_directly_matched_recalls_are_not_double_counted():
    """같은 리콜을 '일치' 와 '같은 제조사' 두 곳에서 세면 건수가 부풀려진다."""
    from sourcing_guard.recall_index import RecallIndex

    idx = FakeIndex([rec("이케아", uid="1"), rec("이케아", uid="2")])
    assert len(idx.by_maker_exact("이케아")) == 2
    assert len(idx.by_maker_exact("이케아", exclude_uids={"1"})) == 1


# ---------------------------------------------------------------------------
# 이 상품의 위험이 아니다
# ---------------------------------------------------------------------------


def test_statement_says_it_does_not_mean_this_product_is_recalled():
    """단서가 없으면 셀러는 이걸 '이 상품이 리콜됐다' 로 읽는다."""
    facts = ProductFacts(product_name="어린이 의자", maker="이케아",
                         model_name="LATT-1", category=ItemCategory.CHILDREN_TOY)
    findings, _ = _run(facts, [rec("이케아")])
    f = next(x for x in findings if x.kind is FindingKind.MAKER_OTHER_RECALLS)
    assert "이 상품이 리콜 대상이라는 뜻은 아닙니다" in f.statement_ko
    assert "참고" in f.statement_ko


def test_it_lands_in_the_context_group():
    facts = ProductFacts(product_name="어린이 의자", maker="이케아",
                         model_name="LATT-1", category=ItemCategory.CHILDREN_TOY)
    findings, result = _run(facts, [rec("이케아")])
    f = next(x for x in findings if x.kind is FindingKind.MAKER_OTHER_RECALLS)
    assert f.group is FindingGroup.CONTEXT
    ctx = next(g for g in result.grouped_findings if g["group"] == "context")
    assert FindingKind.MAKER_OTHER_RECALLS in {x.kind for x in ctx["findings"]}


@pytest.mark.parametrize(
    "kinds,expected",
    [
        ([(FindingKind.KC_VERIFIED, Signal.GREEN), (FindingKind.RECALL_CLEAR, Signal.GREEN)], Signal.GREEN),
        ([(FindingKind.SUBSTANCE_MENTIONED, Signal.AMBER),
          (FindingKind.KC_VERIFIED, Signal.GREEN), (FindingKind.RECALL_CLEAR, Signal.GREEN)], Signal.AMBER),
        ([(FindingKind.RECALL_MATCH, Signal.RED)], Signal.RED),
    ],
)
def test_signal_and_score_are_untouched(kinds, expected):
    """공급처 이력이 이 상품의 신호를 바꾸면 안 된다.

    점수를 깎으면 대형 수입사 상품이 전부 노란불이 되고, 그러면 셀러가
    노란불을 무시한다 - HAZARD_RULE_APPLIES 를 0 으로 둔 것과 같은 논리.
    """
    facts = ProductFacts(product_name="x", maker="이케아", category=ItemCategory.CHILDREN_TOY)
    made = [Finding(kind=k, signal=s, statement_ko="x", source_label="l",
                    source_url="https://www.safetykorea.kr/") for k, s in kinds]
    extra = Finding(kind=FindingKind.MAKER_OTHER_RECALLS, signal=Signal.UNKNOWN,
                    statement_ko="같은 제조사의 다른 리콜이 37건 있습니다. "
                                 "이 상품이 리콜 대상이라는 뜻은 아닙니다.",
                    source_label="l", source_url="https://www.safetykorea.kr/")
    a, b = score(facts, made), score(facts, made + [extra])
    assert a.signal is expected and b.signal is expected
    assert a.score == b.score


def test_no_maker_means_no_finding():
    facts = ProductFacts(product_name="어린이 의자", model_name="LATT-1",
                         category=ItemCategory.CHILDREN_TOY)
    findings, _ = _run(facts, [rec("이케아")])
    assert not [x for x in findings if x.kind is FindingKind.MAKER_OTHER_RECALLS]


def test_category_and_material_axes_are_not_used():
    """품목군·재질 축은 버렸다. 실측에서 수백~수천 건 소음이었다.

    구현이 다시 그 축을 들이지 않게 코드 형태로 고정한다.
    """
    from pathlib import Path

    src = Path("sourcing_guard/recall_index.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    for banned in ("by_category", "by_material", "productItemName", "harmDscr"):
        assert banned not in body, f"버린 축이 되살아났습니다: {banned}"
