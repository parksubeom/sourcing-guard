"""전파인증 조회 버튼 경로 — POST /api/v1/rf-lookup.

왜 스캔에서 뺐나
----------------
국립전파연구원 검색은 결과가 있으면 실측 12초다(0건은 1.3초, 팝업은 0.1초).
스캔에 넣으면 무선 상품마다 13초가 되고 기획서 §8 의 "캐시 히트 3초 이내" 가
깨진다. 투표 기간에 무선 상품을 넣은 심사위원이 기다리다 닫으면 그걸로 끝이다.

그래서 ⑦ 의 KC 이미지 확인 버튼과 같은 패턴으로 옮겼다 - 오래 걸리는 조회는
셀러가 소요 시간을 인지한 상태에서 누르게 한다.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sourcing_guard import main as main_mod

_STATIC = Path(__file__).resolve().parent.parent / "sourcing_guard" / "static"


@pytest.fixture
def client():
    return TestClient(main_mod.app)


def test_lookup_returns_findings(client):
    """스캔 결과와 같은 Finding 모양으로 준다.

    프론트가 같은 렌더러로 그리고, R2(근거 필수)·§9(단정 금지) 검증도 같은
    자리에서 걸린다.
    """
    r = client.post("/api/v1/rf-lookup", json={"model_name": "A05418"})
    assert r.status_code == 200
    body = r.json()
    assert body["model_name"] == "A05418"
    for f in body["findings"]:
        assert f["source_url"] and f["source_label"]   # R2
        assert f["kind"].startswith("rf_") or f["kind"] == "lookup_failed"


def test_lookup_rejects_empty_model(client):
    assert client.post("/api/v1/rf-lookup", json={"model_name": ""}).status_code == 422


def test_lookup_is_rate_limited(client, monkeypatch):
    """12초짜리 요청이라 반복 호출이 스캔보다 비싸다."""
    from sourcing_guard.ratelimit import RateLimiter

    monkeypatch.setattr(main_mod, "_limiter", RateLimiter(per_minute=1))
    assert client.post("/api/v1/rf-lookup", json={"model_name": "A05418"}).status_code == 200
    blocked = client.post("/api/v1/rf-lookup", json={"model_name": "A05418"})
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")


def test_scan_stays_fast_by_not_searching(client, monkeypatch):
    """스캔이 RRA 검색을 부르면 응답이 12초에 묶인다."""

    class Tripwire(main_mod.RraClient):
        def search_certs_by_model(self, model):
            raise AssertionError("스캔이 RRA 검색을 불렀습니다")

    monkeypatch.setattr(main_mod, "_rra", Tripwire(mock=True))
    r = client.post("/api/v1/scan", json={"page_text": "블루투스 무선 이어폰\n모델명: A05418"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 화면 — 버튼과 소요 시간 안내
# ---------------------------------------------------------------------------


def test_button_announces_how_long_it_takes():
    """소요 시간을 안 적으면 누르고 멈춘 줄 안다."""
    index = (_STATIC / "index.html").read_text(encoding="utf-8")
    assert "data-rf" in index
    assert "전파인증 조회하기" in index
    assert "10~20초" in index          # 버튼 옆 사전 안내
    assert "조회 중" in index        # 누른 뒤 로딩 표시


def test_button_only_appears_for_searchable_models():
    """식별력 없는 모델명('A1' 은 1,579페이지)에는 버튼을 주지 않는다."""
    index = (_STATIC / "index.html").read_text(encoding="utf-8")
    assert "searchable_model" in index


# ---------------------------------------------------------------------------
# 인라인 스크립트가 문법적으로 살아 있는가
#
# 실제로 죽인 적이 있다. 커밋 1523955 에서 JS 문자열 리터럴이 줄바꿈으로 끊겨
# `<script>` 전체가 SyntaxError 였고, 그러면 데모·검사·감시 버튼이 전부 죽는다.
# 화면 테스트가 전부 문자열 grep 이라 아무도 못 잡았다.
# ---------------------------------------------------------------------------


def _unterminated_string_line(js: str) -> int | None:
    """줄바꿈으로 끊긴 '..' 또는 ".." 리터럴의 줄 번호. 없으면 None.

    JS 는 문자열 리터럴이 줄을 넘을 수 없다(템플릿 리터럴 제외). 문자·주석·
    정규식 리터럴을 건너뛰며 훑는다.
    """
    i, line, n = 0, 1, len(js)
    prev_significant = ""
    while i < n:
        ch = js[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in " \t\r":
            i += 1
            continue
        if js.startswith("//", i):
            i = js.find("\n", i)
            if i < 0:
                return None
            continue
        if js.startswith("/*", i):
            end = js.find("*/", i + 2)
            if end < 0:
                return None
            line += js.count("\n", i, end)
            i = end + 2
            continue
        if ch in "'\"":
            start_line = line
            quote, i = ch, i + 1
            while i < n:
                c = js[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "\n":
                    return start_line
                if c == quote:
                    i += 1
                    break
                i += 1
            prev_significant = quote
            continue
        if ch == "`":
            i += 1
            while i < n:
                c = js[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "\n":
                    line += 1
                elif c == "`":
                    i += 1
                    break
                i += 1
            prev_significant = "`"
            continue
        if ch == "/" and prev_significant in "(,=:[!&|?{};+" :
            # 정규식 리터럴. 문자 클래스 안의 '/' 는 종료가 아니다.
            i += 1
            in_class = False
            while i < n:
                c = js[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    i += 1
                    break
                elif c == "\n":
                    break
                i += 1
            prev_significant = "/"
            continue
        prev_significant = ch
        i += 1
    return None


@pytest.mark.parametrize("page", ["index.html", "watch.html"])
def test_inline_script_has_no_unterminated_string(page):
    html = (_STATIC / page).read_text(encoding="utf-8")
    for js in re.findall(r"(?is)<script>(.*?)</script>", html):
        bad = _unterminated_string_line(js)
        assert bad is None, (
            f"{page}: 인라인 스크립트 {bad}번째 줄에서 문자열 리터럴이 줄바꿈으로 "
            "끊겼습니다. JS 는 이걸 SyntaxError 로 보고 <script> 전체가 죽습니다."
        )


def test_the_guard_catches_the_bug_it_was_written_for():
    """1523955 에서 실제로 난 모양 그대로."""
    broken = 'var x = (a ? b.replace(/\\s*$/, "") + "\n" : "") + "y";'
    assert _unterminated_string_line(broken) == 1
    assert _unterminated_string_line('var x = "a\\nb"; // ok') is None
