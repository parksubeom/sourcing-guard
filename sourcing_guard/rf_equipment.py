"""전파 적합성평가 대상기자재 표 — [⑦-a].

⚠⚠ **화면에 연결하지 않았다 (2026-09-14).** 기준은 "새표본235 + 도매꾹239 에서
  비대상 오부착 0" 이었고 실측은 3건이다 - `data/rf_target_equipment.yaml`
  머리 주석에 그 셋을 적어 뒀다. 표는 리포에 두고 화면은 "무선 기능 표기가
  있습니다" 를 유지한다.

  이 파일이 있는 이유는 **다음에 다시 잴 수 있게** 하기 위해서다
  (`scripts/measure_rf_attachment.py`). 표가 자라거나 매처가 좋아지면 같은
  자로 다시 재고, 0 이 되면 그때 연다.

⚠ 매칭은 `ItemGradeBook` 을 그대로 쓴다. 새 매칭 규칙을 만들지 않는다.
"""

from __future__ import annotations

import collections
from functools import lru_cache
from pathlib import Path

import yaml

_PATH = Path(__file__).with_name("data") / "rf_target_equipment.yaml"


@lru_cache(maxsize=1)
def table() -> dict:
    return yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}


def wired_to_screen() -> bool:
    """화면이 이 표를 쓰는가. **지금은 False 다** - 측정이 열어 준 뒤에 켠다."""
    return bool(table().get("화면연결"))


@lru_cache(maxsize=1)
def example_aliases() -> dict[str, tuple[str, ...]]:
    """고시가 적어 둔 **대표 품목** → 표의 품목명.

    ⚠ 우리가 만든 별칭이 아니다. 고시 본문의 "o 대표적인 품목은 다음과 같다."
      목록을 그대로 옮긴 것이다 (R5).

    ⚠ 이것이 없으면 매칭이 **0건**이다 - 표의 이름이 `전기청소기류` 처럼 류
      단위라 상품명(`로봇청소기`)과 한 글자도 안 겹친다. 실측으로 확인했다.

    ⚠⚠ **괄호 앞 머리 낱말도 넣는다 (2026-09-14 · ⑦-a-3).**

      고시가 `A(B, C)` 로 적었다면 **A 가 품목명이고 괄호는 A 를 좁히는
      말**이다. A 를 별칭으로 내는 것은 고시를 읽는 것이지 지어내는 것이
      아니다 (R5). ⑦-a-2 에서 꼬리(B·C)를 뺀 것과 **같은 축의 반대쪽**이다 -
      머리는 안전하고 꼬리는 안전하지 않다.

      이것이 없으면 `전기토스터(팝업, 오븐 포함)` 는 상품명에 그 문자열이
      통째로 있어야 맞는다. 그런 상품명은 없다.

    ⚠ `rstrip(")")` 을 **뺐다.** 옛 조각(`'블라인드)'`)을 다듬으려고 넣었던
      것인데, 합친 예시에 걸리면 **여는 괄호만 남은 문자열**이 된다
      (`'전기토스터(팝업, 오븐 포함'`). 그런 별칭은 영원히 아무것도 못 맞힌다 -
      ⑦-a-2 직후 57개가 그랬다. 머리 낱말이 그 자리를 대신한다.
    """
    out: dict[str, list[str]] = collections.defaultdict(list)
    for row in table().get("items") or ():
        for raw in row.get("examples") or ():
            full = str(raw).strip()
            head = full.split("(")[0].strip() if "(" in full else ""
            for word in (full, head):
                if 2 <= len(word) <= 20 and row["item"] not in out[word]:
                    out[word].append(row["item"])
    return {k: tuple(v) for k, v in out.items()}


@lru_cache(maxsize=1)
def rf_book():
    """이 표만 담은 `ItemGradeBook`. 측정 전용이다.

    ⚠ `ItemGradeBook` 은 어린이 표를 함께 읽는다. 여기서는 전파 표만 재야
      하므로 빈 어린이 표를 끼운다 - 섞으면 무엇이 붙었는지 못 가린다.
    """
    import tempfile

    from .item_grades import ItemGradeBook

    empty = Path(tempfile.mkdtemp()) / "child.yaml"
    empty.write_text(yaml.safe_dump(
        {"items": [], "catch_all": {"applies_to": "-", "grade": "-", "standard": "-",
                                    "source": "-", "source_text": "-",
                                    "statement_ko": "-"}},
        allow_unicode=True), encoding="utf-8")
    return ItemGradeBook(path=_PATH, child_path=empty)
