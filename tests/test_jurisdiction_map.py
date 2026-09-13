"""[L-1] 소관 안내 — **안내 축이다. 판정이 아니다.**

지켜야 할 것 (미완 §1-d · 총괄 정의):

    신호등을 바꾸지 않는다 · 등급을 붙이지 않는다
    다섯 숫자 0/0/0/0/0 · ④ 비대상 부착은 정의상 움직일 수 없다
    새 `FindingKind` 를 만들지 않는다
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts
from sourcing_guard.scoping import (
    OUT_OF_SCOPE_HINTS,
    jurisdiction_for,
    jurisdiction_line,
)
from sourcing_guard.verifier import RuleBook, verify

_ROOT = Path(__file__).resolve().parents[1]
_YAML = _ROOT / "sourcing_guard/data/jurisdiction_map.yaml"


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return yaml.safe_load(_YAML.read_text(encoding="utf-8"))["소관"]


def _kats():
    k = MagicMock()
    k.lookup_certification_cached.return_value = MagicMock(record=None)
    return k


# ── 매핑 자체 ──────────────────────────────────────────────────────
def test_every_key_matches_a_real_out_of_scope_reason(rows):
    """⚠ 키가 갈리면 안내가 **조용히 사라진다.** 두 목록을 대조한다."""
    keys = {r["key"] for r in rows}
    missing = sorted(set(OUT_OF_SCOPE_HINTS) - keys)
    extra = sorted(keys - set(OUT_OF_SCOPE_HINTS))
    assert not missing, f"표지어는 있는데 소관 안내가 없다: {missing}"
    assert not extra, f"소관 안내는 있는데 표지어가 없다 - 죽은 줄이다: {extra}"


def test_every_row_carries_its_evidence(rows):
    """R2 · R5 — 줄마다 법령·조문·정부 URL·확인 절차·실측이 있어야 한다."""
    for r in rows:
        for field in ("기관", "법령", "조문", "url", "확인절차", "확인url", "실측"):
            assert r.get(field), f"{r['key']} 에 {field} 가 없다"
        assert r["url"].startswith("https://www.law.go.kr/"), r["key"]
        assert r["확인url"].startswith("https://"), r["key"]
        # 조문은 원문 인용이어야 한다 - 조 번호만 적으면 근거가 아니다.
        assert "제" in r["조문"] and len(r["조문"]) > 20, f"{r['key']} 조문이 인용이 아니다"
        for k in ("도매꾹", "새표본"):
            assert isinstance(r["실측"][k], int), f"{r['key']} 실측 {k}"


def test_the_yaml_records_what_was_measured_and_not_added(rows):
    """⚠⚠ **크레파스 원칙.** 안 넣은 후보와 그 이유가 파일에 남아 있어야 한다.

    없으면 다음 사람이 "환경부가 왜 없지" 하고 근거 없이 넣는다.
    """
    text = _YAML.read_text(encoding="utf-8")
    assert "넣지 않은 후보" in text
    for must in ("모기향", "훈증기", "카시트", "사료", "검역"):
        assert must in text, f"안 넣은 후보 '{must}' 의 실측이 기록되지 않았다"
    # 왜 안 넣었는지가 숫자와 함께 있어야 한다.
    assert "본체 대상" in text or "본체 = 대상" in text
    assert "전부 오탐" in text


# ── 화면 문구 ──────────────────────────────────────────────────────
def test_the_line_never_asserts_a_verdict():
    """§9 단정 금지. "소관으로 보입니다 — 확인" 까지다."""
    banned = ("판매 불가", "허가 필요", "위법", "불법", "안전합니다", "판매 가능")
    for key in OUT_OF_SCOPE_HINTS:
        line = jurisdiction_line(key)
        assert line, f"{key} 안내가 비었다"
        assert "보입니다" in line, f"{key} 가 단정문이다: {line}"
        for b in banned:
            assert b not in line, f"{key} 에 단정 표현 '{b}': {line}"


def test_an_unknown_reason_is_silent_not_invented():
    """모르면 빈 문자열이다. 지어내지 않는다 (R5)."""
    assert jurisdiction_line("듣도 보도 못한 소관") == ""
    assert jurisdiction_line(None) == ""
    assert jurisdiction_for(None) == {}


# ── 안내 축이라는 것 ───────────────────────────────────────────────
def test_the_guidance_rides_on_the_existing_kind():
    """⚠ **새 kind 를 만들지 않았다.** `out_of_scope` 의 detail 을 채운다."""
    facts = ProductFacts(product_name="수분크림 마스크팩 세트",
                         category=ItemCategory.UNCLASSIFIED)
    found = verify(facts, _kats(), RuleBook())
    oos = [f for f in found if f.kind is FindingKind.OUT_OF_SCOPE]
    assert len(oos) == 1
    j = (oos[0].detail or {}).get("jurisdiction")
    assert j and j["기관"] == "식품의약품안전처" and j["법령"] == "화장품법"
    assert "소관(「화장품법」)으로 보입니다" in oos[0].statement_ko
    # 안내가 신호를 바꾸지 않는다.
    assert oos[0].signal.name == "UNKNOWN"


def test_the_guidance_kind_stays_out_of_the_penalty_table():
    """penalty 0 · 신호등을 못 바꾼다."""
    from sourcing_guard.scorer import _PENALTY

    assert _PENALTY.get(FindingKind.OUT_OF_SCOPE, 0) == 0


def test_a_missing_map_does_not_break_verification(monkeypatch):
    """⚠ yaml 이 없어도 **검증은 그대로 돈다.** 안내가 검증을 막으면 안 된다 (R3)."""
    import sourcing_guard.scoping as sc

    sc._jurisdiction_map.cache_clear()
    monkeypatch.setattr(sc, "_JURISDICTION_PATH", Path("/없는/경로.yaml"))
    try:
        assert sc.jurisdiction_line("화장품 (화장품법 / 식약처 소관)") == ""
        facts = ProductFacts(product_name="수분크림 마스크팩 세트",
                             category=ItemCategory.UNCLASSIFIED)
        found = verify(facts, _kats(), RuleBook())
        oos = [f for f in found if f.kind is FindingKind.OUT_OF_SCOPE]
        assert len(oos) == 1, "안내가 없다고 finding 이 사라지면 안 된다"
        # 옛 문장으로 돌아간다.
        assert "해당 소관 부처의 별도 기준을 확인해 주세요." in oos[0].statement_ko
    finally:
        sc._jurisdiction_map.cache_clear()


def test_the_baseline_five_do_not_move():
    """⚠⚠ **다섯 숫자 0/0/0/0/0.** 안내가 숫자를 움직이면 그건 판정이다."""
    import sys

    sys.path.insert(0, str(_ROOT / "scripts"))
    import json
    import os

    cwd = os.getcwd()
    os.chdir(_ROOT)
    try:
        from audit_tally import BASELINE, BASELINE_EXTRACTOR, load_audit, load_scope, tally

        rows = json.loads(
            (_ROOT / "tests/fixtures/단건경로_gpt.json").read_text(encoding="utf-8"))
        scope = load_scope()
        rows = [r for r in rows if scope.get(r["name"])]
        kats, rules = _kats(), RuleBook()
        res = {}
        for r in rows:
            try:
                cat = ItemCategory(r.get("category") or "unclassified")
            except ValueError:
                cat = ItemCategory.UNCLASSIFIED
            f = ProductFacts(product_name=r.get("product_name") or None,
                             category=cat, legal_item_name=r.get("legal") or None)
            found = verify(f, kats, rules, raw_text=r["name"])
            res[r["name"]] = sorted({c["item"] for x in found
                                     for c in (x.detail or {}).get("candidates", []) or []})
        from audit_tally import load_reviewed_pairs

        got = tally(res, reviewed=load_reviewed_pairs(
            "tests/fixtures/단건경로_claude_235.json"))
    finally:
        os.chdir(cwd)

    base = BASELINE[BASELINE_EXTRACTOR]
    for key in ("ok", "unreviewed", "ok_upper", "off_target", "on_vague"):
        assert got[key] == base[key], (
            f"소관 안내가 다섯 숫자를 움직였다 - {key}: {base[key]} → {got[key]}. "
            "안내 축은 숫자를 움직이면 안 된다 (미완 §1-d)"
        )
