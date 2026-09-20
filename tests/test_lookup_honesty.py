"""조회 실패 문구 — **원인을 말하지 않는다** (P2 · 2026-09-20).

왜 있나
-------
전에 화면이 이렇게 말했다:

    "국가기술표준원 인증 조회 서비스에 **일시적으로** 연결하지 못했습니다.
     인증 확인이 완료되지 않았으니 **잠시 후** 다시 시도해 주세요."

한 문장에 원인 단정이 둘이다. 그런데 **우리는 원인을 모른다**:

    P1 실측    도쿄에서 TCP 핸드셰이크가 8·10·30초 모두 `network.connect`
               → connect 라는 것까지만 좁혔다
    안 잰 것   도쿄만인가 국외 전반인가
    9/18       같은 도쿄에서 **스스로 풀린 기록**이 있다 → "계속" 도 단정 못 한다

R3 이 답을 갖고 있다 - "데이터가 없으면 UNKNOWN 이다." **원인 추정도 같다.**

⚠⚠ 한쪽만 재면 **단정을 다른 단정으로 바꾼 것**도 통과한다. 그래서
  (1) 원인 낱말이 없는가 (2) 사실·행동이 남아 있는가 (3) 본 경우의 수가
  몇인가 를 함께 단정한다 (§6 "몇 개를 봤는가").
"""

from __future__ import annotations

from datetime import date

import pytest

from sourcing_guard import kats_client as kc
from sourcing_guard.verifier import _PERSISTING_AFTER, _lookup_failed

#: 원인을 단정하는 낱말. **하나도 나오면 안 된다.**
_CAUSE_WORDS = ("일시적", "잠시 후", "지역", "서버 위치", "차단", "국외",
                "해외", "네트워크 문제", "곧 복구")

#: 봐야 하는 경우의 수. (연속실패, 코드, 한 줄이 붙는가)
_CASES = [
    (0, "network.connect", False),
    (1, "network.connect", False),
    (_PERSISTING_AFTER - 1, "network.read", False),
    (_PERSISTING_AFTER, "network.connect", True),
    (99, "network", True),
    (0, "4001", False),                 # 우리 설정 문제 - 아는 것은 말한다
    (99, "4000", False),                # 연속이어도 설정 문구가 이긴다
    (0, "http", False),
    (0, None, False),
]


@pytest.fixture(autouse=True)
def _reset():
    before = kc.health.consecutive_failures
    yield
    kc.health.consecutive_failures = before


def _say(streak: int, code):
    kc.health.consecutive_failures = streak
    return _lookup_failed("인증", date(2026, 1, 1), code).statement_ko


def test_no_sentence_guesses_the_cause():
    """⚠ **본 경우의 수를 같이 적는다.** 하나만 보고 통과하면 검사가 아니다."""
    seen = 0
    for streak, code, _ in _CASES:
        text = _say(streak, code)
        seen += 1
        for w in _CAUSE_WORDS:
            assert w not in text, f"연속{streak}·{code}: 원인을 단정한다 ('{w}')\n  {text}"
    assert seen == len(_CASES) == 9, f"본 경우가 {seen}개다"


def test_every_sentence_still_says_the_fact_and_a_next_step():
    """⚠ 반대 방향 - 원인을 빼다가 **사실과 다음 걸음까지** 빼면 안 된다."""
    for streak, code, _ in _CASES:
        text = _say(streak, code)
        assert "연결하지 못했습니다" in text, f"연속{streak}·{code}: 사실이 없다"
        assert "완료되지 않았습니다" in text, f"연속{streak}·{code}: 결과가 없다"
        # 항상 참인 다음 행동 - 우리 상태와 무관하게 셀러가 할 수 있는 것.
        assert "직접 조회하실 수 있습니다" in text, f"연속{streak}·{code}: 다음 걸음이 없다"


def test_the_extra_line_is_a_count_not_a_cause():
    """연속 실패 한 줄은 **우리가 실제로 센 값**이다.

    ⚠⚠ 이번 코드와 전역 상태를 **둘 다** 본다. 하나만 보면
      `verifier.py` 주석이 걱정한 것("직전에 다른 종류의 실패가 있었을 때
      엉뚱한 문구") 이 그대로 돌아온다.
    """
    for streak, code, want in _CASES:
        text = _say(streak, code)
        has = "계속 실패하고 있습니다" in text
        assert has is want, (
            f"연속{streak}·{code}: 계속-실패 줄이 {'붙었다' if has else '안 붙었다'} "
            f"(기대 {want})")

    # 임계 바로 아래/위를 한 번 더 - 경계가 뜻을 가진다.
    assert "계속 실패" not in _say(_PERSISTING_AFTER - 1, "network.connect")
    assert "계속 실패" in _say(_PERSISTING_AFTER, "network.connect")


def test_the_headline_and_the_body_say_the_same_thing():
    """⚠⚠ 한쪽만 고치면 갈린다 (§6). 굵기 건에서 방금 겪은 모양이다."""
    from sourcing_guard.scorer import unknown_reasons

    head = {r.key: r for r in unknown_reasons()}["lookup_failed"]
    for w in _CAUSE_WORDS:
        assert w not in head.headline, f"헤드라인이 원인을 단정한다 ('{w}')"
    assert "연결하지 못했습니다" in head.body
    assert "직접 조회하실 수 있습니다" in head.body


def test_the_operator_fault_message_still_says_what_we_know():
    """⚠ 키 무효·IP 미등록은 **우리 설정 문제이고 우리가 안다.** 아는 것은 말한다.

    원인을 안 말하는 규칙이 "아무것도 말하지 마라" 가 되면 안 된다.
    """
    for code in ("4000", "4001", "4005"):
        assert "설정을 점검하고 있습니다" in _say(0, code), code


# --- 축 카드도 본다 -------------------------------------------------------
#
# 주의(가장 중요): 위 검사들은 **문장만** 봤다. 그래서 2026-09-20 에 P2 를 하고도
#   `scorer._axes()` 의 인증 축 note 가 "잠시 후 다시 시도해 주세요" 인 채로
#   배포됐다 - 같은 화면에서 문장은 원인을 안 말하고 바로 옆 카드는 "잠시" 라고
#   단정했다. §6 "화면 검사는 틀이 아니라 틀에 붓는 값을 본다" 의 그 모양이다.

def _axis_notes():
    """축 카드 note 를 **갈래마다 한 번씩** 만든다. (이름, note) 를 돌려준다."""
    from datetime import date as _date

    from sourcing_guard.models import Finding, FindingKind, Signal

    src = {"source_label": "국가기술표준원", "source_url": "https://safetykorea.kr/"}

    def mk(kind, signal=Signal.UNKNOWN, detail=None):
        fd = Finding(kind=kind, signal=signal, statement_ko="조회 결과입니다.",
                     checked_at=_date(2026, 1, 1), **src)
        if detail:
            fd.detail = detail
        return fd

    from sourcing_guard.scorer import _axes

    cases = {
        "빈 입력": [],
        "조회 실패": [mk(FindingKind.LOOKUP_FAILED, detail={"scope": "인증"})],
        "번호 없음(부재 정상)": [mk(FindingKind.KC_ABSENCE_EXPECTED)],
        "번호 없음(그 외)": [mk(FindingKind.COVERAGE_GAP)],
        "인증 조회됨": [mk(FindingKind.KC_VERIFIED, Signal.GREEN,
                        detail={"cert_state": "적합"})],
        "인증 취소": [mk(FindingKind.KC_REVOKED, Signal.RED,
                       detail={"cert_state": "안전인증취소"})],
        "리콜 대조함": [mk(FindingKind.RECALL_CLEAR, Signal.GREEN)],
        "리콜 일치": [mk(FindingKind.RECALL_MATCH, Signal.RED)],
    }
    out = []
    for name, findings in cases.items():
        for a in _axes(findings, "20260914"):
            out.append((f"{name}/{a['key']}", a.get("note") or ""))
    return out


def test_no_axis_card_guesses_the_cause_either():
    """⚠ **본 칸 수를 같이 적는다** (§6). 0칸을 보고 통과하면 검사가 아니다."""
    notes = _axis_notes()
    assert len(notes) == 8 * 3 == 24, f"본 칸이 {len(notes)}개다 - 축이나 갈래가 바뀌었다"
    for where, note in notes:
        for w in _CAUSE_WORDS:
            assert w not in note, f"{where}: 축 카드가 원인을 단정한다 ('{w}')\n  {note}"


def test_the_failed_axis_still_tells_the_seller_what_to_do():
    """⚠ 반대 방향 - 원인을 빼다가 **다음 걸음까지** 빼면 빈 칸이 된다."""
    got = dict(_axis_notes())["조회 실패/cert"]
    assert got, "조회 실패 축이 아무 말도 안 한다"
    assert "직접 조회하실 수 있습니다" in got, got
    # 셀러에게 없는 번호를 받아 오라고 하면 안 된다 - 우리 쪽 사정이다.
    assert "받으면" not in got, got
