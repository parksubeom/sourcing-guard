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
# ⚠ landing.html 을 넣어야 이모지·h1·고지문·단정 표현 가드가 랜딩에도 걸린다.
# ⚠ guide.html 도 넣는다 - 이모지·h1·고지문·단정 표현 가드가 새 화면에도
#   걸려야 한다. 화면을 늘리면서 가드 목록을 안 늘리면 새 화면만 무방비다.
PAGES = ["index.html", "watch.html", "landing.html", "guide.html"]
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


@pytest.mark.parametrize("path", ["/", "/scan", "/watch"])
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
        # ⚠ 실제 태그만 본다 - 주석의 설명 문구에 걸리지 않게.
        assert not re.search(r"<style[\s>]", src), (
            f"{name} 에 페이지 전용 스타일이 생겼습니다")


def test_no_emoji_anywhere(html):
    """이모지는 어떤 자리에도 쓰지 않는다. 상태는 색·아이콘·텍스트로 전달한다."""
    found = [c for c in html if 0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF]
    assert not found, f"이모지가 있습니다: {found}"


def test_focus_outline_is_never_removed(html):
    """outline:none 은 키보드 사용자에게서 현재 위치를 빼앗는다."""
    assert "outline:none" not in html.replace(" ", "")
    assert "outline: 2px solid" in html or "outline:2px solid" in html


def test_body_does_not_use_h1(html):
    """도구 화면(`/scan` 등)은 H2 이하로 운영한다.

    ⚠⚠ **랜딩은 예외다** (2026-09-13). 도구 화면은 페이지 제목이 워드마크이고
      본문이 h2 부터인데, **랜딩의 주제목은 그 페이지가 무엇인가를 말하는
      한 줄**이라 h1 이 맞다 - 스크린리더가 페이지를 식별하는 자리다.
      `design/landing-hero.html` 정본도 `<h1 class="t-display">` 다.

    ⚠ 예외를 두되 **하나만** 허용한다. 둘 이상이면 위계가 무너진다.
    """
    from pathlib import Path as _Path

    for name in PAGES:
        body = (STATIC / name).read_text(encoding="utf-8")
        found = re.findall(r"<h1[\s>]", body, re.I)
        # ⚠ **문서 화면**은 제목이 하나 있어야 한다. 도구 화면(스캔·감시)은
        #   머리말이 곧 제목이라 h1 을 두지 않지만, 랜딩과 가이드는 읽는 글이고
        #   h1 이 없으면 스크린리더가 문서 제목을 못 읽는다. 둘 다 **하나만**.
        if _Path(name).stem in ("landing", "guide"):
            assert len(found) <= 1, f"{name}: h1 이 {len(found)}개 - 하나만 둔다"
            continue
        assert not found, f"{name}: 도구 화면은 h2 이하로 운영한다"


def test_corner_radius_stays_within_scale(html):
    """반경은 **토큰 눈금 안**에 있어야 한다. pill(999px)은 칩·점 전용 예외.

    ⚠⚠ **2026-09-13 에 상한이 12 → 토큰 최대값으로 바뀌었다.** 디자인 시스템
      v0.1 이 카드 16px · 붙여넣기 카드 20px 을 쓴다. 숫자를 여기 다시 적지
      않고 `design/tokens.css` 의 `--r-*` 최대값을 읽는다 - 두 곳에 적으면
      토큰을 올릴 때 이 검사만 낡는다 (6절).
    """
    import re as _re
    from pathlib import Path as _Path

    tokens = (_Path(__file__).resolve().parents[1] / "design/tokens.css").read_text(
        encoding="utf-8")
    scale = sorted(int(v) for v in _re.findall(r"--r-[a-z]+:\s*(\d+)px", tokens)
                   if int(v) < 999)
    assert scale, "토큰에서 --r-* 를 못 읽었다"
    ceiling = scale[-1]
    over = sorted({
        int(v) for v in re.findall(r"border-radius:\s*(\d+)px", html)
        if ceiling < int(v) < 999
    })
    assert not over, (
        f"라운드 상한({ceiling}px · design/tokens.css 의 --r-* 최대값) 초과: {over}"
    )


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
    """적용 기준 14종을 그대로 펼치면 셀러가 읽을 화면이 아니게 된다.

    v2 에서 자리가 바뀌었다 - 카드 맨 아래 아코디언이 아니라 **참고 정보 줄
    안에서** 한 줄로 접는다(design/README §10-5). 접어도 세 가지는 남는다:
    몇 건인지 · 어떤 물질이 얼마인지 · 원문 링크.
    """
    assert "hazard_rule_applies" in html
    assert "유해물질 공통안전기준" in html
    assert "FOLD_AT = 4" in html, "접기 문턱이 4건이어야 한다 (총괄 명령)"
    # 알약 값은 **서버 detail** 에서 읽는다. 문장에서 뽑으면 화면이 값을 짓는다.
    #
    # ⚠ 오너가 `hazardLabel` 이다 (2026-09-20). 화면 알약과 공급처에 보낼
    #   문안이 같은 문자열을 써야 해서 뺐다 - 두 곳에 적으면 셀러가 보내는
    #   글과 화면이 갈린다 (§6). 검사는 **오너를 따라간다.**
    label = html[html.index("function hazardLabel("):]
    label = label[: label.index("\n  }")]
    assert "d.substance" in label and "d.limit_value" in label
    assert "statement_ko" not in label, "알약을 문장에서 뽑고 있다 (R5)"

    chip = html[html.index("function hazardChip("):]
    chip = chip[: chip.index("\n  }")]
    assert "hazardLabel(" in chip, "알약이 오너를 안 쓴다"
    assert "d.substance" not in chip, "값 읽기가 두 곳에 있다 (§6)"


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
    # 2026-09-12 부터 도구는 /scan 이다. "/" 는 소개다.
    assert 'href="/scan"' in pages["watch.html"]
    assert 'href="/watch"' in pages["index.html"]


def test_scan_page_shows_the_server_headline(pages):
    """셀러의 질문은 "이거 소싱해도 돼?" 다. 헤드라인이 거기에 직접 답한다.

    서버 문장을 그대로 써야 한다. 프론트가 다시 쓰면 GREEN 의 "판매자 제공
    정보 기준으로" 같은 §6.1 한계 문구가 조용히 사라진다.
    """
    index = pages["index.html"]
    assert "data.headline" in index
    # v2: 서버 문장을 " — " 에서 **자르기만** 한다. 문장은 안 바꾼다.
    assert 'String(head).split(" — ")' in index
    assert "esc(cut[0])" in index and 'esc(cut.slice(1).join(" — "))' in index


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

    # ⚠⚠ **업로드 자리만 본다.** 2026-09-13 에 파비콘
    #   `<link type="image/svg+xml">` 이 붙으면서 문서 전체 검색이 깨졌다 -
    #   파비콘은 우리가 서버로 보내는 것이 아니라 브라우저가 그리는 것이라
    #   업로드 허용 목록과 무관하다. **검사가 재려던 것은 업로드다.**
    upload = re.sub(r"<link\b[^>]*>", "", index)
    assert "image/svg" not in upload, (
        "업로드 자리에 SVG 가 허용돼 있다 - 서버가 거절해 사용자가 422 를 본다"
    )

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
    assert 'class="rv-gh ' in index
    assert "esc(g.header)" in index, "그룹 머리말을 서버에서 그려야 한다"
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
    # 데모 실행 본문. G-1 에서 인라인 → `runDemo` 이름 붙은 함수로 옮겼다
    # (버튼 클릭과 `/scan?demo=` 자동 실행이 같은 본문을 써야 해서). 검사는
    # 이름이 아니라 **본문**을 본다 - 클릭 핸들러가 그 함수를 가리키는지까지.
    start = index.index("function runDemo()")
    demo_body = index[start: index.index('b.addEventListener("click", runDemo)')]
    assert "shots = []" in demo_body
    assert "scan();" in demo_body


# ---------------------------------------------------------------------------
# "우리가 이렇게 읽었습니다" — 판정 위의 신뢰 (허점 1)
# ---------------------------------------------------------------------------


def test_extracted_is_rendered_above_every_finding(pages):
    """읽은 값은 **근거 줄 전부보다** 위에 둔다.

    우리가 잘못 읽었으면 셀러가 여기서 바로 알아채야 한다. 아래 줄들은 전부
    이 값을 입력으로 삼은 결과이므로, 입력을 보기 전에 결과부터 읽으면 잘못된
    입력 위의 결론을 믿게 된다.

    ⚠ **v2 에서 신호 머리가 위로 갔다.** 전에는 "읽은 값 → 판정" 이었고 이
      검사도 그렇게 적혀 있었다. 정본(design/result-card-v2.html)이
      "머리 → 읽은 값 → 축 → 근거" 로 정한다 - 머리는 신호 칩과 헤드라인
      둘뿐이고 근거는 전부 아래다. 그래서 기준을 "판정보다 위" 가 아니라
      **"근거 줄보다 위"** 로 옮겼다.
    """
    index = pages["index.html"]
    assert "이 페이지에서 이렇게 읽었습니다" in index
    body = index[index.index("function render(data)"):]
    read_at = body.index("readPills(data.extracted")
    assert read_at < body.index("rowsHtml(g.findings"), "읽은 값이 근거 줄보다 아래다"
    assert read_at < body.index('class="rv-axes"'), "읽은 값이 축보다 아래다"


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
    read = index[index.index("function readPills("):]
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
    block = block[: block.index("var meta = data.meta")]
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
    assert index.index("data.input_note") < index.index("readPills(data.extracted")


def test_axes_are_rendered_from_the_server_not_recomputed():
    """축 셋은 서버가 정한 상태를 그대로 그린다.

    프론트가 다시 판정하면 "우리가 한 행위이지 상품의 상태가 아니다" 라는
    §3.2 원칙이 조용히 무너진다 - grouped_findings·headline 을 서버가 내리는
    것과 같은 이유다.
    """
    html = (Path(__file__).resolve().parents[1] / "sourcing_guard" / "static"
            / "index.html").read_text(encoding="utf-8")
    assert "data.axes" in html
    # 프론트가 축 라벨을 자기가 만들면 안 된다.
    for banned in ("조회함", "대조함", "이 품목 미수록", "일치 있음"):
        assert banned not in html, f"프론트가 축 라벨 '{banned}' 을 직접 쓰고 있다"


def test_unknown_badge_agrees_with_the_subtitle():
    """배지가 "모름" 인데 부제목이 "일부만 확인" 이면 둘이 다른 말을 한다.

    우리는 인증·리콜을 실제로 조회했다. 안 한 것은 유해물질 수록뿐이다.
    """
    html = (Path(__file__).resolve().parents[1] / "sourcing_guard" / "static"
            / "index.html").read_text(encoding="utf-8")
    assert 'UNKNOWN:"일부 확인"' in html
    assert 'UNKNOWN:"모름"' not in html


def test_watch_cta_sits_right_after_the_findings():
    """감시 버튼이 확인 항목 바로 뒤에 온다.

    "모름" 화면에서 셀러에게 줄 수 있는 확정적 가치가 감시 하나뿐이다
    (기획서 §3.3). 맨 끝으로 밀리면 스크롤 밖으로 나가 없는 것과 같아진다.

    ⚠ **v2 에서 조건 분기가 없어졌다.** 전에는 유해물질 아코디언이 카드 맨
      아래에 있어서 "UNKNOWN 이면 그 위로 올린다" 로 피했고, 그래서 같은
      HTML 을 두 자리에서 그렸다(그리는 곳이 둘이면 id 가 겹칠 수 있다).
      접기가 근거 줄 안으로 들어가면서 아코디언이 사라졌으므로 **한 자리에서
      한 번** 그리면 된다.
    """
    html = (Path(__file__).resolve().parents[1] / "sourcing_guard" / "static"
            / "index.html").read_text(encoding="utf-8")
    body = html[html.index("function render(data)"):]
    assert html.count('id="cta"') == 1
    assert html.count('id="watch"') == 1
    assert body.index('class="watch-cta') > body.index("rowsHtml(g.findings")
    assert body.index('class="watch-cta') < body.index('class="rv-foot"')
    # UNKNOWN 도 GREEN 처럼 강조한다.
    assert 'sig === "GREEN" || sig === "UNKNOWN"' in html


# ---------------------------------------------------------------------------
# ②-e 메타 줄은 셀러가 읽는 줄이다 (2026-09-14)
# ---------------------------------------------------------------------------


def test_the_meta_footer_has_no_english_state_words():
    """`ok` 하나만 영어로 남아 있었다.

    `조회 실패` · `시도 안 함` 은 한국어인데 성공만 `ok` 였다 - 셀러는 그 줄에서
    "이게 뭔가" 로 멈춘다. 상태 낱말 셋이 같은 말로 읽혀야 비교가 된다.

    ⚠ 이름(변수 `LOOKUP`)이 아니라 **값**을 본다. 키는 서버가 주는 영어이고
      그것은 바뀌면 안 된다.
    """
    html = (Path(__file__).resolve().parents[1] / "sourcing_guard" / "static"
            / "index.html").read_text(encoding="utf-8")
    line = _lookup_block(html)
    values = re.findall(r':\s*"([^"]+)"', line)
    assert values, line
    for v in values:
        assert not re.fullmatch(r"[A-Za-z _-]+", v), f"메타 줄에 영어 리터럴: {v!r}"
    assert "성공" in values


def _lookup_block(html: str) -> str:
    """`var LOOKUP = {...};` 선언 전체.

    ⚠ 전에는 `var LOOKUP` 이 들어간 **한 줄**만 봤다. 2026-09-19 에 값이 넷이
      되며 선언이 두 줄로 나뉘자 뒤 줄의 `not_attempted` 를 통째로 놓쳤고,
      검사는 "키가 셋이다" 로 **성공한 것처럼** 깨졌다. 줄 수에 기대지 않는다.
    """
    m = re.search(r"var LOOKUP\s*=\s*\{(.+?)\};", html, re.S)
    assert m, "index.html 에서 LOOKUP 대응표를 못 찾았다"
    return m.group(1)


def test_the_lookup_keys_stay_as_the_server_sends_them():
    """값만 한국어로 바꾼다. 키를 번역하면 서버 응답과 못 맞춘다.

    ⚠⚠ 기대값을 **손으로 적지 않는다.** 서버가 낼 수 있는 상태값의 소유자는
      `scorer.GOV_LOOKUP_STATES` 하나다. 여기 목록을 따로 적어 두면 값을 늘릴
      때 한쪽만 고쳐지고, 화면은 `LOOKUP[x] || x` 라 **조용히 영어를 찍는다** -
      깨지지 않으므로 아무도 못 본다 (2026-09-19 에 `stale` 을 늘리며 실제로
      이 검사가 잡았다).
    """
    from sourcing_guard.scorer import GOV_LOOKUP_STATES

    html = (Path(__file__).resolve().parents[1] / "sourcing_guard" / "static"
            / "index.html").read_text(encoding="utf-8")
    keys = set(re.findall(r"(\w+):", _lookup_block(html)))
    assert keys == set(GOV_LOOKUP_STATES), (
        "화면 대응표와 서버 상태값이 어긋난다.\n"
        f"  화면에만: {keys - set(GOV_LOOKUP_STATES)}\n"
        f"  서버에만: {set(GOV_LOOKUP_STATES) - keys}"
    )


def test_the_scan_input_says_one_product_at_a_time():
    """[§1-j] 여러 상품을 한 번에 붙이면 **한 상품으로 합쳐진다.**

    ⚠⚠ **막는 것이 아니라 알리는 것이다.** 감지·차단 코드를 넣지 않았다 -
      오탐은 코드가 막을 때만 생기고, 문구는 아무것도 막지 않으므로 오탐이 없다.

    ⚠ 문구가 "섞입니다" 가 아닌 이유가 실측이다 (2026-09-18 · 10쌍 · gpt):
        상품명이 한쪽으로 쏠림 **8/10** · 품목은 **언제나 하나** · 밖의 번호 섞임 2/10
      8/10 은 섞인 것이 아니라 **다른 상품이 아예 검사되지 않은 것**이고,
      셀러에게 더 위험한 쪽이 그쪽이다 - "섞입니다" 를 읽으면 "갈라 읽으면
      되겠다" 고 생각하는데 **갈라 읽을 것이 없다.**

    ⚠ 둘째 줄(세트 상품)은 도매꾹 상세 317건 실측이 받친다 - safetyCert 항목
      2개 이상 13건(4.1% · 상한) · 실제 KC 2개 이상 2건(0.6%). 0 이 아니다.
    """
    scan = (STATIC / "index.html").read_text(encoding="utf-8")
    body = re.sub(r"<!--.*?-->", "", scan, flags=re.S)

    assert "한 상품씩 넣어 주세요" in body, "입력부에 '한 상품씩' 안내가 없다"
    assert "한쪽 기준으로만 결과가 나옵니다" in body, (
        "'한쪽 기준으로만' 이 빠졌다 - '섞입니다' 는 8/10 을 설명하지 않는다")
    assert "구성품이 여러 개인 한 상품은 그대로 넣으셔도 됩니다" in body, (
        "세트 상품 안내가 빠졌다 - 그 줄이 없으면 '한 상품씩' 이 세트 상품 "
        "셀러에게는 틀린 말로 읽힌다")

    # ⚠ **입력부다. 결과 카드가 아니다.** 결과에 붙이면 이미 합쳐진 다음이라 늦다.
    head = body[: body.index('<textarea id="pt"')]
    assert "한 상품씩 넣어 주세요" in head, "안내가 입력창 **뒤**에 있다"

    # ⚠ 막지 않는다 - 감지 코드가 들어오면 여기서 운다.
    for banned in ("여러 상품", "multi_product", "multiple_product"):
        assert banned not in scan.replace("여러 상품을 함께 붙이면", ""), (
            f"감지/차단 코드가 들어왔다: {banned}")


def test_the_batch_screen_does_not_carry_the_one_product_hint():
    """⚠ `/batch` 는 **한 줄에 한 상품**이 설계다. 거기 붙이면 틀린 말이 된다."""
    batch = (STATIC / "batch.html").read_text(encoding="utf-8")
    assert "한 상품씩 넣어 주세요" not in batch


def test_the_nav_wraps_on_phones_instead_of_pushing_the_page_sideways():
    """⚠⚠ **다섯째 항목이 들어오면서 폰에서 화면이 옆으로 밀렸다** (9/17~).

    실측 (2026-09-18 · Chromium · 배포본):

        390px   scrollWidth 539 / viewport 390   nav 515×40   ← 넘쳤다
        360px   scrollWidth 539 / viewport 360

    내비가 안 접혀서 `카테고리 가이드` 가 **화면 밖에 있었다** - [④ M-5] 로
    만든 화면이 폰에서 안 보였다. 만들어 놓고 못 닿게 둔 것이다.

    고친 뒤: 390/390 · 360/360 · nav 342×90 · 가이드 보임.

    ⚠⚠ **이 검사는 약하다.** 실제 브라우저를 안 띄우고 **CSS 규칙의 존재**만
      본다. 폭을 재는 것이 아니므로 "접히게 돼 있다" 까지만 말하고 "안 넘친다"
      를 말하지 못한다. 실제 폭은 손으로 잰다(위 수치).

    ⚠ **순서도 함께 잠근다.** `nav.pages` 선언이 이 파일에 **두 벌**이고
      (머리글 · 랜딩 v2) 뒤엣것이 `gap:28px` 를 다시 준다. 미디어쿼리가 그보다
      앞에 있으면 같은 명시도라 **나중 것이 이겨** 행 간격이 28px 이 되고
      머리글이 108px 로 두꺼워진다 - 2026-09-18 에 실제로 그렇게 됐다.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    m = re.search(r"@media \(max-width:640px\)\{\s*\n?\s*nav\.pages\{([^}]*)\}", css)
    assert m, "폰 폭에서 nav.pages 를 손보는 미디어쿼리가 없다"
    rule = m.group(1)
    assert "flex-wrap:wrap" in rule.replace(" ", ""), (
        "내비가 안 접힌다 - 다섯째 항목이 화면 밖으로 나가고 페이지가 옆으로 밀린다")
    assert re.search(r"gap:\s*\d+px\s+\d+px", rule), (
        "gap 을 한 값으로 주면 행 간격까지 그 값이 되어 머리글이 두꺼워진다 "
        "(실측: gap:28px 하나면 108px, 10px 18px 이면 90px)")

    # ⚠ 순서 - 마지막 `nav.pages{` 기본 선언보다 **뒤**여야 한다.
    last_base = max(mm.start() for mm in re.finditer(r"^nav\.pages\{", css, re.M))
    assert m.start() > last_base, (
        "미디어쿼리가 기본 nav.pages 선언보다 앞에 있다 - 같은 명시도라 "
        "나중 것이 이겨서 gap 이 안 먹는다")


# ── 마스코트 안심이 (2026-09-18 교체) ──────────────────────────
def test_the_sprite_ids_are_the_signal_values_themselves():
    """주의(가장 중요): **id 가 곧 신호다. 지도를 따로 적지 않는다.**

    전에는 `{GREEN:"calm", AMBER:"alert", RED:"worried", UNKNOWN:"unsure"}` 가
    `index.html` 과 `landing.html` **두 곳에** 적혀 있었고 잠그는 검사가 없었다.
    마스코트를 갈면서 symbol id 를 `Signal` 값 그대로 붙여 **적을 곳 자체를
    없앴다** - 같은 판단을 두 곳에 적지 않는 가장 싼 방법이다 (CLAUDE.md §6).
    """
    from sourcing_guard.models import Signal

    sprite = (STATIC / "mascot.svg").read_text(encoding="utf-8")
    ids = set(re.findall(r'<symbol id="([^"]+)"', sprite))
    want = {f"ansimi-{s.value}" for s in Signal} | {"ansimi-look"}
    assert ids == want, f"스프라이트에만 {sorted(ids - want)} · 빠진 것 {sorted(want - ids)}"


def test_no_face_map_survives_anywhere():
    """지도가 되살아나면 실패한다. **되돌리면 실패해야 하는 검사다.**"""
    for name in ("index.html", "landing.html", "watch.html", "batch.html", "guide.html"):
        src = (STATIC / name).read_text(encoding="utf-8")
        # 주석은 **왜 없앴는지**를 적고 있으므로 뺀다 (자기 걸림 방지).
        code = re.sub(r"<!--.*?-->|/\*.*?\*/", "", src, flags=re.S)
        code = "\n".join(ln for ln in code.splitlines()
                         if not ln.strip().startswith("//"))
        # 주의(중요): **값이 표정 이름인 지도**만 본다. `SIGNAL_LABEL` ·
        #   `SIGNAL_SHORT` 는 화면 문구 지도이고 있어야 한다 - 처음에
        #   `GREEN\s*:` 로만 걸었다가 그 둘을 잡았다. 이름이 아니라 **값**으로
        #   가린다.
        assert not re.search(
            r'GREEN\s*:\s*["\'](?:calm|alert|worried|unsure)', code), (
            f"{name}: Signal→표정 지도가 돌아왔다 - id 를 신호 이름으로 두면 필요 없다")
        for gone in ("mungchi", "kkureomi", "kongi"):
            assert gone not in code, f"{name}: 옛 마스코트 이름 {gone}"


def test_every_mascot_reference_points_at_an_id_that_exists():
    """끊어진 `<use>` 는 **조용히 빈 칸**이 된다. 화면이 안 깨진 것처럼 보인다."""
    sprite = (STATIC / "mascot.svg").read_text(encoding="utf-8")
    ids = set(re.findall(r'<symbol id="([^"]+)"', sprite))
    for name in ("index.html", "landing.html", "watch.html", "batch.html", "guide.html"):
        src = (STATIC / name).read_text(encoding="utf-8")
        for ref in re.findall(r'mascot\.svg#(ansimi-[A-Za-z]+)"', src):
            assert ref in ids, f"{name}: {ref} 가 스프라이트에 없다"


def test_the_sprite_carries_the_images_itself():
    """주의(중요): PNG 를 `static/` 에 뿌리면 **요청이 열 번** 간다.

    base64 로 품고 있어야 한다. SVG 원본이 오면 같은 id 로 이 파일만 갈아
    끼운다 - 호출부·검사 변경 0.
    """
    sprite = (STATIC / "mascot.svg").read_text(encoding="utf-8")
    assert sprite.count("data:image/png;base64,") == 5, "symbol 다섯이 그림을 품어야 한다"
    assert not list(STATIC.glob("ansimi-*.png")), "PNG 를 static/ 에 뿌렸다"

    fav = (STATIC / "favicon.svg").read_text(encoding="utf-8")
    assert "data:image/png;base64," in fav
    # 주의(중요): 20px 에서 전신을 쓰면 눈이 1px 이 된다. 파비콘은 **머리만**.
    assert 'viewBox="0 0 64 49"' in fav, "파비콘이 머리 비율이 아니다 - 전신을 넣었나"


# ── 접힌 유해물질 줄 (2026-09-20) ──────────────────────────────────
def test_only_the_hazard_fold_loses_its_signal_dot(html):
    """⚠⚠ **양쪽을 다 단정한다.** 이것이 이 검사의 값이다.

    `hazard_rule_applies` 의 `signal=UNKNOWN` 은 `verifier.py` 가 **축을 안
    흔들려고** 고른 값이다("이 finding 하나로 신호가 갈리면 규제 품목군이 전부
    AMBER 가 된다"). 화면에 내보이려고 고른 값이 아니므로 점을 뗀다.

    ⚠⚠ 그런데 **참고 정보 줄 열셋 전부에서 떼면 안 된다.** `kc_verified` 와
      `recall_clear` 는 방금 정부 DB 에서 **확인된 것**이고 초록 점을 달고
      있다. 떼면 확인된 줄이 나머지와 같아 보이고, 그건 R3 을 화면에서
      뒤집는 것이다 - 값이 있는 것을 없는 것으로 반올림한다.

      2026-09-20 에 실제로 "CONTEXT 줄의 점을 전부 뗀다" 는 지시가 나왔다가
      물렸다. 잰 것은 한 kind 인데 결론을 열세 kind 에 걸었던 것이다.
      **아래 두 번째 단정이 없으면 다음에 누가 "정리" 하며 같은 일을 해도
      아무것도 안 깨진다.**
    """
    fold = html[html.index("function hazardFold("):]
    fold = fold[: fold.index("\n  }")]
    assert "rv-dot" not in fold, "접힌 유해물질 줄에 신호 점이 있다"
    assert "rv-nosignal" in fold, "점 자리를 메우는 클래스가 없다 - 줄이 왼쪽으로 튄다"

    # ⚠ 반대 방향. 일반 근거 줄은 점을 **가지고 있어야** 한다.
    row = html[html.index("function findingRow("):]
    row = row[: row.index("\n  }")]
    assert "rv-dot" in row, (
        "일반 근거 줄에서 신호 점이 사라졌다 - kc_verified·recall_clear 는 "
        "확인된 줄이고 점이 그 사실을 말한다 (R3)")


def test_the_fold_label_has_one_owner(html):
    """⚠ 같은 문자열이 두 곳에 있었다 - 처음 그릴 때와 토글이 다시 접을 때.

    한 곳만 고치면 **한 번 접었다 펴는 순간** 옛 문구로 돌아간다 (§6).
    """
    assert "function foldLabel(" in html, "문구 오너가 없다"
    # 주석을 뺀 뒤 센다 - "이 문구를 두 곳에 적지 마라" 라고 적은 주석이
    # 그 검사에 걸린다 (오늘 두 번 걸린 자리다).
    code = re.sub(r"^\s*//.*$", " ", html, flags=re.M)
    assert code.count("적용되는 기준 ") == 1, (
        "문구가 두 곳에 적혀 있다 - foldLabel 하나만 두고 두 곳이 부른다")
    # 두 자리가 모두 오너를 부른다.
    assert "foldLabel(run.length)" in html, "최초 렌더가 오너를 안 쓴다"
    assert "foldLabel(box.children.length)" in html, "토글 핸들러가 오너를 안 쓴다"
    # ⚠ 여기도 주석을 뺀 것을 본다. 옛 문구를 **설명하는 주석**이 그 문구를
    #   인용하기 때문이다 - 오늘 이 함정에 세 번 걸렸다.
    assert "건 펼치기" not in code, "옛 문구가 코드에 남아 있다"


def test_the_hazard_fold_says_what_to_do_next(html):
    """"확인합니다" 로 끝나면 셀러가 무엇을 해야 하는지 없다.

    ⚠ 이 줄은 우리가 못 본 것이 아니라 **상세페이지로는 알 수 없는 것**이다.
      둘을 가려 적는다 (R3 · §9).
    """
    fold = html[html.index("function hazardFold("):]
    fold = fold[: fold.index("\n  }")]
    assert "상세페이지로 알 수 없습니다" in fold
    assert "공급처에 시험성적서를 요청하세요" in fold


# ── 공급처에 보낼 문안 (2026-09-20) ────────────────────────────────
def _ask_src(html: str) -> str:
    body = html[html.index("function askText("):]
    return body[: body.index("\n  function stamp(")]


def test_the_supplier_message_quotes_the_server_and_writes_nothing_new(html):
    """⚠⚠ **여기서 문장을 만들지 않는다.**

    이 글은 **공급처에게 나간다.** 셀러가 자기 주장으로 보내는 글에 우리가
    지어낸 문장이 섞이면 화면에서보다 비싸다 (R5). 그래서 줄마다 서버가 낸
    `statement_ko` 를 그대로 인용하고 `source_url` 을 붙인다.

    ⚠ 서류 목록도 우리가 짜지 않는다. "안전확인신고증" 은 완구에는 맞지만
      공급자적합성확인 품목에는 **틀린 서류**다. finding 들이 이미 무엇을
      요청해야 하는지 말하고 있다.
    """
    src = _ask_src(html)
    assert "f.statement_ko" in src, "서버 문장을 인용하지 않는다"
    assert "f.source_url" in src, "근거 링크를 안 붙인다 (R2)"
    assert "data.disclaimer" in src, "§9 고정 문구를 서버에서 받지 않는다"
    # 서류 이름을 우리가 적지 않는다.
    for invented in ("신고증", "성적서 사본", "수입신고필증", "시험성적서를 첨부"):
        assert invented not in src, f"서류 목록을 우리가 짜고 있다: {invented}"


def test_the_supplier_message_folds_like_the_screen(html):
    """클립보드에 들어가는 것은 화면에 보이는 것과 같다.

    ⚠ 딱 한 군데만 다르다 - 유해물질은 알약 넷 + "+10" 이 아니라 **전부**
      적는다. "+10" 은 메시지에서 쓸모가 없다.
    """
    src = _ask_src(html)
    assert "FOLD_AT" in src, "접기 문턱이 화면과 다른 값을 쓴다"
    assert "FOLD_CHIPS" not in src, "메시지가 알약을 넷으로 자르고 있다"
    assert "hazardLabel(" in src or "hazardLabel(" in html[html.index("function askHazard("):], (
        "물질 문자열이 화면과 다른 오너에서 온다")


def test_the_supplier_message_never_misattributes_a_legal_basis(html):
    """⚠⚠ **근거로 묶는다.** `isHazard` 는 kind 로만 묶으므로 한 덩어리 안에
    근거가 섞인다 - 검수 완료 21건이 공통안전기준 17 · 안전확인 부속서 2 ·
    공급자적합성 부속서 2 다.

    화면은 펼치면 줄마다 제 근거를 들어 R2 가 지켜지지만, 이 글은 공급처에게
    나간다. `source_url` 로 계열을 나누고 그 안에서 `legal_basis` 로 조항을
    나눈다 - 물질이 제 조항에만 붙는다.
    """
    src = html[html.index("function askHazard("):]
    src = src[: src.index("\n  // 검사한 시각")]
    assert "source_url" in src, "계열(문서)로 안 나눈다"
    assert "legal_basis" in src, "조항으로 안 나눈다"


def test_the_supplier_message_block_sits_below_the_watch_cta(html):
    """⚠ 감시 CTA 가 밀려 내려가면 안 된다.

    UNKNOWN 에서 우리가 주는 **유일한 확정적 가치**가 그 버튼이다.
    """
    assert html.index('id="cta"') < html.index('class="rv-ask"'), (
        "문안 블록이 감시 CTA 위에 있다 - CTA 가 접힘 아래로 밀린다")


def test_the_copy_fallback_needs_no_browser_api(html):
    """⚠ 실패하면 **텍스트를 그냥 펼친다.** 우리가 선택을 대신 잡아 주지 않는다.

    선택을 잡아 주려 하면 브라우저마다 되는지 재야 하고, 우리는 그것을 안
    쟀다. 펼쳐서 보여 주면 API 가 0개라 잴 것이 없다 - 재지 않아도 되는
    설계를 고른다 (§8).
    """
    block = html[html.index("var askBtn = document.getElementById"):]
    block = block[: block.index("\n    // 접힌 유해물질")]
    assert "pre.hidden = false" in block, "실패해도 텍스트를 안 보여 준다"
    for api in ("getSelection", "createRange", "execCommand", "select()"):
        assert api not in block, f"선택을 대신 잡고 있다: {api}"


def test_the_source_bundle_is_derived_not_written(html):
    """⚠⚠ **목록을 손으로 짜지 않는다.**

    근거가 늘 때 이 묶음만 낡으면 "정부 원문으로 확인합니다" 라고 적힌 자리가
    거짓이 된다. finding 의 `source_url` 에서 중복만 지운다.
    """
    block = html[html.index("var seen = {};"):]
    block = block[: block.index("// ⑥ 메타 푸터")]
    assert "f.source_url" in block, "묶음이 응답에서 나오지 않는다"
    assert "seen[f.source_url]" in block, "중복을 안 지운다"
    # 링크를 하드코딩하지 않는다.
    assert "https://" not in block and "http://" not in block, (
        "묶음에 URL 이 박혀 있다 - 서버가 준 것만 쓴다")


def test_the_source_bundle_does_not_replace_per_row_links(html):
    """⚠ 요약이지 **대체가 아니다.** 줄마다 붙은 개별 링크는 그대로 둔다 (R2).

    그 줄이 어느 근거에서 왔는지는 그 자리에 있어야 한다. 묶음만 남기면
    셀러가 "이 문장의 근거" 를 찾으려면 아래까지 내려가 추측해야 한다.
    """
    row = html[html.index("function findingRow("):]
    row = row[: row.index("\n  }")]
    assert "srcLink(" in row or "source_url" in row, (
        "근거 링크가 줄에서 사라졌다 - 묶음이 대체가 됐다")
