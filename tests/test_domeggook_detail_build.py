"""A-4 산출물 — 무엇으로 잰 것인지가 파일 안에 적혀 있는지 잠근다.

⚠ 이 검사의 요지는 "텍스트가 있다" 가 아니다. **이 텍스트가 상세페이지 DOM
  이 아니라 API 필드로 조립한 것**이라는 조건이 파일 머리에 남아 있는지,
  치환 토큰 줄이 지워지지 않았는지, 개인정보가 없는지를 본다. 조건이 빠진
  숫자는 다시 물어야 한다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from sourcing_guard.domeggook_fields import is_placeholder
from sourcing_guard.domeggook_pii import residual

_TXT = Path("tests/fixtures/도매꾹_상세텍스트_2026-09-08.txt")
_JSON = Path("tests/fixtures/도매꾹_구조_2026-09-08.json")
_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")


def _mod():
    sys.path.insert(0, "scripts")
    import build_domeggook_detail as m

    return m


_SECTION = re.compile(r"^=====\s*(\d+)\s*=====\s*$", re.M)


def _text() -> str:
    if not _TXT.exists():
        pytest.skip("A-4 텍스트가 아직 없습니다")
    return _TXT.read_text(encoding="utf-8")


def _head_and_body(text: str) -> tuple[str, str]:
    """머리와 본문을 첫 **구획 줄**에서 가른다.

    ⚠ `text.split("=====")` 로 가르면 안 된다 - 머리의 설명문 안에
      `'===== <번호> ====='` 라는 형식 설명이 있어서 머리가 잘린다.
    """
    m = _SECTION.search(text)
    assert m, "구획 줄이 없다"
    return text[: m.start()], text[m.start():]


def _struct() -> dict:
    if not _JSON.exists():
        pytest.skip("A-4 구조 JSON 이 아직 없습니다")
    return json.loads(_JSON.read_text(encoding="utf-8"))


# ── 조건이 파일 안에 있다 ────────────────────────────────────────────
def test_header_says_it_is_assembled_not_a_dom_paste():
    head, _ = _head_and_body(_text())
    assert "API 필드로 조립한 텍스트" in head
    assert "이미지 안의 글자는 없다" in head
    assert "치환 토큰" in head


def test_header_states_the_counts_it_was_built_from():
    head, _ = _head_and_body(_text())
    s = _struct()
    n = s["건수"]["채택"]
    assert f"채택 {n}건" in head
    assert f"대상 {s['건수']['대상']}" in head


# ── 치환 토큰을 지우지 않았다 ────────────────────────────────────────
def test_contact_token_lines_survive_in_the_text():
    """셀러가 붙여 넣는 텍스트에도 A/S 연락처는 있다.

    추출기가 그것을 무시하는지도 측정의 일부라 줄을 지우지 않는다.
    """
    _head, body = _head_and_body(_text())
    assert "[연락처]" in body


def test_no_pii_in_either_artifact():
    body = _text()
    assert residual(body) == []
    assert residual(_struct()) == []


# ── 번호·집합이 맞다 ─────────────────────────────────────────────────
def test_every_section_number_is_a_sample_row():
    scope_nos = set()
    for line in _SCOPE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        scope_nos.add(int(line.split("\t")[0]))
    nos = [int(m) for m in _SECTION.findall(_text())]
    assert nos, "구획이 없다"
    assert len(nos) == len(set(nos)), "같은 번호가 두 번 있다"
    assert set(nos) <= scope_nos
    assert len(nos) == _struct()["건수"]["채택"]


def test_structured_rows_match_the_text_sections():
    s = _struct()
    assert len(s["상품"]) == s["건수"]["채택"]
    counts = {"대상": 0, "비대상": 0, "애매": 0}
    for row in s["상품"]:
        counts[row["대상분류"]] += 1
    for k, v in counts.items():
        assert s["건수"][k] == v


# ── seller 없음 · imgUrl 유지 ────────────────────────────────────────
def test_structured_json_has_no_seller_and_keeps_cert_image_url():
    s = _struct()
    for row in s["상품"]:
        assert "seller" not in row
        assert set(row["도매꾹_카테고리"]) <= {"name", "code", "depth"}
    # safetyCert[].imgUrl 은 이미지 추출 경로의 입력이라 남긴다.
    with_img = [c for row in s["상품"] for c in row["safetyCert"] if c.get("imgUrl")]
    assert with_img, "imgUrl 이 전부 사라졌다 - kc_numbers_from_image 입력이 없어진다"


def test_placeholder_flag_agrees_with_the_shared_judgement():
    """`내용없음` 플래그가 `domeggook_fields.is_placeholder` 와 어긋나면 안 된다."""
    for row in _struct()["상품"]:
        for entry in row["infoDuty"]["item"]:
            assert entry["내용없음"] == is_placeholder(entry["desc"])


# ── 조립 규칙 ────────────────────────────────────────────────────────
def test_assemble_skips_dash_placeholders_but_keeps_real_values():
    m = _mod()
    item = {
        "detail": {"country": "중국", "manufacturer": "-", "model": "M1"},
        "category": {"current": {"name": "블록"}},
    }
    text = m.assemble_text("블록 완구", item)
    assert "제조국 : 중국" in text
    assert "모델 : M1" in text
    assert "제조사" not in text, "'-' 는 값이 아니다"
    assert text.startswith("블록 완구")


def test_assemble_writes_the_certification_number_when_present():
    m = _mod()
    item = {"detail": {"safetyCert": [
        {"cert": "Y", "certType": "안전확인", "certName": "안전확인신고",
         "no": "CB061R2170-3018", "exem": "N"}]}}
    text = m.assemble_text("블록 완구", item)
    assert "인증번호 : CB061R2170-3018" in text
    assert "인증면제" not in text


def test_assemble_marks_exemption():
    m = _mod()
    item = {"detail": {"safetyCert": [
        {"cert": "N", "no": "-", "exem": "Y", "exemTitle": "구매대행"}]}}
    text = m.assemble_text("블록 완구", item)
    assert "인증면제 : 구매대행" in text
    assert "인증번호" not in text, "'-' 를 인증번호로 적으면 안 된다"
