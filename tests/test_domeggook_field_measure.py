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
    """도매꾹은 `certType` 으로 제도를 직접 적어 준다 - 그것을 쓴다.

    ⚠ **전제가 2026-09-08 에 바뀌었다.** 전에는 "정규식이 MSIP 를 못 잡으니
      certType 을 써야 한다" 였다. 4-c 로 정규식이 MSIP 를 잡게 됐으므로 그
      근거는 사라졌다. 그래도 `certType` 을 쓰는 이유가 남는다 - **도매꾹이
      제도를 명시해 주는데 우리가 번호 모양으로 다시 추측할 이유가 없다.**
      정규식은 붙여넣기 입력(모양밖에 없는 경우)의 몫이다.
    """
    from sourcing_guard.rra_client import is_rf_number

    assert is_rf_number("MSIP-CMI-YOU-SOUND-T"), "4-c 가 되돌려졌다"
    m = _mod()
    # 모양으로는 KATS 번호처럼 생긴 값이라도, certType 이 방송통신기자재면
    # 전파 축으로 보낸다.
    axis = m.cert_axis([
        _row({"cert": "Y", "certType": m.RF_CERT_TYPE, "no": "MSIP-CMI-DVT-Rainbow"},
             no="10"),
        _row({"cert": "Y", "certType": m.RF_CERT_TYPE, "no": "HU071406-18008A"},
             no="11"),
    ])
    assert axis["kats"] == {}, "제도가 적혀 있는데도 KATS 로 보냈다"
    assert sorted(n for n, _ in axis["rf"]) == [
        "HU071406-18008A", "MSIP-CMI-DVT-Rainbow",
    ]


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


def test_the_a5_document_numbers_match_the_measurement_file():
    """A-5 문서의 수치가 원자료 json 과 같은가.

    ⚠ 이 가드가 없어서 문서가 낡았다 (2026-09-12). 자리표시자 판정을 한 소유자로
      합치면서 `내용 없음` 이 645 → 655 로 움직였는데, 문서도 json 도 자동으로
      갱신되지 않았고 **검사가 그것을 잡지 않았다.**

    ⚠ 재측정 스크립트는 `--out` 없이 돌리면 json 을 쓰지 않는다. 그래서 화면에는
      새 숫자가 나오는데 파일은 옛 숫자인 상태가 될 수 있다 - 이 검사가 그 상태를
      잡는다.
    """
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "tests/fixtures/도매꾹_필드실측_2026-09-08.json").read_text(encoding="utf-8"))
    doc = (root / "docs/A5_도매꾹_상세효과_2026-09-08.md").read_text(encoding="utf-8")
    n = data["내용없음"]
    rows, empty = n["항목줄"], n["내용없음줄"]

    # 문서가 "814줄 중 내용 없음  655줄 (80.5%)" 꼴로 적는다.
    m = re.search(r"고시 항목\(type=item\) (\d+)줄 중 내용 없음\s+\*{0,2}(\d+)줄 \(([\d.]+)%\)", doc)
    assert m, "A-5 문서에서 '내용 없음' 줄을 못 찾았다 - 형식이 바뀌었나"
    assert int(m.group(1)) == rows, f"항목줄: 문서 {m.group(1)} vs 원자료 {rows}"
    assert int(m.group(2)) == empty, f"내용없음줄: 문서 {m.group(2)} vs 원자료 {empty}"
    assert abs(float(m.group(3)) - empty / rows * 100) < 0.1

    m2 = re.search(r"항목 전부가 내용 없는 상품\s+\*{0,2}(\d+)", doc)
    assert m2 and int(m2.group(1)) == n["전부빈상품"], (
        f"전부빈상품: 문서 {m2.group(1) if m2 else '없음'} vs 원자료 {n['전부빈상품']}")
