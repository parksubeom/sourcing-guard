#!/usr/bin/env python
"""[제출-2] 랜딩 인수 기준을 **측정으로** 확인한다. 눈으로 세지 않는다.

총괄이 준 기준 여덟을 그대로 잰다:

    밑줄 있는 버튼 0개 · 파란색 0곳 · 헤더와 본문 좌측선 일치 ·
    히어로 오른쪽에 마스코트 · 데모 셋이 칩+제목 · ⓪이 카드 셋 ·
    폰트가 실제 로드 · 파비콘

⚠ 스크린샷은 사람이 보는 것이고 이 스크립트는 **수로 낸다.** 둘 다 남긴다 -
  그림만 보면 "좌측선이 40px 어긋난다" 를 눈대중으로 판정하게 된다.

    python scripts/check_landing_acceptance.py --base http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import sys

WIDTHS = (1440, 390)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    bad: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        try:
            for width in WIDTHS:
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(args.base + "/", wait_until="networkidle", timeout=60_000)
                page.evaluate("() => document.fonts.ready")
                page.wait_for_timeout(400)
                tag = f"{width}px"

                # ① 밑줄 있는 버튼·링크 0개 (버튼 모양인 것만)
                underlined = page.eval_on_selector_all(
                    ".btn-primary, .btn-ghost, .demo",
                    "els => els.filter(e => getComputedStyle(e).textDecorationLine"
                    ".includes('underline')).map(e => e.className)")
                if underlined:
                    bad.append(f"[{tag}] 밑줄 있는 버튼/카드: {underlined}")

                # ② 파란색 0곳 - 화면에 그려지는 색에 파랑 계열이 없어야 한다
                blues = page.evaluate("""() => {
                    const out = [];
                    for (const el of document.querySelectorAll('*')) {
                        const cs = getComputedStyle(el);
                        for (const prop of ['color','backgroundColor','borderTopColor','borderLeftColor']) {
                            const m = cs[prop].match(/rgba?\\((\\d+), (\\d+), (\\d+)/);
                            if (!m) continue;
                            const [r,g,b] = [+m[1],+m[2],+m[3]];
                            if (cs[prop].startsWith('rgba') && cs[prop].endsWith(', 0)')) continue;
                            // 파랑 계열 = 파랑이 가장 크고 **빨강이 작다**.
                            // 브랜드색 오키드(139,76,203)는 파랑이 크지만 빨강도
                            // 커서 보라다 - 2026-09-13 에 이 식이 브랜드색을
                            // 파랑으로 읽었다. 기준은 "파랗게 보이는가" 다.
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
                    const h = document.querySelector('.hero h1');
                    if (!w || !h) return null;
                    return [w.getBoundingClientRect().left, h.getBoundingClientRect().left];
                }""")
                if left is None:
                    bad.append(f"[{tag}] 워드마크나 h1 을 못 찾음")
                else:
                    wx, hx = left
                    # 워드마크 앞에 마크(32px)+간격이 있으므로 그만큼은 정상 차이다.
                    gap = abs(wx - hx)
                    if gap > 46:
                        bad.append(f"[{tag}] 좌측선 어긋남: 워드마크 {wx:.0f} · 본문 {hx:.0f} (차 {gap:.0f}px)")

                # ④ 히어로 오른쪽 마스코트 (1100px 아래는 숨김이 정상)
                art = page.evaluate("""() => {
                    const m = document.querySelector('.mascot-hero');
                    if (!m) return 'none';
                    const r = m.getBoundingClientRect();
                    return (r.width > 0 && r.height > 0) ? [r.left, r.width] : 'hidden';
                }""")
                if width >= 1100 and (art in ("none", "hidden")):
                    bad.append(f"[{tag}] 히어로 마스코트가 안 보인다: {art}")
                if width < 1100 and art not in ("none", "hidden"):
                    bad.append(f"[{tag}] 좁은 폭인데 오른쪽 그림이 보인다")

                # ⑤ 데모 셋이 칩 + 제목
                demos = page.eval_on_selector_all(
                    "#demos .demo",
                    "els => els.map(e => [!!e.querySelector('.chip'), !!e.querySelector('.t')])")
                if len(demos) != 3 or not all(a and b for a, b in demos):
                    bad.append(f"[{tag}] 데모 카드가 칩+제목이 아니다: {demos}")

                # ⑥ ⓪ 이 카드 셋이고 숫자가 실제로 채워졌다
                cards = page.eval_on_selector_all(
                    "#why-figures .card",
                    "els => els.map(e => (e.querySelector('.num')||{}).textContent||'')")
                if len(cards) != 3:
                    bad.append(f"[{tag}] ⓪ 카드가 3개가 아니다: {len(cards)}")
                elif any(c.strip() in ("", "-") for c in cards):
                    bad.append(f"[{tag}] ⓪ 카드 숫자가 안 채워졌다: {cards}")

                # ⑦ 폰트가 실제로 로드됐다
                fonts = page.evaluate("""() => {
                    const h1 = document.querySelector('.hero h1');
                    const ok = document.fonts.check('16px "Gowun Dodum"');
                    return [ok, h1 ? getComputedStyle(h1).fontFamily : ''];
                }""")
                loaded, family = fonts
                if not loaded:
                    bad.append(f"[{tag}] Gowun Dodum 이 로드되지 않았다")
                if "Gowun Dodum" not in family:
                    bad.append(f"[{tag}] 제목 서체가 display 가 아니다: {family}")

                # ⑨ 칩이 눕지 않았나 (2026-09-13 추가)
                #
                # ⚠⚠ **눈에 보이는 결함을 이 스크립트가 못 잡았다.** 옛
                #   `.demo span{display:block}` 이 칩과 점을 block 으로 눕혀
                #   점이 글자 위에 얹혔는데, 앞의 검사는 "칩이 있나" 만 봤다.
                #   **있는지가 아니라 어떻게 그려지는지를 본다.**
                # ⚠ `display` 이름으로 재지 않는다. `.demo` 가 flex 컨테이너라
                #   자식의 `inline-flex` 는 명세대로 `flex` 로 **블록화**된다 -
                #   이름만 보면 정상을 결함으로 읽는다(실제로 그랬다).
                #   **점과 글자가 가로로 나란한가**를 좌표로 잰다.
                chips = page.evaluate("""() => {
                    const out = [];
                    for (const c of document.querySelectorAll('#demos .demo .chip')) {
                        const dot = c.querySelector('.dot');
                        const r = c.getBoundingClientRect();
                        if (!dot) { out.push({err: 'no-dot'}); continue; }
                        const d = dot.getBoundingClientRect();
                        // 칩 안 글자만의 상자 = 칩에서 점을 뺀 나머지
                        const range = document.createRange();
                        range.selectNodeContents(c);
                        const t = range.getBoundingClientRect();
                        out.push({
                            chipW: r.width, chipH: r.height,
                            dotRight: d.right, textLeft: t.left,
                            sameRow: Math.abs((d.top + d.height / 2) - (r.top + r.height / 2)) < 6,
                            tall: r.height > 40,
                        });
                    }
                    return out;
                }""")
                if len(chips) != 3:
                    bad.append(f"[{tag}] 칩이 3개가 아니다: {len(chips)}")
                for i, c in enumerate(chips):
                    if c.get("err"):
                        bad.append(f"[{tag}] 데모 {i} 칩에 점이 없다")
                        continue
                    if not c["sameRow"]:
                        bad.append(f"[{tag}] 데모 {i} 점이 글자와 같은 줄이 아니다")
                    if c["tall"]:
                        bad.append(
                            f"[{tag}] 데모 {i} 칩이 {c['chipH']:.0f}px 로 높다 - "
                            "점이 글자 위에 얹혔을 때의 모양이다")

                # ⑩ 히어로 상단 여백 (1440 에서만 · 좁은 폭은 값이 다르다)
                #
                # ⚠ `.container{padding:0 64px}` shorthand 가 `.hero` 의 세로
                #   여백을 0 으로 덮은 적이 있다. 가로를 고치다 세로를 날렸다.
                if width >= 1100:
                    pad = page.eval_on_selector(
                        ".hero", "e => parseFloat(getComputedStyle(e).paddingTop)")
                    if pad < 64:
                        bad.append(f"[{tag}] 히어로 상단 여백이 {pad:.0f}px (64 이상이어야 한다)")

                # ⑪ 붙여넣기 카드가 왼쪽 정렬인가
                #
                # ⚠ `/scan` 의 붙여넣기 **버튼**도 `.paste` 라 그쪽의
                #   `text-align:center` 를 물려받아 카드 글이 가운데로 갔다.
                #   **이름이 같은 것이 원인이다.**
                    align = page.eval_on_selector(
                        ".hero-art .paste", "e => getComputedStyle(e).textAlign")
                    if align not in ("left", "start"):
                        bad.append(f"[{tag}] 붙여넣기 카드 정렬이 {align} 다 (left 여야 한다)")

                # ⑧ 파비콘
                icon = page.eval_on_selector("link[rel=icon]", "e => e.href")
                if not icon or not icon.endswith("favicon.svg"):
                    bad.append(f"[{tag}] 파비콘 링크가 없다: {icon}")

                print(f"  [{tag}] 검사 완료")
                page.close()
        finally:
            browser.close()

    if bad:
        print("\n인수 기준 미달:")
        for b in bad:
            print("  ", b)
        return 1
    print("\n인수 기준 여덟 항목 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
