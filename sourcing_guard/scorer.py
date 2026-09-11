"""Deterministic scoring. No LLM, no I/O, no clock, no randomness.

CLAUDE.md R1: this is the ONLY place a verdict is produced.
CLAUDE.md R3: absence of data yields UNKNOWN, never GREEN.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from .models import SPECIFIC_FINDING_KINDS, Finding, FindingKind, ProductFacts, ScanMeta, ScanResult, Signal, ItemCategory, WatchSuggestion, ExtractedField, FindingGroup

# Weights are intentionally boring and auditable. Any change must be
# accompanied by a test case explaining the new behaviour.
_PENALTY: dict[FindingKind, int] = {
    FindingKind.RECALL_MATCH: 100,
    FindingKind.KC_NOT_FOUND: 45,
    FindingKind.KC_REVOKED: 100,
    FindingKind.KC_EXPIRED: 30,
    FindingKind.KC_SUSPENDED: 100,
    FindingKind.KC_UNDER_ACTION: 40,
    FindingKind.KC_MISSING_BUT_REQUIRED: 45,
    # 부재가 정상인 등급(공급자적합성확인·안전기준준수)으로 확정된 경우는
    # 깎지 않는다. 조회할 번호가 애초에 없는 제도다 (R3-b).
    FindingKind.KC_ABSENCE_EXPECTED: 0,
    # 0 이다. 적용 범위 안내이지 문제 지적이 아니므로 신호를 가르지 않고
    # (아래 _signal_for 참조) 점수도 깎지 않는다.
    #
    # 20 으로 뒀더니 GREEN 이 무조건 0점이 됐다. 룰마다 finding 이 하나씩
    # 붙는데 완구·학용품에 14건, 아동섬유에 17건이 적용되기 때문이다
    # (14 x 20 = 280점 감점). "확인된 문제 없음" 과 "0점" 은 모순이다.
    #
    # 애초에 룰이 많다고 위험한 것이 아니라 그 품목군에 기준이 많은 것뿐이다.
    # 점수는 "확인이 얼마나 필요한가" 인데 적용 기준 개수는 그 척도가 아니다.
    # 전파인증. 조회됨은 감점 없음, 미조회·미확인은 확인 사유라 AMBER 쪽.
    FindingKind.RF_CERT_VERIFIED: 0,
    FindingKind.RF_CERT_NOT_FOUND: 30,
    FindingKind.RF_WIRELESS_UNVERIFIED: 30,
    FindingKind.RF_NONCOMPLIANT: 100,
    FindingKind.HAZARD_RULE_APPLIES: 0,
    FindingKind.SUBSTANCE_MENTIONED: 25,
    FindingKind.COVERAGE_GAP: 0,
    FindingKind.LOOKUP_FAILED: 0,
    FindingKind.KC_TIER_UNKNOWN: 0,
    # 등급을 알아낸 것은 사실 확인이지 위험이 아니다. 점수를 깎지 않고,
    # 신호(_HARD_RED · AMBER 집합)에도 넣지 않는다 - 인증번호 부재의
    # 의미를 셀러에게 설명하는 역할만 한다.
    FindingKind.ITEM_GRADE_MATCHED: 0,
    FindingKind.ITEM_GRADE_SPLIT: 0,
    # 셀러가 부속품이라고 답해 등급을 적용하지 않은 경우. 셀러가 준
    # 사실을 기록한 것이라 위험도 감점도 아니다.
    FindingKind.ITEM_GRADE_NOT_APPLIED: 0,
    # 셀러에게 묻는 것이지 위험을 발견한 것이 아니다.
    FindingKind.ITEM_GRADE_NEEDS_POWER: 0,
    # 어린이제품인데 세부품목 목록에 없어 공통안전기준이 적용되는 경우.
    # 시행규칙 별표 3 제2호가 명시한 사실을 옮긴 것이지 위험 발견이
    # 아니다. ITEM_GRADE_MATCHED 를 0 으로 둔 것과 같은 이유다 -
    # 등급을 아는 것은 인증번호 부재의 의미를 설명하는 재료다.
    FindingKind.CHILD_CATCH_ALL: 0,
    FindingKind.OUT_OF_SCOPE: 0,
    FindingKind.AGE_OUT_OF_CHILD_RANGE: 0,
    FindingKind.INFO_REQUEST: 0,
    FindingKind.KC_VERIFIED: 0,
    FindingKind.RECALL_CLEAR: 0,
    # 0 이다. 같은 제조사에 다른 리콜이 있다는 사실이 이 상품의 결함은 아니다.
    # 점수를 깎으면 대형 수입사 상품이 전부 노란불이 되고, 그러면 셀러가
    # 노란불을 무시하게 된다 - HAZARD_RULE_APPLIES 를 0 으로 둔 것과 같은 논리.
    # _HARD_RED 와 AMBER 집합에도 넣지 않는다 (아래 _signal_for 참조).
    FindingKind.MAKER_OTHER_RECALLS: 0,
    # 0 이다. 약한 일치는 제조사와 제품명 단어가 겹쳤을 뿐 모델명·인증번호가
    # 맞은 것이 아니다. 점수를 깎으면 흔한 단어를 쓴 상품이 전부 노란불이 되고,
    # 그러면 셀러가 노란불을 무시한다 - MAKER_OTHER_RECALLS 와 같은 논리다.
    FindingKind.RECALL_WEAK_MATCH: 0,
    # 0 이다. 아직 조회하지 않았다. 조회 전에 점수를 깎으면 이미지에 인증을
    # 붙여둔 상품이 안 붙인 상품보다 불리해지고, 그건 거꾸로다.
    FindingKind.KC_IMAGE_CANDIDATE: 0,
    # 0 이다. "다른 법 소관 가능성이 있어 등급을 판단하지 않았다" 는 우리가
    # 모른다는 말이고 위험 발견이 아니다. 점수를 깎으면 **모른다는 사실이
    # 위험으로 읽힌다** - R3 을 정면으로 어긴다.
    FindingKind.SCOPE_UNDETERMINED: 0,
}

# ⚠⚠ **모든 kind 가 이 표에 있어야 한다. 없으면 `score()` 가 KeyError 를 던진다.**
#
#   `score()` 는 `sum(_PENALTY[f.kind] for f in findings)` 로 감점을 모으므로,
#   새 kind 를 추가하고 여기 안 넣으면 **그 finding 이 나오는 모든 스캔이
#   500 이 된다.** 2026-09-11 에 `SCOPE_UNDETERMINED` 를 추가하며 실제로 겪었다.
#
# ⚠ `.get(kind, 0)` 으로 바꾸지 않는다. 그러면 KeyError 는 없어지지만 **감점이
#   필요한 kind 를 추가했을 때 조용히 0** 이 되고, 위험을 놓치는 쪽으로 조용히
#   틀린다. 시끄럽게 깨지는 것이 낫다.
#
# ⚠ 그래서 **임포트 시점에** 단정한다. 검사를 안 돌려도 앱이 부팅할 때 터지므로
#   배포본이 500 을 내기 전에 드러난다. 부팅 실패가 런타임 500 보다 낫다.
_MISSING_PENALTY = set(FindingKind) - set(_PENALTY)
if _MISSING_PENALTY:  # pragma: no cover - 부팅 시점에 걸린다
    raise RuntimeError(
        "_PENALTY 에 없는 FindingKind 가 있습니다 - score() 가 KeyError 를 던집니다: "
        + ", ".join(sorted(k.value for k in _MISSING_PENALTY))
    )

_HARD_RED = {
    # RED 는 정부 DB 가 문제를 적어둔 경우에만 준다. 부재는 증거가 아니다.
    #
    # KC_EXPIRED 도 여기 없다. 기간만료·반납은 정부 DB 가 "문제가 있다" 고 적은
    # 것이 아니라 인증의 수명이 끝났다고 적은 것이다. 완구 인증의 67% 가
    # 기간만료여서(2026-09-01 실측) RED 로 두면 정상 상품 대부분에 빨간불이 뜬다.
    #
    # KC_NOT_FOUND 는 여기 없다. 전안법은 위해도 4단계이고 가장 낮은
    # 공급자적합성확인(SCoC) 대상은 제조·수입자가 스스로 시험해 확인하므로
    # 조회 DB 에 번호가 없는 것이 정상이다. 미조회를 RED 로 두면 정상 상품에
    # 반복해서 빨간불이 뜨고, 셀러가 모든 RED 를 무시하게 된다. 그러면 진짜
    # 취소된 인증도 안 보게 된다.
    #
    # RECALL_WEAK_MATCH 도 여기 없다. 약한 일치는 정부 DB 가 "이 상품에 문제가
    # 있다" 고 적은 것이 아니라 우리가 제조사·제품명 단어로 추정한 것이다.
    # RED 로 두면 무관한 상품에 빨간불이 반복되고("펜을 검사했는데 블라인드가
    # 뜬다"), 셀러가 모든 RED 를 무시하게 된다.
    FindingKind.RECALL_MATCH,
    FindingKind.KC_REVOKED,
    FindingKind.KC_SUSPENDED,
    # 부적합 방송통신기자재 현황. 전파인증 축에서 유일하게 정부가 문제를
    # 적어둔 소스다 (R3-b).
    FindingKind.RF_NONCOMPLIANT,
}

_REGULATED = {
    ItemCategory.CHILDREN_TOY,
    ItemCategory.CHILDREN_STATIONERY,
    ItemCategory.CHILDREN_TEXTILE,
    ItemCategory.ELECTRICAL,
}


# 신호를 셀러의 소싱 판단 언어로 옮긴 한 줄. 시스템 상태가 아니라 "그래서
# 소싱해도 되나?" 에 답한다. GREEN 은 "판매자 제공 정보 기준" 을 명시해
# 안전 보증으로 읽히지 않게 한다 (§6.1).
_HEADLINE: dict[Signal, str] = {
    Signal.GREEN: "소싱 가능 — 판매자 제공 정보 기준으로 리콜·인증 문제가 확인되지 않습니다. 실제 검증은 시험성적서로 이루어집니다.",
    Signal.AMBER: "확인 후 소싱 — 공급처에 아래 항목을 확인한 뒤 판단하세요.",
    Signal.RED: "소싱 보류 — 리콜 또는 인증 문제가 확인되었습니다. 아래 근거를 확인하세요.",
    Signal.UNKNOWN: "판단 보류 — 판매자 제공 정보만으로는 소싱 여부를 가릴 수 없습니다. 아래 확인 항목을 공급처에 요청하세요.",
}


# UNKNOWN 은 이유가 여럿인데 문구가 하나면 셀러가 "아무것도 못 하는 서비스" 로
# 읽는다. 실제로 프로덕션에 실입력을 넣으면 같은 "판단 보류" 가 반복해서 나온다.
#
# 특히 연령 표기로 대상이 아닌 경우는 우리가 판단을 **한** 것이다. 그걸
# "가릴 수 없습니다" 라고 말하면 한 판단을 안 한 것처럼 스스로 깎아내린다.
#
# 순서가 곧 우선순위다. 위에서 먼저 걸리는 사유가 헤드라인을 가져간다.
# "우리 소관이 아니다" · "연령 기준으로 대상이 아니다" 는 품목 자체에 대한
# 확정된 판단이라 무엇보다 먼저 말한다. 그 뒤에 "번호 부재가 정상" 이 오고,
# 우리 수록 범위(COVERAGE_GAP)·조회 실패는 그다음이다.
_UNKNOWN_HEADLINE_FIRST: list[tuple[FindingKind, str]] = [
    (
        FindingKind.OUT_OF_SCOPE,
        "본 서비스 범위 밖 — 식품·화장품 등은 식약처 등 다른 부처 소관입니다. "
        "해당 기준으로 확인하세요.",
    ),
    (
        FindingKind.AGE_OUT_OF_CHILD_RANGE,
        "대상 아님 — 표기된 사용연령 기준으로는 어린이제품 안전기준 대상이 "
        "아닙니다. 실사용 연령이 13세 이하이면 대상이 될 수 있으니 표기 근거를 확인하세요.",
    ),
]

_UNKNOWN_HEADLINE: list[tuple[FindingKind, str]] = [
    (
        FindingKind.COVERAGE_GAP,
        "일부만 확인 — 인증·리콜은 대조했으나, 이 품목의 유해물질 기준은 아직 "
        "수록되지 않았습니다. 확인된 범위는 아래를 보세요.",
    ),
    # 조회 실패는 맨 뒤다. 축 하나가 빠진 것이지 품목 판단 자체를 못 한 것이
    # 아니라서, "대상 아님" 같이 확정된 판단이 있으면 그쪽을 먼저 말해야 한다.
    (
        FindingKind.LOOKUP_FAILED,
        "확인 미완료 — 정부 조회 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    ),
]

_UNKNOWN_NO_INPUT = (
    "입력 확인 — 상품 정보를 읽지 못했습니다. 상품 상세페이지의 '상품정보' 표를 "
    "붙여넣으면 확인해 드립니다."
)


def _absence_expected_headline(kinds: set[FindingKind], grade: str) -> str:
    """"번호가 없는 것이 정상" 을 헤드라인이 말한다.

    finding 안에만 묶어 두면 첫 줄만 읽는 셀러가 못 본다. 정상 상품에 회색·
    노란불이 반복되면 셀러가 모든 경고를 무시하게 되고, 그게 R3-b 가 막으려던
    상태다.

    주의: 면제 표현을 쓰지 않는다. "인증이 필요 없다" 는 틀리다 - 제조·수입자
      가 스스로 시험해 확인할 의무가 있다. 정확한 표현은 "조회 DB 에 번호가
      없는 것이 정상" 이다.

    리콜 문구는 실제로 대조했을 때만 붙인다. 조회에 실패했으면 대조하지
    않은 것을 대조했다고 말할 수 없다 (R3).
    """
    if FindingKind.RECALL_CLEAR in kinds:
        recall = " 리콜 이력도 확인되지 않았습니다."
    elif FindingKind.LOOKUP_FAILED in kinds:
        recall = " 다만 리콜 조회에는 연결하지 못했습니다."
    else:
        recall = ""
    gap = (
        " 이 품목의 유해물질 기준은 아직 수록되지 않았습니다."
        if FindingKind.COVERAGE_GAP in kinds
        else ""
    )
    return (
        f"인증번호 부재가 정상 — 이 품목은 {grade} 대상으로, 정부 조회 DB 에 "
        f"번호가 없는 것이 정상입니다.{recall}{gap} "
        "다만 실제 안전성은 시험성적서로 확인됩니다."
    )


def _unknown_headline(
    kinds: set[FindingKind], has_extracted: bool, *, absence_grade: str | None = None
) -> str:
    """UNKNOWN 의 사유를 헤드라인으로 옮긴다.

    같은 회색불이라도 "대상이 아니다" 와 "정보가 부족하다" 와 "우리 범위 밖이다"
    는 셀러에게 전혀 다른 정보다. 뭉뚱그리면 전부 실패로 읽힌다.
    """
    if not has_extracted:
        return _UNKNOWN_NO_INPUT
    # "범위 밖" · "연령 기준 대상 아님" 은 더 확정된 판단이라 먼저 말한다.
    # 그 둘이 아니면 "번호 부재가 정상" 이 먼저다 - 셀러의 즉각적인 걱정이
    # "번호가 없는데 팔아도 되나" 이고, 우리 수록 범위(COVERAGE_GAP)보다
    # 그 답이 급하다. 수록 범위는 같은 헤드라인 안에 덧붙인다.
    for kind, text in _UNKNOWN_HEADLINE_FIRST:
        if kind in kinds:
            return text
    if absence_grade and FindingKind.KC_ABSENCE_EXPECTED in kinds:
        return _absence_expected_headline(kinds, absence_grade)
    for kind, text in _UNKNOWN_HEADLINE:
        if kind in kinds:
            return text
    return _HEADLINE[Signal.UNKNOWN]


# 신호마다 워치리스트를 권하는 이유가 다르다. 핵심은 GREEN 이다 - 부재의
# 증명이라 가장 약한 신호이므로, "지금 괜찮음" 의 유효기간을 워치리스트가
# 이어받는다. OUT_OF_SCOPE 는 우리 소관이 아니므로 감시를 권하지 않는다.
_WATCH_REASON: dict[Signal, str] = {
    Signal.GREEN: (
        "지금은 리콜·인증 문제가 없지만, 이는 조회 시점 기준입니다. "
        "이 상품을 감시 목록에 넣으면 나중에 리콜이 공표될 때 가장 먼저 알려드립니다."
    ),
    Signal.AMBER: (
        "공급처에 확인하는 동안 이 상품을 감시 목록에 넣어두면, "
        "그 사이 리콜이 공표되어도 놓치지 않습니다."
    ),
    Signal.RED: (
        "이미 문제가 확인된 상품이지만, 감시 목록에 넣으면 이후 추가 리콜도 알려드립니다."
    ),
    Signal.UNKNOWN: (
        "판단에 필요한 정보가 부족합니다. 감시 목록에 넣으면 이후 리콜 공표 시 알려드립니다."
    ),
}


# 각 화면 구획의 제목. 셀러가 "무엇부터 봐야 하나" 를 안다.
_GROUP_HEADER: dict[FindingGroup, str] = {
    FindingGroup.ACTION: "소싱하려면 확인할 것",
    FindingGroup.FINDING: "확인된 문제",
    FindingGroup.CONTEXT: "참고 정보",
}


def _grouped_findings(findings: list[Finding]) -> list[dict]:
    """finding 을 셀러 관점 구획으로 묶는다.

    리콜·인증 결과보다 '확인할 것' 을 앞에 둔다. 소싱 셀러는 리콜 조회가 아니라
    '이거 팔려면 뭘 준비하나' 를 먼저 알고 싶다. 빈 구획은 넣지 않는다.
    """
    out: list[dict] = []
    for group in (FindingGroup.ACTION, FindingGroup.FINDING, FindingGroup.CONTEXT):
        items = [f for f in findings if f.group is group]
        if items:
            out.append({"group": group.value, "header": _GROUP_HEADER[group], "findings": items})
    return out


def _extracted_fields(facts: ProductFacts) -> list[ExtractedField]:
    """페이지에서 읽은 값을 화면 표시용으로 정리한다.

    판정 위에 이걸 먼저 보여줘야 셀러가 "제대로 읽었네" 를 믿는다. 인증번호는
    정부 조회 링크를 붙여, 그 번호가 맞는지 직접 확인할 수 있게 한다. 빈 값은
    넣지 않는다 - 못 읽은 것을 읽은 것처럼 채우지 않는다.
    """
    from .kats_client import cert_evidence_url

    out: list[ExtractedField] = []
    if facts.product_name:
        out.append(ExtractedField(label="제품명", value=facts.product_name))
    if facts.model_name:
        out.append(ExtractedField(label="모델명", value=facts.model_name))
    if facts.maker:
        out.append(ExtractedField(label="제조사", value=facts.maker))
    for num in facts.kc_numbers:
        out.append(ExtractedField(label="인증번호", value=num, link=cert_evidence_url(num)))
    # 이미지에서 읽은 번호는 라벨을 달리 준다. 같은 "인증번호" 로 보이면 셀러가
    # 이미 조회된 것으로 읽고, 확인 단계를 건너뛴다.
    for num in facts.kc_numbers_from_image:
        out.append(
            ExtractedField(
                label="인증번호 (이미지에서 읽음)", value=num, link=cert_evidence_url(num)
            )
        )
    if facts.target_age:
        out.append(ExtractedField(label="사용연령", value=facts.target_age))
    if facts.materials:
        out.append(ExtractedField(label="재질", value=", ".join(facts.materials)))
    if facts.category is not ItemCategory.UNCLASSIFIED:
        out.append(ExtractedField(label="품목 구분", value=facts.category.label_ko))
    return out


def _input_note(extracted: list[ExtractedField]) -> str | None:
    """읽은 값이 하나도 없으면 그건 상품 문제가 아니라 입력 문제다.

    "이 페이지에서 이렇게 읽었습니다" 블록이 통째로 비는 경우다. 그대로 두면
    화면은 "판단 보류 — 판매자 제공 정보만으로는 소싱 여부를 가릴 수 없습니다"
    로 끝나는데, 셀러는 그 문장을 상품에 대한 판정으로 읽는다. 실제로는 URL
    한 줄이나 배송 안내만 붙여넣은 것일 수 있고, 그건 다시 붙여넣으면 풀린다.

    판정은 그대로 둔다 (R3: 못 읽었으면 UNKNOWN 이다). 원인만 말해준다.
    """
    if extracted:
        return None
    return (
        "상품 정보를 하나도 읽지 못했습니다. 상품 상세페이지 내용을 붙여넣으셨나요? "
        "상품명·모델명·재질·KC 인증번호가 들어가도록 본문을 그대로 복사해 주세요. "
        "상세표가 이미지뿐이면 캡처를 붙여넣어도 됩니다."
    )


def _watch_suggestion(facts: ProductFacts, signal: Signal, kinds: set[FindingKind]) -> WatchSuggestion:
    # 감시할 단서가 있어야 약속을 지킬 수 있다. WatchItem.is_matchable 과 같은 기준.
    can_watch = bool(
        facts.model_name
        or facts.kc_numbers
        or (facts.maker and facts.product_name)
    )
    # 소관 밖은 우리가 리콜을 대조하지 않으므로 감시를 권하지 않는다.
    if FindingKind.OUT_OF_SCOPE in kinds:
        can_watch = False
        reason = "이 품목은 본 서비스가 리콜을 대조하는 범위 밖입니다."
    elif not can_watch:
        reason = "감시할 단서(모델명·인증번호·제조사)가 부족해 리콜 감시를 걸 수 없습니다."
    else:
        reason = _WATCH_REASON[signal]
    return WatchSuggestion(can_watch=can_watch, reason=reason)


def score(
    facts: ProductFacts,
    findings: list[Finding],
    *,
    recall_data_as_of: str | None = None,
    # 우리가 마지막으로 동기화한 시각(ISO). 정부 공표일과 다른 값이다 -
    # "2026-09-04 공표분까지" 만 적으면 셀러가 "3일 전 데이터" 로 읽는다.
    # 주말·공휴일에는 공표가 없으므로 공표일은 며칠 전이 정상이다.
    recall_synced_at: str | None = None,
    # ⚠ scorer 는 순수 함수다 - 현재시각을 스스로 읽지 않는다 (CLAUDE.md §6).
    #   "오늘 갱신" 을 말하려면 오늘이 언제인지 부르는 쪽이 알려줘야 한다.
    today: "date | None" = None,
    # 이 스캔이 어떻게 나왔나. 판정에 쓰지 않는다 - 그대로 실어 보낸다.
    meta: "ScanMeta | None" = None,
) -> ScanResult:
    """Combine findings into a display score and a signal.

    The score is a UI affordance, not a legal judgement. The signal is what
    matters and it is derived from findings, never from the score alone.
    """
    # 근거가 약한 리콜 매칭의 색을 먼저 내린다 (4-d-2). 문구는 그대로다.
    findings = downgrade_unqualified_recall_reds(facts, findings)

    kinds = {f.kind for f in findings}

    # --- 소관 안내가 병기인가 단독인가 (4-d-1) -----------------------------
    #
    # 병기(`standalone=False`)면 **신호·헤드라인·감시권유·수록범위 안내에서
    # 없는 것처럼 본다.** 화면에는 그 줄이 그대로 남는다 - 색만 바뀌는 것이
    # 아니라 "덮지 않는다" 는 뜻이다.
    #
    # ⚠ 왜 kinds 에서 빼는가. 이 아래 다섯 곳이 `OUT_OF_SCOPE in kinds` 를
    #   보고 각자 덮는다(_signal_for · 헤드라인 · _unknown_headline ·
    #   _watch_suggestion · _coverage_note). 다섯 군데 조건을 따로 고치면
    #   한 곳을 빼먹고, 그 한 곳이 5건을 침묵시킨 그 결함이다. 입구에서 한 번
    #   가른다.
    #
    # ⚠ 감점은 원래 0 이므로 점수는 움직이지 않는다(_PENALTY).
    #   `_grouped_findings`·`_axes` 는 findings 를 직접 보므로 그 줄이 화면에서
    #   사라지지 않는다.
    #
    # ⚠ 판정은 verifier 가 아니라 여기서 한다고 착각하지 말 것 - verifier 가
    #   "단독이냐" 라는 **사실**(등급이 붙었는가)을 detail 에 적고, scorer 는
    #   그 사실로 신호를 정한다. R1 의 경계 그대로다.
    if FindingKind.OUT_OF_SCOPE in kinds:
        co_listed = all(
            f.detail.get("standalone") is False
            for f in findings
            if f.kind is FindingKind.OUT_OF_SCOPE
        )
        if co_listed:
            kinds = kinds - {FindingKind.OUT_OF_SCOPE}

    penalty = sum(_PENALTY[f.kind] for f in findings)
    value = max(0, 100 - penalty)

    signal = _signal_for(facts, kinds, findings)
    if signal is Signal.UNKNOWN:
        # Do not present a reassuring number next to "we don't know".
        value = 0

    # 헤드라인이 추출 결과를 참조하므로 먼저 만든다 — 읽은 게 하나도 없으면
    # "판단 보류" 가 아니라 "입력 확인" 이라고 말해야 한다.
    extracted = _extracted_fields(facts)

    if signal is Signal.UNKNOWN:
        # 부재가 정상인 등급은 finding 의 detail 에 있다. scorer 는 여전히
        # 순수 함수다 - 주어진 findings 만 읽는다.
        absence_grade = next(
            (
                f.detail.get("grade")
                for f in findings
                if f.kind is FindingKind.KC_ABSENCE_EXPECTED and f.detail.get("grade")
            ),
            None,
        )
        headline = _unknown_headline(
            kinds, has_extracted=bool(extracted), absence_grade=absence_grade
        )
    else:
        headline = _HEADLINE[signal]
    if FindingKind.OUT_OF_SCOPE in kinds:
        headline = (
            "본 서비스 범위 밖 — 식품·화장품 등은 식약처 등 다른 부처 소관입니다. "
            "해당 기준으로 확인하세요."
        )

    return ScanResult(
        signal=signal,
        headline=headline,
        score=value,
        facts=facts,
        findings=findings,
        coverage_note=_coverage_note(facts, kinds),
        watch_suggestion=_watch_suggestion(facts, signal, kinds),
        extracted=extracted,
        input_note=_input_note(extracted),
        grouped_findings=_grouped_findings(findings),
        axes=_axes(findings, recall_data_as_of, recall_synced_at, today),
        recall_data_as_of=recall_data_as_of,
        # ⚠ 판정에 쓰지 않는다. `_signal_for` 도 `_HEADLINE` 도 meta 를 보지
        #   않는다 - 추출 경로가 신호를 바꾸면 "휴리스틱이면 더 위험" 같은
        #   판정을 하게 되고, 그것은 R1 위반이다.
        meta=(
            meta.model_copy(update={"recall_data_as_of": recall_data_as_of})
            if meta is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# 리콜 매칭이 RED 자격이 있는가 (4-d-2)
# ---------------------------------------------------------------------------
#
# 실측 (A-5 · 대상 109건): 상품명만 조건은 RED 0건이었는데 상세를 넣자
# `model_name` 추출이 16 → 104건으로 6.5배가 되고 리콜 모델명 매칭이 생겼다.
# RED 5건 중 3건이 **품목이 다른 우연 충돌**이었다:
#
#     [44] LED 무드등·스피커   모델명 '레인보우'   ↔ 리콜 품목 승차용 안전모
#     [48] 차량용 핸디청소기   모델명 '진공 청소기' ↔ 리콜 품목 전지(충전지)
#     [97] 어린이 무릎보호대   모델명 'hope'       ↔ 리콜 품목 전기자전거
#
# 문구는 R6 대로 "유사 일치 … 원문 확인이 필요합니다" 다. 문제는 **신호가
# RED** 라는 점이고, R3-b 가 금지한 "항상 켜지는 경고" 에 그대로 걸린다 -
# 정상 상품에 빨간불이 반복되면 셀러가 [67]·[137] 의 진짜 인증취소도 안 보게
# 된다.
#
# ⚠ **3자 미만 모델명을 빼는 R6 의 가드는 여기서 듣지 않는다.** `레인보우`(4자)
#   `hope`(4자) `진공 청소기`(6자) 가 전부 통과한다. 길이가 아니라 **품목**이
#   문제다.
#
# 그래서 RED 자격을 이렇게 둔다:
#
#     (a) 인증번호 일치                        - 번호가 같다. 추정이 아니다
#     (b) 모델명 일치 + (제조사 일치 or 품목 일치)
#     (c) 인증상태 취소·정지 (KC_REVOKED · KC_SUSPENDED - 이 함수 밖)
#
# **모델명만 맞은 것**은 AMBER 다. 근거 줄은 그대로 남고 색만 바뀐다.
#
# ⚠ 구현은 "자격이 있으면 RED" 가 아니라 **"모델명만 맞았다고 확실히 알 때만
#   내린다"** 다. 방향이 중요하다 - `matched_on` 이 비어 있는 것은 근거가 약한
#   것이 아니라 코드 공백이고, 그때 조용히 색을 내리면 진짜 리콜을 놓치는 쪽으로
#   틀린다.
#
# ⚠⚠ **워치리스트 sweep 은 건드리지 않는다.** R6 이 못 박아 뒀다 - 스캔에서는
#   잘못 안심시키는 것이 비싼 오류이지만 **알림에서는 놓친 알림이 우리가 하는
#   유일한 약속을 깨뜨린다.** 그래서 둘의 오류 비대칭이 반대다:
#
#       스캔(여기)        약한 근거로 RED 를 주면 셀러가 모든 RED 를 무시한다
#       sweep(watchlist)  약한 일치도 알린다. MatchStrength 를 함께 노출한다
#
#   `watchlist.sweep()` 은 `verify()`·`score()` 를 거치지 않는 별개 경로이고
#   자기 `MatchStrength` 로 판단한다. 이 변경이 거기 닿지 않는다 - 그것이
#   의도다. 두 곳을 한 규칙으로 묶으려는 다음 사람은 R6 을 먼저 읽을 것.
#
# ⚠ `KC_EXPIRED` 는 여기에도 위 `_HARD_RED` 에도 **넣지 않았다.** 기간만료·반납은
#   정부 DB 가 "문제가 있다" 고 적은 것이 아니라 인증의 수명이 끝났다고 적은
#   것이고, 완구 인증의 67% 가 기간만료다(2026-09-01 실측). RED 로 두면 정상
#   상품 대부분에 빨간불이 뜬다.


def _norm_name(value: str | None) -> str:
    """품목·제조사 비교용. 공백·기호를 지운다.

    ⚠ 기호를 지우는 이유는 리콜 원문이 `전지(충전지만 해당)` 처럼 괄호를 쓰고
      우리 쪽은 `전지` 로 오기 때문이다. 숫자·영문은 남긴다 - 모델명이 아니라
      품목명 비교이므로 우연 충돌보다 놓침이 더 비싸다.
    """
    if not value:
        return ""
    return re.sub(r"[\s\-_/·,.()\[\]{}]+", "", unicodedata.normalize("NFKC", value)).upper()


def _our_item_names(facts: ProductFacts, findings: list[Finding]) -> set[str]:
    """우리가 이 상품을 무엇으로 봤는가. 등급 후보 + 법령 품목명."""
    names = {facts.legal_item_name or ""}
    for f in findings:
        for cand in (f.detail or {}).get("candidates", []) or []:
            item = cand.get("item") if isinstance(cand, dict) else None
            if item:
                names.add(item)
    return {n for n in names if n}


def _overlaps(a: str | None, b: str | None) -> bool:
    """정규화 후 한쪽이 다른 쪽을 담고 있으면 겹친 것으로 본다."""
    x, y = _norm_name(a), _norm_name(b)
    if not x or not y:
        return False
    return x in y or y in x


def recall_match_earns_red(
    facts: ProductFacts, findings: list[Finding], finding: Finding
) -> bool:
    """이 리콜 매칭에 RED 를 줄 수 있는가.

    ⚠ **기본값은 RED 다.** 내리는 것은 "모델명만 맞았다" 를 **확실히 아는**
      경우 하나뿐이다.

      처음에는 반대로 짰다 - (a)·(b) 에 해당할 때만 RED. 그러면 `matched_on`
      이 비어 있는 finding 이 조용히 AMBER 로 내려간다. 그건 **근거가 약한
      것이 아니라 코드 공백**이다(그 축을 만든 곳이 detail 을 안 채운 것).
      조용히 신호를 낮추면 진짜 리콜을 놓치는 쪽으로 틀리므로, 모르면 시끄러운
      쪽으로 둔다 - "미조회를 GREEN 으로 반올림하지 않는다"(R3)와 같은 방향이다.
      실제로 검사 5개가 이 차이에서 깨졌다.
    """
    detail = finding.detail or {}
    if detail.get("matched_on") != "model_name":
        return True

    # ⚠ **모델명 칸에 품목명이 들어온 경우는 모델명 축을 쓰지 않는다** (4-가).
    #
    #   실측 [48] 차량용 무선 휴대용 핸디 청소기 · `model_name='진공 청소기'`.
    #   그것으로 리콜 모델명을 대조하면 같은 품목의 아무 리콜에나 걸린다 -
    #   4건에 걸렸고 그중 셋은 리콜 품목이 `전지(충전지만 해당)` 였다. 4번째는
    #   리콜 품목이 `진공청소기` 여서 아래 품목 일치를 통과해 RED 가 됐다.
    #   즉 "품목이 같으니 RED" 인데 **모델명이 품목명이므로 그 일치는 정보가
    #   아니다.**
    #
    #   목록은 등급표(정부 표)의 품목명과 표 자체의 별칭이다. "무엇이
    #   일반명사인가" 를 우리가 정하지 않는다 (R1). 판정은 verifier 가
    #   `matched_value_names_an_item` 으로 적어 준다 - scorer 는 순수 함수라
    #   YAML 을 읽지 않는다.
    #
    # ⚠ 버리지는 않는다. finding 은 그대로 나오고 문구도 그대로다. 색만 내린다.
    # ⚠ 워치리스트 sweep 은 건드리지 않는다 (R6) - 위 머리 주석 참조.
    if detail.get("matched_value_names_an_item"):
        return False

    if _overlaps(facts.maker, detail.get("maker")):
        return True
    recalled = detail.get("recalled_product_name")
    return any(_overlaps(name, recalled) for name in _our_item_names(facts, findings))


def downgrade_unqualified_recall_reds(
    facts: ProductFacts, findings: list[Finding]
) -> list[Finding]:
    """자격 없는 리콜 매칭의 **색만** 내린다. 문구·근거는 그대로 (R6)."""
    out: list[Finding] = []
    for f in findings:
        if (
            f.kind is FindingKind.RECALL_MATCH
            and f.signal is Signal.RED
            and not recall_match_earns_red(facts, findings, f)
        ):
            out.append(f.model_copy(update={"signal": Signal.AMBER}))
        else:
            out.append(f)
    return out


def gov_lookup_state(findings: list[Finding]) -> dict[str, str]:
    """**이 스캔**에서 정부 조회가 됐나. 축별로 셋 중 하나다 (4-p).

        ok              조회해서 답을 받았다
        failed          조회를 시도했는데 실패했다
        not_attempted   조회할 것이 없었다 (번호가 없거나 대조 대상이 없음)

    ⚠⚠ **"조회했더니 없다" 와 "조회를 못 했다" 는 다르다.** 이것이 R3 의
      핵심이고 화면이 반드시 갈라야 하는 것이다. 실증이 있다 - 같은 스크립트를
      키 있는 환경과 없는 환경에서 돌리면 인증 축이 이렇게 갈린다:

          키 있음   kc_verified 22 · expired 6 · revoked 2 · not_found 2  = 32
          키 없음   kc_not_found 32                                        = 32

      **합이 같고 그림이 정반대다.** 후자만 보면 "조회했더니 32건이 없더라" 로
      읽히는데 실제로는 조회 자체를 못 한 것이다.

    ⚠ `/healthz` 의 `kats` 는 **프로세스 누적값**이라 "이 결과" 를 말하지
      못한다. [B-백] 의 `extraction` 과 같은 이유로 스캔 응답에 따로 넣는다.

    ⚠ 순수 함수다 - 주어진 findings 만 읽는다. `_axes` 와 같은 신호를 보지만
      화면 문구가 아니라 **기계가 읽는 상태값**을 준다.
    """
    kinds = {f.kind for f in findings}
    failed_scopes = {
        str((f.detail or {}).get("scope") or "")
        for f in findings
        if f.kind is FindingKind.LOOKUP_FAILED
    }

    if "인증" in failed_scopes:
        cert = "failed"
    elif kinds & {
        FindingKind.KC_VERIFIED, FindingKind.KC_NOT_FOUND, FindingKind.KC_UNDER_ACTION,
        FindingKind.KC_REVOKED, FindingKind.KC_EXPIRED, FindingKind.KC_SUSPENDED,
    }:
        cert = "ok"
    else:
        cert = "not_attempted"

    if "리콜" in failed_scopes:
        recall = "failed"
    elif kinds & {
        FindingKind.RECALL_MATCH, FindingKind.RECALL_WEAK_MATCH,
        FindingKind.RECALL_CLEAR, FindingKind.MAKER_OTHER_RECALLS,
    }:
        recall = "ok"
    else:
        recall = "not_attempted"

    # ⚠ scope 문자열은 `verifier._lookup_failed(...)` 의 첫 인자다. 실제 값은
    #   "인증" · "리콜" · **"전파인증"** 셋이다 - 처음에 "전파" 로 적었다가
    #   실측에서 틀렸다(그러면 RF 조회 실패가 not_attempted 로 잘못 보인다).
    #   아래 검사가 이 셋을 verifier 소스와 대조한다.
    if "전파인증" in failed_scopes:
        rf = "failed"
    elif kinds & {
        FindingKind.RF_CERT_VERIFIED, FindingKind.RF_CERT_NOT_FOUND,
        FindingKind.RF_NONCOMPLIANT,
    }:
        rf = "ok"
    else:
        rf = "not_attempted"

    return {"cert": cert, "recall": recall, "rf": rf}


def has_specific_finding(findings: list[Finding]) -> bool:
    """이 검사가 셀러에게 **구체적인 것을 하나라도 줬는가** (E).

    ⚠ 순수 함수다 - 세는 것은 부르는 쪽(`main.py`)이 한다. scorer 에 카운터를
      두면 §6 의 "동일 입력 → 동일 출력" 이 깨진다.

    ⚠ **판정에 쓰지 않는다.** 관측 지표일 뿐이다. 신호를 여기에 걸면
      "구체적 finding 이 많으면 위험" 같은 판정이 된다 (R1).

    ⚠ "원문 링크가 붙었나" 로는 아무것도 갈리지 않는다 - 모든 `Finding` 이
      `source_url` 을 갖는다(R2). 갈라야 하는 것은 **이 상품에 대해 무엇을
      말했나** 이고, 그 목록이 `SPECIFIC_FINDING_KINDS` 다.
    """
    return any(f.kind in SPECIFIC_FINDING_KINDS for f in findings)


def _signal_for(
    facts: ProductFacts, kinds: set[FindingKind], findings: list[Finding]
) -> Signal:
    # ⚠ **kind 만 보지 않는다.** `_HARD_RED` 는 "RED 자격이 있는 종류" 이고,
    #   그 종류라도 근거가 약하면 finding 자체가 AMBER 로 내려와 있다
    #   (`downgrade_unqualified_recall_reds`). 종류만 보면 내린 색이 무시된다.
    #
    #   _HARD_RED 의 네 종류는 전부 Signal.RED 로 생성되므로, 내려온 것이
    #   없으면 동작이 전과 같다.
    if any(f.kind in _HARD_RED and f.signal is Signal.RED for f in findings):
        return Signal.RED

    # 조회를 못 했으면 아무것도 확인하지 못한 것이다. GREEN 이 나오면 확인하지
    # 못한 것을 확인한 것처럼 말하게 된다. 지금은 RECALL_CLEAR 가 안 붙어서
    # 자동으로 막히지만, 나중에 GREEN 조건을 완화할 때를 대비해 명시로 막는다.
    if FindingKind.LOOKUP_FAILED in kinds:
        return Signal.UNKNOWN

    # 우리 소관 밖 품목(식품·화장품 등)은 신호를 매기지 않는다. "판별 못 함"이
    # 아니라 "다른 부처 소관"이므로, 안내만 하고 UNKNOWN 으로 둔다.
    if FindingKind.OUT_OF_SCOPE in kinds:
        return Signal.UNKNOWN

    # R3: an unclassified item means we do not know which rules apply.
    if facts.category is ItemCategory.UNCLASSIFIED:
        return Signal.UNKNOWN
    if FindingKind.COVERAGE_GAP in kinds:
        return Signal.UNKNOWN

    if kinds & {
        FindingKind.RF_CERT_NOT_FOUND,
        FindingKind.RF_WIRELESS_UNVERIFIED,
        FindingKind.KC_NOT_FOUND,
        FindingKind.KC_EXPIRED,
        FindingKind.KC_UNDER_ACTION,
        FindingKind.KC_MISSING_BUT_REQUIRED,
        FindingKind.SUBSTANCE_MENTIONED,
    }:
        return Signal.AMBER

    # HAZARD_RULE_APPLIES 는 여기 없다. "이 품목군에 납 기준이 걸린다" 는 적용
    # 범위 안내이지 문제 지적이 아니다 (R3-b 와 같은 논리). 이걸 AMBER 로 두면
    # 완구·학용품·아동섬유가 무엇을 해도 노란불이 되고, 그러면 셀러가 노란불을
    # 무시하게 된다 — SCoC 오탐(48e7787) 때 세운 논리 그대로다. 항상 켜지는
    # 경고는 꺼진 경고와 같다.
    #
    # 대신 상세페이지에 규제 물질이 실제로 적혀 있으면(SUBSTANCE_MENTIONED)
    # 확인해볼 이유가 생긴 것이므로 AMBER 다. 기획서 §3 의 AMBER 정의
    # ("규제 물질 언급 감지")와 일치한다.
    #
    # 초록불에는 점검 범위를 반드시 병기한다 (_coverage_note, 기획서 §6.1).

    # GREEN requires positive evidence on BOTH axes. Silence is not evidence.
    if {FindingKind.KC_VERIFIED, FindingKind.RECALL_CLEAR} <= kinds:
        return Signal.GREEN

    return Signal.UNKNOWN


def _sync_label(synced_at: str | None, today: "date | None") -> str:
    """마지막 동기화 시각을 사람이 읽는 말로. 없으면 빈 문자열.

    ⚠ 순수하다 - today 를 인자로 받는다. 스스로 시계를 읽지 않는다.
    """
    if not synced_at:
        return ""
    try:
        when = datetime.fromisoformat(synced_at)
    except ValueError:
        return ""
    hhmm = when.strftime("%H:%M")
    if today is not None and when.date() == today:
        return f"오늘 {hhmm} 갱신"
    return f"{when.strftime('%Y-%m-%d')} {hhmm} 갱신"


def _axes(
    findings: list[Finding],
    recall_as_of: str | None,
    recall_synced_at: str | None = None,
    today: "date | None" = None,
) -> list[dict]:
    """검사 축 셋의 상태. **우리가 한 행위**를 적는다.

    종합 배지 하나로는 "무엇을 했고 무엇을 못 했는지" 가 안 보인다. 배지가
    "모름" 인데 부제목이 "일부만 확인" 이면 둘이 다른 말을 한다.

    ⚠ **"안전"·"이상 없음" 으로 쓰지 않는다** (기획서 §3.2 · CLAUDE.md §9).
      "리콜 대조함" 이지 "리콜 없음" 이 아니다. 우리는 공표된 목록과 대조했을
      뿐이고, 공표되지 않은 결함은 대조할 수 없다. ✓ 를 크게 쓰면 셀러가
      초록불로 읽는데 그게 우리가 회색불을 택한 이유다.

    ⚠ scorer 는 순수 함수다 - 주어진 findings 만 읽는다.
    """
    kinds = {f.kind for f in findings}
    failed = {
        str((f.detail or {}).get("scope") or "")
        for f in findings
        if f.kind is FindingKind.LOOKUP_FAILED
    }

    # ① 인증 조회
    if "인증" in failed:
        cert = ("조회 실패", False)
    elif kinds & {
        FindingKind.KC_VERIFIED, FindingKind.KC_NOT_FOUND, FindingKind.KC_UNDER_ACTION,
        FindingKind.KC_REVOKED, FindingKind.KC_EXPIRED, FindingKind.KC_SUSPENDED,
    }:
        cert = ("조회함", True)
    else:
        cert = ("번호 없음", False)

    # ② 리콜 대조
    if "리콜" in failed:
        recall = ("조회 실패", False)
    elif kinds & {FindingKind.RECALL_MATCH, FindingKind.RECALL_WEAK_MATCH}:
        recall = ("일치 있음", True)
    elif FindingKind.RECALL_CLEAR in kinds:
        # ⚠⚠ **`RECALL_CLEAR` 가 있을 때만 "대조함" 이다 (4-r).**
        #
        #   전에는 `verifier` 가 `product_name` 만 있어도 `RECALL_CLEAR` 를
        #   붙였고, 그래서 **대조를 안 했는데 이 축이 "대조함 ✅" 으로 떴다.**
        #   실측 233/233 = 100%(상품명만 경로). 그 표시가 거짓 안심의 절반이다.
        #
        #   이제 `RecallIndex.can_compare()` 가 참일 때만 `RECALL_CLEAR` 가
        #   붙으므로 이 분기는 그대로 두어도 맞다 - **여기에 조건을 또 적지
        #   않는다.** 조건이 두 곳에 있었던 것이 그 결함의 원인이었다.
        recall = ("대조함", True)
    else:
        recall = ("대조 못 함", False)

    # ③ 유해물질
    if FindingKind.HAZARD_RULE_APPLIES in kinds:
        hazard = ("수록됨", True)
    else:
        hazard = ("이 품목 미수록", False)

    # 두 값을 함께 적는다. 공표일만 적으면 "3일 전 데이터" 로 읽히는데,
    # 주말·공휴일에는 정부 공표가 없어서 공표일이 며칠 전인 것이 정상이다.
    note = ""
    if recall[1] and recall_as_of and len(recall_as_of) == 8 and recall_as_of.isdigit():
        note = f"{recall_as_of[:4]}-{recall_as_of[4:6]}-{recall_as_of[6:]} 공표분까지"
        synced = _sync_label(recall_synced_at, today)
        if synced:
            note = f"{note} · {synced}"
    as_of = note

    return [
        {"key": "cert", "name": "인증 조회", "label": cert[0], "done": cert[1], "note": ""},
        {"key": "recall", "name": "리콜 대조", "label": recall[0], "done": recall[1],
         "note": as_of},
        {"key": "hazard", "name": "유해물질", "label": hazard[0], "done": hazard[1],
         "note": ""},
    ]


def _coverage_note(facts: ProductFacts, kinds: set[FindingKind]) -> str | None:
    if FindingKind.OUT_OF_SCOPE in kinds:
        return "이 품목은 본 서비스가 다루는 규제 범위 밖입니다. 해당 소관 부처 기준을 확인하세요."
    if FindingKind.AGE_OUT_OF_CHILD_RANGE in kinds:
        return "연령 표기 기준으로는 어린이제품 안전기준 적용 대상이 아닙니다."
    if FindingKind.INFO_REQUEST in kinds and facts.category is ItemCategory.UNCLASSIFIED:
        return "판정에 필요한 정보가 상세페이지에 없습니다. 공급처 확인 항목을 확인해 주세요."
    if facts.category is ItemCategory.UNCLASSIFIED:
        return "품목군을 특정하지 못해 적용 기준을 확정할 수 없습니다."
    if FindingKind.COVERAGE_GAP in kinds:
        return (
            f"현재 규칙 DB는 이 품목(품목군 {facts.category.value})의 유해물질 기준을 "
            "아직 수록하지 않았습니다. 인증·리콜 조회 결과만 반영되었습니다."
        )
    if facts.category not in _REGULATED:
        return "안전인증 의무 대상 여부는 별도 확인이 필요합니다."
    if FindingKind.HAZARD_RULE_APPLIES in kinds:
        # 초록불은 "안 걸린다"는 보증이 아니다 (기획서 §6.1). 우리는 상세페이지
        # 텍스트를 읽고 단속은 실물을 수거해 시험한다. 그 간극을 화면이 말해야 한다.
        return (
            "이 품목에는 유해물질 기준이 적용됩니다. 실제 함유량은 시험성적서로만 "
            "확인되며, 인증번호 도용·상표권·수입요건은 확인 대상이 아닙니다."
        )
    return None
