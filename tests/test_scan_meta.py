"""[B-백] **이 스캔 한 건**이 어떻게 나왔는지를 응답과 /healthz 가 말한다.

⚠ 2026-09-08 사고: Claude 잔액이 0 이 되어 배포본이 매 스캔마다 400 을 받고
  휴리스틱으로 떨어졌는데, 응답도 화면도 그 사실을 말하지 않아 **휴리스틱
  결과를 "실물 확인" 으로 보고했다.** `/healthz` 의 `extraction` 은 프로세스
  누적값이라 "지금 이 결과가 무엇으로 나왔나" 를 답하지 못한다.

⚠ 화면은 이 필드를 **읽어 그린다. 하드코딩 금지.** 모델 이름도 설정에서 온다 -
  문서에 적힌 이름과 배포본 secret 이 다를 수 있고, 그것을 확인할 방법이 없어서
  이 필드를 만들었다.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from sourcing_guard.extractor import ExtractionTrace
from sourcing_guard.main import app
from sourcing_guard.models import (
    Finding,
    FindingKind,
    ItemCategory,
    ProductFacts,
    ScanMeta,
    Signal,
)
from sourcing_guard.scorer import score

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_live_government_api(monkeypatch):
    """이 파일의 스캔은 **네트워크를 쓰지 않는다** (CLAUDE.md §7).

    ⚠ 로컬 `.env` 가 `MOCK_MODE=false` 라 `main._kats` · `main._rra` 가 실호출
      모드로 만들어진다. 인증번호가 있는 페이지를 스캔하면 safetykorea.kr 로
      나가고, 그러면 이 검사가 남의 API 상태에 따라 흔들린다 - 회귀 테스트가
      비결정적이 되면 사람이 빨간불을 안 믿기 시작한다.

    ⚠ 이 파일이 재는 것은 **메타 필드**이지 인증 조회가 아니다. 그래서 목으로
      막는 것이 측정 대상을 훼손하지 않는다.
    """
    from unittest.mock import MagicMock

    import sourcing_guard.main as m

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    monkeypatch.setattr(m, "_kats", kats)
    monkeypatch.setattr(m, "_rra", None)


# ── /healthz ────────────────────────────────────────────────────────
def test_healthz_exposes_model_names_not_keys():
    """이름은 낸다. 키는 절대 내지 않는다."""
    body = client.get("/healthz").json()
    ex = body["extraction"]

    assert ex["claude_model"], "claude 모델 이름이 없다"
    assert ex["gpt_model"], "gpt 모델 이름이 없다"
    # 키 유무는 불리언으로만. 값이 새면 안 된다.
    assert isinstance(ex["claude_key"], bool)
    assert isinstance(ex["gpt_key"], bool)
    blob = str(body)
    for secretish in ("sk-", "sk-ant-"):
        assert secretish not in blob, "키가 응답에 섞였다"


def test_healthz_exposes_the_latest_recall_publication_date():
    """화면 상단 두 줄 중 하나다. 이미 sync 스냅샷에 있으므로 그대로 쓴다."""
    body = client.get("/healthz").json()
    assert "latest_published_on" in (body.get("sync") or {})


# ── 스캔 응답 ───────────────────────────────────────────────────────
def test_scan_response_says_how_this_one_scan_was_produced():
    body = client.post(
        "/api/v1/scan",
        json={"page_text": "블록 완구 장난감 KC 인증번호 CB067R317-5002 대상연령 3세"},
    ).json()
    meta = body["meta"]

    assert meta["extracted_by"], "화면이 그대로 쓸 한 줄이 없다"
    assert meta["extraction_path"] in ("llm", "heuristic")
    # 리콜 기준일이 메타 자리에도 있어야 한다 - 상단 두 줄이 한 곳에서 읽힌다.
    assert meta["recall_data_as_of"] == body["recall_data_as_of"]


def test_the_meta_is_not_inside_product_facts():
    """`ProductFacts` 는 `extra="forbid"` 인 판정 입력이다 (R1)."""
    body = client.post("/api/v1/scan", json={"page_text": "블록 완구"}).json()
    assert "extracted_by" not in body["facts"]
    assert "extraction_path" not in body["facts"]
    with pytest.raises(Exception):
        ProductFacts(product_name="x", extraction_path="llm")


# ── 판정에 쓰지 않는다 (R1) ─────────────────────────────────────────
def test_meta_never_changes_the_signal_or_the_score():
    """추출 경로가 신호를 바꾸면 "휴리스틱이면 더 위험" 같은 판정이 된다."""
    facts = ProductFacts(product_name="블록 완구", category=ItemCategory.CHILDREN_TOY)
    findings = [
        Finding(
            kind=FindingKind.RECALL_CLEAR, signal=Signal.GREEN,
            statement_ko="리콜 공표 목록에서 일치 항목을 찾지 못했습니다.",
            source_label="제품안전정보센터", source_url="https://www.safetykorea.kr/",
            checked_at=date(2026, 9, 9),
        )
    ]
    llm = score(facts, findings, meta=ScanMeta(
        extracted_by="LLM(GPT · gpt-5.4-mini)", extraction_path="llm",
        extractor_vendor="gpt", extractor_model="gpt-5.4-mini"))
    heur = score(facts, findings, meta=ScanMeta(
        extracted_by="규칙 기반 (일일 한도 초과)", extraction_path="heuristic",
        extraction_reason="daily_limit"))
    none = score(facts, findings)

    assert llm.signal is heur.signal is none.signal
    assert llm.score == heur.score == none.score
    assert llm.headline == heur.headline == none.headline
    # 그래도 실려 나간다.
    assert llm.meta.extractor_vendor == "gpt"
    assert heur.meta.extraction_path == "heuristic"
    assert none.meta is None


# ── 경로별 문구 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("trace,expected", [
    (ExtractionTrace(path="llm", vendor="gpt", model="gpt-5.4-mini"),
     "LLM(GPT · gpt-5.4-mini)"),
    (ExtractionTrace(path="llm", vendor="claude", model="claude-sonnet-5"),
     "LLM(Claude · claude-sonnet-5)"),
    (ExtractionTrace(path="heuristic", reason="daily_limit"),
     "규칙 기반 (일일 한도 초과)"),
    (ExtractionTrace(path="heuristic", reason="all_vendors_failed"),
     "규칙 기반 (추출기 전부 실패)"),
    (ExtractionTrace(path="heuristic", reason="no_key"),
     "규칙 기반 (추출기 키 없음)"),
])
def test_trace_label_is_ready_to_print(trace, expected):
    """화면이 조립하지 않는다 - 서버가 완성된 한 줄을 준다."""
    assert trace.label_ko == expected


def test_the_daily_limit_path_is_distinguishable_from_a_vendor_failure():
    """둘은 원인이 다르고 대응도 다르다. 하나로 뭉치면 09-08 을 못 잡는다.

    일일 한도는 우리 설정 문제이고, 벤더 실패는 남의 API 장애다.
    """
    limit = ExtractionTrace(path="heuristic", reason="daily_limit")
    failed = ExtractionTrace(path="heuristic", reason="all_vendors_failed")
    assert limit.reason != failed.reason
    assert limit.label_ko != failed.label_ko


def test_extract_keeps_its_old_shape_for_existing_callers():
    """`extract()` 는 얇은 래퍼로 남는다 - 골든셋·측정 스크립트가 쓴다."""
    from sourcing_guard.extractor import extract, extract_traced

    facts = extract("블록 완구 장난감")
    traced, trace = extract_traced("블록 완구 장난감")
    assert isinstance(facts, ProductFacts)
    assert isinstance(traced, ProductFacts)
    assert isinstance(trace, ExtractionTrace)
