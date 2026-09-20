"""`showcase_pii` — 남길 목록이 **디스크에 닿기 전에** 거르는지 잠근다.

`mfds_pii` 와 같은 방향(allowlist)이므로 같은 성질을 잰다:

    ① 목록 밖 필드는 **사라진다** (지울 목록이면 남는다)
    ② 정제 뒤에도 패턴이 남으면 **파일을 만들지 않고 던진다**
    ③ 무엇을 몇 개 지웠는지 **세서 사이드카에 적는다**

⚠⚠ **반대 방향을 함께 잰다.** 우리 저장소에서 네 번 물린 자리다 - 주석이
  걱정한 방향은 막혀 있고 안 적은 반대가 뚫려 있었다 (CLAUDE.md §6).
  여기서는 "인증번호를 개인정보로 오인해 정상 수집을 멈추는가" 가 그 반대다.
"""
from __future__ import annotations

import json

import pytest

from sourcing_guard.showcase_pii import (
    KEEP_FIELDS,
    OWN_KEYS,
    ResidualPiiError,
    residual_of,
    sanitize_list_item,
    sanitize_record,
    write_sanitized,
)

#: 도매꾹 `getItemList` 실측 항목 하나 (2026-09-20 · 값만 바꿨다).
RAW_ITEM = {
    "no": "10304817",
    "title": "블럭피규어시계2종 360도회전 어린이날선물",
    "thumb": "https://cdn1.domeggook.com/upload/item/x_stt_330.png",
    "idxCOM": "0",
    "id": "jjakhs",
    "nick": "짝할인",
    "price": "2660",
    "unitQty": "6",
    "comOnly": "false",
    "deli": {"who": "C", "fee": "2500"},
    "url": "http://domeggook.com/10304817",
    "market": {"domeggook": "true"},
}


def test_the_keep_list_drops_everything_it_does_not_name():
    """목록 밖은 **사라진다.** 남긴 것과 버린 수를 둘 다 단정한다."""
    counts: dict[str, int] = {}
    out = sanitize_list_item(RAW_ITEM, counts)
    assert set(out) == set(KEEP_FIELDS)
    # ⚠ 수를 함께 단정한다. `assert not bad` 만으로는 0개를 보고 통과한다.
    assert counts["id 제거"] == 1 and counts["nick 제거"] == 1
    assert counts["목록 밖 필드 제거"] == 4      # idxCOM · comOnly · deli · market


def test_a_new_field_from_the_api_is_dropped_by_default():
    """⚠⚠ **방향이 여기서 갈린다.** 도매꾹이 필드를 늘려도 기본이 "버린다" 다.

    지울 목록이었으면 새 필드가 조용히 디스크에 눕는다 - 식약처에서 실제로
    그렇게 됐고(총괄 목록에 없던 4개) 남길 목록이 자동으로 버렸다.
    """
    item = dict(RAW_ITEM, sellerPhone="010-1234-5678", newFieldNobodyAsked="x")
    out = sanitize_list_item(item)
    assert "sellerPhone" not in out and "newFieldNobodyAsked" not in out


def test_the_source_thumbnail_url_never_reaches_the_copy():
    """받는 쪽은 URL 을 쓰고, 기록에는 우리 파일 이름만 남는다 (hotlink 금지)."""
    counts: dict[str, int] = {}
    out = sanitize_record(dict(RAW_ITEM, thumb_file="10304817.webp"), counts)
    assert "thumb" not in out
    assert out["thumb_file"] == "10304817.webp"
    assert counts["thumb 원본 URL 제거"] == 1


def test_our_own_values_are_not_counted_as_leftovers():
    """`result`·`facts` 는 우리 값이다. "목록 밖" 으로 세면 제거기록이 거짓이 된다."""
    counts: dict[str, int] = {}
    record = dict(RAW_ITEM, thumb_file="x.webp", cert_numbers=["CB061R2170-3018"],
                  certs=[{"number": "CB061R2170-3018"}], facts={"product_name": "블록"},
                  page_text="블록", result={"signal": "GREEN"})
    out = sanitize_record(record, counts)
    assert set(out) == (set(KEEP_FIELDS) | set(OWN_KEYS)) - {"thumb"}
    assert counts.get("우리 값 목록 밖 필드 제거") is None


def test_the_facts_block_is_an_allowlist_too():
    """상세에는 A/S 전화번호 행이 있다. `FACT_KEYS` 밖은 안 들어온다."""
    out = sanitize_record({
        "no": "1", "title": "t",
        "facts": {"product_name": "블록", "as_phone": "02-123-4567"},
    })
    assert set(out["facts"]) == {"product_name"}


@pytest.mark.parametrize("field,value,name", [
    ("title", "블록 문의 02-123-4567", "전화"),
    ("page_text", "문의 hello@example.com", "이메일"),
    ("title", "서울특별시 강남구 테헤란로 직배송", "주소"),
])
def test_residual_catches_what_slipped_into_free_text(field, value, name):
    """자유 텍스트에 섞여 든 것은 **자리로** 잡는다."""
    found = residual_of({"no": "1", field: value})
    assert any(name in f for f in found), f"{name} 를 못 잡았다: {found}"


def test_a_certificate_number_is_not_mistaken_for_a_phone_number():
    """⚠⚠ **반대 방향.** 인증번호가 전화번호 모양을 띤다 (`YU101649-22001`).

    여기서 걸리면 정상 인증이 "미조회" 가 되어 R3-b 를 정면으로 어긴다.
    이 프로젝트에서 가장 비싼 오탐이다.
    """
    for number in ("YU101649-22001", "HU071406-18008A", "CB061R2170-3018"):
        assert not residual_of({
            "no": "1", "title": f"블록 완구 KC {number}",
            "cert_numbers": [number],
            "page_text": f"블록 완구\nKC 인증번호 {number}",
        }), f"{number} 가 개인정보로 읽혔다"


def test_the_write_refuses_and_leaves_no_file(tmp_path):
    """정제 뒤에도 남으면 **파일을 만들지 않고 던진다** (CLAUDE.md §6)."""
    out = tmp_path / "showcase.json"
    with pytest.raises(ResidualPiiError):
        write_sanitized(out, {"items": [{"no": "1", "title": "문의 02-123-4567"}]})
    assert not out.exists(), "던졌는데 파일이 남았다"
    assert not out.with_name("showcase_제거기록.json").exists()


def test_the_write_records_what_it_dropped(tmp_path):
    """사이드카가 **무엇을 몇 개** 지웠는지 적는다."""
    out = tmp_path / "showcase.json"
    write_sanitized(out, {"as_of": "2026-09-20", "items": [dict(RAW_ITEM)]})
    clean = json.loads(out.read_text(encoding="utf-8"))
    assert clean["as_of"] == "2026-09-20"
    assert set(clean["items"][0]) == set(KEEP_FIELDS) - {"thumb"}
    side = json.loads(
        out.with_name("showcase_제거기록.json").read_text(encoding="utf-8"))
    assert side["건수"]["id 제거"] == 1
    assert side["건수"]["thumb 원본 URL 제거"] == 1
    assert side["잔존"] == []


def test_the_pattern_owner_is_not_copied_here():
    """정규식을 여기서 다시 쓰지 않는다. 소유자는 `mfds_pii` 다 (§6)."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "sourcing_guard" / "showcase_pii.py").read_text(encoding="utf-8")
    from tests.srccheck import code_only

    body = code_only(src)
    assert "text_residual" in body
    assert "re.compile" not in body, "패턴을 두 번째로 적고 있다"
