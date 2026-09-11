"""도매꾹 응답 필드를 읽는 공통 규칙. **여기가 한 곳이다.**

정제(`domeggook_pii`)와 측정(`scripts/`) 이 같은 판정을 써야 한다. 두 곳에
같은 목록을 두면 갈라진다 - 이 저장소의 반복 결함이다.

담는 것
-------
1. **"채워져 있지만 내용은 없는" 표기** — 고시 항목이 값을 갖고 있지만 그
   값이 "상세설명참조" 류인 경우. 참조.md §7 이 탐침 1건에서 6개 중 5개가
   이 류였다고 적었고, **그 비율이 이 API 가 상세페이지를 대신하는 정도다.**
2. **고시 항목 이름** — 「전자상거래 등에서의 상품 등의 정보제공에 관한
   고시」 문구 그대로다. 짧은 이름이 아니다(참조.md §7 실호출 확인).
"""
from __future__ import annotations

import re

from .placeholders import is_not_a_value

# ── 1. 내용 없는 표기 ────────────────────────────────────────────────
#
# 실측(2026-09-08 · 상세 100건)에서 나온 것만 넣는다. 짐작으로 늘리지 않는다.
#
#   상세설명참조 / 상세설명 참조 / 상세설명참조 / 상세설명참조   ← 슬래시로 이은 것도 있다
#   [상세정보 별도표기]
#   상세페이지 참조 · 상세페이지참조
#   -  ·  '' (빈 값)
#: ⚠ **더 이상 판정에 쓰이지 않는다** (2026-09-12). 소유자는 `placeholders.NOT_A_VALUE`
#: 다. 여기 남긴 것은 "도매꾹 응답에서 이 표기를 봤다" 는 실측 기록이다 -
#: 지우면 그 출처를 잃는다.
_PLACEHOLDER_CORE = (
    "상세설명참조",
    "상세설명 참조",
    "상세정보별도표기",
    "상세정보 별도표기",
    "상세페이지참조",
    "상세페이지 참조",
    "상품상세참조",
    "상품상세 참조",
    "본문참조",
    "본문 참조",
)

_STRIP = re.compile(r"[\[\]()\s]+")


def _norm(value: str) -> str:
    return _STRIP.sub("", value or "")


def is_placeholder(value: str | None) -> bool:
    """값이 있으나 내용이 없는가.

    ⚠ **판단은 `placeholders.is_not_a_value` 가 한다** (2026-09-12). 전에는 이
      함수가 `_PLACEHOLDER_CORE` 로 직접 판정했고, 같은 판단이 여섯 곳에
      흩어져 LLM 경로가 뒤처졌다 - 그 모듈 머리 주석 참조. 이름은 호출부가
      많아 그대로 두고 위임만 한다.

    ⚠ 그래서 이제 "해당없음"·"미상"·"N/A" 도 참이다. 전에는 거짓이었다 -
      A-4 의 `내용없음` 플래그와 A-5 필드 수치가 그만큼 움직인다.
    """
    return is_not_a_value(value)


# ── 2. 고시 항목 이름 ────────────────────────────────────────────────
#
# ⚠ "KC인증 필 유무" 가 아니다. 이름으로 항목을 찾을 때 이 긴 문구를 쓴다.
INFODUTY_CERT = "법에 의한 인증·허가 등을 받았음을 확인할 수 있는 경우 그에 대한 사항"
INFODUTY_NAME_MODEL = "품명 및 모델명"
INFODUTY_ORIGIN = "제조국 또는 원산지"
INFODUTY_MAKER = "제조사"
INFODUTY_CONTACT = "A/S 책임자와 전화번호 또는 소비자상담 관련 전화번호"

#: 연락처를 담는 항목을 이름으로 가릴 때 쓰는 조각. 고시 문구가 품목분류에
#: 따라 달라지므로 완전일치로 찾지 않는다.
CONTACT_NAME_MARKERS: tuple[str, ...] = ("A/S 책임자", "소비자상담", "전화번호")


def infoduty_rows(item: dict) -> list[dict]:
    """`detail.infoDuty.item` 을 리스트로. 없으면 빈 리스트."""
    info = (item.get("detail") or {}).get("infoDuty")
    if not isinstance(info, dict):
        return []
    rows = info.get("item")
    if isinstance(rows, dict):
        rows = [rows]
    return [r for r in (rows or []) if isinstance(r, dict)]


def safety_certs(item: dict) -> list[dict]:
    """`detail.safetyCert` 를 리스트로.

    ⚠ 실호출에서 **배열**이었고 `null` 일 수도 있다(참조.md §7). 20/100 건만
      갖고 있었다. 값의 진위는 우리가 SafetyKorea 에 대조해서 확인한다 -
      공급사가 입력한 값이다(CLAUDE.md R4).
    """
    sc = (item.get("detail") or {}).get("safetyCert")
    if isinstance(sc, dict):
        sc = [sc]
    return [c for c in (sc or []) if isinstance(c, dict)]


_TAG = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>|<[^>]+>")
_WS = re.compile(r"[ \t\xa0]+")


def html_to_text(html: str | None) -> str:
    """상세 HTML 에서 태그를 떼고 보이는 텍스트만.

    ⚠ **이미지 안의 글자는 오지 않는다.** `desc.contents.item` 은 대부분
      `<img>` 나열이고, 그래서 태그를 떼면 길이가 0 에 가깝다. 그 0 인 비율이
      "이 API 가 상세페이지를 대신하는가" 의 답이다 - 길이를 세는 이유다.
    """
    if not html:
        return ""
    import html as _html

    s = _TAG.sub(" ", str(html))
    s = _html.unescape(s)
    s = _WS.sub(" ", s)
    return "\n".join(line.strip() for line in s.splitlines() if line.strip())
