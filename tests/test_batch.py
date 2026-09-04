"""대량 검사 - 셀러의 실제 작업 흐름에 맞춘 1차 선별.

셀러는 상품을 하나씩 보고 등록하지 않는다. 도매매·온채널에서 200개 단위로
엑셀을 내려 전송 프로그램으로 일괄 업로드한다. 한 건씩 붙여넣는 화면은 그
흐름과 어긋난다.

핵심 제약은 LLM 예산이다. 일일 상한 500회에서 200건을 전건 LLM 에 보내면 한
번에 40% 를 쓴다. 상품명만으로 판단 가능한 것을 먼저 걸러 LLM 을 아낀다.
"""

import pytest

from sourcing_guard.batch import MAX_ROWS, RowVerdict, parse_lines, screen
from sourcing_guard.item_grades import ItemGradeBook


@pytest.fixture(scope="module")
def book() -> ItemGradeBook:
    return ItemGradeBook()


# --- 입력 파싱 -------------------------------------------------------------
def test_excel_column_paste_is_accepted():
    """엑셀에서 열을 복사하면 줄바꿈으로 구분된다."""
    names, truncated = parse_lines("선풍기 미니\n가습기 USB\n전기포트 1.7L")
    assert names == ["선풍기 미니", "가습기 USB", "전기포트 1.7L"]
    assert truncated == 0


def test_multi_column_paste_takes_the_first_cell():
    """여러 열을 함께 복사하면 탭이 섞인다. 상품명이 앞쪽에 있다."""
    names, _ = parse_lines("선풍기 미니\t12000\t재고10\n가습기\t8000\t재고5")
    assert names == ["선풍기 미니", "가습기"]


def test_header_row_is_dropped():
    """엑셀 열 머리글이 함께 복사되는 일이 흔하다."""
    names, _ = parse_lines("상품명\n선풍기 미니\n제품명\n가습기")
    assert names == ["선풍기 미니", "가습기"]


def test_rows_beyond_the_limit_are_reported_not_silently_dropped():
    """상한을 넘겨 잘렸으면 알려야 한다. 조용히 버리면 셀러가 검사됐다고 믿는다.

    2026-09-04 갱신: 250줄·잘림 50 을 박아 뒀는데 MAX_ROWS 를 실측으로 다시
    정하면서(200 → 500) 깨졌다. 상한값이 아니라 **잘렸다는 사실을 보고하는가**
    가 이 검사의 요지이므로 MAX_ROWS 기준으로 쓴다.
    """
    over = 50
    names, truncated = parse_lines(
        "\n".join(f"상품{i}번" for i in range(MAX_ROWS + over))
    )
    assert len(names) == MAX_ROWS
    assert truncated == over


# --- LLM 예산 -------------------------------------------------------------
def test_most_rows_resolve_without_llm(book):
    """상품명만으로 등급이 확정되면 LLM 을 쓰지 않는다.

    실측(도매꾹 실상품 200건): 144건이 이 단계에서 확정 -> LLM 72% 절감.
    """
    raw = "\n".join([
        "신일 BLDC 무선 선풍기 써큘레이터 캠핑용",
        "휴대용 미니 가습기 USB 무드등",
        "전기포트 1.7L 스테인리스 무선주전자",
        "3단 자동우산 UV 자외선차단 암막",
    ])
    report = screen(raw, book)
    assert report.llm_candidates == 0, "등급이 확정된 줄을 LLM 으로 보내고 있다"


def test_unmatched_rows_are_marked_for_llm(book):
    """품목을 특정 못 하면 상세페이지를 읽어야 한다 - 그때만 LLM 이다."""
    report = screen("무엇인지 알 수 없는 물건 이름", book)
    assert report.rows[0].needs_llm is True
    assert report.rows[0].verdict is RowVerdict.UNDECIDED


# --- 판정 ----------------------------------------------------------------
def test_absence_normal_grades_are_not_warnings(book):
    """공급자적합성확인·안전기준준수는 번호가 없는 것이 정상이다 (R3-b)."""
    report = screen("3단 자동우산 UV 자외선차단 암막 양우산", book)
    row = report.rows[0]
    assert row.verdict is RowVerdict.ABSENCE_NORMAL
    assert "정상" in row.reason


def test_missing_number_in_the_name_is_not_a_warning(book):
    """상품명에 인증번호를 적는 셀러는 거의 없다 - 번호는 상세페이지에 있다.

    "상품명에 번호가 없다" 를 경고로 내면 규제 품목 전부가 경고가 되고(실측
    200건 중 104건), 셀러는 전부 무시한다. R3-b 가 미조회를 RED 로 두지 않은
    것과 같은 이유다. 배치가 할 일은 "이 품목은 번호가 있어야 한다" 를 알리는
    것이다.
    """
    report = screen("신일 BLDC 무선 선풍기 써큘레이터", book)
    row = report.rows[0]
    assert row.verdict is RowVerdict.CERT_REQUIRED
    assert "반드시 있어야" in row.reason
    # 부재 자체를 문제로 단정하지 않는다
    assert "찾지 못했습니다" not in row.reason


def test_split_grades_do_not_pick_a_side(book):
    """등급이 갈리면 후보를 다 담고 한쪽을 고르지 않는다 (R3)."""
    report = screen("공기청정기 미니 탁상용 USB 차량용", book)
    row = report.rows[0]
    if len(row.grade_candidates) > 1:
        assert row.verdict is RowVerdict.CHECK_SUPPLIER
        assert row.grade is None, "갈렸는데 한쪽을 골랐다"


def test_review_first_puts_actionable_rows_on_top(book):
    """셀러는 200줄을 다 읽지 않는다. 다시 볼 것이 위로 와야 한다."""
    raw = "\n".join([
        "3단 자동우산 UV 암막",            # 부재 정상 - 아래로
        "신일 BLDC 무선 선풍기",           # 번호 필수 - 위로
    ])
    report = screen(raw, book)
    order = [r.verdict for r in report.review_first]
    assert order.index(RowVerdict.CERT_REQUIRED) < order.index(RowVerdict.ABSENCE_NORMAL)


def test_batch_declares_that_it_only_read_the_name(book):
    """상세페이지를 안 봤으면 봤다고 말하지 않는다 (R3)."""
    from sourcing_guard.batch import screen as _s

    report = _s("선풍기 미니", book)
    # 판정 사유가 상품명 근거임을 드러내야 한다
    assert report.rows[0].reason
    assert "상세페이지" in report.rows[0].reason or "단건" in report.rows[0].reason


# ---------------------------------------------------------------------------
# 갈릴 때 대표 품목 하나를 고르지 않는다
# ---------------------------------------------------------------------------


def test_split_rows_do_not_name_a_single_representative_item():
    """단건 화면에서 세 겹으로 막은 "한쪽 단정" 을 배치에서 하면 안 된다.

    실측(도매꾹 239건)에서 드러났다 - "보조배터리 10000 C타입보조배터리
    선풍기조끼 쿨링조끼 …" 가 candidates[0] 로 '선풍기' 를 대표로 달았다.
    연관 검색어에서 온 후보이고, 셀러는 보조배터리를 팔면서 선풍기를 본다.
    """
    report = screen(
        "보조배터리 10000 C타입보조배터리 선풍기조끼 쿨링조끼 아이폰 휴대폰",
        grades=ItemGradeBook(),
    )
    row = report.rows[0]
    assert row.verdict is RowVerdict.CHECK_SUPPLIER
    assert row.matched_item is None, row.matched_item
    # 대신 후보를 다 낸다 - 등급처럼 품목도 전부.
    assert len(row.matched_items) > 1
    assert "전지" in row.matched_items


def test_agreed_rows_still_name_the_item():
    """등급이 하나로 모이면 어느 품목을 골라도 결론이 같으므로 이름을 준다."""
    report = screen("신일 BLDC 무선 선풍기 14인치 SIF-B1424CL", grades=ItemGradeBook())
    row = report.rows[0]
    assert row.matched_item == "선풍기"
    assert row.matched_items == ["선풍기"]


def test_the_api_exposes_every_item_candidate():
    """화면이 후보를 다 그리려면 응답에 있어야 한다."""
    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    with TestClient(app) as client:
        res = client.post(
            "/api/v1/batch",
            json={"text": "간편부착 바트 무선 센서라이트 LED센서등 건전지형"},
        )
    assert res.status_code == 200
    row = res.json()["rows"][0]
    assert row["matched_item"] is None
    assert set(row["matched_items"]) == {"LED등기구", "충전식 휴대전등"}
