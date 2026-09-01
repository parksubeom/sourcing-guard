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


def test_demo_texts_come_from_the_server(pages):
    """프론트가 데모 문구를 따로 들고 있으면 서버의 상한 면제 목록과 갈라진다.

    그러면 상한을 넘긴 순간 데모 버튼이 429 를 받는다 - 투표자가 첫 화면에서
    보는 그 버튼이다 (핸드오프 §9).
    """
    from sourcing_guard.demos import DEMO_TEXTS

    index = pages["index.html"]
    assert "/api/v1/demos" in index
    # placeholder 예시에 인증번호가 있는 건 정상이다. 데모 문구 자체가 박혀
    # 있는지를 본다 — 그게 서버 면제 목록과 갈라지는 지점이다.
    for text in DEMO_TEXTS:
        assert text not in index, f"데모 문구가 프론트에 하드코딩돼 있습니다: {text[:30]}"


def test_scan_page_shows_the_rate_limit_message(pages):
    """429 를 "서버가 429 로 응답했습니다" 로 보여주면 셀러가 뭘 해야 할지 모른다."""
    assert "429" in pages["index.html"]


def test_scan_page_surfaces_degraded_extraction(pages):
    """한도를 넘겨 간이 추출로 갔으면 그 사실을 감추지 않는다."""
    assert "extraction_note" in pages["index.html"]


# ---------------------------------------------------------------------------
# 이미지 붙여넣기 (기획서 §2 — 상세표가 이미지뿐인 페이지)
#
# 이미지 API 만 열려 있고 화면이 없으면, 통짜 이미지 페이지를 가진 셀러는
# 이 서비스를 쓸 수 없다. 그게 이 기능을 붙인 이유다.
# ---------------------------------------------------------------------------


def test_paste_area_exists_and_names_the_shortcut(pages):
    """캡처 도구로 잘라 붙이는 것이 셀러의 자연스러운 동선이다."""
    index = pages["index.html"]
    assert 'id="paste"' in index
    assert "Ctrl+V" in index
    assert "Cmd+V" in index, "Mac 사용자에게도 단축키를 알려야 한다"


def test_scan_sends_images_as_base64(pages):
    index = pages["index.html"]
    assert "images:" in index
    assert "media_type" in index
    assert "readAsDataURL" in index


def test_images_can_be_sent_together_with_text(pages):
    """텍스트와 이미지를 함께 보낼 수 있어야 한다.

    인증번호는 이미지에서 읽지 않으므로, 셀러는 캡처를 붙이고 인증번호만
    텍스트로 적는 조합을 쓴다. 그 조합이 막히면 이미지 페이지에서는 인증
    조회를 아예 못 한다.
    """
    index = pages["index.html"]
    assert "page_text: text," in index, "page_text 와 images 가 같은 본문에 실려야 한다"
    assert "!text && !shots.length" in index, "이미지만 있어도 검사해야 한다"


def test_image_types_match_the_server_allowlist(pages):
    """SVG 는 서버가 거절한다. 프론트에서 먼저 걸러 사용자가 422 를 보지 않게 한다."""
    index = pages["index.html"]
    for mt in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        assert mt in index, mt
    assert "image/svg" not in index

    # 서버 상한과 갈라지면 4장을 붙인 뒤 검사에서 거절당한다.
    from sourcing_guard.main import ScanRequest

    field = ScanRequest.model_fields["images"]
    server_max = next(
        (m.max_length for m in field.metadata if getattr(m, "max_length", None)), None
    )
    assert server_max == 4
    assert "MAX_SHOTS = 4" in index


def test_screen_explains_the_two_paths_for_cert_numbers(pages):
    """이미지에서 읽되 바로 조회하지 않는다는 것을 화면이 말해야 한다.

    이전에는 "이미지에서 읽지 않습니다" 였다. 그러면 KC 마크만 붙은 상세페이지가
    "인증번호 없음" 으로 처리되는데, KC 마크 이미지는 규정상 유효한 기재라
    실제로는 있는 인증을 안 본 것이다 (R3).

    그렇다고 바로 조회하면 0/O 오독 하나가 정상 인증을 "조회 안 됨" 으로
    뒤집는다. 그래서 경로가 둘이고, 화면이 그 차이를 설명해야 한다 - 안 적으면
    셀러는 왜 어떤 번호는 바로 조회되고 어떤 번호는 확인을 요구하는지 모른다.
    """
    index = pages["index.html"]
    assert "바로 조회하지는 않습니다" in index
    assert "확인한 뒤 조회" in index
    # 텍스트 경로는 그대로 자동 조회라는 것도 남아 있어야 한다
    assert "직접 적으면 확인 없이 바로 조회" in index


def test_image_read_numbers_get_a_confirm_button(pages):
    """이미지에서 읽은 번호는 확인 버튼으로 나가야 한다.

    문장만 내면 셀러가 번호를 손으로 옮겨 적어야 하고, 그 자리에서 이탈한다.
    버튼은 번호를 입력란에 넣고 다시 검사한다 - 그때부터는 텍스트 경로라
    자동 조회된다. 조회 경로를 새로 만들지 않는 것이 요점이다.
    """
    index = pages["index.html"]
    assert 'f.kind === "kc_image_candidate"' in index
    assert "detail.candidates" in index
    assert "data-kc" in index


def test_findings_are_rendered_in_server_groups(pages):
    """서버가 묶어준 구획을 그대로 그려야 한다.

    확정 일치와 유사 일치가 한 목록에 섞이면 셀러가 구분하지 못한다 - 실제로
    "펜을 검사했는데 왜 블라인드가 뜨나" 라는 질문이 나왔다. 프론트가 다시
    정렬하면 판정 기준이 두 벌이 되므로 서버 순서를 그대로 쓴다.
    """
    index = pages["index.html"]
    assert "grouped_findings" in index
    assert 'class="fgroup ' in index
    # 약한 일치는 리콜 일치와 같은 모양으로 그리지 않는다
    assert 'f.kind === "recall_weak_match"' in index


def test_pasting_plain_text_is_not_intercepted(pages):
    """클립보드에 이미지가 없으면 붙여넣기를 가로채지 않는다.

    본문 붙여넣기가 주 입력 경로다. 그걸 막으면 기능 하나 붙이려다 본 기능을
    깨뜨린다.
    """
    index = pages["index.html"]
    assert "if (!files.length) return;" in index


def test_demo_buttons_clear_pasted_images(pages):
    """데모는 서버가 보낸 문구 그대로를 검사해야 한다.

    붙여둔 이미지가 섞이면 예시와 다른 결과가 나오고, 투표자가 첫 화면에서
    보는 것이 그 결과다.
    """
    index = pages["index.html"]
    demo_click = index[index.index('b.addEventListener("click"'):]
    demo_click = demo_click[: demo_click.index('$("demos").appendChild(b)')]
    assert "shots = []" in demo_click
    assert "scan();" in demo_click


# ---------------------------------------------------------------------------
# "우리가 이렇게 읽었습니다" — 판정 위의 신뢰 (허점 1)
# ---------------------------------------------------------------------------


def test_extracted_is_rendered_above_the_verdict(pages):
    """판정보다 위에 둔다.

    우리가 잘못 읽었으면 셀러가 여기서 바로 알아채야 하고, 제대로 읽었으면
    아래 판정을 믿는다. 순서가 뒤집히면 이미 판정을 본 뒤에 근거를 보게 된다.
    """
    index = pages["index.html"]
    assert "이 페이지에서 이렇게 읽었습니다" in index
    body = index[index.index("function render(data)"):]
    read_at = body.index("readBlock(data.extracted)")
    verdict_at = body.index('<div class="verdict ')
    assert read_at < verdict_at, "읽은 값이 신호등보다 아래에 그려집니다"


def test_government_lookup_links_are_buttons_but_stay_anchors(pages):
    """모양은 버튼, 요소는 a.

    실제로 페이지를 이동하므로 button 으로 만들면 스크린리더가 동작을 잘못
    알린다. 새 창으로 열되 opener 는 넘기지 않는다.
    """
    index = pages["index.html"]
    go = index[index.index("function goLink("):]
    go = go[: go.index("\n  }")]
    assert "<a class=\\\"golink\\\"" in go or "'<a class=\"golink\"" in go
    assert 'target="_blank"' in go
    assert "noopener noreferrer" in go
    assert "<button" not in go


def test_cert_number_carries_its_lookup_link(pages):
    """화면의 인증번호에 정부 조회를 붙인다. 셀러가 그 번호가 맞는지 직접 확인한다."""
    index = pages["index.html"]
    read = index[index.index("function readBlock("):]
    read = read[: read.index("\n  }")]
    assert "f.link" in read and "goLink(" in read


def test_missing_cert_search_link_is_an_action_button(pages):
    """인증번호가 없을 때의 검색 링크는 셀러가 다음에 할 일이라 버튼으로 낸다."""
    index = pages["index.html"]
    row = index[index.index("function findingRow("):]
    row = row[: row.index("\n  }")]
    assert "kc_missing_but_required" in row
    assert "goLink(f.source_url" in row


# ---------------------------------------------------------------------------
# 감시 제안 — GREEN 의 유효기간을 넘김 (허점 2)
# ---------------------------------------------------------------------------


def test_watch_reason_comes_from_the_server(pages):
    """프론트가 문구를 다시 쓰면 GREEN 의 "조회 시점 기준" 한계가 조용히 사라진다."""
    index = pages["index.html"]
    assert "data.watch_suggestion" in index
    assert "ws.reason" in index


def test_green_watch_suggestion_is_emphasised(pages):
    """GREEN 은 가장 약한 신호다. 셀러가 '안전'으로 읽으면 우리가 가장 크게 빗나간다."""
    index = pages["index.html"]
    assert 'sig === "GREEN"' in index
    assert "watch-cta.lead" in (STATIC / "app.css").read_text(encoding="utf-8")


def test_no_watch_button_when_the_server_says_it_cannot_be_watched(pages):
    """지킬 수 없는 약속은 권하지 않는다.

    감시할 단서가 없으면 스캔에서 버튼을 감춘다 — 누르게 해두고 등록에서
    거절하면 사용자를 배신한다.
    """
    index = pages["index.html"]
    assert "ws.can_watch" in index
    assert "canWatch" in index
    block = index[index.index("var ws = data.watch_suggestion"):]
    block = block[: block.index('if (data.disclaimer)')]
    assert 'id="watch"' in block and "canWatch" in block


def test_maker_other_recalls_is_visually_separated(pages):
    """같은 제조사의 다른 리콜을 리콜 일치와 같은 모양으로 그리면 안 된다.

    셀러가 "이 상품이 리콜됐다" 로 읽는다. 서버 문장에 단서가 붙어 있지만
    화면 표시도 달라야 한다 - 색과 배지가 같으면 문장을 읽기 전에 판단한다.
    """
    index = pages["index.html"]
    assert 'f.kind === "maker_other_recalls"' in index
    assert "aside" in index
    assert ".findings>li.aside" in (STATIC / "app.css").read_text(encoding="utf-8")


def test_empty_extraction_is_explained_as_an_input_problem(pages):
    """읽은 값이 없으면 원인을 말해야 한다.

    안 말하면 화면은 "판단 보류 — 판매자 제공 정보만으로는 소싱 여부를 가릴 수
    없습니다" 로 끝나는데, 셀러는 그걸 상품에 대한 판정으로 읽고 닫는다. 실제로는
    URL 한 줄이나 배송 안내만 붙여넣은 것일 수 있고, 그건 다시 붙여넣으면 풀린다.
    """
    index = pages["index.html"]
    assert "data.input_note" in index
    assert 'class="input-note"' in index
    # "이렇게 읽었습니다" 블록이 비는 자리를 대신한다 — 그 앞에 와야 한다
    assert index.index("data.input_note") < index.index("readBlock(data.extracted)")
