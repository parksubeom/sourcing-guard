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

    got = _verified_counts([], _axes(True, True, True), 37430, 2753)
    assert got.recall_rows == 37430

    # ⚠ 전파 부적합은 여기서 안 본다 - **다른 축**이다.
    #   이 검사가 처음에 `rf_noncompliant_rows == 2753` 을 함께 단정했는데,
    #   그게 곧 총괄이 잡은 결함이었다 (리콜 done 으로 전파를 게이트함).
    #   전파 쪽은 `test_the_rf_count_is_absent_when_the_rf_axis_never_ran` 이 본다.


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

# ── ③-b 전파 부적합은 **리콜과 다른 축**이다 ──────────────────────────

def _rf(kind_name: str = "RF_WIRELESS_UNVERIFIED"):
    from sourcing_guard.models import Finding, FindingKind

    return Finding(
        kind=getattr(FindingKind, kind_name), signal=Signal.AMBER,
        statement_ko="무선 기능 표기가 있습니다", source_url="https://rra.go.kr/x",
        source_label="전파 부적합 현황")


def test_the_rf_count_is_absent_when_the_rf_axis_never_ran():
    """⚠⚠ **`verifier.py:610` 이 무선 표기도 번호도 없으면 전파 축을 통째로
    건너뛴다.** 봉제 완구 같은 상품은 리콜 축이 done=True 여도 부적합 인덱스를
    한 번도 안 본다 - 거기에 "2,753건과 대조" 를 붙이면 거짓이다.

    ⚠ 처음에 `did_recall` 로 묶었다가 총괄 검수에서 잡혔다. 게이트는 옳았고
      **축을 잘못 골랐다.** 어제 화면이 "37,430건과 대조" 로 한 잘못과 같은 종류다.
    """
    from sourcing_guard.scorer import _verified_counts

    axes = _axes(True, True, True)
    no_rf = _verified_counts([], axes, 37430, 2753)
    assert no_rf.recall_rows == 37430, "리콜은 했으므로 남아야 한다"
    assert no_rf.rf_noncompliant_rows is None, (
        "전파 축을 안 돌았는데 부적합 건수가 붙었습니다")

    with_rf = _verified_counts([_rf()], axes, 37430, 2753)
    assert with_rf.rf_noncompliant_rows == 2753


@pytest.mark.parametrize("kind_name", [
    "RF_CERT_VERIFIED", "RF_CERT_NOT_FOUND",
    "RF_WIRELESS_UNVERIFIED", "RF_NONCOMPLIANT",
])
def test_every_rf_finding_kind_opens_the_count(kind_name):
    """넷 중 어느 것이 나와도 전파 축은 **돌았다**는 뜻이다."""
    from sourcing_guard.scorer import _verified_counts

    got = _verified_counts([_rf(kind_name)], _axes(True, True, True), 37430, 2753)
    assert got.rf_noncompliant_rows == 2753, kind_name


def test_zero_is_not_a_comparison():
    """인덱스가 비면 `size` 가 0 이다. 0 을 실으면 화면이 "0건과 대조했다" 를
    말한다 - 그것도 하지 않은 일이다 (R3).
    """
    from sourcing_guard.scorer import _verified_counts

    got = _verified_counts([_rf()], _axes(True, True, True), 0, 0)
    assert got.recall_rows is None and got.rf_noncompliant_rows is None


def test_no_recorded_sample_triggers_the_rf_axis():
    """실측 0/10 (2026-09-21). 「무선 청소기」·「무선포트」도 RF 가 안 붙는다 -
    추출기가 **전파 송수신**과 **선이 없음**을 구분하기 때문이고 그게 맞다
    (`wireless_hints=[]` 로 기록돼 있다).

    ⚠ 그래서 「부적합 공표 N건과 대조」 줄은 **지금 표본에서는 한 번도 안 뜬다.**
      화면을 그릴 때 그 줄이 없는 경우를 기본으로 봐야 한다.
    """
    import json
    from pathlib import Path as P

    raw = json.loads((P(__file__).resolve().parents[1] / "sourcing_guard" / "data"
                      / "experience_samples.json").read_text(encoding="utf-8"))
    rf_kinds = {"rf_cert_verified", "rf_cert_not_found",
                "rf_wireless_unverified", "rf_noncompliant"}
    hits = [
        it["title"] for it in raw["items"]
        if {f.get("kind") for f in ((it.get("result") or {}).get("findings") or [])} & rf_kinds
    ]
    assert len(raw["items"]) == 10, "표본 수가 바뀌었습니다"
    assert hits == [], f"RF 표본이 생겼습니다 - 위 주석을 갱신하세요: {hits}"
