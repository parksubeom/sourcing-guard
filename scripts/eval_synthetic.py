#!/usr/bin/env python3
"""합성 표본으로 매칭 정확도를 잰다. 정답이 확정돼 있어 오답이 자동 판정된다.

⚠ 이 숫자를 실제 매칭률로 읽으면 안 된다. 합성으로 재는 것은 "수식어·브랜드·
  연관품목에 흔들리지 않는가" 이지 "셀러 말을 알아듣는가" 가 아니다.
  후자는 실상품 표본으로만 잴 수 있다.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections import Counter

from sourcing_guard.item_grades import ItemGradeBook


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample")
    ap.add_argument("--show", type=int, default=25, help="오답을 몇 건까지 볼지")
    args = ap.parse_args()

    rows = json.loads(pathlib.Path(args.sample).read_text(encoding="utf-8"))
    book = ItemGradeBook()

    ok = wrong = missed = 0
    grade_ok = 0
    wrong_rows: list[tuple[str, str, str, str, str]] = []
    for row in rows:
        found = book.lookup_all(row["title"])
        if not found:
            missed += 1
            continue
        items = [g.item for g in found]
        if row["answer_item"] in items:
            ok += 1
            # 등급까지 맞았는가 - 후보가 여럿이면 등급이 하나로 모여야 한다
            if ItemGradeBook.grades_agree(found) == row["answer_grade"]:
                grade_ok += 1
        else:
            wrong += 1
            head = found[0]
            wrong_rows.append(
                (row["title"], row["answer_item"], row["answer_grade"],
                 head.item, f"{head.grade}/{head.matched_by}")
            )

    n = len(rows)
    print(f"합성 표본 {n}건\n")
    print(f"  정답 포함   {ok:4} ({ok / n * 100:5.1f}%)   후보 안에 정답이 있다")
    print(f"  등급 일치   {grade_ok:4} ({grade_ok / n * 100:5.1f}%)   후보 등급이 하나로 모이고 정답과 같다")
    print(f"  오답       {wrong:4} ({wrong / n * 100:5.1f}%)   다른 품목으로 붙었다")
    print(f"  못 맞춤     {missed:4} ({missed / n * 100:5.1f}%)")

    if wrong_rows:
        print(f"\n── 오답 {len(wrong_rows)}건 중 {min(args.show, len(wrong_rows))}건 ──")
        for title, want, want_g, got, got_g in wrong_rows[: args.show]:
            print(f"  {title[:52]}")
            print(f"      정답 {want[:22]:24}({want_g})   →   붙은 것 {got[:22]} ({got_g})")
        print("\n── 오답 패턴 (정답 → 붙은 것) ──")
        pat = Counter((w[1], w[3]) for w in wrong_rows)
        for (want, got), c in pat.most_common(15):
            print(f"  {c:4}회  {want[:24]:26} → {got[:24]}")


if __name__ == "__main__":
    main()
