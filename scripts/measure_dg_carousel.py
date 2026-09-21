"""도매꾹 카드 가로 목록 실측 — 총괄이 준 검증 순서 그대로.

    1 손으로 밀리는가 · 밀면 자동이 멈추는가
    2 5초가 실제 5초인가
    3 카드 줄이 붙는가 (did)
    4 제목
    5 폭별 가로넘침

띄워 두고 돌린다:

    PYTHONUTF8=1 MOCK_MODE=true python -m uvicorn sourcing_guard.main:app --port 8031
    python -u scripts/measure_dg_carousel.py

⚠ 실호출 0회다 - 목 모드이고 진열 자료는 이미 받아 둔 사본이다.
⚠ 시간을 재므로 **한 번에 하나만** 돌린다. 둘이 겹치면 간격이 흔들린다.
"""
import time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8031/scan"
SEL = ".dg-list"


def scroll_left(pg):
    return pg.eval_on_selector(SEL, "el => el.scrollLeft")


with sync_playwright() as p:
    br = p.chromium.launch()

    # ── 1  손으로 밀리는가 · 밀면 자동이 멈추는가 ────────────────────────
    pg = br.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_selector(SEL)
    print("── ① 손으로 밀기 · 밀면 자동 멈춤 (1440) ──")
    time.sleep(11)                       # 자동 2칸분
    auto = scroll_left(pg)
    print(f"   11초 자동      scrollLeft = {auto:.0f}px")
    pg.eval_on_selector(SEL, "el => el.scrollTo({left: 754})")   # 손으로 민다
    pg.wait_for_timeout(400)
    hand = scroll_left(pg)
    print(f"   손으로 민 직후 scrollLeft = {hand:.0f}px   → 밀린다: {hand > auto}")
    time.sleep(6.5)                      # 자동이 살아 있으면 여기서 움직인다
    after = scroll_left(pg)
    print(f"   민 뒤 6.5초    scrollLeft = {after:.0f}px   → 자동 멈춤: {abs(after - hand) < 1}")

    # ── 2  5초가 실제 5초인가 ───────────────────────────────────────────
    pg2 = br.new_page(viewport={"width": 1440, "height": 900})
    pg2.goto(URL, wait_until="networkidle")
    pg2.wait_for_selector(SEL)
    print("\n── ② 간격이 5초인가 (1440 · 17초 관찰) ──")
    marks, prev, t0 = [], scroll_left(pg2), time.time()
    while time.time() - t0 < 17:
        time.sleep(0.1)
        now = scroll_left(pg2)
        if abs(now - prev) > 4:
            marks.append(time.time()); prev = now
            while True:                  # smooth 가 멎을 때까지
                time.sleep(0.15)
                n2 = scroll_left(pg2)
                if abs(n2 - prev) < 1: break
                prev = n2
    print(f"   넘김 {len(marks)}회")
    for a, b in zip(marks, marks[1:]):
        print(f"   간격  {b - a:.2f}초")

    # ── 자동이 꺼져야 하는 자리 셋 ──────────────────────────────────────
    print("\n── 자동이 꺼지는가 (11초 동안 칸이 안 움직여야 한다) ──")
    for label, kw in [
        ("reduced-motion", dict(viewport={"width":1440,"height":900}, reduced_motion="reduce")),
        ("폰 390",         dict(viewport={"width":390,"height":844})),
    ]:
        q = br.new_page(**kw)
        q.goto(URL, wait_until="networkidle"); q.wait_for_selector(SEL)
        a0 = scroll_left(q); time.sleep(11); a1 = scroll_left(q)
        print(f"   {label:14s} {a0:.0f} → {a1:.0f}px   꺼짐: {abs(a1-a0) < 1}")
        q.close()

    q = br.new_page(viewport={"width": 1440, "height": 900})
    q.goto(URL, wait_until="networkidle"); q.wait_for_selector(SEL)
    q.hover(SEL); a0 = scroll_left(q); time.sleep(11); a1 = scroll_left(q)
    print(f"   {'호버':14s} {a0:.0f} → {a1:.0f}px   정지: {abs(a1-a0) < 1}")
    q.close()

    # ── 3·4  카드 줄 · 제목 ─────────────────────────────────────────────
    q = br.new_page(viewport={"width": 1440, "height": 900})
    q.goto(URL, wait_until="networkidle"); q.wait_for_selector(SEL)
    cards = q.eval_on_selector_all(f"{SEL} > li", "els => els.length")
    dids  = q.eval_on_selector_all(".dg-did", "els => els.map(e => e.textContent.trim())")
    print(f"\n── ③ 카드 줄 ──\n   카드 {cards}장 · did 있는 카드 {len(dids)}장")
    for d in dids[:3]: print(f"   {d}")
    head = q.eval_on_selector("#dg-h", "el => el.textContent.trim()")
    print(f"\n── ④ 제목 ──\n   {head}")

    # ── 5  폭별 가로넘침 ────────────────────────────────────────────────
    print("\n── ⑤ 폭별 (페이지가 옆으로 밀리나) ──")
    for w in (1440, 1280, 1024, 768, 390):
        z = br.new_page(viewport={"width": w, "height": 900})
        z.goto(URL, wait_until="networkidle"); z.wait_for_selector(SEL)
        over = z.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth")
        lefts = z.eval_on_selector_all(f"{SEL} > li",
                "els => [...new Set(els.map(e => Math.round(e.getBoundingClientRect().top)))].length")
        sw = z.eval_on_selector(SEL, "el => el.scrollWidth")
        cw = z.eval_on_selector(SEL, "el => el.clientWidth")
        print(f"   {w:5d}px   가로넘침 {str(over):5s} · 카드 윗변 좌표 가짓수 {lefts} · 목록 {cw}→{sw}px")
        z.close()
    br.close()
