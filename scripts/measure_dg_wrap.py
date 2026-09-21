"""did 줄이 어디서 끊기는가 — **일곱 폭에서** 잰다 (총괄 ⑶).

    · 1440 에서 한 줄이던 것이 두 줄이 되면 안 된다
    · 좁은 폭에서 1행 끝이 「·」 로 끝나면 안 된다
    · 29장이 다 같은 줄수·같은 높이여야 한다 (들쭉날쭉하면 그게 흠이다)

띄워 두고 돌린다:

    PYTHONUTF8=1 MOCK_MODE=true python -m uvicorn sourcing_guard.main:app --port 8031
    python -u scripts/measure_dg_wrap.py

⚠ 실호출 0회.
"""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8031/scan"

MEASURE = """() => {
  const out = [];
  document.querySelectorAll('.dg-did').forEach((el, i) => {
    const kids = [...el.children];
    const tops = [...new Set(kids.map(k => Math.round(k.getBoundingClientRect().top)))];
    // 1행에 놓인 조각들의 글자를 이어 붙여 줄 끝 글자를 본다
    const firstTop = Math.min(...kids.map(k => Math.round(k.getBoundingClientRect().top)));
    const line1 = kids.filter(k => Math.round(k.getBoundingClientRect().top) === firstTop)
                      .map(k => k.textContent.trim()).join(' ');
    out.push({ i, lines: tops.length, h: Math.round(el.getBoundingClientRect().height),
               line1, all: el.textContent.trim() });
  });
  return out;
}"""

with sync_playwright() as p:
    br = p.chromium.launch()
    for w in (1440, 1280, 1024, 768, 390, 360, 320):
        q = br.new_page(viewport={"width": w, "height": 900})
        q.goto(URL, wait_until="networkidle"); q.wait_for_selector(".dg-did")
        rows = q.evaluate(MEASURE)
        lines = sorted({r["lines"] for r in rows})
        hs = sorted({r["h"] for r in rows})
        bad = [r for r in rows if r["line1"].rstrip().endswith("·")]
        print(f"{w:5d}px  did {len(rows)}개 · 줄수 {lines} · 높이 {hs}px"
              f" · 1행이 「·」로 끝나는 카드 {len(bad)}개")
        if rows:
            print(f"        1행 보기: {rows[0]['line1']!r}   전체 {rows[0]['all']!r}")
        q.close()
    br.close()
