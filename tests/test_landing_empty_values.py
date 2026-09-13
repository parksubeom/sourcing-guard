"""값이 없을 때 랜딩이 **거짓말하지 않는다** (⓷-b · 2026-09-13).

⚠⚠ 실측으로 잡힌 결함이다. `/healthz` 의 `sync` 가 비면 이렇게 나왔다:

    "이미 리콜 공표된 0건과 모델명·인증번호를 대조합니다. - 공표분까지."

원인 둘. `num(0)` 이 문자열 `"0"` 이라 `total ? … : null` 이 **참**이 됐고,
없는 값을 `"-"` 로 채우는 규칙이 **문장 가운데**에서 쓰레기가 됐다.

⚠ 드문 상태가 아니다. 배포본은 **부팅 직후 초기 적재 전 몇 초**와 정부 API
  장애 때 이 화면이 뜬다 - 매 배포마다 지나는 상태다.

⚠ 렌더까지 재는 것은 `scripts/check_empty_state.py` 다(브라우저가 필요하다).
  여기서는 **계약**을 잠근다 - 그 스크립트를 안 돌려도 깨지게.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_LANDING = (_ROOT / "sourcing_guard" / "static" / "landing.html").read_text(encoding="utf-8")
_DATA = json.loads(
    (_ROOT / "sourcing_guard" / "static" / "data" / "안전성조사_보도자료.json")
    .read_text(encoding="utf-8"))


def _script() -> str:
    m = re.search(r"<script>(.*?)</script>", _LANDING, re.S)
    assert m, "랜딩에 스크립트가 없다"
    return re.sub(r"(?m)^\s*//.*$", "", m.group(1))


def _body() -> str:
    m = re.search(r"<main\b[^>]*>(.*?)</main>", _LANDING, re.S)
    assert m
    return re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S)


def test_missing_values_are_hidden_not_filled_with_a_dash():
    """`set()` 이 없는 값을 "-" 로 채우면 문장 가운데에 박힌다."""
    js = _script()
    # ⚠ **쓰임을 가린다.** 처음에 `"-"` 를 통째로 금지했다가 `fmtDate` 의 날짜
    #   구분자("YYYY" + "-" + "MM")를 결함으로 읽었다 - 정상을 막는 가드는
    #   고치라는 신호가 아니라 무시하라는 신호가 된다.
    #   금지하는 것은 **없는 값의 대체값**으로 쓰는 자리다.
    fallbacks = re.findall(r'(?:\?|:|\|\|)\s*"-"', js)
    assert not fallbacks, f"없는 값을 '-' 로 채우는 자리: {fallbacks}"
    # 값이 없으면 딸린 절을 숨긴다.
    assert "data-when=" in js, "딸린 절을 숨기는 규칙이 없다"
    assert "hidden = !has" in js.replace("  ", " "), "숨기는 코드가 없다"


def test_the_dependent_clauses_are_marked_in_the_markup():
    """숫자가 없으면 사라져야 하는 절이 표시돼 있어야 한다."""
    body = _body()
    # 공표일이 없으면 " … 공표분까지." 가 통째로 사라진다.
    assert 'data-when="as_of"' in body
    assert "공표분까지" in body
    # 기준선이 없으면 두 숫자 칸이 통째로 사라진다.
    assert 'data-when="ok_rate"' in body
    assert 'data-when="off_target"' in body


def test_the_recall_sentence_stays_true_without_a_count():
    """숫자가 없어도 **말이 되는 낱말**이 자리에 있어야 한다.

    "이미 리콜 공표된 목록과 모델명·인증번호를 대조합니다." 로 남는다.
    """
    m = re.search(r'이미 리콜 공표된 <b data-h="recalls">([^<]*)</b>', _body())
    assert m, "리콜 문장을 못 찾았다"
    assert m.group(1).strip() == "목록", m.group(1)


def test_zero_recalls_is_treated_as_no_value():
    """⚠ `num(0)` 은 문자열 `"0"` 이라 **참**이다 - 여기서 그 실수를 했다.

    그리고 대조할 목록이 없는데 "대조합니다" 는 거짓이다 (R3).
    """
    js = _script()
    assert 'typeof rec.domestic === "number"' in js, "수로 가르지 않는다"
    assert "num((rec.domestic || 0)" not in js, "옛 계산이 남아 있다"


def test_the_date_formatter_returns_null_not_a_dash():
    """모양을 만드는 함수가 없는 값을 지어내지 않는다 (R5 와 같은 태도)."""
    js = _script()
    m = re.search(r"function fmtDate\(s\)\s*\{(.*?)\n  \}", js, re.S)
    assert m, "fmtDate 를 못 찾았다"
    body = m.group(1)
    # 값이 없는 갈래가 null 이어야 한다. 본문의 "-" 는 날짜 구분자라 정상이다.
    assert re.search(r":\s*null\s*;", body), body
    assert not re.search(r'(?:\?|:|\|\|)\s*"-"', body), body


def test_the_population_noun_is_read_from_the_raw_data_not_written_by_hand():
    """⚠⚠ "온라인 구매대행 제품" 이라고 적혀 있었다. 원자료는 **해외** 구매대행이다.

    '해외' 가 빠지면 국내 온라인 유통 전체를 잰 것처럼 읽힌다 - 표본을 넓혀
    읽게 만드는 종류의 오류다(`test_failure_rate_honesty` 가 기획서에서 막는
    것과 같은 실수).
    """
    js = _script()
    assert "온라인 구매대행" not in js, "모집단 명사를 손으로 적었다"
    assert "조사_대상" in js, "모집단 명사를 원자료에서 읽지 않는다"

    a = [x for x in _DATA["조사"] if x["id"] == "2026-05-14-구매대행"][0]
    who = a["조사_대상"].split("(")[0].strip()
    assert who == "해외 구매대행 제품", who
    # 화면에 뜰 문장을 여기서 조립해 확인한다 - 사람이 읽는 그 문장이다.
    assert f"{who} {a['조사_수']}개" == "해외 구매대행 제품 420개"
