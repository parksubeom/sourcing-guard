"""제목 굵기를 **실제 브라우저의 computed 값으로** 잰다.

왜 있나
-------
소스에 `font-weight:700` 이 적혀 있는 것과 화면이 그렇게 그려지는 것은 다르다.
2026-09-20 에 `.intro h2` 가 그랬다 - 240줄이 700 을 적었는데 591줄의
`h1, h2, .wordmark, .intro h2{font-weight:400}` 이 **같은 명시도로 뒤에 와서**
이겼고, 화면은 400 이었다. 검사 1,800개가 전부 소스 문자열만 보아 못 잡았다.

`docs/CLAUDE.md` §6 이 이미 이름 붙여 둔 자리다 - "주입으로 잰 CSS 값을
「검증했다」고 말했다" · "화면 검사는 틀이 아니라 틀에 붓는 값을 본다".

무엇을 재나
-----------
여덟 화면의 **`h1` · `h2` · `.wordmark` 전부**의 computed `font-weight` 를
폭마다 찍는다. 히어로 제목(`.hero-say h1` · `.intro h2`)은 따로 표시하고,
랜딩과 도구 화면이 **같은 값인지**를 판정에 쓴다.

⚠ 굵기는 폭에 따라 달라질 이유가 없지만 **그렇다는 것도 재서 안다.**
  좁은 폭 분기가 `font-size` 만 바꾸는지 확인하는 자리이기도 하다.

⚠ 다크는 `prefers-color-scheme` 만 바꾼다. 굵기가 테마를 타면 그것 자체가
  결함이므로 같이 잰다.

쓰는 법
-------
    PYTHONUTF8=1 MOCK_MODE=true python -m uvicorn sourcing_guard.main:app --port 8021
    PYTHONUTF8=1 python -u scripts/measure_weights.py --base http://127.0.0.1:8021

`playwright` 는 `requirements.txt` 에 없다 (`docs/새_PC_이전_체크리스트.md` §6).

    pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import sys

#: 여덟 화면 전부. 늘리면 여기 먼저 적는다 - `tests/test_frontend.py` 의 PAGES 가
#: 넷만 들고 있어 새 화면이 가드 밖에 있던 것이 2026-09-20 의 일이다.
PAGES = ("/", "/scan", "/batch", "/watch", "/guide", "/samples", "/misses", "/unknown")

WIDTHS = (1440, 1280, 1024, 768, 390, 320)

#: 히어로 제목. 랜딩과 도구 화면이 **같은 굵기**여야 한다 (C안 · 2026-09-20).
HERO_SEL = ".hero-say h1, .intro h2"

_PROBE = """(heroSel) => {
  const out = [];
  document.querySelectorAll('h1, h2, .wordmark').forEach(el => {
    const cs = getComputedStyle(el);
    // 가장 가까운 '클래스를 가진 조상' 까지 적는다. 같은 태그가 화면마다
    // 여럿이라 태그만으로는 어느 줄인지 못 가린다.
    let anc = el.parentElement, path = '';
    while (anc && anc !== document.body) {
      if (anc.className && typeof anc.className === 'string') {
        path = '.' + anc.className.trim().split(/\s+/).join('.'); break;
      }
      anc = anc.parentElement;
    }
    out.push({
      el: el.tagName.toLowerCase()
          + (el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : ''),
      under: path,
      text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 22),
      weight: cs.fontWeight,
      size: cs.fontSize,
      family: cs.fontFamily.split(',')[0].replace(/"/g, ''),
      hero: el.matches(heroSel),
    });
  });
  return out;
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8021")
    ap.add_argument("--pages", default=",".join(PAGES))
    ap.add_argument("--widths", default=",".join(str(w) for w in WIDTHS))
    ap.add_argument("--json", help="원자료를 이 경로에 적는다")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 가 없다: pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 2

    pages = [p for p in args.pages.split(",") if p]
    widths = [int(w) for w in args.widths.split(",") if w]
    #: (폭, 스킴) 조합. 다크는 대표 폭 하나에서만 본다 - 굵기가 폭 × 테마로
    #: 갈릴 이유가 없고, 전조합을 돌면 96쪽이 된다.
    combos = [(w, "light") for w in widths] + [(widths[0], "dark")]

    rows: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for scheme in ("light", "dark"):
            ctx = browser.new_context(color_scheme=scheme)
            for path in pages:
                for width, sch in combos:
                    if sch != scheme:
                        continue
                    page = ctx.new_page()
                    page.set_viewport_size({"width": width, "height": 900})
                    page.goto(args.base + path, wait_until="networkidle", timeout=60_000)
                    page.evaluate("() => document.fonts.ready")
                    for got in page.evaluate(_PROBE, HERO_SEL):
                        rows.append({"page": path, "width": width, "scheme": scheme, **got})
                    page.close()
            ctx.close()
        browser.close()

    if not rows:
        print("잰 요소가 0개다. 이건 검사가 아니다 (§6).", file=sys.stderr)
        return 1

    # ── 표 ────────────────────────────────────────────────────────────
    print(f'{"화면":9} {"폭":>5} {"테마":5} {"요소":28} {"글":22} {"굵기":>5} {"크기":>7} 글꼴')
    for r in rows:
        star = "★" if r["hero"] else " "
        el = (r["under"] + " " + r["el"]).strip()
        print(f'{r["page"]:9} {r["width"]:>5} {r["scheme"]:5} {star}{el[:27]:27} '
              f'{r["text"][:21]:21} {r["weight"]:>5} {r["size"]:>7} {r["family"]}')

    # ── 판정 ──────────────────────────────────────────────────────────
    print()
    combos_seen = {(r["page"], r["width"], r["scheme"]) for r in rows}
    print(f"본 쪽 {len(combos_seen)} (화면 {len({r['page'] for r in rows})} × "
          f"폭·테마 {len(combos)}) · 잰 요소 {len(rows)}개")

    heroes = [r for r in rows if r["hero"]]
    hero_pages = {r["page"] for r in heroes}
    print(f"히어로 제목이 있는 화면 {len(hero_pages)}: {' '.join(sorted(hero_pages))}")
    hero_weights = sorted({r["weight"] for r in heroes})
    print(f"히어로 굵기 집합 = {hero_weights}")

    bad = 0
    if len(hero_weights) != 1:
        bad += 1
        for w in hero_weights:
            who = sorted({r["page"] for r in heroes if r["weight"] == w})
            print(f"  ⚠ 굵기 {w}: {' '.join(who)}")
        print("  → 랜딩과 도구 화면의 히어로 제목이 갈렸다.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print(f"원자료: {args.json}")

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
