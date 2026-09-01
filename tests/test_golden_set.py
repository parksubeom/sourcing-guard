"""골든셋 회귀 테스트.

실제 도매·구매대행 상세페이지 11건에서 뽑은 판정 정답을 고정한다. 11건 전부
KC 인증번호가 없다 — 구매대행 소싱 상품은 인증정보가 없는 것이 정상이고,
우리 서비스의 본체는 그럴 때 무엇을 확인해야 하는지 답하는 것이다.

이 테스트는 리콜 인덱스 없이 돈다(추출·분류·범위 판정은 리콜과 독립적이다).
리콜 매칭 자체는 test_recall_index / test_watchlist 가 따로 검증한다.
"""

from pathlib import Path

import yaml

from sourcing_guard.extractor import extract
from sourcing_guard.kats_client import KatsClient
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify

_GOLDEN = yaml.safe_load(
    (Path(__file__).parent / "golden" / "golden_set.yaml").read_text(encoding="utf-8")
)["cases"]
_KATS = KatsClient(None, None, mock=True)
_RULES = RuleBook()


def _run(text: str):
    facts = extract(text)
    findings = verify(facts, _KATS, _RULES, None)
    return facts, findings, score(facts, findings)


def _ids():
    return [c["id"] for c in _GOLDEN]


import pytest  # noqa: E402


@pytest.mark.parametrize("case", _GOLDEN, ids=_ids())
def test_golden_case(case):
    facts, findings, result = _run(case["text"])
    kinds = {f.kind.value for f in findings}
    exp = case["expect"]

    if "signal" in exp:
        # Signal enum 은 대문자('UNKNOWN'), 골든셋은 소문자로 읽기 쉽게 적는다.
        assert result.signal.value.lower() == exp["signal"].lower(), (
            f"{case['id']}: 신호 기대 {exp['signal']}, 실제 {result.signal.value}"
        )

    if "category" in exp:
        assert facts.category.value == exp["category"], (
            f"{case['id']}: 품목 기대 {exp['category']}, 실제 {facts.category.value}"
        )

    for kind in exp.get("must_find", []):
        assert kind in kinds, f"{case['id']}: finding '{kind}' 없음. 실제: {sorted(kinds)}"

    for token in exp.get("must_extract", []):
        haystack = " ".join(facts.materials + facts.substances_mentioned + facts.kc_numbers)
        assert token in haystack, (
            f"{case['id']}: '{token}' 추출 실패. materials={facts.materials}"
        )


def test_all_eleven_samples_lack_kc_number():
    """11건 전부 KC 번호가 없다는 것 자체가 시장 사실이다.

    이 전제가 깨지면(표본이 바뀌면) 골든셋의 성격이 달라진 것이므로 알린다.
    """
    without = [c["id"] for c in _GOLDEN if not extract(c["text"]).kc_numbers]
    assert len(without) == len(_GOLDEN), (
        f"KC 번호가 있는 표본이 생겼습니다: {set(_ids()) - set(without)}. "
        "골든셋 성격이 바뀌었으니 정답을 재검토하세요."
    )


def test_out_of_scope_items_short_circuit_to_a_single_finding():
    """식품·화장품은 '판별 못 함' 이 아니라 '소관 아님' 이다.

    OUT_OF_SCOPE 는 나머지 검증을 건너뛰고 단일 finding 으로 끝나야 한다 —
    화장품에 '재질 확인 요청' 을 붙이면 엉뚱하다.
    """
    for cid in ("cleansing-foam", "skinfoou-ampoule", "bamboo-salt-set"):
        case = next(c for c in _GOLDEN if c["id"] == cid)
        _, findings, _ = _run(case["text"])
        assert [f.kind.value for f in findings] == ["out_of_scope"], cid


def test_bear_keyring_is_not_forced_into_toy_category():
    """인형 붙은 키링을 완구로 단정하면 품목 오판정이다 (R1).

    액세서리이므로 완구 기준(프탈레이트·납)을 자동으로 들이대지 않는다.
    """
    case = next(c for c in _GOLDEN if c["id"] == "bear-keyring")
    facts, _, _ = _run(case["text"])
    assert facts.category.value != "children_toy"
