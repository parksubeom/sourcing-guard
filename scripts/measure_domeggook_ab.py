#!/usr/bin/env python
"""A-5. 같은 상품을 **상품명만** vs **도매꾹 API 상세 텍스트** 두 조건으로 잰다.

⚠ **매칭률 하나만 재지 않는다.** 오답이 같이 오르는지가 핵심이다. 상세를 넣어
  매칭이 늘어도 오답이 같이 늘면 그것은 개선이 아니다.

    품목 매칭 (정답 / 애매 / 오답 / 미매칭)
    kc_numbers · kc_numbers_from_image · rf_numbers
    target_age  → CHILD_CATCH_ALL 이 몇 건 켜지나
    materials   → 유해물질 규칙이 몇 건 걸리나
    신호등 분포  → 상세가 신호를 뒤집는가

⚠ **모든 숫자에 입력 조건을 함께 적는다.** 라벨:

    gpt · 단건 · 상세(도매꾹 API 정제 텍스트) · 분모 = 채택 대상 N/135

⚠ **"상세를 넣으면 X%" 라고 말하지 않는다.** 채택된 N건은 표본 전체가 아니고
  (사라진 것·복수 불일치가 빠졌다), 상세 텍스트는 상세페이지 DOM 이 아니라
  API 필드로 조립한 것이다. 말할 수 있는 것은 "채택 N건에서 상품명만 대비
  이렇게 움직였다" 까지다.

⚠ 벤더는 추측하지 않고 `/healthz` 의 `extraction.by_vendor` **증가분**으로
  확인한다 (CLAUDE.md R7: 출력 모양으로 추론하지 않는다).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")
_WRONG = Path("tests/fixtures/새표본235_오답.tsv")
_SECTION = re.compile(r"^=====\s*(\d+)\s*=====\s*$", re.M)


def split_details(path: Path) -> dict[int, str]:
    """'===== <번호> =====' 로 잘라 번호→본문. 주석 줄은 버린다."""
    out: dict[int, str] = {}
    cur: int | None = None
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _SECTION.match(line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = int(m.group(1)), []
            continue
        if line.startswith("#"):
            continue
        if cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return {k: v for k, v in out.items() if v}


def load_scope() -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for line in _SCOPE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        no, verdict, name, _why = line.split("\t")
        out[int(no)] = (verdict, name)
    return out


def load_reviewed() -> tuple[set[str], set[str]]:
    """오답·애매 절. `measure_detail_vs_name.py` 와 같은 규칙이다."""
    wrong: set[str] = set()
    vague: set[str] = set()
    section = None
    for line in _WRONG.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            if "--- 오답" in line:
                section = "wrong"
            elif "[애매]" in line:
                section = "vague"
            elif "[검수했고 정답]" in line or "[고쳐짐" in line:
                section = None
            continue
        if not line.strip() or section is None:
            continue
        (wrong if section == "wrong" else vague).add(line.split("\t")[0])
    return wrong, vague


def healthz(url: str) -> dict:
    out = subprocess.run(
        ["curl", "-s", "--max-time", "30", f"{url}/healthz"],
        capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except ValueError:
        return {}


class Pacer:
    """분당 한도를 지키면서 최대 속도로. 응답 지연도 간격에 포함한다."""

    def __init__(self, min_gap: float) -> None:
        self._gap = min_gap
        self._last = 0.0

    def wait(self) -> None:
        if self._last:
            left = self._gap - (time.monotonic() - self._last)
            if left > 0:
                time.sleep(left)
        self._last = time.monotonic()


def scan(url: str, text: str, pacer: Pacer) -> dict:
    """실패를 조용히 삼키지 않는다 - 429 를 '추출 실패' 로 읽으면 숫자가 뒤집힌다."""
    for attempt in (1, 2):
        pacer.wait()
        out = subprocess.run(
            ["curl", "-s", "--max-time", "240", "-w", "\n%{http_code}",
             "-X", "POST", f"{url}/api/v1/scan",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"page_text": text}, ensure_ascii=False)],
            capture_output=True, text=True).stdout
        body, _, code = out.rpartition("\n")
        code = code.strip()
        if code == "200":
            return json.loads(body)
        if code == "429" and attempt == 1:
            print("    429 - 60초 쉬고 한 번만 다시 칩니다", flush=True)
            time.sleep(60)
            continue
        raise RuntimeError(f"HTTP {code or '없음'} — {body[:160]}")
    raise RuntimeError("429 가 계속됩니다")


def tally(payload: dict) -> dict:
    facts = payload.get("facts") or {}
    items = [c["item"] for f in payload.get("findings", [])
             for c in (f.get("detail") or {}).get("candidates", [])]
    kinds = [f.get("kind") for f in payload.get("findings", [])]
    grades = [(f.get("detail") or {}).get("grade") for f in payload.get("findings", [])
              if f.get("kind") == "item_grade_matched"]
    return {
        "matched": bool(items),
        "items": items,
        "grades": [g for g in grades if g],
        "legal_item_name": facts.get("legal_item_name"),
        "category": facts.get("category"),
        "kc": len(facts.get("kc_numbers") or []),
        "kc_img": len(facts.get("kc_numbers_from_image") or []),
        "rf": len(facts.get("rf_numbers") or []),
        "age": bool(facts.get("target_age")),
        "materials": len(facts.get("materials") or []),
        "catch_all": "child_catch_all" in kinds,
        "hazard": sum(1 for k in kinds if k == "hazard_rule_applies"),
        "signal": payload.get("signal"),
        "kinds": kinds,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://sourcing-guard.fly.dev")
    ap.add_argument("--detail",
                    default="tests/fixtures/도매꾹_상세텍스트_2026-09-08.txt")
    ap.add_argument("--gap", type=float, default=5.2,
                    help="요청 시작 간 최소 간격(초). /healthz limits.per_minute 를 볼 것")
    ap.add_argument("--scope", default="대상")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    details = split_details(Path(args.detail))
    scope = load_scope()
    wrong, vague = load_reviewed()

    rows_todo = [
        (no, scope[no][1], text) for no, text in sorted(details.items())
        if args.scope == "전체" or scope[no][0] == args.scope
    ]
    if args.limit:
        rows_todo = rows_todo[: args.limit]
    if not rows_todo:
        raise SystemExit("분모가 0 입니다")

    before = healthz(args.url)
    v0 = ((before.get("extraction") or {}).get("by_vendor") or {})
    limits = before.get("limits") or {}
    print(f"배포본 {args.url}")
    print(f"  extraction.order  {(before.get('extraction') or {}).get('order')}")
    print(f"  by_vendor (전)     {v0}")
    print(f"  limits            per_minute={limits.get('per_minute')}"
          f" · daily_llm_used={limits.get('daily_llm_used')}"
          f"/{limits.get('daily_llm_limit')}")
    need = len(rows_todo) * 2
    print(f"\n{len(rows_todo)}건 × 2조건 = LLM {need}회 · 간격 {args.gap}초"
          f" · 예상 {need * args.gap / 60:.0f}분\n", flush=True)

    pacer = Pacer(args.gap)
    rows: list[dict] = []
    started = time.time()
    for i, (no, name, detail) in enumerate(rows_todo, 1):
        try:
            by_name = scan(args.url, name, pacer)
            by_detail = scan(args.url, detail, pacer)
        except RuntimeError as exc:
            print(f"  [{no:3}] !! {exc}", flush=True)
            print(f"  진행 {i - 1}/{len(rows_todo)} 에서 멈춥니다.", flush=True)
            break
        rows.append({"no": no, "name": name, "detail_chars": len(detail),
                     "name_only": by_name, "detail": by_detail})
        a, b = tally(by_name), tally(by_detail)
        flip = "" if a["signal"] == b["signal"] else f" 신호 {a['signal']}→{b['signal']}"
        print(f"  [{i:3}/{len(rows_todo)}] no={no:<4} "
              f"{'명O' if a['matched'] else '명X'} → "
              f"{'상O' if b['matched'] else '상X'}"
              f" · kc {a['kc']}→{b['kc']}{flip}  {name[:32]}", flush=True)

    after = healthz(args.url)
    v1 = ((after.get("extraction") or {}).get("by_vendor") or {})
    delta = {k: v1.get(k, 0) - v0.get(k, 0) for k in set(v0) | set(v1)}
    delta = {k: v for k, v in delta.items() if v}

    n = len(rows)
    if not n:
        raise SystemExit("측정된 건이 없습니다")

    print(f"\n{'=' * 74}")
    print("A-5 · 상품명만 vs 상세(도매꾹 API 정제 텍스트)")
    print(f"  라벨  gpt · 단건 · 상세(도매꾹 API 정제 텍스트)"
          f" · 분모 = 채택 대상 {n}/135")
    print(f"  by_vendor 증가분  {delta}   ← 어느 벤더가 뽑았는지 (R7)")
    print(f"{'=' * 74}")

    for cond, label in (("name_only", "상품명만"), ("detail", "상세 전체")):
        t = [tally(r[cond]) for r in rows]
        ok = sum(1 for r, x in zip(rows, t)
                 if x["matched"] and r["name"] not in wrong and r["name"] not in vague)
        amb = sum(1 for r, x in zip(rows, t) if x["matched"] and r["name"] in vague)
        bad = sum(1 for r, x in zip(rows, t) if x["matched"] and r["name"] in wrong)
        sig: dict[str, int] = {}
        for x in t:
            sig[str(x["signal"])] = sig.get(str(x["signal"]), 0) + 1
        print(f"\n[{label}]  n={n}")
        print(f"  품목 매칭    정답 {ok} · 애매 {amb} · 오답 {bad}"
              f" · 미매칭 {n - ok - amb - bad}")
        print(f"  kc_numbers   {sum(1 for x in t if x['kc'])}건"
              f"  (이미지 {sum(1 for x in t if x['kc_img'])}"
              f" · 전파 {sum(1 for x in t if x['rf'])})")
        print(f"  target_age   {sum(1 for x in t if x['age'])}건"
              f"  → CHILD_CATCH_ALL {sum(1 for x in t if x['catch_all'])}건")
        print(f"  materials    {sum(1 for x in t if x['materials'])}건"
              f"  → 유해물질 규칙 {sum(x['hazard'] for x in t)}건")
        print(f"  신호등       {sig}")

    print("\n── 상세로 새로 걸린 것 (오답인지 눈으로 볼 것) ──")
    for r in rows:
        a, b = tally(r["name_only"]), tally(r["detail"])
        if b["matched"] and not a["matched"]:
            print(f"  [{r['no']}] {r['name'][:50]}\n        → {b['items']}")
    print("── 상세로 없어진 것 ──")
    for r in rows:
        a, b = tally(r["name_only"]), tally(r["detail"])
        if a["matched"] and not b["matched"]:
            print(f"  [{r['no']}] {r['name'][:50]}  {a['items']} → 없음")
    print("── 신호가 뒤집힌 것 ──")
    for r in rows:
        a, b = tally(r["name_only"]), tally(r["detail"])
        if a["signal"] != b["signal"]:
            print(f"  [{r['no']}] {a['signal']} → {b['signal']}"
                  f"  kc {a['kc']}→{b['kc']}  {r['name'][:38]}")

    print(f"\n  걸린 시간 {time.time() - started:.0f}초")
    print("\n⚠ 이 숫자로 \"상세를 넣으면 X%\" 라고 말하지 않는다. 채택 "
          f"{n}건은 표본 전체가 아니고, 상세 텍스트는 상세페이지 DOM 이 아니라 "
          "API 필드로 조립한 것이다.")

    if args.out:
        Path(args.out).write_text(
            json.dumps({
                "라벨": f"gpt · 단건 · 상세(도매꾹 API 정제 텍스트) · 분모 = 채택 대상 {n}/135",
                "잰날": f"{date.today():%Y-%m-%d}",
                "배포본": args.url,
                "extraction_order": (before.get("extraction") or {}).get("order"),
                "by_vendor_증가분": delta,
                "행": rows,
            }, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
