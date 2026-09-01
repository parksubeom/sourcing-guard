"""단일 페이지 프론트엔드.

디자인 규약(KRDS)에서 차용한 것은 접근성 우선의 시각 언어다. 아래 가드는 그중
빌드 없이 검증 가능한 것만 고정한다 - 이모지 금지, 포커스 표시 제거 금지,
본문 H1 금지, 정부 식별 요소 이식 금지.

정부 식별 요소를 넣지 않는 이유: 우리는 정부 서비스가 아니다. "공식 전자정부
누리집" 배너나 대한민국정부 워드마크를 달면 사용자가 이 서비스를 정부가
운영한다고 오해한다. 법령 도메인이라 그 오해가 특히 비싸다.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

INDEX = Path("sourcing_guard/static/index.html")


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_index_is_served_at_root():
    from sourcing_guard.main import app

    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_no_emoji_anywhere(html):
    """이모지는 어떤 자리에도 쓰지 않는다. 상태는 색·아이콘·텍스트로 전달한다."""
    found = [c for c in html if 0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF]
    assert not found, f"이모지가 있습니다: {found}"


def test_focus_outline_is_never_removed(html):
    """outline:none 은 키보드 사용자에게서 현재 위치를 빼앗는다."""
    assert "outline:none" not in html.replace(" ", "")
    assert "outline: 2px solid" in html or "outline:2px solid" in html


def test_body_does_not_use_h1(html):
    """헤딩 위계는 H2 이하로 운영한다."""
    assert not re.search(r"<h1[\s>]", html, re.I)


def test_corner_radius_stays_within_scale(html):
    """12px 상한. pill(999px)은 칩·점 전용으로 예외."""
    over = [
        v for v in re.findall(r"border-radius:\s*(\d+)px", html)
        if 12 < int(v) < 999
    ]
    assert not over, f"라운드 상한 초과: {over}"


def test_no_government_identity_is_borrowed(html):
    """정부 식별 요소를 비정부 제품에 이식하지 않는다."""
    for banned in ("전자정부", "대한민국정부", "누리집"):
        assert banned not in html, f"정부 식별 문구 '{banned}' 가 있습니다"


def test_design_system_name_is_not_shown_in_ui(html):
    """차용한 것은 시각 언어이지 시스템 이름이 아니다."""
    assert "KRDS" not in html


def test_disclaimer_is_always_visible(html):
    """모든 결과 화면에 고정 표기한다 (CLAUDE.md §9)."""
    assert "법적 판단이나 안전 인증을 대체하지 않습니다" in html


def test_no_verdict_language_in_ui_copy(html):
    """단정 표현은 쓰지 않는다 (CLAUDE.md §9)."""
    for banned in ("안전합니다", "합법입니다", "판매 가능합니다", "문제없습니다"):
        assert banned not in html, f"단정 표현 '{banned}' 가 있습니다"


def test_hazard_rules_are_collapsed(html):
    """적용 기준 14종을 그대로 펼치면 셀러가 읽을 화면이 아니게 된다."""
    assert "hazard_rule_applies" in html
    assert "<details" in html
    assert "적용되는 유해물질 기준" in html


def test_source_links_open_in_a_new_tab_safely(html):
    """근거 링크는 새 창으로 열되 opener 를 넘기지 않는다."""
    assert 'target="_blank"' in html
    assert 'rel="noopener noreferrer"' in html


def test_user_input_is_escaped_before_rendering(html):
    """스캔 응답을 innerHTML 로 그린다. 이스케이프가 빠지면 붙여넣은 본문이 실행된다."""
    assert "function esc(" in html
    assert "&amp;" in html and "&lt;" in html


def test_recall_cutoff_date_is_rendered_readably(html):
    """20260828 을 그대로 내보내면 읽히지 않는다."""
    assert "리콜 대조 기준" in html
    assert "asOfLabel" in html


def test_scan_posts_page_text_not_a_url(html):
    """서버는 상거래 사이트를 가져오지 않는다 (CLAUDE.md R4).

    입력은 사용자가 직접 복사한 본문이다. URL 을 보내면 서버가 그 페이지를
    가져와야 하고, 그건 ToS 위반이자 봇 차단으로 데모 중에 죽는 길이다.
    """
    assert "page_text" in html
    assert "page_url" not in html
    assert "서버가 판매 사이트에 직접 접속하지 않습니다" in html
