"""[G-2] 랜딩 ⓪ 절과 제출문은 **같은 원자료 하나**에서 나온다.

숫자의 출처가 둘이 되면 갈린다. 이 프로젝트에서 이미 여러 번 겪었다 -
제출문에 `71.1%` 가 남아 있었고(2026-09-11 정정), 설계 문서의 국외 리콜 수가
`/healthz` 와 달랐고, 4-o 의 자리 수가 코드와 어긋났다.

그래서 정부 보도자료 숫자는 `sourcing_guard/static/data/안전성조사_보도자료.json`
하나에만 둔다. 랜딩은 그것을 fetch 해서 그리고, 제출문은 그 값만 인용한다.

⚠ 이 파일이 잠그는 것 셋
    (a) 원자료 줄마다 기관 도메인 URL 과 게시일이 있다
    (b) 랜딩 ⓪ 절 마크업에 숫자가 없다 · 제출문의 숫자는 원자료에 있는 값이다
    (c) §9 단정 금지가 ⓪ 문구에도 걸린다
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DATA = _ROOT / "sourcing_guard" / "static" / "data" / "안전성조사_보도자료.json"
_LANDING = _ROOT / "sourcing_guard" / "static" / "landing.html"
_DRAFT = _ROOT / "docs" / "제출문_초안.md"

#: 기관 원문만 싣는다. 기사 URL 은 넣지 않는다 - 기사는 숫자를 요약하며 바꾼다.
#: 실제로 이 작업에서 한 기사가 조사 수를 396, 다른 요약이 404 로 적었다.
_ALLOWED_HOSTS = {"kats.go.kr", "www.kats.go.kr",
                  "motir.go.kr", "www.motir.go.kr",
                  "korea.kr", "www.korea.kr"}


def _data() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def _landing() -> str:
    return _LANDING.read_text(encoding="utf-8")


def _body() -> str:
    """랜딩 **본문 마크업**. 스크립트·주석·`<head>` 는 뺀다.

    ⚠ v2 에서 절 번호(⓪①②…)를 지웠다 (design/README §10-3). 그래서 절 하나를
      잘라낼 앵커가 없다 - 대신 **본문 전체**를 본다. 검사가 넓어진 것이고,
      v2 는 숫자를 하나도 마크업에 두지 않으므로 그래야 맞다.
    """
    html = _landing()
    m = re.search(r"<main\b[^>]*>(.*?)</main>", html, re.S)
    assert m, "랜딩에 <main> 이 없습니다"
    body = re.sub(r"<script\b.*?</script>", "", m.group(1), flags=re.S)
    return re.sub(r"<!--.*?-->", "", body, flags=re.S)


# ── (a) 원자료 ──────────────────────────────────────────────────────
def test_every_release_has_an_agency_url_and_a_date():
    surveys = _data()["조사"]
    assert surveys, "원자료가 비었습니다"
    for s in surveys:
        host = urlparse(s["url"]).netloc
        assert host in _ALLOWED_HOSTS, (
            f"{s.get('id')}: 기관 원문이 아닌 호스트입니다 - {host}. "
            "기사 URL 은 넣지 않습니다 (기사는 숫자를 요약하며 바꿉니다)."
        )
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["게시일"]), (
            f"{s.get('id')}: 게시일이 YYYY-MM-DD 가 아닙니다 - {s['게시일']!r}"
        )
        assert s.get("id"), "조사마다 id 가 있어야 합니다 (제목이 거의 같은 건이 둘 있습니다)"


def test_the_totals_add_up_to_what_the_release_says():
    """분야별 합이 총계와 맞는지 - 원문을 잘못 옮겼으면 여기서 드러난다."""
    for s in _data()["조사"]:
        fields = s["분야별"]
        assert sum(x["조사_수"] for x in fields) == s["조사_수"], f"{s['id']}: 조사 수 합이 안 맞습니다"
        assert sum(x["부적합_수"] for x in fields) == s["부적합_수"], f"{s['id']}: 부적합 수 합이 안 맞습니다"


def test_item_rates_match_their_own_numerator_and_denominator():
    """품목별 부적합률이 분자/분모와 맞는지. 반올림 1%p 까지 허용한다."""
    for s in _data()["조사"]:
        for it in s["품목별"]:
            if "조사_수" not in it or "부적합률" not in it:
                continue          # 분모를 안 적은 보도자료가 있다 (품목별_주석)
            calc = round(it["부적합_수"] / it["조사_수"] * 100)
            assert abs(calc - it["부적합률"]) <= 1, (
                f"{s['id']} {it['품목']}: 원문 {it['부적합률']}% · 계산 {calc}%"
            )


# ── (b) 숫자의 출처는 하나다 ─────────────────────────────────────────
def test_the_landing_body_hardcodes_no_numbers_at_all():
    """랜딩 **본문 전체**에 숫자가 있으면 실패한다. 넷 다 그 자리에서 그린다.

    ⚠ v2 에서 이 검사가 넓어졌다. 전에는 ⓪ 절만 봤고 나머지 절은 70.4%·135건을
      마크업에 적어 두고 **다른 검사가 기준선과 대조**했다 - 같은 숫자를 두 곳에
      적는 것이라 §6 이 막는 모양 그대로였다. 이제 마크업에 숫자가 0 이다.
    """
    body = re.sub(r"<[^>]+>", " ", _body())        # 태그(속성 포함) 제거
    found = re.findall(r"\d+", body)
    assert not found, (
        f"랜딩 본문에 숫자가 박혀 있습니다: {found}. "
        "리콜 수·공표일은 /healthz, 보도자료 수는 안전성조사_보도자료.json, "
        "70.4%·135건·0건은 /healthz.baseline 에서 그립니다."
    )


def test_the_landing_draws_the_four_numbers_from_their_sources():
    """마크업이 비어 있기만 하면 안 된다 - 실제로 그 출처를 읽어야 한다.

    넷 = 리콜 수 · 공표일(healthz) · 5개 중 1개(보도자료 원자료) ·
    70.4%·135건(healthz.baseline) · 0건(healthz.baseline).
    """
    html = _landing()
    assert "/static/data/안전성조사_보도자료.json" in html, "보도자료 원자료를 읽지 않는다"
    assert "/healthz" in html, "healthz 를 읽지 않는다"
    for key in ("band-k", "band-big", "band-b", "band-src"):
        assert f'data-p="{key}"' in html, f"{key} 자리가 없습니다"
    for key in ("recalls", "as_of", "ok_rate", "denominator", "off_target"):
        assert f'data-h="{key}"' in html, f"{key} 자리가 없습니다"
    # 후킹 숫자는 **원자료에서 만든다** - "5개 중 1개" 를 적어 두지 않는다.
    assert "조사_수 / a.부적합_수" in html.replace("a.조사_수", "조사_수"), (
        "'N개 중 1개' 를 원자료에서 계산하지 않는다"
    )


def _numbers_in(text: str) -> set[int]:
    return {int(t) for t in re.findall(r"\d+", text)}


def _allowed_numbers() -> set[int]:
    """원자료가 담은 모든 수 + 게시일의 연·월·일."""
    ok: set[int] = set()
    for s in _data()["조사"]:
        for key in ("조사_수", "부적합_수", "부적합률", "국내_유통_평균_부적합률"):
            ok.add(s[key])
        for it in s["품목별"]:
            ok.update(v for k, v in it.items() if isinstance(v, int))
        for f in s["분야별"]:
            ok.update(v for k, v in f.items() if isinstance(v, int))
        y, m, d = s["게시일"].split("-")
        ok.update({int(y), int(m), int(d)})
        ok.update(_numbers_in(s["조사_대상"]))
    return ok


#: 보도자료와 무관한, 이 절이 원래 쓰던 수. 늘리려면 근거를 함께 적을 것.
_NON_RELEASE_NUMBERS = {
    3, 5, 8, 100,      # "상품 하나당 3~5분", "하루 100개면 5~8시간"
    2022, 220,         # 어린이제품 공통안전기준 고시 번호
}


def test_the_draft_quotes_only_numbers_that_exist_in_the_raw_data():
    """제출문 '해결하려는 문제' 의 숫자는 원자료에 있는 값이어야 한다.

    ④ 가 기획서 숫자를 `audit_tally.BASELINE` 에 묶는 것과 같은 방식이다.
    보도자료 숫자를 손으로 옮겨 적으면 원자료가 바뀔 때 여기만 낡는다.
    """
    doc = _DRAFT.read_text(encoding="utf-8")
    block = re.search(r"^## \d+\. 해결하려는 문제\n(.*?)(?=^## |\Z)", doc, re.S | re.M)
    assert block, "'해결하려는 문제' 절을 찾지 못했습니다"

    # `### 200자` 같은 길이 표기는 구조이지 본문이 아니다.
    body = re.sub(r"^### \d+자\s*$", "", block.group(1), flags=re.M)
    allowed = _allowed_numbers() | _NON_RELEASE_NUMBERS
    unknown = sorted(n for n in _numbers_in(body) if n not in allowed)
    assert not unknown, (
        f"원자료에 없는 숫자가 제출문에 있습니다: {unknown}. "
        "보도자료 숫자는 안전성조사_보도자료.json 에 먼저 넣고 그 값을 인용하세요."
    )


def test_the_draft_actually_carries_the_headline_figures():
    """비어 있어서 통과하는 검사가 되지 않게, 핵심 두 값이 실제로 있는지 본다."""
    doc = _DRAFT.read_text(encoding="utf-8")
    block = re.search(r"^## \d+\. 해결하려는 문제\n(.*?)(?=^## |\Z)", doc, re.S | re.M).group(1)
    survey = [s for s in _data()["조사"] if s["id"] == "2026-05-14-구매대행"][0]
    assert f"{survey['부적합률']}%" in block, "부적합률이 제출문에 없습니다"
    assert "과태료" in block, "공표 뒤 따라오는 조치가 제출문에 없습니다"


# ── (c) §9 단정 금지 ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "banned", ["안전합니다", "합법입니다", "판매 가능합니다", "문제없습니다", "걸리지 않습니다."]
)
def test_the_landing_makes_no_verdict(banned):
    """§9 단정 금지는 랜딩 본문 전체에 걸린다. 위험을 말하는 절에서 더 쉽게 미끄러진다."""
    assert banned not in _body(), f"랜딩 본문에 단정 표현 '{banned}' 가 있습니다"


def test_the_landing_does_not_claim_a_direct_multiple():
    """'국내의 4배' 같은 직접 비교는 조사 설계가 달라 성립하지 않는다.

    `test_failure_rate_honesty` 가 기획서에서 막는 것과 같은 실수다. 표적 조사와
    유통제품 평균은 표본 설계가 다르다.
    """
    text = _body()
    for phrase in ("4배", "네 배", "배입니다"):
        assert phrase not in text, f"직접 비교 표현이 랜딩에 있습니다: {phrase}"


def test_the_raw_data_still_records_that_the_sampling_was_targeted():
    """⚠⚠ **v2 에서 이 단서가 화면에서 사라졌다.** 총괄 확인이 필요하다.

    옛 랜딩은 "표적 조사" 라고 적었다 - 안 적으면 20% 가 전체 평균으로 읽히기
    때문이다. v2 문구(design/landing-v2.html)에는 그 단서가 없고, 문구는 "글자
    그대로" 옮기라는 지시라 여기서 지어내지 않았다.

    지금 남은 방어는 둘이다:
      - 모집단을 문장에 적는다 ("온라인 구매대행 제품 420개를 사서 시험했더니")
      - 직접 비교("국내의 4배")를 금지한다 (위 검사)

    원자료의 단서는 **지우지 않는다** - 화면에 다시 넣기로 하면 여기서 읽는다.
    """
    notes = " ".join(_data()["_주석"])
    assert "표적 조사" in notes, "원자료에서 표적 조사 단서가 사라졌다"
    # 모집단이 화면 문장에 남아 있는지 - 스크립트가 그리므로 원문에서 본다.
    assert "온라인 구매대행 제품" in _landing()
