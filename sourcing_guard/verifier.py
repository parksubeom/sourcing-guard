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
    recall_evidence_for,
    CertState,
    KatsApiError,
    KatsClient,
    OPERATOR_FAULT_CODES,
    cert_evidence_url,
    item_search_url,
    is_state_not_stated,
    normalize_kc,
    recall_evidence,
)
from .scoping import (
    CHILDREN_CATEGORIES,
    AgeScope,
    classify_age,
    missing_inputs,
    out_of_scope_reason,
)
from .noncompliant_index import NoncompliantIndex
from .rra_client import RraApiError, RraClient, is_searchable_model, rf_evidence_url

_NONCOMPLIANT_URL = "https://www.rra.go.kr/ko/license/A_d_list.do"
from .models import (
    object_particle,
    subject_particle,
    topic_particle,
    Finding,
    FindingKind,
    ItemCategory,
    MatchStrength,
    ProductFacts,
    Signal,
    matched_on_label,
)

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
    # pH 처럼 상·하한이 모두 있는 룰. 크기 비교(어느 쪽이 더 엄격한가)에 쓴다.
    range_min: float | None = None
    range_max: float | None = None

    # --- 성능·구조 요건 (생활용품·전기용품) ------------------------------
    # 유해물질은 "납 90mg/kg" 처럼 값 하나로 떨어지지만, 성능 요건은 그렇지
    # 않다. 부속서 53(운동용 안전모) 원문을 보면 기준이 "가속도계를 무게중심
    # 반경 10mm 이내에 설치하고 6kHz 로 샘플링해 CFC 1000 으로 필터링" 같은
    # **시험 절차 규격**이다. 셀러에게 그 값을 보여줘 봐야 쓸 수 없다.
    #
    # 그래서 값 대신 **어떤 시험을 통과해야 하는지**를 담는다. 화면에서 하는
    # 일은 유해물질과 같다 - "이걸 확인하라" 는 안내다.
    requirement_type: str = "substance"   # substance | performance
    test_items: tuple[str, ...] = ()      # 충격흡수성, 관통성 ...
    annex_no: str | None = None           # 부속서 번호
    # 정부 조사에서 이 품목이 어떻게 나왔는지. 비율만 두면 표본 8개짜리가
    # 통계처럼 읽히므로 표본을 반드시 함께 담는다 (test_failure_rate_honesty).
    failure_rate: dict | None = None


def _performance_statement(rule: "HazardRule") -> str:
    """성능·구조 요건의 화면 문구.

    유해물질처럼 값을 보여줄 수 없다 - 기준이 시험 절차 규격이라 셀러가 쓸 수
    없기 때문이다. 대신 **어떤 시험을 통과해야 하는지**와, 정부 조사에서 이
    품목이 어떻게 나왔는지를 알려준다.

    부적합률은 비율만 쓰지 않고 표본을 함께 낸다. "88%" 만 적으면 표본 8개짜리
    수치가 통계처럼 읽힌다 (기획서 §2.2 에서 한 번 틀렸던 실수다).
    """
    items = ", ".join(rule.test_items[:5]) if rule.test_items else None
    parts = [f"이 품목은 {rule.legal_basis} 대상입니다."]
    if items:
        parts.append(f"{items} 시험을 통과해야 하며, 공급처에 시험성적서를 요구하세요.")
    else:
        parts.append("공급처에 해당 안전기준 시험성적서를 요구하세요.")

    rate = rule.failure_rate or {}
    sample = rate.get("sample")
    if sample:
        source = rate.get("source", "정부 안전성조사")
        parts.append(
            f"참고로 {source}에서 이 품목은 {sample}가 안전기준에 부적합했습니다. "
            "표적 조사이고 표본이 작아 일반화할 수는 없으나, 확인 없이 소싱하기에는 "
            "위험이 큽니다."
        )
    return " ".join(parts)


def _looser_of(a: "HazardRule", b: "HazardRule") -> "HazardRule | None":
    """두 룰 중 더 느슨한 쪽. 비교 불가면 공통기준 쪽을 돌려준다.

    셀러가 통과시켜야 하는 것은 둘 중 빡빡한 기준이므로, 화면에는 엄격한 쪽만
    남긴다. 단위가 다르거나(mg/kg 대 %) 형태가 다르면(범위 대 단일값) 크기를
    비교할 수 없으므로, 그 품목을 더 정확히 겨냥한 개별기준을 남긴다.
    """
    # 범위(pH)끼리는 상한이 큰 쪽이 느슨하다.
    if a.range_max is not None and b.range_max is not None:
        return a if a.range_max > b.range_max else b

    comparable = (
        a.limit_value is not None
        and b.limit_value is not None
        and a.unit == b.unit
        and a.range_max is None
        and b.range_max is None
    )
    if comparable:
        if a.limit_value == b.limit_value:
            # 값이 같으면 중복이다. 개별기준을 남기고 공통을 뺀다.
            return b if b.id.startswith("KC-COMMON-") else a
        return a if a.limit_value > b.limit_value else b

    # 비교 불가 - 개별기준을 남긴다.
    return b if b.id.startswith("KC-COMMON-") else a


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
                    range_min=r.get("range_min"),
                    range_max=r.get("range_max"),
                    requirement_type=r.get("requirement_type", "substance"),
                    test_items=tuple(r.get("test_items", [])),
                    annex_no=r.get("annex_no"),
                    failure_rate=r.get("failure_rate"),
                )
            )

    def for_category(self, cat: ItemCategory) -> list[HazardRule]:
        """해당 품목군에 적용되는 룰. 같은 물질에 두 기준이 있으면 하나만 남긴다.

        공통안전기준 3.1.5 는 "개별안전기준이 없는 섬유제품" 에만 적용된다고
        스스로 적고 있다(비고 1). 그래서 개별 부속서가 우선한다 - 다만 그것을
        **"부속서가 무조건 이긴다" 로 구현하면 안 된다.**

        실제로 갈린다:
          부속서 1  폼알데하이드 20  vs 공통 75   -> 부속서가 더 엄격
          부속서 11 pH 4.0~8.0     vs 공통 ~7.5 -> **부속서가 더 느슨**

        둘을 함께 내보내면 화면에 두 값이 나란히 떠서 셀러가 느슨한 쪽을 읽는다.
        그렇다고 부속서를 무조건 남기면 pH 처럼 느슨한 값을 우리가 골라주는 셈이
        된다. 그래서 **더 엄격한 쪽**을 남긴다 - 셀러가 통과시켜야 할 기준은
        둘 중 빡빡한 쪽이기 때문이다.

        비교가 불가능하면(단위가 다르거나 범위 대 단일값) 부속서를 남긴다.
        개별기준이 그 품목을 더 정확히 겨냥하고 있어서다.
        """
        applicable = [r for r in self.active if cat.value in r.applies_to]

        # 물질별로 묶는다. 표기가 달라도 잡히도록 aliases 까지 키로 쓴다
        # (총 납 함유량 / 총 납(함유량)).
        buckets: dict[str, list[HazardRule]] = {}
        for rule in applicable:
            for term in {rule.substance, *rule.aliases}:
                buckets.setdefault(term, []).append(rule)

        dropped: set[str] = set()
        for rules in buckets.values():
            annex = [r for r in rules if r.id.startswith("KC-ANNEX")]
            common = [r for r in rules if r.id.startswith("KC-COMMON-")]
            if not annex or not common:
                continue
            for c in common:
                for a in annex:
                    loser = _looser_of(a, c)
                    if loser is not None:
                        dropped.add(loser.id)

        return [r for r in applicable if r.id not in dropped]

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


def _short(text: str | None, limit: int = 60) -> str:
    """리콜 원문의 모델명 칸에는 수십 개가 콤마로 묶여 오기도 한다.

    한 줄에 그대로 내보내면 문장이 화면을 넘어가 다른 근거를 밀어낸다.
    """
    if not text:
        return ""
    t = " ".join(text.split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _matched_value(facts: ProductFacts, m) -> str:
    """셀러 쪽에서 무엇이 맞았는지. 화면에 그 값을 그대로 보여준다."""
    if m.matched_on == "kc_number":
        return ", ".join(facts.kc_numbers)
    if m.matched_on == "model_name":
        return facts.model_name or ""
    return facts.maker or ""


def _match_statement(facts: ProductFacts, r, m) -> str:
    """무엇이 어느 강도로 무엇과 맞았는지를 한 문장에 담는다.

    "리콜 목록과 일치합니다" 만으로는 셀러가 판단할 수 없다. 실제로 나온 질문이
    "펜을 검사했는데 왜 블라인드가 뜨나" 였다 - 우리 쪽 값, 리콜된 제품, 리콜
    쪽 모델명이 한 줄에 있어야 셀러가 스스로 가린다. 우리는 판정하지 않는다(R1).
    """
    where = "국내" if r.scope == "domestic" else "해외"
    when = _fmt_date(r.announced_on) or "공표일 미상"
    ours = _short(_matched_value(facts, m), 40)
    subject = matched_on_label(m.matched_on)
    head = f"{subject} '{ours}'" if ours else subject
    recalled = _short(r.product_name) or "제품명 미상"
    theirs = _short(r.model_name)
    tail = f", 리콜 쪽 모델명은 '{theirs}'" if theirs else ""
    return (
        f"{head}{subject_particle(head)} 리콜 공표 목록과 {m.strength.label_ko}합니다 — "
        f"리콜된 제품은 '{recalled}'({where}, {when} 공표){tail} 입니다. "
        "원문 확인이 필요합니다."
    )


def _as_of_label(yyyymmdd: str | None) -> str:
    """YYYYMMDD -> '2026-08-28 공표분까지'. 값이 없으면 그렇다고 말한다."""
    d = _fmt_date(yyyymmdd)
    return f"{d} 공표분까지" if d else "기준일 미상"


def _lookup_failed(
    what: str, today: date, code: str | None = None, *, agency: str = "국가기술표준원"
) -> Finding:
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
            f"{agency} {what} 조회 서비스에 일시적으로 연결하지 못했습니다. "
            f"{what} 확인이 완료되지 않았으니 {tail}"
        ),
        source_label="국가기술표준원",
        source_url=_LOOKUP_FAILED_SOURCE,
        detail={"scope": what},
        checked_at=today,
    )


def _rf_verified(record, today: date, *, via: str) -> Finding:
    """조회된 적합성평가 레코드를 finding 으로.

    번호로 찾았는지 모델명으로 찾았는지를 문장에 적는다. 모델명 검색은 부분
    일치 목록을 재대조(models_match)한 결과라, 셀러가 어느 축으로 걸렸는지
    알아야 스스로 가릴 수 있다 (리콜에서 matched_on 을 실은 것과 같은 이유).
    """
    models = ", ".join(record.all_models[:4]) or "-"
    how = "모델명으로 조회한 결과" if via == "model" else "번호로 조회한 결과"
    return Finding(
        kind=FindingKind.RF_CERT_VERIFIED,
        signal=Signal.GREEN,
        statement_ko=(
            f"전파인증 번호 '{record.cert_number}'"
            f"{subject_particle(record.cert_number)} 조회되었습니다({how}). "
            f"업체: {record.company or '-'} / 기자재: {record.equipment or '-'} / "
            f"모델: {models}"
        ),
        source_label="국립전파연구원 적합성평가 현황 검색",
        source_url=rf_evidence_url(record.cert_number),
        legal_basis="전파법 제58조의2 (적합성평가)",
        detail={
            "rf_cert_number": record.cert_number,
            "company": record.company,
            "equipment": record.equipment,
            "models": list(record.all_models),
            "matched_on": via,
        },
        checked_at=today,
    )


def _verify_rf(
    facts: ProductFacts,
    rra: "RraClient | None",
    noncompliant: "NoncompliantIndex | None",
    today: date,
) -> list[Finding]:
    """전파인증 축.

    무선 표기가 없으면 아무것도 하지 않는다 - 대상이 아닌 상품에 전파인증을
    요구하면 오탐이다.

    ⚠ 문구는 "무선 기능 표기가 있습니다" 여야지 "전파인증 대상입니다" 면 안
      된다. 대상 여부는 고시 별표 1 이 정하며 우리가 판별하지 않는다 (R1).

    R3-b: 미조회를 RED 로 두지 않는다. 자기적합확인 대상은 R- 번호가 아예 없고
    별도 레지스트리에 자체 관리번호로 공개된다 - 전안법 SCoC 와 같은 구조다.
    """
    if not facts.wireless_hints and not facts.rf_numbers:
        return []

    out: list[Finding] = []
    hint = ", ".join(facts.wireless_hints[:3]) if facts.wireless_hints else None

    # 부적합 현황이 먼저다. 전파인증 축에서 유일하게 RED 자격이 있는 소스이며,
    # 여기 걸리면 "인증이 있느냐" 보다 앞선 사실이다.
    if noncompliant is not None and not noncompliant.is_empty():
        models = [m for m in (facts.model_name, facts.product_name) if m]
        for hit in noncompliant.find(rf_numbers=facts.rf_numbers, models=models):
            axis = "인증번호" if hit.matched_on == "cert_number" else "모델명"
            out.append(
                Finding(
                    kind=FindingKind.RF_NONCOMPLIANT,
                    signal=Signal.RED,
                    statement_ko=(
                        f"부적합 방송통신기자재 현황에 {axis}{subject_particle(axis)} 일치하는 항목이 "
                        f"있습니다. 업체: {hit.company or '-'} / 모델: {hit.model or '-'} / "
                        f"처분일자: {hit.acted_on or '-'}"
                    ),
                    source_label="국립전파연구원 부적합 방송통신기자재 현황",
                    source_url=_NONCOMPLIANT_URL,
                    legal_basis="전파법 제58조의2 (적합성평가)",
                    detail={
                        "matched_on": hit.matched_on,
                        "company": hit.company,
                        "cert_number": hit.cert_number,
                        "model": hit.model,
                        "acted_on": hit.acted_on,
                    },
                    checked_at=today,
                )
            )

    # 번호가 있으면 유효성을 조회한다.
    for number in facts.rf_numbers:
        record = None
        if rra is not None:
            try:
                record = rra.lookup_number(number)
            except RraApiError:
                out.append(_lookup_failed("전파인증", today, agency="국립전파연구원"))
                continue
        if record is not None:
            out.append(_rf_verified(record, today, via="number"))
        else:
            out.append(
                Finding(
                    kind=FindingKind.RF_CERT_NOT_FOUND,
                    signal=Signal.AMBER,
                    statement_ko=(
                        f"전파인증 번호 '{number}'"
                        f"{subject_particle(number)} 적합성평가 현황에서 조회되지 "
                        "않습니다. 자기적합확인 대상은 이 DB에 번호가 없는 것이 정상이므로, "
                        "공급처에 적합성평가 구분을 확인해 주세요."
                    ),
                    source_label="국립전파연구원 적합성평가 현황 검색",
                    source_url=rf_evidence_url(number),
                    legal_basis="전파법 제58조의2 (적합성평가)",
                    detail={"rf_cert_number": number},
                    checked_at=today,
                )
            )

    # 무선 표기는 있는데 번호가 없다 - 가장 흔한 경우(구매대행 상품).
    #
    # ⚠ 여기서 RRA 를 조회하지 않는다. 실측 12초짜리 요청이라(결과 있는 질의)
    #   스캔에 넣으면 무선 상품마다 13초가 되고, 기획서 §8 의 "캐시 히트 3초
    #   이내" 약속이 깨진다. 투표 기간에 무선 상품을 넣은 심사위원이 기다리다
    #   닫으면 그걸로 끝이다.
    #
    #   대신 화면에 "전파인증 조회하기" 버튼을 주고, 누르면
    #   POST /api/v1/rf-lookup 이 verify_rf_by_model 을 부른다. ⑦ 의 KC 이미지
    #   확인 버튼과 같은 패턴이다 - 오래 걸리는 조회는 셀러가 인지한 상태로
    #   누르게 한다.
    #
    #   detail.searchable_model 이 그 버튼의 방아쇠다. 식별력이 없는 모델명
    #   ('A1' 은 1,579페이지)에는 버튼을 주지 않는다 - 눌러도 답이 안 나온다.
    if facts.wireless_hints and not facts.rf_numbers:
        searchable = facts.model_name if is_searchable_model(facts.model_name) else None
        out.append(
            Finding(
                kind=FindingKind.RF_WIRELESS_UNVERIFIED,
                signal=Signal.AMBER,
                statement_ko=(
                    f"상세페이지에 무선 기능 표기({hint})가 있으나 전파인증 번호를 찾지 "
                    "못했습니다. 무선 기자재는 KC 안전인증과 별개로 전파법 적합성평가를 "
                    "받아야 할 수 있습니다. 아래에서 모델명·업체명으로 직접 검색하거나 "
                    "공급처에 확인해 주세요."
                ),
                source_label="국립전파연구원에서 적합성평가 직접 검색",
                source_url=rf_evidence_url(),
                legal_basis="전파법 제58조의2 (적합성평가)",
                detail={
                    "wireless_hints": list(facts.wireless_hints),
                    # 프론트가 이 값으로 "전파인증 조회하기" 버튼을 낸다.
                    # None 이면 버튼을 주지 않는다 (식별력 미달 모델명).
                    "searchable_model": searchable,
                },
                checked_at=today,
            )
        )
    return out


def verify_rf_by_model(
    model: str, rra: "RraClient | None", *, today: date | None = None
) -> list[Finding]:
    """모델명 하나로 적합성평가를 조회한다. 버튼이 부르는 경로다.

    스캔에서는 부르지 않는다 - 실측 12초라 응답 시간을 통째로 잡아먹는다.
    셀러가 "전파인증 조회하기" 를 눌렀을 때만 돈다.

    반환은 Finding 목록이다. 프론트가 스캔 결과와 같은 렌더러로 그리고,
    R2(근거 필수)·R1(판정 금지) 검증도 같은 자리에서 걸린다.
    """
    today = today or date.today()
    if not is_searchable_model(model):
        # 질의 자체를 던지면 안 되는 문자열이다. 버튼이 안 나오는 것이 정상이라
        # 여기 오는 것은 직접 호출뿐이다.
        return []
    if rra is None:
        return [_lookup_failed("전파인증", today, agency="국립전파연구원")]

    try:
        records = rra.search_certs_by_model(model)
    except RraApiError:
        # 못 연 것과 없는 것은 다르다 (R3). 조용히 "인증 없음" 으로 흘리면
        # 확인하지 못한 것을 확인한 것처럼 말하게 된다.
        return [_lookup_failed("전파인증", today, agency="국립전파연구원")]

    if records:
        return [_rf_verified(r, today, via="model") for r in records]
    return [
        Finding(
            kind=FindingKind.RF_CERT_NOT_FOUND,
            signal=Signal.AMBER,
            statement_ko=(
                f"모델명 '{model}' 으로 적합성평가 현황을 조회했으나 일치하는 항목을 "
                "찾지 못했습니다. 자기적합확인 대상은 이 DB에 번호가 없는 것이 "
                "정상이므로, 공급처에 적합성평가 구분을 확인해 주세요."
            ),
            source_label="국립전파연구원 적합성평가 현황 검색",
            source_url=rf_evidence_url(),
            legal_basis="전파법 제58조의2 (적합성평가)",
            detail={"searched_model": model},
            checked_at=today,
        )
    ]


def verify(
    facts: ProductFacts,
    kats: KatsClient,
    rules: RuleBook,
    recalls: "RecallIndex | None" = None,
    rra: "RraClient | None" = None,
    noncompliant: "NoncompliantIndex | None" = None,
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
    #
    # 이미지(KC 마크)에서 읽은 번호는 텍스트 번호와 경로가 다르다. 텍스트는
    # 바로 조회하고, 이미지는 셀러가 확인한 뒤에 조회한다. 이유는 오독이다 -
    # 0/O·1/l·5/S 가 뒤바뀌면 멀쩡한 인증이 "조회 안 됨" 으로 뒤집힌다.
    #
    # 그렇다고 안 읽으면 더 나쁘다. KC 마크 이미지만 붙이고 번호를 텍스트로
    # 적지 않는 것이 규정상 유효한 기재라, 안 읽으면 실제로는 있는 인증을
    # "표기 없음" 으로 처리하게 된다 - 못 찾은 것과 찾아보지 않은 것은
    # 다르다 (R3).
    _text_kc = {normalize_kc(x) for x in facts.kc_numbers}
    image_candidates = [
        n for n in facts.kc_numbers_from_image if normalize_kc(n) not in _text_kc
    ]

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
                            f"상세페이지에 표기된 인증번호 '{num}'"
                            f"{subject_particle(num)} 조회되지 않습니다. "
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
                        f"인증번호 '{rec.cert_number}'"
                        f"{subject_particle(rec.cert_number)} 조회되었습니다"
                        f"(인증상태: {rec.status}). 등록 제품명: {rec.product_name or '-'}"
                    )
                elif is_state_not_stated(rec.status):
                    # 값이 비어 있는 것("-")과 우리가 해석 못 한 것은 다르다.
                    # "해석하지 못했습니다" 는 우리 잘못처럼 들린다 (완구 43건).
                    statement = (
                        f"인증번호 '{rec.cert_number}'"
                        f"{topic_particle(rec.cert_number)} 조회되었으나 "
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
    elif image_candidates or _cert_required_here:
        if image_candidates:
            # "찾지 못했습니다" 가 아니다. 읽었고, 형식 검증도 통과했다.
            # 조회만 셀러 확인 뒤로 미룬다.
            findings.append(_image_candidate_finding(image_candidates, today))
        else:
            findings.append(_kc_missing_finding(facts, today))

        if _cert_required_here:
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

    # 강도로 가른다. 셀러가 화면에서 묻는 것은 "펜인데 왜 블라인드?" 이고,
    # 그 답은 "무엇이 맞았는가" 다 (CLAUDE.md R6).
    #
    #   exact / strong  모델명·인증번호가 맞았다        → 확인된 문제
    #   weak            제조사와 제품명 단어만 겹쳤다   → 참고
    #
    # 약한 일치를 버리지는 않는다. 놓친 알림이 이 서비스가 하는 유일한 약속을
    # 깨뜨린다. 대신 "이 상품이 리콜됨" 과 같은 자리에 두지 않는다 - 섞어 놓으면
    # 셀러가 둘 다 무시하게 되고, 그러면 진짜 일치도 안 보게 된다.
    confirmed = [(r, m) for r, m in hits if m.strength is not MatchStrength.WEAK]
    weak = [(r, m) for r, m in hits if m.strength is MatchStrength.WEAK]

    for r, m in confirmed:
        label, url = recall_evidence_for(r)
        findings.append(
            Finding(
                kind=FindingKind.RECALL_MATCH,
                signal=Signal.RED,
                statement_ko=_match_statement(facts, r, m),
                source_label=label,
                source_url=url,
                detail={
                    "reason": r.reason,
                    "model": r.model_name,
                    "maker": r.maker,
                    "match_strength": m.strength.value,
                    "match_strength_ko": m.strength.label_ko,
                    "matched_on": m.matched_on,
                    "matched_on_ko": matched_on_label(m.matched_on),
                    "matched_value": _matched_value(facts, m),
                    "recalled_product_name": r.product_name,
                    "evidence_is_original": label == "리콜 공표 원문",
                },
                checked_at=today,
            )
        )

    if weak:
        # 한 건씩 내지 않고 묶는다. 약한 일치는 원래 여러 건이 한꺼번에 걸린다 -
        # 중성펜 'M-1000' 하나가 잔디깎이·전기냄비·유아용 드레스 등 6건을 물고
        # 왔다. 수십 줄로 내면 그건 경고가 아니라 소음이고, 소음이 된 경고는
        # 꺼진 경고와 같다. 주변 리콜(b-2)을 정확 일치로 좁힌 것과 같은 논리다.
        newest = max(weak, key=lambda pair: pair[0].announced_on or "")[0]
        label, url = recall_evidence_for(newest)
        findings.append(
            Finding(
                kind=FindingKind.RECALL_WEAK_MATCH,
                # 신호를 매기지 않는다. 이 상품에 대해 확인된 것이 없다.
                signal=Signal.UNKNOWN,
                statement_ko=(
                    f"참고 — {_weak_reason(weak)} 리콜 공표가 {len(weak)}건 있습니다 "
                    f"(가장 최근 {_fmt_date(newest.announced_on) or '공표일 미상'} 공표: "
                    f"'{_short(newest.product_name) or '제품명 미상'}'). "
                    "확실하지 않은 유사 일치이며, 이 상품이 리콜 대상이라는 뜻은 "
                    "아닙니다. 원문에서 확인해 주세요."
                ),
                source_label=label,
                source_url=url,
                detail={
                    "count": len(weak),
                    "match_strength": MatchStrength.WEAK.value,
                    "match_strength_ko": MatchStrength.WEAK.label_ko,
                    "matched_on": sorted({m.matched_on for _, m in weak}),
                    "matched_on_ko": "·".join(
                        matched_on_label(a) for a in sorted({m.matched_on for _, m in weak})
                    ),
                    "latest_announced_on": newest.announced_on,
                    "products": [
                        r.product_name for r, _ in weak[:5] if r.product_name
                    ],
                },
                checked_at=today,
            )
        )

    if not confirmed and recall_available and (facts.product_name or facts.model_name):
        # "리콜 이력 없음" 에는 유효기간이 있다. 로컬 사본이라 오늘 공표된
        # 리콜은 다음 동기화 전까지 안 잡힌다. 숨기면 안 되는 트레이드오프다.
        #
        # ⚠ 문장이 "일치 항목이 없다" 에서 "모델명·인증번호가 일치하는 항목이
        #   없다" 로 좁혀졌다. 약한 일치가 있는데 "일치 항목 없음" 이라고 하면
        #   바로 아래 참고 항목과 앞뒤가 맞지 않는다. 좁힌 문장은 약한 일치가
        #   있어도 참이다.
        as_of = _as_of_label(recalls.as_of)
        findings.append(
            Finding(
                kind=FindingKind.RECALL_CLEAR,
                signal=Signal.GREEN,
                statement_ko=(
                    f"리콜 공표 목록에서 모델명·인증번호가 일치하는 항목을 "
                    f"찾지 못했습니다. 리콜 대조 기준: {as_of} (매일 갱신)"
                ),
                source_label="국가기술표준원 리콜정보",
                source_url=recall_evidence(None)[1],
                detail={"recall_data_as_of": recalls.as_of},
                checked_at=today,
            )
        )

    # --- (b-2) 같은 제조사의 다른 리콜 ----------------------------------------
    #
    # 셀러가 소싱 단계에서 실제로 판단하는 것은 "이 공급처를 믿을 수 있나" 다.
    # 같은 업체에 리콜이 쌓여 있으면 그건 이 상품의 결함은 아니지만 공급처를
    # 다시 볼 이유는 된다. 그래서 참고 정보로만 낸다.
    #
    # ⚠ 정확 일치만 쓴다. 로컬 사본 실측(2026-09-01)에서 축 세 개를 재보니:
    #     제조사 정확 일치  13~63건    ← 셀러에게 보여줄 만한 숫자
    #     제조사 포함 일치   1,600건+   어떤 질의에도. 일반 접미사가 폭발한다
    #     품목군            671~1,370건 버킷이 11종뿐이다
    #     재질              2,181건     또는 2건. 어휘가 서로 다르다
    #   그래서 품목군·재질 축은 버렸고 제조사도 포함 매칭을 쓰지 않는다.
    if recall_available and facts.maker:
        seen_uids = {r.uid for r, _ in hits if r.uid}
        others = recalls.by_maker_exact(facts.maker, exclude_uids=seen_uids)
        if others:
            latest = _fmt_date(others[0].announced_on) or "공표일 미상"
            findings.append(
                Finding(
                    kind=FindingKind.MAKER_OTHER_RECALLS,
                    # 신호를 매기지 않는다. 이 상품에 대해 확인된 것이 없다.
                    signal=Signal.UNKNOWN,
                    statement_ko=(
                        f"같은 제조사 '{facts.maker}' 의 다른 리콜이 "
                        f"{len(others)}건 있습니다 (최근 {latest} 공표). "
                        "이 상품이 리콜 대상이라는 뜻은 아닙니다 — "
                        "업체명이 같은 다른 제품의 이력이며, 공급처를 확인할 때 참고하세요."
                    ),
                    source_label="국가기술표준원 리콜정보에서 확인",
                    source_url=recall_evidence(None)[1],
                    detail={
                        "maker": facts.maker,
                        "count": len(others),
                        "match": "maker_exact",
                        "latest_announced_on": others[0].announced_on,
                        "products": [
                            r.product_name for r in others[:5] if r.product_name
                        ],
                    },
                    checked_at=today,
                )
            )

    # --- (b-4) 전파인증 (적합성평가) ----------------------------------------
    # KC 와 완전히 별개 제도다. KC 마크가 있어도 전파인증이 없으면 위반이라,
    # 셀러가 가장 자주 놓치는 지점이다.
    findings.extend(_verify_rf(facts, rra, noncompliant, today))

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
            # 지금 규칙 DB 에는 공통안전기준만 들어 있다(17건 전부). 품목별
            # 부속서 - 완구 6 · 학용품 11 · 유아용 섬유제품 1 - 가 같은 물질에
            # 더 엄격한 값을 정하는 경우가 있어서, 공통기준 값을 최종 적용값처럼
            # 말하면 셀러에게 실제보다 느슨한 수치를 보여주게 된다. 이건 "모른다"
            # 가 아니라 "틀렸다" 라서, 부속서를 수록할 때까지 그 한계를 문장에
            # 적어둔다. 값을 지어내지 않고 단정만 걷어내는 것이다 (R5·§1).
            if rule.requirement_type == "performance":
                statement = _performance_statement(rule)
                findings.append(
                    Finding(
                        kind=FindingKind.HAZARD_RULE_APPLIES,
                        signal=Signal.UNKNOWN,
                        statement_ko=statement,
                        source_label=rule.legal_basis,
                        source_url=rule.source_url,
                        legal_basis=rule.legal_basis,
                        detail={
                            "rule_id": rule.id,
                            "requirement_type": "performance",
                            "test_items": list(rule.test_items),
                            "failure_rate": rule.failure_rate,
                        },
                        checked_at=today,
                    )
                )
                continue

            limit = f" ({rule.limit_value}{rule.unit})" if rule.limit_value else ""
            if "공통안전기준" in (rule.legal_basis or ""):
                statement = (
                    f"이 품목군에는 '{rule.substance}' 공통안전기준{limit}이 적용됩니다. "
                    "품목별 부속서가 더 엄격한 값을 정하는 경우가 있어, "
                    "시험성적서로 확인이 필요합니다."
                )
            else:
                statement = (
                    f"이 품목군에는 '{rule.substance}' 기준{limit}이 적용됩니다. "
                    "시험성적서로 확인이 필요합니다."
                )
            findings.append(
                Finding(
                    kind=FindingKind.HAZARD_RULE_APPLIES,
                    # 적용 범위 안내다. 문제를 지적하는 것이 아니므로 노란불을
                    # 달지 않는다 — 이 finding 하나로 신호가 갈리면 규제 품목군이
                    # 전부 AMBER 가 된다.
                    signal=Signal.UNKNOWN,
                    statement_ko=statement,
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


# 약한 일치가 왜 약한지. 축마다 이유가 다르므로 문구도 달라야 한다.
#
#   maker+product  제조사가 같고 제품명 단어가 겹쳤을 뿐이다
#   model_name     모델명이 맞긴 했는데 그 문자열의 식별력이 낮다
#                  ('153' 처럼 숫자만이거나, 'M1000' 처럼 글자가 하나뿐)
_WEAK_REASON_KO: dict[str, str] = {
    "maker+product": "제조사와 제품명 단어가 겹치는",
    "model_name": "식별력이 낮은 모델명 문자열이 겹치는",
    "kc_number": "인증번호 문자열이 겹치는",
}


def _weak_reason(weak: list) -> str:
    axes = sorted({m.matched_on for _, m in weak})
    return "·".join(_WEAK_REASON_KO.get(a, a) for a in axes) or "유사한"


def _kc_missing_finding(facts: ProductFacts, today: date) -> Finding:
    """인증번호 표기를 못 찾았을 때.

    제품명·업체명이 있으면 셀러가 정부 사이트에서 직접 인증 여부를 검색할 수
    있게 링크를 연다. 우리가 대신 조회해 "인증 없음"을 단정하지 않는다 -
    브랜드명 미등록·SCoC 대상이면 DB 에 없는 게 정상이다 (R3).
    """
    search_hint = facts.maker or facts.product_name
    guide = (
        f" 아래 링크에서 '{search_hint}' 로 직접 검색해 인증 이력을 확인할 수 있습니다."
        if search_hint else ""
    )
    return Finding(
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


def _image_candidate_finding(candidates: list[str], today: date) -> Finding:
    """이미지에서 읽고 형식 검증을 통과한 인증번호.

    조회하지 않은 채로 낸다. 자동 조회하면 오독된 한 글자가 "조회 안 됨" 으로
    나가고, 셀러는 멀쩡한 인증을 문제로 읽는다. 셀러가 눈으로 확인·수정한 뒤
    텍스트 경로로 들어가면 그때부터는 다른 번호와 똑같이 자동 조회된다.

    "인증번호 없음" 으로 처리하지 않는 것이 핵심이다. 실제로는 적혀 있는데
    우리가 안 본 것을 없다고 말하면 R3 위반이다.
    """
    shown = ", ".join(candidates)
    return Finding(
        kind=FindingKind.KC_IMAGE_CANDIDATE,
        # 아직 조회하지 않았다. 조회 전에 신호를 매기면 확인하지 않은 것을
        # 확인한 것처럼 말하게 된다 (R3).
        signal=Signal.UNKNOWN,
        statement_ko=(
            f"이미지에서 인증번호 '{shown}'"
                    f"{object_particle(shown)} 확인했습니다. "
            "이미지 판독은 0과 O, 1과 l 이 뒤바뀔 수 있어 자동 조회하지 않습니다. "
            "번호가 맞는지 확인한 뒤 조회해 주세요."
        ),
        source_label="국가기술표준원 안전인증정보 조회",
        source_url=cert_evidence_url(candidates[0]),
        detail={"candidates": candidates, "read_from": "image"},
        checked_at=today,
    )
