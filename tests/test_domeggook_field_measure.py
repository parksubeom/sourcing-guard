"""A-5 앞부분 실측 — 제도가 섞인 축을 갈라 놓았는지 잠근다.

⚠ **이 검사의 요지는 하나다.** 전파(방송통신기자재) 인증번호를 SafetyKorea 에
  묻지 않는다. 물으면 당연히 안 나오는데 그 0 을 "인증 없음" 으로 읽으면
  R3-b 를 정면으로 어긴다 - 부재는 증거가 아니다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_OUT = Path("tests/fixtures/도매꾹_필드실측_2026-09-08.json")
_STRUCT = Path("tests/fixtures/도매꾹_구조_2026-09-08.json")


def _mod():
    sys.path.insert(0, "scripts")
    import measure_domeggook_fields as m

    return m


def _row(*certs, name="상품", no="1") -> dict:
    return {"표본_상품명": name, "도매꾹_상품번호": no, "safetyCert": list(certs)}


# ── 제도 분리 ────────────────────────────────────────────────────────
def test_broadcast_equipment_numbers_never_go_to_safetykorea():
    m = _mod()
    axis = m.cert_axis([
        _row({"cert": "Y", "certType": "방송통신기자재", "no": "MSIP-CMI-YOU-SOUND-T"},
             name="스피커", no="10"),
        _row({"cert": "Y", "certType": "전기용품", "no": "HU071406-18008A"},
             name="전기오븐", no="11"),
    ])
    assert axis["rf"] == [("MSIP-CMI-YOU-SOUND-T", "스피커")]
    assert axis["kats"] == {"11": ["HU071406-18008A"]}


def test_split_uses_cert_type_not_the_number_shape():
    """번호 모양으로 가르면 우리 정규식이 못 잡는 표기를 놓친다.

    실측: `MSIP-CMI-*` 2개가 `rra_client.RF_NUMBER_RE` 를 통과하지 못한다.
    도매꾹은 `certType` 으로 제도를 직접 적어 준다 - 그것을 쓴다.
    """
    from sourcing_guard.rra_client import is_rf_number

    assert not is_rf_number("MSIP-CMI-YOU-SOUND-T"), (
        "정규식이 MSIP 를 잡게 됐다면 이 검사의 전제가 바뀌었다 - 확인할 것"
    )
    m = _mod()
    axis = m.cert_axis([
        _row({"cert": "Y", "certType": m.RF_CERT_TYPE, "no": "MSIP-CMI-DVT-Rainbow"})
    ])
    assert axis["kats"] == {}, "제도가 적혀 있는데도 KATS 로 보냈다"


def test_dash_and_useno_n_are_not_numbers():
    m = _mod()
    axis = m.cert_axis([
        _row({"cert": "Y", "certType": "전기용품", "no": "-"}, no="1"),
        _row({"cert": "Y", "certType": "전기용품", "no": "AB-1", "useNo": "N"}, no="2"),
    ])
    assert axis["kats"] == {}
    assert axis["번호실제"] == []


def test_image_only_rows_are_counted_for_the_image_path():
    m = _mod()
    axis = m.cert_axis([
        _row({"cert": "Y", "certType": "어린이제품", "no": "-",
              "useImgUrl": "Y", "imgUrl": "https://x/kc.png"})
    ])
    assert len(axis["이미지만"]) == 1
    assert axis["kats"] == {}


# ── 산출물 ───────────────────────────────────────────────────────────
def _out() -> dict:
    if not _OUT.exists():
        pytest.skip("실측 결과가 아직 없습니다")
    return json.loads(_OUT.read_text(encoding="utf-8"))


def test_measurement_records_that_the_lookup_was_live():
    """목 결과를 실측으로 보고하지 않는다."""
    o = _out()
    assert o["인증번호축"]["대조"]["실호출"] is True


def test_no_broadcast_number_appears_in_the_lookup_result():
    o = _out()
    rf = set(o["인증번호축"]["전파번호"])
    assert rf, "전파 번호가 하나도 없으면 이 검사가 무의미하다"
    assert not (rf & set(o["인증번호축"]["대조"]["조회안된번호"]))


def test_denominators_are_labelled():
    o = _out()
    assert o["분모"]["기준"] == "대상"
    assert o["분모"]["n"] == 109, "대상 135 중 채택 109"


def test_placeholder_ratio_is_the_headline_and_is_computed_from_rows():
    """참조.md §7 의 우려(탐침 1건에서 6개 중 5개)가 규모에서도 맞는지."""
    o = _out()["내용없음"]
    assert o["항목줄"] > 0
    ratio = o["내용없음줄"] / o["항목줄"]
    assert 0.5 < ratio < 1.0, f"내용없음 비율 {ratio:.1%} - 눈으로 확인할 것"
