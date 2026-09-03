#!/usr/bin/env python3
"""못 맞춘 상품명을 세 갈래로 나눈다. 개선 대상은 셋째뿐이다.

    A. 브랜드·모델·부속만 있음  품목어가 아예 없다. 우리가 할 일이 없다.
    B. 표에 없는 비대상          도마 · 텀블러 · 옷걸이. 안전관리 대상이 아닐
                                가능성이 높다 - 매칭 실패가 아니라 정답이다.
    C. 표에 있는데 못 찾음        여기만 고치면 된다.

C 판정은 사람이 해야 한다. 자동으로는 "상품명의 어느 조각이 표의 어느 품목과
겹치는가" 만 계산해서 후보를 보여준다 - 판정을 대신하지 않는다 (R1).

    PYTHONPATH=. python scripts/classify_misses.py tests/fixtures/도매꾹239.txt
"""

from __future__ import annotations

import argparse
import pathlib
import re

from sourcing_guard.item_grades import (
    ItemGradeBook,
    is_usable_contain_key,
    normalize,
    split_aliases,
)

# 부속·거치·커버류. 본체가 아니므로 본체 품목으로 붙으면 오답이다.
_ACCESSORY = ("거치대", "홀더", "커버", "받침대", "선반", "걸이", "정리함",
              "케이스", "필터", "리필", "덮개", "행거", "보관함", "카바")


def overlaps(name: str, book: ItemGradeBook) -> list[str]:
    """상품명과 핵심어가 겹치는 표의 품목을 찾는다. 판정이 아니라 단서다.

    ⚠ 여기서도 짧은 조각을 쓰면 안 된다. 처음엔 2글자부터 잘라 봤더니
      "보조배터리 미니보조배터리" 에서 '리미' 가 걸려 '스팀다리미' 가
      후보로 나왔다 - normalize 가 띄어쓰기를 지운 뒤 낱말 경계를 넘어
      들러붙은 것이다. 이 스크립트가 찾으려던 결함을 스스로 되풀이했다.

      그래서 (1) 3글자 이상 (2) 식별력 있는 말 (3) 품목명의 **접미**
      (핵심어는 뒤에 온다 - '자전거용 안전모' 의 핵심은 '안전모') 로만
      본다.
    """
    target = normalize(name)
    hits: list[str] = []
    for row in book._rows:
        for alias in split_aliases(row["item"]):
            key = normalize(alias)
            for cut in range(len(key) - 2):
                tail = key[cut:]
                if is_usable_contain_key(tail) and tail in target:
                    hits.append(f"{row['item'][:28]}({row['grade']})")
                    break
            else:
                continue
            break
    return sorted(set(hits))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample")
    args = ap.parse_args()

    names = [n.strip() for n in
             pathlib.Path(args.sample).read_text(encoding="utf-8").splitlines() if n.strip()]
    book = ItemGradeBook()
    misses = [n for n in names if not book.lookup_all(n)]

    print(f"전체 {len(names)}건 · 매칭 {len(names) - len(misses)}건 "
          f"({(len(names) - len(misses)) / len(names) * 100:.0f}%) · "
          f"못 맞춤 {len(misses)}건\n")

    for i, name in enumerate(misses, 1):
        acc = [w for w in _ACCESSORY if w in name]
        cand = overlaps(name, book)
        print(f"{i:3} {name[:78]}")
        if acc:
            print(f"     부속어: {'·'.join(acc)}")
        if cand:
            print(f"     표에 비슷한 것: {' / '.join(cand[:4])}")
        else:
            print("     표에 겹치는 품목 없음")
    print("\n분류: A 브랜드·모델만 / B 표에 없는 비대상 / C 표에 있는데 못 찾음")
    print("C 만 개선 대상입니다. '표에 비슷한 것' 이 실제로 같은 물건인지 보십시오.")


if __name__ == "__main__":
    main()
