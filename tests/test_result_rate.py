"""[E] 유효 결과율 — **구체적인 것을 하나라도 준 검사의 비율.**

매칭률과 별개로 우리가 움직여야 할 지표다. 매칭률이 올라도 화면이 "확인 필요"
세 줄뿐이면 셀러에게 준 것이 없다.

⚠ "원문 링크가 붙었나" 로는 아무것도 갈리지 않는다 - **모든 `Finding` 이
  `source_url` 을 갖는다**(R2). 갈라야 하는 것은 "이 상품에 대해 무엇을 말했나" 다.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from sourcing_guard.main import app
from sourcing_guard.recall_index import RecallIndex
from sourcing_guard.models import (
    NON_SPECIFIC_FINDING_KINDS,
    SPECIFIC_FINDING_KINDS,
    Finding,
    FindingKind,
    Signal,
)
from sourcing_guard.scorer import has_specific_finding

client = TestClient(app)


class _FakeRecallStore:
    """`RecallIndex` 가 쓰는 것만 흉내낸다 - `recall_payloads` · `latest_published_on`.

    ⚠ **MagicMock 을 쓰지 않는다.** 목이면 `RecallIndex` 의 인터페이스가 바뀌어도
      조용히 통과한다. 실제 `RecallIndex` 를 이 가짜 store 위에 올리면 매칭·
      is_empty·as_of 가 모두 **진짜 코드**를 타므로, 인터페이스가 갈라지면 여기서
      깨진다.
    """

    def __init__(self, records: "list[dict]") -> None:
        self._payloads = [json.dumps(r) for r in records]

    def recall_payloads(self, *, scope: str | None = None) -> list[str]:
        return list(self._payloads)

    def latest_published_on(self) -> str | None:
        return "20260908"


def _recall_index_with_one_unrelated_record() -> RecallIndex:
    """색인은 **비어 있지 않고**, 우리 입력과는 일치하지 않는 상태.

    ⚠ 이 상태가 `recall_clear` 를 낳는다. 색인이 비면 `verifier` 가
      `recall_available=False` 로 보고 `lookup_failed` 를 내며, 그것은
      "대조했지만 없었다" 가 아니라 "대조를 못 했다" 다 - 둘을 섞으면 R3 위반이다.
    """
    return RecallIndex(
        _FakeRecallStore([
            {
                "product_name": "무관한 리콜 상품 · 산업용 절단기",
                "model_name": "ZZ-9999-NOMATCH",
                "maker": "무관제조",
                "reason": "감전 위험",
                "announced_on": "20260901",
                "detail_url": "https://www.safetykorea.kr/recall/1",
                "scope": "domestic",
                "models": ["ZZ-9999-NOMATCH"],
                "cert_numbers": [],
                "uid": "fake-1",
            }
        ])
    )


@pytest.fixture(autouse=True)
def _no_live_government_api(monkeypatch):
    """네트워크를 쓰지 않는다 (CLAUDE.md §7).

    ⚠⚠ **리콜 색인도 여기서 만든다.** 전에는 `_kats`·`_rra` 만 목킹하고 리콜
      축은 프로세스가 들고 있는 `data/watchlist.db`(33MB · 커밋 안 됨)를 그대로
      썼다. 그래서 이 파일은 **그 DB 가 있는 PC 에서만 통과**했고, 새 PC · CI ·
      총괄 검증 환경에서는 `recall_clear` 대신 `lookup_failed` 가 나와 깨졌다.

      DB 유무로 skip 하지 않는다 - skip 은 아무것도 지키지 않는다. 검사가
      필요한 상태를 **스스로 만든다.**
    """
    from unittest.mock import MagicMock

    import sourcing_guard.main as m

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    monkeypatch.setattr(m, "_kats", kats)
    monkeypatch.setattr(m, "_rra", None)
    monkeypatch.setattr(m, "_recalls", _recall_index_with_one_unrelated_record())


def _f(kind: FindingKind) -> Finding:
    return Finding(
        kind=kind, signal=Signal.UNKNOWN, statement_ko="어떤 사실",
        source_label="근거", source_url="https://www.safetykorea.kr/",
        checked_at=date(2026, 9, 9),
    )


# ── 분류가 빠짐없다 ─────────────────────────────────────────────────
def test_every_finding_kind_is_classified():
    """새 종류가 생기면 **결정을 강제한다.**

    자동으로 "구체적" 이 되면 지표가 조용히 부풀고, 자동으로 "비구체적" 이 되면
    조용히 깎인다. 둘 다 그 지표를 못 믿게 만든다.
    """
    everything = set(FindingKind)
    assert SPECIFIC_FINDING_KINDS | NON_SPECIFIC_FINDING_KINDS == everything, (
        "분류 안 된 종류: "
        f"{sorted(k.value for k in everything - SPECIFIC_FINDING_KINDS - NON_SPECIFIC_FINDING_KINDS)}"
    )
    assert not (SPECIFIC_FINDING_KINDS & NON_SPECIFIC_FINDING_KINDS)


@pytest.mark.parametrize("kind", [
    FindingKind.INFO_REQUEST,       # 우리가 **묻는** 것이다
    FindingKind.COVERAGE_GAP,       # 수록 범위 밖이라고 말한 것
    FindingKind.LOOKUP_FAILED,      # 조회를 **못 했다**
    FindingKind.KC_TIER_UNKNOWN,    # 등급을 몰라 부재를 해석 못 한다
    FindingKind.RECALL_CLEAR,       # 모든 검사에 붙는다 - 아래 검사 참조
])
def test_these_are_not_something_we_gave_the_seller(kind):
    assert kind in NON_SPECIFIC_FINDING_KINDS
    assert not has_specific_finding([_f(kind)])


@pytest.mark.parametrize("kind", [
    FindingKind.KC_VERIFIED,
    FindingKind.KC_REVOKED,
    FindingKind.KC_ABSENCE_EXPECTED,   # "이 등급에선 부재가 정상" 은 답이다 (R3-b)
    FindingKind.ITEM_GRADE_MATCHED,
    FindingKind.OUT_OF_SCOPE,          # "다른 부처 소관" 도 답이다
    FindingKind.RECALL_MATCH,
    FindingKind.HAZARD_RULE_APPLIES,
])
def test_these_are_something_we_gave_the_seller(kind):
    assert kind in SPECIFIC_FINDING_KINDS
    assert has_specific_finding([_f(kind)])


# ── recall_clear 를 뺀 이유 ─────────────────────────────────────────
def test_recall_clear_alone_does_not_count_or_the_metric_never_moves():
    """`recall_clear` 는 **모든 검사에 붙는다.**

    URL 만 붙여넣어 우리가 아무것도 못 읽은 검사에도 붙고, 그때 "일치 항목을
    찾지 못했습니다" 는 대조할 것이 없어서 못 찾은 것이다. 넣으면 지표가 항상
    1.0 이 되고 **움직이지 않는 지표는 지표가 아니다.**
    """
    body = client.post(
        "/api/v1/scan", json={"page_text": "https://example.com/goods/12345"}
    ).json()
    kinds = {f["kind"] for f in body["findings"]}
    # ⚠ 색인은 fixture 가 만든다. 로컬 DB 에 의존하면 이 줄이 환경마다 갈린다.
    assert "recall_clear" in kinds, (
        f"이 검사의 전제가 바뀌었다 - 나온 것: {sorted(kinds)}"
    )
    assert not has_specific_finding(
        [Finding(**{**f, "checked_at": None}) for f in body["findings"]]
    ), kinds


def test_a_real_product_does_count():
    body = client.post(
        "/api/v1/scan", json={"page_text": "유아용 블록 완구 장난감 대상연령 3세"}
    ).json()
    kinds = {f["kind"] for f in body["findings"]}
    assert kinds & {k.value for k in SPECIFIC_FINDING_KINDS}, kinds


# ── /healthz ────────────────────────────────────────────────────────
def test_healthz_reports_the_rate_and_says_what_it_is_not():
    body = client.get("/healthz").json()
    r = body["results"]
    for key in ("scans", "with_specific_finding", "rate", "note"):
        assert key in r, key
    # ⚠ 프로세스 메모리이고 단건 경로만 센다 - 그 사실이 값과 함께 있어야 한다.
    assert "프로세스 메모리" in r["note"]
    assert "단건" in r["note"]


def test_the_counter_moves_and_discriminates():
    import sourcing_guard.main as m

    before = m._result_stats.snapshot()
    client.post("/api/v1/scan", json={"page_text": "https://example.com/x"})
    client.post("/api/v1/scan",
                json={"page_text": "유아용 블록 완구 장난감 대상연령 3세"})
    after = m._result_stats.snapshot()

    assert after["scans"] == before["scans"] + 2
    # 하나만 구체적이어야 한다 - 둘 다 세면 지표가 안 갈린다.
    assert after["with_specific_finding"] == before["with_specific_finding"] + 1


# ── 판정에 쓰지 않는다 (R1) ─────────────────────────────────────────
def test_the_metric_is_not_used_for_the_signal():
    """관측 지표가 신호를 바꾸면 "구체적 finding 이 많으면 위험" 이 된다."""
    import inspect

    from sourcing_guard import scorer

    # 판정을 만드는 함수들이 이 집합을 보면 안 된다.
    for fn in (scorer.score, scorer._signal_for, scorer.recall_match_earns_red):
        src = inspect.getsource(fn)
        assert "SPECIFIC_FINDING_KINDS" not in src, (
            f"{fn.__name__} 이 관측 지표 집합을 본다 - 판정에 새고 있다"
        )
    # 오직 이 헬퍼만 본다.
    assert "SPECIFIC_FINDING_KINDS" in inspect.getsource(scorer.has_specific_finding)

    # 같은 findings 에 대해 지표와 신호가 독립인지 실물로 확인한다.
    from sourcing_guard.models import ItemCategory, ProductFacts

    facts = ProductFacts(product_name="블록 완구", category=ItemCategory.CHILDREN_TOY)
    findings = [_f(FindingKind.KC_VERIFIED)]
    assert has_specific_finding(findings) is True
    signal_with = scorer.score(facts, findings).signal
    # 비구체적 finding 을 하나 더해도 신호는 그것 때문에 바뀌지 않는다.
    signal_more = scorer.score(facts, findings + [_f(FindingKind.INFO_REQUEST)]).signal
    assert signal_with is signal_more
