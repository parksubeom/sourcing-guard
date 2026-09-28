"""본선 시연 경로 점검 — 투표자·심사위원이 밟는 길을 그 순서대로 밟아 본다.

    python -u scripts/check_demo_path.py              ①②③⑥ 만 (실호출 0)
    python -u scripts/check_demo_path.py --live       ④⑤ 까지 (실호출 있음)

⚠⚠ **한 번 돌리면 실호출이 몇 번 나가나** (`--live` 일 때):

        ④ 체험표본 재검사   KC 번호 조회 1 + GPT 1
        ⑤ 입력창 검사       KC 번호 조회 1 + GPT 1
        ─────────────────────────────────────────
        합계                KC 2 · GPT 2      (총괄 승인 단위)

    전제는 **두 입력 모두 인증번호가 하나**라는 것이다. 번호가 둘인 입력을
    고르면 KC 가 조용히 4 가 된다 - 그래서 고른 이유를 `LIVE_*` 상수 옆에
    적어 두고, 스크립트가 **실제 소비량을 재서 찍는다**(`/healthz` 전/후 차).
    내 짐작이 아니라 잰 수를 보고한다.

    ①②③⑥ 은 실호출 0 이다 - 기록된 사본(`showcase.json`)과 `/healthz` 만 본다.

⚠ 실패하는 단계가 있어도 **나머지를 마저 돈다.** 한 번에 전체 그림을 보려고
  그렇게 했다 - 고치기 전에 전부 보고하기 위해서다 (총괄 지시 2026-09-28).

⚠ 단계마다 걸린 시간을 적는다. 본선장 회선이 느릴 수 있어 「되나」만큼
  「몇 초 걸리나」가 정보다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

BASE = "https://sourcing-guard.fly.dev"

#: ④ 가 다시 검사할 체험표본. **GREEN 을 고른다** - 조회가 죽으면 신호가
#: 내려가므로 이 표본이 가장 민감하다. 번호는 하나다(실측).
LIVE_SAMPLE = "CB063R10777-3001"
LIVE_SAMPLE_SIGNAL = "GREEN"

#: ⑤ 가 입력창에 넣을 글. **화면 placeholder 와 같은 문장**이다 - 투표자가
#: 실제로 따라 칠 가능성이 가장 높은 입력이고, 인증번호가 하나다.
LIVE_TEXT = (
    "유아용 블록 완구 · 모델명 BLK-100 · 재질 ABS · "
    "KC 인증번호 CB061R2170-3018 · 대상연령 3세 이상"
)

RESULT = ".rv-head"
SIGNALS = ("GREEN", "AMBER", "RED", "UNKNOWN")

fails: list[str] = []


def health(base: str) -> dict:
    with urllib.request.urlopen(base + "/healthz", timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def spent(before: dict, after: dict) -> tuple[int, int]:
    """이번 실행이 실제로 쓴 (KC 번호 조회, GPT) 횟수."""
    def cert(h):
        return ((h.get("kats") or {}).get("by_path") or {}).get("user_cert", {}).get("calls", 0)
    def gpt(h):
        return ((h.get("extraction") or {}).get("by_vendor") or {}).get("gpt", 0)
    return cert(after) - cert(before), gpt(after) - gpt(before)


@contextmanager
def step(no: str, name: str):
    print(f"[{no}] {name}", flush=True)
    t0 = time.time()
    try:
        yield
    except Exception as exc:                      # noqa: BLE001
        fails.append(f"{no} {name} — {type(exc).__name__}: {exc}")
        print(f"     ✗ 실패  {time.time() - t0:5.2f}초  {type(exc).__name__}: {exc}", flush=True)
    else:
        print(f"     ✓ {time.time() - t0:5.2f}초", flush=True)


def want(cond: bool, why: str) -> None:
    if not cond:
        raise AssertionError(why)


def signal_of(page) -> str:
    """결과 머리의 신호. 클래스에 그대로 박혀 있다 (`rv-head GREEN`)."""
    cls = page.eval_on_selector(RESULT, "el => el.className").split()
    got = [c for c in cls if c in SIGNALS]
    want(len(got) == 1, f"신호 클래스가 하나여야 하는데 {got} (class={cls})")
    return got[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--live", action="store_true",
                    help="④⑤ 를 실제로 돌린다 (KC 2 · GPT 2)")
    args = ap.parse_args()

    print(f"대상 {args.base} · {time.strftime('%FT%TZ', time.gmtime())}")
    print(f"실호출 {'예 — KC 2 · GPT 2 예상' if args.live else '아니오 (①②③⑥ 만)'}\n")

    before = health(args.base)
    print(f"시작 시점  user_cert {((before.get('kats') or {}).get('by_path') or {}).get('user_cert')}"
          f" · gpt {((before.get('extraction') or {}).get('by_vendor') or {}).get('gpt', 0)}\n")

    head = ""          # ③ 이 ② 에서 읽은 번호 앞자리를 쓴다

    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1280, "height": 900})

        # ── ① 첫 화면 · 다섯 숫자 ───────────────────────────────────────
        with step("①", "첫 화면이 뜬다 · 발표 숫자가 보인다"):
            resp = pg.goto(args.base + "/", wait_until="networkidle", timeout=60_000)
            want(resp is not None and resp.status == 200, f"HTTP {resp and resp.status}")
            b = (before.get("baseline") or {})
            # ⚠ 비율은 **서버가 준 글자**(`ok_rate_label`)와 맞춘다. 여기서
            #   숫자로 만들면 이 점검이 화면과 똑같은 실수를 하게 된다 -
            #   `f"{77.0}%"` 는 파이썬에선 "77.0%" 라 JS 의 결함을 못 본다.
            for hook, expect in (("ok_rate", b.get("ok_rate_label")),
                                 ("denominator", str(b.get("denominator"))),
                                 ("off_target", f"{b.get('off_target')}건")):
                got = pg.eval_on_selector(f'[data-h="{hook}"]', "el => el.textContent.trim()")
                want(got == expect, f"{hook}: 화면 {got!r} ≠ /healthz {expect!r}")
                print(f"     {hook:12s} {got}")

        # ── ② 도매꾹 카드 ───────────────────────────────────────────────
        with step("②", "도매꾹 카드 · did 줄 · 제목 줄맞춤"):
            pg.goto(args.base + "/scan", wait_until="networkidle", timeout=60_000)
            pg.wait_for_selector(".dg-card", timeout=30_000)
            cards = pg.eval_on_selector_all(".dg-list > li", "els => els.length")
            dids = pg.eval_on_selector_all(
                ".dg-did", "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")
            want(cards > 0, "카드가 0장이다")
            want(len(dids) == cards, f"카드 {cards}장인데 did 는 {len(dids)}장")
            # 제목이 늘 두 줄 자리를 차지한다 (min-height). 높이 가짓수가 하나여야 한다.
            hs = pg.eval_on_selector_all(
                ".dg-t", "els => [...new Set(els.map(e => Math.round("
                         "e.getBoundingClientRect().height)))]")
            want(len(hs) == 1, f"제목 높이가 갈린다: {sorted(hs)}px")
            print(f"     카드 {cards}장 · did {len(dids)}장 · 제목 높이 {hs[0]}px")
            head = dids[0].split("·")[-1].strip().rstrip("…")
            want(len(head) >= 4, f"카드에서 번호 앞자리를 못 읽었다: {dids[0]!r}")
            print(f"     첫 카드 {dids[0]}")

        # ── ③ 카드를 누르면 결과 · 근거가 그 번호를 가리킨다 ────────────
        with step("③", "카드 → 결과로 스크롤 · 신호 · 근거가 셀러 번호를 가리킨다"):
            pg.eval_on_selector(".dg-card", "el => el.click()")
            pg.wait_for_selector(RESULT, timeout=60_000)
            pg.wait_for_timeout(1200)                       # 부드러운 스크롤이 멎을 때까지
            y = pg.evaluate("() => Math.round(window.scrollY)")
            want(y > 200, f"결과로 안 내려갔다 (scrollY {y})")
            sig = signal_of(pg)
            lab = pg.eval_on_selector(".rv-lab", "el => el.textContent.trim()")
            hrefs = pg.eval_on_selector_all(
                'a.rv-src[href*="certNum="]', "els => els.map(e => e.href)")
            want(bool(hrefs), "근거 링크에 certNum 이 없다")
            nums = [h.split("certNum=")[1].split("&")[0] for h in hrefs]
            want(any(n.upper().startswith(head.upper()) for n in nums),
                 f"근거 번호 {nums} 가 카드가 말한 {head}… 로 시작하지 않는다")
            print(f"     scrollY {y} · 신호 {sig}({lab}) · 근거 certNum {nums[0]}")

        # ── ④ 체험표본을 지금 다시 검사 ─────────────────────────────────
        if args.live:
            with step("④", f"체험표본 {LIVE_SAMPLE} → 지금 다시 검사"):
                pg.goto(f"{args.base}/scan?sample={LIVE_SAMPLE}",
                        wait_until="networkidle", timeout=60_000)
                pg.wait_for_selector(RESULT, timeout=120_000)
                sig = signal_of(pg)
                want(sig == LIVE_SAMPLE_SIGNAL,
                     f"기록본은 {LIVE_SAMPLE_SIGNAL} 인데 지금 검사는 {sig}")
                print(f"     신호 {sig} — 기록본과 같다")
        else:
            print("[④] 건너뜀 (--live 아님)")

        # ── ⑤ 입력창에 직접 넣고 검사 ───────────────────────────────────
        if args.live:
            with step("⑤", "입력창에 알려진 상품 → 검사"):
                pg.goto(args.base + "/scan", wait_until="networkidle", timeout=60_000)
                pg.fill("#pt", LIVE_TEXT)
                pg.click("#go")
                pg.wait_for_selector(RESULT, timeout=120_000)
                sig = signal_of(pg)
                want(sig in SIGNALS, f"신호가 이상하다: {sig}")
                srcs = pg.eval_on_selector_all("a.rv-src", "els => els.length")
                want(srcs > 0, "근거 링크가 하나도 없다 (R2)")
                print(f"     신호 {sig} · 근거 링크 {srcs}개")
        else:
            print("[⑤] 건너뜀 (--live 아님)")

        br.close()

    # ── ⑥ /healthz ──────────────────────────────────────────────────────
    after = {}
    with step("⑥", "/healthz — retrying None · consec 0 · 오류 없음"):
        after = health(args.base)
        s, k = after.get("sync") or {}, after.get("kats") or {}
        want(s.get("retrying") is None, f"retrying {s.get('retrying')}")
        want(k.get("consecutive_failures") == 0, f"consec {k.get('consecutive_failures')}")
        want(not s.get("last_sync_error"), f"last_sync_error {s.get('last_sync_error')!r}")
        print(f"     build {(after.get('build') or {}).get('commit')} · syncs {s.get('syncs')}"
              f" · last_fetched {s.get('last_fetched')}")

    cert, gpt = spent(before, after or health(args.base))
    print(f"\n실제로 쓴 실호출 — KC 번호 조회 {cert} · GPT {gpt}"
          f"{'  (①②③⑥ 만 돌렸으므로 0 이어야 한다)' if not args.live else ''}")

    if fails:
        print(f"\n✗ 실패 {len(fails)}건")
        for f in fails:
            print(f"   {f}")
        return 1
    print("\n✓ 전 단계 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
