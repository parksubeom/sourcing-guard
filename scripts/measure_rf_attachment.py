#!/usr/bin/env python
"""[⑦-a ④] 전파 표를 화면에 올려도 되는가 — **비대상 오부착을 센다.**

    PYTHONPATH=. python scripts/measure_rf_attachment.py

기준(총괄): 새표본235 + 도매꾹239 에서 **비대상 오부착 0** 이면 화면에
"이 품목은 적합인증 대상입니다" 로 올린다. 1건이라도 붙으면 표만 리포에 두고
화면은 "무선 기능 표기가 있습니다" 를 유지한다. 등급표를 올릴 때와 같은 기준.

⚠ **매칭은 `ItemGradeBook` 을 그대로 쓴다.** 새 매칭 규칙을 만들지 않는다 -
  같은 규칙을 두 곳에 두면 반드시 갈라진다 (§6 · measure_matcher 가 겪은 그대로).

⚠ 별칭은 **고시가 적어 둔 대표 품목**이다("o 대표적인 품목은 다음과 같다. -
  진공청소기, 로봇청소기, …"). 우리가 지어낸 이름이 아니다 (R5). 표의 이름이
  `전기청소기류` 처럼 류 단위라, 별칭 없이는 상품명과 한 글자도 안 겹친다 -
  실측으로 확인했다(별칭 없이 두 표본 모두 **0건**).
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.item_grades import ItemGradeBook  # noqa: E402
from sourcing_guard.rf_equipment import (  # noqa: E402
    example_aliases,
    rf_book,
)

SAMPLES = {
    "새표본235": Path("tests/fixtures/새표본235.txt"),
    "도매꾹239": Path("tests/fixtures/도매꾹239.txt"),
}
CLASSIFIED = Path("tests/fixtures/새표본235_대상분류.tsv")


def _verdicts() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in CLASSIFIED.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            out[parts[2]] = parts[1]
    return out


def main() -> int:
    book: ItemGradeBook = rf_book()
    alias = example_aliases()
    print(f"표 {len(book._rows)}행 · 고시가 적어 둔 대표 품목 별칭 {len(alias)}개\n")

    verdicts = _verdicts()
    wrong: list[tuple[str, str]] = []
    for name, sample in SAMPLES.items():
        lines = [l.strip() for l in sample.read_text(encoding="utf-8").splitlines() if l.strip()]
        tally = collections.Counter()
        hits = 0
        for line in lines:
            got = book.lookup_all(line, extra_aliases=alias)
            if not got:
                continue
            hits += 1
            v = verdicts.get(line)
            tally[v or "분류없음"] += 1
            if v == "비대상":
                wrong.append((line, got[0].item))
        print(f"{name}: 붙은 줄 {hits}/{len(lines)} ({hits / len(lines) * 100:.0f}%)")
        for k, n in sorted(tally.items()):
            print(f"    {k}: {n}")
    print()
    if wrong:
        print(f"⚠ 비대상 오부착 {len(wrong)}건 — **화면에 올리지 않는다**")
        for line, item in wrong:
            print(f"    {line[:58]!r}\n      → {item}")
        return 1
    print("비대상 오부착 0 — 화면에 올릴 수 있다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
