"""Stage 2 — deterministic verification. No LLM here.

Produces Finding objects only. Scoring happens in scorer.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from .kats_client import (
    CertState,
    KatsApiError,
    KatsClient,
    OPERATOR_FAULT_CODES,
    cert_evidence_url,
    is_state_not_stated,
)
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
    CertState.EXPIRED: (
        FindingKind.KC_EXPIRED, Signal.AMBER,
        "재인증되어 번호가 바뀌었을 수 있습니다. 공급처에 현재 유효한 인증번호를 "
        "확인해 주세요.",
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


_LOOKUP_FAILED_SOURCE = "https://www.safetykorea.kr/"


def _lookup_failed(what: str, today: date, code: str | None = None) -> Finding:
    """조회를 못 했다는 사실 자체를 Finding 으로 남긴다.

    "조회했는데 없음" 과 "조회를 못 함" 은 셀러에게 완전히 다른 정보다. 후자를
    전자로 표시하면 우리가 확인하지 못한 것을 확인한 것처럼 말하는 게 된다.

    문구는 원인에 따라 갈린다. 키 무효(4000)·IP 미등록(4001) 은 우리 설정
    문제라 "다시 시도해 주세요" 가 거짓말이다 — 우리가 고치기 전엔 계속 실패한다.
    그 경우엔 원인을 로그로 올리고 화면엔 일시적 오류로만 표시한다.
    """
    # 전역 상태가 아니라 이번 오류의 코드로 판단한다. 전역을 보면 직전에 다른
    # 종류의 실패가 있었을 때 엉뚱한 문구가 나간다.
    if code in OPERATOR_FAULT_CODES:
        tail = "조회 서비스 설정을 점검하고 있습니다. 확인이 완료되지 않았습니다."
    else:
        tail = "잠시 후 다시 시도해 주세요."
    return Finding(
        kind=FindingKind.LOOKUP_FAILED,
        signal=Signal.UNKNOWN,
        statement_ko=(
            f"국가기술표준원 {what} 조회 서비스에 일시적으로 연결하지 못했습니다. "
            f"{what} 확인이 완료되지 않았으니 {tail}"
        ),
        source_label="국가기술표준원",
        source_url=_LOOKUP_FAILED_SOURCE,
        detail={"scope": what},
        checked_at=today,
    )


def verify(facts: ProductFacts, kats: KatsClient, rules: RuleBook) -> list[Finding]:
    today = date.today()
    findings: list[Finding] = []

    # --- (a) KC certification -------------------------------------------
    if facts.kc_numbers:
        for num in facts.kc_numbers:
            try:
                rec = kats.lookup_certification(num)
            except KatsApiError as exc:
                findings.append(_lookup_failed("인증", today, exc.code))
                break
            if rec is None:
                findings.append(
                    Finding(
                        kind=FindingKind.KC_NOT_FOUND,
                        signal=Signal.AMBER,
                        statement_ko=(
                            f"상세페이지에 표기된 인증번호 '{num}' 이(가) 조회되지 않습니다. "
                            "공급자적합성확인 대상 품목은 인증번호가 조회 DB에 없는 것이 "
                            "정상이므로, 이 품목의 인증 구분을 먼저 확인해 주세요."
                        ),
                        source_label="국가기술표준원 안전인증정보 조회",
                        # 조회에 실제로 쓴 정규화 번호로 링크한다. 셀러가 눌러
                        # 정부 사이트에서 직접 빈 결과를 확인하는 것이 "우리가
                        # 못 찾았다" 보다 강한 근거다 (R2).
                        source_url=cert_evidence_url(num),
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
                elif is_state_not_stated(rec.status):
                    # 값이 비어 있는 것("-")과 우리가 해석 못 한 것은 다르다.
                    # "해석하지 못했습니다" 는 우리 잘못처럼 들린다 (완구 43건).
                    statement = (
                        f"인증번호 '{rec.cert_number}' 은(는) 조회되었으나 "
                        "인증상태가 표기되지 않았습니다. 원문에서 직접 확인해 주세요."
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
                        source_url=rec.detail_url or cert_evidence_url(rec.cert_number),
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
                    "규제 품목군으로 보이나 상세페이지에서 인증번호를 찾지 못했습니다. "
                    "안전인증·안전확인 대상이면 인증번호가 있어야 하고, "
                    "공급자적합성확인 대상이면 없는 것이 정상입니다. "
                    "공급처에 인증 구분과 시험성적서를 요청해 확인하세요."
                ),
                source_label="제품안전정보센터 안전확인 대상 품목 안내",
                source_url="https://www.safetykorea.kr/policy/targetsSafetyCheck3",
                checked_at=today,
            )
        )

        # 어느 위해도 단계(안전인증 / 안전확인 / 공급자적합성확인)인지 모르면
        # 인증번호 부재를 해석할 수 없다. 모른다는 사실을 감추지 않는다 (R3).
        findings.append(
            Finding(
                kind=FindingKind.KC_TIER_UNKNOWN,
                signal=Signal.UNKNOWN,
                statement_ko=(
                    "이 품목의 인증 구분(안전인증 / 안전확인 / 공급자적합성확인)을 "
                    "판별하지 못했습니다. 구분에 따라 인증번호 유무의 의미가 달라집니다."
                ),
                source_label="제품안전정보센터 대상 품목 안내",
                source_url="https://www.safetykorea.kr/policy/targetsSafetyCheck3",
                checked_at=today,
            )
        )

    # --- (b) recall matching --------------------------------------------
    try:
        recalls = kats.search_recalls(
            product_name=facts.product_name,
            model_name=facts.model_name,
            cert_number=facts.kc_numbers[0] if facts.kc_numbers else None,
        )
    except KatsApiError as exc:
        # 리콜 조회가 실패하면 RECALL_CLEAR 를 붙이면 안 된다. "일치 항목을 찾지
        # 못했다" 는 조회에 성공했을 때만 할 수 있는 말이다.
        findings.append(_lookup_failed("리콜", today, exc.code))
        recalls = []
        return findings

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
