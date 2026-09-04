#!/usr/bin/env python3
"""매처가 신호별로 몇 건을 거부하는지 센다.

1단계(검색)가 후보를 넓게 찾고 2단계(매처)가 참인 것을 가린다. 이전에는
부속어 가드가 여섯 곳에 흩어져 있어 **무엇이 왜 거부됐는지 셀 수가 없었다.**
한곳에 모았으니 이제 센다.

    PYTHONPATH=. python scripts/measure_matcher.py
"""

from __future__ import annotations

import collections
import pathlib

from sourcing_guard.item_grades import (
    ItemGradeBook,
    chemical_variant_dominates,
    names_the_subject,
    normalize,
    strip_modifiers,
)
from sourcing_guard.matcher import (
    Confidence,
    chemical_rival_wins,
    has_consumable_hint,
    judge,
)

_SAMPLE = pathlib.Path("tests/fixtures/도매꾹239.txt")


def main() -> None:
    names = [
        n.strip() for n in _SAMPLE.read_text(encoding="utf-8").splitlines() if n.strip()
    ]
    book = ItemGradeBook()

    # 1단계가 찾아온 후보를 매처 없이 세려면 판정을 직접 돌려야 한다.
    rejected = collections.Counter()
    accepted = collections.Counter()
    per_product_rejected = 0
    products_with_rejection = 0

    for raw in names:
        intact = normalize(raw)
        consumable = has_consumable_hint(raw)
        stripped = normalize(strip_modifiers(raw))
        forms = [intact] + ([stripped] if stripped != intact else [])

        seen: set[tuple[str, str]] = set()
        hits: list[tuple[str, str, object]] = []

        # 1단계 재현: 포함 · 정확 · 별칭
        for base in (raw, strip_modifiers(raw)):
            rows = book._by_name.get(normalize(base))
            for row in rows or ():
                hits.append(("exact", normalize(row["item"]), row))
        for key, rows in book._contain_keys:
            if key in intact:
                for row in rows:
                    hits.append(("contains", key, row))
        from sourcing_guard.item_grades import ALIASES

        for target in forms:
            for key, legal in ALIASES.items():
                if normalize(key) not in target:
                    continue
                for name in (legal,) if isinstance(legal, str) else legal:
                    for row in book._by_name.get(normalize(name)) or ():
                        hits.append(("alias", normalize(key), row))

        any_reject = False
        for how, key, row in hits:
            mark = (row["item"], row["grade"])
            if mark in seen:
                continue
            seen.add(mark)
            # 매처는 신호를 계산하지 않고 받는다 - 호출측(ItemGradeBook)이
            # 이미 정규화를 했으므로 규칙을 두 곳에 두지 않는다.
            v = judge(
                normalized_name=intact,
                normalized_key=key,
                matched_by=how,
                names_subject=(
                    True if how == "exact" else names_the_subject(intact, key)
                ),
                chemical_dominates=chemical_variant_dominates(
                    intact, normalize(row["item"])
                ),
                consumable_hint=consumable,
                chemical_rival=chemical_rival_wins(raw, row["item"]),
            )
            if v.confidence is Confidence.REJECTED:
                name = next((s.name for s in v.signals if s.rejects), "알수없음")
                rejected[name] += 1
                any_reject = True
                per_product_rejected += 1
            else:
                accepted[v.confidence.value] += 1
        products_with_rejection += any_reject

    total_rej = sum(rejected.values())
    total_acc = sum(accepted.values())
    print(f"도매꾹 실상품 {len(names)}건\n")
    print(f"1단계가 찾아온 후보  {total_acc + total_rej:4}개")
    print(f"  매처가 통과시킴     {total_acc:4}개")
    print(f"  매처가 거부함       {total_rej:4}개   "
          f"(상품 {products_with_rejection}건에서 발생)\n")

    print("── 거부 신호별 ──")
    for name, n in rejected.most_common():
        print(f"  {n:4}개  {name}")
    print("\n── 통과한 것의 신뢰도 ──")
    for level in ("certain", "likely", "possible"):
        if accepted[level]:
            print(f"  {accepted[level]:4}개  {level}")

    # 매처를 끄면 몇 건이 살아나는가 = 이전 상태
    print(f"\n매처가 없으면 후보 {total_rej}개가 더 붙는다. "
          f"그중 상당수가 오답이었다.")


if __name__ == "__main__":
    main()
