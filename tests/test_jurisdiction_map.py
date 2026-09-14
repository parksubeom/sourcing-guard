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
    """⚠ 키가 갈리면 안내가 **조용히 사라진다.** 두 목록을 대조한다.

    ⚠ 2026-09-14 부터 줄이 두 갈래다. `mode: notice` 줄은 검증을 끄지 않으므로
      `OUT_OF_SCOPE_HINTS` 에 키가 없고, 대신 자기 `표지어_안내` 를 든다 -
      **어느 쪽이든 표지어가 하나도 없으면 죽은 줄**이라는 점은 같다.
    """
    keys = {r["key"] for r in rows if r.get("mode", "out_of_scope") == "out_of_scope"}
    missing = sorted(set(OUT_OF_SCOPE_HINTS) - keys)
    extra = sorted(keys - set(OUT_OF_SCOPE_HINTS))
    assert not missing, f"표지어는 있는데 소관 안내가 없다: {missing}"
    assert not extra, f"소관 안내는 있는데 표지어가 없다 - 죽은 줄이다: {extra}"

    dead = [r["key"] for r in rows
            if r["key"] not in OUT_OF_SCOPE_HINTS and not r.get("표지어_안내")]
    assert not dead, f"표지어가 아예 없는 줄이다: {dead}"


def test_notice_rows_never_switch_off_verification(rows):
    """`mode: notice` 의 표지어는 **검증을 끄면 안 된다.**

    ⚠ 이 검사가 잡는 것: 안내용으로 넣은 낱말을 나중에 `OUT_OF_SCOPE_HINTS`
      에도 넣으면, 안내만 하려던 낱말이 리콜 대조를 통째로 끈다. 카시트가
      그러면 자동차용품 리콜을 놓친다 (R6).
    """
    from sourcing_guard.scoping import out_of_scope_reason

    for r in rows:
        for word in r.get("표지어_안내") or ():
            got = out_of_scope_reason(f"테스트 상품 {word}")
            assert got != r["key"], (
                f"{word!r} 가 안내용인데 {r['key']} 로 단락된다"
            )


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


# ── 소관 부처는 **목록**으로 본다 (2026-09-14) ──────────────────────
#
# ⚠⚠ law.go.kr 이 같은 사실을 두 칸으로 주는데 **값이 다르다.**
#
#     법령        lawSearch 소관부처명        lawService 소관부처.content
#     약사법       보건복지부,식품의약품안전처    보건복지부
#     의료기기법    보건복지부,식품의약품안전처    식품의약품안전처
#
#   `lawService` 는 공동 소관을 하나로 줄인다. 그 칸만 보고 우리 문구를
#   대조했더니 약사법이 "어긋났다" 로 나왔는데, **어긋난 것은 yaml 이 아니라
#   내가 고른 칸**이었다. 네트워크 없이 되짚을 수 있게 두 값을 yaml 에 적고
#   여기서 잠근다.


def test_every_row_records_both_ministry_fields(rows):
    for r in rows:
        assert r.get("소관부처_목록"), f"{r['key']} 에 소관부처_목록 이 없다"
        assert r.get("소관부처_대표"), f"{r['key']} 에 소관부처_대표 가 없다"
        assert isinstance(r["소관부처_목록"], list)
        # 대표는 목록 안에 있어야 한다. 밖이면 둘 중 하나를 잘못 적은 것이다.
        assert r["소관부처_대표"] in r["소관부처_목록"], r["key"]


def test_the_wording_names_a_ministry_that_is_actually_in_charge(rows):
    """우리 문구의 앞 기관이 **목록 안에** 있어야 한다.

    ⚠ 대표와 같을 필요는 없다 - 약사법은 대표가 보건복지부인데 우리는 식약처를
      앞에 둔다(의약품 품목허가 창구). 같은 목록인데 의료기기법은 대표가
      식약처다. **대표로 문구를 정하면 안 된다.**
    """
    for r in rows:
        head = r["기관"].split(" (")[0].strip()
        assert head in r["소관부처_목록"], (
            f"{r['key']}: 문구의 {head!r} 가 소관 목록 {r['소관부처_목록']} 에 없다"
        )


def test_the_two_fields_really_disagree_somewhere(rows):
    """**반대 방향.** 둘이 늘 같다면 두 칸을 적을 이유가 없다.

    약사법이 그 자리다 - 목록은 둘, 대표는 보건복지부 하나. 이 검사가
    실패하면 "왜 두 칸을 적나" 를 다시 물어야 한다.
    """
    diverging = [r["법령"] for r in rows
                 if len(r["소관부처_목록"]) > 1 and r["소관부처_대표"] != r["기관"].split(" (")[0]]
    assert diverging, "두 칸이 어긋나는 줄이 하나도 없다 - 기록할 이유가 사라졌다"
    assert "약사법" in diverging, diverging
