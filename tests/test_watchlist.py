"""Watchlist matching contract tests."""

from datetime import date

import pytest

from sourcing_guard.kats_client import RecallRecord, extract_model_hints, split_list_field
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


# ---------------------------------------------------------------------------
# 포함 매칭 게이트 — 짧은 쪽을 재야 한다
#
# 라이브에서 이미지 입력을 눌러보다 발견했다. 'MB-120S' 하나로 리콜 일치가
# 137건 나왔다. 게이트가 `len(wm) >= 5 or len(rm) >= 5` 였고, 우리 쪽이 길면
# 리콜 쪽이 1자여도 통과했다.
#
# 오탐 137건은 RED 를 무의미하게 만든다. 셀러가 "리콜 137건 일치"를 보면 그건
# 경고가 아니라 소음이고, 다음에 진짜 1건이 떴을 때도 소음으로 읽는다.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fragment",
    # 로컬 사본 37,313건 실측으로 실제로 걸렸던 조각들. 모델명이 아니라 정부
    # 데이터를 쪼갠 부스러기다 - 괄호 주석, 콤마 목록, 슬래시 조각.
    ["S", "1", "2", "0", "M", "B", "12", "20", "120", "B12", "B120", "120S"],
)
def test_short_recall_fragment_does_not_match_a_long_watched_model(fragment):
    watched = item(product_name="말랑 블록 완구 세트", model_name="MB-120S")
    assert match(watched, recall(product_name="블록완구", model_name=fragment)) is None


@pytest.mark.parametrize("fragment", ["뱀", "렌치", "드릴", "품번", "번호", "품명", "주황", "살색"])
def test_korean_annotation_fragments_do_not_match(fragment):
    """괄호 주석과 필드 라벨이 모델명 칸에 섞여 들어온다.

    '(뱀)' 은 봉제인형 색상 주석이고 '품번' 은 필드 이름이다. 이것들이 포함
    매칭을 통과하면 감시 중인 모든 상품이 그 리콜에 걸린다.
    """
    watched = item(product_name="블록 완구", model_name="BLOCK-1000")
    assert match(watched, recall(product_name="완구", model_name=fragment)) is None


def test_containment_still_matches_when_both_sides_are_substantial():
    """게이트를 조인 것이지 포함 매칭을 없앤 것이 아니다.

    셀러가 'MB-120' 을 감시하고 리콜이 'MB-120S' 로 공표되면 잡아야 한다.
    표기 흔들림을 놓치면 이 서비스의 유일한 약속이 깨진다 (CLAUDE.md R6).
    """
    m = match(item(model_name="MB-120"), recall(model_name="MB-120S"))
    assert m is not None and m.strength is MatchStrength.STRONG

    m = match(item(model_name="MB-120S"), recall(model_name="MB-120"))
    assert m is not None and m.strength is MatchStrength.STRONG


def test_short_but_real_model_is_still_caught_by_the_exact_tier():
    """진짜 짧은 모델명은 exact 티어가 잡는다.

    포함 게이트를 짧은 쪽 5자로 올려도 '솔로-X' 같은 3자 모델은 잃지 않는다 -
    리콜의 콤마 목록을 쪼개 둔 덕분에 정확 일치로 걸린다.
    """
    raw = "솔로, 솔로-X, 솔로 윈터, 듀오"
    r = recall(model_name=raw, models=extract_model_hints(raw))
    m = match(item(model_name="솔로-X"), r)
    assert m is not None and m.strength is MatchStrength.EXACT


def test_the_gate_measures_the_shorter_side_not_the_longer():
    """구현이 다시 `or` 로 돌아가지 않게 코드 형태를 고정한다.

    주석에는 이전 구현이 그대로 적혀 있다(발견 경위 기록). 주석을 걷어내고
    코드만 본다.
    """
    from pathlib import Path

    src = Path("sourcing_guard/watchlist.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "min(len(wm), len(rm)) >= _MIN_CONTAIN_LEN" in body
    assert "len(wm) >= _MIN_CONTAIN_LEN or" not in body


# ---------------------------------------------------------------------------
# 빈 문자열 정규화 가드 — 제조사 쪽 (137건 오탐과 같은 모양)
#
# normalize_model 은 [A-Z0-9가-힣] 만 남긴다. 그래서 중국어·그리스문자만인
# 업체명과 '-' 가 모두 "" 가 되고, `"" == ""` 로 제조사 게이트를 통과했다.
# 로컬 사본 실측: maker 가 있는데 정규화하면 빈 문자열인 레코드 15,937건(42.7%).
#
# 모델명 쪽은 `if wm:` 과 _recall_models 의 `if m` 이 이미 막고 있었다.
# 비교의 한쪽이 비었는데 통과하는 것이 137건 오탐의 본질이었다.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "watched_maker,recall_maker",
    [
        ("深圳市特格尔科技有限公司", "-"),          # 실측으로 실제 걸렸던 조합
        ("-", "深圳市特格尔科技有限公司"),
        ("广东三角牌电器股份有限公司", "-"),
        ("ΤΙ-ΤΙΝ", "乐金生活健康贸易（上海）有限公司"),
        ("-", "-"),
    ],
)
def test_makers_that_normalise_to_nothing_do_not_match(watched_maker, recall_maker):
    """정규화하면 빈 문자열이 되는 업체명끼리 맞아떨어지면 안 된다.

    제품명 토큰은 일부러 2개 이상 겹치게 뒀다. 제조사 게이트만 막으면
    약한 일치가 성립하지 않는다는 것을 보이기 위한 것이다.
    """
    watched = item(product_name="어린이용 장신구 목걸이", maker=watched_maker)
    r = recall(product_name="어린이용 장신구 목걸이 팔찌", maker=recall_maker)
    assert match(watched, r) is None


def test_normal_maker_weak_match_still_works():
    """가드는 빈 문자열만 막는다. 정상 업체명의 약한 일치는 그대로 남는다."""
    watched = item(product_name="어린이 원목 의자", maker="이케아")
    r = recall(product_name="어린이 원목 의자 세트", maker="이케아")
    m = match(watched, r)
    assert m is not None and m.strength is MatchStrength.WEAK


def test_maker_gate_checks_both_sides_are_non_empty():
    """구현이 다시 `normalize(a) == normalize(b)` 단독으로 돌아가지 않게 고정한다."""
    from pathlib import Path

    src = Path("sourcing_guard/watchlist.py").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "if watched_maker and recall_maker and watched_maker == recall_maker:" in body
    assert "normalize_model(item.maker) == normalize_model(r.maker)" not in body


# ---------------------------------------------------------------------------
# 식별력 강등 — "펜을 검사했는데 블라인드가 뜬다"
#
# 프로덕션 실측(2026-09-01) 결과 오탐이 두 갈래였고, 둘 다 매칭 자체는 규칙대로
# 동작한 것이었다. 문제는 맞은 문자열에 식별력이 없다는 것이다.
#
#   '153'   숫자만 3자      정확 일치 1건  2014 국외 'LED 전등'
#   'M1000' 글자 1 + 숫자   포함 일치 6건  잔디깎이·전기냄비·유아용 드레스 …
#
# 임계값을 올려 없애지 않고 강도를 낮춘다. 없애면 진짜 '153' 리콜을 놓치고,
# 놓친 알림은 이 서비스가 하는 유일한 약속을 깨뜨린다 (R6). 강등하면 알림은
# 계속 나가되 빨간불만 꺼진다.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("digits", ["153", "510", "999"])
def test_three_digit_model_is_demoted_not_dropped(digits):
    """3자리 숫자는 서로 다른 상품이 우연히 공유한다.

    실측(37,313건): 3자리 숫자 모델 502개 중 46.8% 가 둘 이상의 리콜에 걸린다.
    '153'(모나미 볼펜)이 2014년 국외 'LED 전등' 과 부딪힌 것이 그 경우다.
    """
    m = match(item(model_name=digits), recall(model_name=digits))
    assert m is not None, "버리면 진짜 일치를 놓친다 (R6)"
    assert m.strength is MatchStrength.WEAK


@pytest.mark.parametrize("digits", ["1000", "12345", "123456"])
def test_four_or_more_digits_stays_exact(digits):
    """4자리부터는 대체로 유일하다. 여기까지 강등하면 재현율만 깎인다.

    실측: 충돌률이 3자리 46.8% → 4자리 18.3% → 5자리 10.3% 로 꺾이고 이후
    평평하다. 처음에 최소 6자리로 뒀다가 4·5자리 3,035개를 통째로 버려
    재현율이 7.8pp 깎였다.
    """
    m = match(item(model_name=digits), recall(model_name=digits))
    assert m is not None and m.strength is MatchStrength.EXACT


@pytest.mark.parametrize("model", ["BLK-100", "솔로-X", "GP500"])
def test_models_with_letters_stay_exact(model):
    m = match(item(model_name=model), recall(model_name=model))
    assert m is not None and m.strength is MatchStrength.EXACT


# 프로덕션 /api/v1/scan 이 실제로 돌려준 리콜 모델명 원문이다. 가공하지 않았다.
@pytest.mark.parametrize("recalled", [
    "TK-500, TK-1000, AM-1000PTK",                       # 휴대용 축전지
    "1 HRM1000 MCJF1000031 - MCJF1005100 2 HRM1500",     # 로봇 잔디깎이
    "HRM1000, HRM1500, HRM2500, HRM4000",                # 잔디깎이 로봇
    "AJ-26LZ 26cm 1000W 220V~50Hz ",                     # 전기 냄비
    '"3*2 LARGE CURTAIN LIGHTS-WARM WHITE BYC100M1000D"',  # 체인형 조명기구
    "JM1000/1001/1002/1003",                             # 유아용 드레스
])
def test_single_letter_containment_is_demoted(recalled):
    """'M1000' 은 다른 모델 코드 안에 우연히 들어간다.

    중성펜 'M-1000' 하나로 저 여섯 건이 전부 빨간불이었다.
    """
    r = recall(model_name=recalled,
               models=split_list_field(recalled) + extract_model_hints(recalled))
    m = match(item(model_name="M-1000"), r)
    assert m is not None, "버리지는 않는다"
    assert m.strength is MatchStrength.WEAK


def test_containment_with_real_signal_stays_strong():
    """글자가 둘 이상이면 포함 일치를 그대로 인정한다."""
    m = match(item(model_name="MB-120"), recall(model_name="MB-120S"))
    assert m is not None and m.strength is MatchStrength.STRONG


def test_cert_number_match_is_never_demoted():
    """인증번호는 형태가 정해진 하드 데이터라 우연 충돌이 다르다."""
    m = match(
        item(model_name="153", kc_numbers=["CB061R2170-3018"]),
        recall(model_name="153", cert_numbers=["CB061R2170-3018"]),
    )
    assert m is not None and m.strength is MatchStrength.EXACT
    assert m.matched_on == "kc_number"


def test_weak_model_match_does_not_hide_a_stronger_axis():
    """축을 전부 재고 가장 강한 것을 낸다.

    첫 히트에서 반환하던 구현이라면 모델명 약한 일치가 인증번호 정확 일치를
    가렸다. 그러면 진짜 일치가 참고로 내려간다.
    """
    m = match(
        item(model_name="1000", kc_numbers=["CB067R317-5002"]),
        recall(model_name="1000", cert_numbers=["CB067R317-5002"]),
    )
    assert m is not None and m.strength is MatchStrength.EXACT


def test_alerts_still_fire_for_demoted_matches():
    """강등은 알림을 끄지 않는다. 강도만 바뀐다 (R6)."""
    alerts = sweep(
        [item(model_name="153")],
        [recall(model_name="153", product_name="LED 전등", scope="overseas")],
        today=TODAY,
    )
    assert len(alerts) == 1
    assert alerts[0].strength is MatchStrength.WEAK
    assert "LED 전등" in alerts[0].statement_ko
    assert "모델명" in alerts[0].statement_ko
