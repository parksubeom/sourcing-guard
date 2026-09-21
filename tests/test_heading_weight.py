"""제목 굵기의 **소유자가 하나**인가 — 명시도가 같으면 뒤가 이긴다.

왜 있나
-------
2026-09-20 배포본 실측:

    /scan  `.intro h2`     computed **400**   (240줄은 700 을 적고 있었다)
    /      `.hero-say h1`  computed 700

`h1, h2, .wordmark, .intro h2{font-weight:400}` 이 591줄에 있었고, 240줄의
`.intro h2{font-weight:700}` 과 **명시도가 같았다**(둘 다 0-1-1). 같으면 뒤가
이긴다. 그래서 같은 제품의 히어로가 한쪽은 굵고 한쪽은 얇았다.

⚠⚠ **소스 문자열만 보는 검사 1,800개가 전부 못 잡았다.** `font-weight:700`
  이 파일에 **있었기** 때문이다 - 있다는 것과 이긴다는 것은 다르다.

⚠ computed 값 자체는 브라우저가 있어야 재고, `tests/` 는 네트워크·브라우저에
  기대지 않는다(CLAUDE.md §7). 그래서 여기서는 **구조**를 본다 - "그 요소에
  굵기를 정하는 규칙이 몇 개인가". 실제 화면 값은
  `scripts/measure_weights.py` 가 브라우저로 잰다.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.srccheck import markup_only

_CSS = (Path(__file__).resolve().parents[1]
        / "sourcing_guard" / "static" / "app.css").read_text(encoding="utf-8")

#: 굵기를 정하는 소유자가 **하나여야 하는** 제목들.
#: (요소 이름, 그 요소에 붙는 선택자 조각)
_HEADINGS = {
    "/scan 히어로 제목": (".intro", "h2"),
    "랜딩 히어로 제목": (".hero-say", "h1"),
}


def _rules(css: str):
    """`@media` 안까지 포함해 (선택자, 선언) 쌍을 뽑는다.

    ⚠ 주석 제거는 **여기서 새로 쓰지 않는다.** 오너는 `tests/srccheck.py` 의
      `markup_only` 다 - 파일마다 정규식을 따로 들면 그 규칙 자체가 여러 벌이
      된다 (CLAUDE.md §6). `test_srccheck` 가 그것을 잡는다.
    """
    body = markup_only(css)
    for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", body):
        sel, decl = m.group(1).strip(), m.group(2)
        if sel and not sel.startswith("@"):
            yield sel, decl


def _applies(sel_part: str, cls: str, tag: str) -> bool:
    """이 선택자 조각이 `<tag class=cls-조상>` 에 붙을 수 있는가 (거칠게)."""
    s = sel_part.strip()
    if not s or s.startswith(("@", "%", "from", "to")):
        return False
    last = s.split()[-1].split(">")[-1].strip()
    # 의사요소·의사클래스가 붙은 것은 다른 상태라 여기서 세지 않는다.
    if "::" in last or ":hover" in s or ":focus" in s or ":not(" in s:
        return False
    if last == tag:
        return True
    if last == f"{cls} {tag}".split()[-1] and cls in s:
        return True
    return last.startswith(tag) and last[len(tag):].startswith((".", "#")) is False \
        and last == tag


def test_each_hero_heading_has_exactly_one_weight_owner():
    """⚠⚠ **굵기를 적는 규칙이 둘이면, 파일에 적힌 값이 화면 값이 아니다.**

    이 검사가 세는 것은 "700 이 적혀 있는가" 가 아니라 **"굵기를 적는 규칙이
    몇 개인가"** 다. 전자는 통과하면서 화면이 400 일 수 있다.
    """
    for name, (cls, tag) in _HEADINGS.items():
        owners = []
        for sel, decl in _rules(_CSS):
            if "font-weight" not in decl:
                continue
            for part in sel.split(","):
                p = part.strip()
                # 그 요소에 실제로 붙는 선택자만 센다.
                if p == tag or p == f"{cls} {tag}" or p.endswith(f"{cls} {tag}"):
                    owners.append(f"{p} {{{decl.strip()[:40]}}}")
                    break
        assert len(owners) == 1, (
            f"{name}: 굵기를 정하는 규칙이 {len(owners)}개다 - 뒤가 이긴다\n  "
            + "\n  ".join(owners))


def test_the_shared_display_rule_sets_no_weight():
    """공용 `h1, h2, .wordmark` 규칙은 **서체만** 준다.

    ⚠ 굵기를 여기 적으면 개별 제목 규칙과 명시도가 같아져(0-0-1 vs 0-1-1
      처럼 보이지만 `h2` 단독은 0-0-1 이고 `.intro h2` 는 0-1-1) 선택자에
      클래스가 섞이는 순간 덫이 된다 - 실제로 `.intro h2` 가 섞여 있었다.
    """
    # ⚠⚠ **선택자 글자 모양이 아니라 조각으로 본다** (2026-09-21).
    #   전에는 `"," in sel` 로 걸렀는데, 히어로 규칙이 `.intro h1, .intro h2` 로
    #   합쳐지자(프로덕션 · h1 합류) 그것까지 "공용" 으로 잡았다. 덫이 되는 것은
    #   **맨 `h1`·`h2`**(0-0-1)가 굵기를 적는 경우이지 `.intro h2`(0-1-1)가
    #   아니다 - 후자는 소유자다.
    hit = []
    for sel, decl in _rules(_CSS):
        if "font-weight" not in decl:
            continue
        for part in sel.split(","):
            if part.strip() in ("h1", "h2"):
                hit.append((sel.strip(), decl.strip()[:60]))
                break
    assert not hit, f"맨 h1·h2 가 굵기를 정한다 - 개별 규칙과 덫이 된다: {hit}"

    shared = [sel for sel, decl in _rules(_CSS)
              if "font-family:var(--font-display)" in decl.replace(" ", "")
              and sel.strip().startswith("h1,")]
    assert shared, "공용 제목 규칙을 못 찾았다"
    for sel in shared:
        assert ".intro" not in sel, (
            f"공용 규칙 선택자에 `.intro` 가 남아 있다 ({sel}) - 개별 규칙과 "
            "명시도가 같아져 덫이 된다")


def test_the_two_heroes_ask_for_the_same_weight():
    """같은 제품의 히어로가 갈리면 안 된다 - 한쪽만 굵었던 것이 이 건이다."""
    # ⚠ 선택자가 `.intro h1, .intro h2` 로 합쳐질 수 있으므로 **조각으로** 찾는다.
    want = {}
    for name, (cls, tag) in _HEADINGS.items():
        for sel, decl in _rules(_CSS):
            if "font-weight" not in decl:
                continue
            if any(part.strip() == f"{cls} {tag}" for part in sel.split(",")):
                want[name] = re.search(r"font-weight:\s*(\d+)", decl).group(1)
    assert len(want) == 2, f"제목 규칙을 못 찾았다: {want}"
    assert len(set(want.values())) == 1, f"두 히어로의 굵기가 다르다: {want}"


# ── 여기부터는 **브라우저가 실제로 계산한 값**을 본다 ──────────────────────
#
# ⚠⚠ 위 검사들은 **구조**를 본다 - "굵기를 정하는 규칙이 몇 개인가". 그것만으로는
#   부족하다. 이번 건의 교훈이 정확히 "파일에 700 이 있는 것과 화면이 700 인
#   것은 다르다" 이고, CLAUDE.md §6 이 이미 이름 붙여 뒀다 - "주입으로 잰 CSS
#   값을 「검증했다」고 말했다" · "화면 검사는 틀이 아니라 틀에 붓는 값을 본다".
#
# ⚠ 그래서 페이지를 **띄워서** `getComputedStyle` 을 읽는다. 외부로는 나가지
#   않는다 - 정적 파일만 로컬에서 내고, 127.0.0.1 밖 요청은 전부 끊는다.
#   웹폰트가 없어도 `font-weight` 의 computed 값은 안 바뀐다(선언된 수 그대로).
#
# ⚠ 브라우저가 없으면 **skip 된다.** skip 은 통과가 아니지만, 그래도 "아무도
#   안 보는 상태" 가 될 수 있다 - 그 자리를 위 구조 검사들이 항상 메운다.

import functools
import http.server
import socketserver
import threading

import pytest

_STATIC_ROOT = Path(__file__).resolve().parents[1] / "sourcing_guard"

#: 화면 여덟 장 전부. 히어로 제목이 있는 넷은 선택자를 같이 적는다.
#: `None` 은 "이 화면에는 히어로 규칙이 없다" 로, 굵기 동일성 판정에서 뺀다.
_SCREENS = {
    "/static/landing.html": ".hero-say h1",
    "/static/index.html": ".intro h2",
    "/static/batch.html": ".intro h2",
    "/static/watch.html": ".intro h2",
    "/static/guide.html": None,
    "/static/samples.html": None,
    "/static/misses.html": None,
    "/static/unknown.html": None,
}


@pytest.fixture(scope="module")
def static_site():
    """정적 파일만 내는 로컬 서버. 앱을 띄우지 않는다(라이프사이클·API 불필요)."""
    class _Quiet(http.server.SimpleHTTPRequestHandler):
        # ⚠ `functools.partial` 에 속성을 달면 클래스가 아니라 partial 객체에
        #   붙어 아무 일도 안 한다 - 실제로 그렇게 짰다가 로그가 그대로 나왔다.
        def log_message(self, *a, **k):
            pass

    handler = functools.partial(_Quiet, directory=str(_STATIC_ROOT))
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture(scope="module")
def browser():
    pw_api = pytest.importorskip(
        "playwright.sync_api",
        reason="playwright 가 없다 - `pip install playwright && playwright install chromium`")
    with pw_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:  # 브라우저 바이너리가 없을 때
            pytest.skip(f"chromium 을 못 띄운다: {exc}")
        try:
            yield b
        finally:
            b.close()


_READ_HEADINGS = """(heroSel) => {
  const out = {heads: [], hero: null};
  document.querySelectorAll('h1, h2, .wordmark').forEach(el => {
    out.heads.push({tag: el.tagName.toLowerCase(),
                    weight: getComputedStyle(el).fontWeight});
  });
  if (heroSel) {
    const h = document.querySelector(heroSel);
    if (h) {
      const cs = getComputedStyle(h);
      out.hero = {weight: cs.fontWeight, size: cs.fontSize};
    }
  }
  return out;
}"""


def _visit(browser, base, path, hero_sel):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    # 바깥으로 나가지 않는다. 웹폰트(Google Fonts · jsDelivr)도 여기서 끊긴다.
    page.route("**/*", lambda route: (route.continue_() if route.request.url.startswith(base)
                                      else route.abort()))
    page.goto(base + path, wait_until="domcontentloaded", timeout=30_000)
    got = page.evaluate(_READ_HEADINGS, hero_sel)
    return page, got


def _declared(sel: str) -> str:
    """app.css 가 그 선택자에 **적어 둔** 굵기. 기대값을 손으로 적지 않는다."""
    # ⚠ 선택자가 `.intro h1, .intro h2` 로 합쳐질 수 있다 (프로덕션 · h1 합류
    #   2026-09-21). **조각으로** 찾는다 - 글자 모양에 기대면 합치는 순간 깨진다.
    for rule_sel, decl in _rules(_CSS):
        if "font-weight" not in decl:
            continue
        if any(part.strip() == sel for part in rule_sel.split(",")):
            return re.search(r"font-weight:\s*(\d+)", decl).group(1)
    raise AssertionError(f"`{sel}` 의 font-weight 선언을 app.css 에서 못 찾았다")


def test_computed_hero_weight_matches_what_the_source_says(static_site, browser):
    """⚠⚠ **화면이 계산한 굵기 == 소스가 적어 둔 굵기.**

    기대값을 숫자로 박지 않는다 - app.css 에서 끌어온다(§6 "기대값은 코드에서
    끌어낸다"). 그래야 C안을 800 으로 바꿔도 이 검사가 따라온다.

    ⚠ 본 화면 수를 같이 단정한다. 0장을 보고 통과하면 검사가 아니다 (§6).
    """
    seen: dict[str, dict] = {}
    empty: list[str] = []
    for path, hero_sel in _SCREENS.items():
        page, got = _visit(browser, static_site, path, hero_sel)
        page.close()
        if not got["heads"]:
            empty.append(path)
        seen[path] = got

    assert len(seen) == len(_SCREENS) == 8, f"본 화면 {len(seen)}장"
    assert not empty, f"제목을 하나도 못 읽은 화면: {empty}"

    heroes = {p: g["hero"] for p, g in seen.items() if _SCREENS[p]}
    assert len(heroes) == 4, f"히어로 제목을 잰 화면 {len(heroes)}장 - 넷이어야 한다"
    assert all(h for h in heroes.values()), f"히어로 선택자가 안 잡힌 화면: {heroes}"

    for path, hero in heroes.items():
        want = _declared(_SCREENS[path])
        assert hero["weight"] == want, (
            f"{path}: 소스는 {want} 인데 화면은 {hero['weight']} 다 - "
            "뒤에 오는 같은 명시도 규칙이 이기고 있다")


def test_landing_and_tool_screens_draw_the_same_hero(static_site, browser):
    """랜딩과 도구 화면의 히어로가 **같은 굵기·같은 크기**로 그려진다.

    240줄 주석이 "랜딩 히어로와 같은 눈금이다" 라고 적고 있다. 두 곳에 적힌
    같은 판단이므로 여기서 대조한다 (§6).
    """
    got = {}
    for path, hero_sel in _SCREENS.items():
        if not hero_sel:
            continue
        page, seen = _visit(browser, static_site, path, hero_sel)
        page.close()
        got[path] = (seen["hero"]["weight"], seen["hero"]["size"])

    assert len(got) == 4, f"잰 히어로 {len(got)}개"
    assert len(set(got.values())) == 1, f"화면마다 히어로가 다르게 그려진다: {got}"


def test_this_check_would_notice_the_old_bug(static_site, browser):
    """⚠⚠ **반대 방향도 한 줄로 잰다** (§6).

    "굵기가 맞다" 만 재면 재는 쪽이 고장 났을 때 조용히 통과한다. 그래서 옛
    결함과 **같은 모양**(뒤에 오는 같은 명시도 규칙)을 일부러 얹어 보고,
    이 프로브가 그 차이를 **실제로 본다**는 것을 단정한다.

    ⚠ 얹는 것은 이 검사 안에서만이다. 파일은 건드리지 않는다 - 주입으로 잰
      값을 파일의 상태로 보고하지 않기 위해서다.
    """
    page, before = _visit(browser, static_site, "/static/index.html", ".intro h2")
    try:
        page.add_style_tag(content=".intro h2{font-weight:400}")
        after = page.evaluate(_READ_HEADINGS, ".intro h2")
    finally:
        page.close()

    assert before["hero"]["weight"] == _declared(".intro h2")
    assert after["hero"]["weight"] == "400", (
        "덮어썼는데도 값이 안 바뀐다 - 이 프로브는 아무것도 못 본다")
    assert before["hero"]["weight"] != after["hero"]["weight"]
