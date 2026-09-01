"""Stage 2 — deterministic verification. No LLM here.

Produces Finding objects only. Scoring happens in scorer.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import logging
import yaml
from typing import TYPE_CHECKING

from .kats_client import (
    CertState,
    KatsApiError,
    KatsClient,
    OPERATOR_FAULT_CODES,
    cert_evidence_url,
    item_search_url,
    is_state_not_stated,
)
from .scoping import (
    CHILDREN_CATEGORIES,
    AgeScope,
    classify_age,
    missing_inputs,
    out_of_scope_reason,
)
from .models import Finding, FindingKind, ItemCategory, ProductFacts, Signal

_log = logging.getLogger(__name__)

if TYPE_CHECKING:  # 순환 import 방지 — recall_index 가 watchlist 를 쓴다
    from .recall_index import RecallIndex

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


def _fmt_date(yyyymmdd: str | None) -> str | None:
    """YYYYMMDD -> '2026-08-28'. 원본 그대로 화면에 내보내면 읽히지 않는다."""
    if not yyyymmdd or len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return None
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _as_of_label(yyyymmdd: str | None) -> str:
    """YYYYMMDD -> '2026-08-28 공표분까지'. 값이 없으면 그렇다고 말한다."""
    d = _fmt_date(yyyymmdd)
    return f"{d} 공표분까지" if d else "기준일 미상"


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


def verify(
    facts: ProductFacts,
    kats: KatsClient,
    rules: RuleBook,
    recalls: "RecallIndex | None" = None,
) -> list[Finding]:
    today = date.today()
    findings: list[Finding] = []

    # --- (0) 우리 소관인가 -------------------------------------------------
    # 공통안전기준 1항이 제외하는 물품이면 여기서 끝낸다. 셀러에게 "판별 못 함"
    # 이 아니라 "우리 소관이 아니고 어디 소관인지" 를 알려주는 것이 유용하다.
    #
    # ⚠ 단락은 코드가 동의할 때만 한다. LLM 이 category=out_of_scope 라고 해도
    #   out_of_scope_reason() 이 근거를 못 찾으면 그냥 검증한다.
    #
    #   OUT_OF_SCOPE 는 인증·리콜 검증을 통째로 건너뛰는 유일한 분류다. 그런데
    #   LLM 분류는 완전히 결정론적이지 않다 - 진주 귀걸이를 10회 돌렸더니 2회
    #   out_of_scope 로 흔들렸다(액세서리는 1항 제외 대상이 아니므로 오분류다).
    #   같은 페이지가 20% 확률로 검증을 건너뛰면 놓친 리콜이 생긴다 (R6).
    #
    #   반대 방향(코드가 근거를 찾았는데 LLM 이 다른 분류)에서는 코드를 따른다.
    #   화장품책임판매업자·EWG 같은 표기는 흔들리지 않는 하드 신호다.
    scope_reason = out_of_scope_reason(
        facts.product_name, facts.model_name, *facts.materials, *facts.substances_mentioned
    )
    if scope_reason:
        findings.append(
            Finding(
                kind=FindingKind.OUT_OF_SCOPE,
                signal=Signal.UNKNOWN,
                statement_ko=(
                    "이 품목은 어린이제품 공통안전기준 적용 대상에서 제외됩니다"
                    + (f" ({scope_reason})" if scope_reason else "")
                    + ". 해당 소관 부처의 별도 기준을 확인해 주세요."
                ),
                source_label="어린이제품 공통안전기준 1. 적용범위",
                source_url="https://law.go.kr/행정규칙/어린이제품공통안전기준",
                legal_basis="어린이제품 공통안전기준 1. 적용범위",
                detail={"reason": scope_reason},
                checked_at=today,
            )
        )
        return findings

    if facts.category is ItemCategory.OUT_OF_SCOPE:
        # LLM 만 소관 밖이라고 봤다. 단락하지 않고 계속 검증하되, 판단이
        # 갈렸다는 사실은 남긴다 - 조용히 무시하면 진짜 소관 밖을 놓쳤을 때
        # 원인을 못 찾는다.
        _log.info(
            "추출기는 out_of_scope 로 분류했으나 근거 표기를 찾지 못해 계속 검증합니다: %r",
            (facts.product_name or "")[:40],
        )

    # 연령 표기를 먼저 해석한다. 어린이제품 기준을 적용할지, 인증번호를 요구할지
    # 모두 여기에 달려 있다. 공통안전기준은 만 13세 이하에 적용된다.
    age = classify_age(facts.target_age)
    if age is AgeScope.DECLARED_NOT_CHILD:
        findings.append(
            Finding(
                kind=FindingKind.AGE_OUT_OF_CHILD_RANGE,
                signal=Signal.UNKNOWN,
                statement_ko=(
                    f"사용연령이 '{facts.target_age}' 로 표기되어 어린이제품 공통안전기준"
                    "(만 13세 이하) 적용 대상이 아닙니다. 다만 실사용 연령이 13세 이하이면 "
                    "대상이 될 수 있으니 표기 근거를 공급처에 확인해 주세요."
                ),
                source_label="어린이제품 공통안전기준 1. 적용범위",
                source_url="https://law.go.kr/행정규칙/어린이제품공통안전기준",
                legal_basis="어린이제품 공통안전기준 1. 적용범위",
                detail={"target_age": facts.target_age, "age_scope": age.value},
                checked_at=today,
            )
        )

    # 표기상 어린이제품이 아니면 어린이 품목군의 인증번호를 요구하지 않는다.
    _cert_required_here = facts.category in _CERT_REQUIRED and not (
        age is AgeScope.DECLARED_NOT_CHILD and facts.category in CHILDREN_CATEGORIES
    )

    # --- (a) KC certification -------------------------------------------
    if facts.kc_numbers:
        for num in facts.kc_numbers:
            try:
                lookup = kats.lookup_certification_cached(num)
            except KatsApiError as exc:
                # 캐시조차 없어 답할 수 없는 경우다.
                findings.append(_lookup_failed("인증", today, exc.code))
                break
            rec = lookup.record
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
                if lookup.stale:
                    # 하루 묵은 답을 최신인 것처럼 말하지 않는다.
                    statement += (
                        f" (조회 서비스에 연결하지 못해 {lookup.fetched_at[:10]} 조회분으로 "
                        "표시합니다. 최신 상태는 근거 링크에서 확인해 주세요.)"
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
    elif _cert_required_here:
        # 제품명·업체명이 있으면 셀러가 정부 사이트에서 직접 인증 여부를 검색할 수
        # 있게 링크를 연다. 우리가 대신 조회해 "인증 없음"을 단정하지 않는다 -
        # 브랜드명 미등록·SCoC 대상이면 DB 에 없는 게 정상이다 (R3).
        search_hint = facts.maker or facts.product_name
        guide = (
            f" 아래 링크에서 '{search_hint}' 로 직접 검색해 인증 이력을 확인할 수 있습니다."
            if search_hint else ""
        )
        findings.append(
            Finding(
                kind=FindingKind.KC_MISSING_BUT_REQUIRED,
                signal=Signal.AMBER,
                statement_ko=(
                    "규제 품목군으로 보이나 상세페이지에서 인증번호를 찾지 못했습니다. "
                    "안전인증·안전확인 대상이면 인증번호가 있어야 하고, "
                    "공급자적합성확인 대상이면 없는 것이 정상입니다."
                    + guide
                    + " 공급처에 인증 구분과 시험성적서를 요청해 확인하세요."
                ),
                source_label="제품안전정보센터에서 인증 여부 직접 검색",
                source_url=item_search_url(search_hint),
                detail={"search_term": search_hint},
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
    #
    # 로컬 사본으로 대조한다. 두 가지가 달라진다:
    #
    #   ① 공개 트래픽이 정부 API 를 건드리지 않는다 (핸드오프 §8). API 가 죽어도
    #      리콜 대조는 계속된다.
    #   ② 매칭이 정확해진다. API 의 recallModelName 검색은 서버가 통짜 문자열로
    #      부분 매칭하는 것이라, 우리가 실데이터로 만든 콤마·슬래시·괄호 분해와
    #      자리표시자 필터가 적용되지 않았다.
    #
    # 그리고 매칭 두뇌가 하나로 합쳐진다. 이전에는 스캔이 API 검색, 워치리스트
    # 스윕이 로컬 watchlist.match() 로 서로 다른 방법을 썼다 — 같은 상품이
    # 스캔에선 안 걸리고 스윕에선 걸릴 수 있는 상태였다. 이제 둘 다 match() 다.
    hits: list = []
    recall_available = recalls is not None and not recalls.is_empty()
    if recall_available:
        hits = recalls.find(facts, today=today)
    else:
        # 로컬 사본이 아직 없다(초기 적재 전). 대조하지 않은 것을 대조했다고
        # 말할 수 없으므로 조회 실패와 같이 다룬다 (R3). 다만 여기서 끝내지
        # 않는다 — 재질·연령·품목 확인 요청은 리콜 조회와 독립적이고, 그것이
        # 소싱 단계에서 셀러에게 주는 실질 가치다.
        findings.append(_lookup_failed("리콜", today))

    if hits:
        for r, m in hits:
            findings.append(
                Finding(
                    kind=FindingKind.RECALL_MATCH,
                    signal=Signal.RED,
                    statement_ko=(
                        f"모델명/인증번호가 리콜 공표 목록과 {m.strength.label_ko}합니다 "
                        f"({'국내' if r.scope == 'domestic' else '해외'} "
                        f"{_fmt_date(r.announced_on) or '공표일 미상'} 공표). "
                        "원문 확인이 필요합니다."
                    ),
                    source_label="국가기술표준원 리콜정보",
                    source_url=r.detail_url or "https://www.safetykorea.kr/",
                    detail={
                        "reason": r.reason,
                        "model": r.model_name,
                        "maker": r.maker,
                        "match_strength": m.strength.value,
                        "matched_on": m.matched_on,
                    },
                    checked_at=today,
                )
            )
    elif recall_available and (facts.product_name or facts.model_name):
        # "리콜 이력 없음" 에는 유효기간이 있다. 로컬 사본이라 오늘 공표된
        # 리콜은 다음 동기화 전까지 안 잡힌다. 숨기면 안 되는 트레이드오프다.
        as_of = _as_of_label(recalls.as_of)
        findings.append(
            Finding(
                kind=FindingKind.RECALL_CLEAR,
                signal=Signal.GREEN,
                statement_ko=(
                    f"리콜 공표 목록에서 일치 항목을 찾지 못했습니다. "
                    f"리콜 대조 기준: {as_of} (매일 갱신)"
                ),
                source_label="국가기술표준원 리콜정보",
                source_url="https://www.safetykorea.kr/",
                detail={"recall_data_as_of": recalls.as_of},
                checked_at=today,
            )
        )

    # --- (b-3) 공급처에 물어야 할 것 ----------------------------------------
    # "모르겠습니다" 로 끝내지 않는다. 소싱 단계에서 셀러가 실제로 할 수 있는
    # 행동은 공급처에 묻는 것뿐이고, 무엇을 물어야 하는지가 실질 가치다.
    for label, ask in missing_inputs(
        materials=facts.materials, target_age=facts.target_age, category=facts.category
    ):
        findings.append(
            Finding(
                kind=FindingKind.INFO_REQUEST,
                signal=Signal.UNKNOWN,
                statement_ko=f"[{label} 확인 필요] {ask}",
                source_label="제품안전정보센터 대상 품목 안내",
                source_url="https://www.safetykorea.kr/policy/targetsSafetyCheck3",
                detail={"missing": label},
                checked_at=today,
            )
        )

    # --- (c) hazard rules ------------------------------------------------
    if age is AgeScope.DECLARED_NOT_CHILD and facts.category in CHILDREN_CATEGORIES:
        pass  # 표기상 대상이 아니므로 어린이제품 기준을 적용하지 않는다.
    elif not rules.covers(facts.category):
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
                    # 적용 범위 안내다. 문제를 지적하는 것이 아니므로 노란불을
                    # 달지 않는다 — 이 finding 하나로 신호가 갈리면 규제 품목군이
                    # 전부 AMBER 가 된다.
                    signal=Signal.UNKNOWN,
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
