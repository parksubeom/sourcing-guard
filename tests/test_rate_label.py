"""적중률 **글자**는 서버가 만든다 — 화면이 짓지 않는다.

2026-09-28 에 랜딩이 `77%`, 체험표본이 `77.0%` 를 적고 있었다. 같은 수인데
화면마다 다른 글자였다. 원인은 JS 에 정수/실수 구분이 없어서다 - JSON 의
`77.0` 이 숫자 `77` 이 되고 `+ "%"` 가 `.0` 을 지운다.

`_baseline_snapshot` 바로 그 자리의 주석이 **「소수 한 자리. 화면이 다시
계산하면 반올림이 갈린다」**를 이미 걱정하고 있었다. 걱정한 방향(재계산)은
막혀 있었고 **안 적은 쪽(서식)이 뚫려 있었다** — §6 의 그 패턴이다.

고친 방식은 `scorer._UNLOCK_KO`("축 이름을 셀러의 말로. **화면이 짓지 않게**
여기서 준다")와 같다: 서버가 `ok_rate_label` 을 주고 화면은 찍기만 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from sourcing_guard import main as app_module
from tests.srccheck import markup_only

_LANDING = (Path(__file__).resolve().parents[1]
            / "sourcing_guard" / "static" / "landing.html").read_text(encoding="utf-8")


def _baseline() -> dict:
    return TestClient(app_module.app).get("/healthz").json()["baseline"]


def test_the_server_ships_a_display_string():
    b = _baseline()
    assert "ok_rate_label" in b, "표시 문자열이 없으면 화면이 만들게 된다"
    assert isinstance(b["ok_rate_label"], str)
    assert re.fullmatch(r"\d+\.\d%", b["ok_rate_label"]), b["ok_rate_label"]


def test_the_label_and_the_number_never_disagree():
    """두 필드를 다 내보내므로 **갈리지 않는지**를 잠근다 (§6)."""
    b = _baseline()
    assert b["ok_rate_label"] == f"{b['ok_rate']:.1f}%"


def test_a_whole_number_rate_still_shows_one_decimal(monkeypatch):
    """**정수 모양일 때도 소수 한 자리.** 이 검사가 이번 결함 자체다.

    오늘 값(104/135 → 77.0)이 이미 그 경우이지만, 기준선이 움직여 80/100 같은
    딱 떨어지는 수가 되어도 화면은 `80%` 가 아니라 `80.0%` 여야 한다.
    """
    monkeypatch.setitem(
        app_module.BASELINE, app_module.BASELINE_EXTRACTOR,
        {"denominator": 100, "ok": 80, "off_target": 0})
    got = app_module._baseline_snapshot()
    assert got["ok_rate"] == 80.0
    assert got["ok_rate_label"] == "80.0%", "정수 모양에서 .0 이 사라졌다"


def test_the_landing_prints_the_label_and_does_not_build_one():
    """화면은 받아 찍기만 한다.

    ⚠ 주석을 먼저 걷는다 - 이 규칙을 설명한 주석이 규칙 대신 잡힌다 (§6①).
      `landing.html` 머리 주석과 고친 자리 주석이 둘 다 옛 모양을 인용한다.
    """
    code = markup_only(_LANDING)
    assert "ok_rate_label" in code, "서버가 준 글자를 안 쓴다"
    # 화면이 스스로 만드는 모양 — 어느 쪽도 있으면 안 된다.
    for built in ('ok_rate + "%"', "ok_rate + '%'", "ok_rate.toFixed"):
        assert built not in code, f"화면이 글자를 만들고 있다: {built}"


def test_the_stale_example_percent_is_gone():
    """`70.4%` 는 검수 전 95/135 의 값이다. 예시로 박아 두면 낡는다 (§6)."""
    for path in ("sourcing_guard/static/landing.html", "sourcing_guard/main.py"):
        src = (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
        hits = [ln for ln in src.splitlines() if "70.4%" in ln]
        # 고친 경위를 적은 줄 하나는 남겨도 되지만, **예시로 쓰는 줄**은 없어야 한다.
        bad = [ln for ln in hits if "전에" not in ln and "옛" not in ln]
        assert not bad, f"{path}: 낡은 예시 값이 남아 있다 — {bad}"
