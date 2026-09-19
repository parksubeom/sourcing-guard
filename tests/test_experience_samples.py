"""체험 표본 — 기록본이 정직한가.

이 화면이 하는 약속은 둘이다.

  ① "저희가 실제로 검사한 결과 그대로입니다"
     → 문장을 우리가 만들지 않았다는 것. 숫자를 화면에 박지 않았다는 것.
  ② "여기 있는 것은 저희가 맞힌 예입니다"
     → 고른 것만 보여 준다는 의심에 **틀린 수와 함께** 답한다는 것.

⚠⚠ 둘째가 더 중요하다. 표본은 본디 체리피킹이고, 그걸 감추면 심사위원이
  찾아낸다. 그래서 정직 문구의 다섯 숫자는 `baseline.BASELINE` 에서만 오고
  화면에는 적히지 않는다 - 기준선이 움직이면 문구도 같이 움직여야 한다.

⚠ 그리고 **기간만료·취소가 빠지면 안 된다.** 적합만 늘어놓은 표본은
  "잘 되네" 로 끝난다. 인증번호가 버젓이 적혀 있는데 인증이 만료·취소된
  실제 도매 상품 - 그게 이 제품이 존재하는 이유다 (총괄 판정 §3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sourcing_guard.baseline import BASELINE, BASELINE_EXTRACTOR
from sourcing_guard.cert_seed import load_entries
from sourcing_guard.main import app
from sourcing_guard.samples import SAMPLES_PATH, payload

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "sourcing_guard" / "static"
_HTML = (_STATIC / "samples.html").read_text(encoding="utf-8")
_JS = (_STATIC / "samples.js").read_text(encoding="utf-8")


def _cards():
    return payload()["items"]


# ── 기록본 자체 ──────────────────────────────────────────────────────
def test_there_are_samples_to_show():
    assert len(_cards()) >= 8, "체험 표본이 여덟 개보다 적다"


def test_every_card_says_something_specific_with_a_source():
    """R2 - 근거 없는 줄은 없다. 카드가 그리는 줄도 같다."""
    for c in _cards():
        rows = [r for r in (c["cert_row"], c["recall_row"]) if r]
        assert rows, f'{c["id"]} 에 인증·리콜 줄이 하나도 없다'
        for r in rows:
            assert r["statement_ko"], f'{c["id"]} 의 {r["kind"]} 문장이 비었다'
            assert r["source_url"], f'{c["id"]} 의 {r["kind"]} 에 원문 링크가 없다'


def test_expired_and_revoked_are_in_the_set():
    """⚠⚠ 적합만 늘어놓으면 표본이 아무 말도 하지 않는다 (총괄 §3).

    인증번호가 적힌 실제 도매 상품인데 인증이 만료·취소된 것 - 인증번호만
    보는 셀러가 놓치는 자리다.
    """
    kinds = [c["cert_row"]["kind"] for c in _cards() if c["cert_row"]]
    assert kinds.count("kc_revoked") >= 2, f"안전인증취소가 둘보다 적다: {kinds}"
    assert kinds.count("kc_expired") >= 3, f"기간만료가 셋보다 적다: {kinds}"
    assert kinds.count("kc_verified") >= 4, f"적합이 넷보다 적다: {kinds}"


def test_the_first_card_is_not_a_red_one():
    """첫 카드가 빨강이면 "겁주는 서비스" 로 읽힌다 (총괄 §3)."""
    assert _cards()[0]["signal"] != "RED"


def test_at_least_one_card_is_green():
    """⚠ 적합을 전부 전기용품으로 고르면 유해물질 축이 미수록이라 신호가 전부
    UNKNOWN 이 된다. 그러면 화면이 "모름투성이" 로 읽히고, 그건 이 표본이
    고치려던 인상 그 자체다 (총괄 §2 (3)).
    """
    signals = [c["signal"] for c in _cards()]
    assert "GREEN" in signals, f"초록불이 하나도 없다: {signals}"


def test_every_sample_number_is_in_the_cert_seed():
    """⚠ 시드에 없는 번호를 표본에 넣으면, 재배포 뒤 국표원이 죽어 있을 때
    그 카드만 "조회 실패" 가 된다. 표본은 그럴 때도 살아 있어야 한다.
    """
    seeded = {e.cert_number for e in load_entries()[0]}
    for c in _cards():
        assert c["id"] in seeded, (
            f'{c["id"]} 가 시드에 없다 - scripts/build_cert_seed.py 를 다시 돌릴 것')


# ── 개인정보 ─────────────────────────────────────────────────────────
def test_no_shop_name_prefix_survives():
    """도매꾹 상호·공급사명은 한 글자도 안 나간다 (총괄 §3).

    `[상호]` 꼴 앞머리는 뗀다. 홍보 문구인지 상호인지 자동으로 가를 수 없으니
    **앞머리 괄호 묶음은 전부** 뗀다 - 남기는 쪽이 위험하다.
    """
    for c in _cards():
        for field in ("title", "text"):
            assert not re.match(r"^\s*[\[(（【]", c[field]), (
                f'{c["id"]} 의 {field} 가 괄호로 시작한다: {c[field][:40]}')


def test_no_contact_details_anywhere_in_the_file():
    """전화·사업자번호·이메일은 파일 어디에도 없다."""
    raw = SAMPLES_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\b\d{3}-\d{2}-\d{5}\b", raw), "사업자번호 모양이 있다"
    assert not re.search(r"\b01[016-9]-?\d{3,4}-?\d{4}\b", raw), "휴대전화 모양이 있다"
    assert "@" not in raw, "이메일 모양이 있다"


def test_no_supplier_name_rides_along_in_the_product_fields():
    """⚠ 막으려는 것은 **도매꾹 공급사**다. 상품명·붙여넣기 문구가 그 통로다.

    ⚠⚠ 국표원 등록 원부의 제조사·수입자명(`detail.maker`)은 다른 것이다 -
      우리가 근거 링크로 거는 **정부 조회 페이지에 그대로 있는 값**이고,
      `data/cert_seed.json` 에도 같은 성격으로 들어 있다. 그것까지 지우면
      기록본이 "응답 그대로" 가 아니게 된다. 대신 **화면으로 나가지 않는지**를
      아래 검사가 따로 본다.
    """
    for c in _cards():
        for field in ("title", "text"):
            for token in ("주식회사", "(주)", "㈜"):
                assert token not in c[field], f'{c["id"]} 의 {field} 에 {token} 이 있다'


def test_the_api_never_sends_the_raw_finding_details():
    """카드가 그리는 것은 문장과 링크뿐이다. `detail` 을 통째로 내보내지 않는다."""
    blob = json.dumps(payload(), ensure_ascii=False)
    assert "detail" not in blob, "체험 표본 API 가 finding detail 을 내보낸다"
    for token in ("주식회사", "(주)", "㈜"):
        assert token not in blob, f"체험 표본 API 가 법인 표기를 내보낸다: {token}"


# ── 정직 문구 ────────────────────────────────────────────────────────
def test_the_baseline_numbers_come_from_the_baseline_module():
    got = payload()["baseline"]
    want = BASELINE[BASELINE_EXTRACTOR]
    assert got["extractor"] == BASELINE_EXTRACTOR
    for key in ("denominator", "ok", "wrong", "missed", "off_target"):
        assert got[key] == want[key], key


def test_the_page_does_not_hardcode_the_numbers():
    """⚠⚠ 화면에 숫자를 박으면 기준선이 움직일 때 한쪽만 고쳐진다.

    그러면 "고른 것만 보여 준다" 는 의심에 **거짓으로** 답하게 된다.
    """
    base = BASELINE[BASELINE_EXTRACTOR]
    # ⚠ 낱자리 수(8)는 `utf-8` 같은 곳에도 걸린다. **문구 모양으로** 찾는다 -
    #   위험한 것은 숫자가 어딘가 있는 것이 아니라 **문장에 박히는 것**이다.
    pct = f'{base["ok"] / base["denominator"] * 100:.1f}%'
    for shape in (f'{base["denominator"]}건', f'{base["ok"]}건',
                  f'{base["wrong"]}건', f'{base["missed"]}건', pct):
        assert shape not in _HTML, f"samples.html 에 '{shape}' 이 박혀 있다"
        assert shape not in _JS, f"samples.js 에 '{shape}' 이 박혀 있다"


def test_the_recorded_date_is_not_written_by_hand():
    """날짜는 파일의 실측 시각에서 온다. 손으로 적으면 그 문장이 거짓이 된다."""
    assert payload()["recorded_at"], "기록 시각이 없다"
    assert not re.search(r"20\d\d-\d\d-\d\d", _HTML), "samples.html 에 날짜가 박혀 있다"
    # samples.js 의 날짜는 주석의 예시 하나뿐이어야 한다 (코드가 아니라 설명).
    for line in _JS.splitlines():
        if re.search(r"20\d\d-\d\d-\d\d", line):
            assert line.strip().startswith(("/*", "*", "//")), f"코드에 날짜가 있다: {line}"


def test_the_page_offers_a_fresh_scan():
    """기록본만 보여 준다는 의심에 대한 답이 화면 안에 있어야 한다."""
    assert "지금 다시 검사" in _JS
    assert "/scan?sample=" in _JS


def test_the_scan_screen_handles_the_sample_deep_link():
    """`/scan?sample=<번호>` 가 **일반 예산 안의** 검사를 돈다.

    ⚠ 면제 지문을 늘리지 않는다 - 투표 18일 × 공개 접근 × 10개면 상한 없는
      호출이 된다 (총괄 §2).
    """
    index = (_STATIC / "index.html").read_text(encoding="utf-8")
    assert 'get("sample")' in index, "검사 화면이 sample 딥링크를 안 받는다"

    from sourcing_guard.demos import DEMO_TEXTS
    from sourcing_guard.ratelimit import text_fingerprint

    exempt = {text_fingerprint(t) for t in DEMO_TEXTS}
    for c in _cards():
        assert text_fingerprint(c["text"]) not in exempt, (
            f'{c["id"]} 가 면제 지문에 들어갔다 - 표본은 일반 예산으로 돈다')


def test_the_signal_words_match_the_scan_screen():
    """같은 신호를 두 화면이 다르게 부르면 셀러가 다른 것으로 읽는다."""
    index = (_STATIC / "index.html").read_text(encoding="utf-8")
    short = dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"',
                            re.search(r"var SIGNAL_SHORT = \{(.+?)\};", index, re.S).group(1)))
    tone = dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"',
                           re.search(r"var TONE = \{(.+?)\};", _JS, re.S).group(1)))
    assert tone == short, f"신호 낱말이 갈렸다\n  검사화면 {short}\n  표본화면 {tone}"


# ── 배선 ─────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_the_page_and_the_api_are_served(client):
    assert client.get("/samples").status_code == 200
    body = client.get("/api/v1/samples").json()
    assert len(body["items"]) == len(_cards())
    assert body["baseline"]["ok"] == BASELINE[BASELINE_EXTRACTOR]["ok"]


def test_the_api_does_not_call_anything(client, monkeypatch):
    """⚠ 이 경로는 LLM·정부 API 를 부르지 않는다. 부르면 기록본의 뜻이 없다."""
    import sourcing_guard.main as m

    def boom(*a, **k):  # pragma: no cover - 불리면 실패다
        raise AssertionError("체험 표본이 LLM 을 불렀다")

    monkeypatch.setattr(m, "extract_traced", boom)
    assert client.get("/api/v1/samples").status_code == 200


def test_a_missing_file_leaves_an_empty_list(tmp_path, monkeypatch):
    """파일이 없으면 빈 목록이다. 빈 껍데기를 그리지 않는다 (R3)."""
    import sourcing_guard.samples as s

    s.payload.cache_clear()
    monkeypatch.setattr(s, "SAMPLES_PATH", tmp_path / "없는파일.json")
    try:
        assert s.payload()["items"] == []
    finally:
        s.payload.cache_clear()


def test_the_recorded_results_are_whole_scan_responses():
    """기록본은 잘라 담은 요약이 아니라 **응답 그대로**여야 한다.

    요약만 담으면 다음 사람이 화면에 필요한 조각을 손으로 채우게 되고, 그
    순간 화면이 우리 서버가 낸 적 없는 문장을 말한다 (R5).
    """
    raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    for item in raw["items"]:
        result = item["result"]
        for key in ("signal", "headline", "findings", "axes", "meta", "disclaimer"):
            assert key in result, f'{item["cert_number"]} 의 기록본에 {key} 가 없다'


# ── 랜딩 대비 한 컷 ──────────────────────────────────────────────────
def test_the_comparison_cut_comes_from_one_real_scan():
    """⚠⚠ 두 칸이 **같은 한 번의 응답**에서 나와야 한다.

    따로 만들면 왼쪽이 "남의 서비스" 라는 뜻이 되는데 우리는 남의 서비스를
    재 본 적이 없다 (R5). 왼쪽은 우리 결과의 인증 축, 오른쪽은 리콜 축이다.
    """
    from sourcing_guard.samples import compare_cut

    cut = compare_cut()
    assert cut, "대비 컷이 없다"
    assert cut["cert"]["kind"].startswith("kc_"), cut["cert"]["kind"]
    assert cut["recall"]["kind"].startswith("recall"), cut["recall"]["kind"]
    # 이야기가 성립하려면 인증은 초록이고 리콜이 빨강이어야 한다.
    assert cut["cert"]["signal"] == "GREEN", cut["cert"]
    assert cut["recall"]["signal"] == "RED", cut["recall"]
    assert cut["signal"] == "RED"
    for side in ("cert", "recall"):
        assert cut[side]["statement_ko"], side
        assert cut[side]["source_url"], f"{side} 에 원문 링크가 없다 (R2)"


def test_the_landing_does_not_write_the_comparison_sentences():
    """문구는 서버가 낸 문장 그대로다. 화면이 사본을 들면 갈린다."""
    from sourcing_guard.samples import compare_cut

    landing = (_STATIC / "landing.html").read_text(encoding="utf-8")
    cut = compare_cut()
    for side in ("cert", "recall"):
        # 문장의 앞 12자만 봐도 충분하다 - 통째로 박으면 여기서 걸린다.
        assert cut[side]["statement_ko"][:12] not in landing, (
            f"landing.html 에 {side} 문장이 박혀 있다")


def test_the_landing_never_calls_the_left_side_someone_else():
    """⚠ 우리는 남의 서비스를 재 본 적이 없다. 그렇게 부르면 지어낸 비교가 된다."""
    landing = (_STATIC / "landing.html").read_text(encoding="utf-8")
    for banned in ("다른 서비스", "타 서비스", "경쟁", "일반 조회 서비스"):
        assert banned not in landing, f"대비 컷이 남의 서비스를 가리킨다: {banned}"


def test_the_comparison_section_is_hidden_without_data(monkeypatch, tmp_path):
    """자료가 없으면 구역째 안 그린다. 빈 껍데기를 만들지 않는다 (R3)."""
    import sourcing_guard.samples as s

    s.compare_cut.cache_clear()
    monkeypatch.setattr(s, "COMPARE_PATH", tmp_path / "없는파일.json")
    try:
        assert s.compare_cut() is None
    finally:
        s.compare_cut.cache_clear()

    landing = (_STATIC / "landing.html").read_text(encoding="utf-8")
    assert 'id="cmp-sec" hidden' in landing, "대비 구역이 기본 hidden 이 아니다"
