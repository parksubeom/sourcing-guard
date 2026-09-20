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

from tests.srccheck import markup_only
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
    body = markup_only(_HTML)                              # 주석은 화면이 아니다
    for n in (s["categories"], s["observed"], s["silent"], s["titles"]):
        assert str(n) not in body, f"화면에 {n} 이 박혀 있다 - 서버에서 그려라"
        assert f"{n:,}" not in body, f"화면에 {n:,} 이 박혀 있다"


def test_the_label_lives_on_in_the_data_not_on_the_screen():
    """⚠⚠ 이 검사는 **뜻이 바뀌었다** (2026-09-20 총괄).

    옛 화면은 표에 퍼센트를 그렸기 때문에 "매칭률이지 정답률이 아니다" 라는
    라벨을 **반드시 그려야** 했다. 표를 내렸으므로 라벨이 붙을 수가 없다 -
    수식할 수가 없어졌다.

    ⚠ 라벨 자체는 자료에 남는다. 표를 다시 그릴 일이 생기면 이 라벨도 같이
      돌아와야 한다 - 그래서 **서버에서 사라지지 않았는지**를 여기서 본다.
    """
    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    with TestClient(app) as c:
        assert c.get("/api/v1/guide").json()["summary"]["label"] == LABEL
    assert "매칭" not in markup_only(_HTML), "화면에 「매칭」이 돌아왔다"


def test_the_page_never_calls_a_silent_category_out_of_scope():
    """⚠⚠ '붙음 0' 은 **우리가 못 붙인 것**이지 비대상이 아니다 (R3).

    "비대상입니다"·"대상 아님" 을 화면에 쓰면 그 순간 판정이 된다.
    """
    # ⚠ 2026-09-20 에 답이 표에서 **카드**로 옮겨졌다. 그래서 문장이 JS 에
    #   있다 - 검사도 따라간다. 뜻은 한 글자도 안 바뀌었다.
    body = markup_only(_HTML) + markup_only(_JS)
    for banned in ("비대상입니다", "대상이 아닙니다", "대상 아님", "해당 없음",
                   "안 다룹니다", "다루지 않습니다"):
        assert banned not in body, f"단정 표현 '{banned}' 가 있다"
    assert "저희가 못 찾은 것입니다" in body, "못 찾은 것의 뜻을 화면이 설명하지 않는다"
    assert "의무가 없다는 뜻은 아닙니다" in body, (
        "품목 0 을 '의무 없음' 으로 읽을 수 있게 두었다 (R3)")


def test_the_page_declares_its_boundary_not_a_hole():
    """⚠ 침묵 47 중 다수가 식품·여행이다. **구멍이 아니라 선언된 경계다.**

    심사에서 "왜 비었나" 를 물었을 때 답이 있는 것과 없는 것은 다르다.
    README 의 "화장품·식품 등 식약처 소관 | 불가" 와 같은 말이어야 한다.
    """
    body = markup_only(_HTML)
    # ⚠ 낱말이 쉬운 말로 바뀌었다 (2026-09-20). 「소관」·「선언된 경계」는
    #   뜻은 좋은데 처음 보는 사람이 못 읽는다. **단정하는 것은 뜻이다** -
    #   어디 담당인지 말하고, 빈 것이 빠뜨린 것이 아니라고 말하는가.
    assert "식약처" in body, "어디 담당인지 안 적혀 있다"
    assert "빠뜨린 것이 아니라" in body, "빈 칸이 구멍이 아니라는 말이 없다"
    assert "다루지" in body and "않기로 한 범위" in body


def test_the_screen_shows_no_number_that_could_be_read_as_accuracy():
    """⚠⚠ 이 검사도 **뜻이 바뀌었다** (2026-09-20 총괄).

    옛 화면은 퍼센트를 그렸으므로 "맞힌 비율이 아닙니다" 를 **반드시 적어야**
    했다. 이제 퍼센트가 0건이라 오해할 수가 없다 - 그래서 단서 대신
    **수가 없는 것**을 단정한다.

    ⚠ 머리의 한 줄(198개 · 18,938개)은 **양**이다. "실제로 넣어 봤습니다" 로
      끝나서 정확도로 읽히지 않는다.
    """
    body = markup_only(_HTML) + markup_only(_JS)
    assert "%" not in body, "퍼센트가 돌아왔다"
    assert "matched_pct" not in body, "퍼센트 값을 읽고 있다"
    assert "실제로 넣어 봤습니다" in body, "머리 한 줄이 양이라는 것을 안 말한다"


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


# ── 「내 카테고리가 되나요?」 (2026-09-20 총괄) ──────────────────────
def _guide_src() -> tuple[str, str]:
    from pathlib import Path as _P

    from tests.srccheck import markup_only

    root = _P(__file__).resolve().parents[1] / "sourcing_guard" / "static"
    return (markup_only((root / "guide.html").read_text(encoding="utf-8")),
            markup_only((root / "guide.js").read_text(encoding="utf-8")))


def test_the_screen_shows_no_percentage_and_no_matching_word():
    """⚠⚠ 표의 수는 **셀러에게 적용되는 수가 아니다.**

        이 표      배치 경로 — 상품명 글자만, AI 안 씀
        셀러의 검사  단건 경로 — 상세페이지 전체, AI 추출

    「남성신발 14%」를 보고 "나는 14% 확률이구나" 로 읽으면 틀린다. 그래서
    화면에서 내렸다 - 자료(`/api/v1/guide` · TSV · docs)는 그대로다.

    ⚠ 반대 방향 - 되돌리면 실패한다.
    """
    html, js = _guide_src()
    for src, name in ((html, "guide.html"), (js, "guide.js")):
        assert "%" not in src, f"{name} 에 퍼센트가 있다"
        assert "매칭" not in src, f"{name} 에 「매칭」이 남아 있다"
        assert "matched_pct" not in src, f"{name} 이 퍼센트 값을 읽는다"
    assert "<table" not in html, "표가 살아 있다"
    assert "읽는 법" not in html, "일곱 단락 설명이 살아 있다"


def test_the_data_behind_the_screen_is_untouched():
    """⚠ 화면에서만 내렸다. 자료를 지우면 되돌릴 수 없다."""
    from pathlib import Path as _P

    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    root = _P(__file__).resolve().parents[1]
    assert (root / "sourcing_guard/data/category_guide.tsv").exists(), "TSV 가 사라졌다"
    with TestClient(app) as c:
        d = c.get("/api/v1/guide").json()
    assert len(d["rows"]) > 150, "API 가 행을 잃었다"
    assert "matched_pct" in d["rows"][0], "API 에서 값을 지웠다 - 화면만 내리는 것이다"


def test_the_three_answers_split_on_real_categories():
    """답 셋이 **자료에서** 갈린다. 새 분류표를 만들지 않았다."""
    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    with TestClient(app) as c:
        rows = {r["category"]: r for r in c.get("/api/v1/guide").json()["rows"]}

    assert rows["유아동잡화"]["matched"] > 0, "① 예시가 자료에서 안 갈린다"
    assert rows["카시트"]["matched"] == 0, "② 예시가 자료에서 안 갈린다"
    assert "자동차관리법" in rows["카시트"]["jurisdictions"], "③ 예시가 자료에 없다"

    js = _guide_src()[1]
    assert "r.matched > 0" in js, "① / ② 를 matched 로 안 가른다"
    assert "JURIS_MIN = 10" in js, "③ 문턱이 10이 아니다"
    assert "jurisCount" in js, "소관 관찰 건수를 안 센다"


def test_a_car_seat_is_never_told_we_do_not_cover_it():
    """⚠⚠ **이게 핵심 가드다.**

    카시트는 자동차관리법 20건이 관찰되지만 **어린이제품이기도 하다.**
    소관 관찰만 보고 "안 다룹니다" 로 밀어내면 진짜 대상 상품을 내보낸다.
    """
    js = _guide_src()[1]
    for banned in ("안 다룹니다", "다루지 않습니다", "대상이 아닙니다", "해당 없음"):
        assert banned not in js, f"소관 관찰을 밀어내기로 쓴다: {banned}"

    # ③ 은 **덧붙임**이다 - 답을 바꾸지 않는다.
    add = js[js.index("jurisCount(r.jurisdictions) >= JURIS_MIN"):]
    add = add[: add.index("\n    }")]
    assert "gd-also" in add, "③ 이 별도 덧붙임이 아니다"
    assert "함께 확인" in add, "③ 이 배제로 쓰인다"


def test_the_empty_answer_still_offers_the_real_path():
    """품목을 못 찾았을 때 **끝내지 않는다.** 표본은 상품명 글자만 본 것이다."""
    js = _guide_src()[1]
    quiet = js[js.index('gd-a quiet'):]
    quiet = quiet[: quiet.index("</div>")]
    assert "상품명 글자만" in quiet, "왜 못 찾았는지 안 말한다"
    assert "결과가 다를 수 있습니다" in quiet, "직접 넣으면 다를 수 있다는 말이 없다"
    assert "/scan" in quiet, "다음 걸음이 없다"


def test_the_nav_says_what_the_page_answers():
    """「카테고리 가이드」는 무엇을 답하는지 안 말한다. 항목 수는 다섯 그대로."""
    from pathlib import Path as _P

    from tests.srccheck import markup_only

    root = _P(__file__).resolve().parents[1] / "sourcing_guard" / "static"
    for f in sorted(root.glob("*.html")):
        body = markup_only(f.read_text(encoding="utf-8"))
        nav = body[body.index('<nav class="pages"'):]
        nav = nav[: nav.index("</nav>")]
        assert "다루는 범위" in nav, f"{f.name}: 내비 라벨이 안 바뀌었다"
        assert "카테고리 가이드" not in nav, f"{f.name}: 옛 라벨이 남아 있다"
        assert nav.count("<a ") == 5, f"{f.name}: 내비 항목이 다섯이 아니다 (320px 넘침)"
