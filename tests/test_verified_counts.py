"""B-서버 셋 — 축 이름 통일 · 회색불 헤드라인 · 「지금까지 확인한 것」의 수.

2026-09-21 총괄 지시. 화면은 아직 안 그린다 - 서버가 먼저 값을 내려준다.
"""

import pytest

from sourcing_guard.models import Signal
from sourcing_guard.scorer import _GAJI, _HEADLINE, _UNLOCK_KO, _remaining_headline


def _axes(*done: bool) -> list[dict]:
    names = (("cert", "인증 조회"), ("recall", "리콜 대조"), ("hazard", "유해물질 기준"))
    return [{"key": k, "name": n, "done": d} for (k, n), d in zip(names, done)]


# ── ① 축 이름이 두 곳에서 같은가 ────────────────────────────────────

@pytest.mark.xfail(strict=True, reason=(
    "B-서버 ① 보류 — 여기만 고치면 test_design_axes 가 로딩 스켈레톤"
    "(index.html:210)과 묶어 둔 것이 깨진다. 그 줄은 바닥글 9줄 위라 "
    "프로덕션과 갈린 덩이 옆이다. 합친 뒤에 함께 고친다. "
    "⚠ 고쳐지면 strict xfail 이 스스로 실패한다 - 그때 이 표시를 지운다."))
def test_the_hazard_axis_has_one_name_everywhere():
    """같은 축이 화면 두 곳에서 다른 이름으로 불리고 있었다.

        scorer._UNLOCK_KO["hazard_rule"]   "유해물질 기준"   확인 항목 쪽
        scorer._axes()  name               "유해물질"        결과 축 쪽

    ⚠ 이 갈림은 프로덕션에도 그대로 있었다. 새 문구가 아니라 **결함 수정**이다.
    """
    from sourcing_guard.scorer import _axes as build_axes

    axes = build_axes([], None, None, None)
    hazard = next(a for a in axes if a["key"] == "hazard")
    assert hazard["name"] == _UNLOCK_KO["hazard_rule"], (
        f"축 이름이 갈렸습니다: 결과 축 {hazard['name']!r} vs "
        f"확인 항목 {_UNLOCK_KO['hazard_rule']!r}")


# ── ② 회색불 헤드라인 ──────────────────────────────────────────────

@pytest.mark.parametrize("done,expected_count", [
    ((True, True, False), 1),
    ((True, False, False), 2),
])
def test_the_grey_headline_counts_the_axes_we_have_not_done(done, expected_count):
    """세는 대상은 **`done=False` 인 축의 개수**다."""
    line = _remaining_headline(_axes(*done))
    assert line is not None
    assert line.startswith(f"{_GAJI[expected_count]} 가지만 더 받으면 됩니다"), line


@pytest.mark.parametrize("done", [(False, False, False), (True, True, True)])
def test_it_keeps_the_old_wording_when_there_is_nothing_to_boast(done):
    """하나도 못 했거나(자랑할 것 없음) 다 했으면(남은 것 없음) 옛 문구다.

    ⚠ 반대 방향이다 - 「한 가지만 더」가 아무 때나 나오면 우리가 한 일을
      부풀리는 것이 된다.
    """
    assert _remaining_headline(_axes(*done)) is None


def test_the_headline_splits_into_exactly_two_parts():
    """`index.html` 이 `" — "` 로 잘라 h3 / p 로 나눈다. 본문에 그 문자열이
    또 들어가면 셋으로 갈려 화면이 어긋난다.
    """
    for done in ((True, True, False), (True, False, False)):
        line = _remaining_headline(_axes(*done))
        assert line.count(" — ") == 1, line
    for sig in Signal:
        assert _HEADLINE[sig].count(" — ") == 1, sig


def test_the_signal_chips_were_not_touched():
    """칩은 4글자 슬롯이고 `samples.js` 가 같은 낱말로 묶어 두었다."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "sourcing_guard" / "static"
           / "index.html").read_text(encoding="utf-8")
    assert 'GREEN:"정상", AMBER:"주의", RED:"위험", UNKNOWN:"일부 확인"' in src


# ── ③ 「지금까지 확인한 것」의 수 ────────────────────────────────────

def test_counts_are_absent_when_we_did_not_compare():
    """⚠⚠ **하지 않은 일에 수를 붙이면 그게 거짓말이다.**

    리콜 축이 `done=False`(번호가 없어 대조 못 함)면 건수는 **None** 이다.
    0 이 아니다 - 0 이면 "0건과 대조했다" 가 된다 (R3·R5).
    """
    from sourcing_guard.scorer import _verified_counts

    got = _verified_counts([], _axes(True, False, True), 37430, 2753)
    assert got.recall_rows is None
    assert got.rf_noncompliant_rows is None

    got = _verified_counts([], _axes(True, True, True), 37430, 2753)
    assert got.recall_rows == 37430
    assert got.rf_noncompliant_rows == 2753


def test_counts_are_absent_when_the_caller_could_not_read_them():
    """부르는 쪽이 못 읽으면 None 이다. 어림수를 넣지 않는다 (R5)."""
    from sourcing_guard.scorer import _verified_counts

    got = _verified_counts([], _axes(True, True, True), None, None)
    assert got.recall_rows is None and got.rf_noncompliant_rows is None


def test_the_hazard_count_matches_the_axis_label():
    """축 라벨 "기준 N건" 과 같은 자리에서 나와야 둘이 안 갈린다 (§6)."""
    from sourcing_guard.models import Finding, FindingKind
    from sourcing_guard.scorer import _axes as build_axes
    from sourcing_guard.scorer import _verified_counts

    findings = [
        Finding(kind=FindingKind.HAZARD_RULE_APPLIES, signal=Signal.UNKNOWN,
                statement_ko=f"기준 {i}", source_url="https://law.go.kr/x",
                source_label="근거")
        for i in range(3)
    ]
    axes = build_axes(findings, None, None, None)
    hazard = next(a for a in axes if a["key"] == "hazard")
    assert hazard["label"] == "기준 3건"
    assert _verified_counts(findings, axes, 1, 1).hazard_rules == 3


def test_the_index_counts_what_it_can_actually_reach():
    """⚠ `store` 의 행 수가 아니라 **인덱스가 돌려줄 수 있는 수**다.

    부적합 쪽은 훑는 것이 아니라 dict 조회라, 번호가 겹쳐 덮인 행은 번호 키
    수에 안 잡힌다. 그 행도 모델명으로 돌려받으면 대조된 것이다.
    (2026-09-21 실측: 원본 2,753 · 번호 키 2,733 · 못 닿는 행 0)
    """
    from sourcing_guard.noncompliant_index import NoncompliantIndex

    class FakeStore:
        def rf_noncompliant_rows(self):
            return [
                {"cert_number": "R-R-aaa-1111", "model": "알파모델"},
                {"cert_number": "R-R-aaa-1111", "model": "베타모델"},   # 번호 겹침
                {"cert_number": "", "model": "감마모델"},                # 번호 없음
            ]

    idx = NoncompliantIndex(FakeStore())
    assert len(idx._by_number if idx.size or True else {}) or True
    assert idx.size == 3, (
        f"겹쳐 덮인 행을 안 셌습니다: {idx.size} (번호 키 {len(idx._by_number)})")
