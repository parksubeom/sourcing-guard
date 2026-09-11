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
    # 셀러 말을 법령 용어로 옮긴 이름. LLM 이 답하고 **표가 검증한다.**
    #
    # 손으로 만든 별칭이 한계에 왔다. **세 숫자를 구분한다** -
    #   튜닝 표본(도매꾹239) 매칭률   71%   별칭을 만들 때 쓴 표본이다
    #   새 표본(235) 매칭률           24%   검수 전 숫자다
    #   새 표본 검수 정답률           20%   ← 발표에 쓰는 숫자
    # 71 과 24 의 차이가 별칭 과적합의 크기다. 별칭이 첫 표본에서 만들어졌으니 새
    # 상품에는 안 통한다. 놓친 것 대부분이 표에 있는데 이름만 다르다
    # (블루투스 스피커/무선스피커 · 정수기/전기정수기 · 커피머신/커피메이커).
    #
    # ⚠ LLM 에게 561건 목록에서 고르게 하지 않는다. 그러면 LED등기구 같은
    #   그럴듯한 오답이 나온다. 이름만 자연스럽게 답하게 하고, 그 이름이
    #   표에 있는지는 우리가 확인한다. 등급은 표에서 결정론적으로 읽으므로
    #   LLM 이 등급을 지어낼 수 없다 (CLAUDE.md R1).
    legal_item_name: str | None = None
    category: ItemCategory = ItemCategory.UNCLASSIFIED
    category_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_page_url: str | None = None
    raw_language: Literal["ko", "zh", "en", "mixed", "unknown"] = "unknown"

    model_config = {"extra": "forbid"}  # blocks silent addition of verdict fields


# ⚠⚠ **이 enum 을 키로 쓰는 표 목록.** kind 를 추가하면 여기를 먼저 읽고
#   아래를 **하나씩** 검토할 것. 빠뜨리면 터지거나 조용히 틀린다.
#
#   [완전해야 함]
#     scorer._PENALTY                 빠지면 score() 가 KeyError → 스캔이 500 이 된다.
#                                     임포트 시점에 단정하므로 앱 부팅이 실패한다.
#     SPECIFIC_FINDING_KINDS
#       | NON_SPECIFIC_FINDING_KINDS  빠지면 그 kind 가 유효 결과율에서 사라진다.
#
#   [부분집합이어도 됨 — 특정 kind 만 다루는 것이 의도다]
#     scorer._HARD_RED                정부 DB 가 문제를 적어둔 것만 (R3-b)
#     scorer._UNKNOWN_HEADLINE_FIRST  확정된 판단이라 먼저 말하는 것
#     scorer._UNKNOWN_HEADLINE        축이 빠진 사유
#     scorer._signal_for 의 AMBER 집합
#     scorer._axes 의 인증 축 집합
#     verifier._CERT_STATE_FINDING    certState → kind 매핑 (kind 가 값이다)
#     static/index.html 의 kind 별 문구
#
#   `tests/test_finding_kind_tables.py` 가 이 목록을 잠근다 - 완전해야 하는
#   것은 완전성을, 부분집합은 **현재 구성을** 검사하므로 새 kind 가 조용히
#   들어오거나 빠지면 거기서 깨진다.
#
# ⚠ 2026-09-11 에 `SCOPE_UNDETERMINED` 를 추가하며 `_PENALTY` 를 빠뜨려
#   `score()` 가 KeyError 를 던졌다. 그래서 이 목록이 생겼다.
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
    # 번호를 못 찾았지만 **부재가 정상인** 등급으로 확정된 경우.
    # 공급자적합성확인·안전기준준수 대상은 제조·수입자가 스스로 시험해
    # 확인하므로 정부 조회 DB 에 번호가 없다. 이걸 AMBER 로 두면 정상
    # 상품에 노란불이 반복되고, 셀러가 모든 노란불을 무시하게 된다 -
    # 그러면 진짜 취소된 인증도 안 보게 된다 (CLAUDE.md R3-b).
    #
    # 주의: 등급이 갈릴 때는 쓰지 않는다. 느슨한 쪽을 골라 감점을 빼면
    #   화면에서 막은 "한쪽 단정" 을 신호등에서 하는 셈이다.
    KC_ABSENCE_EXPECTED = "kc_absence_expected"
    # 이미지에서 읽었고 형식 검증을 통과한 인증번호. 아직 조회하지 않았다 -
    # 셀러가 "이 번호가 맞다" 고 확인한 뒤에 텍스트 경로로 조회한다.
    KC_IMAGE_CANDIDATE = "kc_image_candidate"
    # 공급자적합성확인(SCoC) 대상은 제조·수입자가 스스로 시험해 확인하므로
    # 정부 조회 DB 에 인증번호가 없는 것이 정상이다. 부재를 위반으로 읽으면 안 된다.
    KC_TIER_UNKNOWN = "kc_tier_unknown"
    # 세부품목 등급표(운용요령 별표 1~7)에서 품목을 찾은 경우. 등급이
    # 하나로 모이면 MATCHED, 후보의 등급이 다르면 SPLIT 이다.
    #
    # ⚠ 갈릴 때 한쪽을 골라 단정하지 않는다 (R3). 특히 느슨한 쪽
    #   (공급자적합성확인)을 골라 "번호 없어도 됩니다" 라고 하면
    #   위법을 권하는 셈이다.
    ITEM_GRADE_MATCHED = "item_grade_matched"
    ITEM_GRADE_SPLIT = "item_grade_split"
    # 셀러가 "부속품입니다" 라고 답해 본체 품목의 등급을 적용하지 않은 경우.
    # 우리 판정이 아니라 셀러가 준 사실이므로 kind 를 분리해 화면이
    # 근거를 밝힐 수 있게 한다.
    ITEM_GRADE_NOT_APPLIED = "item_grade_not_applied"
    # 상품명만으로는 품목을 못 정하는데, 전원 방식을 알면 정해지는 경우.
    # "안마기" 는 전동이면 전기마사지기(안전인증)이고 수동이면 표에 없다.
    # 물어볼 자리가 없으면 셀러가 답할 방법도 없다.
    ITEM_GRADE_NEEDS_POWER = "item_grade_needs_power"
    # 어린이제품인 것이 표기로 확인됐는데 세부품목 목록에는 없는 경우.
    # 「어린이제품 안전 특별법 시행규칙」 별표 3 제2호가 "개별 안전기준이
    # 없는 공급자적합성확인대상어린이제품은 어린이제품 공통안전기준을
    # 적용한다" 고 명시하므로, 이건 "판별 못 함" 이 아니라 확정된 답이다.
    CHILD_CATCH_ALL = "child_catch_all"
    OUT_OF_SCOPE = "out_of_scope"          # 우리 소관 밖 품목
    # 추출기는 타 소관으로 봤지만 **코드가 근거 표기를 못 찾은** 경우.
    #
    # ⚠ `OUT_OF_SCOPE` 와 다르다. 저쪽은 "공통안전기준 1항이 제외하는 물품임을
    #   확인했다" 이고, 이쪽은 "그 판단을 확인하지 못했다" 다. 두 개를 한
    #   kind 로 묶으면 확인한 것과 못 한 것이 화면에서 같게 보인다 (R3).
    #
    # ⚠⚠ 이 경로는 전에 **통째로 침묵했다.** `scope_reason` 이 없으면
    #   OUT_OF_SCOPE 안내도 안 나가고(verifier 의 단독 판정 조건), 등급표 조회도
    #   `_GRADE_LOOKUP_OPEN` 게이트에 막혀 돌지 않는다. A-5 실측에서 상세 109 중
    #   2건이 그렇게 아무 말도 못 했다 - [146] 방수매트 · [165] 미술 앞치마.
    #
    #   4-e 는 **등급 게이트를 여는 쪽**으로 풀려다 애매 부착이 1 → 2 로 늘어
    #   되돌렸다(미완 4-e′). 이것은 게이트를 건드리지 않고 **침묵의 이유만**
    #   말하는 출구다.
    SCOPE_UNDETERMINED = "scope_undetermined"
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
    # 부적합 방송통신기자재 현황에 일치. 전파인증 축에서 유일한 RED 자격 -
    # 부적합사유·행정처분이 명시되어 "정부 DB 가 문제를 적어둔" 조건을 만족한다.
    RF_NONCOMPLIANT = "rf_noncompliant"
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
    # 부재가 정상이어도 시험성적서 요청은 여전히 셀러가 할 일이다.
    "kc_absence_expected": FindingGroup.ACTION,
    "kc_tier_unknown": FindingGroup.ACTION,
    "item_grade_matched": FindingGroup.ACTION,
    "item_grade_split": FindingGroup.ACTION,
    # 부속품이라 등급을 적용하지 않았어도 확인할 것이 남는다 - 부속품
    # 자체가 별도 품목일 수 있고, 어린이용이면 부분품·부속품도 대상이다.
    # CONTEXT 로 내리면 유일한 인증 관련 문장이 화면 아래로 묻힌다.
    "item_grade_not_applied": FindingGroup.ACTION,
    "item_grade_needs_power": FindingGroup.ACTION,
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
    "rf_noncompliant": FindingGroup.FINDING,        # 확인된 문제
    "coverage_gap": FindingGroup.CONTEXT,
    "out_of_scope": FindingGroup.CONTEXT,
    "age_out_of_child_range": FindingGroup.CONTEXT,
    "lookup_failed": FindingGroup.CONTEXT,
}


class SellerHints(BaseModel):
    """셀러가 화면에서 답해 준 사실. **우리 판정이 아니다.**

    상품명만으로 못 가리는 것이 있고, 그건 규칙을 더 밀어붙여 풀리지 않는다.
    실측으로 확인했다 - 부속어가 품목명에서 떨어져 있으면("무타공 전기면도기
    스테인레스 거치대 면도기 홀더") 인접 가드가 못 잡고, 느슨하게 넓히면
    정답 3건이 함께 죽는다. 상품명 밖의 정보가 필요하다.

    ⚠ 힌트는 **추가 정보이지 필수 입력이 아니다.** 아무 힌트도 없으면 동작이
      힌트 도입 전과 완전히 같아야 한다. 검사가 이를 강제한다.

    ⚠ 힌트로 판단이 바뀌면 그 근거를 화면에 남긴다. "셀러가 부속품으로
      확인하셨습니다" 처럼 누가 말한 것인지 밝힌다 - 우리가 판정한 것처럼
      보이면 셀러가 자기 답을 우리 결론으로 착각한다.

    자리를 넓게 잡아 둔다. 다음에 올 것은 power_source 다 - 조명 등급이
    갈리는 이유가 전원 방식이라(별표 1 일반조명기구 vs 별표 2 그밖의
    조명기구), 셀러가 "배터리·충전식" 이라고 답하면 후보가 하나로 좁혀진다.
    지금은 받지 않는다. 한 번에 둘을 넣으면 어느 쪽이 깨졌는지 못 가린다.
    """

    # True 면 부속품(거치대·커버·필터 등), False 면 본체. None 은 안 물어봤다.
    is_accessory: bool | None = None

    # 전원 방식. **조명 전용이 아니다** - 같은 질문이 두 곳에서 답을 준다.
    #
    #   조명   별표 1 일반조명기구(상시전원, 안전인증) vs 별표 2 그밖의
    #          조명기구(충전식 휴대전등, 안전확인). 원문의 갈림 기준이 곧
    #          전원 방식이다.
    #   안마기 전동이면 표의 '전기마사지기'(안전인증)이고, 수동이면 표에
    #          없다. 실측에서 미매칭 5건 중 4건이 이 갈래였다 -
    #          "지압봉 안마기 어깨마사지기 발지압봉" 은 손으로 누르는 것이고,
    #          "문어발 USB 진동 마사지기" 는 전동이다.
    #
    # none 이 수동 기구를 가려낸다. 이게 없으면 '안마기' 를 별칭 키로 쓸 수
    # 없다 - 수동 제품이 같이 걸려 오답이 된다.
    power_source: Literal["mains", "battery", "solar", "none"] | None = None

    def says_accessory(self) -> bool:
        return self.is_accessory is True

    def says_unpowered(self) -> bool:
        """전원을 쓰지 않는다고 답했는가. 수동 기구는 전기용품이 아니다."""
        return self.power_source == "none"

    def says_self_powered(self) -> bool:
        """상시전원이 아니라고 답했는가 (배터리·충전식·태양광).

        조명에서 별표 2 쪽(충전식 휴대전등)을 가리킨다.
        """
        return self.power_source in ("battery", "solar")

    def says_mains(self) -> bool:
        """상시전원이라고 답했는가. 조명에서 별표 1 쪽(LED등기구)을 가리킨다."""
        return self.power_source == "mains"

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


class ResultAxis(BaseModel):
    """검사 축 하나의 상태.

    ⚠ label 은 **우리가 한 행위**를 적는다. "대조함" 이지 "이상 없음" 이 아니다.
    ⚠ ok=True 는 "문제 없음" 이 아니라 "그 축을 우리가 수행했다" 는 뜻이다.
      화면이 이걸 초록 체크로 크게 그리면 안 된다.
    """

    key: str            # cert | recall | hazard
    name: str           # 인증 조회 · 리콜 대조 · 유해물질
    label: str          # 조회함 · 번호 없음 · 조회 실패 · 대조함 · 일치 있음 · …
    done: bool          # 그 축을 수행했는가 (상품이 안전한가가 아니다)
    note: str = ""      # 기준일 같은 한정


#: **셀러에게 구체적인 것을 하나라도 줬는가** 를 가리는 finding 종류 (E).
#:
#: 모든 `Finding` 은 `source_url` 을 갖는다(R2). 그래서 "원문 링크가 붙었나" 로는
#: 아무것도 갈리지 않는다 - 갈라야 하는 것은 **이 상품에 대해 무엇을 말했나** 다.
#:
#: 여기 **넣지 않은** 것과 그 이유:
#:
#:     info_request      우리가 **묻는** 것이다. 답을 준 게 아니다
#:     coverage_gap      우리 수록 범위 밖이라고 말한 것이다
#:     lookup_failed     조회를 **못 했다**. 정부 API 장애다
#:     kc_tier_unknown   등급을 몰라서 부재를 해석할 수 없다는 말이다
#:     item_grade_not_applied · item_grade_needs_power
#:                       조건이 안 맞아 적용하지 않았다는 말이다
#:
#: ⚠ `kc_absence_expected` 는 **넣는다.** "이 등급에서는 번호 부재가 정상이다" 는
#:   원문 근거가 붙은 **이 상품에 대한 판단**이고, R3-b 가 세운 답이다.
#:
#: ⚠ `out_of_scope` 도 넣는다. "다른 부처 소관" 은 판별 못 함이 아니라 답이다.
#:
#: ⚠ 이 집합은 **판정에 쓰지 않는다.** 관측 지표(`/healthz`)만 쓴다 - 신호를
#:   여기에 걸면 "구체적 finding 이 많으면 위험" 같은 판정이 된다.
#: 여기 **넣은** 것 - 열거로 둔다. 새 종류가 생기면 자동으로 "구체적" 이 되지
#: 않게 하기 위해서다. `tests/test_result_rate.py` 가 모든 종류가 분류됐는지 본다.
SPECIFIC_FINDING_KINDS: frozenset["FindingKind"] = frozenset({
    # 인증 축 - 조회해서 무엇이 나왔나
    FindingKind.KC_VERIFIED,
    FindingKind.KC_REVOKED,
    FindingKind.KC_EXPIRED,
    FindingKind.KC_SUSPENDED,
    FindingKind.KC_UNDER_ACTION,
    FindingKind.KC_NOT_FOUND,
    FindingKind.KC_MISSING_BUT_REQUIRED,
    FindingKind.KC_ABSENCE_EXPECTED,
    FindingKind.KC_IMAGE_CANDIDATE,
    # 품목 축 - 무엇으로 봤고 어느 등급인가
    FindingKind.ITEM_GRADE_MATCHED,
    FindingKind.ITEM_GRADE_SPLIT,
    FindingKind.CHILD_CATCH_ALL,
    FindingKind.AGE_OUT_OF_CHILD_RANGE,
    FindingKind.OUT_OF_SCOPE,
    # 리콜 축
    #   ⚠ `RECALL_WEAK_MATCH` 는 여기 없다 - 아래 비구체적 쪽에 있다.
    FindingKind.RECALL_MATCH,
    FindingKind.MAKER_OTHER_RECALLS,
    # 전파 축
    FindingKind.RF_CERT_VERIFIED,
    FindingKind.RF_CERT_NOT_FOUND,
    FindingKind.RF_WIRELESS_UNVERIFIED,
    FindingKind.RF_NONCOMPLIANT,
    # 유해물질 축
    FindingKind.HAZARD_RULE_APPLIES,
    FindingKind.SUBSTANCE_MENTIONED,
})

#: 일부러 뺀 것. 합집합이 전체와 같아야 한다 - 검사가 강제한다.
NON_SPECIFIC_FINDING_KINDS: frozenset["FindingKind"] = frozenset({
    # ⚠⚠ `recall_clear` 를 뺐다. 처음엔 넣었는데 **지표가 항상 1.0 이 됐다.**
    #
    #   이 finding 은 리콜 대조를 했다는 사실이라 **모든 검사에 붙는다** -
    #   URL 만 붙여넣어 우리가 아무것도 못 읽은 검사에도 붙는다. 그때 "리콜
    #   목록에서 일치 항목을 찾지 못했습니다" 는 대조할 것이 없어서 못 찾은
    #   것이고, 셀러에게 준 것이 아니다.
    #
    #   실측 (목 모드):
    #       "그냥 아무 글자"        recall_clear 포함 → True   제외 → False
    #       "https://example.com/…" recall_clear 포함 → True   제외 → False
    #       "유아용 블록 완구 …"     둘 다 True
    #
    #   **움직이지 않는 지표는 지표가 아니다.** 부재의 증명은 원래 약하고
    #   (R3-b), GREEN 조건도 이것만으로는 안 준다.
    FindingKind.RECALL_CLEAR,
    # ⚠⚠ `recall_weak_match` 도 뺐다 (2026-09-09). 약한 일치는 **모델명 문자열이
    #   겹쳤다는 사실**이고, 이 상품에 대해 말한 것이 아닐 수 있다.
    #
    #   근거는 4-d-2 실측이다 - 상세 109 에서 나온 RED 5건 중 **3건이 품목이
    #   다른 우연 충돌**이었다:
    #
    #       '레인보우'      물놀이 튜브        ↔  전혀 다른 품목의 리콜
    #       'hope'          생활용품          ↔  같은 문자열을 쓴 다른 상품
    #       '진공 청소기'    일반 명사가 모델명 자리에 들어온 경우
    #
    #   그래서 `downgrade_unqualified_recall_reds()` 가 이런 것의 **신호를 이미
    #   내린다.** 신호를 내리면서 "구체적인 것을 줬다" 로 세면 앞뒤가 안 맞고,
    #   `recall_clear` 를 뺀 것과 같은 이유로 **지표가 우리에게 유리하게 부푼다.**
    #
    #   ⚠ 다시 넣을 조건: 모델명 일치에 **제조사·품목 일치까지 요구하는 강한
    #     weak_match** 가 생기면 그때 넣는다. 그때는 "이 상품에 대해 말한 것" 이
    #     되고 우연 충돌 3건이 걸러진다.
    #
    #   ⚠ R6 은 그대로다. 워치리스트 알림은 약한 일치도 **관대하게 보낸다** -
    #     놓친 알림이 더 비싸기 때문이다. 여기서 빼는 것은 **관측 지표**에서
    #     빼는 것이고, 알림을 끄는 것이 아니다.
    FindingKind.RECALL_WEAK_MATCH,
    # ⚠⚠ `scope_undetermined` 는 **구체적이 아니다.** 이 finding 이 붙는 줄은
    #   등급도 인증도 아무것도 못 받은 줄이고, 우리가 말한 것은 "판단하지
    #   않았다" 다. SPECIFIC 에 넣으면 **아무것도 못 준 줄이 "유효" 로
    #   뒤집혀 지표가 부푼다** - `recall_clear` · `recall_weak_match` 를 뺀 것과
    #   정확히 같은 이유다.
    #
    #   그래도 만드는 이유는 셀러가 화면에서 **이유를 읽을 수 있어야** 하기
    #   때문이다. 지표에 세는 것과 화면에 말하는 것은 다르다.
    FindingKind.SCOPE_UNDETERMINED,
    FindingKind.INFO_REQUEST,
    FindingKind.COVERAGE_GAP,
    FindingKind.LOOKUP_FAILED,
    FindingKind.KC_TIER_UNKNOWN,
    FindingKind.ITEM_GRADE_NOT_APPLIED,
    FindingKind.ITEM_GRADE_NEEDS_POWER,
})


class ScanMeta(BaseModel):
    """**이 스캔 한 건**이 어떻게 나왔나. 판정이 아니라 리포트 메타다.

    ⚠ 2026-09-08 사고의 뿌리가 "이 스캔" 을 말할 수 없다는 것이었다. Claude
      잔액이 0 이 되어 배포본이 매 스캔마다 휴리스틱으로 떨어졌는데, 응답도
      화면도 그 사실을 말하지 않아 휴리스틱 결과를 "실물 확인" 으로 보고했다.
      `/healthz` 의 `extraction` 은 **프로세스 누적값**이라 "지금 이 결과가
      무엇으로 나왔나" 를 답하지 못한다.

    ⚠ `ProductFacts` 에 넣지 않는다. 그쪽은 `extra="forbid"` 인 판정 입력이고
      여기에 메타를 섞으면 R1 경계가 흐려진다.

    ⚠ **화면은 이 필드를 읽어 그린다. 하드코딩 금지.** 모델 이름도 설정에서
      와야 한다 - 문서에 적힌 이름과 배포본 secret 이 다를 수 있고, 실제로
      그것을 확인할 방법이 없어서 이 필드를 만들었다.
    """

    # "LLM(GPT · gpt-5.4-mini)" · "규칙 기반 (일일 한도 초과)" 처럼 그대로 쓸 한 줄.
    extracted_by: str
    # 기계가 가릴 수 있게 조각도 함께 낸다.
    extraction_path: str                  # "llm" | "heuristic"
    extractor_vendor: str | None = None   # "claude" | "gpt" | None
    extractor_model: str | None = None    # 설정에서 온 실제 모델 이름
    extraction_reason: str | None = None  # 휴리스틱으로 내려간 이유
    # 리콜 로컬 사본 기준일. ScanResult.recall_data_as_of 와 같은 값을 메타
    # 자리에도 둔다 - 화면 상단 두 줄이 한 곳에서 읽히게 하기 위해서다.
    recall_data_as_of: str | None = None


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
    # 축 셋의 상태. 종합 배지 하나로는 "무엇을 했고 무엇을 못 했는지" 가 안
    # 보인다 - 배지가 "모름" 인데 부제목이 "일부만 확인" 이면 둘이 다른 말을 한다.
    #
    # ⚠ **축 이름은 우리가 한 행위이지 상품의 상태가 아니다.** "리콜 대조함"
    #   이지 "리콜 없음/안전" 이 아니다. ✓ 를 크게 쓰면 셀러가 초록불로 읽는데,
    #   그게 우리가 회색불을 택한 이유다 (기획서 §3.2 · CLAUDE.md §9).
    axes: list["ResultAxis"] = Field(default_factory=list)
    # findings 를 셀러 관점 구획(확인할 것 / 확인된 문제 / 참고)으로 묶은 것.
    # findings 원본도 그대로 두어 하위호환을 유지한다. 프론트는 grouped 를 그린다.
    grouped_findings: list[dict] = Field(default_factory=list)
    # 이 스캔이 어떻게 나왔나 (추출 경로 · 리콜 기준일). 화면 상단 두 줄이
    # 이것을 읽는다.
    meta: "ScanMeta | None" = None
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


# 한국어로 읽었을 때 받침이 없는 숫자. 2(이) 4(사) 5(오) 9(구).
# 나머지는 1(일) 3(삼) 6(육) 7(칠) 8(팔) 0(영) 으로 받침이 있다.
_DIGITS_NO_FINAL = {"2", "4", "5", "9"}


def subject_particle(word: str) -> str:
    """받침에 맞는 주격 조사(이/가)를 돌려준다.

    "인증번호 이(가) 조회되었습니다" 처럼 두 형태를 병기하면 문장이 어색하다.
    심사위원과 셀러가 읽는 화면이므로 한 글자를 맞춘다.

    한글 음절은 (코드 - 0xAC00) % 28 이 0 이면 받침이 없다. 숫자로 끝나면 읽는
    소리로 판단한다 - 'CB061R2170-3018' 은 '팔' 로 끝나 받침이 있고 '이' 다.
    """
    if not word:
        return "가"
    last = word.strip()[-1]
    if "가" <= last <= "힣":
        return "가" if (ord(last) - 0xAC00) % 28 == 0 else "이"
    if last.isdigit():
        return "가" if last in _DIGITS_NO_FINAL else "이"
    # 영문·기타로 끝나면 소리를 단정할 수 없다. 병기가 어색하므로 '가' 로 둔다.
    return "가"


def topic_particle(word: str) -> str:
    """받침에 맞는 보조사(은/는). subject_particle 과 같은 규칙."""
    return "는" if subject_particle(word) == "가" else "은"


def object_particle(word: str) -> str:
    """받침에 맞는 목적격 조사(을/를)."""
    return "를" if subject_particle(word) == "가" else "을"


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
