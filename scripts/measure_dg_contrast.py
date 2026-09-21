"""did 줄이 다크에서도 읽히는가 — 색 토큰이 실제로 갈라지는지 본다.

띄워 두고 돌린다:

    PYTHONUTF8=1 MOCK_MODE=true python -m uvicorn sourcing_guard.main:app --port 8031
    python -u scripts/measure_dg_contrast.py

⚠ **눈으로 본 것이 아니다.** 계산된 색을 WCAG 식으로 잰 수다 - "읽힌다" 는
  단정이 아니라 대비비다. 눈으로 본 것은 캡처 둘(1440 밝기 · 390 밝기)뿐이다.
"""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8031/scan"

def lum(rgb):
    def c(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (c(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def parse(s):
    return tuple(int(x) for x in s[s.index("(") + 1:s.index(")")].split(",")[:3])

with sync_playwright() as p:
    br = p.chromium.launch()
    for scheme in ("light", "dark"):
        pg = br.new_page(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_selector(".dg-did")
        fg = pg.eval_on_selector(".dg-did", "el => getComputedStyle(el).color")
        bg = pg.eval_on_selector(".dg-list > li",
             "el => { let n = el; while (n) { const c = getComputedStyle(n).backgroundColor;"
             "  if (c && c !== 'rgba(0, 0, 0, 0)') return c; n = n.parentElement; } return 'rgb(255,255,255)'; }")
        L1, L2 = lum(parse(fg)), lum(parse(bg))
        hi, lo = max(L1, L2), min(L1, L2)
        ratio = (hi + 0.05) / (lo + 0.05)
        ok = "통과" if ratio >= 4.5 else ("큰글자만" if ratio >= 3.0 else "미달")
        print(f"{scheme:6s} 글자 {fg:22s} 바탕 {bg:22s} 대비 {ratio:.2f}:1  AA {ok}")
        pg.close()
    br.close()
