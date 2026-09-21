"""도매꾹 상품 리스트 (P4) — **자료 칸과 화면 둘 다** 잠근다.

왜 자료 칸까지 보나
-------------------
2026-09-20 에 「우리가 틀린 것」 화면에서 난 사고 그대로다. 그 화면에는 검사가
넷이나 걸려 있었는데 전부 `misses.html`·`misses.js` 를 읽었고, 셀러가 실제로
읽는 문장은 `data/misses.json` 의 `why` 였다. **틀은 깨끗했고 값은 아니었다.**

그래서 여기서는 `sourcing_guard/data/showcase.json` 을 직접 연다.

⚠⚠ **공급사가 쓴 글과 우리가 쓴 글을 가른다.**

    공급사 글   `title` · `facts.*` · `page_text`   ← 재지 않는다
    우리 글     `result.*` 의 문장 · `result_note`  ← 잰다

  상품 제목에 우리 용어가 있을 리 없고, 있더라도 그것은 우리가 쓴 것이 아니다.
  「우리가 틀린 것」 검사도 같은 이유로 `name`·`said` 를 뺐다.

⚠ **본 수를 단정한다.** 0개를 보고 통과하는 검사는 초록불을 주면서 우리를
  안심시킨다 (CLAUDE.md §6). 그리고 **반대 방향**도 잰다 - 심어 둔 나쁜
  문자열을 못 잡으면 위의 통과는 "깨끗하다" 가 아니라 "안 본다" 다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.srccheck import emoji_chars, markup_only

_ROOT = Path(__file__).resolve().parents[1]
_DATA = _ROOT / "sourcing_guard" / "data" / "showcase.json"
_THUMBS = _ROOT / "sourcing_guard" / "static" / "showcase"
_INDEX = _ROOT / "sourcing_guard" / "static" / "index.html"

#: 셀러에게 아무 뜻이 없는 우리 집안 용어. `misses` 검사와 **같은 규칙**이다.
_HOUSE = re.compile(r"\bR\d+(?:-[a-z])?\b|CLAUDE\.md|§\d|미완 목록")

#: §9 가 금지하는 단정 표현.
_VERDICT = ("안전합니다", "합법입니다", "판매 가능합니다", "문제없습니다")


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def payload() -> dict:
    from sourcing_guard.showcase import payload as showcase_payload

    return showcase_payload()


# ── 자료 칸 ──────────────────────────────────────────────────────────
def test_the_copy_has_a_recorded_scan_behind_it(raw):
    """모든 카드가 **실제 스캔 응답**을 들고 있다. 손으로 적은 카드는 없다."""
    items = raw["items"]
    assert items, "사본이 비었다 - scripts/build_showcase.py 를 돌리세요"
    for it in items:
        assert it.get("result", {}).get("findings"), f'{it["no"]} 에 결과가 없다'
        assert it["result"].get("signal"), f'{it["no"]} 에 신호가 없다'


def test_no_red_product_is_listed(raw):
    """총괄 지시: 리스트에 RED 를 두지 않는다.

    ⚠ **뺀 것이 감춘 것이 되지 않게** 스크립트가 무엇을 뺐는지 기록한다
      (`tests/fixtures/showcase_*/RED_제외.md`). 여기서는 목록 쪽만 본다.
    """
    reds = [i["no"] for i in raw["items"] if i["result"]["signal"] == "RED"]
    assert not reds, f"RED 상품이 목록에 있다: {reds}"


def test_the_screen_never_gets_a_hotlink(raw):
    """도매꾹 약관: 이미지를 받아서 우리가 서빙한다.

    ⚠ 원본 썸네일 URL 을 사본에 **남기지 않는다.** 남기면 다음 사람이 그것을
      `<img src>` 에 넣는다 - 경로를 없애는 것이 당부보다 강하다.
    """
    blob = _DATA.read_text(encoding="utf-8")
    assert "cdn1.domeggook.com" not in blob, "원본 썸네일 호스트가 사본에 남았다"
    for it in raw["items"]:
        assert "thumb" not in it, f'{it["no"]} 에 원본 썸네일 URL 이 남았다'


def test_every_thumbnail_exists_and_is_small(raw):
    """썸네일이 실재하고 **200px 이하**다. 원본을 커밋하면 공개 리포가 무거워진다."""
    from PIL import Image

    from scripts.build_showcase import THUMB_MAX_PX

    seen = 0
    for it in raw["items"]:
        name = it.get("thumb_file")
        assert name, f'{it["no"]} 에 썸네일이 없다'
        path = _THUMBS / name
        assert path.is_file(), f"{path} 가 없다"
        with Image.open(path) as img:
            assert max(img.size) <= THUMB_MAX_PX, f"{name} 이 {img.size} 다"
        seen += 1
    assert seen == len(raw["items"])
    # ⚠ **반대 방향.** "쓰는 파일이 있다" 만 재면 주인 없는 파일이 리포에
    #   남는다 - 실측에서 두 장이 남았다 (collect 를 다시 돌리면 고른 상품이
    #   달라지고, scan 이 RED 를 빼면 그 상품 썸네일도 주인을 잃는다).
    on_disk = {f.name for f in _THUMBS.glob("*.webp")}
    used = {i["thumb_file"] for i in raw["items"]}
    assert on_disk == used, f"주인 없는 썸네일: {sorted(on_disk - used)}"


def test_no_seller_identity_survives(raw):
    """판매자 아이디·닉네임·사업자 정보는 한 글자도 안 나간다 (남길 목록)."""
    from sourcing_guard.showcase_pii import KEEP_FIELDS, OWN_KEYS

    allowed = (set(KEEP_FIELDS) | set(OWN_KEYS)) - {"thumb"}
    for it in raw["items"]:
        extra = set(it) - allowed
        assert not extra, f'{it["no"]} 에 목록 밖 키가 있다: {extra}'


def test_our_own_sentences_carry_no_house_vocabulary(raw):
    """**자료에서 온 문구**를 잰다. 틀이 아니라 값이다 (머리 주석).

    ⚠ 공급사가 쓴 글(`title`·`facts`·`page_text`)은 빼고 잰다 - 우리가 쓴
      문장이 아니다.
    """
    from sourcing_guard.showcase import RESULT_NOTE

    ours: list[tuple[str, str]] = [("result_note", RESULT_NOTE)]
    for it in raw["items"]:
        r = it["result"]
        for key in ("headline", "coverage_note", "input_note", "extraction_note",
                    "disclaimer"):
            if r.get(key):
                ours.append((f'{it["no"]}.{key}', r[key]))
        for f in r["findings"]:
            for key in ("statement_ko", "source_label"):
                if f.get(key):
                    ours.append((f'{it["no"]}.{f["kind"]}.{key}', f[key]))

    # ⚠ **본 수를 단정한다.** 0개를 보고 통과하면 그건 검사가 아니다.
    assert len(ours) > 100, f"잰 문장이 {len(ours)}개뿐이다 - 자료를 못 읽었나"

    for where, text in ours:
        bad = emoji_chars(text)
        assert not bad, f"{where} 에 기호: {bad}"
        hit = _HOUSE.search(text)
        assert not hit, f'{where} 에 우리 용어가 남았다: "{hit.group(0)}"'
        for word in _VERDICT:
            assert word not in text, f"{where} 에 단정 표현 '{word}' 가 있다"

    # ⚠ 반대 방향. 못 잡으면 위의 통과는 "깨끗하다" 가 아니라 "안 본다" 다.
    assert _HOUSE.search("상품명만으로는 고르지 못한다 (R3)"), "규칙 번호를 못 잡는다"
    assert emoji_chars("⚠ 우리가 정한 선이다"), "경고 기호를 못 잡는다"
    assert not _HOUSE.search("부속서 15 · 별표 7"), "고시 표기를 잡으면 안 된다"


def test_the_fixed_disclaimer_rides_along(raw):
    """§9 고정 표기가 **모든** 기록된 결과에 들어 있다."""
    for it in raw["items"]:
        assert "법적 판단이나 안전 인증을 대체하지 않습니다" in it["result"]["disclaimer"]


# ── 서버가 내는 것 ───────────────────────────────────────────────────
def test_the_card_payload_carries_no_signal(payload):
    """⚠⚠ **목록에 신호를 칠할 값을 아예 주지 않는다.**

    문구로 당부하는 것보다 값을 안 주는 쪽이 강하다. 카드 한 장의 키를
    **집합으로** 단정한다 - "signal 이 없다" 만 재면 다음에 `score` 나
    `axes` 가 붙었을 때 안 걸린다.
    """
    assert payload["items"], "카드가 없다"
    # `did`·`cert_head` 는 **우리가 한 일**이다 (2026-09-21). 판정이 아니라
    # 행위라 이 금지에 안 걸린다 - 초록은 상품이 아니라 우리 행위에 붙는다.
    want = {"no", "title", "thumb", "url", "price", "unit_qty", "did", "cert_head"}
    for card in payload["items"]:
        assert set(card) <= want, (
            f'{card.get("no")} 에 모르는 키가 있다: {set(card) - want}')

    # ⚠ 키 집합만 재면 `did` 에 "정상" 을 담아도 통과한다 - **값도 본다.**
    for card in payload["items"]:
        for banned in ("signal", "score", "axes", "verdict", "findings", "grade"):
            assert banned not in card, f'{card["no"]} 에 {banned} 가 있다'
        if card.get("did"):
            for word in ("정상", "주의", "위험", "안전", "적합", "이상 없음"):
                assert word not in card["did"], (
                    f'{card["no"]} 의 did 가 판정을 말한다: {card["did"]!r}')


def test_numbers_are_numbers(payload):
    """가격·최소수량이 **문자열로 새지 않는다** (CLAUDE.md §6).

    `"5" > "10"` 이 참이라, 문자열로 흘리면 비교·합산이 조용히 틀린다.
    """
    seen = 0
    for card in payload["items"]:
        for key in ("price", "unit_qty"):
            if card[key] is not None:
                assert isinstance(card[key], int), f'{card["no"]}.{key} 가 {type(card[key])}'
                seen += 1
    assert seen >= len(payload["items"]), "잰 숫자가 카드 수보다 적다"


def test_the_base_date_comes_from_the_file(payload, raw):
    """기준일을 화면이 짓지 않는다. 사본에 적힌 수집일 그대로다 (R5)."""
    assert payload["as_of"] == raw["as_of"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["as_of"])


def test_a_missing_file_yields_an_empty_list(monkeypatch, tmp_path):
    """자료가 없으면 **빈 목록**이다. 빈 껍데기를 그리지 않는다."""
    import sourcing_guard.showcase as mod

    mod._raw.cache_clear()
    monkeypatch.setattr(mod, "SHOWCASE_PATH", tmp_path / "없음.json")
    try:
        assert mod.payload()["items"] == []
        assert mod.result_of("1") is None
    finally:
        mod._raw.cache_clear()


def test_the_endpoints_answer(raw):
    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    with TestClient(app) as client:
        listing = client.get("/api/v1/showcase")
        assert listing.status_code == 200
        no = listing.json()["items"][0]["no"]
        one = client.get(f"/api/v1/showcase/{no}")
        assert one.status_code == 200
        assert one.json()["result"]["signal"]
        # 없는 상품은 404 다. 빈 결과를 200 으로 주면 화면이 빈 카드를 그린다.
        assert client.get("/api/v1/showcase/999999999999").status_code == 404


def test_the_title_is_kept_verbatim_on_purpose(raw):
    """⚠⚠ **체험 표본과 일부러 다르다** (2026-09-20 총괄 판정).

    저쪽은 제목 앞머리의 `[상호]` 를 뗀다. 여기서는 떼지 않는다 - 카드가
    **도매꾹 원문으로 링크**하므로, 제목만 가리는 것은 가리는 시늉이고 고치면
    "실제 도매꾹 판매중 상품" 이라는 주장이 거짓이 된다.

    검사가 하는 일은 **그 결정이 일부러라는 것을 잠그는 것**이다. 다음 사람이
    `record_samples` 를 보고 "여기도 떼야 하는 것 아닌가" 하고 조용히 고치면
    링크와 제목이 갈린다.
    """
    src = (_ROOT / "sourcing_guard" / "showcase_pii.py").read_text(encoding="utf-8")
    assert "상품 제목은 손대지 않는다" in src, "결정이 어디에도 안 적혀 있다"

    # ⚠ 결정이 실제로 지켜지는지도 **값으로** 확인한다. 주석만 재면 코드가
    #   딴짓을 해도 통과한다 (틀만 보던 「우리가 틀린 것」 사고와 같은 모양).
    bracketed = [i["title"] for i in raw["items"] if re.search(r"[\[(（【]", i["title"])]
    assert bracketed, (
        "괄호가 든 제목이 한 장도 없다 - 누가 떼고 있거나 표본이 바뀌었다. "
        "떼고 있는 것이면 이 결정이 뒤집힌 것이다"
    )


# ── 화면 ─────────────────────────────────────────────────────────────
def test_the_list_lives_inside_the_scan_screen():
    """자리는 `/scan` **입력란 위**다. 별도 화면이면 안 들어가는 사람이 생긴다."""
    src = _INDEX.read_text(encoding="utf-8")
    body = markup_only(src)
    assert 'id="dg-sec"' in body
    assert body.index('id="dg-sec"') < body.index('id="input-h"'), (
        "도매꾹 리스트가 입력란 아래에 있다"
    )


def test_the_screen_does_not_paint_a_signal_on_the_cards():
    """카드 마크업에 신호 클래스·칩을 넣지 않는다.

    ⚠ 서버가 값을 안 주지만 화면이 `result` 를 따로 받아 칠할 수도 있다.
      **두 쪽 다 잠근다** - 한쪽만 재면 반대쪽이 뚫린다 (§6).
    """
    body = markup_only(_INDEX.read_text(encoding="utf-8"))
    card = body[body.index('class="dg-card"'):]
    card = card[: card.index("</button>")]
    for banned in ("chip", "signal", "GREEN", "AMBER", "RED", "UNKNOWN"):
        assert banned not in card, f"카드에 '{banned}' 가 있다"


def test_the_screen_offers_a_way_past_the_list():
    """⚠ **직접 치러 온 셀러를 붙잡지 않는다** (총괄 판정 §3-①).

    이 구역이 입력란 위에 있는 것은 "먼저 보여준다" 이지 "직접 치는 길을
    멀게 한다" 가 아니다. 320px 에서 입력란이 y=2,878 이라 건너뛰는 길이
    필요하다.
    """
    body = markup_only(_INDEX.read_text(encoding="utf-8"))
    dg = body[body.index('id="dg-sec"'):body.index('id="input-h"')]
    assert 'href="#pt"' in dg, "리스트를 건너뛰어 입력란으로 가는 길이 없다"
    # 대상이 실재해야 한다 - 없는 자리로 보내면 아무 일도 안 일어난다.
    assert 'id="pt"' in body


def test_the_screen_shows_the_base_date_and_the_source_link():
    """기준일 · 도매꾹 원문 · 고정 문장이 화면에 실제로 나간다."""
    body = markup_only(_INDEX.read_text(encoding="utf-8"))
    assert 'id="dg-lede"' in body and "기준 도매꾹에서 판매중인 상품입니다" in body
    assert "도매꾹 원문 보기" in body
    assert "data.result_note" in body, "고정 문장을 서버에서 안 받는다"


def test_the_screen_does_not_hardcode_the_base_date():
    """날짜를 화면에 박으면 사본을 다시 만들 때 화면만 옛날을 말한다 (R5)."""
    body = markup_only(_INDEX.read_text(encoding="utf-8"))
    dg = body[body.index('id="dg-sec"'):]
    assert not re.search(r"20\d{2}-\d{2}-\d{2}", dg), "화면에 날짜가 박혀 있다"


def test_the_list_cannot_push_the_page_sideways():
    """목록이 **페이지를 옆으로 밀지 않는다.**

    막는 방법이 2026-09-21 에 바뀌었다. 전에는 격자였고 `minmax(N,1fr)` 의
    하한이 곧 최소 폭이라 `min(N,100%)` 로 감싸야 했다(랜딩·`/unknown` 에서
    같은 자리가 두 번 났다). 지금은 **가로 스크롤**이라 목록이 스스로 넘치고
    페이지는 안 밀린다 - `overflow-x` 가 그 자리를 대신한다.

    주의(가장 중요): **주석을 빼고 본다.** 처음에 원문을 그대로 훑었더니
      minmax 를 **설명한 주석**이 이 검사에 걸렸다 - 저장소에서 열두 번 넘게
      난 그 자리다. 오너는 `tests/srccheck.markup_only` 다 (§6).
    """
    css = markup_only(
        (_ROOT / "sourcing_guard" / "static" / "app.css").read_text(encoding="utf-8"))
    rules = dict(re.findall(r"([^{}]*\.dg-list[^{}]*)\{([^}]*)\}", css))
    base = next((d for s, d in rules.items() if s.strip() == ".dg-list"), None)
    assert base, ".dg-list 규칙이 없다"
    assert re.search(r"overflow-x\s*:\s*auto", base), (
        "목록이 스크롤 컨테이너가 아니다 - 넘치면 페이지가 옆으로 밀린다")
    assert re.search(r"scroll-snap-type\s*:\s*x", base), "칸 맞춤이 없다"

    item = next((d for s, d in rules.items() if "> li" in s), None)
    assert item, ".dg-list > li 규칙이 없다"
    assert re.search(r"scroll-snap-align", item), "카드가 칸에 안 맞춰진다"
    assert re.search(r"flex\s*:\s*0 0 auto", item), (
        "카드가 줄어들 수 있다 - 그러면 스크롤이 아니라 찌그러진다")


def test_the_auto_scroll_can_be_pushed_by_hand():
    """주의(가장 중요): **CSS `@keyframes` 로 굴리면 손으로 못 민다.**
    그것이 이 방식을 고른 이유이므로, 애니메이션이 아니라 **스크롤**인지 잠근다.

    주의(중요): 사용자가 밀면 자동이 멈춰야 한다 - 안 그러면 손과 타이머가 싸운다.
    """
    src = markup_only(
        (_ROOT / "sourcing_guard" / "static" / "index.html").read_text(encoding="utf-8"))
    assert "scrollBy" in src and "behavior" in src, "타이머가 스크롤로 밀지 않는다"
    assert "@keyframes" not in src, "keyframes 로 굴리면 손으로 못 민다"
    for hook in ("mouseenter", "focusin", "touchstart", "prefers-reduced-motion",
                 "max-width: 768px"):
        assert hook in src, f"{hook} 처리가 없다"
    assert "DG_STEP_MS = 5000" in src, "간격이 5초가 아니다"
