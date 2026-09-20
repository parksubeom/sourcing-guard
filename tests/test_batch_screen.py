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


def test_the_screen_promises_the_number_the_server_accepts():
    """⚠⚠ 화면이 약속한 상한과 서버가 받는 상한은 **같은 수**여야 한다.

    다르면 둘 중 하나다 - 셀러가 넣은 줄이 조용히 잘리거나(화면이 크게
    약속), 쓸 수 있는데 안 쓰거나(화면이 작게 약속). 앞엣것은 "검사됐다고
    믿는" 자리라 이 파일 머리말 ①이 막으려던 바로 그것이다.

    ⚠ 반대 방향 - 화면에 수가 아예 없어도 실패한다. 없으면 셀러가 몇 줄까지
      되는지 모른 채 붙여넣는다.
    """
    body = src()
    assert f"최대 {MAX_ROWS}개" in body, (
        f"화면이 상한을 안 적었거나 {MAX_ROWS} 가 아니다 (batch.MAX_ROWS)")

    # 다른 수를 약속하고 있지 않은가. 주석은 빼고 본다.
    from tests.srccheck import markup_only

    import re as _re
    shown = {int(n) for n in _re.findall(r"최대 (\d+)개", markup_only(body))}
    assert shown == {MAX_ROWS}, f"화면이 여러 상한을 말한다: {sorted(shown)}"


def test_the_screen_says_it_is_a_first_pass():
    """⚠⚠ 이 한 줄이 빠지면 셀러가 **배치 결과를 판정으로 읽는다.**

    상품명만 보는 경로라 인증번호도 리콜 모델명도 없다. 단건으로 다시 봐야
    한다는 말이 화면에 없으면, 우리가 "1차 선별" 이라고 부르는 것을 셀러는
    "검사했다" 로 받는다 (총괄 §4).
    """
    from tests.srccheck import markup_only

    body = markup_only(src())
    assert "1차 선별" in body
    assert "단건 검사로 다시" in body


def test_the_screen_offers_no_feature_we_do_not_have():
    """그릇은 시안대로 쓰되 **없는 기능의 단추는 만들지 않는다** (총괄 §5).

    엑셀 파일 업로드·샘플 파일 내려받기는 우리에게 없다. 그려 두면 눌러도
    아무 일이 없고, 그것은 단추가 거짓말을 하는 것이다.
    """
    from tests.srccheck import markup_only

    body = markup_only(src())
    for absent in ("샘플 파일", "파일 선택", ".xlsx", ".xls", "드래그"):
        assert absent not in body, f"없는 기능이 화면에 있다: {absent}"


# ── 끌어다 놓기 (2026-09-20 총괄 §3) ────────────────────────────────
def _js() -> str:
    from tests.srccheck import markup_only

    return markup_only(src())


def test_a_dropped_file_never_navigates_away():
    """막지 않으면 브라우저가 그 파일로 이동해 **붙여넣어 둔 줄이 사라진다.**"""
    js = _js()
    assert 'document.addEventListener("drop"' in js, "떨어뜨리기를 안 받는다"
    assert '"dragover"' in js, "dragover 를 안 막으면 drop 이 아예 안 온다"
    drop = js[js.index('document.addEventListener("drop"'):]
    assert "e.preventDefault()" in drop[: drop.index("\n  });")], "기본 동작을 안 막는다"


def test_a_multi_column_file_is_not_filled_in():
    """⚠⚠ **이게 이 기능의 요지다.** 열이 여럿이면 채우지 않는다.

    우리가 어느 열이 상품명인지 고르면 **틀린 열을 조용히 검사**하고, 셀러는
    검사됐다고 믿는다 - 이 파일 머리말 ①이 막으려던 바로 그것이다.

    ⚠ 반대 방향 - 안 채우고 **끝나면** 셀러는 왜 안 됐는지 모른다. 왜 안
      넣었는지 적는 자리(`#drop-note`)가 있어야 한다.
    """
    js, html = _js(), src()
    assert "function columnCount(" in js, "열 수를 안 센다"
    assert 'id="drop-note"' in html, "왜 안 넣었는지 적는 자리가 없다"
    assert "넣지 않았습니다" in js, "안 넣었다는 말을 안 한다"
    assert "고르면 틀릴 수" in js, "왜 안 넣었는지를 안 말한다"


def test_the_comma_count_needs_every_row_to_agree():
    """⚠ 콤마는 **상품명 안에도** 있다 ("우산, 양산, 자동우산").

    한 줄만 보고 정하면 그 상품명을 세 열로 읽고, 한 열짜리 파일이 거부된다.
    모든 줄이 같은 수일 때만 열로 본다.
    """
    js = _js()
    fn = js[js.index("function columnCount("):]
    fn = fn[: fn.index("\n  }")]
    assert "every(" in fn, "모든 줄이 같은 수인지 안 본다"
    assert "slice(0, 20)" in fn, "줄 수를 제한하지 않는다 - 500줄이면 느리다"


def test_xlsx_is_explained_not_parsed():
    """`.xlsx` 는 zip 이다. 파서도 업로드 엔드포인트도 만들지 않는다.

    ⚠ 저장소에 외부 JS 가 **0건**이고 그 상태를 깨지 않는다. 열 선택 UI 가
      먼저이고 파서는 그다음이다 (미완 §1).
    """
    js = _js()
    assert "xlsx" in js and "엑셀 파일은 열을 복사해" in js, "엑셀 안내가 없다"
    for banned in ("jszip", "xlsx.full", "sheetjs", "cdn.", "unpkg", "jsdelivr"):
        assert banned not in js.lower(), f"외부 라이브러리를 끌어온다: {banned}"


def test_the_screen_still_loads_no_external_script():
    """저장소에 외부 JS 0건 - 이 화면이 그것을 깨지 않는다."""
    import re as _re

    for m in _re.finditer(r'<script[^>]*src="([^"]+)"', src()):
        assert m.group(1).startswith("/static/"), f"외부 스크립트: {m.group(1)}"
