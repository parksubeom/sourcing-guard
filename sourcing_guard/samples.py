"""체험 표본 — 우리가 실제로 낸 결과를 그대로 얼려 둔 것.

왜 기록본인가 (총괄 판정 2026-09-19 §2)
--------------------------------------
표본 버튼을 데모처럼 **면제 지문**으로 늘리면 투표 18일 × 공개 접근 × 10개가
전부 상한 없는 LLM 호출이 된다. 그리고 첫 10초에 6초 대기가 붙는다.

그래서 랜딩 미리보기와 같은 방식이다 - 실측 1회를 파일로 두고 그린다. 화면에는
**"지금 다시 검사"** 가 함께 있고, 그것은 면제가 아닌 일반 예산 안의
`/api/v1/scan` 을 부른다(`/scan?sample=<번호>`).

⚠⚠ **여기서 문장을 만들지 않는다.** 담기는 것은 `scripts/record_samples.py` 가
  받은 `/api/v1/scan` 응답 그대로이고, 이 모듈은 카드에 그릴 조각만 고른다.
  문구를 손으로 고치면 화면이 우리 서버가 낸 적 없는 문장을 말한다 (R5 · ③).

⚠ 파일이 없거나 깨지면 **빈 목록**이다. 빈 껍데기를 그리지 않는다 - 화면은
  표본 구역을 통째로 숨긴다 (`demos.preview()` 와 같은 규칙).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from .baseline import BASELINE, BASELINE_EXTRACTOR

_log = logging.getLogger(__name__)

SAMPLES_PATH = Path(__file__).resolve().parent / "data" / "experience_samples.json"
COMPARE_PATH = Path(__file__).resolve().parent / "data" / "compare_cut.json"

#: 카드에 그리는 근거 줄. 인증 축 하나 · 리콜 축 하나면 카드가 말할 것을 다
#: 말한다. 유해물질 줄은 **수만 적는다** - 열넷을 그대로 그리면 카드가 화면을
#: 덮고, 그게 지금 고치고 있는 "모름투성이" 그 자체다 (index.html FOLD_AT).
_CERT_KINDS = ("kc_verified", "kc_not_found", "kc_revoked", "kc_expired",
               "kc_suspended", "kc_under_action", "kc_state_unknown")
_RECALL_KINDS = ("recall_match", "recall_weak_match", "recall_clear",
                 "maker_other_recalls")


def _row(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": finding.get("kind"),
        "signal": finding.get("signal"),
        "statement_ko": finding.get("statement_ko"),
        "source_label": finding.get("source_label"),
        "source_url": finding.get("source_url"),
    }


def _card(item: dict[str, Any]) -> dict[str, Any] | None:
    result = item.get("result") or {}
    findings = result.get("findings") or []
    if not result.get("signal") or not findings:
        return None

    first_of = lambda kinds: next(  # noqa: E731
        (f for f in findings if f.get("kind") in kinds), None)
    cert = first_of(_CERT_KINDS) or first_of(("lookup_failed",))
    recall = first_of(_RECALL_KINDS)
    hazards = [f for f in findings if f.get("kind") == "hazard_rule_applies"]

    return {
        "id": item.get("cert_number"),
        "title": item.get("title"),
        "text": item.get("text"),
        "signal": result.get("signal"),
        "headline": result.get("headline"),
        "product_name": result.get("product_name"),
        "cert_row": _row(cert) if cert else None,
        "recall_row": _row(recall) if recall else None,
        # 수만 적는다. 화면이 "기준 N개가 적용됩니다" 로 그린다.
        "hazard_count": len(hazards),
        "hazard_source_url": (hazards[0].get("source_url") if hazards else None),
        "recall_data_as_of": result.get("recall_data_as_of"),
        # ⚠ 이 스캔이 어떻게 나왔는지. 바닥 한 줄에 그대로 옮긴다 - 기록본이라고
        #   해서 "정부 조회 성공" 을 감추거나 지어내지 않는다.
        "gov_lookup": (result.get("meta") or {}).get("gov_lookup"),
        "extractor": (result.get("meta") or {}).get("extractor_vendor"),
    }


@lru_cache(maxsize=1)
def payload() -> dict[str, Any]:
    """`/api/v1/samples` 가 내는 것. 파일이 없으면 `items` 가 빈 목록이다."""
    try:
        raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("체험 표본을 읽지 못했습니다: %s", exc)
        return {"recorded_at": None, "items": []}

    cards = [c for c in (_card(i) for i in raw.get("items") or []) if c]
    base = BASELINE[BASELINE_EXTRACTOR]
    return {
        # ⚠ 날짜는 **파일에 적힌 실측 시각**이다. 화면이 "2026-09-19 에 실제로
        #   검사한 것입니다" 라고 말하므로 손으로 적으면 그 문장이 거짓이 된다.
        "recorded_at": raw.get("recorded_at"),
        "items": cards,
        # ⚠⚠ 정직 문구의 숫자다. **화면에 적지 않고 여기서 보낸다.**
        #   "여기 있는 것은 저희가 맞힌 예입니다. 실상품 135건 기준 품목 적중
        #    104건(77.0%)이고, 틀린 8건과 못 맞힌 19건도 저장소에 공개돼
        #    있습니다."
        #   화면에 박으면 기준선이 움직일 때 한쪽만 고쳐져 **고른 것만 보여
        #   준다**는 의심에 거짓으로 답하게 된다 (§6 같은 판단을 두 곳에 적지
        #   마라). 소유자는 `baseline.BASELINE` 하나다.
        "baseline": {
            "extractor": BASELINE_EXTRACTOR,
            "denominator": base["denominator"],
            "ok": base["ok"],
            "wrong": base["wrong"],
            "missed": base["missed"],
            "off_target": base["off_target"],
        },
    }


@lru_cache(maxsize=1)
def compare_cut() -> dict[str, Any] | None:
    """랜딩의 **대비 한 컷** — "인증번호만 보면 vs 우리".

    ⚠⚠ 두 칸이 **같은 한 번의 응답**에서 나온다. 왼쪽은 우리 결과의 인증 축
      줄이고 오른쪽은 리콜 축 줄이다. 남의 서비스를 재 본 적이 없으므로
      왼쪽을 "다른 서비스" 라고 부르지 않는다 (R5) - 화면 문구는 "인증번호만
      조회하면 여기까지" 다.

    ⚠ 파일이 없으면 `None` 이고 화면은 그 구역을 안 그린다. 빈 껍데기를
      만들지 않는다.
    """
    try:
        raw = json.loads(COMPARE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("대비 컷을 읽지 못했습니다: %s", exc)
        return None
    if not raw.get("cert") or not raw.get("recall"):
        return None
    return {
        "signal": raw.get("signal"),
        "recorded_at": raw.get("recorded_at"),
        "cert": raw["cert"],
        "recall": raw["recall"],
    }
