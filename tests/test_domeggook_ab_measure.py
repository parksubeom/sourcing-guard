"""A-5 A/B 측정 — 라벨과 집계 규칙을 잠근다.

⚠ **이 검사의 요지는 두 가지다.** (1) 숫자에 입력 조건이 붙어 있다.
  (2) "정답" 집계가 검수 파일(`새표본235_오답.tsv`)을 실제로 읽는다 -
  매칭됐다는 것만으로 정답으로 세면 오답이 개선으로 보인다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_OUT = Path("tests/fixtures/도매꾹_AB_2026-09-08.json")
_TXT = Path("tests/fixtures/도매꾹_상세텍스트_2026-09-08.txt")


def _mod():
    sys.path.insert(0, "scripts")
    import measure_domeggook_ab as m

    return m


# ── 입력 자르기 ──────────────────────────────────────────────────────
def test_split_details_drops_comments_and_keeps_bodies(tmp_path):
    m = _mod()
    p = tmp_path / "d.txt"
    p.write_text(
        "# 머리말 - '===== <번호> =====' 형식이라고 설명한다\n"
        "\n# [7] (대상) 어떤 상품\n===== 7 =====\n본문 첫 줄\n본문 둘째 줄\n"
        "\n# [9] (비대상) 다른 상품\n===== 9 =====\n다른 본문\n",
        encoding="utf-8",
    )
    got = m.split_details(p)
    assert got == {7: "본문 첫 줄\n본문 둘째 줄", 9: "다른 본문"}


def test_split_details_ignores_the_format_note_in_the_header():
    """머리말이 형식을 설명하며 같은 모양을 적는다 - 구획으로 세면 안 된다."""
    m = _mod()
    if not _TXT.exists():
        pytest.skip("A-4 텍스트가 아직 없습니다")
    got = m.split_details(_TXT)
    assert len(got) == 190
    assert all(isinstance(k, int) and v for k, v in got.items())


def test_reviewed_sections_are_read_from_the_audit_file():
    """정답 집계가 검수 파일을 실제로 읽는지."""
    m = _mod()
    wrong, vague = m.load_reviewed()
    assert wrong, "오답 절이 비었다 - 그러면 모든 매칭이 정답으로 세어진다"
    assert not (wrong & vague), "같은 줄이 오답과 애매에 동시에 있다"


# ── 집계 ─────────────────────────────────────────────────────────────
def test_tally_reads_candidates_and_signal():
    m = _mod()
    payload = {
        "signal": "AMBER",
        "facts": {"kc_numbers": ["CB061R2170-3018"], "materials": ["PVC"],
                  "target_age": "3세 이상", "legal_item_name": "완구",
                  "category": "children_toy", "rf_numbers": [],
                  "kc_numbers_from_image": []},
        "findings": [
            {"kind": "item_grade_matched",
             "detail": {"grade": "안전확인", "candidates": [{"item": "완구"}]}},
            {"kind": "hazard_rule_applies", "detail": {}},
            {"kind": "child_catch_all", "detail": {}},
        ],
    }
    t = m.tally(payload)
    assert t["matched"] and t["items"] == ["완구"] and t["grades"] == ["안전확인"]
    assert t["kc"] == 1 and t["materials"] == 1 and t["age"] is True
    assert t["hazard"] == 1 and t["catch_all"] is True
    assert t["signal"] == "AMBER"


def test_tally_on_an_empty_scan_is_all_zero():
    m = _mod()
    t = m.tally({"signal": "UNKNOWN", "facts": {}, "findings": []})
    assert not t["matched"] and t["kc"] == 0 and t["hazard"] == 0
    assert t["age"] is False and t["catch_all"] is False


def test_pacer_keeps_the_minimum_gap_between_starts():
    import time

    m = _mod()
    p = m.Pacer(0.2)
    p.wait()
    t0 = time.monotonic()
    p.wait()
    assert time.monotonic() - t0 >= 0.19


# ── 산출물의 라벨 ────────────────────────────────────────────────────
def _out() -> dict:
    if not _OUT.exists():
        pytest.skip("A-5 결과가 아직 없습니다")
    return json.loads(_OUT.read_text(encoding="utf-8"))


def test_raw_result_carries_its_conditions():
    """조건이 빠진 숫자는 다시 물어야 한다."""
    o = _out()
    label = o["라벨"]
    for piece in ("gpt", "단건", "도매꾹 API 정제 텍스트", "분모"):
        assert piece in label, label
    assert o["extraction_order"][0] == "gpt"


def test_vendor_is_confirmed_by_the_counter_not_by_output_shape():
    """CLAUDE.md R7: 어느 벤더가 뽑았는지 출력 모양으로 추론하지 않는다."""
    o = _out()
    delta = o["by_vendor_증가분"]
    assert delta.get("gpt", 0) > 0
    assert delta.get("claude", 0) == 0, (
        "claude 로 넘어간 호출이 있다 - 라벨이 'gpt' 하나면 거짓이다"
    )


def test_every_row_has_both_conditions():
    o = _out()
    assert o["행"]
    for r in o["행"]:
        assert r["name_only"].get("facts") is not None
        assert r["detail"].get("facts") is not None
        assert r["detail_chars"] > 0
