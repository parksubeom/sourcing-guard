"""도매꾹 필드 판정 — 정제와 측정이 **같은 목록**을 쓰는지 잠근다."""
from __future__ import annotations

import pytest

from sourcing_guard.domeggook_fields import (
    CONTACT_NAME_MARKERS,
    html_to_text,
    infoduty_rows,
    is_placeholder,
    safety_certs,
)


@pytest.mark.parametrize("value", [
    "상세설명참조",
    "상세설명 참조",
    "[상세정보 별도표기]",
    "상세정보 별도표기",
    "상세페이지 참조",
    "상세설명참조 / 상세설명참조",   # 슬래시로 이은 것 - 조각 전부가 placeholder
    "-",
    "",
    None,
])
def test_placeholder_values_are_recognised(value):
    assert is_placeholder(value) is True


@pytest.mark.parametrize("value", [
    "블록 완구 세트 100pcs",
    "대한민국",
    "지에스켐 / 상세설명참조",       # 한쪽에 실제 값이 있으면 내용이 있다
    "CB061R2170-3018",
])
def test_real_values_are_not_placeholders(value):
    assert is_placeholder(value) is False


def test_contact_markers_match_the_notice_wording():
    """고시 문구 그대로다 - 짧은 이름이 아니다 (참조.md §7)."""
    name = "A/S 책임자와 전화번호 또는 소비자상담 관련 전화번호"
    assert any(m in name for m in CONTACT_NAME_MARKERS)


def test_infoduty_rows_accepts_dict_or_list_or_missing():
    assert infoduty_rows({}) == []
    one = {"detail": {"infoDuty": {"item": {"name": "제조사", "desc": "x"}}}}
    assert len(infoduty_rows(one)) == 1
    many = {"detail": {"infoDuty": {"item": [{"name": "a"}, {"name": "b"}]}}}
    assert len(infoduty_rows(many)) == 2


def test_safety_certs_accepts_null_dict_or_list():
    """실호출에서 **배열**이었고 `null` 일 수도 있다 (참조.md §7)."""
    assert safety_certs({"detail": {"safetyCert": None}}) == []
    assert len(safety_certs({"detail": {"safetyCert": {"no": "A"}}})) == 1
    assert len(safety_certs({"detail": {"safetyCert": [{"no": "A"}, {"no": "B"}]}})) == 2


def test_html_to_text_drops_tags_and_leaves_image_only_html_empty():
    """이미지 안의 글자는 오지 않는다. 그 0 이 우리가 세려는 신호다."""
    assert html_to_text('<p align=center><img src="a.jpg"><img src="b.jpg"></p>') == ""
    assert html_to_text("<p>재질 : 폴리에스터</p>") == "재질 : 폴리에스터"
    assert html_to_text("<style>p{color:red}</style><p>본문</p>") == "본문"
    assert html_to_text(None) == ""
