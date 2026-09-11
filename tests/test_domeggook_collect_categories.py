"""[M-2] 카테고리 표본 수집 — 파라미터가 참조.md 와 같고, 개인정보 게이트를 거친
값만 밖으로 나가며, 응답 JSON 을 그대로 쓰지 않는지. 네트워크 0회.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sourcing_guard.domeggook_client import DomeggookClient  # noqa: E402
from sourcing_guard.domeggook_pii import ResidualPiiError, sanitize  # noqa: E402


@pytest.fixture
def captured(monkeypatch):
    calls: list[dict] = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params or {}))
        return httpx.Response(200, json={"domeggook": {"header": {}, "list": {"item": []}}},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_search_by_category_sends_ca_and_so_per_the_reference(captured):
    c = DomeggookClient("KEY", min_interval=0)
    c.search(ca="09_03_00_00_00", so="rd", sz=100, pg=1)
    p = captured[0]
    assert p["ver"] == "4.1" and p["mode"] == "getItemList" and p["market"] == "dome"
    assert p["ca"] == "09_03_00_00_00" and p["so"] == "rd" and p["sz"] == 100
    assert "kw" not in p, "kw 없이 ca 만으로 검색한다"


def test_search_requires_kw_or_ca(captured):
    c = DomeggookClient("KEY", min_interval=0)
    with pytest.raises(ValueError):
        c.search()
    c.search(kw="마스크")                      # 기존 호출은 그대로 된다
    assert captured[0]["kw"] == "마스크" and "ca" not in captured[0]


def test_list_sanitizer_now_drops_the_seller_nick():
    """`id` 는 지우고 `nick` 은 남기고 있었다 - 둘 다 판매자 식별자다 (참조.md)."""
    payload = {"domeggook": {"list": {"item": [
        {"no": 1, "title": "상품", "id": "seller01", "nick": "어떤도매몰", "thumb": "http://x/t.jpg", "price": 1000},
    ]}}}
    clean, counts = sanitize(payload)
    it = clean["domeggook"]["list"]["item"][0]
    assert "id" not in it and "nick" not in it and "thumb" not in it
    assert it["no"] == 1 and it["title"] == "상품" and it["price"] == 1000
    assert counts["list.item.nick 제거"] == 1


def test_gate_and_project_returns_only_no_and_title_after_the_pii_gate():
    from domeggook_collect_categories import gate_and_project

    payload = {"domeggook": {"header": {"numberOfItems": "89169", "currentPage": 1},
                             "list": {"item": [
                                 {"no": 11, "title": "블록\t완구  세트", "id": "s", "nick": "n", "price": 1},
                                 {"no": 12, "title": "물놀이 튜브", "id": "s", "nick": "n"},
                             ]}}}
    rows, total = gate_and_project(payload)
    assert rows == [("11", "블록 완구 세트"), ("12", "물놀이 튜브")]   # 탭·이중 공백 정리
    assert total == 89169


def test_gate_and_project_raises_when_pii_remains(monkeypatch):
    """잔존이 있으면 값이 밖으로 나가지 않는다 - 부르는 쪽이 그 카테고리를 건너뛴다."""
    import domeggook_collect_categories as m

    monkeypatch.setattr(m, "residual", lambda clean: ["list.item[0].title"])
    with pytest.raises(ResidualPiiError):
        m.gate_and_project({"domeggook": {"list": {"item": [{"no": 1, "title": "010-1234-5678"}]}}})


def test_read_map_takes_depth_two_only(tmp_path):
    from domeggook_collect_categories import read_map

    p = tmp_path / "지도.tsv"
    p.write_text("# 머리\n01_00_00_00_00\t패션잡화\t1\t10\t\t\n"
                 "01_07_00_00_00\t남성가방\t2\t7\t\t패션잡화\n"
                 "01_07_01_00_00\t브리프케이스\t3\t3\tFALSE\t패션잡화 > 남성가방\n", encoding="utf-8")
    rows = read_map(p)
    assert rows == [{"code": "01_07_00_00_00", "name": "남성가방", "item_cnt": "7"}]


def test_the_script_never_writes_the_raw_response():
    src = (Path(__file__).resolve().parents[1] / "scripts/domeggook_collect_categories.py").read_text(encoding="utf-8")
    assert "write_sanitized(" not in src and "json.dump" not in src, "응답 JSON 을 쓰면 24MB 다 - 압축 TSV 만"
    assert "residual(clean)" in src and "sanitize(payload)" in src
    assert "매칭률 아님" in src and "검수 없음" in src
    assert "재시도하지 않는다" in src
