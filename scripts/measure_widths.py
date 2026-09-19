"""화면이 가로로 밀리는지 **실제 브라우저로** 잰다.

왜 있나
-------
지금 모바일 검사는 **CSS 규칙의 존재와 순서**만 본다. "접히게 돼 있다" 까지만
말하고 **"안 넘친다" 는 못 말한다** (`docs/미완_목록.md` §1-l (3)).

그래서 `scrollWidth <= viewport` 를 폭마다 직접 잰다. 넘치면 **어느 요소가**
넘치는지, 그 요소의 그리드 칸이 몇 px 로 풀렸는지까지 같이 뱉는다 - 숫자만
있으면 다음 사람이 픽셀을 깎는 고침을 한다 (§1-l 이 하지 말라고 적어 둔 것).

⚠ **이 수는 상수가 아니다.** 칸 폭이 글자에서 나오므로 폰트·기계에 따라
  움직인다. 총괄 기계와 개발 PC 가 `/` 320px 에서 340 과 339 로 갈렸고 폰트를
  차단하면 **방향까지** 갈렸다(+6 / −5). 그래서 이 스크립트는 **넘쳤는가**
  (불리언)를 판정에 쓰고, px 는 참고로만 적는다.

⚠ 640/641 을 목록에 넣는다 - 미디어쿼리가 꺼지는 자리가 제일 잘 깨진다.

쓰는 법
-------
    # 앱을 먼저 띄운다 (목 모드면 LLM·정부 API 를 안 부른다)
    PYTHONUTF8=1 MOCK_MODE=true python -m uvicorn sourcing_guard.main:app --port 8011

    PYTHONUTF8=1 python -u scripts/measure_widths.py --base http://127.0.0.1:8011

`playwright` 는 `requirements.txt` 에 없다. 검사에 안 쓰이므로 코드만 볼 때는
필요 없다 (`docs/새_PC_이전_체크리스트.md` §6).

    pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import sys

WIDTHS = (320, 360, 375, 390, 414, 430, 480, 540, 640, 641, 768, 1000, 1280, 1440)
PAGES = ("/", "/scan", "/batch", "/watch", "/guide")

# 넘친 요소를 조상까지 따라가 "누가 칸을 벌리는가" 를 찾는다. §1-l 이 그렇게
# 재서 원인을 찾았다 - 넘친 요소 목록만으로는 글자 탓으로 오독한다.
_PROBE = """() => {
  const vw = document.documentElement.clientWidth;
  const bad = [];
  document.querySelectorAll('body *').forEach(el => {
    const r = el.getBoundingClientRect();
    // ⚠ 왼쪽으로 나간 것은 세지 않는다. 건너뛰기 링크를 화면 밖에 두는 것은
    //   일부러 하는 접근성 관례이고(`A.skip` right=-9869), 문서의 가로 스크롤은
    //   오른쪽으로만 생긴다. 왼쪽을 세면 매 폭마다 같은 오탐이 하나씩 붙어
    //   진짜 넘침이 묻힌다.
    if (r.right > vw + 0.5 || el.scrollWidth > Math.ceil(r.width) + 1) {
      const cs = getComputedStyle(el);
      const p = el.parentElement;
      bad.push({
        tag: el.tagName + (el.className ? '.' + String(el.className).split(' ').join('.') : ''),
        w: Math.round(r.width * 100) / 100,
        scroll: el.scrollWidth,
        right: Math.round(r.right * 100) / 100,
        parentDisplay: p ? getComputedStyle(p).display : null,
        parentCols: p ? getComputedStyle(p).gridTemplateColumns : null,
        minWidth: cs.minWidth,
      });
    }
  });
  return {
    scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    viewport: vw,
    offenders: bad.slice(0, 6),
  };
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--pages", default=",".join(PAGES))
    ap.add_argument("--widths", default=",".join(str(w) for w in WIDTHS))
    ap.add_argument("--verbose", action="store_true", help="넘치지 않아도 줄을 적는다")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 가 없다: pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 2

    pages = [p for p in args.pages.split(",") if p]
    widths = [int(w) for w in args.widths.split(",") if w]
    overflows: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for path in pages:
            for width in widths:
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(args.base + path, wait_until="networkidle")
                got = page.evaluate(_PROBE)
                over = got["scrollWidth"] > got["viewport"]
                mark = "넘침" if over else "  ok"
                if over or args.verbose:
                    print(f'{mark}  {path:8} {width:>5}px  scrollWidth={got["scrollWidth"]}')
                if over:
                    overflows.append(f'{path} {width}px (+{got["scrollWidth"] - width})')
                    for o in got["offenders"]:
                        print(f'        {o["tag"][:54]:56} w={o["w"]:>8} '
                              f'scroll={o["scroll"]:>5} right={o["right"]:>8}')
                        if o["parentDisplay"] == "grid":
                            print(f'        └ 부모 grid columns = {o["parentCols"]} '
                                  f'· min-width={o["minWidth"]}')
                page.close()
        browser.close()

    print(f"\n재 본 범위: 화면 {len(pages)} × 폭 {len(widths)} = {len(pages) * len(widths)}쪽")
    if overflows:
        print(f"넘친 곳 {len(overflows)}: " + " · ".join(overflows))
        return 1
    print("넘친 곳 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
