#!/usr/bin/env python3
"""매처가 신호별로 몇 건을 거부하는지 센다. 매칭률도 함께.

    PYTHONPATH=. python scripts/measure_matcher.py
    PYTHONPATH=. python scripts/measure_matcher.py --sample tests/fixtures/도매꾹239.txt

⚠⚠ **재현을 없앴다 (4-f · 2026-09-09).**

  전에는 이 스크립트가 `ItemGradeBook.lookup_all` 의 1단계(검색)를 **직접
  재현**했다. 통과한 후보만 돌려주는 API 로는 "거부된 후보" 를 셀 수 없었기
  때문이다. 그래서 자기검사(`재현 == 실제`)를 두고 어긋나면 멈추게 했는데,
  실제로 멈췄다:

      재현이 실제 코드와 어긋납니다.
        상품: 장갑 높이조절 스탠드 스팀 다리미판 행거 지지대
        재현: ['스팀다리미', '의류']
        실제: []

  **자기검사가 옳았고 재현이 낡았다.** 재현에는 그 뒤 들어온 가드 셋
  (`names_a_standalone_accessory` · `accessory_follows_the_key` ·
  `is_excluded_by_marker`)과 접두 확장 단계가 없었다. 기대값을 현재 출력에
  맞춰 덮어쓰면 검사가 아무것도 안 지킨다.

  그래서 재현을 고치는 대신 **없앴다** - `lookup_all(..., trace=[])` 이 후보를
  전부 적어 주므로 이 스크립트는 그것만 센다. 같은 규칙을 두 곳에 두면 반드시
  갈라진다.

⚠ `trace` 의 결과는 셋이다.

    accepted  매처가 통과시켰다
    rejected  매처(`judge`)가 거부했다 - `rejected_by` 에 어느 신호인지
    guard     `judge` 앞의 가드가 걸렀다 (부속품 · 원문 제외 표기)

⚠⚠ **`rejected_by` 의 두 값을 섞어 읽지 말 것 (4-h).**

    key_absent            키가 이름에 **아예 없다.** 대부분 (3) 접두 확장 단계가
                          낸 후보이고 **부속품 판단이 아니다.** 정상 동작이다
    accessory_or_negated  키는 이름에 있는데 부속품·부정 표현으로만 나온다.
                          **이것만이 진짜 부속품 판단이다**

  전에는 둘이 하나로 찍혀 도매꾹239 거부 134,900건이 전부 부속품 판단처럼
  보였다. 그대로 두면 다음 사람이 "우리 매처가 너무 엄격하다" 로 읽고 가드를 푼다.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sourcing_guard.item_grades import ItemGradeBook  # noqa: E402

_DEFAULT = pathlib.Path("tests/fixtures/새표본235.txt")

# 09-04 작업로그 §7 이 적은 값. 지금 값과 다르므로 **라벨을 붙여 나란히 적는다.**
#
#   09-04 로그   "매칭 165 → 170/239 (69% → 71%)"
#   재현          커밋 f555d52 에서 lookup_all 기준 170/239 = 71.1% (worktree 로 확인)
#
# ⚠ 두 숫자를 "개선/악화" 로 읽지 말 것. 아래 §차이 참조 - 3건 중 2건은 오답을
#   지운 것이고 1건은 정답을 잃은 것이다.
_LOG_0904 = {"sample": "도매꾹239", "matched": 170, "total": 239, "commit": "f555d52"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(_DEFAULT))
    args = ap.parse_args()

    path = pathlib.Path(args.sample)
    names = [
        n.strip() for n in path.read_text(encoding="utf-8").splitlines() if n.strip()
    ]
    book = ItemGradeBook()

    rejected: collections.Counter = collections.Counter()
    accepted: collections.Counter = collections.Counter()
    guarded: collections.Counter = collections.Counter()
    matched: list[str] = []
    products_with_rejection = 0

    for raw in names:
        trace: list[dict] = []
        got = book.lookup_all(raw, trace=trace)
        if got:
            matched.append(raw)
        any_reject = False
        for row in trace:
            if row["outcome"] == "accepted":
                accepted[row["confidence"]] += 1
            elif row["outcome"] == "guard":
                guarded[row["reason"]] += 1
            else:
                rejected[row.get("rejected_by") or "알수없음"] += 1
                any_reject = True
        products_with_rejection += any_reject

    total_rej = sum(rejected.values())
    total_acc = sum(accepted.values())
    total_guard = sum(guarded.values())

    print(f"{path.name} · {len(names)}건 "
          f"(재현 없음 - lookup_all 의 trace 를 그대로 센다)\n")
    print(f"등급이 붙은 상품     {len(matched):4}/{len(names)} "
          f"= {len(matched) / len(names) * 100:.1f}%")
    print(f"  ⚠ 라벨: 원본 상품명 · lookup_all 기준 · LLM 없음\n")
    print(f"1단계가 찾아온 후보  {total_acc + total_rej + total_guard:7}개")
    print(f"  매처가 통과시킴     {total_acc:7}개")
    print(f"  매처가 거부함       {total_rej:7}개   "
          f"({products_with_rejection}개 상품에서)")
    print(f"  가드가 걸러냄       {total_guard:7}개   (judge 앞)")

    if rejected:
        print("\n매처 거부 사유")
        for name, n in rejected.most_common():
            note = {
                "key_absent": "  ← 키가 이름에 아예 없다. 대부분 (3) 접두 확장 "
                              "단계가 낸 후보이고 **부속품 판단이 아니다**",
                "accessory_or_negated": "  ← 키는 이름에 있는데 부속품·부정 "
                                        "표현으로만 나온다. 이것이 진짜 부속품 판단이다",
            }.get(name, "")
            print(f"  {n:7}개  {name}{note}")
    if guarded:
        print("\n가드 사유")
        for name, n in guarded.most_common():
            print(f"  {n:7}개  {name}")
    if accepted:
        print("\n통과한 후보의 확신도")
        for level, n in accepted.most_common():
            print(f"  {n:7}개  {level}")

    if path.name == f"{_LOG_0904['sample']}.txt":
        then = _LOG_0904
        print(f"\n{'=' * 70}")
        print(f"09-04 로그와 대조 — **개선/악화로 읽지 말 것**")
        print(f"  09-04 (커밋 {then['commit']})  {then['matched']}/{then['total']} "
              f"= {then['matched'] / then['total'] * 100:.1f}%")
        print(f"  지금                      {len(matched)}/{len(names)} "
              f"= {len(matched) / len(names) * 100:.1f}%")
        print(f"  차이 {len(matched) - then['matched']:+d}건 - 무엇이 빠졌는지는 "
              f"docs/미완_목록.md 4-f 참조")


if __name__ == "__main__":
    main()
