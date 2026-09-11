"""생활용품도 인증 경로에 넣는다 - 다만 등급을 알아냈을 때만.

등급표 561건 중 140건이 생활용품인데 _CERT_REQUIRED 에 없어서, 우산·의자
셀러는 등급 finding 조차 못 받고 리콜 대조만 받았다. 표를 만들고 절반을
안 쓰는 셈이었다.

⚠ 그냥 넣으면 안 된다. 전기용품은 3등급 중 둘이 번호 필수라 "규제 품목군인데
  번호가 없다" 가 그 자체로 의미 있는 경고지만, 생활용품은 4등급이고
  안전기준준수(번호 없음이 정상)가 많다. 등급을 모르는 채로 경고하면
  대부분 틀린 경고가 된다 - 우산에 "인증번호가 없습니다" 라고 하는 것과 같다.
"""

from __future__ import annotations

import pytest

from sourcing_guard.recall_index import RecallIndex
from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts
from sourcing_guard.verifier import (
    _CERT_REQUIRED,
    _CERT_REQUIRED_IF_GRADED,
    RuleBook,
    verify,
)


class NoRecalls:
    # ⚠ 대조 가능 여부는 **진짜 로직을 빌린다** (4-r). 여기서 따로 적으면
    #   조건이 또 갈리고, 그 갈림이 이 결함의 원인이었다.
    can_compare = RecallIndex.can_compare
    as_of = "20260903"

    def is_empty(self):
        return False

    def find(self, facts, *, today=None):
        return []

    def by_maker_exact(self, maker, *, exclude_uids=None):
        return []


def kinds(name: str, category: ItemCategory) -> set[str]:
    facts = ProductFacts(product_name=name, category=category)
    found = verify(facts, KatsClient(None, None, mock=True), RuleBook(), NoRecalls())
    return {f.kind.value for f in found}


CERT_KINDS = {
    "kc_missing_but_required",
    "kc_absence_expected",
    "kc_tier_unknown",
    "item_grade_matched",
    "item_grade_split",
}


# ---------------------------------------------------------------------------
# 등급을 알아낸 생활용품은 정확한 답을 받는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "우산 양산 양우산 자동우산 3단자동우산 골프우산 암막우산",
        "한리빙 미니빨래건조대 4종 양말 수건 심플 건조대",
    ],
)
def test_graded_household_gets_the_absence_is_normal_answer(name):
    """우산은 안전기준준수 대상이다. 인증·신고 절차 자체가 없다.

    "인증번호가 없습니다" 가 틀리고, "절차 자체가 없어 조회 DB 에 번호가
    없는 것이 정상" 이 맞다.
    """
    got = kinds(name, ItemCategory.HOUSEHOLD)
    assert "kc_absence_expected" in got
    assert "item_grade_matched" in got
    # 틀린 경고를 하지 않는다.
    assert "kc_missing_but_required" not in got
    assert "kc_tier_unknown" not in got


# ---------------------------------------------------------------------------
# 등급을 못 찾은 생활용품에는 아무 말도 하지 않는다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        # '의자' 는 식별력이 없어 포함 키에서 뺐다(의자방석이 의자로 붙는다).
        # 그래서 등급 미매칭이고, 이때 경고하면 틀린 경고가 된다.
                # 예초기 안전모는 표의 안전모(자전거·등산·승차·스키용)가 아니다.
        "고급형 레드 예초기 보호 헬맷 안전모",
        # 휴지통은 부속서 5 가구 적용범위에서 명시 제외된다.
        "슬림 휴지통 20L 분리수거함",
    ],
)
def test_ungraded_household_says_nothing_about_certification(name):
    """등급을 못 찾은 생활용품에는 인증 이야기를 꺼내지 않는다.

    2026-09-03 갱신: 캠핑 의자를 표본에서 뺐다. '의자' 를 경쟁 규칙(_RIVAL_ITEMS)
    으로 열면서 등급이 붙었기 때문이고, 붙은 뒤에는 "안전기준준수라 인증 절차가
    없다" 를 말하는 것이 맞다. 낡은 위치, 살아있는 의도다.
    """
    got = kinds(name, ItemCategory.HOUSEHOLD)
    assert not (got & CERT_KINDS), got


# ---------------------------------------------------------------------------
# 전기용품은 등급을 못 찾아도 경고한다 - 구분이 유지되어야 한다
# ---------------------------------------------------------------------------


def test_electrical_still_warns_without_a_grade():
    """전기용품 3등급 중 둘이 번호 필수라 부재 자체가 의미 있는 경고다.

    생활용품과 달리 등급을 몰라도 "규제 품목군인데 번호가 없다" 를 말한다.
    이 구분이 사라지면 전기용품 경고가 통째로 없어진다.
    """
    got = kinds("모델명 XY-100 제조사 미상", ItemCategory.ELECTRICAL)
    assert "kc_missing_but_required" in got
    assert "kc_tier_unknown" in got


def test_the_two_sets_stay_disjoint():
    """생활용품이 두 집합에 다 들어가면 조건부 진입이 무력화된다."""
    assert not (_CERT_REQUIRED & _CERT_REQUIRED_IF_GRADED)
    assert ItemCategory.HOUSEHOLD in _CERT_REQUIRED_IF_GRADED
    assert ItemCategory.ELECTRICAL in _CERT_REQUIRED


# --- 승격했다고 커버리지를 선언하지는 않는다 -------------------------------
def test_household_coverage_is_decided_per_product_not_per_category():
    """생활용품 룰 4건은 승차용 안전모·레이저·속눈썹기 세 품목뿐이다.

    ⚠ 예전에는 이 검사가 "coverage 에 household 를 넣지 않는다" 를 잠갔다.
      선언에 넣으면 우산·가구·섬유에도 COVERAGE_GAP 이 사라져 "이 품목군을 다
      봤다" 는 잘못된 안심이 되기 때문이었다. 그런데 넣지 않으면 verified 룰
      4건이 아예 안 쓰였다 - 두 방향으로 틀린 상태였다.

    2026-09-07 에 **단위를 품목으로 좁혔다.** covers() 는 선언을 보지 않고
    "이 상품에 적용되는 verified 룰이 있는가" 를 본다.
    """
    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook

    book = RuleBook()

    def covers(name: str, cat: ItemCategory = ItemCategory.HOUSEHOLD) -> bool:
        return book.covers(ProductFacts(product_name=name, category=cat))

    # 룰이 있는 품목은 커버된다 - 4건이 이제 실제로 쓰인다.
    assert covers("승차용 안전모 오토바이 헬멧")
    assert covers("속눈썹 열 성형기 뷰러")

    # 룰이 없는 품목은 회색으로 남는다. 그게 맞다 (R3).
    assert not covers("우산 양산 자동우산")
    assert not covers("수납가구 서랍장")
    assert not covers("전기주전자 1.8L", ItemCategory.ELECTRICAL)

    # 공통안전기준은 품목을 가리지 않는다 - 스스로 공통 적용이라 적는다.
    assert covers("블록", ItemCategory.CHILDREN_TOY)


def test_coverage_declaration_matches_reality():
    """coverage.categories 는 서술용이다. 실제와 어긋나면 조용히 오해를 남긴다.

    게이트에는 쓰지 않지만, 어긋난 채 두면 다음 사람이 "household 는 미수록"
    으로 읽는다. verified 룰이 있는 품목군과 같은지 잠근다.
    """
    import yaml
    from pathlib import Path

    import sourcing_guard

    path = Path(sourcing_guard.__file__).parent / "data" / "hazard_rules.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    declared = set(doc["coverage"]["categories"])
    actual = {
        c for r in doc["rules"] if r.get("status") == "verified"
        for c in r.get("applies_to", [])
    }
    assert declared == actual, (sorted(declared), sorted(actual))


def test_promoted_household_rules_name_the_annex_they_came_from():
    """승격한 생활용품 규칙은 어느 부속서 몇 절을 대조했는지 남겨야 한다."""
    import yaml
    from pathlib import Path

    import sourcing_guard

    path = Path(sourcing_guard.__file__).parent / "data" / "hazard_rules.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    promoted = [
        r for r in doc["rules"]
        if r["id"].startswith("KC-LIFE-") and r["status"] == "verified"
    ]
    assert len(promoted) == 4
    for rule in promoted:
        assert rule["annex_no"], rule["id"]
        assert rule["verified_source"], rule["id"]
        assert rule["verified_by"] == "박수범", rule["id"]
