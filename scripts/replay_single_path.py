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
from audit_tally import (  # noqa: E402
    BASELINE_ON_VAGUE,
    compare_baseline,
    load_audit,
    load_reviewed_pairs,
    load_scope,
    tally,
    verdict,
)

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

    # 검수 분리까지 **정본 집계**로 낸다. 다섯 기준을 한 화면에 둔다.
    which = "gpt" if any("gpt" in str(p) for p in args.src) else "claude"
    reviewed = load_reviewed_pairs("tests/fixtures/단건경로_claude_235.json")
    full = tally(res, scope=scope, reviewed=reviewed)

    print(f"단건 재생 · 대상 {len(target)}   (기준선 표: {which})")
    print(f"  ① 검수된 정답  {full['ok']:3} ({full['ok'] / full['denominator'] * 100:.1f}%)")
    print(f"  ② 미검수       {full['unreviewed']:3}")
    print(f"  ③ 상한         {full['ok_upper']:3} "
          f"({full['ok_upper'] / full['denominator'] * 100:.1f}%)   ← 미검수 포함")
    print(f"     애매 {full['vague']} · 오답 {full['wrong']} · 미매칭 {full['missed']}")
    print(f"  ④ 비대상 부착  {full['off_target']:3}   ← 0 이 아니면 발표에 쓸 수 없다")
    # ⚠ **⑤ 를 조건부로 숨기지 않는다.** 4-e 에서 이 숫자가 1 → 2 로 움직였는데
    #   보고에서 빠졌다. 분모 밖이라 정답률에는 안 보이지만 화면에는 보인다.
    print(f"  ⑤ 애매 부착    {full['on_vague']:3}   ← 분모 밖이지만 화면에는 뜬다")
    for n, v in vag:
        known = n in BASELINE_ON_VAGUE.get(which, ())
        print(f"       {'  ' if known else '⚠ 새'} [애매] {n[:44]} → {v}")
    for n, v in off:
        print(f"       ⚠ 새 [비대상] {n[:44]} → {v}")

    drift = compare_baseline(full, which)
    if drift:
        print("\n  ⚠⚠ 기준선과 다르다 - 보고에 다섯을 다 적을 것")
        for line in drift:
            print(f"       {line}")
    else:
        print(f"\n  ✅ 기준선({which})과 같다")
    if args.out:
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                  encoding="utf-8")


if __name__ == "__main__":
    main()
