"""같은 사실을 두 번 말하지 않는다.

오늘 이 결함을 세 번 고쳤다.

  ① KC_MISSING_BUT_REQUIRED 의 "안전인증·안전확인 대상이면…" 일반론이
     ITEM_GRADE_MATCHED 의 특정된 답과 겹쳤다.
  ② KC_ABSENCE_EXPECTED 가 등급의 뜻을 되풀이해 헤드라인·부재·등급 finding
     이 같은 말을 세 번 했다.
  ③ 그 전에 조회 성공 후에도 "인증 여부를 직접 검색하세요" 안내가 남았다.

새 finding 을 추가할 때마다 반복될 구조라서 검사로 고정한다. 특정된 답이
있는데 일반론을 먼저 두면 정확한 정보가 묻히고, 셀러는 같은 말을 두 번
읽으며 화면을 신뢰하지 않게 된다.

⚠ 헤드라인은 예외다. 첫 줄만 읽는 셀러가 결론을 봐야 하므로 finding 의
  핵심을 일부러 되풀이한다 - 그건 중복이 아니라 요약이다. 이 검사는
  **finding 들 사이의** 중복만 본다.
"""

from __future__ import annotations

import pytest

from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import Finding, ItemCategory, ProductFacts
from sourcing_guard.verifier import _GRADE_MEANING, RuleBook, verify


class NoRecalls:
    as_of = "20260903"

    def is_empty(self):
        return False

    def find(self, facts, *, today=None):
        return []

    def by_maker_exact(self, maker, *, exclude_uids=None):
        return []


# 한 결과 안에서 한 번만 나와야 하는 문장들.
#
# 등급이 뜻하는 바는 ITEM_GRADE_* 가 말한다. 다른 finding 이 되풀이하면
# 어느 것이 우리 판단이고 어느 것이 근거인지 흐려진다.
CANONICAL = tuple(_GRADE_MEANING.values()) + (
    "안전인증·안전확인 대상이면 인증번호가 있어야 하고",
    "정부 조회 DB 에 번호가 없는 것이 정상",
    "공급처에 인증 구분과 시험성적서를 요청해 확인하세요",
)

# 각 분기를 한 번씩 밟는 상품명. 새 분기를 만들면 여기에 추가한다.
CASES = [
    # 등급 합의 · 번호 필수
    ("신일 BLDC 무선 선풍기 14인치 SIF-B1424CL", ItemCategory.ELECTRICAL),
    # 등급 합의 · 부재가 정상
    ("USB 충전식 전기손난로 핸드워머 10000mAh", ItemCategory.ELECTRICAL),
    # 등급 갈림
    ("HK HAIKE 13급 원룸 소형 미니공기청정기", ItemCategory.ELECTRICAL),
    # 등급 미상
    ("모델명 XY-100 제조사 미상 220V", ItemCategory.ELECTRICAL),
    # 생활용품 · 부재가 정상
    ("우산 양산 양우산 자동우산 골프우산 암막우산", ItemCategory.HOUSEHOLD),
    # 생활용품 · 등급 미매칭 (인증 경로에 진입하지 않는다)
    ("휴대용 폴딩 접이식 캠핑 의자 초경량 간이 의자", ItemCategory.HOUSEHOLD),
    # 인증번호가 있어 조회하는 경로
    ("유아용 블록 완구 KC 인증번호 CB061R2170-3018 대상연령 3세 이상",
     ItemCategory.CHILDREN_TOY),
]


def run(name: str, category: ItemCategory) -> list[Finding]:
    facts = ProductFacts(product_name=name, category=category)
    return verify(facts, KatsClient(None, None, mock=True), RuleBook(), NoRecalls())


@pytest.mark.parametrize("name, category", CASES)
@pytest.mark.parametrize("phrase", CANONICAL)
def test_no_canonical_sentence_appears_in_two_findings(name, category, phrase):
    holders = [
        f.kind.value for f in run(name, category) if phrase in f.statement_ko
    ]
    assert len(holders) <= 1, (
        f"'{phrase[:28]}…' 가 {holders} 에 동시에 있습니다. "
        "특정된 답이 있으면 일반론을 빼십시오."
    )


@pytest.mark.parametrize("name, category", CASES)
def test_findings_do_not_share_a_long_verbatim_run(name, category):
    """정경 문장 목록에 없는 새 중복도 잡는다.

    finding 두 개가 24자 이상을 통째로 공유하면 같은 말을 두 번 하는
    것이다. 목록을 갱신하지 않아도 새 중복이 걸린다.
    """
    found = run(name, category)
    span = 24
    for i, a in enumerate(found):
        for b in found[i + 1:]:
            # 같은 kind 가 여러 개인 것은 목록이다 - 유해물질 규칙이 품목마다
            # 하나씩 붙으면 정형구가 반복되는데, 그건 "특정된 답이 일반론에
            # 묻히는" 결함과 다르다. 화면도 별도 구획에 목록으로 그린다.
            if a.kind is b.kind:
                continue
            for start in range(0, max(0, len(a.statement_ko) - span) + 1):
                chunk = a.statement_ko[start:start + span]
                if chunk in b.statement_ko:
                    raise AssertionError(
                        f"{a.kind.value} 와 {b.kind.value} 가 겹칩니다: '{chunk}'"
                    )


def test_the_guard_can_actually_fail():
    """검사가 무엇도 잡지 못하는 상태로 통과하지 않게 한다.

    같은 문장을 두 finding 에 넣으면 반드시 걸려야 한다.
    """
    phrase = _GRADE_MEANING["안전인증"]
    twins = [
        Finding(
            kind=k, signal=s, statement_ko=f"앞말. {phrase}. 뒷말.",
            source_label="근거", source_url="https://law.go.kr/",
        )
        for k, s in (
            (__import__("sourcing_guard.models", fromlist=["FindingKind"]).FindingKind.ITEM_GRADE_MATCHED,
             __import__("sourcing_guard.models", fromlist=["Signal"]).Signal.UNKNOWN),
            (__import__("sourcing_guard.models", fromlist=["FindingKind"]).FindingKind.KC_MISSING_BUT_REQUIRED,
             __import__("sourcing_guard.models", fromlist=["Signal"]).Signal.AMBER),
        )
    ]
    holders = [f.kind.value for f in twins if phrase in f.statement_ko]
    assert len(holders) == 2, "검사가 중복을 못 만들면 회귀를 못 잡는다"
