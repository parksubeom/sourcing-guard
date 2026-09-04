#!/usr/bin/env python3
"""단건 경로 매칭률을 잰다. 배치와 다를 수 있다.

두 경로가 매처에 넘기는 것이 다르다.

    배치   상품명 원본을 그대로 넘긴다 (LLM 을 안 쓴다)
    단건   LLM 이 정리한 product_name 을 넘긴다

LLM 이 연관 검색어를 정리하는 것은 제품명을 정확히 뽑으려는 것인데,
매칭에는 손해일 수 있다 - 도매 상품명의 연관 검색어가 품목 정보를 담고
있기 때문이다("의자방석" 의 '의자').

⚠ LLM 을 부르므로 일일 상한을 쓴다. 30건이면 상한 500회의 6% 다.
  239건 전부를 돌리지 않는 이유가 이것이고, 차이가 크면 그때 늘린다.

    PYTHONPATH=. python scripts/measure_single_path.py --n 30
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import time

from sourcing_guard.item_grades import ItemGradeBook

_SAMPLE = pathlib.Path("tests/fixtures/도매꾹239.txt")


def scan(url: str, text: str) -> dict:
    """한 건을 스캔한다. 실패를 조용히 삼키지 않는다.

    ⚠ 처음에 실패를 빈 dict 로 돌려줬더니 **429(분당 12회 상한)를 "LLM 이
      상품명을 못 뽑았다" 로 잘못 읽었다.** 단건 매칭률이 47% 로 나왔는데
      실제로는 응답을 못 받은 것이었다. 측정 도구가 조용히 실패하면 그
      숫자가 결론이 된다.
    """
    out = subprocess.run(
        ["curl", "-s", "--max-time", "120", "-w", "\n%{http_code}",
         "-X", "POST", f"{url}/api/v1/scan",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"page_text": text}, ensure_ascii=False)],
        capture_output=True, text=True,
    ).stdout
    body, _, code = out.rpartition("\n")
    if code.strip() != "200":
        raise RuntimeError(f"HTTP {code.strip() or '없음'} — {body[:120]}")
    return json.loads(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--url", default="https://sourcing-guard.fly.dev")
    ap.add_argument("--gap", type=float, default=5.5,
                    help="요청 간격(초). 분당 12회 상한을 넘지 않게 한다")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    names = [
        n.strip() for n in _SAMPLE.read_text(encoding="utf-8").splitlines() if n.strip()
    ]
    step = max(1, len(names) // args.n)
    pick = names[::step][: args.n]

    book = ItemGradeBook()
    rows = []
    # 분당 상한(healthz 의 limits.per_minute)에 걸리지 않게 간격을 둔다.
    # 상한을 넘기면 429 가 오고, 그것을 매칭 실패로 읽으면 숫자가 뒤집힌다.
    for i, raw in enumerate(pick):
        if i:
            time.sleep(args.gap)
        got = scan(args.url, raw)
        facts = got.get("facts") or {}
        cleaned = facts.get("product_name") or ""
        rows.append({
            "raw": raw,
            "cleaned": cleaned,
            "category": facts.get("category"),
            "batch": [g.item for g in book.lookup_all(raw)],
            "single": [g.item for g in book.lookup_all(cleaned)],
        })

    n = len(rows)
    b_hit = sum(1 for r in rows if r["batch"])
    s_hit = sum(1 for r in rows if r["single"])
    lost = [r for r in rows if r["batch"] and not r["single"]]
    gained = [r for r in rows if r["single"] and not r["batch"]]
    changed = [r for r in rows if r["batch"] and r["single"] and r["batch"] != r["single"]]

    print(f"표본 {n}건 (239건에서 {step}건마다)\n")
    print(f"  배치 경로 (상품명 원본)      {b_hit:3}/{n} = {b_hit / n * 100:.0f}%")
    print(f"  단건 경로 (LLM 정리본)       {s_hit:3}/{n} = {s_hit / n * 100:.0f}%")
    print(f"\n  단건에서 잃은 것  {len(lost)}건")
    print(f"  단건에서 얻은 것  {len(gained)}건")
    print(f"  후보가 달라진 것  {len(changed)}건")

    for label, group in (("잃음", lost), ("얻음", gained), ("달라짐", changed)):
        if not group:
            continue
        print(f"\n── {label} ──")
        for r in group:
            print(f"  {r['raw'][:56]}")
            print(f"     LLM → {r['cleaned'][:56]!r}  ({r['category']})")
            print(f"     배치 {r['batch'][:3]}  단건 {r['single'][:3]}")

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
