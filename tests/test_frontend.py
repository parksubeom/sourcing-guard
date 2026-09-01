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

STATIC = Path("sourcing_guard/static")
PAGES = ["index.html", "watch.html"]
ASSETS = PAGES + ["app.css", "owner.js"]


@pytest.fixture(scope="module")
def html() -> str:
    """정적 자산 전체를 한 덩어리로 본다.

    CSS 와 공용 스크립트를 별도 파일로 빼면서 index.html 만 보던 가드가
    조용히 통과하기 시작했다. 페이지가 늘어도 규약은 같으므로 전부 합쳐 본다.
    """
    return "\n".join((STATIC / f).read_text(encoding="utf-8") for f in ASSETS)


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    return {f: (STATIC / f).read_text(encoding="utf-8") for f in PAGES}


@pytest.mark.parametrize("path", ["/", "/watch"])
def test_pages_are_served(path):
    from sourcing_guard.main import app

    with TestClient(app) as client:
        r = client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.parametrize("path", ["/static/app.css", "/static/owner.js"])
def test_shared_assets_are_served(path):
    from sourcing_guard.main import app

    with TestClient(app) as client:
        assert TestClient(app).get(path).status_code == 200


def test_both_pages_use_the_same_stylesheet(pages):
    """배지·색·톤이 두 화면에서 갈리면 같은 RED 를 다른 것으로 읽는다."""
    for name, src in pages.items():
        assert '/static/app.css' in src, name
        assert "<style>" not in src, f"{name} 에 페이지 전용 스타일이 생겼습니다"


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
    assert "esc:" in html or "function esc(" in html
    assert "&amp;" in html and "&lt;" in html
    for name, src in {"index.html": None, "watch.html": None}.items():
        page = (STATIC / name).read_text(encoding="utf-8")
        assert "window.SG.esc" in page or "SG.esc" in page, name


def test_recall_cutoff_date_is_rendered_readably(html):
    """20260828 을 그대로 내보내면 읽히지 않는다."""
    assert "리콜 대조 기준" in html
    assert "asOfLabel" in html


def test_scan_posts_page_text_not_a_url(html):
    """서버는 상거래 사이트를 가져오지 않는다 (CLAUDE.md R4).

    입력은 사용자가 직접 복사한 본문이다. URL 을 보내면 서버가 그 페이지를
    가져와야 하고, 그건 ToS 위반이자 봇 차단으로 데모 중에 죽는 길이다.
    """
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "page_text" in index
    assert "page_url" not in index
    assert "서버가 판매 사이트에 직접 접속하지 않습니다" in index


# ---------------------------------------------------------------------------
# 감시 목록 — 이 서비스가 유일하게 보증하는 것 (기획서 §3-4단계, §6.1)
# ---------------------------------------------------------------------------


def test_watch_page_states_what_is_promised(pages):
    """"지금 안전하다"는 보증할 수 없지만 "놓치지 않는다"는 보증할 수 있다.

    그 경계가 화면에서 읽혀야 한다. 감시 목록은 우리가 유일하게 약속하는
    것이라, 무엇을 약속하고 무엇을 못 하는지 감추면 안 된다.
    """
    w = pages["watch.html"]
    assert "보증할 수 없습니다" in w
    assert "놓치지 않는 것" in w


def test_watch_page_does_not_promise_undelivered_notifications(pages):
    """알림 발송은 v1 범위 밖이다. 없는 기능을 있는 것처럼 적으면 안 된다."""
    w = pages["watch.html"]
    assert "아직 준비 중입니다" in w
    assert "이메일·카카오" in w


def test_watch_page_discloses_how_the_list_is_identified(pages):
    """로그인이 없다. 브라우저 저장소로 묶인다는 사실을 알려야 한다."""
    assert "브라우저에 저장된 식별자" in pages["watch.html"]


def test_scan_page_offers_registration(pages):
    assert "이 상품 감시하기" in pages["index.html"]
    assert "/api/v1/watch" in pages["index.html"]


def test_matched_items_reuse_the_scan_red_treatment(html):
    """스캔의 RED 와 같은 색·배지를 쓴다. 갈리면 같은 위험을 다르게 읽는다."""
    assert ".item.hit" in html
    assert "background:var(--danger)" in html.replace(" ", "").replace(
        "background:var(--danger)", "background:var(--danger)"
    ) or "var(--danger)" in html


def test_matched_items_stay_marked_after_a_reload(pages):
    """sweep 은 이미 알린 리콜을 다시 돌려주지 않는다.

    새로고침하면 알림 목록이 비므로, 표시를 sweep 응답에만 의존하면 강조가
    사라진다. seen_recall_fingerprints 로 이력을 유지한다.
    """
    assert "seen_recall_fingerprints" in pages["watch.html"]


def test_watch_page_links_back_to_scan(pages):
    assert 'href="/"' in pages["watch.html"]
    assert 'href="/watch"' in pages["index.html"]


def test_scan_page_shows_the_server_headline(pages):
    """셀러의 질문은 "이거 소싱해도 돼?" 다. 헤드라인이 거기에 직접 답한다.

    서버 문장을 그대로 써야 한다. 프론트가 다시 쓰면 GREEN 의 "판매자 제공
    정보 기준으로" 같은 §6.1 한계 문구가 조용히 사라진다.
    """
    index = pages["index.html"]
    assert "data.headline" in index
    assert "esc(head)" in index
