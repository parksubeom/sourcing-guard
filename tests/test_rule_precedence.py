"""개별 안전기준이 공통기준을 이긴다.

공통안전기준 3.1.5 는 "개별안전기준이 없는 섬유제품의 경우" 에만 적용된다고
스스로 적고 있다(비고 1). 실제로 부속서 1(유아용 섬유제품)의 폼알데하이드는
20 으로 공통 75 보다 3.75배 엄격하다.

둘을 함께 내보내면 화면에 75 와 20 이 나란히 떠서 셀러가 느슨한 쪽을 읽을 수
있다. "모른다" 가 아니라 "틀렸다" 라 더 나쁘다.
"""

import pathlib
import tempfile

import pytest
import yaml

from sourcing_guard.models import ItemCategory
from sourcing_guard.verifier import RuleBook

_SRC = pathlib.Path("sourcing_guard/data/hazard_rules.yaml")


@pytest.fixture
def promoted() -> RuleBook:
    """부속서 1 을 승격한 상태를 흉내낸다. 실제 승격은 사람이 원문 대조 후에 한다."""
    raw = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    for rule in raw["rules"]:
        if rule["id"].startswith("KC-ANNEX1-"):
            rule["status"] = "verified"
    tmp = pathlib.Path(tempfile.mkdtemp()) / "h.yaml"
    tmp.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return RuleBook(tmp)


def _by_substance(rules):
    return {r.substance: r for r in rules}


def test_annex_formaldehyde_replaces_the_common_one(promoted):
    """20 만 남아야 한다. 75 가 함께 뜨면 셀러가 느슨한 값을 읽는다."""
    rules = promoted.for_category(ItemCategory.CHILDREN_TEXTILE)
    hcho = [r for r in rules if "폼알데하이드" in r.substance]
    assert len(hcho) == 1, f"폼알데하이드 룰이 {len(hcho)}건 - 공통과 부속서가 함께 떴다"
    assert hcho[0].limit_value == 20
    assert hcho[0].id.startswith("KC-ANNEX1")


def test_common_rules_survive_when_annex_is_silent(promoted):
    """부속서가 다루지 않는 물질은 공통기준이 그대로 적용된다.

    용출 8종·니트로사민·석면은 부속서 1 에 없다. 개별기준이 있다고 공통을
    통째로 걷어내면 오히려 커버리지가 준다.
    """
    by = _by_substance(promoted.for_category(ItemCategory.CHILDREN_TEXTILE))
    for substance in ("안티모니", "비소", "셀레늄", "석면"):
        assert substance in by, f"{substance} 가 사라졌다"
        assert by[substance].id.startswith("KC-COMMON-")


def test_annex_adds_substances_the_common_standard_lacks(promoted):
    """부속서에만 있는 6종. 이것이 없으면 유아용 섬유제품을 절반도 못 본다."""
    by = _by_substance(promoted.for_category(ItemCategory.CHILDREN_TEXTILE))
    for substance in ("유기주석화합물 DBT", "유기주석화합물 TBT", "방염제",
                      "알러지성 염료", "니켈 용출량", "노닐페놀"):
        assert substance in by, f"{substance} 가 적용되지 않는다"


def test_other_categories_are_untouched(promoted):
    """부속서 1 은 섬유제품 전용이다. 완구·학용품에 새어 들어가면 안 된다."""
    for cat in (ItemCategory.CHILDREN_TOY, ItemCategory.CHILDREN_STATIONERY):
        rules = promoted.for_category(cat)
        assert all(not r.id.startswith("KC-ANNEX1-") for r in rules)
        # 완구·학용품은 공통 폼알데하이드 75 를 그대로 쓴다
        hcho = [r for r in rules if "폼알데하이드" in r.substance]
        assert not hcho or hcho[0].limit_value == 75


def test_precedence_is_inert_while_annex_is_draft():
    """draft 인 동안에는 아무것도 바뀌지 않는다 - 승격 전까지 화면은 그대로다."""
    rules = RuleBook().for_category(ItemCategory.CHILDREN_TEXTILE)
    hcho = [r for r in rules if "폼알데하이드" in r.substance]
    assert len(hcho) == 1 and hcho[0].limit_value == 75


# --- "부속서가 이긴다" 가 아니라 "엄격한 쪽이 이긴다" ------------------------
def test_stricter_wins_in_both_directions():
    """부속서가 항상 더 엄격한 것은 아니다.

      부속서 1  폼알데하이드 20   vs 공통 75    -> 부속서가 엄격
      부속서 11 pH 4.0~8.0      vs 공통 ~7.5  -> **부속서가 느슨**

    "부속서 우선" 으로 구현하면 두 번째에서 우리가 느슨한 값을 골라주게 된다.
    셀러가 통과시켜야 하는 것은 둘 중 빡빡한 기준이다.
    """
    from sourcing_guard.verifier import RuleBook, _looser_of

    rules = {r.id: r for r in RuleBook().active}
    all_rules = {}
    import yaml
    raw = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}

    # 값 비교: 큰 쪽이 느슨하다
    assert by_id["KC-ANNEX1-TEXTILE-HCHO"]["limit_value"] == 20
    assert by_id["KC-COMMON-3.1.5-HCHO"]["limit_value"] == 75

    # 범위 비교: 상한이 큰 쪽이 느슨하다
    assert by_id["KC-ANNEX11-SCHOOL-PH"]["range_max"] == 8.0
    assert by_id["KC-COMMON-3.1.5-PH"]["range_max"] == 7.5


def test_common_ph_is_textile_only():
    """공통 3.1.5 는 '개별안전기준이 없는 섬유제품' 에만 적용된다고 스스로 적는다.

    그래서 학용품 pH(4.0~8.0)는 경쟁 상대가 없는 유일한 기준이다 - 더 느슨해
    보여도 그것이 그 품목의 기준이다.
    """
    import yaml

    raw = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}
    assert by_id["KC-COMMON-3.1.5-PH"]["applies_to"] == ["children_textile"]


def test_annex11_only_adds_what_differs():
    """부속서 11 은 대부분 공통과 같아서 중복 룰을 만들지 않는다.

    유해원소 용출 8종·총 납 100·총 카드뮴 75 는 공통과 동일하고, 프탈레이트는
    아예 '공통안전기준에 따름' 으로 위임한다. 다른 것만 담는다.
    """
    import yaml

    raw = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    ids = {r["id"] for r in raw["rules"] if r["id"].startswith("KC-ANNEX11-")}
    assert ids == {
        "KC-ANNEX11-SCHOOL-HCHO-INK",
        "KC-ANNEX11-SCHOOL-HCHO-GLUE",
        "KC-ANNEX11-SCHOOL-PH",
    }


# --- 부속서 6 완구: 카테고리 3단 + 공통보다 훨씬 엄격 -----------------------
def test_toy_migration_limits_are_far_stricter_than_common():
    """완구 유해원소는 공통보다 훨씬 엄격하다.

      납    공통 90  vs 완구 카테고리2 3.4   (26배)
      카드뮴 공통 75  vs 완구 카테고리2 0.3   (250배)

    공통 값을 완구에 쓰면 느슨한 기준을 보여주게 된다.
    """
    import yaml

    raw = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}

    pb = by_id["KC-ANNEX6-TOY-MIG-PB"]
    assert pb["limit_value"] == 3.4
    assert pb["category_limits"] == {"category_1": 13.5, "category_2": 3.4, "category_3": 160}
    assert by_id["KC-COMMON-3.1.1-PB"]["limit_value"] == 90


def test_toy_limit_value_uses_the_strictest_category():
    """셀러가 재질을 안 적었을 때 느슨한 값을 보여주면 안 된다.

    limit_value 에는 카테고리 2(가장 엄격)를 둔다. 재질이 확인되면
    category_limits 에서 해당 값을 쓴다.
    """
    import yaml

    raw = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    for rule in raw["rules"]:
        if not rule["id"].startswith("KC-ANNEX6-TOY-MIG-"):
            continue
        limits = rule["category_limits"]
        assert rule["limit_value"] == min(limits.values()), rule["id"]
        assert rule["limit_value"] == limits["category_2"], rule["id"]


def test_toy_element_count_matches_the_decree():
    """원문 [표 4-2] 는 19종이다. 공통기준 8종의 배가 넘는다."""
    import yaml

    raw = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    mig = [r for r in raw["rules"] if r["id"].startswith("KC-ANNEX6-TOY-MIG-")]
    assert len(mig) == 19


def test_nitrosamine_lives_in_part4_not_part12():
    """공통기준과 부속서 11 은 '부속서 6 제12부' 로 인용하는데, 원문은 제4부 4.6 이다.

    인용된 위치와 실제 위치가 다르다는 사실을 기록해 둔다. 값은 같다.
    """
    import yaml

    raw = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}
    nitro = by_id["KC-ANNEX6-TOY-NITROSAMINE"]
    assert "제4부 4.6" in nitro["clause"]
    assert nitro["limit_value"] == 0.05
    assert nitro["variant_limits"]["입에 넣는 36개월 미만용"] == 0.01
