"""한국어 "무선" 의 두 뜻 — 전원 코드가 없다 vs 전파를 쓴다.

무선청소기·무선고데기·무선주전자는 배터리로 도는 것이지 전파를 쓰지 않는다.
그런데 키워드에 맨 "무선" 이 있어서 셋 다 rf_wireless_unverified 가 뜨고
신호까지 AMBER 로 바뀌었다(실측). 전파와 무관한 배터리 가전 전반에 "전파인증
확인하세요" 가 붙으면, R3-b 에서 세운 "항상 켜지는 경고는 꺼진 경고와 같다" 에
그대로 걸린다.

'차' 한 글자가 기차놀이를 식품으로 판정했던 것(e542467)과 같은 뿌리다 -
단어 매칭에는 문맥이 없다.

구조는 out_of_scope 와 같다:
    키워드   전파를 특정하는 표기만. LLM 이 못 돌 때의 폴백이다.
    LLM     문맥으로 판단. "무선 이어폰" 처럼 키워드가 못 잡는 것을 잡는다.
"""

import pytest

from sourcing_guard.extractor import SYSTEM_PROMPT, _EXAMPLES, extract


# --- 키워드 폴백 -----------------------------------------------------------
@pytest.mark.parametrize("text", [
    "무선청소기 핸디형 흡입력 강력",
    "무선 고데기 휴대용",
    "무선주전자 1.7L 스테인리스",
    "무선드릴 18V 배터리 2개",
    "무선 충전거치대 없음 유선만 지원",
])
def test_cordless_appliances_are_not_wireless_hints(text):
    """'무선' 이 전원 코드 없음을 뜻하는 경우다. 전파를 쓰지 않는다."""
    assert extract(text).wireless_hints == []


@pytest.mark.parametrize("text,expected", [
    ("블루투스 이어폰 TWS", "블루투스"),
    ("Wi-Fi 공유기 듀얼밴드", "Wi-Fi"),
    ("무선충전 패드 15W", "무선충전"),
    ("NFC 태그 스티커 10매", "NFC"),
    ("2.4GHz 수신기 포함", "2.4GHz"),
])
def test_radio_terms_are_kept(text, expected):
    """전파를 특정하는 표기는 키워드로도 잡는다."""
    assert expected in extract(text).wireless_hints


def test_bare_wireless_word_is_not_a_keyword():
    """맨 '무선' 을 키워드에 두면 배터리 가전이 전부 걸린다.

    구현이 다시 돌아가지 않게 코드 형태로 고정한다.
    """
    import inspect

    from sourcing_guard import extractor

    src = inspect.getsource(extractor._heuristic_fallback)
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert '"무선"' not in body, "맨 '무선' 이 키워드로 돌아왔습니다"
    assert '"블루투스"' in body


# --- LLM 쪽 지시 -----------------------------------------------------------
def test_prompt_separates_the_two_meanings_of_wireless():
    """키워드로 못 가르는 것은 LLM 이 문맥으로 판단해야 한다."""
    assert "전파를 송수신하는 기능" in SYSTEM_PROMPT
    assert "무선청소기" in SYSTEM_PROMPT
    assert "전원 코드가 없다" in SYSTEM_PROMPT
    # 판정이 아니라 사실이라는 경계도 유지한다 (R1)
    assert "전파인증 대상이다" in SYSTEM_PROMPT


def test_few_shot_teaches_both_directions():
    """문장보다 예시가 강하다. 양쪽을 다 보여준다."""
    answers = {page: ans for page, ans in _EXAMPLES}
    cordless = [a for p, a in _EXAMPLES if "무선청소기" in p]
    radio = [a for p, a in _EXAMPLES if "블루투스" in p]
    assert cordless and cordless[0]["wireless_hints"] == []
    assert radio and radio[0]["wireless_hints"]


# --- 파이프라인 ------------------------------------------------------------
def _signal_and_kinds(text: str):
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.rra_client import RraClient
    from sourcing_guard.scorer import score
    from sourcing_guard.verifier import RuleBook, verify

    facts = extract(text)
    findings = verify(facts, KatsClient(None, None, mock=True), RuleBook(), None,
                      RraClient(mock=True))
    return score(facts, findings).signal, {f.kind.value for f in findings}


def test_cordless_vacuum_gets_no_rf_finding():
    """전파와 무관한 상품에 전파인증을 요구하면 오탐이다."""
    _, kinds = _signal_and_kinds("무선청소기 핸디형\n재질: ABS\n충전시간 4시간")
    assert not [k for k in kinds if k.startswith("rf_")]


def test_bluetooth_earbuds_still_get_the_rf_axis():
    """좁히다가 진짜 전파기기를 놓치면 안 된다."""
    _, kinds = _signal_and_kinds("블루투스 이어폰 TWS\n모델명: ABC-100")
    assert "rf_wireless_unverified" in kinds
