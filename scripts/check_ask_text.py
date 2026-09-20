"""공급처 문안이 **서버가 낸 문장만** 담고 있는지 브라우저로 확인한다.

왜 스크립트인가
---------------
`askText` 는 브라우저 안에서 도는 JS 다. 소스 단정(`tests/test_frontend.py`)은
"인용하게 짜여 있는가" 까지만 말하고 **"실제로 인용했는가" 는 못 말한다** -
`test_hazard_rules_are_collapsed` 가 "접히게 돼 있다" 까지만 말했던 것과 같다.

여기서는 진짜 DOM 을 읽어 문안의 **모든 줄**을 응답과 대조한다.

⚠ `playwright` 는 `requirements.txt` 에 없다. 검사에 쓰지 않으므로 코드만 볼
  때는 필요 없다 (`scripts/measure_widths.py` 와 같은 자리).

⚠⚠ **LLM 을 부르지 않는다.** `/api/v1/scan` 을 가로채 기록본
  (`data/experience_samples.json`)을 돌려준다 - 같은 입력에 같은 결과가 나오게
  해서, 문안이 흔들리는 것이 아니라 **틀린 것**을 잡는다 (미완 §1-q).

쓰는 법
-------
    PYTHONUTF8=1 MOCK_MODE=true python -m uvicorn sourcing_guard.main:app --port 8011
    PYTHONUTF8=1 PYTHONPATH=. python -u scripts/check_ask_text.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ROOT = Path(__file__).resolve().parents[1]
_SAMPLES = _ROOT / "sourcing_guard" / "data" / "experience_samples.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8011")
    ap.add_argument("--sample", default="CB063R10777-3001")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 가 없다: pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 2

    raw = json.loads(_SAMPLES.read_text(encoding="utf-8"))
    item = next((i for i in raw["items"] if i["cert_number"] == args.sample), None)
    if item is None:
        print(f"기록본에 {args.sample} 이 없다", file=sys.stderr)
        return 2
    result = item["result"]
    findings = result["findings"]

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1200})
        page.route("**/api/v1/scan", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(result, ensure_ascii=False)))
        page.goto(args.base + "/scan", wait_until="networkidle")
        page.fill("#pt", item["text"])
        page.click("#go")
        page.wait_for_selector("#ask-text", state="attached", timeout=60000)
        text = page.eval_on_selector("#ask-text", "e => e.textContent")
        browser.close()

    said = {f["statement_ko"] for f in findings}
    urls = {f["source_url"] for f in findings if f.get("source_url")}
    problems: list[str] = []

    # ① 모든 인용 줄이 실제 문장인가.
    quoted = 0
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        body = line[2:]
        if body.startswith("적용되는 유해물질 기준 "):
            continue                      # 유해물질 묶음 머리말
        if body in said:
            quoted += 1
        else:
            problems.append(f"응답에 없는 문장: {body[:70]}")

    # ② 모든 근거 URL 이 실제 근거인가.
    for line in text.splitlines():
        if "근거:" not in line:
            continue
        url = line.rsplit(" ", 1)[-1].strip()
        if url not in urls:
            problems.append(f"응답에 없는 근거 URL: {url}")

    # ③ 물질이 **제 조항에만** 붙었는가.
    by_basis: dict[str, set[str]] = {}
    for f in findings:
        if f["kind"] != "hazard_rule_applies":
            continue
        d = f.get("detail") or {}
        if not d.get("substance"):
            continue
        v = d.get("limit_value")
        unit = d.get("unit") or ""
        label = d["substance"] + (f" {v}{unit}" if v == 0 or v else "")
        by_basis.setdefault(f.get("legal_basis") or "", set()).add(label)

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("  · "):
            continue
        basis = line[4:].strip()
        if basis not in by_basis:
            problems.append(f"응답에 없는 근거 조항: {basis[:60]}")
            continue
        listed = set()
        if i + 1 < len(lines) and lines[i + 1].startswith("    "):
            listed = {t.strip() for t in lines[i + 1].strip().split(",") if t.strip()}
        wrong = listed - by_basis[basis]
        missing = by_basis[basis] - listed
        if wrong:
            problems.append(f"{basis[:40]} 에 남의 물질이 붙었다: {sorted(wrong)}")
        if missing:
            problems.append(f"{basis[:40]} 에서 빠진 물질: {sorted(missing)}")

    # ④ 화면에 있는 §9 고정 문구가 들어 있는가.
    #
    # ⚠ 이 글은 우리 화면을 떠나 **공급처에게 간다.** 화면에서는 카드 아래
    #   고정 문구가 있지만 복사본에는 안 따라간다 - 셀러의 주장으로 읽히는
    #   글에서 빠지면 §9 가 막으려던 바로 그 자리다.
    if result.get("disclaimer") and result["disclaimer"] not in text:
        problems.append("§9 고정 문구가 문안에 없다")

    # ⑤ **완전 검사** - 틀 문자열 말고 서버가 안 준 문장이 하나도 없는가.
    #
    # ⚠⚠ ①~③ 은 "인용한 줄이 진짜인가" 만 본다. 이것은 반대로 **모든 줄**을
    #   분류해서, 어느 쪽에도 안 들어가는 줄이 있으면 실패한다. 우리가 문장을
    #   지어내면 여기서 걸린다 - 그게 §3 설계의 전부다.
    frame = {
        "아래는 공개된 정부 데이터에서 확인한 내용입니다.",
        "확인이 필요한 항목의 서류를 보내 주실 수 있을까요?",
    }
    bases = set(by_basis)
    subs = set()
    for v in by_basis.values():
        subs |= v
    for line in text.splitlines():
        t = line.strip()
        if not t or t in frame:
            continue
        if t.endswith("사입을 검토 중입니다."):          # 틀 - 상품명 + 고정 꼬리
            continue
        if t.startswith("- ") and (t[2:] in said or
                                   t[2:].startswith("적용되는 유해물질 기준 ")):
            continue
        if t.startswith("근거:"):
            continue
        if t.startswith("· ") and t[2:] in bases:
            continue
        if all(x.strip() in subs for x in t.split(",") if x.strip()):
            continue                                    # 물질 목록 줄
        if t.startswith("(안심 소싱 돋보기 ") and t.endswith("검사)"):
            continue
        if t == (result.get("disclaimer") or ""):
            continue
        problems.append(f"어디서 왔는지 모르는 줄: {t[:70]}")

    # ⑥ 물질이 **한 줄인가 열네 줄인가** - 길이를 줄일 자리가 있는지 (총괄 질문)
    sub_lines = [ln for ln in text.splitlines()
                 if ln.startswith("    ") and ln.strip()]
    print(f"물질 줄 {len(sub_lines)}개 · 물질 {len(subs)}종 "
          f"→ {'한 줄로 모임' if len(sub_lines) < len(subs) else '물질마다 한 줄'}")

    # ⑦ **복사가 막혔을 때 텍스트가 실제로 뜨는가.**
    #
    # ⚠⚠ 이것은 "잴 것이 없는 설계" 가 아니다. 두 가지가 섞여 있었다:
    #     (가) iOS 사파리가 readonly 를 프로그램으로 선택해 주는가
    #          → 우리가 선택을 안 하기로 해서 **질문 자체가 없어졌다**
    #     (나) 클립보드가 없을 때 텍스트가 뜨는가
    #          → 이건 그냥 **안 재 본 것**이다. 헤드리스에서 잰다
    #
    # ⚠ 안 재면 이런 화면이 가능하다 - 버튼을 눌렀는데 아무 일도 안 일어나고
    #   문안도 안 뜬다. **버튼이 거짓말을 하는 것**이다.
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1200})
        page.add_init_script(
            "Object.defineProperty(navigator, 'clipboard', {value: undefined});")
        page.route("**/api/v1/scan", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(result, ensure_ascii=False)))
        page.goto(args.base + "/scan", wait_until="networkidle")
        page.fill("#pt", item["text"])
        page.click("#go")
        page.wait_for_selector("#ask-copy", timeout=60000)
        had_api = page.evaluate("() => !!(navigator.clipboard && navigator.clipboard.writeText)")
        page.click("#ask-copy")
        page.wait_for_timeout(300)
        shown = page.eval_on_selector("#ask-text", "e => e.offsetParent !== null")
        hint = page.eval_on_selector("#ask-hint", "e => e.offsetParent !== null")
        label = page.eval_on_selector("#ask-copy", "e => e.textContent.trim()")
        body = page.eval_on_selector("#ask-text", "e => e.textContent")
        browser.close()

    print(f"클립보드 없음 상태  API 있음 {had_api} · 문안 보임 {shown} · "
          f"안내 보임 {hint} · 버튼 '{label}'")
    if had_api:
        problems.append("클립보드를 못 없앴다 - 이 확인은 무효다")
    if not shown:
        problems.append("복사가 막혔는데 문안이 안 뜬다 - 버튼이 아무 일도 안 한다")
    if not hint:
        problems.append("복사가 막혔는데 안내가 안 뜬다")
    if body.strip() != text.strip():
        problems.append("펼친 문안이 복사 대상과 다르다")

    print(f"문안 {len(text.splitlines())}줄 · 인용된 문장 {quoted} / "
          f"응답 문장 {len(said)} · 근거 조항 {len(by_basis)}")
    if problems:
        print("\n문제:")
        for p in problems:
            print("  " + p)
        return 1
    print("문안의 모든 줄이 응답에서 왔다. 물질이 제 조항에만 붙었다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
