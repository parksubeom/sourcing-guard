"""[4-f] 매처 측정을 되살렸다 — 재현을 없애고 `lookup_all` 의 trace 를 센다.

전에는 `scripts/measure_matcher.py` 가 `lookup_all` 의 1단계를 **직접 재현**했고,
그 재현이 낡아 자기검사에서 멈췄다. 세 기준선 중 하나가 죽어 있으면 회귀 방어가
둘뿐이다.

⚠ **자기검사가 옳았고 재현이 틀렸다.** 재현에는 그 뒤 들어온 가드 셋과 접두 확장
  단계가 없었다. 기대값을 현재 출력에 맞춰 덮어쓰는 것은 검사를 없애는 것이다.
  그래서 재현을 고치는 대신 없앴다.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from sourcing_guard.item_grades import ItemGradeBook

sys.path.insert(0, "scripts")


def _book() -> ItemGradeBook:
    return ItemGradeBook()


# ── trace 계약 ──────────────────────────────────────────────────────
def test_trace_records_every_candidate_with_an_outcome():
    """통과한 것만 돌려주는 API 로는 "왜 안 붙었나" 를 셀 수 없다."""
    book = _book()
    trace: list[dict] = []
    got = book.lookup_all("무선 블루투스 스피커 충전 거치대", trace=trace)

    assert trace, "후보가 하나도 기록되지 않았다"
    assert {r["outcome"] for r in trace} <= {"accepted", "rejected", "guard"}
    # 통과한 것의 수가 결과와 맞아야 한다.
    accepted = [r for r in trace if r["outcome"] == "accepted"]
    assert len(accepted) == len(got)
    assert {r["item"] for r in accepted} == {g.item for g in got}


def test_trace_says_which_signal_rejected():
    """매처는 거부하는 쪽으로만 강하다 - 그 신호 이름이 곧 "왜" 다."""
    book = _book()
    trace: list[dict] = []
    book.lookup_all("에어프라이어 토스터기 선반", trace=trace)
    reasons = {r.get("rejected_by") for r in trace if r["outcome"] == "rejected"}
    guards = {r.get("reason") for r in trace if r["outcome"] == "guard"}
    assert reasons or guards, "거부 사유가 하나도 없다"


def test_trace_is_off_by_default_and_does_not_change_the_result():
    """측정이 판정을 바꾸면 안 된다."""
    book = _book()
    name = "유아용 블록 완구 장난감"
    without = [g.item for g in book.lookup_all(name)]
    trace: list[dict] = []
    with_trace = [g.item for g in book.lookup_all(name, trace=trace)]
    assert without == with_trace


def test_the_case_that_broke_the_old_self_check_is_correctly_rejected():
    """`장갑 높이조절 스탠드 스팀 다리미판 행거 지지대` → 붙지 않는다.

    옛 재현은 `['스팀다리미','의류']` 를 냈고 실제 코드는 `[]` 를 냈다.
    **실제 코드가 옳다** - `test_standalone_accessory_at_the_end_blocks_the_match`
    가 이 상품을 오답으로 잡는 가드를 이미 적어 뒀다.
    """
    book = _book()
    assert book.lookup_all("장갑 높이조절 스탠드 스팀 다리미판 행거 지지대") == []


# ── 기준선 ③ ───────────────────────────────────────────────────────
@pytest.mark.parametrize("sample", ["도매꾹239", "새표본235"])
def test_sample_matching_counts_match_the_baseline(sample):
    """다섯 기준의 ③. 죽어 있던 것을 되살렸다 (4-f)."""
    from audit_tally import BASELINE_MATCH

    book = _book()
    names = [
        n.strip()
        for n in pathlib.Path(f"tests/fixtures/{sample}.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if n.strip()
    ]
    base = BASELINE_MATCH[sample]
    assert len(names) == base["total"]
    matched = sum(1 for n in names if book.lookup_all(n))
    assert matched == base["matched"], (
        f"{sample} 매칭이 기준선과 다르다: {matched} vs {base['matched']} - "
        "정당한 변경이면 [기준선 변경] 커밋으로 다섯 숫자를 전/후로 적을 것"
    )


def test_the_script_no_longer_reimplements_stage_one():
    """재현이 돌아오면 또 낡는다. 같은 규칙을 두 곳에 두지 않는다."""
    src = pathlib.Path("scripts/measure_matcher.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "trace=trace" in code, "trace 를 쓰지 않는다"
    # 1단계를 다시 짜는 흔적이 없어야 한다.
    for banned in ("book._by_name", "book._contain_keys", "rival_wins(", "judge("):
        assert banned not in code, f"1단계를 재현한다: {banned}"


# ---------------------------------------------------------------------------
# 4-g. '걸이' 를 부속품명 목록에서 뺐다 — 길이가 아니라 의미 때문이다
# ---------------------------------------------------------------------------
def test_a_wall_mounted_heater_is_a_heater_not_a_hanger():
    """`벽걸이` 는 거는 **방식**이다. 파는 물건은 히터다.

    4-f 에서 매처 측정을 되살리자 09-04 대비 정답 1건이 빠진 것이 보였다.
    `accessory_follows_the_key` 가 `'걸이'` 를 `벽걸이` **안에서** 찾아
    `전기온풍기` 를 거부하고 있었다.
    """
    book = _book()
    got = [
        g.item for g in book.lookup_all(
            "PTC 리모컨 온풍기 벽걸이히터 전기난로 전기히터 사은품 답례품 "
            "판촉물 집들이선물 미니난로 히터"
        )
    ]
    assert "전기온풍기" in got, got


def test_the_word_hanger_is_gone_but_holder_and_shelf_stay():
    """**2자라서 뺀 것이 아니다.** '홀더'도 2자이고 남아 있다.

        벽걸이 · 문걸이            거는 방식을 말한다
        벽선반 · 컵홀더 · 신발행거   물건 자체를 말한다
    """
    from sourcing_guard.item_grades import _STANDALONE_ACCESSORIES

    assert "걸이" not in _STANDALONE_ACCESSORIES
    for kept in ("홀더", "행거", "선반", "거치대", "보관함", "정리함"):
        assert kept in _STANDALONE_ACCESSORIES, kept


def test_the_two_wrong_answers_that_candidate_c_would_let_in_stay_rejected():
    """후보 C(2자 전부 제거)가 더 붙이던 2건은 둘 다 오답이다.

    두 번째는 `새표본235_오답.tsv` `[고쳐짐 2]` 에 이미 있는 줄이라, C 를
    택하면 그 수정을 되돌리게 된다.
    """
    book = _book()
    assert book.lookup_all("핸디캐디 주방 정리 밥솥 에어프라이어 토스터기 선반") == []
    assert book.lookup_all(
        "(기본형) 홀더 거치대 헤어 기수납 드라이기 욕실 드라이 헤어 드라이어"
    ) == []


def test_removing_the_word_did_not_move_the_other_sample():
    """새표본235 는 116 그대로여야 한다. ③ 만 움직였다."""
    from audit_tally import BASELINE_MATCH

    assert BASELINE_MATCH["새표본235"]["matched"] == 116
    assert BASELINE_MATCH["도매꾹239"]["matched"] == 168


# ---------------------------------------------------------------------------
# 4-h. 거부 사유를 key_absent 와 accessory_or_negated 로 가른다 (라벨 변경)
# ---------------------------------------------------------------------------
def test_a_key_that_is_not_in_the_name_is_not_an_accessory_judgement():
    """`is_the_subject` 는 키가 이름에 **아예 없을 때**도 False 를 낸다.

    그걸 "부속품·부정 표현으로만 나옵니다" 로 적으면 숫자가 오독된다 -
    도매꾹239 거부 136,078건 중 **136,069건이 key_absent** 이고 진짜 부속품
    판단은 **2건**이다. 가르지 않으면 다음 사람이 "우리 매처가 너무 엄격하다"
    로 읽고 가드를 푼다.
    """
    book = _book()
    trace: list[dict] = []
    book.lookup_all("유아용 블록 완구 장난감", trace=trace)

    rejected = [r for r in trace if r["outcome"] == "rejected"]
    assert rejected, "거부된 후보가 없으면 이 검사가 무의미하다"
    for row in rejected:
        if row["rejected_by"] == "key_absent":
            assert row["key_in_name"] is False, row
        elif row["rejected_by"] == "accessory_or_negated":
            assert row["key_in_name"] is True, row


def test_the_split_is_a_label_change_and_moves_no_verdict():
    """판정은 그대로다 - `judge` 도 `verdict` 도 건드리지 않았다."""
    book = _book()
    for name in ("유아용 블록 완구 장난감", "무선 블루투스 스피커",
                 "PTC 리모컨 온풍기 벽걸이히터 전기난로"):
        trace: list[dict] = []
        got = book.lookup_all(name, trace=trace)
        accepted = [r for r in trace if r["outcome"] == "accepted"]
        assert {r["item"] for r in accepted} == {g.item for g in got}


def test_the_measure_output_explains_both_reasons():
    """숫자만 내면 오독된다. 출력이 둘의 뜻을 함께 적는다."""
    src = pathlib.Path("scripts/measure_matcher.py").read_text(encoding="utf-8")
    assert "key_absent" in src
    assert "부속품 판단이 아니다" in src
    assert "진짜 부속품 판단" in src
