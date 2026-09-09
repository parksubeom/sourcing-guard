#!/usr/bin/env python3
"""[P] 단건 경로 전수 측정 — **발표 숫자다.**

배치 경로(상품명 목록 → 등급표 직접)와 단건 경로(상세페이지 → LLM 추출 →
등급표)는 다른 숫자를 낸다. 데모 3종과 발표 화면은 전부 단건이다.

  배치 경로 · 상품명만 · 대상 136 기준   69.9%   (측정됨)
  단건 경로 · 상품명만 · 대상 136 기준   ?       (이 스크립트)

⚠ 실패를 조용히 삼키지 않는다. 429 를 "매칭 실패" 로 읽으면 숫자가 뒤집힌다.
⚠ 새로 걸린 것은 눈으로 검수해야 한다. 이 스크립트는 목록만 낸다 - 판정은
  사람이 한다(1c6b2f4 에서 자수한 집계 결함).

비용: 136회 = 일일 상한 500 의 27%. 분당 12회 제한이라 간격 5.5초로 12분.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.item_grades import ItemGradeBook  # noqa: E402
from audit_tally import load_audit, load_scope, verdict  # noqa: E402

_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")
_WRONG = Path("tests/fixtures/새표본235_오답.tsv")


def scan(url: str, text: str, *, tries: int = 4) -> dict:
    """실패를 조용히 삼키지 않는다.

    ⚠ 429 만 재시도한다. 속도 제한은 **데이터 실패가 아니라 우리가 너무 빨리
      부른 것**이므로 기다렸다 다시 부르는 것이 맞다. 다른 코드는 즉시 던진다 -
      404·500 을 "매칭 실패" 로 읽으면 숫자가 뒤집힌다.
    """
    for attempt in range(tries):
        out = subprocess.run(
            ["curl", "-s", "--max-time", "180", "-w", "\n%{http_code}",
             "-X", "POST", f"{url}/api/v1/scan",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"page_text": text}, ensure_ascii=False)],
            capture_output=True, text=True).stdout
        body, _, code = out.rpartition("\n")
        code = code.strip()
        if code == "200":
            return json.loads(body)
        if code == "429" and attempt < tries - 1:
            wait = 20 * (attempt + 1)
            print(f"        429 - {wait}초 기다림 (재시도 {attempt + 1}/{tries - 1})")
            time.sleep(wait)
            continue
        raise RuntimeError(f"HTTP {code or '없음'} — {body[:160]}")
    raise RuntimeError("재시도를 다 썼다")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://sourcing-guard.fly.dev")
    ap.add_argument("--gap", type=float, default=6.5)  # 12/분 제한에 5.5 로는 걸렸다
    ap.add_argument("--limit", type=int, default=0, help="0이면 전부")
    # ⚠ 비대상·애매도 재야 한다. "우리는 비대상에 딱지를 붙이지 않는다" 가
    #   핵심 주장인데 발표 경로(단건)에서 미측정이면 그 주장을 못 쓴다.
    ap.add_argument("--scope", default="대상",
                    help="대상 | 비대상 | 애매 | 밖(비대상+애매) | 전부")
    ap.add_argument("--out", default="/tmp/kid/single_full.json")
    args = ap.parse_args()

    scope = {}
    for line in _SCOPE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        # ⚠ 지역 이름을 verdict 로 쓰면 위에서 import 한 함수를 가린다.
        no, sc, name, why = line.split("\t")
        scope[int(no)] = (sc, name, why)
    want = {"밖": {"비대상", "애매"}, "전부": {"대상", "비대상", "애매"}}.get(
        args.scope, {args.scope}
    )
    target = [(n, name) for n, (v, name, _w) in sorted(scope.items()) if v in want]
    if args.limit:
        target = target[: args.limit]

    book = ItemGradeBook()
    wrong, vague = load_audit()
    rows = []
    for i, (no, name) in enumerate(target):
        if i:
            time.sleep(args.gap)
        got = scan(args.url, name)
        facts = got.get("facts") or {}
        items = [
            c["item"] for f in got.get("findings", [])
            for c in (f.get("detail") or {}).get("candidates", [])
        ]
        batch = [g.item for g in book.lookup_all(name)]
        rows.append({
            "no": no, "name": name,
            "single": items, "batch": batch,
            "category": facts.get("category"),
            "product_name": facts.get("product_name"),
            "legal": facts.get("legal_item_name"),
            "signal": got.get("signal"),
        })
        mark = "=" if bool(items) == bool(batch) else ("단건만" if items else "배치만")
        print(f"  [{i+1:3}/{len(target)}] {no:3} {mark:6} {name[:44]}")

    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    n = len(rows)
    s_hit = [r for r in rows if r["single"]]
    b_hit = [r for r in rows if r["batch"]]
    # ⚠ 붙은 품목까지 본다 - 상품명만 보면 고쳐진 오답도 계속 오답으로 센다.
    s_bad = [r for r in s_hit if verdict(r["name"], r["single"], wrong, vague) == "wrong"]
    s_vag = [r for r in s_hit if verdict(r["name"], r["single"], wrong, vague) == "vague"]
    b_bad = [r for r in b_hit if verdict(r["name"], r["batch"], wrong, vague) == "wrong"]
    b_vag = [r for r in b_hit if verdict(r["name"], r["batch"], wrong, vague) == "vague"]
    print(f"\n{'='*70}")
    print(f"분모: 안전관리대상 {n}건")
    print(f"\n  배치 경로 · 상품명만   정답 {len(b_hit)-len(b_bad)-len(b_vag):3}"
          f" ({(len(b_hit)-len(b_bad)-len(b_vag))/n*100:5.1f}%) ·"
          f" 애매 {len(b_vag)} · 오답 {len(b_bad)} · 미매칭 {n-len(b_hit)}")
    print(f"  단건 경로 · 상품명만   정답 {len(s_hit)-len(s_bad)-len(s_vag):3}"
          f" ({(len(s_hit)-len(s_bad)-len(s_vag))/n*100:5.1f}%) ·"
          f" 애매 {len(s_vag)} · 오답 {len(s_bad)} · 미매칭 {n-len(s_hit)}")
    print("\n  ⚠ 단건 '정답' 은 배치 검수표를 재사용한 값이다. 단건에서만 걸린 것은")
    print("    아래 목록을 눈으로 검수해야 한다.")

    only_single = [r for r in rows if r["single"] and not r["batch"]]
    only_batch = [r for r in rows if r["batch"] and not r["single"]]
    diff_items = [r for r in rows if r["single"] and r["batch"]
                  and set(r["single"]) != set(r["batch"])]
    print(f"\n── 단건에서만 걸린 {len(only_single)}건 (눈 검수) ──")
    for r in only_single:
        print(f"  {r['no']:3} {r['name'][:52]}\n      cat={r['category']} legal={r['legal']!r}"
              f"\n      → {r['single']}")
    print(f"\n── 배치에서만 걸린 {len(only_batch)}건 (단건이 잃은 것) ──")
    for r in only_batch:
        print(f"  {r['no']:3} {r['name'][:52]}\n      cat={r['category']}"
              f" product_name={r['product_name']!r}\n      배치 → {r['batch']}")
    print(f"\n── 품목이 다른 {len(diff_items)}건 ──")
    for r in diff_items:
        print(f"  {r['no']:3} {r['name'][:46]}\n      배치 {r['batch']}\n      단건 {r['single']}")
    print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
