"""테스트는 외부 LLM 을 부르지 않는다 (CLAUDE.md §7).

왜 픽스처로 강제하나
--------------------
extract() 는 ANTHROPIC_API_KEY 가 있고 MOCK_MODE=false 면 실제 Anthropic API 를
부른다. 그 조건은 개발자의 .env 가 정하므로, 테스트가 어느 경로로 도는지가
사람마다 달라진다. CI 에는 키가 없어 목으로 돌지만 로컬에서는 라이브로 돈다.

실측(2026-09-01, 키를 .env 에 넣은 직후):

    수트 전체        20초  →  177초
    골든셋 한 건               43초
    test_kats_client 인증번호 6건   각 3~14초
    test_ratelimit 데모 스캔         9초

느린 것보다 나쁜 것이 두 가지다. (1) pytest 를 돌릴 때마다 과금된다.
(2) 회귀 테스트가 비결정적이 된다 — LLM 답이 흔들리면 코드를 안 건드렸는데
빨간불이 뜨고, 그 빨간불을 몇 번 보면 사람이 테스트를 안 믿기 시작한다.

그래서 .env 가 무엇이든 pytest 는 목 모드로 돈다. 여기서 막지 않고 파일마다
막으면, 다음에 추가되는 테스트가 조용히 라이브로 돌아간다.

실제 LLM 으로 재는 것은 계측이지 회귀 테스트가 아니다:

    SG_LIVE_LLM=1 pytest tests/test_golden_set.py   # 같은 단정을 LLM 으로
    python scripts/golden_report.py                 # 필드별 정확도 리포트

⚠ 이 픽스처는 mock_mode 만 켠다. 키를 지우지는 않는다 - test_extractor_image_cache
  처럼 "LLM 경로가 어떻게 구성되는지" 를 검증하는 테스트는 클라이언트를 직접
  목킹한 채 mock_mode=False 로 되돌려 쓴다. autouse 픽스처가 먼저 돌고 그 위에
  테스트의 _live 픽스처가 덮으므로 그 경로는 그대로 산다.

⚠ **추출기가 두 벌이 된 뒤(CLAUDE.md R7, 2026-09-08) 키를 안 지우는 것이
  위험해졌다.** 한 벤더를 목킹하고 mock_mode=False 로 되돌리면, 순서상 뒤에
  있는 **다른 벤더가 실제로 불린다** - 목킹 안 된 쪽은 진짜 키로 나간다.
  그래서 여기서 두 키를 모두 지운다. 벤더별 경로를 검증하는 테스트는 자기가
  필요한 키만 다시 세우면 된다(그때 그 벤더는 목킹돼 있다).
"""

import os
from dataclasses import replace

import httpx
import pytest


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch):
    if os.getenv("SG_LIVE_LLM"):
        return
    import sourcing_guard.extractor as ex

    monkeypatch.setattr(
        ex,
        "settings",
        replace(
            ex.settings,
            mock_mode=True,
            # 목킹 안 된 벤더가 진짜 키로 나가는 것을 막는다.
            anthropic_api_key=None,
            gpt_api_key=None,
        ),
    )


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch, request):
    """테스트는 **실제 HTTP 를 보내지 않는다** (CLAUDE.md §7).

    왜 픽스처로 강제하나
    --------------------
    LLM 을 위에서 막은 것과 같은 논리다 - 파일마다 막으면 다음에 추가되는
    테스트가 조용히 라이브로 돌아간다. 실제로 그렇게 됐다.

    2026-09-11 실측(임시로 HTTP 를 막고 전체 수트를 돌림): **18개 검사가
    네트워크에 나가고 있었다.**

        16개   `with TestClient(app)` 의 lifespan 이 리콜 동기화를 시작해
               safetykorea.kr/openapi/api/recall/*.json 을 부른다.
               검사 본문과 무관하게 앱을 띄우기만 하면 나간다.
         1개   test_ratelimit 의 데모 스캔이 cert/certificationList.json 조회
         2개   test_rf_lookup_endpoint 가 rra.go.kr 조회

    ⚠ 그중 대부분은 **통과하고 있었다.** 실패를 삼키는 경로라서 조용히
      느려지고, 정부 API 쿼터를 쓰고, 네트워크 상태에 따라 비결정적이 된다.
      실제로 2026-09-11 전체 수트에서 `ConnectTimeout` 으로 1건이 깨졌고,
      그 직전 실행에서는 같은 검사가 통과했다.

    ⚠⚠ [E-1] 에서 "환경 의존 검사 0" 이라고 보고한 것의 **정정**이다. 그때는
      개발 PC 에서 네트워크가 됐고, 새 PC 재현에서는 키가 없어 목 모드로
      돌았기 때문에 양쪽 다 통과해 못 봤다. **통과하는 것과 나가지 않는 것은
      다르다.**

    실 API 로 재야 할 때만 연다:

        SG_LIVE_NET=1 pytest tests/test_kats_client.py

    ⚠ `scripts/` 의 계측은 이 픽스처의 영향을 받지 않는다(pytest 대상이 아니다).
      측정은 거기서 하고 회차를 기록한다 - CLAUDE.md §6.
    """
    if os.getenv("SG_LIVE_NET"):
        return

    def _blocked(self, request_):  # pragma: no cover - 나가면 곧바로 터진다
        raise RuntimeError(
            "테스트가 실제 네트워크로 나가려 했습니다 (CLAUDE.md §7): "
            f"{request_.url}\n"
            "  어댑터를 목킹하거나 httpx.MockTransport 를 쓰세요. "
            "실 API 로 재야 하면 SG_LIVE_NET=1 로 여세요."
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked)


@pytest.fixture(autouse=True)
def _fresh_rate_limiter(monkeypatch):
    """검사마다 **새 레이트 리미터**를 준다.

    ⚠⚠ `main._limiter` 는 프로세스 전역이다. 그래서 `/api/v1/scan` 을 부르는
      검사가 예산을 소진하면 **그 뒤에 오는 검사가 429 를 받는다** - 검사
      순서에 따라 결과가 갈리는 격리 위반이다.

      2026-09-11 에 실제로 터졌다. [4-p] 검사가 스캔을 10회 넘게 부르자
      `test_scan_meta` · `test_result_rate` · `test_rf_lookup_endpoint` 가
      429 를 받아 `KeyError: 'meta'` 로 깨졌다. **파일별로 돌리면 통과하고
      전체 수트에서만 깨졌다** - 가장 찾기 어려운 종류다.

    ⚠ 한도를 넉넉히 준다(분당 10,000 · 일 10,000). 상한 자체를 검증하는
      `test_ratelimit` 은 자기 리미터를 monkeypatch 로 덮으므로 영향이 없다 -
      이 픽스처가 먼저 돌고 그 위에 테스트가 덮는다.

    ⚠ 데모 면제를 다시 등록한다. 안 하면 데모 스캔이 예산을 쓰고,
      `/healthz.limits.exempt_fingerprints` 가 0 이 되어 검사가 깨진다.
    """
    from sourcing_guard import main
    from sourcing_guard.demos import DEMO_TEXTS
    from sourcing_guard.ratelimit import RateLimiter

    rl = RateLimiter(per_minute=10_000, daily_llm=10_000)
    rl.register_exempt(*DEMO_TEXTS)
    monkeypatch.setattr(main, "_limiter", rl)
    # [D-백] 신고 버킷도 전역이다 - 같은 이유로 검사마다 새로 준다.
    monkeypatch.setattr(main, "_report_limiter",
                        RateLimiter(per_minute=10_000, daily_llm=10_000), raising=False)


@pytest.fixture(autouse=True)
def _fresh_kats_health(monkeypatch):
    """검사마다 **새 KatsHealth** 를 준다.

    ⚠ `kats_client.health` 는 모듈 전역이라 검사가 남긴 실패가 다음 검사에
      보인다. 지금은 `/healthz` 검사가 키 존재만 보므로 통과하지만, **절대값을
      보는 검사가 생기는 순간 조용히 깨진다** - 전역 리미터가 그랬다(4-p).

    ⚠ 자기 인스턴스를 쓰는 검사(`test_gov_lookup_observability`)는 이 픽스처
      위에 자기 것을 덮으므로 영향이 없다.

    ⚠⚠ **`main` 쪽도 함께 바꿔야 한다.** `main.py` 가
      `from .kats_client import health` 로 **모듈 레벨에서** 가져가므로
      `kats_client.health` 만 patch 하면 `/healthz` 는 여전히 옛 인스턴스를
      읽는다. 실제로 그렇게 짰다가 `test_healthz_never_reports_not_ok_on_kats_
      failure` 가 `assert None == '4001'` 로 깨졌다 - 검사는 새 인스턴스에
      기록하고 `/healthz` 는 옛 것을 읽었다.

      `from X import y` 로 가져간 이름은 **가져간 모듈의 속성**이 된다.
      전역을 patch 할 때는 import 방식을 먼저 볼 것.
    """
    from sourcing_guard import kats_client, main

    fresh = kats_client.KatsHealth()
    monkeypatch.setattr(kats_client, "health", fresh)
    if hasattr(main, "health"):
        monkeypatch.setattr(main, "health", fresh)
