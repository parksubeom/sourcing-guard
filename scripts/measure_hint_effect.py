#!/usr/bin/env python3
"""부속품 힌트가 오답을 실제로 해소하는지 잰다.

세 숫자를 **갈라서** 낸다. 뭉치면 우리가 스스로를 속인다.

    ① 힌트 없음 (기본 상태)     셀러가 아무것도 안 눌렀을 때의 오답
    ② 힌트 있음 (버튼 누름)     그 오답이 사라지는가
    ③ 질문이 뜨는 건수          안 뜨면 해소할 방법 자체가 없다

셀러가 버튼을 눌러야 해소되므로 ①은 줄지 않는다. 개선된 것은 "해소할 방법이
생겼다" 이지 "자동으로 맞아졌다" 가 아니다.

③이 특히 중요하다. 화면은 등급 finding 위에만 질문을 띄우므로, 등급 미매칭인
오답에는 질문이 안 뜬다. 그런 경우가 있으면 힌트로 못 고친다.

    PYTHONPATH=. python scripts/measure_hint_effect.py
"""

from __future__ import annotations

import pathlib

from sourcing_guard.item_grades import ItemGradeBook
from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts, SellerHints
from sourcing_guard.verifier import RuleBook, verify

_SAMPLE = pathlib.Path("tests/fixtures/도매꾹239.txt")
_WRONG = pathlib.Path("tests/fixtures/도매꾹239_오답.tsv")

# 화면이 부속품 질문을 띄우는 kind. 이것이 없으면 셀러가 누를 버튼이 없다.
_ASKS = {FindingKind.ITEM_GRADE_MATCHED, FindingKind.ITEM_GRADE_SPLIT}


class NoRecalls:
    """리콜 축은 이 측정과 무관하다. 대조는 했다고 두고 결과를 비운다."""

    as_of = "20260903"

    def is_empty(self) -> bool:
        return False

    def find(self, facts, *, today=None):
        return []

    def by_maker_exact(self, maker, *, exclude_uids=None):
        return []


def scan(facts: ProductFacts, hints: SellerHints | None):
    return verify(
        facts, KatsClient(None, None, mock=True), RuleBook(), NoRecalls(), hints=hints
    )


_BOOK = ItemGradeBook()


def category_of(name: str) -> ItemCategory:
    """품목군을 등급표에서 가져온다.

    ⚠ 휴리스틱 추출은 상품명만으로 unclassified 를 낸다(키워드가 본문에
      없으니 당연하다). 프로덕션은 LLM 이 분류하고, 라이브로 확인했다 -
      우산→household · 선풍기→electrical · 공기청정기→electrical.

      LLM 을 239번 부르면 일일 한도 500회의 절반을 쓰므로, 등급표가 적어 둔
      품목군을 쓴다. **전제**: LLM 이 등급표와 같은 품목군으로 분류한다.
      위 세 건으로 확인했고, 틀리면 이 측정의 ②③이 과대평가된다.
    """
    found = _BOOK.lookup_all(name)
    if not found:
        return ItemCategory.UNCLASSIFIED
    cats = {g.category for g in found}
    if "electrical" in cats:
        return ItemCategory.ELECTRICAL
    return ItemCategory.HOUSEHOLD


def main() -> None:
    names = [
        n.strip() for n in _SAMPLE.read_text(encoding="utf-8").splitlines() if n.strip()
    ]
    wrong = {
        line.split("\t")[0]: line.split("\t")[1:]
        for line in _WRONG.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }

    asked = 0
    matched = 0
    rows = []
    for name in names:
        facts = ProductFacts(product_name=name, category=category_of(name))
        base = scan(facts, None)
        kinds_base = {f.kind for f in base}
        if kinds_base & _ASKS:
            asked += 1
        if kinds_base & (_ASKS | {FindingKind.ITEM_GRADE_NOT_APPLIED}):
            matched += 1
        if name in wrong:
            hinted = scan(facts, SellerHints(is_accessory=True))
            rows.append((name, kinds_base, {f.kind for f in hinted}))

    n = len(names)
    print(f"도매꾹 실상품 {n}건\n")
    print(f"  등급이 붙은 것            {matched:4}건 ({matched / n * 100:.0f}%)")
    print(f"  부속품 질문이 뜨는 것      {asked:4}건 ({asked / n * 100:.0f}%)")
    print()

    print("── 오답 5건: 질문이 뜨는가 · 힌트로 해소되는가 ──")
    fixed = asks = 0
    for name, base, hinted in rows:
        can_ask = bool(base & _ASKS)
        gone = not (hinted & {FindingKind.ITEM_GRADE_MATCHED, FindingKind.ITEM_GRADE_SPLIT})
        warned = FindingKind.KC_MISSING_BUT_REQUIRED in hinted
        asks += can_ask
        fixed += can_ask and gone and not warned
        print(f"  질문 {'뜬다' if can_ask else '안뜬다'} · "
              f"힌트후 {'해소' if gone and not warned else '남음'}   {name[:52]}")
    print()
    print(f"  ① 힌트 없음 (기본)      오답 {len(rows)}건  ← 셀러가 안 누르면 그대로다")
    print(f"  ② 힌트 있음 (버튼 누름)  오답 {len(rows) - fixed}건")
    print(f"  ③ 질문이 뜨는 오답       {asks}/{len(rows)}건")
    if asks < len(rows):
        print("\n  주의: 질문이 안 뜨는 오답은 힌트로 고칠 수 없다. 별도 대응이 필요하다.")


if __name__ == "__main__":
    main()
