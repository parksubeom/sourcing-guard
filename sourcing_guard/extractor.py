"""Stage 1 — LLM extraction ONLY.

CLAUDE.md R1: this prompt must never ask whether the product is safe, legal or
risky. It asks what the page says. Judgement happens in scorer.py.
"""

from __future__ import annotations

import json
import logging

from .config import settings
from .kats_client import CERT_NUMBER_RE
from .models import ItemCategory, ProductFacts

_log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 이커머스 상품 상세페이지에서 **사실만** 추출하는 파서입니다.
판정 엔진이 따로 있으므로, 당신은 절대 판단하지 않습니다.

# 역할의 경계 (가장 중요)
- 안전한지, 위법한지, 위험한지, 리콜 대상인지 **판단하지 않습니다.**
- "확인이 필요하다", "주의" 같은 권고도 하지 않습니다. 사실만 옮깁니다.
- 인증번호가 유효한지 조회하지 않습니다. 페이지에 적힌 문자열만 그대로 뽑습니다.
- 이 제품이 어린이용인지 당신이 결정하지 않습니다. 페이지에 적힌 대상연령 표기만 옮깁니다.

# 추출 규칙
- 페이지에 **명시적으로 적힌** 내용만 추출합니다. 추론·보충·상식 적용을 하지 않습니다.
- 값이 없으면 null 또는 빈 배열로 둡니다. 그럴듯한 값을 지어내지 않습니다.
- 한국어·중국어·영어가 섞일 수 있습니다. 원문 표기를 보존하되, 재질명은 한국어나
  통용 약어로 정규화합니다 (예: "环保PP材质" → "PP").
- product_name: "상품명/품명/제품명" 으로 표시된 값만. 페이지 첫 줄이나 광고 문구가
  아닙니다. 없으면 가장 근접한 제목 한 줄만, 80자 이내로.
- materials: 재질·소재로 표시된 것. "ABS+PC" 는 ["ABS","PC"] 로 나눕니다.
- substances_mentioned: 본문에 실제로 언급된 규제/화학 물질이나 소관을 가르는 표지.
  예: PVC, 프탈레이트, 납, 화장품책임판매업자, EWG, 죽염. 재질과 겹쳐도 됩니다.
- kc_numbers: 인증번호 형식 문자열만. 예: CB061R2170-3018, B363R871-5002.
  "해당사항 없음"·"비대상" 같은 자리표시자는 인증번호가 아니므로 넣지 않습니다.
- target_age: "사용연령/권장연령/대상연령" 표기를 원문 그대로. 예: "만 14세 이상".
  없으면 null. **당신이 나이를 추정하지 않습니다.**
- category 는 다음 중 하나입니다:
  children_toy, children_stationery, children_textile, electrical, household,
  out_of_scope, unclassified
  · out_of_scope: 식품·화장품·의약품·의료기기·식품용기 등 어린이제품 안전기준 소관 밖.
  · 인형·캐릭터가 붙어도 주된 용도가 완구가 아니면(키링·파우치 등) 완구로 분류하지 않습니다.
  · 확신이 없으면 unclassified 를 쓰고 category_confidence 를 낮게 줍니다.

출력은 JSON 객체 **하나만**. 코드블록 표시나 설명 문장을 붙이지 마세요.
스키마:
{"product_name":str|null,"model_name":str|null,"maker":str|null,
 "materials":[str],"substances_mentioned":[str],"kc_numbers":[str],
 "target_age":str|null,"category":str,"category_confidence":float,
 "raw_language":"ko"|"zh"|"en"|"mixed"|"unknown"}
"""

# Few-shot. The recalled train toy is deliberate: the model must extract facts
# from a genuinely unsafe product WITHOUT flagging it. If the model adds a
# verdict here, the prompt has failed.
_EXAMPLES: list[tuple[str, dict]] = [
    (
        "상품명: 모형완구 기차놀이 제우스\n재질: ABS, PVC\n"
        "인증번호: CB067R317-5002 [어린이제품] 안전확인\n대상연령: 3세 이상\n제조국: 중국",
        {
            "product_name": "모형완구 기차놀이 제우스", "model_name": None, "maker": None,
            "materials": ["ABS", "PVC"], "substances_mentioned": ["PVC"],
            "kc_numbers": ["CB067R317-5002"], "target_age": "3세 이상",
            "category": "children_toy", "category_confidence": 0.9, "raw_language": "ko",
        },
    ),
    (
        "제품명: 약산성 클렌징폼\n용량: 40ml\n"
        "화장품책임판매업자: 에스앤비코리아\nEWG 그린등급\n제조국: 대한민국",
        {
            "product_name": "약산성 클렌징폼", "model_name": None, "maker": "에스앤비코리아",
            "materials": [], "substances_mentioned": ["화장품책임판매업자", "EWG"],
            "kc_numbers": [], "target_age": None,
            "category": "out_of_scope", "category_confidence": 0.95, "raw_language": "ko",
        },
    ),
    (
        "상품명: 곰돌이 인형 키링 9종\n재질: 폴리+PP+금속\n사이즈: 세로 약 12cm",
        {
            "product_name": "곰돌이 인형 키링 9종", "model_name": None, "maker": None,
            "materials": ["폴리", "PP", "금속"], "substances_mentioned": [],
            "kc_numbers": [], "target_age": None,
            "category": "unclassified", "category_confidence": 0.4, "raw_language": "ko",
        },
    ),
]


def _few_shot_messages() -> list[dict]:
    out: list[dict] = []
    for page, answer in _EXAMPLES:
        out.append({"role": "user", "content": page})
        out.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    return out


def extract(
    page_text: str,
    page_url: str | None = None,
    *,
    allow_llm: bool = True,
) -> ProductFacts:
    """allow_llm=False 면 호출 없이 휴리스틱으로 간다.

    일일 LLM 상한을 넘겼을 때 쓴다. 상한을 넘어도 서비스는 계속 돈다 -
    멈추는 대신 정확도가 낮아지고, 그 사실을 화면이 말한다 (핸드오프 §8).
    """
    if not allow_llm or settings.mock_mode or not settings.anthropic_api_key:
        return _heuristic_fallback(page_text, page_url)

    from anthropic import Anthropic

    try:
        client = Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.extractor_model,
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[*_few_shot_messages(), {"role": "user", "content": page_text[:60_000]}],
        )
    except Exception as exc:  # noqa: BLE001
        # 남의 API 장애로 우리 서비스를 죽이지 않는다. 정부 API 에 적용한 원칙과
        # 같다 - 투표 기간 18일 동안 추출기 하나 때문에 스캔 전체가 500 이 되면
        # 안 된다.
        #
        # 빈 ProductFacts 가 아니라 휴리스틱으로 내린다. 빈 값으로 두면 페이지에
        # 인증번호가 적혀 있는데도 "표기 없음" 이라고 말하게 된다 - 못 찾은 것과
        # 찾아보지 않은 것은 다르다 (R3). 휴리스틱은 정규식이라 인증번호·재질은
        # 그대로 잡는다.
        _log.warning(
            "추출기 LLM 호출 실패, 휴리스틱으로 대체합니다: %s: %s",
            type(exc).__name__, exc,
        )
        return _heuristic_fallback(page_text, page_url)

    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # R3: a parse failure is not a safe product. Degrade to unknown.
        return ProductFacts(source_page_url=page_url)

    # Strip anything not in the schema. extra="forbid" would otherwise reject a
    # hallucinated verdict field ("risk_level" etc.) and lose the whole
    # extraction; dropping unknown keys keeps the good fields. R1 lives in the
    # prompt; this is the backstop.
    allowed = set(ProductFacts.model_fields) - {"source_page_url"}
    data = {k: v for k, v in data.items() if k in allowed}
    try:
        return ProductFacts(**data, source_page_url=page_url)
    except Exception:
        return ProductFacts(source_page_url=page_url)


def _heuristic_fallback(text: str, url: str | None) -> ProductFacts:
    """Offline stand-in so the pipeline is runnable without an API key.

    Deliberately dumb. It exists for wiring and tests, not for accuracy.
    """
    import re
    import unicodedata

    # 실제 형식은 설계서 예시대로 하이픈이 들어간다: 'JU071047-12002C',
    # 'CB123A123-1234'. 하이픈 패턴을 먼저 두지 않으면 앞부분만 잘려 나가고,
    # 잘린 번호는 조회에 실패해 멀쩡한 인증에 RED 가 뜬다.
    # 인증번호 패턴은 kats_client 의 CERT_NUMBER_RE 하나만 쓴다. 두 곳에 따로
    # 두면 한쪽만 고쳐져 갈라진다 — 실제로 이 자리의 [A-Z]{2} 가정 때문에
    # B 계열(학용품 리콜의 36%)을 셀러가 붙여넣어도 조회를 시도조차 안 했다.
    kc = CERT_NUMBER_RE.findall(unicodedata.normalize("NFKC", text))
    m = re.search(r"(?:모델명|모델|型号|model)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-_]{2,})", text, re.I)
    cat = ItemCategory.UNCLASSIFIED
    if any(w in text for w in ("완구", "장난감", "블록", "toy")):
        cat = ItemCategory.CHILDREN_TOY
    elif any(w in text for w in ("학용품", "크레파스", "필통")):
        cat = ItemCategory.CHILDREN_STATIONERY

    # 소관 밖(식품·화장품 등)을 알리는 표지를 substances_mentioned 에 흘려보낸다.
    # verify 의 (0) 단계가 이 근거로 OUT_OF_SCOPE 를 판정한다. 휴리스틱은 정확도
    # 목적이 아니라 배선 목적이므로, 대표 키워드만 저비용으로 잡는다.
    scope_markers = [
        w for w in (
            "화장품책임판매업자", "화장품제조업자", "EWG", "클렌징", "앰플", "토너",
            "죽염", "소금", "통후추", "원두", "드립백", "咖啡",
        )
        if w in text
    ]

    upper = text.upper()
    mats = [mt for mt in ("PVC", "PP", "TPE", "ABS", "PC") if mt in upper]

    return ProductFacts(
        product_name=text.strip().splitlines()[0][:80] if text.strip() else None,
        model_name=m.group(1) if m else None,
        materials=mats,
        substances_mentioned=scope_markers,
        kc_numbers=list(dict.fromkeys(kc)),
        category=cat,
        category_confidence=0.3 if cat is not ItemCategory.UNCLASSIFIED else 0.0,
        source_page_url=url,
    )
