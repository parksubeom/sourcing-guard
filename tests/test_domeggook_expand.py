"""A-3″ 분모 확장 — 채택 규칙이 느슨해지지 않았는지, 합이 맞는지 잠근다.

⚠ **이 검사의 요지는 "많이 채택했다" 가 아니다.** 규칙은 그대로 정확 일치이고,
  바꾼 것은 검색어와 복수 처리뿐이라는 것을 잠근다. 규칙이 느슨해지면 다른
  상품의 상세가 표본에 섞이고 그 뒤 모든 측정이 거짓이 된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BASE = Path("tests/fixtures/도매꾹_확장_2026-09-08")
_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")


def _mod():
    sys.path.insert(0, "scripts")
    import expand_domeggook_sample as m

    return m


def _scope() -> dict[str, str]:
    out = {}
    for line in _SCOPE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        _no, verdict, name, _why = line.split("\t")
        out[name] = verdict
    return out


# ── 검색어 만들기 ────────────────────────────────────────────────────
def test_leading_bracket_does_not_empty_the_query():
    """`[겨울필수템] USB 포켓 …` 처럼 앞머리에 딱지가 붙은 줄이 있다.

    "괄호 뒤 꼬리를 뗀다" 를 "첫 괄호 이후 전부" 로 읽으면 검색어가 빈
    문자열이 되어 그 줄은 아예 재검색되지 않는다.
    """
    m = _mod()
    name = "[겨울필수템] USB 포켓 발열무릎담요 플란넬 양털 극세사 대형 무릎담요"
    assert m.query_2nd(name) == "USB 포켓 발열무릎담요"
    assert m.query_3rd(name) == "USB 포켓"


def test_second_round_cuts_at_slash_and_takes_three_tokens():
    m = _mod()
    assert m.query_2nd("들꽃 소프트 마이크로 온수매트커버 / 매트카바") == "들꽃 소프트 마이크로"
    assert m.query_2nd("네온T LED 무드등 미니캡슐 USB/판촉") == "네온T LED 무드등"


def test_no_zero_hit_name_produces_an_empty_query():
    """0건 목록 전부가 실제로 재검색 가능해야 한다."""
    m = _mod()
    picked = Path("tests/fixtures/도매꾹_정제_2026-09-08/채택.json")
    if not picked.exists():
        pytest.skip("1차 수집이 없습니다")
    zero = json.loads(picked.read_text(encoding="utf-8"))["zero"]
    assert zero
    for name in zero:
        assert m.query_2nd(name), name
        assert m.query_3rd(name), name


def test_norm_title_matches_the_collector():
    """두 스크립트의 정규화가 갈라지면 채택 규칙이 조용히 달라진다."""
    m = _mod()
    sys.path.insert(0, "scripts")
    import collect_domeggook as c

    for s in ["A B/C", "  스팀 다리미 (RC530) ", "USB-C 방석", "가-나_다"]:
        assert m.norm_title(s) == c.norm_title(s)


# ── 일치 검사 ────────────────────────────────────────────────────────
def _item(**detail) -> dict:
    return {"detail": detail}


def test_fingerprint_ignores_price_and_stock_but_catches_model():
    m = _mod()
    a = {"detail": {"country": "중국", "manufacturer": "갑", "model": "M1"},
         "price": {"dome": 1000}, "qty": {"stock": 5}}
    b = {"detail": {"country": "중국", "manufacturer": "갑", "model": "M1"},
         "price": {"dome": 9999}, "qty": {"stock": 1}}
    c = {"detail": {"country": "중국", "manufacturer": "갑", "model": "M2"}}
    assert m.fingerprint(a) == m.fingerprint(b)
    assert m.differing_fields([m.fingerprint(a), m.fingerprint(b)]) == []
    assert m.differing_fields([m.fingerprint(a), m.fingerprint(c)]) == ["detail.model"]


def test_fingerprint_compares_certification_numbers():
    m = _mod()
    a = _item(safetyCert=[{"cert": "Y", "no": "CB061R2170-3018", "exem": "N"}])
    b = _item(safetyCert=[{"cert": "Y", "no": "CB061R2170-9999", "exem": "N"}])
    assert m.differing_fields([m.fingerprint(a), m.fingerprint(b)]) == ["safetyCert"]


def test_fingerprint_only_compares_notice_rows_of_type_item():
    """`transaction` 행은 약관 문구다 - 상품이 같은지와 무관하다."""
    m = _mod()
    a = _item(infoDuty={"type": "기타 재화", "item": [
        {"type": "item", "name": "제조사", "desc": "갑"},
        {"type": "transaction", "name": "청약철회", "desc": "[상세정보 별도표기]"}]})
    b = _item(infoDuty={"type": "기타 재화", "item": [
        {"type": "item", "name": "제조사", "desc": "갑"},
        {"type": "transaction", "name": "청약철회", "desc": "다른 문구"}]})
    assert m.differing_fields([m.fingerprint(a), m.fingerprint(b)]) == []


def test_fingerprint_is_order_insensitive_for_rows_and_certs():
    m = _mod()
    a = _item(infoDuty={"item": [{"type": "item", "name": "제조사", "desc": "갑"},
                                 {"type": "item", "name": "제조국", "desc": "중국"}]})
    b = _item(infoDuty={"item": [{"type": "item", "name": "제조국", "desc": "중국"},
                                 {"type": "item", "name": "제조사", "desc": "갑"}]})
    assert m.fingerprint(a) == m.fingerprint(b)


# ── 산출물 ───────────────────────────────────────────────────────────
def _payload() -> dict:
    if not _BASE.exists():
        pytest.skip("확장 결과가 아직 없습니다")
    return json.loads((_BASE / "확장채택.json").read_text(encoding="utf-8"))


def test_buckets_partition_every_target_row():
    """다섯 갈래의 합이 대상 수와 같아야 한다. 하나라도 새면 분모가 거짓이다."""
    payload = _payload()
    scope = _scope()
    n_target = sum(1 for v in scope.values() if v == "대상")
    buckets = payload["분류별_대상"]
    total = sum(len(v) for v in buckets.values())
    assert total == n_target == 135
    flat = [n for v in buckets.values() for n in v]
    assert len(flat) == len(set(flat)), "한 줄이 두 갈래에 들어 있다"
    for name in flat:
        assert scope.get(name) == "대상"


def test_adopted_rows_are_exact_title_matches_only():
    """채택된 것은 전부 정규화 정확 일치로 들어왔어야 한다."""
    payload = _payload()
    m = _mod()
    for name, got in payload["채택"].items():
        assert got["how"] in ("1차", "2차", "3차",
                              "복수일치(1차)", "복수일치(2차)", "복수일치(3차)"), got
        assert str(got["no"]).isdigit()
    # 복수는 필드가 전부 같을 때만 채택했다.
    for g in payload["복수판정"]:
        if g.get("picked"):
            assert g["differs"] == []
            assert g["verdict"].startswith("복수-일치")
        else:
            assert g["differs"] or g["verdict"] == "판정불가(상세 부족)"
    assert m.norm_title(" a b ") == "AB"


def test_expanded_fixture_has_no_pii_left():
    from sourcing_guard.domeggook_pii import residual

    if not _BASE.exists():
        pytest.skip("확장 결과가 아직 없습니다")
    for name in ("재검색.json", "상세_확장.json", "확장채택.json"):
        payload = json.loads((_BASE / name).read_text(encoding="utf-8"))
        assert residual(payload) == [], name
    views = json.loads((_BASE / "상세_확장.json").read_text(encoding="utf-8"))
    items = []
    for v in views:
        got = ((v.get("response", {}).get("domeggook") or {}).get("item")) or []
        items += [got] if isinstance(got, dict) else got
    assert items
    for it in items:
        assert "seller" not in it and "thumb" not in it
