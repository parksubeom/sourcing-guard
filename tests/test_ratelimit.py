"""호출 상한 — 투표 기간 18일을 버티기 위한 장치 (핸드오프 §8).

두 제한의 목적이 다르다. IP당 분당은 한 사람의 반복 호출을 막고, 일일 LLM
상한은 비용을 막는다. 전자는 429 로 거절하고, 후자는 거절하지 않고 정확도를
낮춘다 - 상한 때문에 서비스가 멈추면 투표 기간에 링크가 죽는다.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from sourcing_guard.demos import DEMO_TEXTS
from sourcing_guard.ratelimit import RateLimiter, text_fingerprint


# ---------------------------------------------------------------------------
# IP당 분당
# ---------------------------------------------------------------------------


def test_per_ip_limit_blocks_after_the_cap():
    rl = RateLimiter(per_minute=3)
    assert all(rl.allow_request("1.1.1.1", now=100.0) for _ in range(3))
    assert rl.allow_request("1.1.1.1", now=100.0) is False


def test_one_ip_does_not_block_another():
    """프록시 뒤에서 IP 를 못 가려내면 한 사람이 전원을 막는다."""
    rl = RateLimiter(per_minute=2)
    rl.allow_request("1.1.1.1", now=100.0)
    rl.allow_request("1.1.1.1", now=100.0)

    assert rl.allow_request("1.1.1.1", now=100.0) is False
    assert rl.allow_request("2.2.2.2", now=100.0) is True


def test_window_slides_after_a_minute():
    rl = RateLimiter(per_minute=2)
    rl.allow_request("1.1.1.1", now=100.0)
    rl.allow_request("1.1.1.1", now=100.0)
    assert rl.allow_request("1.1.1.1", now=100.0) is False
    assert rl.allow_request("1.1.1.1", now=161.0) is True


def test_retry_after_is_at_least_one_second():
    rl = RateLimiter(per_minute=1)
    rl.allow_request("1.1.1.1", now=100.0)
    assert rl.retry_after_seconds("1.1.1.1", now=100.0) >= 1


# ---------------------------------------------------------------------------
# 일일 LLM 예산 — 넘어도 서비스는 계속 돈다
# ---------------------------------------------------------------------------


def test_daily_budget_runs_out_but_does_not_raise():
    rl = RateLimiter(daily_llm=2)
    d = date(2026, 9, 1)
    assert rl.take_llm_budget(today=d) is True
    assert rl.take_llm_budget(today=d) is True
    assert rl.take_llm_budget(today=d) is False  # 거절이 아니라 "LLM 없이 가라"


def test_budget_resets_the_next_day():
    rl = RateLimiter(daily_llm=1)
    assert rl.take_llm_budget(today=date(2026, 9, 1)) is True
    assert rl.take_llm_budget(today=date(2026, 9, 1)) is False
    assert rl.take_llm_budget(today=date(2026, 9, 2)) is True


# ---------------------------------------------------------------------------
# 데모 3종은 두 제한 모두와 무관해야 한다 (핸드오프 §9, §10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", DEMO_TEXTS)
def test_demo_texts_bypass_the_per_ip_limit(text):
    """투표자가 첫 화면에서 버튼을 눌렀는데 429 를 보면 그대로 이탈한다."""
    rl = RateLimiter(per_minute=1)
    rl.register_exempt(*DEMO_TEXTS)
    fp = text_fingerprint(text)

    rl.allow_request("1.1.1.1", now=100.0)  # 일반 요청으로 한도 소진
    assert rl.allow_request("1.1.1.1", fingerprint=fp, now=100.0) is True


@pytest.mark.parametrize("text", DEMO_TEXTS)
def test_demo_texts_do_not_consume_the_daily_budget(text):
    rl = RateLimiter(daily_llm=0)
    rl.register_exempt(*DEMO_TEXTS)
    assert rl.take_llm_budget(fingerprint=text_fingerprint(text)) is True
    assert rl.snapshot()["daily_llm_used"] == 0


def test_fingerprint_ignores_whitespace_differences():
    """줄바꿈이 하나 달라졌다고 데모가 면제에서 빠지면 안 된다."""
    a = text_fingerprint("완구  장난감\n KC 인증번호 CB061R2170-3018")
    b = text_fingerprint("완구 장난감 KC 인증번호 CB061R2170-3018")
    assert a == b


# ---------------------------------------------------------------------------
# 엔드포인트 연결
# ---------------------------------------------------------------------------


def test_scan_returns_429_with_retry_after(monkeypatch):
    from sourcing_guard import main

    monkeypatch.setattr(main, "_limiter", RateLimiter(per_minute=1))
    with TestClient(main.app) as client:
        first = client.post("/api/v1/scan", json={"page_text": "완구 장난감 하나"})
        second = client.post("/api/v1/scan", json={"page_text": "완구 장난감 둘"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert "Retry-After" in second.headers
    assert "다시 시도" in second.json()["detail"]


def test_demo_scan_still_works_when_the_limit_is_exhausted(monkeypatch):
    """상한은 낯선 사람의 반복 호출을 막으려는 것이지 데모를 막으려는 것이 아니다."""
    from sourcing_guard import main

    rl = RateLimiter(per_minute=1)
    rl.register_exempt(*DEMO_TEXTS)
    monkeypatch.setattr(main, "_limiter", rl)

    with TestClient(main.app) as client:
        client.post("/api/v1/scan", json={"page_text": "아무거나"})          # 한도 소진
        blocked = client.post("/api/v1/scan", json={"page_text": "또 아무거나"})
        demo = client.post("/api/v1/scan", json={"page_text": DEMO_TEXTS[0]})

    assert blocked.status_code == 429
    assert demo.status_code == 200


def test_demos_endpoint_is_the_single_source(monkeypatch):
    """프론트가 문구를 따로 들고 있으면 서버의 면제 목록과 갈라진다."""
    from sourcing_guard import main

    with TestClient(main.app) as client:
        body = client.get("/api/v1/demos").json()

    assert [d["tone"] for d in body] == ["green", "amber", "red"]
    assert {d["text"] for d in body} == set(DEMO_TEXTS)


def test_healthz_exposes_limit_state():
    """운영자가 오늘 예산을 얼마나 썼는지 볼 수 있어야 한다."""
    from sourcing_guard.main import app

    with TestClient(app) as client:
        limits = client.get("/healthz").json()["limits"]

    for key in ("per_minute", "daily_llm_limit", "daily_llm_used", "exempt_fingerprints"):
        assert key in limits
    assert limits["exempt_fingerprints"] == len(DEMO_TEXTS)


# ---------------------------------------------------------------------------
# CORS — 와일드카드로 열려 있으면 안 된다
# ---------------------------------------------------------------------------


def test_no_cors_middleware_is_registered():
    """프론트가 동일 출처라 CORS 가 필요 없다.

    열어두면 아무 사이트가 우리 API 를 자기 화면에 붙여 쓸 수 있고, 그 화면은
    §6.1 한계 문구도 면책 표기도 없이 우리 신호등만 가져다 쓴다. 필요해지면
    그때 우리 도메인만 명시해서 연다.
    """
    from sourcing_guard.main import app

    names = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" not in names, f"CORS 미들웨어가 붙어 있습니다: {names}"


def test_scan_response_has_no_allow_origin_header():
    from sourcing_guard.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/scan",
            json={"page_text": "완구 장난감"},
            headers={"Origin": "https://evil.example"},
        )

    assert r.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
