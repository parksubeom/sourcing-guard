#!/usr/bin/env python
"""화면 스크린샷을 찍는다. **인수 기준을 그림으로 낸다** ([제출-2]).

왜 스크립트인가
---------------
"밑줄 있는 버튼 0개 · 파란색 0곳 · 헤더와 본문 좌측선 일치" 같은 인수 기준은
사람이 눈으로 봐야 하는 것이지만, **매번 손으로 찍으면 폭·스케일이 달라져
비교가 안 된다.** 폭과 배율을 고정한다.

    python scripts/shoot_screens.py --base http://127.0.0.1:8765 --tag applied

⚠ 로컬 서버를 먼저 띄운다. 배포본을 찍으려면 `--base https://…` 를 준다.

⚠ 폰트가 원격(Google Fonts)이라 **로드를 기다린다.** 안 기다리면 기본 서체로
  찍혀 "폰트가 안 먹었다" 로 오독한다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

WIDTHS = {"1440": 1440, "390": 390}
PAGES = {"landing": "/", "scan": "/scan", "batch": "/batch", "watch": "/watch"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--tag", required=True, help="파일명 꼬리표 (before / applied …)")
    ap.add_argument("--pages", default="landing", help="쉼표로 (landing,scan,…)")
    ap.add_argument("--out", default="design/preview")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright 가 없습니다: pip install playwright")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    want = [p.strip() for p in args.pages.split(",") if p.strip()]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        try:
            for name in want:
                path = PAGES[name]
                for label, width in WIDTHS.items():
                    page = browser.new_page(viewport={"width": width, "height": 900},
                                            device_scale_factor=2)
                    page.goto(args.base + path, wait_until="networkidle", timeout=60_000)
                    # ⚠ 웹폰트가 실제로 그려진 뒤에 찍는다.
                    page.evaluate("() => document.fonts.ready")
                    page.wait_for_timeout(600)
                    f = out / f"{args.tag}-{name}-{label}.png"
                    page.screenshot(path=str(f), full_page=True)
                    print(f"  {f}  ({width}px)")
                    page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
