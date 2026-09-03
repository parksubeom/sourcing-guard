"""Deterministic scoring. No LLM, no I/O, no clock, no randomness.

CLAUDE.md R1: this is the ONLY place a verdict is produced.
CLAUDE.md R3: absence of data yields UNKNOWN, never GREEN.
"""

from __future__ import annotations

from .models import Finding, FindingKind, ProductFacts, ScanResult, Signal, ItemCategory, WatchSuggestion, ExtractedField, FindingGroup

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
}

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
        "일부만 확인 — 인증·리콜은 대조했으나, 이 품목군의 유해물질 기준은 아직 "
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
        " 이 품목군의 유해물질 기준은 아직 수록되지 않았습니다."
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
) -> ScanResult:
    """Combine findings into a display score and a signal.

    The score is a UI affordance, not a legal judgement. The signal is what
    matters and it is derived from findings, never from the score alone.
    """
    kinds = {f.kind for f in findings}

    penalty = sum(_PENALTY[f.kind] for f in findings)
    value = max(0, 100 - penalty)

    signal = _signal_for(facts, kinds)
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
        recall_data_as_of=recall_data_as_of,
    )


def _signal_for(facts: ProductFacts, kinds: set[FindingKind]) -> Signal:
    if kinds & _HARD_RED:
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
    # 무시하게 된다 — SCoC 오탐(7a6fd70) 때 세운 논리 그대로다. 항상 켜지는
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
            f"현재 규칙 DB는 이 품목군({facts.category.value})의 유해물질 기준을 "
            "아직 수록하지 않았습니다. 인증·리콜 조회 결과만 반영되었습니다."
        )
    if facts.category not in _REGULATED:
        return "안전인증 의무 대상 여부는 별도 확인이 필요합니다."
    if FindingKind.HAZARD_RULE_APPLIES in kinds:
        # 초록불은 "안 걸린다"는 보증이 아니다 (기획서 §6.1). 우리는 상세페이지
        # 텍스트를 읽고 단속은 실물을 수거해 시험한다. 그 간극을 화면이 말해야 한다.
        return (
            "이 품목군에는 유해물질 기준이 적용됩니다. 실제 함유량은 시험성적서로만 "
            "확인되며, 인증번호 도용·상표권·수입요건은 확인 대상이 아닙니다."
        )
    return None
