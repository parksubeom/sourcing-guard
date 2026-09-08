#!/usr/bin/env python
"""저장된 LLM 답으로 단건 경로를 재생한다. **LLM·네트워크 0회.**

왜 필요한가
-----------
`measure_single_path_full.py` 는 실 API 를 부르므로 별칭을 하나 고칠 때마다
LLM 235회를 쓴다. 추출 결과가 바뀌지 않는 변경(별칭·가드·표)에서는 저장된
`facts` 를 그대로 되돌려 `verify()` 만 다시 돌리면 같은 숫자가 나온다.

⚠ **집계는 정본과 똑같아야 한다.** 2026-09-08 에 이 재생을 급히 만들면서
  두 번 틀렸다:

    (1) `lookup_all` 을 직접 불러 verifier 의 카테고리 게이트를 건너뛰었다
        → 2건 부풀려 기획서에 77.8% 를 적었다 (실제 76.3%)
    (2) `ITEM_GRADE_MATCHED` 만 셌다 → '전기방석' 처럼 두 등급으로 갈리는
        줄이 `ITEM_GRADE_SPLIT` 으로 나오는데 그것을 미매칭으로 셌다

  그래서 여기서는 정본과 같이 **kind 를 가리지 않고 모든 finding 의
  `detail.candidates`** 를 모은다. 갈림도 "등급이 붙은 것" 이다 - 화면에
  품목명이 뜨기 때문이다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.models import ItemCategory, ProductFacts  # noqa: E402
from sourcing_guard.verifier import RuleBook, verify  # noqa: E402
from audit_tally import load_audit, load_scope, verdict  # noqa: E402

_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")
_WRONG = Path("tests/fixtures/새표본235_오답.tsv")


def grades_for(row: dict, kats, rules: RuleBook) -> list[str]:
    try:
        category = ItemCategory(row.get("category") or "unclassified")
    except ValueError:
        category = ItemCategory.UNCLASSIFIED
    facts = ProductFacts(
        product_name=row.get("product_name") or None,
        category=category,
        legal_item_name=row.get("legal") or None,
    )
    found = verify(facts, kats, rules, raw_text=row["name"])
    # ⚠ 정본과 동일 - kind 를 가리지 않는다.
    return sorted(
        {c["item"] for f in found for c in (f.detail or {}).get("candidates", []) or []}
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", nargs="+",
                    default=["tests/fixtures/단건경로_claude_235.json"],
                    help="측정 원자료 json (기본: 리포의 Claude 235건)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    scope = load_scope()
    wrong, vague = load_audit()
    rows: list[dict] = []
    for p in args.src:
        rows += json.loads(Path(p).read_text(encoding="utf-8"))
    rows = [r for r in rows if scope.get(r["name"])]

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = RuleBook()
    res = {r["name"]: grades_for(r, kats, rules) for r in rows}

    target = [r["name"] for r in rows if scope[r["name"]] == "대상"]
    hit = [n for n in target if res[n]]
    bad = [n for n in hit if verdict(n, res[n], wrong, vague) == "wrong"]
    amb = [n for n in hit if verdict(n, res[n], wrong, vague) == "vague"]
    ok = len(hit) - len(bad) - len(amb)
    off = [(n, res[n]) for n in res if res[n] and scope[n] == "비대상"]
    vag = [(n, res[n]) for n in res if res[n] and scope[n] == "애매"]

    n_off = len([n for n in res if scope[n] == "비대상"])
    n_vag = len([n for n in res if scope[n] == "애매"])
    print(f"단건 재생 · 대상 {len(target)}")
    print(f"  정답 {ok} ({ok / len(target) * 100:.1f}%) · 애매 {len(amb)} "
          f"· 오답 {len(bad)} · 미매칭 {len(target) - len(hit)}")
    if n_off or n_vag:
        print(f"  비대상 {n_off} → {len(off)}건 부착 · 애매 {n_vag} → {len(vag)}건 부착")
        for n, v in off:
            print(f"     [비대상] {n[:46]} → {v}")
        for n, v in vag:
            print(f"     [애매]  {n[:46]} → {v}")
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                  encoding="utf-8")


if __name__ == "__main__":
    main()
