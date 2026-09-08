"""4-e′. `category=out_of_scope` 는 등급표 조회를 **계속 막는다.**

⚠ **2026-09-08 에 열었다가 2026-09-09 에 되돌렸다.** 이 검사는 닫힌 상태를
  잠그고, **왜 되돌렸는지**를 다음 사람에게 남긴다 — 안 남기면 같은 이유로
  다시 열려 한다.

연 이유
-------
도매꾹 고시 `type`(주방용품 등)이 추출기의 `category` 를 `out_of_scope` 로
밀어내고, **고시 품목분류와 전안법 품목군은 다른 분류다.** 상세 109 에서
[146] 방수매트 → 매트류, [165] 앞치마 → 의류가 회복되어 정답 89 → 91 이 됐다.

되돌린 이유 — 통과 기준에 없던 숫자가 움직였다
-----------------------------------------------
    Claude 235 재생 · 애매 47 → 부착   1 → **2**
    GPT 235 재생 · 애매 부착           3 → **4**   (같은 줄)

    [26] 아임명작 청정 북유럽 에어프라이어 종이호일 → 전기오븐기기

26번은 2026-09-07 에 "종이호일이면 식약처 소관이고 '에어프라이어' 는 용도어라
전기오븐기기는 오답" 으로 판정해 대상 → 애매로 옮긴 줄이다. 즉 **LLM 의
out_of_scope 가 맞았던 경우**를 게이트가 뚫었다. 분모 밖이라 정답률에는 안
보이지만 화면에서 종이호일이 '전기오븐기기 · 안전인증' 을 받는다.

가를 방법을 찾지 못했다 — 넷을 쟀다
-------------------------------------
    매칭 출처            셋 다 LLM 의 product_name · matched_by=alias
    걸린 키              26 '에어프라이어' · 146 '방수매트' · 165 '토시'
    out_of_scope_reason  셋 다 None
    has_consumable_hint  셋 다 False

`raw_text` 는 관여하지 않으므로 "원본에만 있는 키는 버린다" 규칙은 아무것도
바꾸지 않는다. 상한 +1 · 상세 정답 +2 를 얻으려고 애매 오부착을 사는 거래는
하지 않는다.
"""
from __future__ import annotations

from datetime import date

import pytest

from sourcing_guard.item_grades import ALIASES, normalize
from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import ItemCategory, ProductFacts
from sourcing_guard.scoping import out_of_scope_reason
from sourcing_guard.verifier import RuleBook, _item_grade_findings, verify

_KATS = KatsClient(None, None, mock=True)
_RULES = RuleBook()

# 세 줄의 LLM 상품명. 실측값이다 (단건경로_*.json · 도매꾹_AB_*.json).
_PAPER_FOIL = "아임명작 청정 북유럽 에어프라이어 종이호일"        # [26] 애매
_MAT = "무독성 사계절 다용도 방수매트 김장매트 180cm 특대형"      # [146] 대상
_APRON = "일회용 방수 미술 물감 앞치마+팔토시(2개) 세트"           # [165] 대상


def _items(facts: ProductFacts) -> list[str]:
    findings = verify(facts, _KATS, _RULES, None)
    return [c["item"] for f in findings
            for c in (f.detail or {}).get("candidates", [])]


# ── 게이트는 닫혀 있다 ───────────────────────────────────────────────
@pytest.mark.parametrize("name", [_PAPER_FOIL, _MAT, _APRON])
def test_out_of_scope_blocks_the_grade_lookup(name):
    """열면 셋이 **함께** 열린다 - 그래서 26번 오부착을 피할 수 없다."""
    blocked = ProductFacts(product_name=name,
                           category=ItemCategory.OUT_OF_SCOPE)
    assert _items(blocked) == [], name

    # 다른 category 에서는 붙는다 - 게이트가 유일한 차이라는 뜻이다.
    open_cat = ProductFacts(product_name=name,
                            category=ItemCategory.UNCLASSIFIED)
    assert _items(open_cat), name


def test_the_legal_name_fallback_is_not_disabled_anywhere():
    """4-e 가 함께 넣었던 폴백 차단도 되돌렸다.

    게이트가 닫혀 있으면 `out_of_scope` 에서 폴백을 끌 자리가 없다 - 조회
    자체가 안 일어난다. 조건을 남겨 두면 읽는 사람이 그 분기가 산다고 믿는다.
    """
    from pathlib import Path

    src = Path("sourcing_guard/verifier.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "_legal_for_lookup" not in code
    assert "legal_name=facts.legal_item_name" in code


# ── 되돌린 근거를 잠근다 ─────────────────────────────────────────────
def test_none_of_the_four_signals_separates_26_from_146_and_165():
    """다시 열려는 사람이 먼저 이 검사를 보게 한다.

    넷 중 하나라도 갈라지게 되면 여기가 깨지고, 그때 게이트를 다시 열지
    판단한다.
    """
    today = date(2026, 9, 9)

    def matched(name: str) -> list[tuple[str, str]]:
        found = _item_grade_findings(name, today)
        return [(c["item"], c.get("matched_by"))
                for f in found for c in (f.detail or {}).get("candidates", [])]

    # (1) 매칭 출처가 같다 - 셋 다 LLM 상품명에서 alias 로 걸린다.
    for name in (_PAPER_FOIL, _MAT, _APRON):
        got = matched(name)
        assert got, name
        assert all(how == "alias" for _item, how in got), got

    # (2) 하드 소관 근거가 없다.
    for name in (_PAPER_FOIL, _MAT, _APRON):
        assert out_of_scope_reason(name) is None, name

    # (3) 소모품 힌트가 없다 - 26번을 가려낼 수 있었던 신호다.
    from sourcing_guard.matcher import has_consumable_hint

    for name in (_PAPER_FOIL, _MAT, _APRON):
        assert has_consumable_hint(name) is False, name

    # (4) 걸린 별칭 키. 26번은 **용도어**이고 나머지는 물건 이름이다 -
    #     그 차이를 코드가 아직 모른다.
    def keys(name: str) -> list[str]:
        n = normalize(name)
        return sorted((k for k in ALIASES if normalize(k) and normalize(k) in n),
                      key=len, reverse=True)

    assert "에어프라이어" in keys(_PAPER_FOIL)
    assert "방수매트" in keys(_MAT)
    assert "토시" in keys(_APRON)


def test_paper_foil_is_classified_as_vague_not_as_target():
    """26번이 애매인 것이 이 이야기의 전제다. 대상으로 돌아가면 계산이 바뀐다."""
    from pathlib import Path

    tsv = Path("tests/fixtures/새표본235_대상분류.tsv").read_text(encoding="utf-8")
    row = next(l for l in tsv.splitlines()
               if not l.startswith("#") and l.split("\t")[0] == "26")
    _no, verdict, _name, why = row.split("\t")
    assert verdict == "애매", row
    assert "종이호일" in why and "에어프라이어" in why
