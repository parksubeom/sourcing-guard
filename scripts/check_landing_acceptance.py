#!/usr/bin/env python
"""랜딩 인수 기준을 **측정으로** 확인한다. 눈으로 세지 않는다.

    python scripts/check_landing_acceptance.py --base http://127.0.0.1:8765

v2 기준 (design/README §10-1 · §10-4 · 총괄 명령 2026-09-13 저녁):

    공통    밑줄 있는 버튼 0 · 파란색 0 · 헤더와 본문 좌측선 일치 ·
            본문 첫 글꼴 Noto Sans KR · 제목 서체 Gowun Dodum 실제 로드 · 파비콘
    v2      화면 글자 최소 15px(허용 목록 밖 0) · --fg-4 색 18px 미만 글자 0 ·
            히어로 하단 <= 900 · 데모 버튼 글 == SIGNAL_SHORT + demos[].title ·
            예시 카드 문구 == fixture · 칩은 점과 글자가 한 줄

⚠ 스크린샷은 사람이 보는 것이고 이 스크립트는 **수로 낸다.** 둘 다 남긴다 -
  그림만 보면 "좌측선이 40px 어긋난다" 를 눈대중으로 판정하게 된다. 반대도
  참이다 - 2026-09-13 에 스크린샷이 스크립트가 못 잡은 줄바꿈 결함을 잡았다.

⚠ 이름이 아니라 **좌표와 계산값**으로 잰다. `display:inline-flex` 를 이름으로
  보면 flex 자식의 정상 블록화를 결함으로 읽는다 (실제로 그랬다).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WIDTHS = (1440, 390)
SCHEMES = ("light", "dark")

#: 랜딩 말고도 같은 규약을 지켜야 하는 화면들. 랜딩 전용 항목은 여기서 빼고
#: **공통 규약**(밑줄·파랑·좌측선·글꼴·파비콘)만 본다.
TOOL_PAGES = ("/scan", "/batch", "/watch")

#: 14px 을 허용하는 자리. design/README §10-4 가 "카드 안 한정어" 라 부른 것들 -
#: 예시 결과 카드의 축 이름 · 공표분 주석 · "예시 결과" 표 · 근거 줄 아래 안내.
#: ⚠ 목록을 늘릴 때는 **왜 한정어인지** 한 줄로 적는다. 늘리기만 하면 기준이
#:   사라진다.
SMALL_OK = (".rc-ax .n", ".rc-ax .m", ".rc-tag", ".rc-foot .hint")

_FIXTURE = Path("tests/fixtures/demo_amber_result.json")


def _js_small_text(small_ok: list[str]) -> str:
    """화면에 **실제로 그려지는** 글자 중 기준보다 작은 것을 모은다.

    ⚠ 글자 없는 요소·숨은 요소는 세지 않는다. 그것까지 세면 목록이 노이즈로
      가득 차서 아무도 안 읽게 된다.
    """
    # ⚠ 인자는 **객체 하나**로 넘긴다. 배열을 넘기면 Playwright 가 그것을
    #   그대로 첫 인자로 주는데, 파라미터를 둘로 적으면 둘째가 undefined 가 되고
    #   첫째에 배열 전체가 들어온다 - 실제로 `el.matches(15)` 로 터졌다.
    return """({okSel, minPx}) => {
      const out = [];
      const ok = (el) => okSel.some(s => el.matches(s) || el.closest(s));
      for (const el of document.querySelectorAll('body *')) {
        if (!el.childNodes.length) continue;
        let own = '';
        for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent;
        if (!own.trim()) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        const size = parseFloat(cs.fontSize);
        if (size >= minPx || ok(el)) continue;
        out.push(el.tagName + '.' + (el.className || '') + ' ' + size + 'px "'
                 + own.trim().slice(0, 22) + '"');
      }
      return out.slice(0, 8);
    }"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    fx = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    want_headline = fx["headline"].split(" — ")
    want_axes = [(a["name"], a["label"]) for a in fx["axes"]]

    bad: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        try:
            for scheme in SCHEMES:
                for width in WIDTHS:
                    page = browser.new_page(viewport={"width": width, "height": 900},
                                            color_scheme=scheme)
                    page.goto(args.base + "/", wait_until="networkidle", timeout=60_000)
                    page.evaluate("() => document.fonts.ready")
                    page.wait_for_timeout(500)
                    tag = f"{scheme} {width}px"

                    # ① 밑줄 있는 버튼 0개 (버튼 모양인 것만)
                    underlined = page.eval_on_selector_all(
                        ".btn-primary, .btn-ghost, .demo",
                        "els => els.filter(e => getComputedStyle(e).textDecorationLine"
                        ".includes('underline')).map(e => e.className)")
                    if underlined:
                        bad.append(f"[{tag}] 밑줄 있는 버튼/카드: {underlined}")

                    # ② 파란색 0곳
                    #
                    # ⚠ 파랑 계열 = 파랑이 가장 크고 **빨강이 작다**. 브랜드색
                    #   오키드(139,76,203)는 파랑이 크지만 빨강도 커서 보라다 -
                    #   2026-09-13 에 이 식이 브랜드색을 파랑으로 읽었다.
                    blues = page.evaluate("""() => {
                        const out = [];
                        for (const el of document.querySelectorAll('*')) {
                            const cs = getComputedStyle(el);
                            for (const prop of ['color','backgroundColor','borderTopColor','borderLeftColor']) {
                                const m = cs[prop].match(/rgba?\\((\\d+), (\\d+), (\\d+)/);
                                if (!m) continue;
                                const [r,g,b] = [+m[1],+m[2],+m[3]];
                                if (cs[prop].startsWith('rgba') && cs[prop].endsWith(', 0)')) continue;
                                if (b > r + 40 && b > g + 40 && r < 100) out.push(el.tagName+'.'+el.className+' '+prop+'='+cs[prop]);
                            }
                        }
                        return out.slice(0, 6);
                    }""")
                    if blues:
                        bad.append(f"[{tag}] 파란색: {blues}")

                    # ③ 헤더와 본문 좌측선 일치
                    left = page.evaluate("""() => {
                        const w = document.querySelector('.masthead .wordmark');
                        const h = document.querySelector('.hero-say h1');
                        if (!w || !h) return null;
                        return [w.getBoundingClientRect().left, h.getBoundingClientRect().left];
                    }""")
                    if left is None:
                        bad.append(f"[{tag}] 워드마크나 h1 을 못 찾음")
                    else:
                        wx, hx = left
                        # 워드마크 앞에 마크(32px)+간격이 있으므로 그만큼은 정상 차이다.
                        if abs(wx - hx) > 46:
                            bad.append(f"[{tag}] 좌측선 어긋남: 워드마크 {wx:.0f} · "
                                       f"본문 {hx:.0f} (차 {abs(wx-hx):.0f}px)")

                    # ④ 본문 글꼴이 **받아 온 웹폰트**인가 (design/README §10-1)
                    fam = page.evaluate(
                        "() => getComputedStyle(document.body).fontFamily")
                    first = fam.split(",")[0].strip().strip('"')
                    if first != "Noto Sans KR":
                        bad.append(f"[{tag}] 본문 첫 글꼴이 {first!r} 다")

                    # ⑤ 제목 서체가 실제로 로드됐는가
                    fonts = page.evaluate("""() => {
                        const h1 = document.querySelector('.hero-say h1');
                        return [document.fonts.check('16px "Gowun Dodum"'),
                                h1 ? getComputedStyle(h1).fontFamily : ''];
                    }""")
                    loaded, family = fonts
                    if not loaded:
                        bad.append(f"[{tag}] Gowun Dodum 이 로드되지 않았다")
                    if "Gowun Dodum" not in family:
                        bad.append(f"[{tag}] 제목 서체가 display 가 아니다: {family}")

                    # ⑥ 화면 글자 최소 15px (허용 목록 밖)
                    small = page.evaluate(
                        _js_small_text(list(SMALL_OK)),
                        {"okSel": list(SMALL_OK), "minPx": 15})
                    if small:
                        bad.append(f"[{tag}] 15px 미만 글자: {small}")

                    # ⑦ --fg-4 는 18px 미만 글자에 쓰지 않는다 (대비 3.7:1)
                    faint = page.evaluate("""(minPx) => {
                      const root = getComputedStyle(document.documentElement);
                      const fg4 = root.getPropertyValue('--fg-4').trim();
                      if (!fg4) return ['--fg-4 토큰이 없다'];
                      const probe = document.createElement('span');
                      probe.style.color = fg4;
                      document.body.appendChild(probe);
                      const want = getComputedStyle(probe).color;
                      probe.remove();
                      const out = [];
                      for (const el of document.querySelectorAll('body *')) {
                        let own = '';
                        for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent;
                        if (!own.trim()) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        const cs = getComputedStyle(el);
                        if (cs.color === want && parseFloat(cs.fontSize) < minPx)
                          out.push(el.tagName + '.' + (el.className||'') + ' '
                                   + cs.fontSize + ' "' + own.trim().slice(0,18) + '"');
                      }
                      return out.slice(0, 6);
                    }""", 18)
                    if faint:
                        bad.append(f"[{tag}] --fg-4 로 그린 18px 미만 글자: {faint}")

                    # ⑧ 히어로가 1440x900 안에서 끝난다 (헤더 72 + 828)
                    #
                    # ⚠ 좁은 폭은 접히는 것이 정상이라 1100 이상에서만 본다.
                    if width >= 1100:
                        bottom = page.eval_on_selector(
                            ".lv2-hero", "e => e.getBoundingClientRect().bottom")
                        if bottom > 900:
                            bad.append(f"[{tag}] 히어로가 {bottom:.0f}px 에서 끝난다 "
                                       "(900 안에 들어와야 한다)")

                    # ⑨ 데모 버튼 글 == SIGNAL_SHORT + demos[].title
                    demos = page.evaluate("""() => {
                        const out = [];
                        for (const a of document.querySelectorAll('#demos .demo')) {
                            const chip = a.querySelector('.chip');
                            const t = a.querySelector('.t');
                            const dot = chip && chip.querySelector('.dot');
                            const cr = chip && chip.getBoundingClientRect();
                            const dr = dot && dot.getBoundingClientRect();
                            out.push({
                              chip: chip ? chip.textContent.trim() : null,
                              title: t ? t.textContent.trim() : null,
                              note: !!a.querySelector('.n'),
                              sameRow: (cr && dr)
                                ? Math.abs((dr.top+dr.height/2)-(cr.top+cr.height/2)) < 6 : null,
                              tall: cr ? cr.height > 40 : null,
                            });
                        }
                        return out;
                    }""")
                    import urllib.request
                    with urllib.request.urlopen(args.base + "/api/v1/demos") as r:
                        served = json.loads(r.read().decode("utf-8"))
                    items = served["items"]
                    short = {"green": "정상", "amber": "주의", "red": "위험"}
                    if len(demos) != len(items):
                        bad.append(f"[{tag}] 데모가 {len(demos)}개 (서버는 {len(items)}개)")
                    for i, (got, want) in enumerate(zip(demos, items)):
                        if got["chip"] != short[want["tone"]]:
                            bad.append(f"[{tag}] 데모 {i} 칩 {got['chip']!r} "
                                       f"!= {short[want['tone']]!r}")
                        if got["title"] != want["title"]:
                            bad.append(f"[{tag}] 데모 {i} 제목이 서버와 다르다: "
                                       f"{got['title']!r}")
                        # note 는 랜딩에서 그리지 않는다 (design/README §10-3).
                        if got["note"]:
                            bad.append(f"[{tag}] 데모 {i} 에 note 가 그려졌다")
                        if got["sameRow"] is False:
                            bad.append(f"[{tag}] 데모 {i} 점이 글자와 다른 줄이다")
                        if got["tall"]:
                            bad.append(f"[{tag}] 데모 {i} 칩이 높다 - 점이 글자 위에 얹혔다")

                    # ⑩ 예시 결과 카드의 문구 == fixture (서버가 실제로 낸 문장)
                    card = page.evaluate("""() => {
                        const box = document.getElementById('preview');
                        if (!box || box.hidden) return null;
                        const q = (s) => { const e = box.querySelector(s);
                                           return e ? e.textContent.trim() : null; };
                        return {
                          h: q('.rc-h'), sub: q('.rc-sub'), tag: q('.rc-tag'),
                          axes: [...box.querySelectorAll('.rc-ax')].map(
                              a => [a.querySelector('.n').textContent.trim(),
                                    a.querySelector('.v').textContent.trim()]),
                          rows: [...box.querySelectorAll('.rc-row')].map(
                              r => r.querySelector('.rc-t').textContent.trim()),
                          links: [...box.querySelectorAll('.rc-row a')].length,
                          // 축에 신호 색을 칠하지 않는다 (ResultAxis 주석).
                          axDots: box.querySelectorAll('.rc-ax .dot').length,
                        };
                    }""")
                    if card is None:
                        bad.append(f"[{tag}] 예시 결과 카드가 안 그려졌다")
                    else:
                        if card["h"] != want_headline[0]:
                            bad.append(f"[{tag}] 예시 헤드라인 {card['h']!r} "
                                       f"!= {want_headline[0]!r}")
                        if len(want_headline) > 1 and card["sub"] != want_headline[1]:
                            bad.append(f"[{tag}] 예시 부제 {card['sub']!r} 가 다르다")
                        if card["tag"] != "예시 결과":
                            bad.append(f"[{tag}] '예시 결과' 표가 없다: {card['tag']!r}")
                        if [tuple(a) for a in card["axes"]] != want_axes:
                            bad.append(f"[{tag}] 예시 축이 다르다: {card['axes']}")
                        if card["axDots"]:
                            bad.append(f"[{tag}] 축에 신호 점을 칠했다")
                        if len(card["rows"]) != len(card["links"] * [0]) and not card["links"]:
                            bad.append(f"[{tag}] 근거 줄에 원문 링크가 없다")
                        if card["links"] < len(card["rows"]):
                            bad.append(f"[{tag}] 근거 줄 {len(card['rows'])}개에 "
                                       f"링크가 {card['links']}개다 (R2)")

                    # ⑪ 파비콘 (버전 쿼리가 붙는다)
                    icon = page.eval_on_selector("link[rel=icon]", "e => e.href")
                    if not icon or "favicon.svg" not in icon:
                        bad.append(f"[{tag}] 파비콘 링크가 없다: {icon}")

                    print(f"  [{tag}] 검사 완료")
                    page.close()

            # ── 도구 화면: 공통 규약만 ───────────────────────────────
            for path in TOOL_PAGES:
                for width in WIDTHS:
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.goto(args.base + path, wait_until="networkidle", timeout=60_000)
                    page.evaluate("() => document.fonts.ready")
                    page.wait_for_timeout(300)
                    tag = f"{path} {width}px"

                    fam = page.evaluate(
                        "() => getComputedStyle(document.body).fontFamily")
                    if fam.split(",")[0].strip().strip('"') != "Noto Sans KR":
                        bad.append(f"[{tag}] 본문 첫 글꼴이 {fam.split(',')[0]} 다")
                    if not page.evaluate(
                            "() => document.fonts.check('16px \"Gowun Dodum\"')"):
                        bad.append(f"[{tag}] Gowun Dodum 이 로드되지 않았다")
                    icon = page.eval_on_selector("link[rel=icon]", "e => e.href")
                    if not icon or "favicon.svg" not in icon:
                        bad.append(f"[{tag}] 파비콘 링크가 없다")
                    blues = page.evaluate("""() => {
                        const out = [];
                        for (const el of document.querySelectorAll('*')) {
                            const cs = getComputedStyle(el);
                            for (const prop of ['color','backgroundColor']) {
                                const m = cs[prop].match(/rgba?\\((\\d+), (\\d+), (\\d+)/);
                                if (!m) continue;
                                const [r,g,b] = [+m[1],+m[2],+m[3]];
                                if (cs[prop].startsWith('rgba') && cs[prop].endsWith(', 0)')) continue;
                                if (b > r + 40 && b > g + 40 && r < 100) out.push(el.tagName+'.'+el.className);
                            }
                        }
                        return out.slice(0, 4);
                    }""")
                    if blues:
                        bad.append(f"[{tag}] 파란색: {blues}")
                    print(f"  [{tag}] 검사 완료")
                    page.close()
        finally:
            browser.close()

    print()
    if bad:
        print("인수 기준 미달:")
        for b in bad:
            print("  -", b)
        return 1
    print("인수 기준 전부 통과 (라이트/다크 × 1440/390 · 도구 화면 셋)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
