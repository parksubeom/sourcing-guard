"""진행도 — **우리 쪽 진행이지 상품 점수가 아니다** (사양 §2-②③).

⚠⚠ `1/3` 을 그리면 "이 서비스가 33%밖에 못 하네" 로 읽힌다. 그래서 분수는
  **전부 끝났을 때만**이고 나머지는 개수다. RED 는 아예 안 그린다 - 빨강일 때
  진행도를 크게 쓰면 판정을 흐린다.
"""

import pytest

from sourcing_guard.models import Finding, FindingKind, Signal
from sourcing_guard.scorer import _eul, _progress


def _axes(*done: bool) -> list[dict]:
    names = (("cert", "인증 조회"), ("recall", "리콜 대조"), ("hazard", "유해물질 기준"))
    return [{"key": k, "name": n, "done": d} for (k, n), d in zip(names, done)]


def _f(kind: FindingKind, sig: Signal = Signal.AMBER) -> Finding:
    return Finding(kind=kind, signal=sig, statement_ko="x",
                   source_url="https://www.safetykorea.kr/", source_label="근거")


def test_red_never_draws_a_progress_bar():
    """⚠ 사양 §2-③ — 빨강일 때 진행도를 크게 쓰면 판정을 흐린다."""
    got = _progress(Signal.RED, _axes(True, True, False), [_f(FindingKind.RECALL_MATCH, Signal.RED)])
    assert got.kind == "none"
    assert got.lead == "" and got.tail == ""


def test_the_fraction_is_only_for_a_finished_clean_scan():
    """분수는 **전부 끝났고 주의도 없을 때만**이다."""
    clean = _progress(Signal.GREEN, _axes(True, True, True), [])
    assert clean.kind == "fraction" and clean.done == clean.total == 3

    # 축은 다 했지만 주의가 있으면 개수다 - 3/3 이 "문제 없음" 으로 읽힌다.
    watch = _progress(Signal.AMBER, _axes(True, True, True), [_f(FindingKind.KC_EXPIRED)])
    assert watch.kind == "counts", "주의가 있는데 분수를 그린다"

    # 못 한 축이 있으면 개수다.
    part = _progress(Signal.UNKNOWN, _axes(True, True, False), [])
    assert part.kind == "counts" and part.missing == 1


def test_attention_is_not_the_same_as_missing():
    """⚠⚠ 사양 §2-④ — 「기간만료」는 조회 **실패가 아니라 성공**이다.

    축은 했고 결과가 주의다. 그것을 `missing` 으로 세면 "우리가 못 했다" 가
    되어 거짓이다.
    """
    got = _progress(Signal.AMBER, _axes(True, True, True), [_f(FindingKind.KC_EXPIRED)])
    assert got.done == 3, "조회를 했는데 안 한 것으로 센다"
    assert got.attention == 1 and got.missing == 0


def test_the_words_come_from_the_server_not_the_screen():
    """문구 소유자는 `scorer.py` 다 (§6 · scorer.py:227)."""
    got = _progress(Signal.GREEN, _axes(True, True, True), [])
    assert got.lead and got.tail
    assert "세 축" in got.lead, got.lead          # 수사(셋)가 아니라 수관형사(세)
    assert "셋 축" not in got.lead


@pytest.mark.parametrize("word,want", [
    ("유해물질 기준", "을"),   # 받침 있음
    ("리콜 대조", "를"),       # 받침 없음
    ("인증 조회", "를"),
    ("", "를"),
])
def test_the_particle_follows_the_last_letter(word, want):
    """조사가 틀리면 화면에서 바로 눈에 띈다 - 「기준 를 마쳤습니다」."""
    assert _eul(word) == want


def test_the_progress_rides_on_the_result():
    """상수가 맞아도 `score()` 가 싣는지는 다른 질문이다."""
    from sourcing_guard.models import ProductFacts
    from sourcing_guard.scorer import score

    got = score(ProductFacts(product_name="무언가"), [])
    assert got.progress is not None
    assert got.progress.kind in ("fraction", "counts", "none")
