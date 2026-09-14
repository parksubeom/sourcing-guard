"""[⑦-a] 전파 적합성평가 대상기자재 표.

⚠⚠ **화면에 연결하지 않았다.** 기준(총괄)은 "새표본235 + 도매꾹239 에서 비대상
  오부착 0" 이었고 실측은 3건이다. 표는 리포에 두고 화면은 "무선 기능 표기가
  있습니다" 를 유지한다 - 등급표를 올릴 때와 같은 기준이다.

  이 파일이 지키는 것은 둘이다: **표가 원자료와 맞는가**, 그리고 **화면에
  조용히 연결되지 않았는가.**
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from sourcing_guard.rf_equipment import example_aliases, rf_book, table, wired_to_screen

_ROOT = Path(__file__).resolve().parents[1]
_YAML = _ROOT / "sourcing_guard/data/rf_target_equipment.yaml"
_RAW = sorted((_ROOT / "tests/fixtures").glob("전파_대상기자재_고시_*.json"))[-1]
TYPES = {"적합인증", "적합등록", "자기적합확인", "적합등록/자기적합확인"}


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return table()["items"]


# ── 원자료와 맞는가 ────────────────────────────────────────────────
def test_the_raw_appendix_is_kept_untouched():
    """원자료는 손대지 않는다 - 파싱이 틀렸을 때 되짚을 곳이 여기뿐이다."""
    raw = json.loads(_RAW.read_text(encoding="utf-8"))
    assert raw["행정규칙일련번호"] == "2100000282888"
    assert raw["별표제목"] == "적합성평가 대상기자재(제3조 관련)"
    assert raw["별표구분"] == "별표"
    assert len(raw["별표내용"]) == 1989


def test_the_appendix_is_chosen_by_title_not_by_number():
    """⚠ 번호로 고르면 **서식**을 집는다 - 응답에 `별표번호 0001` 이 둘이다.

    고시가 개정되면 번호가 밀린다. 제목으로 고른다.
    """
    src = (_ROOT / "scripts/probe_rf_target_equipment.py").read_text(encoding="utf-8")
    assert 'TITLE = "적합성평가 대상기자재(제3조 관련)"' in src
    assert "별표제목" in src
    # 번호로 고르는 코드가 다시 들어오면 안 된다.
    assert '별표번호"] == "0001' not in src


def test_every_row_carries_its_evidence(rows):
    """R2 · R5 — 줄마다 유형·기기부호·출처·원문 행 번호가 있어야 한다."""
    assert len(rows) == 367
    for r in rows:
        assert r["item"], r
        assert r["grade"] in TYPES, r
        assert r["category"] == "rf"
        assert r["source"].startswith("방송통신기자재등의 적합성평가에 관한 고시 별표 1")
        assert isinstance(r["별표행"], int) and r["별표행"] > 0
        # 기기부호는 세로 병합되지만 **빈 줄은 없어야 한다**(위에서 물려받는다).
        assert r["device_code"], r["item"]


def test_the_device_code_of_a_merged_run_is_inherited(rows):
    """⑧⑨⑩ 감자탈피기·전기정미기·전기빵자르개가 ⑦ 의 `KCN12` 를 함께 쓴다."""
    codes = {r["item"]: r["device_code"] for r in rows}
    for item in ("과일껍질깎기", "감자탈피기", "전기정미기", "전기빵자르개"):
        assert codes.get(item) == "KCN12", (item, codes.get(item))


def test_a_name_split_across_two_physical_rows_is_joined(rows):
    """"라.해상이동업무용 디지털선택호출" / "장치의 기기" 가 두 줄에 걸친다."""
    sv = next(r for r in rows if r["device_code"] == "SV")
    assert sv["item"] == "VHF송수신장치"
    assert "장치의 기기" in sv["scope_note"], sv["scope_note"]


def test_a_definition_paragraph_is_not_used_as_the_item_name(rows):
    """11절 소분류는 정의 문단이다. 이름은 그 위 칸이고 문단은 예시로 간다."""
    cln = next(r for r in rows if r["device_code"] == "CLN11")
    assert cln["item"] == "전기청소기류"
    assert "진공청소기" in cln["examples"] and "로봇청소기" in cln["examples"]
    for r in rows:
        assert "(정의)" not in r["item"], r["item"]
        assert "대표적인 품목" not in r["item"], r["item"]


def test_the_examples_come_from_the_notice_not_from_us(rows):
    """별칭은 **고시가 적어 둔 대표 품목**이다. 우리가 지어내지 않는다 (R5).

    ⚠ 원자료 전체와 대조하면 안 된다. 표가 **한 낱말을 여러 물리 줄에 걸쳐**
      쓰고, 그 사이에 왼쪽 칸의 다른 글자가 끼어든다:

          │ ※ 전동기의 정격입력은  │  │ - 진공청소기, 물흡입청소기(물걸레청소기  │
          │전력을 기준으로 한다.   │  │표면세척기, 스팀청소기, …                 │

      그래서 대조는 **그 행의 정의 문단**과 한다 - 정의 문단은 파서가 같은
      칸의 조각을 이어 붙인 것이고, 그 이어 붙이기가 맞는지는 위 검사들이
      따로 잠근다. 처음에 통째로 대조했다가 정상 예시 90건이 "없는 말" 로
      읽혔다.
    """
    squash = lambda t: re.sub(r"[\s│┃─━]+", "", t)
    missing = []
    for r in rows:
        body = squash(r.get("definition", "") or r.get("scope_note", ""))
        for x in r.get("examples", []):
            if squash(x) not in body:
                missing.append((r["device_code"], x))
    assert missing == [], missing[:8]


def test_the_definition_text_is_kept_so_examples_can_be_traced(rows):
    """예시가 어디서 왔는지 되짚을 수 있게 정의 문단을 남긴다."""
    with_ex = [r for r in rows if r.get("examples")]
    assert len(with_ex) == 76
    for r in with_ex:
        assert r.get("definition"), r["device_code"]


def test_the_aliases_are_what_makes_matching_possible():
    """별칭이 없으면 **0건**이다 - 표 이름이 류 단위라 상품명과 안 겹친다."""
    book = rf_book()
    title = "이에스 로봇청소기 무선청소기 충전청소기 물걸레 청소걸레 밀대"
    assert book.lookup_all(title) == []
    got = book.lookup_all(title, extra_aliases=example_aliases())
    assert [g.item for g in got] == ["전기청소기류"]


# ── 화면에 조용히 연결되지 않았는가 ───────────────────────────────
def test_the_table_is_not_wired_to_the_screen():
    """⚠⚠ **이 검사가 이 파일의 핵심이다.**

    기준은 "비대상 오부착 0" 이었고 실측 3건이다. 표가 생겼다는 이유로
    화면에 붙이면, 정수기 종이컵에 "적합인증 대상입니다" 가 뜬다.
    """
    assert wired_to_screen() is False
    src = _ROOT / "sourcing_guard"
    users = [p.relative_to(_ROOT) for p in src.rglob("*.py")
             if p.name not in ("rf_equipment.py",)
             and "rf_equipment" in p.read_text(encoding="utf-8")]
    assert users == [], f"화면·판정 경로가 전파 표를 쓰고 있다: {users}"
    for page in (src / "static").glob("*.html"):
        assert "적합인증 대상입니다" not in page.read_text(encoding="utf-8"), page.name


def test_the_reason_for_not_wiring_is_written_down():
    """왜 안 붙였는지가 표에 적혀 있어야 한다. 다음 사람이 그냥 켜지 않게."""
    text = _YAML.read_text(encoding="utf-8")
    assert "화면에 연결하지 않았다" in text
    assert "비대상 오부착" in text
    for line in ("정수기컵", "킥매트", "시트커버"):
        assert line in text, line
    assert "무선 기능 표기가 있습니다" in text


def test_the_measurement_script_fails_while_the_count_is_not_zero():
    """측정 스크립트가 **0이 아니면 실패**해야 한다. 통과하면 열린 줄 안다."""
    src = (_ROOT / "scripts/measure_rf_attachment.py").read_text(encoding="utf-8")
    assert "if wrong:" in src and "return 1" in src
    assert "ItemGradeBook" in src, "같은 매처를 써야 한다"


def test_the_table_is_generated_not_hand_edited():
    text = _YAML.read_text(encoding="utf-8")
    assert "손으로 고치지 않는다" in text
    assert "scripts/build_rf_target_equipment.py" in text
    assert yaml.safe_load(text)["version"] == 1
