"""Domain schemas.

R2 (CLAUDE.md): every Finding MUST carry a verifiable source. This is enforced
at construction time, not at render time, so there is no code path that can
produce an unsourced claim.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Signal(str, Enum):
    RED = "RED"
    AMBER = "AMBER"
    GREEN = "GREEN"
    UNKNOWN = "UNKNOWN"


class ItemCategory(str, Enum):
    """Regulatory category. Drives which rule set applies."""

    CHILDREN_TOY = "children_toy"            # 완구
    CHILDREN_STATIONERY = "children_stationery"  # 학용품
    CHILDREN_TEXTILE = "children_textile"    # 아동용 섬유제품
    ELECTRICAL = "electrical"                # 전기용품
    HOUSEHOLD = "household"                  # 생활용품
    # 공통안전기준 1항이 명시적으로 제외하는 물품. 식약처 등 다른 부처 소관이다.
    # "판별 못 함"(UNCLASSIFIED)과 "우리 소관 아님"은 셀러에게 전혀 다른 정보다.
    OUT_OF_SCOPE = "out_of_scope"
    UNCLASSIFIED = "unclassified"

    @property
    def label_ko(self) -> str:
        return {
            "children_toy": "완구",
            "children_stationery": "학용품",
            "children_textile": "아동용 섬유제품",
            "electrical": "전기용품",
            "household": "생활용품",
            "out_of_scope": "본 서비스 범위 밖",
            "unclassified": "품목 미확정",
        }[self.value]


# ---------------------------------------------------------------------------
# Stage 1 output: extraction only. Deliberately contains NO verdict field.
# ---------------------------------------------------------------------------
class ProductFacts(BaseModel):
    """What the LLM extracted from the page. Facts only, never judgements."""

    product_name: str | None = None
    model_name: str | None = None
    maker: str | None = None
    materials: list[str] = Field(default_factory=list)
    substances_mentioned: list[str] = Field(default_factory=list)
    kc_numbers: list[str] = Field(default_factory=list)
    # 이미지(KC 마크)에서 읽은 인증번호 후보. kc_numbers 와 분리해서 담는다.
    #
    # 많은 상세페이지가 KC 마크 이미지만 붙이고 번호를 텍스트로 적지 않는다.
    # 규정상 유효한 기재라, 안 읽으면 실제로는 있는 인증을 "표기 없음" 으로
    # 처리하게 된다 - 못 찾은 것과 찾아보지 않은 것은 다르다 (R3).
    #
    # 그렇다고 kc_numbers 에 바로 넣지는 않는다. 이미지의 0/O·1/l·5/S 오독이
    # 정상 인증을 "미조회" 로 뒤집기 때문이다. 두 겹으로 막는다:
    #   (1) 여기 따로 담고            (2) CERT_NUMBER_RE 로 형식 검증
    # 그리고 화면에서 셀러가 확인·수정한 뒤에야 조회 경로로 들어간다.
    kc_numbers_from_image: list[str] = Field(default_factory=list)
    # 전파인증(적합성평가) 번호. KC 와 완전히 별개 제도라 따로 담는다 -
    # 형식도 다르고(R-C-.../KCC-...) 조회처도 다르다(emsit/RRA).
    rf_numbers: list[str] = Field(default_factory=list)
    # 무선 기능 표기(블루투스·Wi-Fi·무선). 이것이 전파인증 축을 켜는 방아쇠다.
    #
    # ⚠ "무선 표기가 있다" 는 사실이고 "전파인증 대상이다" 는 판정이다. 대상
    #    여부는 고시 별표 1 이 정하며 우리가 판별하지 않는다 (R1). 화면 문구도
    #    "무선 기능 표기가 있습니다" 여야 한다.
    wireless_hints: list[str] = Field(default_factory=list)
    target_age: str | None = None
    category: ItemCategory = ItemCategory.UNCLASSIFIED
    category_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_page_url: str | None = None
    raw_language: Literal["ko", "zh", "en", "mixed", "unknown"] = "unknown"

    model_config = {"extra": "forbid"}  # blocks silent addition of verdict fields


class FindingKind(str, Enum):
    KC_NOT_FOUND = "kc_not_found"
    KC_VERIFIED = "kc_verified"
    # 인증번호가 조회돼도 그 인증이 살아 있다는 뜻은 아니다 (설계서 p.5).
    KC_REVOKED = "kc_revoked"            # 안전인증취소·안전확인신고 효력상실 (처벌)
    # 기간만료·반납은 행정 사유이며 위반이 아니다. 완구 인증의 67% 가 기간만료라
    # RED 로 두면 정상 상품에 빨간불이 반복된다 (CLAUDE.md R3-b).
    KC_EXPIRED = "kc_expired"            # 기간만료·반납
    KC_SUSPENDED = "kc_suspended"        # 표시 사용금지
    KC_UNDER_ACTION = "kc_under_action"  # 개선명령·청문실시
    KC_MISSING_BUT_REQUIRED = "kc_missing_but_required"
    # 이미지에서 읽었고 형식 검증을 통과한 인증번호. 아직 조회하지 않았다 -
    # 셀러가 "이 번호가 맞다" 고 확인한 뒤에 텍스트 경로로 조회한다.
    KC_IMAGE_CANDIDATE = "kc_image_candidate"
    # 공급자적합성확인(SCoC) 대상은 제조·수입자가 스스로 시험해 확인하므로
    # 정부 조회 DB 에 인증번호가 없는 것이 정상이다. 부재를 위반으로 읽으면 안 된다.
    KC_TIER_UNKNOWN = "kc_tier_unknown"
    OUT_OF_SCOPE = "out_of_scope"          # 우리 소관 밖 품목
    AGE_OUT_OF_CHILD_RANGE = "age_out_of_child_range"  # 14세 이상 표기
    INFO_REQUEST = "info_request"          # 공급처에 물어야 할 것
    RECALL_MATCH = "recall_match"
    # 약한 일치(제조사 + 제품명 토큰). 모델명·인증번호가 맞은 것이 아니므로
    # "이 상품이 리콜됐다" 가 아니라 참고 정보다. 버리지는 않는다 - 놓친 알림이
    # 이 서비스가 하는 유일한 약속을 깨뜨린다 (R6). 대신 구획을 가른다.
    RECALL_WEAK_MATCH = "recall_weak_match"
    RECALL_CLEAR = "recall_clear"
    # 같은 제조사의 다른 리콜. 이 상품의 위험이 아니라 공급처를 보는 참고 정보다.
    # 정확 일치만 쓴다 - 포함 매칭은 실측에서 어떤 질의에도 1,600건 이상을 냈다.
    MAKER_OTHER_RECALLS = "maker_other_recalls"
    # 전파인증(적합성평가). KC 와 별개 제도이므로 kind 도 분리한다.
    RF_CERT_VERIFIED = "rf_cert_verified"      # 조회됨
    RF_CERT_NOT_FOUND = "rf_cert_not_found"    # 미조회. 자기적합확인 여지 (R3-b)
    RF_WIRELESS_UNVERIFIED = "rf_wireless_unverified"  # 무선 표기는 있는데 번호가 없음
    HAZARD_RULE_APPLIES = "hazard_rule_applies"
    SUBSTANCE_MENTIONED = "substance_mentioned"
    COVERAGE_GAP = "coverage_gap"
    # "조회했는데 없음" 과 "조회를 못 함" 은 셀러에게 완전히 다른 정보다.
    # 후자를 전자로 표시하면 확인하지 못한 것을 확인한 것처럼 말하게 된다.
    LOOKUP_FAILED = "lookup_failed"


class FindingGroup(str, Enum):
    """셀러 관점 화면 구획. 판정 결과가 아니라 '무엇부터 봐야 하나' 의 순서다.

    소싱 셀러의 질문 순서: (1) 이거 팔려면 뭘 준비해야 하나 → (2) 문제가
    확인된 게 있나 → (3) 참고 정보. 리콜 조회기가 아니라 소싱 판단 도구로
    보이게 하려면, 리콜·인증 결과보다 '확인할 것' 이 앞에 와야 한다.
    """

    ACTION = "action"        # 소싱하려면 확인·준비할 것 (맨 위)
    FINDING = "finding"      # 문제가 확인된 것 (인증 취소, 리콜 일치)
    CONTEXT = "context"      # 참고 (적용 기준, 조회 상태)


# FindingKind -> 화면 구획. 셀러가 먼저 볼 것일수록 ACTION.
_FINDING_GROUP: dict[str, FindingGroup] = {
    # 소싱 전에 확인·준비할 것
    "kc_missing_but_required": FindingGroup.ACTION,
    "kc_tier_unknown": FindingGroup.ACTION,
    "info_request": FindingGroup.ACTION,
    "kc_image_candidate": FindingGroup.ACTION,
    "substance_mentioned": FindingGroup.ACTION,
    # 문제가 확인된 것
    "kc_not_found": FindingGroup.FINDING,
    "kc_revoked": FindingGroup.FINDING,
    "kc_expired": FindingGroup.FINDING,
    "kc_suspended": FindingGroup.FINDING,
    "kc_under_action": FindingGroup.FINDING,
    "recall_match": FindingGroup.FINDING,
    # 참고 / 상태
    "kc_verified": FindingGroup.CONTEXT,
    "recall_clear": FindingGroup.CONTEXT,
    "maker_other_recalls": FindingGroup.CONTEXT,
    "recall_weak_match": FindingGroup.CONTEXT,
    "hazard_rule_applies": FindingGroup.CONTEXT,
    "rf_cert_verified": FindingGroup.CONTEXT,
    "rf_cert_not_found": FindingGroup.ACTION,       # 확인할 것
    "rf_wireless_unverified": FindingGroup.ACTION,  # 확인할 것
    "coverage_gap": FindingGroup.CONTEXT,
    "out_of_scope": FindingGroup.CONTEXT,
    "age_out_of_child_range": FindingGroup.CONTEXT,
    "lookup_failed": FindingGroup.CONTEXT,
}


class Finding(BaseModel):
    """One verifiable statement. Never a conclusion, always a fact + its source."""

    kind: FindingKind
    signal: Signal
    statement_ko: str            # 사실 진술. 단정 표현 금지 (CLAUDE.md §9)
    source_label: str            # e.g. "국가기술표준원 안전인증 조회"
    source_url: str              # R2: required
    legal_basis: str | None = None
    detail: dict = Field(default_factory=dict)
    checked_at: date | None = None

    @property
    def group(self) -> "FindingGroup":
        return _FINDING_GROUP.get(self.kind.value, FindingGroup.CONTEXT)

    @field_validator("source_url", "source_label")
    @classmethod
    def _must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "Finding requires a non-empty source (CLAUDE.md R2). "
                "If you have no source, do not create the Finding."
            )
        return v.strip()

    @field_validator("statement_ko")
    @classmethod
    def _no_verdict_language(cls, v: str) -> str:
        banned = ["안전합니다", "합법입니다", "판매 가능합니다", "문제없습니다", "위법입니다"]
        for word in banned:
            if word in v:
                raise ValueError(
                    f"단정 표현 '{word}' 은 사용할 수 없습니다 (CLAUDE.md §9)."
                )
        return v


class ExtractedField(BaseModel):
    """페이지에서 읽은 값 하나. '우리가 이렇게 봤습니다' 를 셀러에게 보여준다.

    셀러가 추출 결과를 눈으로 확인하면 두 가지가 된다: (1) '제대로 읽었네' 라는
    신뢰, (2) 잘못 읽었을 때 바로 잡아낼 기회. 인증번호는 link 로 정부 조회를
    바로 연다.
    """

    label: str
    value: str
    link: str | None = None


class WatchSuggestion(BaseModel):
    """스캔 결과에서 워치리스트로 잇는 제안.

    can_watch=False 면 감시할 단서가 없어 제안하지 않는다 - 지킬 수 없는 약속을
    권하지 않는다. reason 은 신호마다 다르다: GREEN 은 "지금 괜찮음의 유효기간",
    AMBER 는 "확인하는 동안 놓치지 않기".
    """

    can_watch: bool
    reason: str


class ScanResult(BaseModel):
    signal: Signal
    # 셀러의 질문은 "이거 소싱해도 돼?" 다. 신호(RED/AMBER/GREEN)와 개별 근거만으로는
    # 그 질문에 한 번 더 번역해서 답해야 한다. headline 이 소싱 판단 언어로 직접
    # 답한다. GREEN 문구에 "판매자 제공 정보 기준으로" 를 박아, 과대 약속이
    # 구조적으로 불가능하게 한다 (§6.1). 이 문장은 판정이 아니라 신호의 번역이다.
    headline: str = ""
    score: int = Field(ge=0, le=100)   # 낮을수록 확인 필요. 표시용일 뿐 판정 아님
    facts: ProductFacts
    findings: list[Finding]
    coverage_note: str | None = None
    # 리콜 로컬 사본의 기준일 (YYYYMMDD). "리콜 이력 없음" 이라는 문장의
    # 유효기간이다. 로컬 사본이라 최대 하루 늦는 트레이드오프를 숨기지 않는다.
    recall_data_as_of: str | None = None
    # GREEN 은 시점 판단이다 - "지금 리콜 없음" 이지 "앞으로도 안전" 이 아니다
    # (§6.1). 부재의 증명은 원래 약하므로, GREEN 일수록 워치리스트로 잇는다.
    # "지금 괜찮음" 은 못 보증해도 "나중에 리콜되면 알림" 은 보증할 수 있다 -
    # 이것이 이 서비스가 유일하게 보증하는 것이자 구독 명분이다 (§3.3).
    #
    #   can_watch    감시할 단서(모델명·인증번호·제조사)가 있는가
    #   watch_reason 왜 지금 감시를 권하는가. 신호마다 이유가 다르다.
    watch_suggestion: "WatchSuggestion | None" = None
    # "우리가 페이지에서 이렇게 읽었습니다." 판정 위에 입력을 먼저 보여줘야
    # 셀러가 "제대로 봤구나" 를 믿는다. 잘못 읽었으면 여기서 바로 잡아낸다.
    extracted: list["ExtractedField"] = Field(default_factory=list)
    # findings 를 셀러 관점 구획(확인할 것 / 확인된 문제 / 참고)으로 묶은 것.
    # findings 원본도 그대로 두어 하위호환을 유지한다. 프론트는 grouped 를 그린다.
    grouped_findings: list[dict] = Field(default_factory=list)
    # 상품 정보를 하나도 읽지 못했을 때의 안내. 판정이 아니라 입력 문제다.
    #
    # 붙여넣은 것이 상세페이지가 아니면(URL 만, 리뷰만, 배송 안내만) 결과가
    # "판단 보류" + 확인 항목 나열로 나가는데, 셀러는 그걸 상품 문제로 읽는다.
    # 우리가 읽은 게 없다는 사실을 먼저 말해야 다시 붙여넣을 기회가 생긴다.
    input_note: str | None = None
    # 일일 분석 한도를 넘겨 간이 추출로 처리했을 때의 안내. 정확도가 낮아진
    # 사실을 감추지 않는다 - 감추면 셀러가 덜 정확한 결과를 최신 분석으로 읽는다.
    extraction_note: str | None = None
    disclaimer: str = (
        "본 결과는 공개된 정부 데이터에 기반한 참고 정보이며, "
        "법적 판단이나 안전 인증을 대체하지 않습니다."
    )


# ---------------------------------------------------------------------------
# Watchlist (기획서 §3-4단계)
#
# A scan is a point-in-time reading. Recall notices are published after the
# fact, so the only thing this service can genuinely promise is speed of
# notification -- not present-tense safety (기획서 §6.1).
#
# Design note on error asymmetry: elsewhere in this codebase a missing fact
# degrades to UNKNOWN, because falsely reassuring a seller is the expensive
# error. Here the asymmetry flips. A missed alert breaks the one guarantee we
# make; a spurious alert costs the seller a minute. So matching is permissive
# and every alert carries its match strength instead of being silently dropped.
# ---------------------------------------------------------------------------
class WatchStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


# 무엇으로 일치했는지의 한국어 이름. 화면과 알림 문구가 같은 어휘를 쓰게 한다.
#
# 셀러의 질문은 "펜인데 왜 블라인드?" 다. 강도만으로는 답이 안 되고, 무엇이
# 맞았는지를 같이 말해야 스스로 판단할 수 있다.
MATCHED_ON_KO: dict[str, str] = {
    "model_name": "모델명",
    "kc_number": "인증번호",
    "maker+product": "제조사·제품명",
}


def matched_on_label(matched_on: str) -> str:
    return MATCHED_ON_KO.get(matched_on, matched_on)


class MatchStrength(str, Enum):
    EXACT = "exact"    # 정규화 모델명 완전 일치, 또는 인증번호 일치
    STRONG = "strong"  # 모델명 포함 관계
    WEAK = "weak"      # 제조사 + 제품명 토큰 중복

    @property
    def label_ko(self) -> str:
        return {"exact": "정확 일치", "strong": "유사 일치", "weak": "약한 일치"}[self.value]


class WatchItem(BaseModel):
    """A product the seller registered for ongoing recall monitoring."""

    id: str
    owner_id: str
    product_name: str | None = None
    model_name: str | None = None
    maker: str | None = None
    kc_numbers: list[str] = Field(default_factory=list)
    category: ItemCategory = ItemCategory.UNCLASSIFIED
    source_page_url: str | None = None
    registered_at: date
    last_swept_at: date | None = None
    status: WatchStatus = WatchStatus.ACTIVE
    # Fingerprints of recalls already surfaced, so a seller is not re-alerted
    # on every daily sweep for the same notice.
    seen_recall_fingerprints: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @classmethod
    def from_facts(cls, *, id: str, owner_id: str, facts: ProductFacts, on: date) -> "WatchItem":
        return cls(
            id=id,
            owner_id=owner_id,
            product_name=facts.product_name,
            model_name=facts.model_name,
            maker=facts.maker,
            kc_numbers=list(facts.kc_numbers),
            category=facts.category,
            source_page_url=facts.source_page_url,
            registered_at=on,
        )

    def is_matchable(self) -> bool:
        """Nothing to match on means we cannot honour the promise."""
        return bool(self.model_name or self.kc_numbers or (self.maker and self.product_name))


class RecallAlert(BaseModel):
    """A newly published recall that matched a watched item.

    Like Finding, this cannot exist without a source (CLAUDE.md R2).
    """

    watch_item_id: str
    recall_fingerprint: str
    strength: MatchStrength
    matched_on: str                # "model_name" | "kc_number" | "maker+product"
    statement_ko: str
    source_label: str
    source_url: str
    announced_on: str | None = None
    reason: str | None = None
    detected_at: date

    @field_validator("source_url", "source_label")
    @classmethod
    def _must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("RecallAlert requires a non-empty source (CLAUDE.md R2).")
        return v.strip()

    @field_validator("statement_ko")
    @classmethod
    def _no_verdict_language(cls, v: str) -> str:
        banned = ["안전합니다", "합법입니다", "판매 가능합니다", "문제없습니다", "위법입니다"]
        for word in banned:
            if word in v:
                raise ValueError(f"단정 표현 '{word}' 은 사용할 수 없습니다 (CLAUDE.md §9).")
        return v
