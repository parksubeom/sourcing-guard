"""[G-1] 랜딩 `/` 와 도구 `/scan` 의 분리 — 구조만. 디자인은 시피님이 새로 한다.

설계 문서 `docs/랜딩페이지_설계.md` §1·§2·§3·§4 를 잠근다.

⚠⚠ 설계 §4 가 "화면 중복 검사(24자)에 걸린다" 고 적어 뒀는데 **그 검사는 존재하지
  않았다.** 문서가 코드보다 앞선 네 번째 사례다(§6). 여기서 실제로 만든다 -
  보이는 텍스트를 24자 창으로 밀어 두 화면이 같은 문장을 반복하지 않는지 본다.
  같은 안내문이 두 화면에 있으면 투표자는 스크롤을 두 번 읽고, 심사위원은 한
  화면이 다른 화면의 복사본이라고 읽는다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "sourcing_guard" / "static"
_LANDING = (_STATIC / "landing.html").read_text(encoding="utf-8")
_SCAN = (_STATIC / "index.html").read_text(encoding="utf-8")


def _visible(html: str) -> str:
    """스크립트·주석·헤더(네비)·태그를 빼고 **본문 카피**만. 공백은 하나로.

    ⚠ 헤더/네비는 모든 페이지가 공유하는 크롬이라 뺀다. 처음엔 안 뺐다가
      "소개 상품 검사 대량 검사 감시 목록" 이 24자 겹침으로 잡혔다 - 그건
      중복이 아니라 일관성이다. 이 검사가 보려는 것은 **설명 문장의 반복**이다.
    """
    s = re.sub(r"<script\b[\s\S]*?</script>", " ", html, flags=re.I)
    s = re.sub(r"<header\b[\s\S]*?</header>", " ", s, flags=re.I)
    s = re.sub(r"<nav\b[\s\S]*?</nav>", " ", s, flags=re.I)
    s = re.sub(r"<!--[\s\S]*?-->", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(s.split())


# ── 라우트 (설계 §1) ───────────────────────────────────────────────
def test_root_is_the_landing_and_scan_is_the_tool():
    from sourcing_guard.main import app

    with TestClient(app) as c:
        root = c.get("/").text
        scan = c.get("/scan").text
    assert "내 상품으로 해보기" in root and 'id="pt"' not in root
    assert 'id="pt"' in scan and "내 상품으로 해보기" not in scan


def test_every_page_links_the_tool_at_scan_not_root():
    """`/` 가 도구에서 소개로 바뀌었다. 옛 링크가 남으면 소개로 튄다."""
    for name in ("index.html", "batch.html", "watch.html", "landing.html"):
        src = (_STATIC / name).read_text(encoding="utf-8")
        assert 'href="/scan"' in src, f"{name} 에 /scan 링크가 없다"
        # "/" 는 소개 링크로만 남는다 - 도구 문구를 달고 있으면 옛 링크다.
        for m in re.finditer(r'<a href="/"[^>]*>([^<]*)</a>', src):
            assert "검사" not in m.group(1), f'{name}: href="/" 가 아직 도구를 가리키는 문구다: {m.group(1)!r}'


# ── 24자 중복 검사 (설계 §4 · 이 검사는 여기서 처음 생겼다) ────────
_SHARED_BY_DESIGN = (
    "본 결과는 공개된 정부 데이터에 기반한 참고 정보이며, 법적 판단이나 안전 인증을 대체하지 않습니다.",
    "출처 · 국가기술표준원 제품안전정보센터 공개 API, 어린이제품 공통안전기준(산업통상자원부고시 제2022-220호)",
    "안심 소싱 돋보기",
    "이 상품, 팔아도 되는지 확인합니다",   # 히어로 제목 - 설계 §2 가 두 화면 같게 뒀다
)


def test_landing_and_scan_do_not_repeat_the_same_sentences():
    a, b = _visible(_LANDING), _visible(_SCAN)
    for shared in _SHARED_BY_DESIGN:
        a = a.replace(shared, " "); b = b.replace(shared, " ")
    a = " ".join(a.split()); b = " ".join(b.split())
    dup = sorted({a[i:i + 24] for i in range(len(a) - 23) if a[i:i + 24] in b})
    assert not dup, "랜딩과 /scan 이 같은 문장을 반복합니다 (24자 창):\n  " + "\n  ".join(dup[:8])


# ── 데모 버튼 (설계 §2) ────────────────────────────────────────────
def test_landing_demo_buttons_come_from_the_server_and_go_to_scan():
    from sourcing_guard.demos import DEMO_TEXTS

    assert "/api/v1/demos" in _LANDING
    assert "/scan?demo=" in _LANDING
    for text in DEMO_TEXTS:
        assert text not in _LANDING, "데모 문구가 랜딩에 하드코딩됐다"


def test_scan_runs_the_demo_from_the_query_and_labels_it():
    """투표자 클릭 1번에 결과 - `/scan?demo=<tone>` 을 읽어 자동 검사한다."""
    assert 'get("demo")' in _SCAN and "URLSearchParams" in _SCAN
    assert 'id="demo-note"' in _SCAN                 # "이 예시는 …" 한 줄
    assert "예시 문구를 검사한 것" in _SCAN
    # 사용자가 입력란을 손대면 예시 표시는 사라져야 한다.
    assert re.search(r'\$\("demo-note"\)\.hidden\s*=\s*true', _SCAN)


# ── 4절 숫자 - 정본과 대조 (설계 §3-④ · test_docs 와 같은 방식) ───
def test_the_figures_match_the_baseline():
    sys.path.insert(0, str(_ROOT / "scripts"))
    from audit_tally import BASELINE, BASELINE_EXTRACTOR

    b = BASELINE[BASELINE_EXTRACTOR]
    v = _visible(_LANDING)
    ok_pct = f"{b['ok'] / b['denominator'] * 100:.1f}%"
    up_pct = f"{b['ok_upper'] / b['denominator'] * 100:.1f}%"
    assert f"{b['ok']}건 ({ok_pct})" in v, f"검수 완료 정답이 기준선 {b['ok']} ({ok_pct}) 와 다르다"
    assert f"{b['ok_upper']}건 ({up_pct})" in v
    assert f"{b['unreviewed']}건을 모두 정답으로 가정" in v
    assert f"비대상 53건 중 {b['off_target']}건" in v
    assert f"애매 47건 중 {b['on_vague']}건" in v
    # 기준 추출기를 밝힌다 - 어느 추출기 숫자인지 없는 숫자는 라벨 없는 숫자다.
    assert "기준 추출기 GPT" in v
    # 검수 전 값은 발표 숫자가 아님을 같은 문단에서 말한다.
    assert "검수 전 값이라 발표 숫자로 쓰지 않습니다" in v


# ── 5절 - 하드코딩 금지, /healthz 에서 그린다 (설계 §3-⑤) ─────────
def test_data_figures_are_not_hardcoded():
    v = _visible(_LANDING)
    for stale in ("4,244", "4,245", "33,085", "33,105", "verified 21", "draft 55"):
        assert stale not in v, f"5절 숫자가 하드코딩됐다: {stale}"
    assert 'fetch("/healthz")' in _LANDING
    for key in ("domestic", "overseas", "as_of", "active", "draft", "gpt", "claude", "commit"):
        assert f'data-h="{key}"' in _LANDING, key
    # 값이 안 오면 "-" 로 남는다 - 지어내지 않는다.
    assert '"-"' in _LANDING


# ── 2절 - 무엇을 안 하나 (설계 §3-②) ─────────────────────────────
def test_the_landing_says_what_it_does_not_do():
    v = _visible(_LANDING)
    assert "판정하지 않습니다" in v
    assert "초록불은 보증이 아닙니다" in v
    assert "원문 링크" in v                          # R2 를 말한다
    for banned in ("안전합니다", "합법입니다", "판매 가능합니다", "문제없습니다", "걸리지 않습니다."):
        assert banned not in v, banned


# ── 디자인 무관 (G-1 조건) ────────────────────────────────────────
def test_landing_has_no_logo_color_or_favicon_and_an_empty_mark():
    assert "<style" not in _LANDING
    assert 'rel="icon"' not in _LANDING
    for f in ("mark.svg", "logo.svg", "favicon.svg"):
        assert f not in _LANDING, f"{f} 를 참조한다 - 디자인은 시피님이 새로 한다"
    assert re.search(r'<span class="mark" aria-hidden="true"></span>', _LANDING), "마크 자리는 빈 span 이어야 한다"
    assert '<svg class="mark"' not in _LANDING
    # 인라인 색상 지정이 없다 - app.css 토큰만.
    assert not re.search(r'style="[^"]*(color|background)', _LANDING)
    assert "/static/app.css" in _LANDING
