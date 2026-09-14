"""[M-5] 카테고리 가이드 — **안내 축이다. 아무것도 판정하지 않는다.**

지켜야 할 것 (미완 §1-d):
    신호등을 바꾸지 않는다 · 등급을 붙이지 않는다 · 다섯 숫자 0/0/0/0/0

⚠⚠ 이 표의 숫자는 **매칭률**이고 정답률이 아니다. 71% 시절의 실수가 정확히
  "매칭률을 정답률처럼 쓴 것" 이라 라벨을 화면이 반드시 그리게 잠근다.

⚠ '붙음 0' 을 "비대상" 으로 적으면 판정이 된다 (R3 · §9).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sourcing_guard.category_guide import LABEL, rows, summary
from sourcing_guard.main import app

_ROOT = Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "sourcing_guard/static/guide.html").read_text(encoding="utf-8")
_JS = (_ROOT / "sourcing_guard/static/guide.js").read_text(encoding="utf-8")
_TSV = _ROOT / "sourcing_guard/data/category_guide.tsv"
_COVERAGE = _ROOT / "tests/fixtures/도매꾹_표본_2026-09-12/커버리지.tsv"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ── 1. 자료가 [M-3] 과 같은 숫자를 말한다 ─────────────────────────
def test_the_matched_counts_equal_the_coverage_map():
    """⚠⚠ **두 문서가 다른 숫자를 말하는 것이 이 저장소의 반복 결함이다.**

    가이드는 [M-3] 커버리지 지도와 **같은 배치 경로**를 돌려 만든다. 붙음 수가
    다르면 둘 중 하나가 낡은 것이고, 그 상태로 화면에 올리면 셀러가 보는 수와
    문서의 수가 갈린다.
    """
    expected = {}
    for ln in _COVERAGE.read_text(encoding="utf-8").splitlines():
        if ln and not ln.startswith("#"):
            c = ln.split("\t")
            if len(c) >= 6:
                expected[c[0]] = int(c[5])

    got = {r.code: r.matched for r in rows()}
    assert got, "가이드 자료가 비었다"
    diff = {k: (expected[k], got[k]) for k in expected if k in got and expected[k] != got[k]}
    assert not diff, f"[M-3] 과 다른 카테고리: {list(diff.items())[:5]}"
    assert set(expected) == set(got), (
        f"지도에만 {sorted(set(expected) - set(got))[:3]} · "
        f"가이드에만 {sorted(set(got) - set(expected))[:3]}"
    )


def test_the_summary_is_counted_not_written():
    """요약 수는 **세어서** 낸다. 적어 두면 자료가 바뀔 때 낡는다."""
    s = summary()
    rs = rows()
    assert s["categories"] == len(rs)
    assert s["observed"] == sum(1 for r in rs if r.matched > 0)
    assert s["silent"] == len(rs) - s["observed"]
    assert s["titles"] == sum(r.sampled for r in rs)
    assert s["label"] == LABEL


# ── 2. 화면이 숫자를 들고 있지 않다 ──────────────────────────────
def test_the_page_hardcodes_no_number_from_the_data():
    """⚠ 랜딩 ④ 와 같은 규칙 - 숫자는 그 자리에서 그린다.

    자료가 바뀌면 화면이 따라와야 하는데, HTML 에 적으면 한쪽만 낡는다.
    """
    s = summary()
    body = re.sub(r"<!--.*?-->", "", _HTML, flags=re.S)   # 주석은 화면이 아니다
    for n in (s["categories"], s["observed"], s["silent"], s["titles"]):
        assert str(n) not in body, f"화면에 {n} 이 박혀 있다 - 서버에서 그려라"
        assert f"{n:,}" not in body, f"화면에 {n:,} 이 박혀 있다"


def test_the_label_is_drawn_on_the_screen():
    """**매칭률이라는 라벨을 화면이 반드시 그린다.**"""
    assert 'id="label"' in _HTML, "라벨 자리가 없다"
    assert "s.label" in _JS, "화면이 서버 라벨을 안 읽는다"
    assert LABEL not in _HTML, "라벨 문구를 HTML 에 적었다 - 서버에서 그린다"


def test_the_page_never_calls_a_silent_category_out_of_scope():
    """⚠⚠ '붙음 0' 은 **우리가 못 붙인 것**이지 비대상이 아니다 (R3).

    "비대상입니다"·"대상 아님" 을 화면에 쓰면 그 순간 판정이 된다.
    """
    body = re.sub(r"<!--.*?-->", "", _HTML, flags=re.S)
    for banned in ("비대상입니다", "대상이 아닙니다", "대상 아님", "해당 없음"):
        assert banned not in body, f"단정 표현 '{banned}' 가 있다"
    assert "못 붙인 것" in body, "붙음 0 의 뜻을 화면이 설명하지 않는다"


def test_the_page_says_the_number_is_not_an_accuracy():
    body = re.sub(r"<!--.*?-->", "", _HTML, flags=re.S)
    assert "맞힌 비율이 아닙니다" in body
    assert "검수하지 않았습니다" in body


# ── 3. 경로 ────────────────────────────────────────────────────
def test_the_api_returns_every_row(client: TestClient):
    d = client.get("/api/v1/guide").json()
    assert d["summary"]["label"] == LABEL
    assert len(d["rows"]) == len(rows())
    first = d["rows"][0]
    for key in ("code", "category", "matched", "sampled", "items", "grades",
                "grade_sources", "annexes", "jurisdictions", "observed"):
        assert key in first, key


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_the_page_answers_both_methods(client: TestClient, method: str):
    """⚠ HEAD 에 405 를 주면 가동 감시·링크 미리보기가 실패로 읽는다."""
    assert client.request(method, "/guide").status_code == 200


def test_every_page_links_the_guide():
    """화면을 만들고 링크를 안 걸면 아무도 못 본다."""
    for name in ("landing.html", "index.html", "batch.html", "watch.html"):
        src = (_ROOT / "sourcing_guard/static" / name).read_text(encoding="utf-8")
        assert 'href="/guide"' in src, f"{name} 에 가이드 링크가 없다"


# ── 4. 안내 축이 판정 경로를 건드리지 않는다 ──────────────────────
def test_the_guide_is_not_reachable_from_the_judging_path():
    """⚠⚠ **안내가 신호를 바꾸면 그건 판정이다** (미완 §1-d).

    `verifier`·`scorer`·`item_grades` 가 가이드를 부르면 안내 자료가 등급에
    닿는다. 부르지 않는 것을 검사로 잠근다.
    """
    for name in ("verifier.py", "scorer.py", "item_grades.py", "batch.py"):
        src = (_ROOT / "sourcing_guard" / name).read_text(encoding="utf-8")
        assert "category_guide" not in src, f"{name} 이 가이드를 부른다"


def test_the_data_file_carries_its_label_and_how_to_rebuild_it():
    """손으로 고치지 못하게 - 만드는 법이 파일 안에 있어야 한다 (§6)."""
    head = _TSV.read_text(encoding="utf-8")[:900]
    assert "매칭률" in head and "정답률이 아니다" in head
    assert "build_category_guide.py" in head
    assert "LLM 0" in head and "네트워크 0" in head
