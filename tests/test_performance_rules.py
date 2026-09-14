"""성능·구조 요건을 담는 방식.

유해물질은 "납 90mg/kg" 처럼 값 하나로 떨어진다. 성능 요건은 아니다 -
부속서 53(운동용 안전모) 원문의 기준이 "가속도계를 무게중심 반경 10mm 이내에
설치하고 6kHz 로 샘플링해 CFC 1000 으로 필터링" 같은 **시험 절차 규격**이라,
값을 보여줘도 셀러가 쓸 수 없다.

그래서 값 대신 어떤 시험을 통과해야 하는지와, 정부 조사에서 이 품목이 어떻게
나왔는지를 담는다. 화면에서 하는 일은 유해물질과 같다 - "이걸 확인하라".
"""

from pathlib import Path

import pytest
import yaml

import sourcing_guard
from sourcing_guard.verifier import HazardRule, RuleBook, _performance_statement

_SRC = Path(sourcing_guard.__file__).parent / "data" / "hazard_rules.yaml"


def _rules() -> list[dict]:
    doc = yaml.safe_load(_SRC.read_text(encoding="utf-8"))
    return doc["rules"] if isinstance(doc, dict) else doc


def test_existing_substance_rules_are_untouched():
    """requirement_type 이 없으면 substance 로 간주한다 - 기존 57건은 그대로다."""
    for rule in _rules():
        if rule["id"].startswith(("KC-COMMON-", "KC-ANNEX")):
            assert rule.get("requirement_type", "substance") == "substance", rule["id"]

    # 활성 룰에 성능 요건이 섞이는 것은 정상이다 - 생활용품 부속서를 승격하면
    # 안전모·레이저가 performance 로 들어온다. 어린이제품 쪽만 불변을 요구한다.
    book = RuleBook()
    for rule in book.active:
        if rule.id.startswith(("KC-COMMON-", "KC-ANNEX")):
            assert rule.requirement_type == "substance", rule.id


def test_performance_rules_carry_no_limit_value():
    """성능 요건에 값을 담으면 안 된다 - 시험 절차 규격이라 셀러가 쓸 수 없다."""
    for rule in _rules():
        if rule.get("requirement_type") != "performance":
            continue
        assert rule["limit_value"] is None, rule["id"]
        assert rule["unit"] is None, rule["id"]


def test_performance_statement_names_the_tests_not_the_numbers():
    rule = HazardRule(
        id="x", substance="승차용 안전모 안전요건", aliases=(), applies_to=("household",),
        limit_value=None, unit=None,
        legal_basis="전기용품 및 생활용품 안전관리법 (안전확인대상생활용품)",
        source_url="u", requirement_type="performance",
        test_items=("충격흡수성", "관통성"),
    )
    text = _performance_statement(rule)
    assert "충격흡수성" in text and "관통성" in text
    assert "시험성적서를 요구하세요" in text


def test_failure_rate_is_shown_with_its_sample():
    """비율만 보여주면 표본 8개짜리가 통계처럼 읽힌다 (기획서 §2.2 에서 겪은 실수)."""
    rule = HazardRule(
        id="x", substance="t", aliases=(), applies_to=("household",),
        limit_value=None, unit=None, legal_basis="전기용품 및 생활용품 안전관리법",
        source_url="u", requirement_type="performance",
        failure_rate={"sample": "10개 중 7개", "source": "국표원 조사 2026-04"},
    )
    text = _performance_statement(rule)
    assert "10개 중 7개" in text
    assert "70%" not in text          # 비율로 환산해 보여주지 않는다
    assert "표적 조사" in text          # 조사 성격을 밝힌다


def test_every_failure_rate_has_sample_and_source():
    """test_failure_rate_honesty 와 같은 계약. 여기서도 지킨다."""
    for rule in _rules():
        rate = rule.get("failure_rate")
        if rate is None:
            continue
        assert rate.get("sample"), rule["id"]
        assert rate.get("source"), rule["id"]


def test_annex_number_implies_a_cited_clause():
    """부속서 번호를 적었으면 조문도 함께 적어야 한다.

    번호를 추측으로 채우면 R5 위반이다. 원문을 실제로 열었다면 몇 절인지도
    알기 마련이므로, 둘을 한 쌍으로 요구해 추측을 걸러낸다.

    ⚠ 원문 확인과 verified 승격은 **다른 단계**다. 원문을 읽어 번호를 채우는
    것은 기계가 하고, 승격은 사람이 원문을 눈으로 대조한 뒤에 한다(R5).
    그래서 annex_no 가 있어도 status 는 draft 일 수 있다.
    """
    for rule in _rules():
        if rule.get("requirement_type") != "performance":
            continue
        if rule.get("annex_no") is None:
            continue
        assert "부속서" in rule["clause"], f"{rule['id']}: 부속서 번호만 있고 조문이 없다"
        assert rule["annex_no"] in rule["clause"], (
            f"{rule['id']}: annex_no({rule['annex_no']})와 clause 가 어긋난다"
        )


# ---------------------------------------------------------------------------
# rule_type — 물질과 요건은 셀러에게 다른 일을 시킨다
# ---------------------------------------------------------------------------


def test_every_rule_declares_its_type():
    """rule_type 이 빠진 룰이 있으면 문장이 조용히 물질 쪽으로 간다.

    substance 필드에 "승차용 안전모 안전요건"·"속눈썹 열 성형기 정격전압" 같은
    비물질이 섞여 있었고, 그걸 "'…정격전압' 기준이 적용됩니다" 로 내보냈다.
    """
    import yaml
    from pathlib import Path

    import sourcing_guard

    path = Path(sourcing_guard.__file__).parent / "data" / "hazard_rules.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = [r["id"] for r in doc["rules"] if "rule_type" not in r]
    assert not missing, missing
    bad = [r["id"] for r in doc["rules"]
           if r["rule_type"] not in ("substance", "requirement")]
    assert not bad, bad

    # 요건 룰 6건 - 안전모·레이저·물놀이·LED·속눈썹 2
    req = {r["id"] for r in doc["rules"] if r["rule_type"] == "requirement"}
    assert req == {
        "KC-LIFE-HELMET-PERF", "KC-LIFE-LASER-PERF", "KC-LIFE-WATERPLAY-PERF",
        "KC-ELEC-LED-PERF", "KC-LIFE-CURLER-VOLT", "KC-LIFE-CURLER-TEMP",
        # 2026-09-07 수집. 부속서 15 는 기준치가 있어도 전부 실물 시험이라
        # 값을 담지 않고 통과해야 할 시험 이름만 담는다.
        "KC-SDOC15-KICKBOARD-PERF",
    }


def test_requirement_says_must_be_within_not_applies():
    """요건은 "충족 여부" 다. "…이하여야 합니다" 로 쓴다.

    물질은 "납 100mg/kg 기준이 적용됩니다" - 초과 가능성이라 시험성적서를
    봐야 안다. 요건은 "정격전압 24V 이하여야 합니다" - 규격표로 확인된다.
    두 문장이 셀러에게 시키는 일이 다르다.
    """
    from unittest.mock import MagicMock

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    facts = ProductFacts(product_name="속눈썹 열 성형기 뷰러",
                         category=ItemCategory.HOUSEHOLD)
    said = [f.statement_ko for f in verify(facts, kats, RuleBook())
            if f.kind.value == "hazard_rule_applies"]
    assert said, "요건 룰이 하나도 안 붙었다"
    volt = next(s for s in said if "정격전압" in s)
    assert "24V(DC) 이하여야 합니다" in volt
    # 원문 문장과 확인방법을 함께 낸다 - 값만으로는 무엇을 어떻게 확인하는지 모른다.
    assert "원문 기준은" in volt
    assert "확인방법:" in volt
    # 물질 문장의 어투를 쓰지 않는다.
    assert "기준이 적용됩니다" not in volt


def test_substance_keeps_the_exceedance_wording():
    """물질은 "적용됩니다" 를 유지한다 - 값을 우리가 확인해 준 것이 아니다."""
    from unittest.mock import MagicMock

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook, verify

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    facts = ProductFacts(product_name="블록", category=ItemCategory.CHILDREN_TOY)
    said = [f.statement_ko for f in verify(facts, kats, RuleBook())
            if f.kind.value == "hazard_rule_applies"]
    lead = next(s for s in said if "납(용출)" in s)
    assert "기준 (90mg/kg)이 적용됩니다" in lead or "기준(90mg/kg)이 적용됩니다" in lead \
        or "공통안전기준 (90mg/kg)이 적용됩니다" in lead
    assert "이하여야 합니다" not in lead


def test_item_scoped_rules_do_not_spill_across_the_category():
    """`scope: item` 룰은 그 품목에만 걸린다.

    ⚠ 이 검사가 없으면 승격 후에 **우산에 마스크 기준이 붙는다.**
      household 는 별표 4~7 의 수백 품목을 담는데 applies_to 가 [household]
      하나뿐이기 때문이다.

    ⚠ rule_type 과 다르다. 부속서 17(마스크)은 rule_type=substance 이면서
      scope=item 이다 - 물질 기준치이지만 마스크에만 걸린다. 처음에 둘을
      하나로 묶었다가 모든 household 상품에 마스크 기준을 붙일 뻔했다.

    ⚠ KC-ANNEX 의 aliases 는 **물질 표기 변형**이다('formaldehyde'·'알루미늄').
      품목 판별에 쓸 수 없으므로 scope=category 여야 한다 - 잘못 item 으로
      두면 완구 부속서 25건이 통째로 죽는다.
    """
    import pathlib
    import tempfile

    import yaml

    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook

    src = pathlib.Path("sourcing_guard/data/hazard_rules.yaml")
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    assert all("scope" in r for r in raw["rules"]), [
        r["id"] for r in raw["rules"] if "scope" not in r
    ]
    bad = [r["id"] for r in raw["rules"] if r["scope"] not in ("category", "item")]
    assert not bad, bad

    # 물질 별칭을 가진 룰은 category 여야 한다.
    for rule in raw["rules"]:
        if rule["id"].startswith(("KC-COMMON-", "KC-ANNEX")):
            assert rule["scope"] == "category", rule["id"]
        if rule["id"].startswith(("KC-LIFE-", "KC-ELEC-", "KC-SDOC")):
            assert rule["scope"] == "item", rule["id"]

    # 전부 승격했다고 가정하고 번짐을 본다.
    for r in raw["rules"]:
        r["status"] = "verified"
    tmp = pathlib.Path(tempfile.mkstemp(suffix=".yaml")[1])
    tmp.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    book = RuleBook(tmp)

    def ids(name: str, cat: ItemCategory) -> set[str]:
        facts = ProductFacts(product_name=name, category=cat)
        return {r.id for r in book.applying_to(facts)}

    mask = ids("멀티스카프 자전거마스크 넥워머", ItemCategory.HOUSEHOLD)
    assert mask and all(i.startswith("KC-SDOC17") for i in mask), mask
    # 같은 품목군의 다른 품목에는 안 붙는다.
    assert ids("우산 양산 자동우산", ItemCategory.HOUSEHOLD) == set()
    assert ids("치즈욕실화 EVA 슬리퍼 실내화", ItemCategory.HOUSEHOLD) == set()
    assert ids("수납가구 서랍장", ItemCategory.HOUSEHOLD) == set()

    # 공통안전기준과 품목 부속서는 함께 붙는다 - 품목군 = 품목인 경우다.
    toy = ids("블록", ItemCategory.CHILDREN_TOY)
    assert any(i.startswith("KC-COMMON-") for i in toy)
    assert any(i.startswith("KC-ANNEX6") for i in toy)


# ---------------------------------------------------------------------------
# 문장이 **화면까지 살아서 가는가** (2026-09-14)
#
# ⚠⚠ 이 파일의 다른 검사는 `_performance_statement` 를 **직접 불러서** 봤다.
#   그래서 `verify()` 가 그 문장을 만들어 놓고 아래 공통 블록으로 **덮어쓰는**
#   것을 아무도 못 봤다. 단위 검사가 통과하는데 화면은 다른 문장을 받는 자리다.
#   부르는 쪽을 지나가는 검사가 없으면 죽은 코드가 살아남는다.
# ---------------------------------------------------------------------------


def _hazard_findings(legal_name: str):
    """목 모드 휴리스틱으로는 category 가 안 잡혀 룰이 안 걸린다.

    그래서 `facts` 를 직접 만들어 `verify()` 를 부른다 - 재는 것은 추출이
    아니라 **verifier 의 분기**다.
    """
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import verify

    facts = ProductFacts(product_name=legal_name,
                         category=ItemCategory.HOUSEHOLD,
                         legal_item_name=legal_name)
    kats = KatsClient(base_url="http://mock.invalid", service_key="x")
    return [f for f in verify(facts, kats, RuleBook())
            if f.kind.value == "hazard_rule_applies"]


@pytest.mark.parametrize(
    "legal_name, rule_id, tests, sample",
    [
        ("승차용 안전모", "KC-LIFE-HELMET-PERF",
         ("충격 흡수", "유지 시스템 강도", "내관통"), "10개 중 7개"),
        ("휴대용 레이저용품", "KC-LIFE-LASER-PERF",
         ("겉모양", "구조", "레이저의 등급"), "10개 중 8개"),
    ],
)
def test_performance_statement_survives_to_the_finding(legal_name, rule_id, tests, sample):
    """verified 성능 룰 2건이 **시험 이름과 부적합률을 달고** 나온다."""
    found = [f for f in _hazard_findings(legal_name)
             if (f.detail or {}).get("rule_id") == rule_id]
    assert len(found) == 1, [f.detail for f in _hazard_findings(legal_name)]
    f = found[0]
    for name in tests:
        assert name in f.statement_ko, (name, f.statement_ko)
    assert sample in f.statement_ko, f.statement_ko
    # 비율만 쓰지 않고 표본을 함께 낸다 - "88%" 만 적으면 표본 8개짜리 수치가
    # 통계처럼 읽힌다 (기획서 §2.2 에서 한 번 틀렸던 실수다).
    assert f.detail["failure_rate"]["sample"] == sample
    assert f.detail["test_items"] == list(tests)
    assert f.detail["requirement_type"] == "performance"


def test_performance_rules_never_fall_through_to_the_common_sentence():
    """공통 물질 문장이 성능 룰을 덮지 않는다.

    덮였을 때 나오던 문장을 그대로 적어 둔다 - 다시 나오면 이 검사가 잡는다.
    """
    for legal_name in ("승차용 안전모", "휴대용 레이저용품"):
        for f in _hazard_findings(legal_name):
            if (f.detail or {}).get("requirement_type") != "performance":
                continue
            assert "기준이 적용됩니다" not in f.statement_ko, f.statement_ko
            assert "공통안전기준" not in f.statement_ko, f.statement_ko
    # 되살리기 전 실측 문장. 리포 어디에도 코드로 남아 있으면 안 된다.
    stale = "'승차용 안전모 안전요건' 기준이 적용됩니다"
    src = (Path(sourcing_guard.__file__).parent / "verifier.py").read_text(encoding="utf-8")
    assert stale not in src


def test_requirement_rules_still_say_must_be_within():
    """세 갈래로 바로 세우면서 `requirement` 가지를 깨지 않았는지 함께 잰다."""
    found = _hazard_findings("속눈썹 열 성형기")
    assert len(found) == 2, [f.detail for f in found]
    for f in found:
        assert "이하여야 합니다" in f.statement_ko, f.statement_ko
        assert f.detail["rule_type"] == "requirement"
        assert "requirement_type" not in f.detail


def test_no_unreachable_append_after_continue():
    """`continue` 뒤에 놓인 도달 불가 블록이 다시 생기지 않게 한다.

    같은 코드를 두 곳에 두면 한쪽만 고쳐도 나머지가 거짓말을 계속한다 (§6).
    """
    import ast

    src = (Path(sourcing_guard.__file__).parent / "verifier.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    dead: list[int] = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for i, stmt in enumerate(body[:-1]):
            if isinstance(stmt, (ast.Continue, ast.Break, ast.Return, ast.Raise)):
                dead.append(body[i + 1].lineno)
    assert dead == [], f"도달할 수 없는 줄: {dead}"
