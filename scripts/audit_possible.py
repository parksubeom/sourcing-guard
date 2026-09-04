#!/usr/bin/env python3
"""possible(우리 추정) 후보를 검수한다.

매처를 붙이고 나서야 보인 것 - 통과한 후보 263개 중 167개(63%)가
possible 이다. 법령 원문 일치가 아니라 **우리가 만든 별칭·접두 확장**이다.
"매칭 69%" 라고만 말하면 이게 안 보인다.

certain 이 0개인 것도 같은 사실의 다른 면이다 - 도매 상품명 중 표의 품목명과
그대로 같은 것이 하나도 없다.

이 스크립트는 판정하지 않는다. 별칭별로 무엇에 붙었는지 모아서 사람이
훑을 수 있게 낸다 (R1).

    PYTHONPATH=. python scripts/audit_possible.py            # 요약
    PYTHONPATH=. python scripts/audit_possible.py --full     # 상품명까지
"""

from __future__ import annotations

import argparse
import collections
import pathlib

from sourcing_guard.item_grades import ItemGradeBook
from sourcing_guard.matcher import Confidence

_SAMPLE = pathlib.Path("tests/fixtures/도매꾹239.txt")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="상품명까지 전부 낸다")
    ap.add_argument("--sample", default=str(_SAMPLE))
    args = ap.parse_args()

    names = [
        n.strip()
        for n in pathlib.Path(args.sample).read_text(encoding="utf-8").splitlines()
        if n.strip()
    ]
    book = ItemGradeBook()

    by_route: collections.Counter[str] = collections.Counter()
    per_item: dict[tuple[str, str], list[str]] = collections.defaultdict(list)

    for raw in names:
        for g in book.lookup_all(raw):
            by_route[str(g.confidence)] += 1
            if str(g.confidence) == Confidence.POSSIBLE.value:
                per_item[(g.item, g.grade, g.matched_by)].append(raw)

    total = sum(by_route.values())
    print(f"도매꾹 실상품 {len(names)}건 · 통과한 후보 {total}개\n")
    for level in ("certain", "likely", "possible"):
        n = by_route[level]
        print(f"  {level:9} {n:4}개 ({n / total * 100:4.1f}%)")
    print()
    print(f"── possible {by_route['possible']}개를 품목별로 ──")
    print("   (우리 추정이다. 이 품목이 정말 그 상품인지 눈으로 볼 것)\n")

    rows = sorted(per_item.items(), key=lambda kv: -len(kv[1]))
    for (item, grade, how), hits in rows:
        print(f"  {len(hits):3}건  {item[:28]:30} {grade:9} ({how})")
        shown = hits if args.full else hits[:2]
        for h in shown:
            print(f"          {h[:76]}")
        if not args.full and len(hits) > 2:
            print(f"          … 외 {len(hits) - 2}건")
    print()
    print(f"품목 {len(rows)}종. --full 로 전부 볼 수 있다.")


if __name__ == "__main__":
    main()
