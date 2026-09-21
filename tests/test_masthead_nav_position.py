"""머리글 내비가 **같은 자리**에 있는가 — 높이·개수가 아니라 위치다.

⚠⚠ 2026-09-21 에 이 축이 비어 있어서 놓쳤다. 어제 보고가 *"헤더 masthead
  65px · 내비 5개 — 8장 전부 같음"* 이었는데, **높이와 개수만 재고 위치를
  안 쟀다.** 실제로는 좌표가 셋으로 갈려 있었다 (1440px 실측):

      /  /scan  /watch              내비 좌 681
      /samples  /misses  /unknown   내비 좌 657
      /batch  /guide                내비 좌 833   ← 152px 오른쪽

  CLAUDE.md §6 *"세기 전에 무엇을 셀 것인가를 먼저 적는다"* 가 가리키는 자리다.

⚠ **이 검사는 좌표를 직접 재지 못한다.** 진짜 불변식은 "여덟 장의 내비
  left·right 가 같다" 이고 그것은 브라우저가 있어야 한다(playwright 는
  requirements.txt 에 없다). 여기서는 **좌표를 그렇게 만든 CSS 두 줄**을
  잠근다 - 대리 검사임을 알고 쓴다. 실좌표는 배포 뒤 브라우저로 잰다.

원인 둘 (2026-09-21 로컬 실측 · 고친 뒤 좌표 가짓수 3 → 1):

    (a) `.masthead .container` 가 `justify-content:space-between` 인데
        배지가 없는 화면은 자식이 셋에서 **둘**이 된다 → 내비가 끝으로 밀린다
    (b) `aria-current="page"` 규칙이 `padding:0 0 2px` 로 **좌우 패딩까지**
        지운다 → 활성 링크만 24px 좁아지고 내비 폭이 511/487 로 갈린다
"""

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parents[1] / "sourcing_guard" / "static" / "app.css"


@pytest.fixture(scope="module")
def css() -> str:
    """⚠⚠ **주석을 걷고 본다.**

    2026-09-21 에 `test_the_icon_box_owns_its_size_in_one_place` 가 자기
    **감사 주석**을 보고 통과했다 - 규칙 위 주석에 "전역 `box-sizing:border-box`
    를 안 받는다" 라고 적어 뒀고, 정작 선언을 지워도 그 글자가 남아서
    가드가 아무것도 못 봤다. CLAUDE.md §6 이 이름 붙인 자리다.

    ⚠ 주석 제거를 여기서 새로 쓰지 않는다 - 오너는 `tests/srccheck.markup_only`
      하나다 (`test_srccheck` 가 그것을 잡는다).
    """
    from tests.srccheck import markup_only

    return markup_only(CSS.read_text(encoding="utf-8"))


def test_the_active_link_keeps_its_horizontal_padding(css):
    """활성 메뉴는 **밑줄**이고(칩이 아니다), 그래서 패딩을 지운다 - 다만
    지워야 하는 것은 세로뿐이다. 좌우까지 지우면 그 링크만 24px 좁아진다.

    ⚠ 반대 방향도 지킨다 - 밑줄이 사라지면 활성 표시가 없어진다.
    """
    rules = re.findall(
        r'nav\.pages a\[aria-current="page"\]\s*\{(.*?)\}', css, re.S)
    assert rules, "활성 메뉴 규칙이 사라졌습니다"

    for body in rules:
        pad = re.search(r"padding\s*:\s*([^;}]+)", body)
        if not pad:
            continue
        parts = pad.group(1).split()
        # padding: <세로> <가로> [<아래>] - 가로가 0 이면 링크가 좁아진다
        assert len(parts) >= 2, (
            f"활성 메뉴 padding 이 한 값입니다({pad.group(1)!r}) - "
            "가로 패딩이 기본 규칙과 갈립니다")
        assert parts[1] not in ("0", "0px"), (
            f"활성 메뉴가 좌우 패딩을 잃었습니다({pad.group(1)!r}). "
            "링크만 24px 좁아져 내비 폭이 화면마다 갈립니다")

    assert re.search(r'nav\.pages a\[aria-current="page"\][^{]*\{[^}]*border-bottom', css, re.S), (
        "활성 메뉴의 밑줄이 없어졌습니다 - 어느 화면인지 표시가 사라집니다")


def test_the_header_has_no_date_badge_at_all(css):
    """⚠⚠ **머리글 기준일 배지를 지웠다** (2026-09-21 시피님 판정 "다 넣던가 다 빼던가").

    전에는 여섯 화면에만 있었다. `/batch`·`/guide` 를 뺀 이유는 그 둘이
    **리콜을 대조하지 않기 때문**이다 - `batch.py` 는 등급표와 번호 형식만 보고
    recall 인덱스를 아예 안 부른다. 거기에 리콜 기준일을 달면 **그 화면도
    리콜을 봤다**고 읽힌다 (R3·§9).

    ⇒ 「다 넣기」가 두 화면에서 거짓이 되므로 전부 뺐다. 기준일은 **결과 카드의
      리콜 축 note** 가 그대로 들고 있다 (`scorer._axes`).

    ⚠ 되살리려면 `/batch`·`/guide` 가 리콜을 대조하게 되었는지 **먼저 확인**할 것.
      아니면 그 둘만 빼는 갈림이 다시 생기고, 그 갈림이 내비를 152px 밀었다.
    """
    import re as _re
    from pathlib import Path as _P

    from tests.srccheck import markup_only

    assert not _re.search(r"\.asof[\s.,:{\[]", css), (
        "배지 CSS 가 남아 있습니다 - 여섯 화면에만 뜨면 내비가 갈립니다")

    static = _P(__file__).resolve().parents[1] / "sourcing_guard" / "static"
    names = ["landing.html", "index.html", "batch.html", "watch.html",
             "guide.html", "samples.html", "misses.html", "unknown.html"]
    assert len(names) == 8
    for n in names:
        src = markup_only((static / n).read_text(encoding="utf-8"))
        assert 'class="asof"' not in src, f"{n} 에 배지가 남아 있습니다"

    # ⚠⚠ **정의를 본다.** 처음에 `"_fill_as_of" not in main` 으로 썼다가
    #   "옛 이름(`_fill_as_of`)을 되살리면 배지가 돌아왔다로 읽힌다" 는
    #   **내 주석**에 걸렸다 (2026-09-21 · 오늘 다섯 번째). 막으려는 것은
    #   그 함수가 **있는 것**이지 이름을 언급하는 것이 아니다 (CLAUDE.md §6 ①).
    main = (_P(__file__).resolve().parents[1] / "sourcing_guard"
            / "main.py").read_text(encoding="utf-8")
    assert not _re.search(r"^def _fill_as_of\b", main, _re.M), (
        "서버가 아직 머리글 배지를 채웁니다")
    assert _re.search(r"^def _fill_footer_asof\b", main, _re.M), (
        "바닥글 기준일을 채우는 곳이 없습니다 - 기준일이 화면에서 사라집니다")


def test_the_recall_date_still_lives_on_the_result_card():
    """배지를 뺐어도 **기준일이 사라지면 안 된다.** "리콜 이력 없음" 의
    유효기간이라 그 문장 옆에 있어야 한다 (R2 와 같은 뿌리).
    """
    from sourcing_guard.models import Finding, FindingKind, Signal
    from sourcing_guard.scorer import _axes

    f = Finding(kind=FindingKind.RECALL_CLEAR, signal=Signal.GREEN,
                statement_ko="x", source_url="https://www.safetykorea.kr/",
                source_label="근거")
    recall = next(a for a in _axes([f], "20260917") if a["key"] == "recall")
    assert "2026-09-17" in (recall["note"] or ""), (
        f"결과 카드에서도 기준일이 사라졌습니다: {recall}")


# ── 바닥글 기준일 ───────────────────────────────────────────────────

_FOOT_PAGES = ["/", "/scan", "/batch", "/watch", "/guide",
               "/samples", "/misses", "/unknown"]


def test_every_screen_says_when_the_recall_copy_is_from():
    """⚠⚠ 머리글 배지를 뺀 뒤 **리콜 사본이 언제 것인지 말하는 유일한 상시
    자리**다 (2026-09-21).

    배지를 뺐을 때 내가 "잃은 것 없습니다" 라고 보고했는데 **틀렸다** -
    총괄이 재 보니 여덟 화면 어디에도 기준일 문자열이 **0** 이었다. 전에는
    여섯 화면 머리글에 늘 보였고, 그 뒤로는 **스캔을 돌려야만** 축 note 에
    나온다. 랜딩·가이드·표본만 보는 사람은 알 방법이 없었다.

    ⚠ 심사에서 "그 데이터 언제 것이냐" 가 첫 질문이다.
    ⚠ 바닥글이라 `/batch`·`/guide` 에 같은 값이 가도 "이 화면이 리콜을 봤다"
      로 안 읽힌다 - 바닥글은 **서비스 전체의 출처 자리**다. 그게 머리글
      배지와 다른 점이고 R3 가 안 걸리는 이유다.
    """
    import re as _re

    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    assert len(_FOOT_PAGES) == 8
    seen = []
    with TestClient(app) as c:
        for path in _FOOT_PAGES:
            html = c.get(path).text
            m = _re.search(r'<p class="row foot-asof">(.*?)</p>', html, _re.S)
            assert m, f"{path} 바닥글에 기준일 줄이 없습니다"
            text = _re.sub(r"<[^>]+>", "", m.group(1))
            assert "리콜 공표" in text and _re.search(r"20\d\d-\d\d-\d\d", text), text
            assert "data-foot-asof" not in html, f"{path}: 빈 슬롯이 남았습니다"
            seen.append(text.strip())
    assert len(set(seen)) == 1, f"화면마다 다른 값이 갑니다: {set(seen)}"


def test_the_footer_date_is_not_written_by_hand():
    """날짜는 **서버가 준다.** 마크업에 박으면 그 문장이 곧 거짓이 된다 (R5)."""
    import re as _re
    from pathlib import Path as _P

    from tests.srccheck import markup_only

    static = _P(__file__).resolve().parents[1] / "sourcing_guard" / "static"
    for path in _FOOT_PAGES:
        name = {"/": "landing.html"}.get(path, path.lstrip("/") + ".html")
        name = "index.html" if path == "/scan" else name
        src = markup_only((static / name).read_text(encoding="utf-8"))
        assert "data-foot-asof" in src, f"{name} 에 바닥글 자리가 없습니다"
        m = _re.search(r'<p class="row foot-asof"[^>]*>(.*?)</p>', src, _re.S)
        assert m and not m.group(1).strip(), (
            f"{name} 바닥글에 값이 박혀 있습니다: {m.group(1)[:40] if m else ''}")


def test_the_footer_line_disappears_when_we_have_no_date():
    """⚠ 값이 없으면 **요소째 지운다.** 빈 줄을 남기거나 오늘 날짜로 메우면
    화면이 없는 사실을 말한다 (R3·R5).
    """
    from sourcing_guard import main as m

    class _NoDate:
        as_of = None

    real = m._recalls
    try:
        m._recalls = _NoDate()
        out = m._fill_footer_asof('<x><p class="row foot-asof" data-foot-asof></p></x>')
    finally:
        m._recalls = real
    assert "foot-asof" not in out, f"값이 없는데 줄이 남았습니다: {out}"
