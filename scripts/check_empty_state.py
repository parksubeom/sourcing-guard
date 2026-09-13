#!/usr/bin/env python
"""값이 없을 때 화면이 **거짓말하지 않는지** 잰다.

    python scripts/check_empty_state.py --base http://127.0.0.1:8765

왜 필요한가
-----------
2026-09-13 에 랜딩에서 잡혔다. `/healthz` 의 `sync` 가 비어 있으면 이렇게 나왔다:

    "이미 리콜 공표된 0건과 모델명·인증번호를 대조합니다. - 공표분까지."

`num(0)` 이 문자열 `"0"` 이라 참이 됐고, 없는 값을 `"-"` 로 채우는 규칙이
문장 가운데에서 쓰레기가 됐다. **배포본은 부팅 직후 초기 적재 전 몇 초와 정부
API 장애 때 이 화면이 뜬다** - 드문 상태가 아니라 매 배포마다 지나는 상태다.

이 스크립트는 서버 응답을 **비우거나 깨뜨려서** 네 화면을 그리고, 화면에 남은
글자에서 쓰레기 자국을 찾는다. 한 곳을 고치는 것이 아니라 **그 종류를** 본다.

⚠ "없는 값을 어떻게 그리나" 의 정답은 셋 중 하나다:
    ① 그 절을 통째로 숨긴다 (문장이 여전히 참이어야 한다)
    ② 숫자 없이도 말이 되는 낱말로 둔다 ("목록")
    ③ 무엇을 못 했는지 적는다 ("조회 실패")
  "-" 를 문장에 박는 것은 셋 중 어느 것도 아니다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

PAGES = ("/", "/scan", "/batch", "/watch")

#: 화면 글자에 남으면 안 되는 자국. 값이 없을 때 코드가 흘린 흔적들이다.
GARBAGE = (
    (r"undefined", "undefined 가 화면에 있다"),
    (r"\bnull\b", "null 이 화면에 있다"),
    (r"\bNaN\b", "NaN 이 화면에 있다"),
    (r"\[object Object\]", "객체가 그대로 찍혔다"),
    (r"(?<![\d\w])-\s*(공표분|건|개|%|일|시)", "빈 값('-')이 단위 앞에 박혔다"),
    (r"(검수한|공표된|공표)\s*-\s*건", "빈 값('-')이 문장 가운데 있다"),
    (r"-%", "빈 값('-')에 % 가 붙었다"),
    (r"^\s*-\s*$", "값 없이 '-' 만 남은 칸"),
)

#: 값이 0/빈 목록일 때 **말이 되는지** 따로 본다. 0 은 쓰레기가 아니지만
#: "0건과 대조합니다" 처럼 **문장을 거짓으로 만드는** 자리가 있다.
#
#: ⚠ **앞자리를 막는다.** 처음에 `0건과` 로 썼더니 "37,350건과" 의 꼬리에
#:   걸려 정상 화면을 결함으로 읽었다. 가드가 스스로 오탐하면 아무도 안 본다.
ZERO_LIES = (
    (r"(?<![\d,])0\s*건과\s*모델명", "리콜 0건인데 '대조합니다' 라고 한다"),
    (r"공표된\s*(?<![\d,])0\s*건", "리콜 0건인데 '공표된' 이라고 한다"),
)

#: 서버 응답을 어떻게 망가뜨릴지. 각 경우가 실제로 일어나는 상태다.
CASES = {
    "healthz 빈 응답": {"**/healthz*": {}},
    "healthz sync 없음": {"**/healthz*": {"ok": True}},
    "healthz 리콜 0건": {"**/healthz*": {"ok": True, "sync": {"recalls": {"domestic": 0, "overseas": 0}, "latest_published_on": None}}},
    "healthz baseline 없음": {"**/healthz*": {"ok": True, "sync": {"recalls": {"domestic": 4245, "overseas": 33105}, "latest_published_on": "20260908"}}},
    "demos 빈 응답": {"**/api/v1/demos*": {"items": [], "preview": None}},
    "watch 빈 목록": {"**/api/v1/watch?*": {"items": [], "sweep": {}, "alerts": []}},
    "보도자료 없음": {"**/안전성조사_보도자료.json*": None},
}


#: ── 2단계: **값이 있는 화면**을 깨뜨린다 ────────────────────────────
#:
#: 1단계는 화면을 열기만 한다. 그러나 값을 문장에 끼워 넣는 코드는 대부분
#: **결과를 그릴 때** 돈다 - 스캔 결과 카드 · 감시 목록 항목 · 대량 검사 표.
#: 서버가 필드를 덜 준 응답을 흘려 그 자리를 지나가게 한다.
#:
#: ⚠ 지어낸 모양이 아니다. 전부 실제로 일어난다 - LLM 폴백이면 `meta` 가
#:   얇아지고, 조회 실패면 `axes` 가 "조회 실패" 가 되고, 감시 항목은
#:   모델명·제조사 중 하나만 있어도 등록된다.
_SCAN_BARE = {
    "signal": "UNKNOWN", "headline": "판단 보류", "score": 0,
    "findings": [], "axes": [], "grouped_findings": [],
    "facts": {}, "meta": {}, "disclaimer": "",
}
_SCAN_THIN_FINDING = {
    "signal": "AMBER", "headline": "확인 후 소싱 — 공급처에 아래 항목을 확인한 뒤 판단하세요.",
    "score": 40,
    "axes": [{"key": "cert", "name": "인증 조회", "label": "조회 실패", "done": False, "note": ""},
             {"key": "recall", "name": "리콜 대조", "label": "대조 못 함", "done": False, "note": ""},
             {"key": "hazard", "name": "유해물질", "label": "이 품목 미수록", "done": False, "note": ""}],
    "findings": [{"kind": "info_request", "signal": "UNKNOWN",
                  "statement_ko": "재질 표기를 확인해 주세요.",
                  "source_url": "https://www.law.go.kr/", "source_label": "국가법령정보센터",
                  "detail": None}],
    "grouped_findings": [], "facts": {}, "meta": {}, "disclaimer": "",
}
_WATCH_THIN = {
    "items": [{"id": "x1", "owner_id": "o", "product_name": None, "model_name": None,
               "maker": None, "kc_numbers": [], "registered_at": None,
               "last_swept_at": None, "seen_recall_fingerprints": [], "status": "active"}],
    "sweep": {}, "alerts": [],
}

#: 마지막 값은 **그려졌다는 증거**다. 없으면 이 검사는 빈 화면을 보고 통과한다 -
#: 이 저장소에서 "비어 있어서 통과하는 검사" 를 여러 번 겪었다.
ACT_CASES = {
    "스캔 결과가 비었다": ("/scan?demo=amber", {"**/api/v1/scan": _SCAN_BARE}, ".rv-head"),
    "스캔 결과의 필드가 얇다": ("/scan?demo=amber", {"**/api/v1/scan": _SCAN_THIN_FINDING}, ".rv-head"),
    "감시 항목에 단서가 없다": ("/watch", {"**/api/v1/watch?*": _WATCH_THIN}, ".items li.item"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--width", type=int, default=1440)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    bad: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        try:
            for case, stubs in CASES.items():
                for path in PAGES:
                    page = browser.new_page(viewport={"width": args.width, "height": 900})

                    def make(body):
                        def handler(route):
                            if body is None:
                                route.fulfill(status=404, body="")
                            else:
                                route.fulfill(status=200, content_type="application/json",
                                              body=json.dumps(body, ensure_ascii=False))
                        return handler

                    for pattern, body in stubs.items():
                        page.route(pattern, make(body))

                    errors: list[str] = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto(args.base + path, wait_until="networkidle", timeout=60_000)
                    page.wait_for_timeout(700)

                    # ⚠ **문장 단위로 모은다.** 처음에 텍스트 노드를 하나씩
                    #   모았더니 "이미 리콜 공표된 " / "0건" / "과 모델명…" 으로
                    #   쪼개져 **문장을 거짓으로 만드는 자리를 못 봤다.**
                    #   `innerText` 는 화면에 보이는 대로(숨은 것 제외) 줄을 준다.
                    text = page.evaluate(
                        "() => document.body.innerText.split('\\n')"
                        ".map(s => s.replace(/\\s+/g, ' ').trim()).filter(Boolean)")

                    tag = f"[{case}] {path}"
                    for line in text:
                        for pat, why in GARBAGE + ZERO_LIES:
                            if re.search(pat, line):
                                bad.append(f"{tag} {why}: {line[:70]!r}")
                    for e in errors:
                        bad.append(f"{tag} 자바스크립트 오류: {e[:90]}")
                    page.close()
                print(f"  [{case}] 네 화면 검사 완료")

            # ── 2단계: 결과가 그려지는 화면 ──────────────────────────
            for case, (path, stubs, proof) in ACT_CASES.items():
                page = browser.new_page(viewport={"width": args.width, "height": 900})

                def make2(body):
                    def handler(route):
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps(body, ensure_ascii=False))
                    return handler

                for pattern, body in stubs.items():
                    page.route(pattern, make2(body))
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(args.base + path, wait_until="networkidle", timeout=60_000)
                page.wait_for_timeout(2500)
                text = page.evaluate(
                    "() => document.body.innerText.split('\\n')"
                    ".map(s => s.replace(/\\s+/g, ' ').trim()).filter(Boolean)")
                tag = f"[{case}] {path}"
                if not page.query_selector(proof):
                    bad.append(f"{tag} 결과가 안 그려졌다({proof}) - 이 경우는 "
                               "아무것도 재지 않았다")
                for line in text:
                    for pat, why in GARBAGE + ZERO_LIES:
                        if re.search(pat, line):
                            bad.append(f"{tag} {why}: {line[:70]!r}")
                for e in errors:
                    bad.append(f"{tag} 자바스크립트 오류: {e[:90]}")
                page.close()
                print(f"  [{case}] 검사 완료")
        finally:
            browser.close()

    print()
    if bad:
        print("빈 값에서 화면이 깨진다:")
        seen = set()
        for b in bad:
            if b in seen:
                continue
            seen.add(b)
            print("  -", b)
        return 1
    print("빈 값에서도 화면이 거짓말하지 않는다 "
          "(열기 %d경우 × 화면 %d · 결과 %d경우)"
          % (len(CASES), len(PAGES), len(ACT_CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
