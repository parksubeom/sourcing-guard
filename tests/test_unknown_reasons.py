"""회색불 사유 — **쪼갠 것이 옛 문장과 같은가.**

왜 있나
-------
`/unknown` 화면이 제목을 따로 써야 해서 `"제목 — 본문"` 한 문자열을 둘로
쪼갰다. 구조만 바꾸고 글자는 그대로여야 하는데, 그 보장이 **검사 말고는
없다** - 리팩터가 띄어쓰기 하나를 바꿔도 아무도 모른다.

⚠⚠ 그래서 옛 다섯 문자열을 **여기 통째로 적어 둔다.** 이것은 "현재 출력을
  붙여넣은 기대값"(§6 이 금지한 것)이 아니다 - 쪼개기 **전에** 화면에 나가고
  있던 값이고, 이 검사가 지키는 것은 "리팩터가 문구를 안 바꿨다" 는 사실
  하나다. 문구를 정당하게 바꾸려면 이 파일을 함께 고치게 된다.
"""

from __future__ import annotations

import pytest

from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts, Signal
from sourcing_guard.scorer import (
    _UNKNOWN_HEADLINE,
    _UNKNOWN_HEADLINE_FIRST,
    _UNKNOWN_NO_INPUT,
    unknown_reasons,
    unlocks_ko,
)

#: 쪼개기 **전**의 헤드라인 다섯. 한 글자도 안 바뀌어야 한다.
BEFORE = {
    "out_of_scope":
        "본 서비스 범위 밖 — 식품·화장품 등은 식약처 등 다른 부처 소관입니다. "
        "해당 기준으로 확인하세요.",
    "age_out_of_range":
        "대상 아님 — 표기된 사용연령 기준으로는 어린이제품 안전기준 대상이 "
        "아닙니다. 실사용 연령이 13세 이하이면 대상이 될 수 있으니 표기 근거를 확인하세요.",
    "coverage_gap":
        "일부만 확인 — 인증·리콜은 대조했으나, 이 품목의 유해물질 기준은 아직 "
        "수록되지 않았습니다. 확인된 범위는 아래를 보세요.",
    "lookup_failed":
        "확인 미완료 — 정부 조회 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "no_input":
        "입력 확인 — 상품 정보를 읽지 못했습니다. 상품 상세페이지의 '상품정보' 표를 "
        "붙여넣으면 확인해 드립니다.",
}


def test_splitting_the_headline_did_not_change_one_character():
    """제목 + " — " + 본문 이 옛 문자열과 같은가."""
    got = {r.key: r.headline for r in (*_UNKNOWN_HEADLINE_FIRST, *_UNKNOWN_HEADLINE)}
    got["no_input"] = _UNKNOWN_NO_INPUT
    for key, before in BEFORE.items():
        assert key in got, f"{key} 사유가 사라졌다"
        assert got[key] == before, (
            f"{key} 문구가 바뀌었다\n  전: {before}\n  후: {got[key]}")


def test_the_headline_still_reaches_the_result():
    """⚠ 상수가 맞아도 **`score()` 가 그것을 쓰는지**는 다른 질문이다.

    쪼개면서 고른 자리를 잘못 고치면 상수는 그대로인데 화면만 바뀐다.
    """
    from datetime import date

    from sourcing_guard.scorer import score

    def f(kind):
        return __import__("sourcing_guard.models", fromlist=["Finding"]).Finding(
            kind=kind, signal=Signal.UNKNOWN, statement_ko="테스트",
            source_label="국가기술표준원", source_url="https://www.safetykorea.kr/",
            checked_at=date(2026, 1, 1))

    facts = ProductFacts(product_name="무언가", category=ItemCategory.UNCLASSIFIED)
    for key, kind in (("out_of_scope", FindingKind.OUT_OF_SCOPE),
                      ("age_out_of_range", FindingKind.AGE_OUT_OF_CHILD_RANGE),
                      ("lookup_failed", FindingKind.LOOKUP_FAILED)):
        got = score(facts, [f(kind)]).headline
        assert got == BEFORE[key], f"{key}: 화면에 가는 문장이 다르다\n  {got}"


def test_every_reason_has_a_title_and_a_body():
    for r in unknown_reasons():
        assert r.key and r.title and r.body, f"{r.key}: 빈 칸이 있다"
        assert " — " not in r.title, f"{r.key}: 제목에 구분자가 남았다"


def test_the_reasons_say_which_ones_open_something():
    """⚠⚠ **이 화면의 요지가 이 갈래다.** 답하면 열리는 것과, 우리가 이미
    판단한 것.

    셋(소관 밖 · 연령 대상 아님 · 번호 부재 정상)은 **못 한 것이 아니라 한
    것**이라 열릴 것이 없다. 나머지는 셀러가 답하면 축이 열린다.
    """
    by_key = {r.key: r for r in unknown_reasons()}
    for key in ("out_of_scope", "age_out_of_range", "absence_expected"):
        assert not by_key[key].unlocks, f"{key}: 판단한 것인데 열린다고 말한다"
    for key in ("missing:legal_item_name", "missing:materials",
                "missing:target_age", "lookup_failed", "no_input"):
        assert by_key[key].unlocks, f"{key}: 답해도 열리는 것이 없다고 말한다"
        assert unlocks_ko(by_key[key].unlocks), f"{key}: 축 이름이 한국어로 안 나온다"


def test_unknown_axis_names_are_dropped_not_shown_raw():
    """모르는 축 이름은 버린다 - 화면에 영문 키가 새는 것보다 낫다."""
    assert unlocks_ko(("hazard_rule", "made_up")) == ("유해물질 기준",)
    assert unlocks_ko(()) == ()


def test_the_absence_card_never_says_it_is_exempt():
    """⚠⚠ "인증이 필요 없다" 는 **틀리다.** 제조·수입자에게 스스로 시험해
    확인할 의무가 있다 (R3-b 주석과 같은 말).

    이 칸이 면제로 읽히면 이 페이지가 셀러를 잘못 안심시킨다 - 화면 전체에서
    제일 비싼 오류다.
    """
    body = {r.key: r for r in unknown_reasons()}["absence_expected"].body
    assert "시험성적서" in body, "무엇을 받아야 하는지 안 말한다"
    assert "의무가 있습니다" in body, "의무가 남는다는 말이 빠졌다"
    for banned in ("필요 없습니다", "면제", "안 받아도", "해당 없음"):
        assert banned not in body, f"면제로 읽히는 말이 있다: {banned}"


# ── 화면 ────────────────────────────────────────────────────────────
_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "sourcing_guard" / "static"


def _page_src(name: str) -> str:
    from tests.srccheck import markup_only

    return markup_only((_STATIC / name).read_text(encoding="utf-8"))


def test_the_page_writes_no_reason_text_of_its_own():
    """⚠⚠ 사유 문구는 **서버 것뿐**이다.

    같은 문장을 `scorer` 가 헤드라인으로도 쓰므로, 화면이 적으면 두 벌이
    되고 한쪽만 고쳐질 때 화면이 낡은 말을 한다 (§6 · R5).
    """
    html, js = _page_src("unknown.html"), _page_src("unknown.js")
    for r in unknown_reasons():
        for text in (r.title, r.body, r.verdict_ko):
            assert text not in html, f"unknown.html 이 서버 문장을 적어 뒀다: {text[:30]}"
            assert text not in js, f"unknown.js 가 서버 문장을 적어 뒀다: {text[:30]}"

    # 판정 낱말도 화면이 고르지 않는다.
    assert "r.verdict" in js, "화면이 판정 문구를 서버에서 안 받는다"
    for banned in ("열립니다", "판단한 것", "채워야"):
        assert banned not in js, f"화면이 판정 문구를 짓고 있다: {banned}"


def test_the_page_has_only_frame_text():
    """⚠⚠ **완전 검사** - 틀 말고 화면이 지어낸 줄이 하나도 없는가.

    `check_ask_text` 의 ⑤ 와 같은 모양이다. 틀에 속하지 않는 줄이 있으면
    그것은 우리가 검수하지 않은 말이다.
    """
    import re as _re

    body = _page_src("unknown.html")
    body = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=_re.S)
    text = _re.sub(r"<[^>]+>", "\n", body)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    frame = {
        "안심 소싱 돋보기", "본문으로 건너가기",
        "소개", "상품 검사", "대량 검사", "감시 목록", "카테고리 가이드",
        '왜 "모름" 이 나왔나',
        '왜 "모름" 이 나왔나 — 안심 소싱 돋보기',      # <title>
        "모름 안내",                                  # 히어로 칩
        "회색불은 저희가", "확인하지 못한 것", "이거나,",
        "입니다. 어느 쪽인지 사유마다",
        "확인해 보니", "대상이 아니었던 것",
        "적어 두었습니다.",
        "모름은 저희가 게을러서가 아니라 상세페이지에 그 정보가 없기 때문입니다.",
        "그래서 저희는 모름을", '"무엇을 누구에게 물으면 되는지"', "로",
        "바꿔 드립니다.",
        "검사 결과 화면 아래", "「공급처에 보낼 문안 복사」", "를",
        "누르면, 확인이 필요한 항목만 모아 공급처에 그대로 보낼 수 있습니다.",
        "상품 검사하러 가기",
        "본 결과는 공개된 정부 데이터에 기반한 참고 정보이며, 법적 판단이나 안전 인증을 대체하지 않습니다.",
    }
    unknown = [ln for ln in lines if ln not in frame]
    assert not unknown, "어디서 왔는지 모르는 줄:\n  " + "\n  ".join(unknown)


def test_the_new_sentences_pass_the_wording_rule():
    """③ 설명과 맺음 둘은 **새로 쓴 문장**이다. §9 가 여기도 걸린다."""
    body = _page_src("unknown.html") + \
        {r.key: r for r in unknown_reasons()}["absence_expected"].body
    for banned in ("안전합니다", "합법입니다", "판매 가능합니다", "문제없습니다",
                   "검출", "안전성을 확인", "이상 없음"):
        assert banned not in body, f"단정 표현이 있다: {banned}"


def test_the_result_card_links_here_only_when_it_is_unknown():
    """⚠⚠ 반대 방향이 요지다. GREEN/AMBER/RED 에 붙으면 판정이 난 결과에도
    "모름" 화면이 따라붙어 뜻이 흐려진다.
    """
    index = _page_src("index.html")
    i = index.index('href="/unknown"')
    around = index[max(0, i - 200):i]
    assert 'sig === "UNKNOWN"' in around, "회색불 조건 없이 링크를 건다"
    assert index.count('href="/unknown"') == 1, "검사 화면에 링크가 둘 이상이다"


def test_the_page_is_reachable_from_where_the_question_arises():
    """전역 내비에는 안 넣는다 (`/samples` 와 같은 이유 · 미완 §1-l).
    대신 질문이 실제로 생기는 세 곳에서 건다.
    """
    for name in ("index.html", "landing.html", "misses.html"):
        assert 'href="/unknown"' in _page_src(name), f"{name} 에서 못 간다"

    # 내비에는 없어야 한다 - 320px 내비 넘침이 되돌아온다.
    for name in ("index.html", "landing.html", "misses.html", "unknown.html"):
        src = _page_src(name)
        nav = src[src.index('<nav class="pages"'):]
        nav = nav[: nav.index("</nav>")]
        assert "/unknown" not in nav, f"{name}: 전역 내비에 들어갔다"


def test_the_endpoint_serves_what_the_owner_says():
    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    with TestClient(app) as c:
        got = c.get("/api/v1/unknown-reasons").json()["reasons"]
        assert c.get("/unknown").status_code == 200
    want = unknown_reasons()
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g["key"] == w.key and g["title"] == w.title and g["body"] == w.body
        assert g["verdict"] == w.verdict_ko
        assert g["unlocks"] == list(unlocks_ko(w.unlocks))
