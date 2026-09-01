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
    UNCLASSIFIED = "unclassified"


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
    # 공급자적합성확인(SCoC) 대상은 제조·수입자가 스스로 시험해 확인하므로
    # 정부 조회 DB 에 인증번호가 없는 것이 정상이다. 부재를 위반으로 읽으면 안 된다.
    KC_TIER_UNKNOWN = "kc_tier_unknown"
    RECALL_MATCH = "recall_match"
    RECALL_CLEAR = "recall_clear"
    HAZARD_RULE_APPLIES = "hazard_rule_applies"
    SUBSTANCE_MENTIONED = "substance_mentioned"
    COVERAGE_GAP = "coverage_gap"


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


class ScanResult(BaseModel):
    signal: Signal
    score: int = Field(ge=0, le=100)   # 낮을수록 확인 필요. 표시용일 뿐 판정 아님
    facts: ProductFacts
    findings: list[Finding]
    coverage_note: str | None = None
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
