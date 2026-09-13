"""랜딩 히어로의 "예시 결과" 카드를 **코드 상수에 묶는다** ([디자인 v2] ⓷).

⚠⚠ **랜딩은 `/api/v1/scan` 을 부르지 않는다.** 부르면 방문마다 LLM 호출이
  나가고, 상한을 넘기는 순간 투표자가 **첫 화면에서 429** 를 본다. 그래서
  배포본에서 실측 1회로 뜬 결과를 파일로 두고 그린다.

⚠ 얼린 값의 위험은 **서버 문장이 바뀌어도 화면은 옛 문장을 계속 말하는 것**
  이다. 이 검사가 그것을 잡는다 - 상수가 바뀌면 여기서 깨지고, 그때 다시
  재서 fixture 를 갱신한다. 손으로 고치면 화면이 없는 문장을 말하게 된다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sourcing_guard.demos import preview
from sourcing_guard.models import FindingKind, Signal
from sourcing_guard.scorer import _HEADLINE, _axes

_FIXTURE = Path("sourcing_guard/data/demo_amber_result.json")


def test_the_fixture_exists_and_records_where_it_came_from():
    """출처 없는 얼린 값은 지어낸 값과 구별되지 않는다 (R5)."""
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    기록 = raw["_기록"]
    for key in ("무엇", "왜", "어떻게", "언제", "배포본", "추출 회차"):
        assert 기록.get(key), f"_기록.{key} 가 비었다"


def test_the_preview_headline_is_the_current_scorer_constant():
    """문구가 갈라지면 랜딩이 **서버가 하지 않는 말**을 하게 된다."""
    p = preview()
    assert p is not None
    assert p["signal"] == Signal.AMBER.value
    assert p["headline"] == _HEADLINE[Signal.AMBER]


def test_the_headline_still_splits_into_two_lines_at_the_dash():
    """화면이 " — " 에서 두 줄로 나눠 그린다. 문장은 안 바꾼다."""
    head, sep, tail = preview()["headline"].partition(" — ")
    assert sep, "헤드라인에 ' — ' 가 없다 - 화면이 한 줄로 흐른다"
    assert head and tail


def test_the_preview_axes_are_the_three_the_server_sends():
    """축이 넷이 되거나 이름이 바뀌면 예시 카드가 옛 축을 그린다."""
    names = [a["name"] for a in preview()["axes"]]
    assert names == [a["name"] for a in _axes([], None)]
    assert len(names) == 3


def test_the_preview_axes_carry_no_time_relative_clause():
    """⚠ 얼린 카드에 "오늘 12:33 갱신" 이 들어 있으면 **내일이면 거짓**이다.

    실제로 실측 원문에 그 절이 있었다. 대조 범위(공표분까지)만 남긴다.
    """
    for a in preview()["axes"]:
        note = a.get("note") or ""
        assert "오늘" not in note and "갱신" not in note, note


def test_every_preview_row_is_a_real_finding_kind_with_a_source():
    """근거 없는 줄은 존재할 수 없다 (R2). 예시 카드도 예외가 아니다."""
    rows = preview()["rows"]
    assert rows, "예시 카드에 근거 줄이 하나도 없다"
    kinds = {k.value for k in FindingKind}
    for r in rows:
        assert r["kind"] in kinds, r["kind"]
        assert r["source_url"] and r["source_label"], r
        assert r["statement_ko"].strip()


def test_the_preview_shows_both_the_reason_for_the_signal_and_something_verified():
    """한 카드 안에서 **왜 주의인가**와 **무엇이 확인됐나**를 같이 보여 준다.

    한쪽만 그리면 셀러가 "전부 문제" 또는 "전부 정상" 으로 읽는다.
    """
    kinds = [r["kind"] for r in preview()["rows"]]
    assert FindingKind.SUBSTANCE_MENTIONED.value in kinds
    assert FindingKind.KC_VERIFIED.value in kinds
    signals = {r["signal"] for r in preview()["rows"]}
    assert len(signals) > 1, f"근거 줄 신호가 하나뿐이다: {signals}"


def test_the_preview_statements_still_match_what_the_verifier_says_today():
    """문장 **형식**이 바뀌면 여기서 깨진다.

    ⚠ 전문 비교가 아니라 형식 비교다 - 인증번호·기준치 같은 값은 그 실측의
      것이라 지금 돌려도 같을 이유가 없다. 바뀌면 안 되는 것은 "우리가 이런
      모양으로 말한다" 쪽이다.
    """
    rows = {r["kind"]: r["statement_ko"] for r in preview()["rows"]}
    cert = rows[FindingKind.KC_VERIFIED.value]
    assert "조회되었습니다" in cert and "인증상태:" in cert, cert
    sub = rows[FindingKind.SUBSTANCE_MENTIONED.value]
    assert "표기가 감지되었습니다" in sub, sub


def test_the_preview_is_not_drawn_by_calling_scan():
    """랜딩이 스캔을 부르면 방문마다 LLM 이 나간다 - 첫 화면에서 429 를 본다.

    ⚠ **코드만 본다.** 처음에 원문 통째로 봤더니 "랜딩은 스캔을 부르지 않는다"
      고 적은 **자기 주석**에 걸렸다 - 이 저장소에서 열한 번째다. 주석을 고쳐
      피하면 다음 사람이 또 겪으므로 가드 쪽을 고친다.
    """
    html = Path("sourcing_guard/static/landing.html").read_text(encoding="utf-8")
    code = re.sub(r"<!--.*?-->|/\*.*?\*/", "", html, flags=re.S)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    assert "/api/v1/scan" not in code, "랜딩이 스캔을 부른다"


def test_the_app_never_reads_anything_the_deploy_image_does_not_ship():
    """⚠⚠ **배포본에서 예시 카드가 안 그려졌다** (2026-09-13 · 인수 검사가 잡았다).

    fixture 를 `tests/fixtures/` 에 뒀는데 `Dockerfile` 은 `sourcing_guard/` 와
    `scripts/` 만 담는다. 로컬에서는 전부 통과하고 **배포본에서만** 비는
    종류의 결함이라, 배포 전에 잡을 가드가 필요하다.

    여기서는 두 가지를 본다:
      (1) 패키지 코드가 `tests/` 경로를 런타임에 읽지 않는다
      (2) 프리뷰 파일이 실제로 이미지에 담기는 디렉터리 아래에 있다
    """
    root = Path(__file__).resolve().parents[1]
    shipped = {
        line.split()[1].rstrip("/")
        for line in (root / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("COPY ") and len(line.split()) >= 3
    }
    assert "sourcing_guard" in shipped, shipped
    assert "tests" not in shipped, "Dockerfile 이 시험 자료를 담는다"

    for py in (root / "sourcing_guard").rglob("*.py"):
        code = re.sub(r"#[^\n]*", "", py.read_text(encoding="utf-8"))
        assert '"tests' not in code and "'tests" not in code, (
            f"{py.name} 이 런타임에 tests/ 를 읽는다 - 배포 이미지에 없다"
        )

    from sourcing_guard.demos import _PREVIEW_PATH

    rel = _PREVIEW_PATH.relative_to(root)
    assert rel.parts[0] in shipped, f"{rel} 는 배포 이미지에 담기지 않는다"
    assert _PREVIEW_PATH.exists(), rel
