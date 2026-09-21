"""다섯 고리 + **실제 입력**으로 「밀면 멈춤」 + 「뗐을 때 되살아남」.

띄워 두고 돌린다:

    PYTHONUTF8=1 MOCK_MODE=true python -m uvicorn sourcing_guard.main:app --port 8031
    python -u scripts/measure_dg_hooks.py

⚠ **`el.scrollTo(...)` 로 흉내 내지 않는다.** 그것은 `scroll` 만 내고 휠·포인터를
  안 내므로 사용자가 하지 않는 행동이다 - `scroll` 추론을 지운 뒤 그 흉내만
  False 가 났고, 틀린 것은 코드가 아니라 측정이었다 (2026-09-21).
⚠ 실호출 0회 · 시간을 재므로 한 번에 하나만 돌린다.
"""
import time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8031/scan"
SEL = ".dg-list"
def sx(q): return q.eval_on_selector(SEL, "el => el.scrollLeft")

with sync_playwright() as p:
    br = p.chromium.launch()

    print("── 자동이 도는가 (1440 · 11초) ──")
    q = br.new_page(viewport={"width":1440,"height":900})
    q.goto(URL, wait_until="networkidle"); q.wait_for_selector(SEL)
    a0 = sx(q); time.sleep(11); a1 = sx(q)
    print(f"   {a0:.0f} → {a1:.0f}px   돈다: {a1 > a0}")
    q.close()

    print("\n── 실제 입력으로 밀면 자동이 멈추는가 ──")
    for label, act in [
        ("휠", lambda w: (w.hover(SEL), w.mouse.wheel(400, 0))),
        ("키보드 →", lambda w: (w.click(SEL), w.keyboard.press("ArrowRight"))),
    ]:
        w = br.new_page(viewport={"width":1440,"height":900})
        w.goto(URL, wait_until="networkidle"); w.wait_for_selector(SEL)
        time.sleep(1)
        act(w); w.wait_for_timeout(800)
        b0 = sx(w); time.sleep(11); b1 = sx(w)
        print(f"   {label:8s} 민 뒤 {b0:.0f} → 11초 후 {b1:.0f}px   멈춤: {abs(b1-b0) < 1}")
        w.close()

    print("\n── 다섯 고리 ──")
    for label, kw, act in [
        ("호버",           dict(viewport={"width":1440,"height":900}), lambda w: w.hover(SEL)),
        ("포커스",         dict(viewport={"width":1440,"height":900}), lambda w: w.eval_on_selector(SEL,"el=>el.focus()")),
        ("reduced-motion", dict(viewport={"width":1440,"height":900}, reduced_motion="reduce"), None),
        ("폰 390",         dict(viewport={"width":390,"height":844}), None),
    ]:
        w = br.new_page(**kw)
        w.goto(URL, wait_until="networkidle"); w.wait_for_selector(SEL)
        if act: act(w)
        c0 = sx(w); time.sleep(11); c1 = sx(w)
        print(f"   {label:16s} {c0:.0f} → {c1:.0f}px   멈춰 있음: {abs(c1-c0) < 1}")
        w.close()

    print("\n── 호버를 풀면 되살아나는가 ──")
    w = br.new_page(viewport={"width":1440,"height":900})
    w.goto(URL, wait_until="networkidle"); w.wait_for_selector(SEL)
    w.hover(SEL); d0 = sx(w); time.sleep(6); d1 = sx(w)
    w.mouse.move(10, 10); time.sleep(6); d2 = sx(w)
    print(f"   호버중 {d0:.0f}→{d1:.0f}  뗀 뒤 →{d2:.0f}   되살아남: {d2 > d1}")
    w.close()
    br.close()
