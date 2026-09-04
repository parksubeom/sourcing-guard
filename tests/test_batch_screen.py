"""대량 검사 화면.

API 만 있고 화면이 없으면 셀러가 쓸 길이 없다. 셀러는 상품을 한 건씩
붙여넣지 않는다 - 도매 플랫폼에서 엑셀을 받아 수백 건을 한 번에 올린다.

화면이 지켜야 하는 것 넷:
  ① 잘림을 보여준다      조용히 버리면 셀러가 검사됐다고 믿는다
  ② 후보를 목록으로       괄호 안에 넣으면 셋 이상일 때 안 읽힌다
  ③ 판정별로 접는다       500줄을 다 펼치면 못 읽는다
  ④ 엑셀로 가져갈 수 있다  화면에만 있으면 손으로 옮겨야 한다
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sourcing_guard.batch import MAX_ROWS
from sourcing_guard.main import app

FRONT = Path(__file__).resolve().parents[1] / "sourcing_guard" / "static" / "batch.html"


def src() -> str:
    return FRONT.read_text(encoding="utf-8")


def test_the_page_is_served():
    with TestClient(app) as client:
        res = client.get("/batch")
    assert res.status_code == 200
    assert "대량 검사" in res.text


def test_every_screen_links_to_it():
    """만들어 두고 길을 안 내면 아무도 못 찾는다."""
    static = FRONT.parent
    for page in ("index.html", "watch.html", "batch.html"):
        assert 'href="/batch"' in (static / page).read_text(encoding="utf-8"), page


# --- ① 잘림 ---------------------------------------------------------------
def test_truncation_is_shown_not_swallowed():
    body = src()
    assert "truncNote" in body
    assert "잘렸습니다" in body
    assert "d.truncated" in body


def test_the_api_reports_truncation_over_the_limit():
    over = 20
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/batch",
            json={"text": "\n".join(f"선풍기 미니 {i}호" for i in range(MAX_ROWS + over))},
        )
    body = res.json()
    assert body["truncated"] == over
    assert body["total"] == MAX_ROWS
    assert body["max_rows"] == MAX_ROWS


# --- ② 후보 목록 -----------------------------------------------------------
def test_split_rows_render_candidates_as_a_list():
    """단건 화면에서 "셋 이상이면 괄호 안에서 안 읽힌다" 고 판단한 것과 같다."""
    body = src()
    assert "b-cands" in body
    assert "r.matched_items" in body
    # 대표 품목이 있을 때만 단일 표기를 쓴다.
    assert "if (r.matched_item)" in body


# --- ③ 접기 ---------------------------------------------------------------
def test_rows_are_grouped_and_folded():
    body = src()
    assert "<details" in body
    assert "MAX_SHOWN" in body
    assert "펼치기" in body
    # 다시 볼 것만 펼쳐 둔다.
    assert 'key === "needs_review" || key === "cert_required"' in body


def test_the_review_order_puts_actionable_first():
    """셀러는 500줄을 다 읽지 않는다. 다시 볼 것부터 둔다."""
    body = src()
    order = [
        body.index('"needs_review"'),
        body.index('"cert_required"'),
        body.index('"check_supplier"'),
        body.index('"absence_normal"'),
    ]
    assert order == sorted(order), "판정 순서가 뒤바뀌었다"


# --- ④ 엑셀 ---------------------------------------------------------------
def test_results_can_be_taken_to_excel():
    body = src()
    assert "toTsv" in body
    assert "엑셀로 복사" in body
    assert "파일로 저장" in body
    # 탭 구분 + BOM. BOM 이 없으면 엑셀이 한글을 깨뜨린다.
    assert "\\t" in body
    assert "﻿" in body


def test_the_copy_falls_back_when_the_clipboard_is_blocked():
    """클립보드는 권한·컨텍스트에 따라 막힌다. 막히면 직접 고를 수 있어야 한다."""
    body = src()
    assert "직접 복사해 주세요" in body


def test_the_export_carries_the_split_candidates_too():
    """갈린 행을 엑셀로 가져갈 때 대표 하나만 나가면 화면과 어긋난다."""
    body = src()
    assert 'r.matched_item || (r.matched_items || []).join(" | ")' in body
