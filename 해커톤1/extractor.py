"""Stage 1 — LLM extraction ONLY.

CLAUDE.md R1: this prompt must never ask whether the product is safe, legal or
risky. It asks what the page says. Judgement happens in scorer.py.
"""

from __future__ import annotations

import json

from .config import settings
from .models import ItemCategory, ProductFacts

SYSTEM_PROMPT = """\
당신은 이커머스 상품 상세페이지에서 사실만 추출하는 파서입니다.

규칙:
- 페이지에 명시적으로 적힌 내용만 추출합니다. 추론하거나 보충하지 않습니다.
- 안전성, 위법성, 위험도를 판단하지 않습니다. 그것은 당신의 역할이 아닙니다.
- 값이 없으면 null 또는 빈 배열로 둡니다. 그럴듯한 값을 지어내지 않습니다.
- 한국어/중국어/영어가 섞여 있을 수 있습니다. 원문 표기를 보존하되 재질명은 한국어로 정규화합니다.
- category 는 다음 중 하나입니다:
  children_toy, children_stationery, children_textile, electrical, household, unclassified
  확신이 없으면 unclassified 를 쓰고 category_confidence 를 낮게 줍니다.

출력은 JSON 객체 하나만. 코드블록 표시나 설명 문장을 붙이지 마세요.
스키마:
{"product_name":str|null,"model_name":str|null,"maker":str|null,
 "materials":[str],"substances_mentioned":[str],"kc_numbers":[str],
 "target_age":str|null,"category":str,"category_confidence":float,
 "raw_language":"ko"|"zh"|"en"|"mixed"|"unknown"}
"""


def extract(page_text: str, page_url: str | None = None) -> ProductFacts:
    if settings.mock_mode or not settings.anthropic_api_key:
        return _heuristic_fallback(page_text, page_url)

    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(
        model=settings.extractor_model,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": page_text[:60_000]}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # R3: a parse failure is not a safe product. Degrade to unknown.
        return ProductFacts(source_page_url=page_url)

    data.pop("source_page_url", None)
    try:
        return ProductFacts(**data, source_page_url=page_url)
    except Exception:
        return ProductFacts(source_page_url=page_url)


def _heuristic_fallback(text: str, url: str | None) -> ProductFacts:
    """Offline stand-in so the pipeline is runnable without an API key.

    Deliberately dumb. It exists for wiring and tests, not for accuracy.
    """
    import re

    kc = re.findall(r"[A-Z]{2}\d{6,}|\bKC[- ]?\d{5,}", text.upper())
    m = re.search(r"(?:모델명|모델|型号|model)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_]{2,})", text, re.I)
    cat = ItemCategory.UNCLASSIFIED
    if any(w in text for w in ("완구", "장난감", "블록", "toy")):
        cat = ItemCategory.CHILDREN_TOY
    elif any(w in text for w in ("학용품", "크레파스", "필통")):
        cat = ItemCategory.CHILDREN_STATIONERY
    return ProductFacts(
        product_name=text.strip().splitlines()[0][:80] if text.strip() else None,
        model_name=m.group(1) if m else None,
        materials=[m for m in ("PVC", "PP", "TPE", "ABS") if m in text.upper()],
        kc_numbers=list(dict.fromkeys(kc)),
        category=cat,
        category_confidence=0.3 if cat is not ItemCategory.UNCLASSIFIED else 0.0,
        source_page_url=url,
    )
