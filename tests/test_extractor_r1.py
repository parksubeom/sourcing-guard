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


def test_llm_failure_degrades_to_heuristic_not_a_500(monkeypatch):
    """남의 API 장애로 우리 서비스를 죽이지 않는다.

    정부 API 에 적용한 원칙과 같다. 투표 기간 18일 동안 추출기 하나 때문에
    스캔 전체가 500 이 되면 안 된다.

    빈 ProductFacts 가 아니라 휴리스틱으로 내려야 한다 - 빈 값이면 페이지에
    인증번호가 적혀 있는데도 "표기 없음"(AMBER)이라고 말하게 된다. 못 찾은
    것과 찾아보지 않은 것은 다르다 (R3).
    """
    import sourcing_guard.extractor as ex

    class Boom:
        def __init__(self, **kw):
            raise RuntimeError("400 anthropic-workspace-id is required")

    import sys
    from dataclasses import replace

    # Settings 는 frozen dataclass 다. 필드를 바꾸지 말고 인스턴스를 갈아끼운다.
    monkeypatch.setattr(
        ex, "settings",
        replace(ex.settings, mock_mode=False, anthropic_api_key="sk-test"),
    )
    monkeypatch.setitem(sys.modules, "anthropic", type("m", (), {"Anthropic": Boom}))

    facts = ex.extract("완구 장난감 KC 인증번호 CB061R2170-3018 재질 PVC")

    assert facts.kc_numbers == ["CB061R2170-3018"], "휴리스틱이 안 돌았습니다"
    assert "PVC" in facts.materials


def test_extraction_path_is_counted_not_inferred():
    """어느 경로로 추출했는지는 세야 한다. 출력 모양으로 추론하면 틀린다.

    처음엔 "키가 설정됐으면 LLM" 으로 판단했다가, 키가 400 을 돌려주는 상태에서
    전부 폴백된 결과를 LLM 정확도로 읽을 뻔했다. 그래서 출력 모양(maker 유무,
    product_name 이 첫 줄과 다른가)으로 바꿨더니 이번엔 11건 중 4건을 오탐했다 -
    LLM 이 정직하게 None 을 내거나 상품명이 마침 첫 줄과 같은 경우다.

    추론을 다른 추론으로 바꾸지 않는다.
    """
    import sourcing_guard.extractor as ex

    ex.stats.reset()
    assert ex.stats.snapshot() == {"llm": 0, "heuristic": 0, "llm_failures": 0}

    ex.extract("완구 장난감 KC CB061R2170-3018", allow_llm=False)
    ex.extract("완구 장난감 KC CB061R2170-3018", allow_llm=False)

    assert ex.stats.snapshot() == {"llm": 0, "heuristic": 2, "llm_failures": 0}
    ex.stats.reset()


def test_llm_failure_is_counted_separately_from_a_deliberate_skip(monkeypatch):
    """호출 실패와 '상한 때문에 안 부름' 은 다른 사건이다.

    전자는 로그를 봐야 할 장애고 후자는 정상 동작이다. 같이 세면 운영자가
    구분할 수 없다.
    """
    import sys
    from dataclasses import replace

    import sourcing_guard.extractor as ex

    class Boom:
        def __init__(self, **kw):
            raise RuntimeError("네트워크 오류")

    ex.stats.reset()
    monkeypatch.setattr(
        ex, "settings",
        replace(ex.settings, mock_mode=False, anthropic_api_key="sk-test"),
    )
    monkeypatch.setitem(sys.modules, "anthropic", type("m", (), {"Anthropic": Boom}))

    ex.extract("완구 장난감")                     # 호출 실패
    ex.extract("완구 장난감", allow_llm=False)     # 의도적 건너뜀

    snap = ex.stats.snapshot()
    assert snap["llm_failures"] == 1
    assert snap["heuristic"] == 2
    ex.stats.reset()
