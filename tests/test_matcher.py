"""매처 - 후보가 실제로 이 상품을 가리키는지 판정한다.

품목 매칭이 두 단계라는 것이 이 파일의 요지다. 쿠팡이 카탈로그 중복 상품을
찾을 때 쓰는 구조와 같다 - 후보를 넓게 찾고(재현율), 그중 참인 것을 가린다
(정밀도).

우리에게 2단계가 없었다. lookup_all 이 후보를 뽑으면 첫 번째를 그대로 썼고,
그래서 "안전모 햇빛가리개" 가 안전모로, "고데기 거치대" 가 전기머리인두로
붙었다.
"""

from sourcing_guard.item_grades import ItemGradeBook
from sourcing_guard.matcher import (
    Confidence,
    has_consumable_hint,
    judge,
    summarize,
)


def _judge(name, key, how="contains", subj=True, chem=False, cons=False):
    return judge(
        normalized_name=name, normalized_key=key, matched_by=how,
        names_subject=subj, chemical_dominates=chem, consumable_hint=cons,
    )


# --- 거부 신호 -------------------------------------------------------------
def test_accessory_is_rejected():
    """거치대는 고데기가 아니다."""
    v = _judge("고데기거치대", "전기머리인두", how="alias", subj=False)
    assert not v.accepted
    assert "부속품" in v.reason


def test_chemical_variant_is_rejected():
    """'제습제' 는 '제습기' 가 아니다. 접미 한 글자가 화학제와 기기를 가른다."""
    v = _judge("옷걸이제습제곰팡이방지", "제습기", chem=True, subj=True)
    assert not v.accepted
    assert "화학제" in v.reason


def test_consumable_alone_does_not_reject():
    """수량·소모품 표기만으로 거부하면 '선풍기 2개입' 이 죽는다.

    쿠팡 매칭 가이드가 "구성품·수량이 다르면 다른 상품" 이라고 적지만, 본체
    신호가 살아 있으면 본체다. 소모품 표기는 본체 신호가 이미 약할 때만
    무게를 싣는다.
    """
    v = _judge("선풍기2개입", "선풍기", subj=True, cons=True)
    assert v.accepted


def test_consumable_rejects_when_subject_is_already_weak():
    v = _judge("전동칫솔칫솔헤드리필팩", "전동칫솔", subj=False, cons=True)
    assert not v.accepted


# --- 신뢰도 ---------------------------------------------------------------
def test_confidence_follows_the_match_path():
    """표는 법령 원문이고 별칭은 우리 추정이라 층이 다르다."""
    assert _judge("선풍기", "선풍기", how="exact").confidence is Confidence.CERTAIN
    assert _judge("신일선풍기", "선풍기", how="contains").confidence is Confidence.LIKELY
    assert _judge("무선주전자", "전기주전자", how="alias").confidence is Confidence.POSSIBLE
    assert _judge("토스터", "전기토스터", how="expand").confidence is Confidence.POSSIBLE


def test_summarize_takes_the_strongest_surviving_candidate():
    """후보가 여럿이면 다 보여주되(R3) 문구 강도는 가장 확실한 것을 따른다."""
    js = [
        _judge("x", "y", how="alias"),
        _judge("x", "y", how="contains"),
    ]
    assert summarize(js) is Confidence.LIKELY


def test_summarize_returns_rejected_when_nothing_survives():
    js = [_judge("고데기거치대", "전기머리인두", subj=False)]
    assert summarize(js) is Confidence.REJECTED


# --- 매처는 참을 만들어내지 않는다 -------------------------------------------
def test_matcher_only_rejects_never_promotes():
    """신호가 없으면 1단계 결과를 그대로 통과시킨다.

    근거 없이 매칭을 늘리면 등급이 뒤집히고, 그것이 셀러를 위법 상태로 보낸다.
    별칭으로 이은 것이 매처를 거쳤다고 CERTAIN 이 되면 안 된다.
    """
    v = _judge("무선주전자", "전기주전자", how="alias")
    assert v.confidence is Confidence.POSSIBLE


def test_consumable_hint_reads_the_raw_name():
    assert has_consumable_hint("전동칫솔 칫솔헤드 리필팩 4EA")
    assert has_consumable_hint("면도기 날 교체용 8개")
    assert not has_consumable_hint("신일 무선 선풍기")


# --- 배선 -----------------------------------------------------------------
def test_lookup_carries_confidence_and_reason():
    """판정 결과가 결과에 남아야 오답을 볼 때 어느 신호가 걸렸는지 짚을 수 있다."""
    book = ItemGradeBook()
    grade = book.lookup("신일 BLDC 무선 선풍기 써큘레이터 캠핑용")
    assert grade is not None
    assert grade.confidence in {"certain", "likely", "possible"}
    assert grade.match_reason


def test_alias_checks_the_alias_key_not_the_destination():
    """본체 검사는 별칭 키로 한다.

    목적지 품목명은 상품명에 없는 것이 정상이다 - '랜턴' 을 '충전식 휴대전등'
    으로 보내는데, 그 이름으로 본체 검사를 하면 항상 거부된다. 매처를 붙이며
    실제로 이 실수를 했고 16건이 깨졌다.
    """
    book = ItemGradeBook()
    grade = book.lookup("캠핑랜턴 감성 캠핑 LED 충전식 텐트 랜턴")
    assert grade is not None
    assert "휴대전등" in grade.item
