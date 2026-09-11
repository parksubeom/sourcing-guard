"""[H] 도매꾹 상세(구조화 필드) → `ProductFacts`. **LLM 0회.**

`getItemView` 의 `basis.title` · `detail.model` · `detail.manufacturer` ·
`detail.safetyCert[]` · `detail.infoDuty.item[]` 를 그대로 옮긴다. 상세페이지 텍스트를
읽지 않으므로 추출기가 없어도 돈다 - 셀러의 소싱처가 도매꾹이면 이것이 첫 입력이다.

⚠⚠ **고시 품목분류(`infoDuty.type`)를 전안법 품목군(`legal_item_name`)으로 옮기지 않는다.**
  둘은 다른 법의 다른 분류다. 실측(2026-09-12 · 190건): `infoDuty.type` 17종 중 등급표
  품목명과 같은 것은 "의류" 하나, 상품 수로 **3/190**. 113/190 은 "기타 재화" 다.
  옮기면 "기타 재화" 가 품목이 되거나 "가정용 전기제품(냉장고/…)" 이 세부품목이 된다 -
  없는 의무를 만드는 방향이다. `legal_item_name` 은 항상 None, `category` 는 UNCLASSIFIED.
  분류는 규칙·추출기의 일이다 (R1).

⚠ **값이 아닌 값을 값으로 넘기지 않는다 (R3).** 판단은 `placeholders` 한 곳이 한다
  (2026-09-12 · 전에는 이 모듈이 자기 목록을 들고 있었다). 도매꾹은 미입력을 "해당없음"
  으로 채운다 - 실측 `model="해당없음"` 71/190. 그대로 넘기면 모델명 "해당없음" 으로
  리콜 대조를 한다.

⚠ 항목 이름은 **관찰된 것만** 쓴다 (R5). 190건 `infoDuty.item[].name` 빈도:
  품명 및 모델명 170 · 법에 의한 인증·허가… 113 · 제조사 113 · 제조자 75 · KC 인증정보 43 ·
  재질 26 · 사용연령 또는 권장사용연령 10. 이 밖의 이름은 읽지 않는다.

⚠ `safetyCert[].no` 는 **공급사 입력값**이다. 우리는 입력으로 받아 SafetyKorea 에 대조한다
  (R4 주석). `cert=Y` 이고 `useNo=Y` 이고 값이 placeholder 가 아닐 때만 받는다 (참조.md §6).
"""
from __future__ import annotations

import re

from .domeggook_fields import (
    INFODUTY_CERT,
    INFODUTY_MAKER,
    INFODUTY_NAME_MODEL,
    infoduty_rows,
    safety_certs,
)
from .placeholders import clean, is_not_a_value
from .kats_client import CERT_NUMBER_RE, normalize_kc
from .models import ItemCategory, ProductFacts

#: 관찰된 항목 이름 (R5). 부분 일치가 아니라 **정확 일치**다 - 이름은 고시가 정한다.
_ROW_MODEL = {INFODUTY_NAME_MODEL}
_ROW_CERT = {INFODUTY_CERT, "KC 인증정보"}
_ROW_MAKER = {INFODUTY_MAKER, "제조자"}
_ROW_MATERIAL = {"재질"}
_ROW_AGE = {"사용연령 또는 권장사용연령"}

_SPLIT = re.compile(r"\s*[/,·]\s*")


def is_value(raw: object) -> bool:
    """실제 값인가. 판단은 `placeholders` 가 한다 - 소유자는 하나다 (§6)."""
    return not is_not_a_value(None if raw is None else str(raw))


def _rows_named(item: dict, names: set[str]) -> list[str]:
    return [str(r.get("desc") or "") for r in infoduty_rows(item) if r.get("name") in names]


def _parts(raw: str) -> list[str]:
    """`A / B` 꼴을 조각으로. 조각마다 값인지 본다 - 한쪽만 placeholder 일 수 있다."""
    return [p for p in (s.strip() for s in _SPLIT.split(raw)) if is_value(p)]


def infoduty_type(item: dict) -> str | None:
    info = (item.get("detail") or {}).get("infoDuty")
    return (info or {}).get("type") if isinstance(info, dict) else None


def kc_numbers_from(item: dict) -> list[str]:
    """`safetyCert[].no` (cert=Y · useNo=Y · 값) + 고시 인증 항목 desc 의 번호 모양. 중복 제거."""
    out: list[str] = []
    for c in safety_certs(item):
        if str(c.get("cert", "")).upper() != "Y" or str(c.get("useNo", "")).upper() != "Y":
            continue
        no = clean(c.get("no"))
        if no:
            out.append(no)
    for desc in _rows_named(item, _ROW_CERT):
        if is_value(desc):
            out.extend(m.group(0) for m in CERT_NUMBER_RE.finditer(desc))
    seen: set[str] = set()
    uniq = []
    for n in out:
        k = normalize_kc(n)
        if k and k not in seen:
            seen.add(k)
            uniq.append(n)
    return uniq


def facts_from_item(item: dict, *, page_url: str | None = None) -> ProductFacts:
    """정제된 `getItemView` 상품 하나 → ProductFacts. 판정 필드는 만들지 않는다."""
    basis = item.get("basis") or {}
    detail = item.get("detail") or {}

    model = clean(detail.get("model"))
    if not model:
        # 고시 "품명 및 모델명" 은 `품명 / 모델명` 꼴이다. 모델 조각(뒤쪽)만 본다.
        for desc in _rows_named(item, _ROW_MODEL):
            parts = _parts(desc)
            if len(parts) >= 2:
                model = parts[-1]
                break

    maker = clean(detail.get("manufacturer"))
    if not maker:
        for desc in _rows_named(item, _ROW_MAKER):
            v = clean(desc)
            if v:
                maker = v
                break

    materials: list[str] = []
    for desc in _rows_named(item, _ROW_MATERIAL):
        materials.extend(_parts(desc))

    age = None
    for desc in _rows_named(item, _ROW_AGE):
        age = clean(desc)
        if age:
            break

    return ProductFacts(
        product_name=clean(basis.get("title")),
        model_name=model,
        maker=maker,
        materials=materials,
        kc_numbers=kc_numbers_from(item),
        target_age=age,
        # ⚠ 고시 품목분류를 옮기지 않는다 - 머리 주석.
        legal_item_name=None,
        category=ItemCategory.UNCLASSIFIED,
        source_page_url=page_url,
    )
