"""[H] 도매꾹 구조 필드 어댑터 — LLM 0회 · 값 아닌 값은 None · 고시 분류를 품목으로 옮기지 않음."""
from __future__ import annotations

import inspect
from pathlib import Path

from sourcing_guard import domeggook_adapter as ad
from sourcing_guard.models import ItemCategory


def _item(**over):
    base = {
        "basis": {"no": 1, "title": "유아용 블록 완구 100pcs"},
        "detail": {
            "model": "BLK-100", "manufacturer": "테스트상사", "country": "국산",
            "safetyCert": [
                {"cert": "Y", "useNo": "Y", "no": "CB061R2170-3018", "certType": "어린이제품"},
                {"cert": "Y", "useNo": "N", "no": "XX000000-0000"},        # 번호 미사용 → 무시
                {"cert": "N", "useNo": "Y", "no": "-"},                    # 미인증 → 무시
                {"cert": "Y", "useNo": "Y", "no": "-"},                    # 값 아님 → 무시
            ],
            "infoDuty": {"type": "어린이제품", "item": [
                {"name": "품명 및 모델명", "desc": "블록 완구 / BLK-100"},
                {"name": "재질", "desc": "ABS / 상세설명참조"},
                {"name": "사용연령 또는 권장사용연령", "desc": "3세 이상"},
                {"name": "KC 인증정보", "desc": "안전확인 CB061R2170-3018 · 추가 CB061R2170-3019"},
            ]},
        },
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k].update(v)
        else:
            base[k] = v
    return base


def test_maps_structured_fields_without_an_llm():
    f = ad.facts_from_item(_item())
    assert f.product_name == "유아용 블록 완구 100pcs"
    assert f.model_name == "BLK-100" and f.maker == "테스트상사"
    assert f.materials == ["ABS"]                         # placeholder 조각은 빠진다
    assert f.target_age == "3세 이상"
    # safetyCert 필터(cert=Y·useNo=Y·값) + 고시 desc 의 번호 모양, 중복 제거
    assert f.kc_numbers == ["CB061R2170-3018", "CB061R2170-3019"]


def test_not_a_value_strings_become_none():
    """⚠ 실측 `model="해당없음"` 71/190. `is_placeholder` 는 이걸 모른다."""
    f = ad.facts_from_item(_item(detail={"model": "해당없음", "manufacturer": "상세설명참조",
                                          "infoDuty": {"type": "기타 재화", "item": []}}))
    assert f.model_name is None and f.maker is None
    for bad in ("해당없음", "해당 없음", "없음", "미기재", "-", "상세설명참조", "상세페이지", "상세설명", "", None):
        assert ad.clean(bad) is None, bad
    assert ad.clean("K2018") == "K2018"


def test_model_falls_back_to_the_notice_row_when_detail_model_is_empty():
    f = ad.facts_from_item(_item(detail={"model": "해당없음"}))
    assert f.model_name == "BLK-100"                      # "품명 / 모델명" 의 뒤쪽 조각
    f2 = ad.facts_from_item(_item(detail={"model": "-", "infoDuty": {"type": "x", "item": [
        {"name": "품명 및 모델명", "desc": "상세설명참조 / 상세설명참조"}]}}))
    assert f2.model_name is None                          # 양쪽이 placeholder 면 값이 없다


def test_the_notice_category_is_never_mapped_to_a_legal_item_name():
    """⚠⚠ 고시 품목분류 ≠ 전안법 품목군. 실측 겹침 3/190. 옮기면 없는 의무를 만든다."""
    for t in ("의류", "기타 재화", "가정용 전기제품(냉장고/세탁기/식기세척기/전자레인지 등)"):
        f = ad.facts_from_item(_item(detail={"infoDuty": {"type": t, "item": []}}))
        assert f.legal_item_name is None
        assert f.category is ItemCategory.UNCLASSIFIED
    assert ad.infoduty_type(_item()) == "어린이제품"


def test_only_observed_row_names_are_read():
    """이름은 고시가 정한다 - 관찰된 정확한 이름만 (R5). 비슷한 이름은 읽지 않는다."""
    f = ad.facts_from_item(_item(detail={"model": "-", "manufacturer": "-", "infoDuty": {"type": "x", "item": [
        {"name": "소재", "desc": "PVC"},                 # '재질' 이 아니다
        {"name": "권장연령", "desc": "3세"},             # 관찰된 이름이 아니다
        {"name": "제조자", "desc": "관찰된 이름"},       # 이건 읽는다
    ]}}))
    assert f.materials == [] and f.target_age is None and f.maker == "관찰된 이름"


def test_adapter_has_no_llm_and_no_network():
    src = inspect.getsource(ad)
    for banned in ("extractor", "anthropic", "openai", "httpx", "requests"):
        assert banned not in src, banned
    # 판정 필드를 만들지 않는다 (R1) - ProductFacts 가 extra=forbid 라 만들 수도 없다.
    assert "verdict" not in src and "is_safe" not in src


def test_measure_script_uses_no_llm():
    src = (Path(__file__).resolve().parents[1] / "scripts/measure_h_adapter.py").read_text(encoding="utf-8")
    assert "extract" not in src.replace("extractor 없어도", "") or "LLM 0회" in src
    assert "httpx" not in src and "LLM 0회" in src and "검수 없음" in src
