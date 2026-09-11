"""**"이 문자열은 값이 아니다" 의 소유자가 하나인지** 잠근다 (판정 1+2 · 2026-09-12).

CLAUDE.md §6: 같은 판단을 두 곳에 적지 마라. 2026-09-12 에 이 판단이 여섯 곳에
흩어져 있었고, 그래서 뒤처진 것이 LLM 경로였다 - `model_name` 이 값 아닌 문자열인
줄 34건이 그 값으로 리콜 대조를 했다고 말했다.

⚠⚠ 4-r 과 같은 뿌리다. 4-r 은 "대조하지 않고 대조했다고 말한 것", 이것은 "값이 아닌
  문자열을 값으로 읽어 대조한 것" - 둘 다 "오류 표시가 없으면 성공" 의 친척이다.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from sourcing_guard import domeggook_adapter, domeggook_fields, kats_client, placeholders, watchlist
from sourcing_guard.models import ProductFacts
from tests.srccheck import code_only

_ROOT = Path(__file__).resolve().parents[1]


# ── 소유자의 동작 ──────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "해당없음", "해당 없음", "해당사항없음", "없음", "미상", "미기재",
    "N/A", "n/a", "-", "", "   ", None,
    "상세설명참조", "상세설명 참조", "상세페이지", "본문참조",
    "[상세정보 별도표기]",                      # 대괄호 표기 - 실측
    "상세설명참조 / 상세설명참조",               # 조각 전부가 자리표시자
])
def test_these_are_not_values(raw):
    assert placeholders.is_not_a_value(raw) is True
    assert placeholders.clean(raw) is None


@pytest.mark.parametrize("raw", [
    "BLK-100", "K2018", "블록 완구 세트", "지에스켐", "ABS", "ABS(플라스틱)",
    "블록 완구 / BLK-100",                      # 한쪽이 값이면 값이다
    "3세 이상", "CB061R2170-3018", "BLACK",     # 색상은 값이다 - 모델명 판정과 다르다
])
def test_these_are_values(raw):
    assert placeholders.is_not_a_value(raw) is False
    assert placeholders.clean(raw) == raw.strip()


def test_the_whole_string_is_checked_before_the_parts():
    """⚠ `N/A` 는 `/` 로 쪼개면 `N`·`A` 가 되어 통과한다 - 실제로 그렇게 짰다가 걸렸다."""
    assert placeholders.is_not_a_value("N/A") is True
    assert "whole" in inspect.getsource(placeholders.is_not_a_value)


def test_clean_never_rewrites_the_value():
    """정규화이지 교정이 아니다 (R5). 값이면 원문 그대로 돌려준다."""
    for raw in ("  BLK-100  ", "지에스켐/상세설명참조"):
        assert placeholders.clean(raw) == raw.strip()


def test_every_entry_has_a_source_comment():
    """항목마다 출처를 적는다 (R5). 출처 없는 문자열을 끼워 넣으면 정당한 값을 잃는다."""
    src = inspect.getsource(placeholders)
    body = src[src.index("NOT_A_VALUE: frozenset"):src.index("#: 조각 구분자")]
    # 항목 줄 사이에 근거 주석이 있어야 한다 - 실측 날짜·문서 이름·상품번호.
    assert re.search(r"실측 2026-09-12", body)
    assert "21114291" in body, "홑말 '상세페이지' 의 출처(상품번호)가 없다"
    assert "참조.md" in body and "설계서" in body
    assert body.count("#") >= 8, "주석이 항목 수에 비해 적다 - 출처 없는 항목이 있나"


# ── 소유자가 하나다 ────────────────────────────────────────────────
def test_the_six_sites_call_the_owner_instead_of_judging():
    """여섯 자리가 자기 판정을 하지 않고 소유자를 부른다."""
    # ① domeggook_fields.is_placeholder → 위임만
    body = code_only(inspect.getsource(domeggook_fields.is_placeholder))
    assert "is_not_a_value ( value )" in body
    assert "_PLACEHOLDER_CORE" not in body, "아직 자기 목록으로 판정한다"

    # ② domeggook_adapter → 자기 목록이 없다
    src = code_only(inspect.getsource(domeggook_adapter))
    assert "NOT_A_VALUE" not in src, "어댑터가 자기 목록을 들고 있다"
    assert "from . placeholders import" in src

    # ③④ watchlist 판정 함수가 층 1 을 먼저 부른다
    for fn in (watchlist.is_model_placeholder, watchlist.is_maker_placeholder):
        assert "is_not_a_value (" in code_only(inspect.getsource(fn)), fn.__name__

    # ⑤ kats_client.is_cert_number 도 층 1 을 부른다
    assert "is_not_a_value (" in code_only(inspect.getsource(kats_client.is_cert_number))


def test_layer_two_does_not_repeat_layer_one():
    """층 2("모델명/업체명/인증번호가 아니다")가 층 1 항목을 다시 들고 있지 않다.

    ⚠ 겹치면 한쪽만 고쳐도 나머지가 뒤처진다 - 그게 이번 문제의 원인이었다.
    """
    one = {placeholders.normalize(x) for x in placeholders.NOT_A_VALUE}
    for name, layer2 in (
        ("watchlist._MODEL_PLACEHOLDERS", watchlist._MODEL_PLACEHOLDERS),
        ("watchlist._MAKER_PLACEHOLDERS", watchlist._MAKER_PLACEHOLDERS),
        ("kats_client.CERT_PLACEHOLDERS", kats_client.CERT_PLACEHOLDERS),
    ):
        dup = sorted(x for x in layer2 if placeholders.normalize(x) in one)
        assert not dup, f"{name} 이 층 1 항목을 다시 들고 있다: {dup}"


def test_layer_two_still_judges_its_own_domain():
    """층 2 고유 판단은 살아 있어야 한다 - 색상명·필드라벨은 모델명이 아니다."""
    assert watchlist.is_model_placeholder("BLACK") is True
    assert watchlist.is_model_placeholder("비대상") is True
    assert watchlist.is_model_placeholder("BLK100") is False
    assert watchlist.is_maker_placeholder("회사정보없음") is True
    assert watchlist.is_maker_placeholder("지에스켐") is False
    assert kats_client.is_cert_number("공급자적합성") is False
    assert kats_client.is_cert_number("CB061R2170-3018") is True
    # ⚠ 색상은 `materials` 에서는 살아야 한다 - 층 1 이 아니기 때문이다.
    assert placeholders.clean("BLACK") == "BLACK"


def test_the_watchlist_comment_records_that_r6_is_unrelated():
    """R6 의 오류 비대칭은 매칭 강도에 걸리는 것이지 자리표시자 판정이 아니다."""
    body = inspect.getsource(watchlist.is_model_placeholder)
    assert "R6" in body and "매칭 강도" in body


# ── ProductFacts 가 모든 경로를 태운다 ─────────────────────────────
def test_product_facts_drops_placeholders_on_every_path():
    """LLM · 어댑터 · 재생 · 목 전부가 이 validator 를 지난다.

    ⚠ extractor 후처리에만 두면 재생이 안 타서 "재생으로 닫는다" 가 성립하지 않는다.
    """
    f = ProductFacts(
        product_name="블록 완구", model_name="해당없음", maker="상세설명참조",
        materials=["ABS", "상세설명참조"], substances_mentioned=["-"],
        target_age="N/A", legal_item_name="미상",
        kc_numbers=["CB061R2170-3018"], rf_numbers=["R-C-ABC-DEF123"],
    )
    assert f.model_name is None and f.maker is None
    assert f.target_age is None and f.legal_item_name is None
    assert f.materials == ["ABS"] and f.substances_mentioned == []
    assert f.product_name == "블록 완구"
    # ⚠ 인증·전파 번호는 건드리지 않는다 - 정규식이 형식을 본다.
    assert f.kc_numbers == ["CB061R2170-3018"] and f.rf_numbers == ["R-C-ABC-DEF123"]


def test_the_validator_is_on_the_model_not_only_the_extractor():
    src = (_ROOT / "sourcing_guard/models.py").read_text(encoding="utf-8")
    assert "_drop_placeholder_text" in src and "_drop_placeholder_items" in src
    assert "재생이 안 타서" in src, "이 자리에 둔 이유가 적혀 있지 않다"
    # 프롬프트는 건드리지 않았다 (R7).
    assert "프롬프트는 건드리지 않았다" in src


def test_placeholder_model_name_no_longer_allows_a_recall_comparison():
    """⚠⚠ 이것이 판정 1+2 의 목적이다.

    전에는 `model_name="해당없음"` 으로 `can_compare()` 가 True 가 되어 "리콜
    대조했다" 고 말했다. 사본에 같은 문자열이 있으면 가짜 일치다 (R3).
    """
    from datetime import date

    from sourcing_guard.recall_index import RecallIndex

    class _Empty(RecallIndex):
        def __init__(self): self._records = []; self._as_of = None

    idx = _Empty()
    bad = ProductFacts(product_name="무선 청소기", model_name="해당없음", maker="상세설명참조")
    good = ProductFacts(product_name="무선 청소기", model_name="ZQ-VC300")
    assert idx.can_compare(bad, today=date(2026, 9, 12)) is False
    assert idx.can_compare(good, today=date(2026, 9, 12)) is True


def test_the_kats_field_map_stays_the_owner_of_cert_state():
    """`cert_state_not_stated` 는 매핑 파일이 소유한다 - 설계서가 정하는 값이다.

    ⚠ 목록이 층 1 과 같아 보이지만 소유자가 다르다. 코드로 옮기면 "필드명·값을
      하드코딩하지 않고 매핑에서 주입한다"(R5 · §6)와 충돌한다.
    """
    yaml_text = (_ROOT / "sourcing_guard/data/kats_field_map.yaml").read_text(encoding="utf-8")
    assert "cert_state_not_stated" in yaml_text
    # ⚠ 코드만 본다. 이 사실을 **설명하는 주석**이 소유자 모듈에 있는 것이 정상이다.
    assert "cert_state_not_stated" not in code_only(inspect.getsource(placeholders))
    assert "매핑에서 주입" in inspect.getsource(placeholders)
