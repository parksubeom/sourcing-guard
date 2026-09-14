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
import re
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
    """세 토막(시도 + 시군구 + 로/길/읍/면/동/리)이면 잡는다."""
    clean, _ = sanitize({"row": [_row(BSSHNM="○○식품 (경기도 성남시 분당구 판교로 123)")]})
    assert residual(clean) == ["행[0].BSSHNM (주소)"]


@pytest.mark.parametrize("text", [
    "황색포도상구균 기준 규격 부적합",   # ⚠ 실측 5건. '황색포도'+'상구' 로 걸렸었다
    "황색포도상구균 검출",
    "전남 구례군 산수유 농축액",          # 원산지 표기는 개인정보가 아니다
    "제주 감귤 착즙 원액",
])
def test_a_real_recall_reason_is_not_read_as_an_address(text: str):
    """⚠⚠ **실측 376건이 처음 그물을 반증했다.**

    잔존 검사가 걸리면 수집 **전체가 멈춘다** - 오탐이 특히 비싸다.
    """
    clean, _ = sanitize({"row": [_row(RTRVLPRVNS=text, PRDTNM=text)]})
    assert residual(clean) == [], text


@pytest.mark.parametrize("text", [
    "경기 광주시 곤지암읍 소재 업소 제품",
    "○○식품(서울특별시 강남구 테헤란로 1) 회수",
    "충남 아산시 배방읍 공장에서 제조",
])
def test_a_full_address_in_free_text_still_stops_the_save(text: str):
    """반대 방향 - 그물을 성기게 했다고 진짜 주소를 놓치면 안 된다."""
    clean, _ = sanitize({"row": [_row(RTRVLPRVNS=text)]})
    assert residual(clean) == ["행[0].RTRVLPRVNS (주소)"], text


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
# ⚠ 대상 수를 적어 **늘어나는 순간 실패하게** 둔다. 빈 목록을 보고 통과하는
#   검사를 이 저장소에서 여러 번 겪었다.
#
#   0 → 1  2026-09-14 `scripts/sync_mfds_recalls.py` 가 생겼다. 래칫이 실제로
#          물었고(설계대로), 옮기기 전에 아래 검사가 무는지 확인했다 -
#          `write_sanitized` 를 빼면 실패, `.write_text(` 를 넣으면 실패.
_EXPECTED_COLLECTORS = 1


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


# ── 커밋된 정제본에 대한 실제 보증 ──────────────────────────────
_COLLECTED = Path(__file__).resolve().parents[1] / "tests/fixtures/식약처회수_2026-09-14.json"


def test_the_collected_fixture_has_no_third_party_contact_left():
    """**리포에 대한 실제 보증이다.** 커밋된 정제본을 다시 훑는다.

    2026-09-14 20:54 KST · 실호출 4회 · 376건 전량.
    """
    import json

    body = _COLLECTED.read_text(encoding="utf-8")
    data = json.loads(body)
    assert len(data["행"]) == 376, len(data["행"])
    assert data["행_경로"] == ".I0490.row"

    for name, rx in (("전화", r"0\d{1,2}-\d{3,4}-\d{4}"),
                     ("대표번호", r"1[568]\d{2}-\d{4}"),
                     ("사업자번호", r"\d{3}-\d{2}-\d{5}"),
                     ("이메일", r"[\w.]+@[\w.]+\.\w{2,}")):
        assert not re.findall(rx, body), f"{name} 패턴이 남아 있다"
    for gone in DROPPED_ON_PURPOSE:
        assert gone not in body, f"{gone} 가 정제본에 있다"

    keys: set[str] = set()
    for row in data["행"]:
        keys |= set(row)
    assert keys <= set(KEEP_FIELDS), f"남길 목록 밖 필드: {sorted(keys - set(KEEP_FIELDS))}"
    assert residual(data) == []


def test_the_sidecar_records_the_unknown_fields_that_were_dropped():
    """⚠⚠ **남길 목록이 실제로 일한 증거다.**

    총괄 목록에 없던 필드 4개(FRMLCUNIT · PRDLST_REPORT_NO · PRDLST_TYPE ·
    RTRVLPLANDOC_RTRVLMTHD)가 왔고 자동으로 버려졌다. 지울 목록이었으면 넷 다
    디스크에 남았다 - 방향을 뒤집은 이유가 여기서 실측으로 확인됐다.
    """
    import json

    side = json.loads(
        Path(str(_COLLECTED) + ".정제.json").read_text(encoding="utf-8"))
    c = side["건수"]
    assert c["행"] == 376
    for gone in DROPPED_ON_PURPOSE:
        assert c[f"{gone} 제거"] == 376, (gone, c)
    # 376행 × 목록 밖 4필드
    assert c["목록 밖 필드 제거"] == 376 * 4, c
    assert side["잔존"] == []
