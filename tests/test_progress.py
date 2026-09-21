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


def test_attention_counts_axes_not_findings():
    """⚠⚠ **왼쪽이 축인데 오른쪽만 finding 이면 분모가 다르다** (§6).

    화면은 「3가지 확인 · 1가지 주의」라고 쓴다. 둘은 같은 것을 세야 한다.
    처음에 finding 개수로 셌고, RED 에서 취소 + 리콜이 2 로 나왔다 - 그 둘은
    **같은 축 둘**(cert · recall)이라 축으로 세도 2 지만, 한 축에 두 건이
    걸리면 갈린다.
    """
    from sourcing_guard.scorer import _verified_counts  # noqa: F401  (임포트 확인)
    from sourcing_guard.scorer import _progress

    # 인증 축 하나에 두 건이 걸린 경우 - finding 은 2, **축은 1**.
    two_on_one = [_f(FindingKind.KC_REVOKED), _f(FindingKind.KC_SUSPENDED)]
    got = _progress(Signal.AMBER, _axes(True, True, True), two_on_one)
    assert got.attention == 1, (
        f"한 축에 두 건이 걸렸는데 {got.attention} 로 셉니다 - finding 을 센 것입니다")


def test_every_flagged_kind_knows_its_axis():
    """⚠ `FindingGroup.FINDING` 인데 지도에 없으면 그 축이 **조용히 안 세어진다.**

    새 kind 가 생겼을 때 여기서 잡는다 (§6 "손으로 유지하는 목록은 낡는다").
    """
    from sourcing_guard.models import FindingGroup, _FINDING_GROUP
    from sourcing_guard.scorer import _ATTENTION_AXIS

    flagged = {k for k, g in _FINDING_GROUP.items() if g is FindingGroup.FINDING}
    known = {k.value for k in _ATTENTION_AXIS}
    missing = sorted(flagged - known)
    assert not missing, f"주의 kind 인데 축 지도에 없습니다: {missing}"
    extra = sorted(known - flagged)
    assert not extra, f"주의 kind 가 아닌데 축 지도에 있습니다: {extra}"


# ── 화면 ────────────────────────────────────────────────────────────

def _index() -> str:
    from pathlib import Path

    from tests.srccheck import markup_only

    return markup_only((Path(__file__).resolve().parents[1] / "sourcing_guard"
                        / "static" / "index.html").read_text(encoding="utf-8"))


def test_the_screen_picks_the_shape_but_does_not_build_the_words():
    """화면은 `kind` 를 보고 **고르기만** 한다. 문구는 서버 것이다 (§6).

    ⚠ "3 / 3" 이나 "N가지 확인" 을 화면에서 조립하면 같은 판단이 두 벌이 된다.
    """
    src = _index()
    assert "data.progress" in src, "진행도를 안 그립니다"
    assert 'pr.kind !== "none"' in src, "RED 에서 진행도를 빼는 가드가 없습니다"
    assert "pr.lead" in src and "pr.parts" in src, "서버 문구를 안 씁니다"
    for made_up in ("가지 확인", "가지 주의", "가지 미수록", "축 모두 확인"):
        assert made_up not in src, f"화면이 진행도 문구를 짓고 있습니다: {made_up}"


def test_the_green_box_needs_a_number():
    """⚠⚠ 숫자 없는 초록 상자는 **축에 초록 칠한 것**이다 (사양 §2-⑧).

    그리고 한 줄은 그 축이 `done` 일 때만 그린다 - `done === false` 를 다른
    말로 바꿔 채우지 않는다 (4-r 이 고치려던 잘못이다).
    """
    src = _index()
    assert "rv-did" in src
    # ⚠ **쓰이는 자리**를 본다. 선언만 보면 `if` 에서 빼도 안 물린다 -
    #   2026-09-21 에 실제로 그랬다 (§6 "가드를 만들 때 반대 방향도 재라").
    assert "didRows.length && hasNumber" in src, "숫자가 없어도 초록 상자를 그립니다"
    assert "filter(function (a) { return a.done; })" in src, (
        "안 한 축까지 초록 상자에 넣고 있습니다")


def test_the_progress_bar_is_not_a_signal_colour():
    """⚠⚠ **진행도는 판정이 아니다.** `design/tokens.css` 원칙 2 -
    "신호등 색은 판정을 말하는 자리에만. 버튼·링크·장식에 쓰지 않는다."

    초록 막대는 그 순간 판정으로 읽힌다. 사양 이미지가 초록이었고 그것이
    틀렸다 (2026-09-21 총괄 정정).
    """
    import re
    from pathlib import Path

    from tests.srccheck import markup_only

    css = markup_only((Path(__file__).resolve().parents[1] / "sourcing_guard"
                       / "static" / "app.css").read_text(encoding="utf-8"))
    m = re.search(r"\.rv-score \.bar i\{([^}]*)\}", css)
    assert m, "진행도 막대 규칙이 없습니다"
    body = m.group(1)
    for banned in ("--signal-green", "--signal-amber", "--signal-red", "--signal-unknown"):
        assert banned not in body, (
            f"진행도 막대에 신호색을 썼습니다({banned}) - 진행도는 판정이 아닙니다")
    assert "--brand" in body, "막대 색이 --brand 가 아닙니다"


def test_red_shows_the_problem_before_what_we_did():
    """⚠⚠ RED 는 **빨강이 먼저**다 (사양 §2-③).

    「확인했습니다」가 「안전인증취소」보다 위에 있으면 뜻이 흐려진다.
    같은 정보라도 그 자리에서 답하는 질문이 달라서 제목도 바뀐다.
    """
    src = _index()
    assert 'if (sig !== "RED") html += didBox;' in src, (
        "RED 에서도 초록 상자를 먼저 그립니다")
    assert 'if (sig === "RED") html += didBox;' in src, (
        "RED 에서 초록 상자를 아예 안 그립니다 - 빼는 것이 아니라 뒤로 옮기는 것입니다")
    assert "어떻게 찾았나" in src, "RED 제목이 그대로입니다"
    i_groups = src.index("rv-groups")
    i_red_box = src.rindex('if (sig === "RED") html += didBox;')
    assert i_groups < i_red_box, "RED 의 초록 상자가 finding 묶음보다 앞에 있습니다"


def test_the_unused_spec_classes_are_gone():
    """쓰지 않는 클래스를 남기면 다음 사람이 "쓰라고 만든 것" 으로 읽는다.

    `.rv-cause`·`.rv-next` 는 사양이 **빈 화면에 그린 것**이라 생겼는데,
    `rv-groups`·`.rv-ask` 가 이미 같은 말을 한다 (총괄 판정 2).
    """
    import re
    from pathlib import Path

    from tests.srccheck import markup_only

    css = markup_only((Path(__file__).resolve().parents[1] / "sourcing_guard"
                       / "static" / "app.css").read_text(encoding="utf-8"))
    for gone in (".rv-cause", ".rv-next"):
        assert not re.search(re.escape(gone) + r"[\s.,:{]", css), (
            f"안 쓰는 클래스가 남아 있습니다: {gone}")
