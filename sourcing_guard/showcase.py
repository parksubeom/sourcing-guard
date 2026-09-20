"""도매꾹 상품 리스트 — **미리 조회해 둔 실상품 카드.**

왜 사본인가 (총괄 지시 2026-09-20 [P4])
---------------------------------------
셀러가 직접 타이핑하기 전에, 도매꾹에 **실제로 올라와 있는 상품**을 보여 주고
클릭하면 우리 검사 결과를 보여 준다. 결과는 미리 조회해 사본에 넣는다 -
배포본(도쿄)에서 국표원 조회가 막혀 있어도 **이 경로는 반드시 답이 나온다.**

체험 표본(`samples.py`)과 같은 갈래이고 다른 점이 둘이다:

    samples    우리가 **고른** 열 개. 기간만료·취소를 일부러 넣었다
    showcase   도매꾹 랭킹순 상위에서 **그냥 걸린** 것. 고르지 않았다

⚠⚠ **여기서 문장을 만들지 않는다.** 담기는 것은 `scripts/build_showcase.py` 가
  받은 `/api/v1/scan` 응답 그대로이고, 이 모듈은 카드에 그릴 조각만 고른다.
  문구를 손으로 고치면 화면이 우리 서버가 낸 적 없는 문장을 말한다 (R5).

⚠⚠ **리스트에 신호를 칠하지 않는다** (총괄 지시). 카드는 제목·썸네일·가격·
  최소수량만 그린다. 신호는 **누른 뒤에** 처음 나온다.

  이유: 목록에 빨강·노랑이 늘어서면 그 자체가 "이 판매자는 위험" 이라는
  평가로 읽힌다. 우리가 한 것은 상세페이지에 적힌 인증번호를 정부 DB 에
  조회한 것뿐이고, 그것은 상품이나 판매자에 대한 평가가 아니다 (§9).
  그래서 카드 payload 에는 **신호를 아예 넣지 않는다** - 화면이 실수로
  칠할 수 있는 값을 주지 않는 것이 문구로 당부하는 것보다 강하다.

⚠ 사본은 낡는다. 참조.md: "판매중지·판매종료·품절·단종은 결과에 포함되지
  않는다." 목록에 나온 순간에는 판매중이었지만 내일은 아닐 수 있다 - 그래서
  화면이 **기준일**을 적고 도매꾹 원문으로 링크한다.

⚠ 파일이 없거나 깨지면 **빈 목록**이다. 빈 껍데기를 그리지 않는다 - 화면은
  이 구역을 통째로 숨긴다 (`demos.preview()` · `samples.payload()` 와 같은 규칙).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

SHOWCASE_PATH = Path(__file__).resolve().parent / "data" / "showcase.json"

#: 썸네일이 놓이는 곳. `scripts/build_showcase.py` 가 200px webp 로 저장한다.
THUMB_URL_PREFIX = "/static/showcase/"

#: 결과 화면 아래 한 줄. **총괄이 문장을 지정했다** - 손대지 않는다.
RESULT_NOTE = (
    "이 결과는 상세페이지에 적힌 인증번호를 정부 DB 에 조회한 것이며, "
    "상품이나 판매자에 대한 평가가 아닙니다."
)


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    try:
        return json.loads(SHOWCASE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("도매꾹 상품 리스트를 읽지 못했습니다: %s", exc)
        return {}


def _card(item: dict[str, Any]) -> dict[str, Any] | None:
    """카드 한 장. **신호·결과는 넣지 않는다** (머리 주석).

    ⚠ 결과를 목록에 함께 실으면 응답이 1MB 가 넘는다(실측 29건에 965KB).
      누른 상품 하나만 `/api/v1/showcase/<번호>` 로 받는다.
    """
    no = str(item.get("no") or "").strip()
    if not no or not item.get("title") or not item.get("result"):
        return None
    return {
        "no": no,
        "title": item["title"],
        "thumb": THUMB_URL_PREFIX + item["thumb_file"] if item.get("thumb_file") else None,
        "url": item.get("url"),
        "price": item.get("price"),
        "unit_qty": item.get("unitQty"),
    }


def payload() -> dict[str, Any]:
    """`/api/v1/showcase` 가 내는 것. 파일이 없으면 `items` 가 빈 목록이다."""
    raw = _raw()
    cards = [c for c in (_card(i) for i in raw.get("items") or []) if c]
    return {
        # ⚠ 날짜는 **파일에 적힌 수집일**이다. 화면이 "2026-09-20 기준 도매꾹
        #   판매중 상품" 이라고 말하므로 손으로 적으면 그 문장이 거짓이 된다.
        "as_of": raw.get("as_of"),
        "scanned_at": raw.get("scanned_at"),
        "surveyed": raw.get("surveyed"),
        "categories": raw.get("categories") or [],
        "result_note": RESULT_NOTE,
        "items": cards,
    }


def result_of(no: str) -> dict[str, Any] | None:
    """상품 하나의 **기록된 스캔 결과**. 없으면 None.

    ⚠ `page_text` 를 함께 준다. 화면이 입력란을 채워 셀러가 **지금 다시
      검사**할 수 있게 하기 위해서다 - 기록만 보여 준다는 의심에 대한 답이
      화면 안에 있어야 한다 (`samples` 와 같은 이유).
    """
    for item in _raw().get("items") or []:
        if str(item.get("no") or "") == str(no):
            return {
                "no": str(item["no"]),
                "title": item.get("title"),
                "url": item.get("url"),
                "page_text": item.get("page_text"),
                "scanned_at": _raw().get("scanned_at"),
                "result_note": RESULT_NOTE,
                "result": item.get("result"),
            }
    return None
