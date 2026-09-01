"""추출기가 R1(판정 금지)을 지키는지 검증.

프롬프트에 "판단하지 마라" 를 적는 것과 그게 지켜지는 것은 다르다. LLM 응답을
직접 부를 수 없으므로(키·비용), 여기서는 구조적 방어를 검증한다:

1. 프롬프트 자체가 판정 금지를 명시하는가 (프롬프트 회귀 방지)
2. few-shot 예시에 판정 필드가 새어 있지 않은가
3. 모델이 판정 필드를 넣어 보내도 스키마가 그것을 버리는가
"""

import json

from sourcing_guard.extractor import _EXAMPLES, SYSTEM_PROMPT, _heuristic_fallback
from sourcing_guard.models import ProductFacts

_VERDICT_FIELDS = {
    "risk", "risk_level", "safe", "is_safe", "verdict", "signal", "score",
    "recommendation", "warning", "compliant", "legal", "safety",
}


def test_prompt_forbids_judgement():
    for phrase in ("판단하지 않습니다", "사실만", "역할의 경계"):
        assert phrase in SYSTEM_PROMPT, f"프롬프트에서 '{phrase}' 가 사라졌습니다"


def test_few_shot_answers_carry_no_verdict():
    for _, answer in _EXAMPLES:
        leaked = _VERDICT_FIELDS & set(answer)
        assert not leaked, f"few-shot 예시에 판정 필드 유출: {leaked}"


def test_few_shot_answers_match_the_schema():
    for _, answer in _EXAMPLES:
        ProductFacts(**answer)


def test_recalled_product_example_stays_factual():
    """리콜된 완구 예시가 사실만 담는지 — 판정 유혹이 가장 큰 케이스다."""
    _, answer = _EXAMPLES[0]
    assert "CB067R317-5002" in answer["kc_numbers"]
    assert answer["category"] == "children_toy"
    blob = json.dumps(answer, ensure_ascii=False)
    for word in ("위험", "리콜", "주의", "불법", "안전하지"):
        assert word not in blob, f"판정성 단어 '{word}' 가 예시에 있습니다"


def test_schema_drops_a_hallucinated_verdict_field():
    """모델이 risk_level 을 넣어 보내도 추출이 통째로 실패하지 않고 그것만 버린다."""
    model_output = {
        "product_name": "완구", "materials": ["PVC"],
        "kc_numbers": ["CB067R317-5002"], "category": "children_toy",
        "risk_level": "high", "recommendation": "구매 금지",
    }
    allowed = set(ProductFacts.model_fields) - {"source_page_url"}
    cleaned = {k: v for k, v in model_output.items() if k in allowed}
    facts = ProductFacts(**cleaned)
    assert facts.materials == ["PVC"]
    assert not (_VERDICT_FIELDS & set(facts.model_dump()))


def test_heuristic_fallback_also_emits_no_verdict():
    facts = _heuristic_fallback("완구 인형 KC CB061R2170-3018", None)
    assert not (_VERDICT_FIELDS & set(facts.model_dump()))
