"""도매꾹 응답 정제 — **저장 경로가 개인정보를 지나가지 못하게** 잠근다.

이 검사가 지키는 것은 셋이다.

1. 제거·치환이 실제로 일어난다.
2. **인증번호를 건드리지 않는다.** 전화번호 모양의 인증번호가 실재한다 -
   그것을 마스킹하면 정상 인증이 "미조회" 가 되어 R3-b 를 정면으로 어긴다.
3. 목록에 없는 새 필드에 개인정보가 오면 **저장하지 않고 던진다.**
"""
from __future__ import annotations

import json

import pytest

from sourcing_guard.domeggook_pii import (
    ResidualPiiError,
    residual,
    sanitize,
    write_sanitized,
)


def _view(**item) -> dict:
    return {"domeggook": {"etc": {}, "item": [item]}}


def _seller_item() -> dict:
    return {
        "seller": {
            "id": "someshop",
            "nick": "어떤도매몰",
            "company": {
                "name": "어떤상사",
                "boss": "홍길동",
                "cno": "478-27-01494",
                "addr": "충남 천안시 동남구 대흥로 258 2층",
                "phone": "010-1234-5678 / 041-555-6666",
            },
        },
        "thumb": {"small": "https://cdn1.domeggook.com/a_img_150"},
        "return": {
            "addr": {
                "address1": "충남 천안시 동남구 대흥로 258",
                "zipcode": "31128",
                "phone": "041-555-6666",
                "mobile": "010-1234-5678",
            },
            "deliAmt": 3000,
        },
        "desc": {
            "license": {"usable": "true", "msg": "사용허용"},
            "notice": "<p>문의 010-1234-5678 · shop@example.com</p>",
            "contents": {
                "item": "<p>사업자등록번호 478-27-01494</p>",
                "deli": "<p>배송 안내</p>",
            },
            "comment": [{"date": "-1709878077", "memo": "연락은 1588-1234 로"}],
        },
        "detail": {
            "country": "중국",
            "infoDuty": {
                "type": "기타 재화",
                "item": [
                    {"type": "item", "name": "품명 및 모델명", "desc": "블록 100pcs"},
                    {
                        "type": "item",
                        "name": "A/S 책임자와 전화번호 또는 소비자상담 관련 전화번호",
                        "desc": "김담당 010-9999-8888",
                    },
                ],
            },
        },
    }


# ── 1. 제거·치환 ─────────────────────────────────────────────────────
def test_seller_block_is_removed_whole_including_id_and_nick():
    clean, _ = sanitize(_view(**_seller_item()))
    item = clean["domeggook"]["item"][0]
    assert "seller" not in item
    assert "seller" not in json.dumps(clean, ensure_ascii=False)


def test_return_address_and_thumb_and_license_are_removed():
    """반품 주소는 앞선 기록에 없던 개인정보 경로다 - 100/100 건이었다."""
    clean, _ = sanitize(_view(**_seller_item()))
    item = clean["domeggook"]["item"][0]
    assert "addr" not in item["return"]
    assert item["return"]["deliAmt"] == 3000  # 배송비는 남는다
    assert "thumb" not in item
    assert "license" not in item["desc"]


def test_free_text_fields_are_redacted_with_tokens():
    clean, counts = sanitize(_view(**_seller_item()))
    item = clean["domeggook"]["item"][0]
    assert "[사업자번호]" in item["desc"]["contents"]["item"]
    assert "478-27-01494" not in json.dumps(clean, ensure_ascii=False)
    assert "[전화]" in item["desc"]["notice"]
    assert "[이메일]" in item["desc"]["notice"]
    assert "[전화]" in item["desc"]["comment"][0]["memo"]  # 1588-1234
    assert counts["사업자번호"] >= 1 and counts["전화"] >= 1 and counts["이메일"] >= 1


def test_contact_infoduty_row_is_replaced_whole():
    clean, _ = sanitize(_view(**_seller_item()))
    rows = clean["domeggook"]["item"][0]["detail"]["infoDuty"]["item"]
    contact = [r for r in rows if "A/S 책임자" in r["name"]][0]
    assert contact["desc"] == "[연락처]"
    assert "김담당" not in json.dumps(clean, ensure_ascii=False)


def test_contact_row_keeps_placeholder_so_the_emptiness_signal_survives():
    """"상세설명참조" 는 연락처가 아니다.

    A-5 가 세는 "채워져 있지만 내용은 없는" 비율이 이 값으로 결정된다.
    통째로 `[연락처]` 로 덮으면 그 측정이 불가능해진다 - 개인정보를 지우는
    것과 측정 신호를 지우는 것은 다르다.
    """
    item = _seller_item()
    item["detail"]["infoDuty"]["item"][1]["desc"] = "상세설명참조"
    clean, counts = sanitize(_view(**item))
    rows = clean["domeggook"]["item"][0]["detail"]["infoDuty"]["item"]
    contact = [r for r in rows if "A/S 책임자" in r["name"]][0]
    assert contact["desc"] == "상세설명참조"
    assert counts.get("연락처항목 placeholder 유지") == 1
    assert "연락처항목 치환" not in counts


# ── 2. 인증번호를 건드리지 않는다 ────────────────────────────────────
@pytest.mark.parametrize("cert_no", ["YU101649-22001", "HU071406-18008A",
                                     "MSIP-CMI-YOU-SOUND-T", "CB061R2170-3018"])
def test_certification_numbers_are_never_masked(cert_no):
    """전화번호 모양의 인증번호가 실재한다 (2026-09-08 실측 2건).

    `YU101649-22001` 안의 `1649-2200` 은 대표번호 패턴에 걸린다. 이 프로젝트
    에서 가장 중요한 필드를 마스킹하면 정상 인증이 "미조회" 가 된다 (R3-b).
    """
    item = _seller_item()
    item["detail"]["safetyCert"] = [{"cert": "Y", "no": cert_no, "exem": "N"}]
    clean, _ = sanitize(_view(**item))
    got = clean["domeggook"]["item"][0]["detail"]["safetyCert"][0]["no"]
    assert got == cert_no


def test_certification_number_shaped_string_is_not_flagged_as_residual():
    payload = _view(detail={"safetyCert": [{"no": "YU101649-22001"}]})
    assert residual(payload) == []


# ── 3. 새 필드는 저장을 멈춘다 ───────────────────────────────────────
def test_unknown_field_with_pii_stops_the_write(tmp_path):
    """목록에 없는 곳에 개인정보가 오면 조용히 저장되지 않게 한다.

    우리 제거 목록은 100건 표본에서 나온 것이다. 새 필드는 목록에 없다.
    """
    payload = _view(newBlock={"someContact": "문의 010-1234-5678"})
    target = tmp_path / "상세.json"
    with pytest.raises(ResidualPiiError) as exc:
        write_sanitized(target, payload)
    assert ".newBlock.someContact" in str(exc.value)
    assert not target.exists(), "잔존이 있으면 파일을 만들지 않는다"


def test_write_sanitized_leaves_a_sidecar_with_counts(tmp_path):
    target = tmp_path / "상세.json"
    counts = write_sanitized(target, _view(**_seller_item()))
    side = json.loads((tmp_path / "상세.json.정제.json").read_text(encoding="utf-8"))
    assert side["잔존"] == []
    assert side["건수"] == dict(sorted(counts.items()))
    assert "[사업자번호]" in side["치환_토큰"]


# ── 4. 검색 응답 ─────────────────────────────────────────────────────
def test_search_list_drops_seller_id_and_thumb():
    payload = {"domeggook": {"header": {"numberOfItems": "1"}, "list": {"item": [
        {"no": "58491071", "title": "블록 100pcs", "id": "someshop",
         "thumb": "https://cdn1.domeggook.com/x", "price": "5000"}
    ]}}}
    clean, counts = sanitize(payload)
    row = clean["domeggook"]["list"]["item"][0]
    assert row["no"] == "58491071" and row["title"] == "블록 100pcs"
    assert "id" not in row and "thumb" not in row
    assert counts["list.item.id 제거"] == 1


def test_saved_shape_wrapper_is_handled():
    """우리가 저장하는 모양(`[{"query":…, "response":…}]`)도 받는다."""
    payload = [{"query": "블록", "response": _view(**_seller_item())},
               {"nos": ["1"], "error": "HTTP 500"}]
    clean, _ = sanitize(payload)
    assert clean[0]["query"] == "블록"
    assert "seller" not in clean[0]["response"]["domeggook"]["item"][0]
    assert clean[1]["error"] == "HTTP 500"


def test_sanitize_does_not_mutate_the_input():
    original = _view(**_seller_item())
    before = json.dumps(original, ensure_ascii=False)
    sanitize(original)
    assert json.dumps(original, ensure_ascii=False) == before


# ── 5. 저장 경로 잠금 ────────────────────────────────────────────────
def test_collect_script_saves_responses_only_through_write_sanitized():
    """수집 스크립트가 응답을 다른 경로로 저장하지 못하게 한다.

    CLAUDE.md §6: "외부 응답을 저장하는 코드는 개인정보 제거 함수를 거치지
    않으면 저장할 수 없게 짠다." 검사 대상은 **응답을 담은 변수**다 -
    채택 목록(우리가 만든 상품명·번호)은 평범한 쓰기로 저장하고 `residual()`
    로 검사한다.
    """
    from pathlib import Path

    src = Path("scripts/collect_domeggook.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "write_sanitized(out_dir / \"검색.json\"" in code
    assert "write_sanitized(out_dir / \"상세.json\"" in code
    for banned in ("검색.json\").write_text", "상세.json\").write_text"):
        assert banned not in code, f"응답을 정제 경로 밖에서 저장한다: {banned}"
    assert "residual(adopted)" in code, "채택 목록도 검사를 거쳐야 한다"


def test_collected_fixture_has_no_pii_left():
    """커밋된 정제본을 다시 훑는다. **이것이 리포에 대한 실제 보증이다.**"""
    from pathlib import Path

    base = Path("tests/fixtures/도매꾹_정제_2026-09-08")
    if not base.exists():  # 수집 전이면 건너뛴다
        pytest.skip("정제본이 아직 없습니다")
    for name in ("검색.json", "상세.json", "채택.json"):
        payload = json.loads((base / name).read_text(encoding="utf-8"))
        assert residual(payload) == [], f"{name} 에 개인정보 패턴이 남아 있다"
    # `seller` 블록 부재는 **키로** 본다.
    #
    # ⚠ 문자열 검색으로 쓰지 말 것. 두 번 틀린다. (1) `benefits.sellerPoint`
    #   가 113곳에 있어 substring 검사는 항상 걸린다 - 그것은 혜택 종류이고
    #   개인정보가 아니다. (2) `assert "seller" not in json.dumps(...)` 는
    #   pytest 의 assert 재작성이 130만 자 피연산자로 비교 설명을 만들려
    #   하면서 수트를 사실상 멈춘다(2026-09-08 에 겪었다).
    views = json.loads((base / "상세.json").read_text(encoding="utf-8"))
    items = []
    for v in views:
        got = ((v.get("response", {}).get("domeggook") or {}).get("item")) or []
        items += [got] if isinstance(got, dict) else got
    assert items, "상세 응답이 비었다"
    for it in items:
        assert "seller" not in it
        assert "thumb" not in it
        assert "addr" not in (it.get("return") or {})
        assert "license" not in (it.get("desc") or {})


def test_no_raw_response_directory_is_committed():
    """`도매꾹_원문_*` 은 다시 만들지 않는다. 이름이 내용과 어긋나면 위험하다."""
    from pathlib import Path

    assert not list(Path("tests/fixtures").glob("도매꾹_원문_*"))
