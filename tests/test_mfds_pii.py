"""식약처 응답에서 제3자 정보가 **디스크에 닿지 않는지** 잠근다 (CLAUDE.md §6).

⚠ 도매꾹과 방향이 반대다 - 여기는 **남길 목록**이라 "목록 밖은 버려진다" 가
  기본이다. 그 성질이 유지되는지가 이 파일의 첫째 관심사다.

⚠⚠ **반대 방향도 잰다.** 전화번호 정규식을 바코드·일련번호에 걸면 정상 값이
  개인정보로 읽혀 수집이 멈춘다 - 도매꾹에서 인증번호 `YU101649-22001` 이
  대표번호 패턴에 걸렸던 그 자리다. 아래 `test_a_barcode_is_not_a_phone_number`
  가 그 반대쪽이다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sourcing_guard.mfds_pii import (
    DROPPED_ON_PURPOSE,
    KEEP_FIELDS,
    ResidualPiiError,
    residual,
    rows_of,
    sanitize,
    sanitize_row,
    write_sanitized,
)

#: 총괄이 이름을 찍어 지시한 목록 (2026-09-14). 바꾸려면 지시가 있어야 한다.
_ORDERED = (
    "PRDTNM", "BSSHNM", "RTRVLPRVNS", "BRCDNO", "PRDLST_CD", "PRDLST_CD_NM",
    "RTRVL_GRDCD_NM", "CRET_DTM", "RTRVLDSUSE_SEQ", "MNFDT", "DISTBTMLMT",
)


def _row(**over) -> dict:
    base = {
        "PRDTNM": "동결건조 블루베리",
        "BSSHNM": "○○식품",
        "RTRVLPRVNS": "이물(금속) 혼입",
        "BRCDNO": "8801234567890",
        "PRDLST_CD": "13",
        "PRDLST_CD_NM": "과자류",
        "RTRVL_GRDCD_NM": "2등급",
        "CRET_DTM": "20260910",
        "RTRVLDSUSE_SEQ": "20260910001",
        "MNFDT": "20260801",
        "DISTBTMLMT": "20270801",
        "ADDR": "경기도 성남시 분당구 판교로 123",
        "TELNO": "031-123-4567",
        "IMG_FILE_PATH": "/recall/img/1.jpg",
        "LCNS_NO": "1234567890",
    }
    base.update(over)
    return base


def test_the_keep_list_is_exactly_what_was_ordered():
    """남길 목록이 지시와 같다. 늘리는 것도 줄이는 것도 지시가 있어야 한다."""
    assert KEEP_FIELDS == _ORDERED, (
        f"목록에만 있는 것 {set(KEEP_FIELDS) - set(_ORDERED)} · "
        f"지시에만 있는 것 {set(_ORDERED) - set(KEEP_FIELDS)}"
    )
    assert not set(KEEP_FIELDS) & set(DROPPED_ON_PURPOSE), "버릴 것이 남길 목록에 있다"


def test_the_third_party_fields_never_survive():
    """ADDR · TELNO · IMG_FILE_PATH · LCNS_NO 는 남지 않는다."""
    counts: dict[str, int] = {}
    out = sanitize_row(_row(), counts)
    for gone in DROPPED_ON_PURPOSE:
        assert gone not in out, gone
        assert counts[f"{gone} 제거"] == 1, counts
    assert set(out) == set(KEEP_FIELDS)


def test_a_field_we_have_never_seen_is_dropped_by_default():
    """⚠⚠ **남길 목록의 존재 이유다.** API 가 필드를 늘려도 기본이 '버린다'."""
    counts: dict[str, int] = {}
    out = sanitize_row(_row(NEW_FIELD_2027="누가 나중에 추가한 값"), counts)
    assert "NEW_FIELD_2027" not in out
    assert counts["목록 밖 필드 제거"] == 1, counts


def test_the_envelope_is_not_stored():
    """저쪽 봉투를 저장하지 않는다 - 안 본 필드가 따라 들어온다."""
    payload = {"I0490": {"total_count": "2", "RESULT": {"CODE": "INFO-000"},
                         "row": [_row(), _row()]}}
    clean, counts = sanitize(payload)
    assert set(clean) == {"출처", "행_경로", "남긴_필드", "행"}
    assert "total_count" not in json.dumps(clean, ensure_ascii=False)
    assert "INFO-000" not in json.dumps(clean, ensure_ascii=False)
    assert counts["행"] == 2


def test_the_row_path_is_found_not_assumed():
    """봉투 경로를 가정하지 않는다 (R5 - 실호출 전에 만들었다)."""
    rows, path = rows_of({"I0490": {"row": [_row()]}})
    assert len(rows) == 1 and path == ".I0490.row"
    rows, path = rows_of({"어디든": {"깊이": {"목록": [_row(), _row()]}}})
    assert len(rows) == 2 and path == ".어디든.깊이.목록"


# ── 잔존 검사: 양방향 ────────────────────────────────────────────
def test_a_phone_inside_a_free_text_field_stops_the_save(tmp_path: Path):
    """회수 사유에 전화번호가 오면 **파일을 만들지 않고 던진다.**"""
    payload = {"row": [_row(RTRVLPRVNS="회수 문의 02-123-4567 로 연락")]}
    clean, _ = sanitize(payload)
    assert residual(clean) == ["행[0].RTRVLPRVNS (전화)"]

    out = tmp_path / "회수.json"
    with pytest.raises(ResidualPiiError):
        write_sanitized(out, payload)
    assert not out.exists(), "던지고도 파일을 만들었다"
    assert not list(tmp_path.iterdir()), "사이드카도 만들면 안 된다"


def test_an_address_inside_a_free_text_field_is_caught():
    clean, _ = sanitize({"row": [_row(BSSHNM="○○식품 (경기도 성남시)")]})
    assert residual(clean) == ["행[0].BSSHNM (주소)"]


def test_a_barcode_is_not_a_phone_number():
    """⚠⚠ **반대 방향.** 13자리 바코드·숫자 일련번호가 개인정보로 읽히면
    정상 수집이 멈춘다. 코드 필드는 잔존 검사에서 본다 - 모양이 아니라 자리다.
    """
    clean, _ = sanitize({"row": [_row()]})
    assert residual(clean) == []


@pytest.mark.parametrize("text", ["동결건조 블루베리", "작동 불량으로 회수",
                                  "도라지청", "시금치 세척 제품"])
def test_ordinary_product_words_are_not_read_as_addresses(text: str):
    """'동'·'시'·'도' 가 든 평범한 말이 주소로 읽히면 안 된다."""
    clean, _ = sanitize({"row": [_row(PRDTNM=text, RTRVLPRVNS=text)]})
    assert residual(clean) == [], text


def test_the_sidecar_records_what_was_removed(tmp_path: Path):
    """무엇을 몇 개 지웠는지 적는다 - 안 세면 지워졌는지 알 수 없다."""
    out = tmp_path / "회수.json"
    counts = write_sanitized(out, {"row": [_row(), _row()]})
    assert out.exists()
    side = json.loads(
        (tmp_path / "회수.json.정제.json").read_text(encoding="utf-8"))
    assert side["건수"]["ADDR 제거"] == 2
    assert side["건수"]["TELNO 제거"] == 2
    assert side["잔존"] == []
    assert side["남긴_필드"] == list(KEEP_FIELDS)
    assert counts["행"] == 2

    saved = json.loads(out.read_text(encoding="utf-8"))
    body = json.dumps(saved, ensure_ascii=False)
    assert "031-123-4567" not in body and "판교로" not in body


# ── 저장 경로 잠금 ──────────────────────────────────────────────
#
# ⚠⚠ **지금은 대상이 0개다** (실호출 0회 · 수집 스크립트는 ⑦-b-3 에서 생긴다).
#   빈 목록을 보고 통과하는 검사를 이 저장소에서 여러 번 겪었으므로, 그 수를
#   여기 적어 **늘어나는 순간 실패하게** 둔다. 그때 아래 검사가 실제로 무는지
#   확인하고 이 수를 옮긴다.
_EXPECTED_COLLECTORS = 0


def test_any_mfds_collector_saves_only_through_write_sanitized():
    """식약처를 부르는 스크립트는 `write_sanitized` 로만 저장한다.

    CLAUDE.md §6: "외부 응답을 저장하는 코드는 개인정보 제거 함수를 거치지
    않으면 저장할 수 없게 짠다."
    """
    import re

    root = Path(__file__).resolve().parents[1]
    users = sorted(
        p for p in (root / "scripts").glob("*.py")
        if "foodsafetykorea" in p.read_text(encoding="utf-8")
    )
    assert len(users) == _EXPECTED_COLLECTORS, (
        f"식약처를 부르는 스크립트 수가 {_EXPECTED_COLLECTORS} → {len(users)} 로 "
        f"바뀌었다: {[p.name for p in users]}. 아래 검사가 실제로 무는지 확인하고 "
        "_EXPECTED_COLLECTORS 를 옮겨라"
    )
    for p in users:
        code = "\n".join(
            ln for ln in p.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")
        )
        assert "write_sanitized(" in code, f"{p.name} 이 정제 경로를 안 쓴다"
        assert not re.search(r"response|resp|payload|\.json\(\)", code) or \
            "write_sanitized(" in code
        assert not re.search(r"\.write_text\(", code), (
            f"{p.name} 이 정제 경로 밖에서 파일을 쓴다"
        )
