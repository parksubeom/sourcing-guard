"""Watchlist matching contract tests."""

from datetime import date

import pytest

from sourcing_guard.kats_client import RecallRecord
from sourcing_guard.models import MatchStrength, RecallAlert, WatchItem, WatchStatus
from sourcing_guard.watchlist import match, normalize_model, recall_fingerprint, sweep

TODAY = date(2026, 9, 20)


def item(**kw) -> WatchItem:
    base = dict(id="w1", owner_id="u1", registered_at=TODAY)
    return WatchItem(**{**base, **kw})


def recall(**kw) -> RecallRecord:
    base = dict(product_name=None, model_name=None, maker=None, reason="기준 초과",
                announced_on="2026-09-18", detail_url="https://www.safetykorea.kr/x",
                scope="domestic")
    return RecallRecord(**{**base, **kw})


# --- normalisation -------------------------------------------------------
@pytest.mark.parametrize("raw", ["BLK-100", "ＢＬＫ 100", "blk_100", " blk 100 "])
def test_model_normalisation_collapses_variants(raw):
    assert normalize_model(raw) == "BLK100"


# --- tiers ---------------------------------------------------------------
def test_exact_model_match():
    m = match(item(model_name="BLK-100"), recall(model_name="blk 100"))
    assert m and m.strength is MatchStrength.EXACT


def test_short_models_do_not_match():
    """'A1' style codes collide by coincidence; never alert on them."""
    assert match(item(model_name="A1"), recall(model_name="A1")) is None


def test_containment_is_strong_not_exact():
    m = match(item(model_name="BLK-1002"), recall(model_name="BLK-1002-RED"))
    assert m and m.strength is MatchStrength.STRONG


def test_maker_plus_product_overlap_is_weak():
    m = match(
        item(maker="안심완구", product_name="유아용 블록 완구 세트"),
        recall(maker="안심완구", product_name="유아용 블록 완구"),
    )
    assert m and m.strength is MatchStrength.WEAK


def test_same_maker_alone_is_not_a_match():
    assert match(
        item(maker="안심완구", product_name="스티커북"),
        recall(maker="안심완구", product_name="유아용 블록 완구"),
    ) is None


# --- sweep behaviour -----------------------------------------------------
def test_sweep_emits_alert_with_source():
    alerts = sweep([item(model_name="BLK-100")], [recall(model_name="BLK-100")], today=TODAY)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.source_url and a.strength is MatchStrength.EXACT
    assert a.detected_at == TODAY


def test_seen_fingerprints_suppress_repeat_alerts():
    r = recall(model_name="BLK-100")
    fp = recall_fingerprint(r)
    it = item(model_name="BLK-100", seen_recall_fingerprints=[fp])
    assert sweep([it], [r], today=TODAY) == []


def test_min_strength_filters_weak_matches():
    it = item(maker="안심완구", product_name="유아용 블록 완구 세트")
    r = recall(maker="안심완구", product_name="유아용 블록 완구")
    assert len(sweep([it], [r], today=TODAY)) == 1
    assert sweep([it], [r], today=TODAY, min_strength=MatchStrength.STRONG) == []


def test_archived_and_unmatchable_items_are_skipped():
    archived = item(model_name="BLK-100", status=WatchStatus.ARCHIVED)
    empty = item(id="w2")
    assert not empty.is_matchable()
    assert sweep([archived, empty], [recall(model_name="BLK-100")], today=TODAY) == []


def test_sweep_is_deterministic():
    items = [item(model_name="BLK-100"), item(id="w2", model_name="BLK-1002")]
    recalls = [recall(model_name="BLK-100"), recall(model_name="BLK-1002-RED")]
    runs = {tuple((a.watch_item_id, a.strength) for a in sweep(items, recalls, today=TODAY))
            for _ in range(50)}
    assert len(runs) == 1


# --- R2 / §9 wording -----------------------------------------------------
def test_alert_requires_source():
    with pytest.raises(ValueError):
        RecallAlert(watch_item_id="w1", recall_fingerprint="x", strength=MatchStrength.EXACT,
                    matched_on="model_name", statement_ko="리콜 공표에 등록되었습니다.",
                    source_label="", source_url="", detected_at=TODAY)


def test_alert_rejects_verdict_language():
    with pytest.raises(ValueError):
        RecallAlert(watch_item_id="w1", recall_fingerprint="x", strength=MatchStrength.EXACT,
                    matched_on="model_name", statement_ko="이 상품은 위법입니다",
                    source_label="국가기술표준원", source_url="https://www.safetykorea.kr/",
                    detected_at=TODAY)


# --- B: 콤마로 묶인 목록 (설계서 p.11, p.14) ------------------------------
def multi(models: str, **kw) -> RecallRecord:
    from sourcing_guard.kats_client import split_list_field

    return recall(model_name=models, models=split_list_field(models), **kw)


def test_multi_model_recall_matches_a_middle_entry():
    """'A,B,C' 리콜에서 B 를 감시 중인 셀러도 알림을 받아야 한다."""
    r = multi("HKAK31101S-00,T3S-T-1-503,BLK-100")
    m = match(item(model_name="T3S-T-1-503"), r)
    assert m and m.strength is MatchStrength.EXACT


def test_packed_string_alone_would_not_match():
    """분해하지 않으면 놓친다는 것을 명시적으로 남긴다 (회귀 방지)."""
    packed = "HKAK31101S-00,T3S-T-1-503"
    assert normalize_model(packed) != normalize_model("T3S-T-1-503")
    assert match(item(model_name="T3S-T-1-503"), multi(packed)) is not None


def test_recall_cert_numbers_match_exactly():
    r = multi("전혀다른모델", cert_numbers=["CB123A123-1234", "JU071047-12002C"])
    m = match(item(kc_numbers=["인증번호: CB123A123-1234"]), r)
    assert m and m.strength is MatchStrength.EXACT and m.matched_on == "kc_number"


def test_fingerprint_uses_uid_when_present():
    a = multi("BLK-100", uid="3802")
    b = multi("BLK-100", uid="9999")
    assert recall_fingerprint(a) != recall_fingerprint(b)


def test_placeholder_cert_number_does_not_match():
    """리콜 레코드의 certNum 에 '공급자적합성' 같은 자리표시자가 온다 (설계서 p.10).

    인증번호로 취급하면 같은 자리표시자를 가진 서로 다른 상품이 전부 일치한다.
    """
    r = RecallRecord(**{**recall(model_name="전혀다른모델").__dict__,
                        "cert_numbers": ["공급자적합성"]})
    assert match(item(kc_numbers=["공급자적합성"]), r) is None
