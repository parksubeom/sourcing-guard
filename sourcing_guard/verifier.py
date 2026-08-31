"""Stage 2 — deterministic verification. No LLM here.

Produces Finding objects only. Scoring happens in scorer.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from .kats_client import CertState, KatsClient
from .models import Finding, FindingKind, ItemCategory, ProductFacts, Signal

_RULES_PATH = Path(__file__).parent / "data" / "hazard_rules.yaml"

# certState -> (FindingKind, Signal, 셀러에게 덧붙일 말)
#
# 어느 상태를 RED 로 볼지는 제품 판단이다. 코드 정합성만으로 바꾸지 말 것
# (00_프로젝트_핸드오프.md §3.1).
_CERT_STATE_FINDING: dict[CertState, tuple[FindingKind, Signal, str]] = {
    CertState.OK: (FindingKind.KC_VERIFIED, Signal.GREEN, ""),
    CertState.REVOKED: (
        FindingKind.KC_REVOKED, Signal.RED,
        "이 인증번호로는 판매 표시를 유지할 수 없습니다. 공급처에 유효한 인증을 요청하세요.",
    ),
    CertState.SUSPENDED: (
        FindingKind.KC_SUSPENDED, Signal.RED,
        "현재 인증표시 사용이 제한된 상태입니다. 원문에서 제한 기간을 확인하세요.",
    ),
    CertState.UNDER_ACTION: (
        FindingKind.KC_UNDER_ACTION, Signal.AMBER,
        "행정 조치가 진행 중인 인증입니다. 원문에서 진행 상황을 확인하세요.",
    ),
    CertState.UNKNOWN: (
        FindingKind.KC_UNDER_ACTION, Signal.AMBER,
        "인증상태를 해석하지 못했습니다. 원문에서 직접 확인해 주세요.",
    ),
}

_CERT_REQUIRED = {
    ItemCategory.CHILDREN_TOY,
    ItemCategory.CHILDREN_STATIONERY,
    ItemCategory.CHILDREN_TEXTILE,
    ItemCategory.ELECTRICAL,
}


@dataclass(frozen=True)
class HazardRule:
    id: str
    substance: str
    aliases: tuple[str, ...]
    applies_to: tuple[str, ...]
    limit_value: float | None
    unit: str | None
    legal_basis: str
    source_url: str


class RuleBook:
    """Loads hazard_rules.yaml. Only `status: verified` rules are active."""

    def __init__(self, path: Path = _RULES_PATH) -> None:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.covered = set(raw.get("coverage", {}).get("categories", []))
        self.active: list[HazardRule] = []
        self.drafts: list[str] = []
        for r in raw.get("rules", []):
            if r.get("status") != "verified":
                self.drafts.append(r["id"])
                continue
            self.active.append(
                HazardRule(
                    id=r["id"],
                    substance=r["substance"],
                    aliases=tuple(r.get("aliases", [])),
                    applies_to=tuple(r.get("applies_to", [])),
                    limit_value=r.get("limit_value"),
                    unit=r.get("unit"),
                    legal_basis=r["legal_basis"],
                    source_url=r["source_url"],
                )
            )

    def for_category(self, cat: ItemCategory) -> list[HazardRule]:
        return [r for r in self.active if cat.value in r.applies_to]

    def covers(self, cat: ItemCategory) -> bool:
        """Declared coverage is not enough: it must be backed by verified rules.

        Otherwise an empty rule book would silently produce GREEN (violates R3).
        """
        return cat.value in self.covered and bool(self.for_category(cat))


def verify(facts: ProductFacts, kats: KatsClient, rules: RuleBook) -> list[Finding]:
    today = date.today()
    findings: list[Finding] = []

    # --- (a) KC certification -------------------------------------------
    if facts.kc_numbers:
        for num in facts.kc_numbers:
            rec = kats.lookup_certification(num)
            if rec is None:
                findings.append(
                    Finding(
                        kind=FindingKind.KC_NOT_FOUND,
                        signal=Signal.RED,
                        statement_ko=f"상세페이지에 표기된 인증번호 '{num}' 이(가) 조회되지 않습니다.",
                        source_label="국가기술표준원 안전인증정보 조회",
                        source_url="https://www.safetykorea.kr/release/certDetail",
                        legal_basis="전기용품 및 생활용품 안전관리법 / 어린이제품 안전 특별법",
                        detail={"kc_number": num},
                        checked_at=today,
                    )
                )
            else:
                # 조회 성공 != 유효한 인증. certState 를 보고 갈라야 한다.
                kind, signal, advice = _CERT_STATE_FINDING[rec.state]
                if kind is FindingKind.KC_VERIFIED:
                    statement = (
                        f"인증번호 '{rec.cert_number}' 이(가) 조회되었습니다"
                        f"(인증상태: {rec.status}). 등록 제품명: {rec.product_name or '-'}"
                    )
                else:
                    statement = (
                        f"인증번호 '{rec.cert_number}' 의 인증상태가 "
                        f"'{rec.status or '미표기'}' 로 조회되었습니다. {advice}"
                    )
                findings.append(
                    Finding(
                        kind=kind,
                        signal=signal,
                        statement_ko=statement,
                        source_label="국가기술표준원 안전인증정보 조회",
                        source_url=rec.detail_url or "https://www.safetykorea.kr/release/certDetail",
                        detail={
                            "maker": rec.maker,
                            "maker_country": rec.maker_country,
                            "cert_state": rec.status,
                            "cert_div": rec.cert_div,
                            "registered_model": rec.model_name,
                            "registered_product": rec.product_name,
                        },
                        checked_at=today,
                    )
                )
    elif facts.category in _CERT_REQUIRED:
        findings.append(
            Finding(
                kind=FindingKind.KC_MISSING_BUT_REQUIRED,
                signal=Signal.AMBER,
                statement_ko=(
                    "안전인증 대상으로 보이는 품목이나 상세페이지에서 인증번호를 찾지 못했습니다. "
                    "공급처에 인증번호를 요청해 확인이 필요합니다."
                ),
                source_label="제품안전정보센터 안전확인 대상 품목 안내",
                source_url="https://www.safetykorea.kr/policy/targetsSafetyCheck3",
                checked_at=today,
            )
        )

    # --- (b) recall matching --------------------------------------------
    recalls = kats.search_recalls(
        product_name=facts.product_name,
        model_name=facts.model_name,
        cert_number=facts.kc_numbers[0] if facts.kc_numbers else None,
    )
    if recalls:
        for r in recalls:
            findings.append(
                Finding(
                    kind=FindingKind.RECALL_MATCH,
                    signal=Signal.RED,
                    statement_ko=(
                        f"동일/유사 모델명이 리콜 공표 목록에 있습니다 "
                        f"({'국내' if r.scope == 'domestic' else '해외'}, {r.announced_on or '일자 미상'})."
                    ),
                    source_label="국가기술표준원 리콜정보",
                    source_url=r.detail_url or "https://www.safetykorea.kr/",
                    detail={"reason": r.reason, "model": r.model_name, "maker": r.maker},
                    checked_at=today,
                )
            )
    elif facts.product_name or facts.model_name:
        findings.append(
            Finding(
                kind=FindingKind.RECALL_CLEAR,
                signal=Signal.GREEN,
                statement_ko="조회 시점 기준 리콜 공표 목록에서 일치 항목을 찾지 못했습니다.",
                source_label="국가기술표준원 리콜정보",
                source_url="https://www.safetykorea.kr/",
                checked_at=today,
            )
        )

    # --- (c) hazard rules ------------------------------------------------
    if not rules.covers(facts.category):
        findings.append(
            Finding(
                kind=FindingKind.COVERAGE_GAP,
                signal=Signal.UNKNOWN,
                statement_ko="이 품목군의 유해물질 기준은 아직 규칙 DB에 수록되지 않았습니다.",
                source_label="규칙 DB 커버리지",
                source_url="https://www.safetykorea.kr/policy/targetsSafetyCheck3",
                checked_at=today,
            )
        )
    else:
        haystack = " ".join(facts.materials + facts.substances_mentioned).lower()
        for rule in rules.for_category(facts.category):
            findings.append(
                Finding(
                    kind=FindingKind.HAZARD_RULE_APPLIES,
                    signal=Signal.AMBER,
                    statement_ko=(
                        f"이 품목군에는 '{rule.substance}' 기준"
                        + (f" ({rule.limit_value}{rule.unit})" if rule.limit_value else "")
                        + "이 적용됩니다. 시험성적서로 확인이 필요합니다."
                    ),
                    source_label=rule.legal_basis,
                    source_url=rule.source_url,
                    legal_basis=rule.legal_basis,
                    detail={"rule_id": rule.id},
                    checked_at=today,
                )
            )
            if any(a.lower() in haystack for a in (rule.substance, *rule.aliases)):
                findings.append(
                    Finding(
                        kind=FindingKind.SUBSTANCE_MENTIONED,
                        signal=Signal.AMBER,
                        statement_ko=(
                            f"상세페이지 본문에 규제 물질 '{rule.substance}' 관련 표기가 감지되었습니다."
                        ),
                        source_label=rule.legal_basis,
                        source_url=rule.source_url,
                        detail={"rule_id": rule.id},
                        checked_at=today,
                    )
                )

    return findings
