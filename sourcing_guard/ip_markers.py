"""지재권 표기어 — [L-2]. `data/ip_markers.yaml` 이 정본이다.

⚠⚠ **판정이 아니다. 안내 축이다.** 이 파일이 답하는 것은 하나다 —
  "상표·디자인권과 관련된 말이 상세페이지에 적혀 있는가."

  적혀 있다는 사실과 권리를 침해한다는 판단은 완전히 다르고, 뒤쪽은 우리가
  할 수 있는 일이 아니다 (R1). 그래서 **브랜드명 사전을 만들지 않는다** -
  만드는 순간 "이 상품은 OO 상표를 쓴다" 를 우리가 말하게 된다 (R5).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

_PATH = Path(__file__).with_name("data") / "ip_markers.yaml"


@lru_cache(maxsize=1)
def _table() -> dict:
    try:
        return yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):  # pragma: no cover - 파일이 깨져도 검증은 돈다
        return {}


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[str, "re.Pattern[str]"], ...]:
    out = []
    for row in _table().get("표지어") or ():
        pat = row.get("패턴") or row.get("key")
        if not pat:
            continue
        # 정규식이 아니면 글자 그대로 찾는다. yaml 에 정규식을 쓰는 자리가
        # 하나뿐이라(`st`) 기본은 리터럴이다 - 기본이 정규식이면 '(' 같은
        # 글자가 든 낱말을 넣었을 때 조용히 터진다.
        rx = re.compile(pat if row.get("정규식") else re.escape(pat))
        out.append((row["key"], rx))
    return tuple(out)


def ip_marker_in(text: str | None) -> str | None:
    """표기어가 보이면 그 **표기어 이름**을 돌려준다. 없으면 None.

    ⚠ 돌려주는 것은 화면에 인용할 이름(`호환`·`st`)이지 걸린 글자가 아니다.
      걸린 글자를 그대로 쓰면 정규식 경로에서 '아st' 같은 조각이 인용된다.
    """
    if not text:
        return None
    for key, rx in _compiled():
        if rx.search(text):
            return key
    return None


def ip_marker_sources() -> tuple[dict, dict]:
    """(상표법, KIPRIS) 근거. 둘 다 `data/ip_markers.yaml` 이 정본이다."""
    src = _table().get("근거") or {}
    return src.get("상표법", {}), src.get("kipris", {})
