"""링크 미리보기 태그 — 카카오·슬랙에 붙였을 때 무엇이 보이는가.

2026-09-21 까지 여덟 장 전부 `og:` · `twitter:` · `canonical` 이 **0개**였다.
링크를 공유하면 제목만 나오고 그림도 설명도 없었다.

⚠⚠ **공유용 문구를 새로 짓지 않는다.** `og:title` 은 그 화면의 `<title>`,
  `og:description` 은 그 화면의 `<meta name=description>` 을 그대로 쓴다.
  따로 적으면 같은 판단이 두 벌이 되고 한쪽만 고쳐질 때 미리보기가 낡은
  말을 한다 (CLAUDE.md §6).
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PAGES = ["/", "/scan", "/batch", "/watch", "/guide", "/samples", "/misses", "/unknown"]


@pytest.fixture(scope="module")
def client():
    from sourcing_guard.main import app
    with TestClient(app) as c:
        yield c


def test_every_screen_carries_preview_tags(client):
    """⚠ 본 화면 수를 같이 단정한다 - 한 장이 목록에서 빠지면 조용히 통과한다."""
    checked = []
    for path in PAGES:
        html = client.get(path).text
        og = dict(re.findall(r'<meta property="(og:[^"]+)" content="([^"]*)">', html))
        for key in ("og:type", "og:url", "og:title", "og:description",
                    "og:image", "og:image:alt", "og:site_name"):
            assert key in og and og[key], f"{path} 에 {key} 가 없습니다"
        assert re.search(r'name="twitter:card" content="summary_large_image"', html), path
        assert re.search(r'<link rel="canonical" href="https?://[^"]+">', html), path
        checked.append(path)
    assert len(checked) == 8, f"여덟 장을 다 보지 않았습니다: {checked}"


def test_preview_text_is_copied_from_the_page_not_written_twice(client):
    """공유 문구의 소유자는 화면의 `<title>`·`description` 하나다."""
    for path in PAGES:
        html = client.get(path).text
        title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
        desc = re.search(r'<meta name="description" content="([^"]*)"', html).group(1)
        og_t = re.search(r'<meta property="og:title" content="([^"]*)">', html).group(1)
        og_d = re.search(r'<meta property="og:description" content="([^"]*)">', html).group(1)
        # 값에 `"` 가 있으면 이스케이프돼 들어간다 - 되돌려 비교한다
        unesc = lambda s: s.replace("&quot;", '"').replace("&amp;", "&").replace("&#x27;", "'")
        assert unesc(og_t) == title, f"{path} 의 og:title 이 화면 제목과 다릅니다"
        assert unesc(og_d) == desc, f"{path} 의 og:description 이 화면 설명과 다릅니다"


def test_attribute_values_are_escaped(client):
    """`/unknown` 제목이 `왜 "모름" 이 나왔나` 다 - 이스케이프를 빼면 그 자리에서
    속성이 끊기고 뒤 태그가 통째로 깨진다 (2026-09-21 실측).
    """
    html = client.get("/unknown").text
    assert '&quot;' in html, "제목의 큰따옴표가 이스케이프되지 않았습니다"
    assert len(re.findall(r'<meta property="og:[^"]+" content="[^"]*">', html)) >= 7


def test_the_route_table_matches_the_registered_routes():
    """`_PAGE_ROUTE` 는 라우트 데코레이터와 **같은 판단을 두 번째로** 적은 곳이다.
    그래서 실제 등록된 라우트와 대조한다 (R4 표 ↔ ALLOWED_HOSTS 와 같은 방식).
    """
    from sourcing_guard.main import _PAGE_ROUTE, app

    registered = {getattr(r, "path", None) for r in app.routes}
    missing = sorted(p for p in _PAGE_ROUTE.values() if p not in registered)
    assert missing == [], f"_PAGE_ROUTE 에 있는데 등록되지 않은 경로: {missing}"
    assert sorted(_PAGE_ROUTE.values()) == sorted(PAGES), (
        "_PAGE_ROUTE 와 이 검사의 화면 목록이 갈렸습니다")


def test_the_cover_image_is_served(client):
    r = client.get("/static/og.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 10_000, "커버가 비어 있습니다"


def test_the_cover_image_still_shows_the_current_five_numbers():
    """⚠⚠ **커버 PNG 안에 `77.0%` 와 `0건` 이 그려져 있다.** 기준선이 움직이면
    그림이 거짓말을 한다 - 그리고 그림은 검사가 읽을 수 없다.

    그래서 **그림이 무엇을 그렸는지**를 옆에 적어 두고 기준선과 대조한다.
    기준선을 옮기면 이 검사가 깨지고, 그때 커버를 다시 그려야 한다는 것을
    알게 된다 (CLAUDE.md §6 "같은 판단을 두 곳에 적지 마라").
    """
    from sourcing_guard.baseline import BASELINE

    drawn = Path(__file__).resolve().parents[1] / "sourcing_guard" / "static" / "og.png.numbers"
    assert drawn.exists(), (
        "커버가 그린 숫자를 적어 둔 파일이 없습니다 - static/og.png.numbers")
    got = dict(
        line.split("=", 1) for line in drawn.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#"))
    gpt = BASELINE["gpt"]
    rate = f"{gpt['ok'] / 135 * 100:.1f}"
    assert got["ok_rate"] == rate, (
        f"커버에 그린 적중률 {got['ok_rate']}% 가 기준선 {rate}% 와 다릅니다 - "
        "커버를 다시 그려 주세요")
    assert int(got["off_target"]) == gpt["off_target"], (
        f"커버에 그린 비대상 부착 {got['off_target']} 이 기준선 "
        f"{gpt['off_target']} 과 다릅니다 - 커버를 다시 그려 주세요")
    assert int(got["denominator"]) == 135
