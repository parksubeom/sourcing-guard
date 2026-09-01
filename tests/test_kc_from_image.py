"""KC 마크 이미지에서 인증번호를 읽는다 — 정규식 검증 + 셀러 확인 후 조회.

왜 읽게 됐나
------------
상세페이지가 KC 마크 이미지만 붙이고 번호를 글자로 안 적는 경우가 많다.
규정상 유효한 기재다. 안 읽으면 실제로는 있는 인증을 "표기 없음" 으로
처리하게 되는데, 그건 못 찾은 것이 아니라 찾아보지 않은 것이다 (R3).

왜 그대로 조회하지 않나
-----------------------
이미지 판독은 0/O, 1/l, 5/S 가 뒤바뀐다. 오독된 번호를 그대로 조회하면
멀쩡한 인증이 "조회 안 됨" 으로 나가고, 셀러는 정상 상품을 문제로 읽는다.

그래서 두 겹이다.
  (1) LLM 은 kc_numbers 가 아니라 kc_numbers_from_image 에 담는다
  (2) CERT_NUMBER_RE 로 형식 검증 — 텍스트에 쓰는 것과 같은 정규식
  (3) 화면에서 셀러가 확인·수정한 뒤 텍스트 경로로 조회
"""

import json
from dataclasses import replace
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from sourcing_guard.extractor import extract
from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import (
    FindingGroup,
    FindingKind,
    ItemCategory,
    ProductFacts,
    Signal,
)
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify

IMG = [{"media_type": "image/png", "data": "aGVsbG8="}]
TODAY = date(2026, 9, 1)


def _fake_client(json_out: dict):
    client = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(json_out, ensure_ascii=False)
    client.messages.create.return_value = MagicMock(content=[block])
    return client


@pytest.fixture
def _live(monkeypatch):
    import sourcing_guard.extractor as ex

    monkeypatch.setattr(
        ex, "settings", replace(ex.settings, mock_mode=False, anthropic_api_key="sk-ant-test")
    )


def _extract(answer: dict, *, text: str = "", images=IMG):
    with patch("anthropic.Anthropic", return_value=_fake_client(answer)):
        return extract(text, images=images)


BASE = {"product_name": "블록완구", "category": "children_toy",
        "category_confidence": 0.9, "raw_language": "ko"}


# ---------------------------------------------------------------------------
# (2) 형식 검증
# ---------------------------------------------------------------------------


def test_well_formed_image_number_is_kept_but_separate(_live):
    """읽되 kc_numbers 에는 넣지 않는다. 조회 경로가 다르다."""
    facts = _extract({**BASE, "kc_numbers": [], "kc_numbers_from_image": ["CB061R2170-3018"]})
    assert facts.kc_numbers == []
    assert facts.kc_numbers_from_image == ["CB061R2170-3018"]


@pytest.mark.parametrize("misread", [
    "CBO61R217O-3O18",   # 0 → O
    "CB061R2170_3018",   # 하이픈이 밑줄로
    "인증번호 확인 불가",
    "KC",
    "",
])
def test_misread_candidates_are_dropped(_live, misread):
    """오독으로 깨진 문자열은 버린다. 살려두면 정상 인증이 '미조회' 가 된다."""
    facts = _extract({**BASE, "kc_numbers": [], "kc_numbers_from_image": [misread]})
    assert facts.kc_numbers_from_image == []


def test_candidate_embedded_in_a_caption_is_recovered(_live):
    """마크 옆 문구째로 읽어 와도 번호만 뽑는다."""
    facts = _extract({**BASE, "kc_numbers": [],
                      "kc_numbers_from_image": ["안전확인신고번호 CB067R317-5002 어린이제품"]})
    assert facts.kc_numbers_from_image == ["CB067R317-5002"]


def test_candidate_already_present_in_text_is_not_duplicated(_live):
    """텍스트에 있으면 그쪽이 이긴다 — 확인 없이 바로 조회되는 경로다."""
    facts = _extract(
        {**BASE, "kc_numbers": ["CB061R2170-3018"],
         "kc_numbers_from_image": ["CB061R2170-3018"]},
        text="KC 인증번호 CB061R2170-3018",
    )
    assert facts.kc_numbers == ["CB061R2170-3018"]
    assert facts.kc_numbers_from_image == []


def test_field_is_ignored_when_no_image_was_sent(_live):
    """이미지가 없는데 이 칸이 차 있으면 LLM 이 텍스트 번호를 잘못 옮긴 것이다.

    그대로 두면 자동 조회돼야 할 번호가 확인 단계로 밀려 한 번 더 클릭을 요구한다.
    """
    facts = _extract(
        {**BASE, "kc_numbers": [], "kc_numbers_from_image": ["CB061R2170-3018"]},
        text="블록완구입니다", images=None,
    )
    assert facts.kc_numbers_from_image == []


def test_text_numbers_still_auto_merge_when_images_are_present(_live):
    """이미지 경로를 붙였다고 텍스트 정규식 합집합이 죽으면 안 된다."""
    facts = _extract(
        {**BASE, "kc_numbers": [], "kc_numbers_from_image": []},
        text="완구 KC 인증번호 CB067R317-5002",
    )
    assert facts.kc_numbers == ["CB067R317-5002"]


# ---------------------------------------------------------------------------
# (3) 확인 후 조회 — 화면 쪽 계약
# ---------------------------------------------------------------------------


def _verify(facts: ProductFacts):
    findings = verify(facts, KatsClient(None, None, mock=True), RuleBook(), None)
    return findings, score(facts, findings)


def test_image_candidate_is_not_looked_up_and_says_so():
    facts = ProductFacts(
        product_name="블록완구", category=ItemCategory.CHILDREN_TOY,
        kc_numbers_from_image=["CB061R2170-3018"],
    )
    findings, _ = _verify(facts)
    f = next(x for x in findings if x.kind is FindingKind.KC_IMAGE_CANDIDATE)

    assert f.signal is Signal.UNKNOWN          # 조회하지 않았다
    assert f.group is FindingGroup.ACTION      # 셀러가 다음에 할 일
    assert f.detail["candidates"] == ["CB061R2170-3018"]
    assert "CB061R2170-3018" in f.statement_ko
    assert "자동 조회하지 않습니다" in f.statement_ko
    # 조회는 안 했지만 근거는 있어야 한다 (R2) — 그 번호의 정부 조회 주소
    assert "CB061R2170-3018" in f.source_url


def test_image_candidate_replaces_the_not_found_message():
    """'찾지 못했습니다' 가 아니다. 읽었고 형식 검증도 통과했다."""
    facts = ProductFacts(
        product_name="블록완구", category=ItemCategory.CHILDREN_TOY,
        kc_numbers_from_image=["CB061R2170-3018"],
    )
    findings, _ = _verify(facts)
    kinds = {f.kind for f in findings}

    assert FindingKind.KC_IMAGE_CANDIDATE in kinds
    assert FindingKind.KC_MISSING_BUT_REQUIRED not in kinds
    assert not any("찾지 못했습니다" in f.statement_ko for f in findings)


def test_without_any_number_the_not_found_message_stays():
    facts = ProductFacts(product_name="블록완구", category=ItemCategory.CHILDREN_TOY)
    findings, _ = _verify(facts)
    kinds = {f.kind for f in findings}
    assert FindingKind.KC_MISSING_BUT_REQUIRED in kinds
    assert FindingKind.KC_IMAGE_CANDIDATE not in kinds


def test_tier_unknown_is_still_reported_alongside_a_candidate():
    """인증 구분을 모른다는 사실은 후보가 있어도 그대로다 (R3)."""
    facts = ProductFacts(
        product_name="블록완구", category=ItemCategory.CHILDREN_TOY,
        kc_numbers_from_image=["CB061R2170-3018"],
    )
    findings, _ = _verify(facts)
    assert FindingKind.KC_TIER_UNKNOWN in {f.kind for f in findings}


def test_candidate_does_not_move_the_signal_or_score():
    """조회 전에 점수를 깎으면 인증을 이미지로 붙여둔 상품이 더 불리해진다."""
    plain = ProductFacts(product_name="키링", category=ItemCategory.UNCLASSIFIED)
    withimg = ProductFacts(product_name="키링", category=ItemCategory.UNCLASSIFIED,
                           kc_numbers_from_image=["CB061R2170-3018"])
    _, a = _verify(plain)
    _, b = _verify(withimg)
    assert (a.signal, a.score) == (b.signal, b.score)


def test_extracted_block_labels_image_numbers_differently():
    """같은 '인증번호' 로 보이면 셀러가 이미 조회된 것으로 읽는다."""
    facts = ProductFacts(
        product_name="블록완구", category=ItemCategory.CHILDREN_TOY,
        kc_numbers=["CB067R317-5002"], kc_numbers_from_image=["CB061R2170-3018"],
    )
    _, result = _verify(facts)
    labels = {f.label: f.value for f in result.extracted}
    assert labels["인증번호"] == "CB067R317-5002"
    assert labels["인증번호 (이미지에서 읽음)"] == "CB061R2170-3018"


def test_unconfirmed_image_numbers_do_not_enter_the_watchlist():
    """감시는 확인된 단서로만 건다. 오독된 번호로 감시하면 영원히 안 맞는다."""
    from sourcing_guard.models import WatchItem

    facts = ProductFacts(product_name="블록완구", kc_numbers_from_image=["CB061R2170-3018"])
    item = WatchItem.from_facts(id="x", owner_id="o", facts=facts, on=TODAY)
    assert item.kc_numbers == []
