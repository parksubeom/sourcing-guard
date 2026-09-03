#!/usr/bin/env python3
"""품목 매칭 검수표. 상품명 -> 품목명 -> 등급을 표로 뽑는다.

매칭률만 보면 안 된다. 40% -> 45% 로 올라도 그중 3건이 오답이면 손해다.
오답 판정은 사람이 해야 하니 눈으로 훑을 수 있는 형태로 낸다 - 이 세션 내내
오탐을 잡아온 방식이다.

    PYTHONPATH=. python scripts/match_review.py tests/fixtures/실상품30.txt
"""

from __future__ import annotations

import argparse
import pathlib

from sourcing_guard.item_grades import ItemGradeBook

_WIDTH = 46


def _cut(s: str, n: int) -> str:
    """한글 폭을 고려한 자르기. 정확한 정렬보다 읽히는 것이 목적이다."""
    out, w = "", 0
    for ch in s:
        cw = 2 if ord(ch) > 0x2000 else 1
        if w + cw > n:
            break
        out += ch
        w += cw
    return out + " " * (n - w)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample", help="상품명이 한 줄에 하나씩 있는 파일")
    args = ap.parse_args()

    names = [
        line.strip()
        for line in pathlib.Path(args.sample).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    book = ItemGradeBook()

    print(f"표본 {len(names)}건 · 등급표 {len(book)}건\n")
    print(f"{'#':>3}  {_cut('상품명', _WIDTH)}  {_cut('매칭된 품목명', 24)}  {'등급':10} 방식")
    print("─" * 118)

    hit = 0
    split = 0
    unmatched: list[tuple[int, str]] = []
    for i, name in enumerate(names, start=1):
        found = book.lookup_all(name)
        if not found:
            unmatched.append((i, name))
            print(f"{i:3}  {_cut(name, _WIDTH)}  {_cut('— 없음', 24)}")
            continue
        hit += 1
        agree = ItemGradeBook.grades_agree(found)
        if agree is None:
            split += 1
        head = found[0]
        flag = "" if agree else "  ⚠ 등급 갈림"
        print(
            f"{i:3}  {_cut(name, _WIDTH)}  {_cut(head.item, 24)}  "
            f"{_cut(head.grade, 10)} {head.matched_by}{flag}"
        )
        for extra in found[1:]:
            print(
                f"     {_cut('', _WIDTH)}  {_cut('+ ' + extra.item, 24)}  "
                f"{_cut(extra.grade, 10)} {extra.matched_by}"
            )

    print("─" * 118)
    print(f"매칭 {hit}/{len(names)} = {hit / len(names) * 100:.0f}%  ·  등급 갈림 {split}건")

    if unmatched:
        print(f"\n못 맞춘 {len(unmatched)}건")
        for i, name in unmatched:
            print(f"  {i:3}  {name}")

    print(
        "\n검수 방법: '매칭된 품목명' 이 상품명과 같은 물건인지 보십시오.\n"
        "  다른 물건이면 오답입니다 - 등급이 틀리면 인증번호 부재의 의미가 뒤집힙니다.\n"
        "  '방식' 은 exact(정확) · alias(별칭) · expand(접두 확장) · contains(포함) 입니다."
    )


if __name__ == "__main__":
    main()
