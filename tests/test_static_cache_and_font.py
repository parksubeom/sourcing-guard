"""정적 자산 캐시 무효화와 본문 글꼴 ([디자인 v2] ⓶ · 2026-09-13).

⚠⚠ **왜 긴급인가.** 배포본 7185d2b 의 `/static/app.css` 에 버전 쿼리가 없었다.
  브라우저가 옛 CSS 를 들고 있으면 **디자인을 고쳐 배포해도 셀러 화면은
  그대로**다. 투표 기간에 그러면 고친 줄도 모르고 지나간다.

⚠ 글꼴은 잰 결함이다 (design/README §10-1). `body{font-family}` 가 공공 디자인
  시스템 폰트를 맨 앞에 두고 `Noto Sans KR` 을 맨 뒤에 둬서, **웹폰트를 받아
  놓고 안 썼다** - 맥은 Apple SD Gothic Neo, 윈도우는 맑은 고딕으로 그려졌다.

⚠ `TestClient` 를 `with` 로 열지 않는다. lifespan 이 돌면 동기화 루프가 실
  네트워크로 나간다(conftest 가 막는다). 여기서는 GET 만 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from sourcing_guard.build_info import snapshot as build_snapshot
from sourcing_guard.main import app

_PAGES = ("/", "/scan", "/batch", "/watch")
_STATIC_DIR = Path("sourcing_guard/static")
_SRC_FILES = ("app.css", "landing.html", "index.html", "batch.html", "watch.html",
              "owner.js")


def _html(client: TestClient, path: str) -> str:
    r = client.get(path)
    assert r.status_code == 200, (path, r.status_code)
    return r.text


#: 따옴표로 열리는 `/static/…` 전부. **여는 따옴표만 본다** - `index.html` 의
#: 결과 카드는 JS 문자열 안에서 `"` 로 열고 `'` 로 닫는다(표정을 이어 붙인다).
#: 짝을 요구하면 그 한 자산을 못 보고 지나간다 - 실제로 그랬다.
_REF = re.compile(r"""(?<=["'])/static/[^"'\s]*""")


def _refs(html: str) -> list[str]:
    return _REF.findall(html)


def test_every_static_reference_on_every_page_carries_the_build_version():
    """네 화면 전부. 한 곳만 빼먹으면 그 자산만 옛 것이 남는다."""
    commit = build_snapshot()["commit"]
    assert commit, "커밋을 모르면 이 검사가 아무것도 못 잡는다 (로컬은 git 에서 읽는다)"
    client = TestClient(app)
    for page in _PAGES:
        html = _html(client, page)
        refs = _refs(html)
        assert refs, f"{page}: 정적 참조가 0개 - 검사가 아무것도 안 보고 있다"
        for ref in refs:
            assert f"?v={commit}" in ref, f"{page}: 버전 없는 참조 {ref!r}"


def test_the_version_query_comes_before_the_fragment():
    """⚠ `/static/mascot.svg#x?v=1` 이면 조각 이름이 `x?v=1` 이 되어 **아이콘이
    사라진다.** 마스코트 참조는 전부 조각을 쓴다."""
    commit = build_snapshot()["commit"]
    client = TestClient(app)
    refs = [r for r in _refs(_html(client, "/watch")) if "mascot.svg" in r]
    assert refs, "마스코트 참조가 없다 - 검사가 아무것도 안 보고 있다"
    for ref in refs:
        assert re.match(rf"/static/mascot\.svg\?v={re.escape(commit)}#", ref), ref


def test_the_page_version_matches_healthz():
    """화면이 박은 버전과 `/healthz.build.commit` 이 같아야 한다.

    다르면 "배포본이 무엇인가" 를 또 역추적하게 된다 (build_info 머리주석).
    """
    client = TestClient(app)
    commit = client.get("/healthz").json()["build"]["commit"]
    assert f"/static/app.css?v={commit}" in _html(client, "/")


def test_html_is_not_cached_and_versioned_static_is_cached_forever():
    """HTML 이 캐시되면 그 안의 버전 쿼리도 옛 것이라 무효화가 한 바퀴 늦는다."""
    commit = build_snapshot()["commit"]
    client = TestClient(app)
    for page in _PAGES:
        assert client.get(page).headers["cache-control"] == "no-cache", page
    r = client.get(f"/static/app.css?v={commit}")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_static_without_a_version_is_not_cached_forever():
    """⚠ 반대 방향. 버전 없는 요청을 1년 캐시하면 되돌릴 방법이 없다.

    이 프로젝트에서 반복된 결함이 **가드가 걱정한 방향은 막혀 있고 안 적은
    반대 방향이 뚫려 있는 것**이라, 양쪽을 다 잰다 (CLAUDE.md §6).
    """
    client = TestClient(app)
    assert client.get("/static/app.css").headers["cache-control"] == "no-cache"


def test_the_body_font_is_the_token_and_the_gov_design_font_is_gone():
    """정부 디자인 시스템 폰트는 쓰지 않는다 — app.css 머리주석 원칙."""
    css = (_STATIC_DIR / "app.css").read_text(encoding="utf-8")
    body = re.search(r"\nbody\{(.*?)\n\}", css, re.S)
    assert body, "body 규칙을 못 찾았다"
    decls = re.sub(r"/\*.*?\*/", "", body.group(1), flags=re.S)
    assert "font-family:var(--font-body)" in decls.replace(" ", ""), decls

    # 주석 안 언급까지 잡으면 근거 기록을 지우게 된다 - 코드에서만 센다.
    for name in _SRC_FILES:
        text = (_STATIC_DIR / name).read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/|<!--.*?-->", "", text, flags=re.S)
        assert "Pretendard" not in code, f"{name} 에 공공 디자인 시스템 폰트가 남아 있다"


def test_the_body_font_token_actually_leads_with_the_webfont_we_download():
    """토큰이 가리키는 첫 글꼴이 `<link>` 로 받는 것과 같아야 한다.

    ⚠ 이것이 잰 결함의 본체였다 - "받아 놓고 안 쓰는" 상태는 토큰을 쓰기만
      해서는 다시 생길 수 있다. 토큰 **안쪽**까지 본다.
    """
    css = (_STATIC_DIR / "app.css").read_text(encoding="utf-8")
    token = re.search(r"--font-body:\s*([^;]+);", css)
    assert token, "--font-body 토큰이 없다"
    assert token.group(1).strip().startswith('"Noto Sans KR"'), token.group(1)
    for name in ("landing.html", "index.html", "batch.html", "watch.html"):
        html = (_STATIC_DIR / name).read_text(encoding="utf-8")
        assert "family=Noto+Sans+KR" in html, f"{name} 이 그 글꼴을 받지 않는다"
