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
