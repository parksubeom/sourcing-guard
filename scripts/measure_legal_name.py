#!/usr/bin/env python3
"""LLM 이 옮긴 법령 품목명이 매칭을 얼마나 올리는지 잰다.

손으로 만든 별칭이 한계에 왔다 - 튜닝 표본 71%, 새 표본 24%. 별칭이 첫
표본에서 만들어졌으니 새 상품에는 안 통한다. 문제가 문자열이 아니라 의미다.

그래서 LLM 을 번역기로 쓴다. **561건 목록에서 고르게 하지 않는다** - 그러면
LED등기구 같은 그럴듯한 오답이 나온다. 이름만 자연스럽게 답하게 하고 표가
검증한다. 등급은 표에서 결정론적으로 읽으므로 LLM 이 등급을 지어낼 수 없다.

재는 것 셋:
  ① 규칙만으로 (지금)      새 표본 24%
  ② 법령 품목명을 더하면   몇 %로 오르나
  ③ **오답**               LLM 이 지어낸 이름이 표에 우연히 걸리나

③이 핵심이다. 매칭률만 오르고 오답이 함께 늘면 얻는 것이 없다.

    PYTHONPATH=. python scripts/measure_legal_name.py --n 30
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import time

from sourcing_guard.item_grades import ItemGradeBook, normalize

_SAMPLE = pathlib.Path("tests/fixtures/새표본235.txt")


def scan(url: str, text: str) -> dict:
    """실패를 조용히 삼키지 않는다 - 429 를 매칭 실패로 읽으면 숫자가 뒤집힌다."""
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
    ap.add_argument("--gap", type=float, default=5.5)
    ap.add_argument("--sample", default=str(_SAMPLE))
    ap.add_argument("--out", default="")
    # 저장된 LLM 응답으로 다시 재는 경로. 30건이 일일 상한의 6% 라,
    # 매칭 규칙만 바꿔 보고 싶을 때 다시 부르면 예산이 아깝다.
    ap.add_argument("--replay", default="",
                    help="저장된 원자료(json)로 재계산. LLM 을 부르지 않는다")
    args = ap.parse_args()

    names = [
        n.strip()
        for n in pathlib.Path(args.sample).read_text(encoding="utf-8").splitlines()
        if n.strip()
    ]
    step = max(1, len(names) // args.n)
    pick = names[::step][: args.n]

    book = ItemGradeBook()

    if args.replay:
        saved = json.loads(pathlib.Path(args.replay).read_text(encoding="utf-8"))
        pairs = [(r["raw"], r.get("legal")) for r in saved]
    else:
        pairs = [(raw, None) for raw in pick]

    rows = []
    for i, (raw, legal) in enumerate(pairs):
        if not args.replay:
            if i:
                time.sleep(args.gap)
            got = scan(args.url, raw)
            facts = got.get("facts") or {}
            legal = facts.get("legal_item_name")
        else:
            facts = {"product_name": None, "category": None}
        by_rule = [g.item for g in book.lookup_all(raw)]
        by_legal = [
            row["item"] for row in (book._by_name.get(normalize(legal or "")) or ())
        ]
        rows.append({
            "raw": raw,
            "product_name": facts.get("product_name"),
            "legal": legal,
            "category": facts.get("category"),
            "by_rule": by_rule,
            "by_legal": by_legal,
        })

    n = len(rows)
    rule_hit = sum(1 for r in rows if r["by_rule"])
    both_hit = sum(1 for r in rows if r["by_rule"] or r["by_legal"])
    new_only = [r for r in rows if r["by_legal"] and not r["by_rule"]]
    named = [r for r in rows if r["legal"]]
    named_missed = [r for r in named if not r["by_legal"]]

    print(f"새 표본 {n}건 (235건에서 {step}건마다)\n")
    print(f"  ① 규칙만          {rule_hit:3}/{n} = {rule_hit / n * 100:.0f}%")
    print(f"  ② 법령 품목명 추가  {both_hit:3}/{n} = {both_hit / n * 100:.0f}%"
          f"   (+{both_hit - rule_hit}건)")
    print()
    print(f"  LLM 이 이름을 답한 것        {len(named):3}/{n}")
    print(f"    그중 표에 있던 것          {len(named) - len(named_missed):3}")
    print(f"    표에 없어 버려진 것        {len(named_missed):3}  ← 표가 걸러낸다")

    print(f"\n── 새로 걸린 {len(new_only)}건 (오답인지 눈으로 볼 것) ──")
    for r in new_only:
        print(f"  {r['raw'][:62]}")
        print(f"     LLM '{r['legal']}' → {r['by_legal']}")

    if named_missed:
        print(f"\n── 표에 없어 버려진 이름 {len(named_missed)}건 ──")
        for r in named_missed:
            print(f"  '{r['legal']}'  ← {r['raw'][:52]}")

    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
