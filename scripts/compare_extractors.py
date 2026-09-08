#!/usr/bin/env python
"""저장된 Claude 추출과 GPT 추출을 같은 입력으로 대조한다.

왜 필요한가
-----------
발표 숫자(단건 정답률)는 **추출 결과를 입력으로** 한다. 추출기를 바꾸면
product_name·legal_item_name·category 세 필드가 달라지고, 그러면 그 숫자가
무효가 된다 (CLAUDE.md R7).

그래서 벤더를 바꿀 때는 (1) 세 필드가 얼마나 일치하는지, (2) 등급표 조회
결과가 실제로 달라지는지를 함께 본다. 필드가 달라도 등급이 같으면 셀러가
보는 화면은 같다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sourcing_guard.extractor as ex  # noqa: E402
from audit_tally import load_scope  # noqa: E402
from replay_single_path import grades_for  # noqa: E402
from sourcing_guard.verifier import RuleBook  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/kid/single_full.json")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--vendor", default="gpt")
    ap.add_argument("--out", default="/tmp/kid/gpt_extract.json")
    args = ap.parse_args()

    rows = json.loads(Path(args.src).read_text(encoding="utf-8"))
    scope = load_scope()
    rows = [r for r in rows if scope.get(r["name"]) == "대상"][: args.limit]

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = RuleBook()

    same_pn = same_legal = same_cat = 0
    same_grade = 0
    out: list[dict] = []
    for i, r in enumerate(rows, 1):
        ex.stats.reset()
        facts = ex.extract(r["name"])
        used = ex.stats.snapshot()["by_vendor"]
        got = {
            "no": r["no"],
            "name": r["name"],
            "vendor": next(iter(used), "heuristic"),
            "product_name": facts.product_name,
            "legal": facts.legal_item_name,
            "category": facts.category.value if facts.category else None,
        }
        new_grades = grades_for(
            {"name": r["name"], "product_name": got["product_name"],
             "category": got["category"], "legal": got["legal"]},
            kats, rules,
        )
        old_grades = grades_for(r, kats, rules)
        got["grades"] = new_grades
        got["grades_claude"] = old_grades
        out.append(got)

        same_pn += got["product_name"] == r.get("product_name")
        same_legal += (got["legal"] or None) == (r.get("legal") or None)
        same_cat += got["category"] == r.get("category")
        same_grade += new_grades == old_grades
        mark = "=" if new_grades == old_grades else "≠"
        print(f"  [{i:3}/{len(rows)}] {mark} {r['no']:>3} {r['name'][:44]}")
        if new_grades != old_grades:
            print(f"          claude {old_grades}\n          {got['vendor']:<6} {new_grades}")

    n = len(rows)
    print(f"\n{'=' * 70}\n{args.vendor} vs claude · {n}건 대조\n")
    print(f"  product_name 일치   {same_pn:3}/{n} ({same_pn / n * 100:.0f}%)")
    print(f"  legal_item_name 일치 {same_legal:3}/{n} ({same_legal / n * 100:.0f}%)")
    print(f"  category 일치       {same_cat:3}/{n} ({same_cat / n * 100:.0f}%)")
    print(f"\n  ⚠ 셀러가 보는 것은 등급이다:")
    print(f"  등급 조회 결과 일치  {same_grade:3}/{n} ({same_grade / n * 100:.0f}%)")
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
