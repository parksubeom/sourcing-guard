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
    """
    out: dict[str, list[str]] = collections.defaultdict(list)
    for row in table().get("items") or ():
        for raw in row.get("examples") or ():
            word = str(raw).strip().rstrip(")")
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
