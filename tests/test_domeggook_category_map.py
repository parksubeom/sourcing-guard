"""[M-1] 카테고리 지도 — 클라이언트 파라미터가 원문 명세와 같고, 파서가
XML→JSON 의 두 모양(dict/list)을 다 받고, 모르는 키는 지어내지 않는지.

⚠ 네트워크 0회. `httpx.get` 을 가로채 파라미터만 본다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from sourcing_guard.domeggook_client import DomeggookClient  # noqa: E402


@pytest.fixture
def captured(monkeypatch):
    calls: list[dict] = []

    def fake_get(url, params=None, timeout=None):
        calls.append(dict(params or {}))
        return httpx.Response(200, json={"domeggook": {"items": []}},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_category_list_params_match_the_reference(captured):
    """참조.md §4 — ver 1.0 · mode getCategoryList · isReg 선택."""
    c = DomeggookClient("KEY", min_interval=0)
    c.categories()
    c.categories(only_registrable=True)
    a, b = captured
    assert a["ver"] == "1.0" and a["mode"] == "getCategoryList" and a["om"] == "json"
    assert "isReg" not in a and b["isReg"] == "true"
    assert a["aid"] == "KEY"
    assert "market" not in a, "getCategoryList 에는 market 파라미터가 없다 (참조.md §4)"


def test_category_counts_params_match_the_reference(captured):
    """참조.md §5 — ver 2.0 · mode getCat · market Y · withZero 0/1."""
    c = DomeggookClient("KEY", market="dome", min_interval=0)
    c.category_counts()
    c.category_counts(with_zero=False)
    a, b = captured
    assert a["ver"] == "2.0" and a["mode"] == "getCat" and a["market"] == "dome"
    assert a["withZero"] == "1" and b["withZero"] == "0"
    # 지도는 0개 카테고리도 봐야 하므로 기본이 1 이다.


# ── 파서 — XML→JSON 의 두 모양 ─────────────────────────────────────
def test_flatten_handles_the_observed_indexed_dict_shape():
    """**실측 모양(2026-09-12)**: items 와 child 가 인덱스 문자열 키의 dict."""
    from domeggook_category_map import flatten_tree

    payload = {"domeggook": {"items": {
        "1": {"code": "01_00_00_00_00", "name": "패션잡화", "locked": None, "int": None,
              "child": {
                  "7": {"code": "01_07_00_00_00", "name": "남성가방", "locked": None, "int": None,
                        "child": {"3": {"code": "01_07_01_00_00", "name": "브리프케이스",
                                        "locked": "FALSE", "int": "4564"}}},
                  "8": {"code": "01_08_00_00_00", "name": "여성가방", "locked": None, "int": None},
              }},
        "2": {"code": "02_00_00_00_00", "name": "뷰티", "locked": None, "int": None},
    }}}
    rows = flatten_tree(payload)
    assert [(r["code"], r["depth"]) for r in rows] == [
        ("01_00_00_00_00", 1), ("01_07_00_00_00", 2), ("01_07_01_00_00", 3),
        ("01_08_00_00_00", 2), ("02_00_00_00_00", 1)]
    assert rows[2]["parents"] == "패션잡화 > 남성가방"


def test_flatten_handles_single_child_as_dict_and_many_as_list():
    """원문 XML 예시대로 왔을 때의 변형도 받는다 (list · 단일 dict)."""
    from domeggook_category_map import flatten_tree

    payload = {"domeggook": {"items": [
        {"code": "01_00_00_00_00", "name": "패션잡화", "locked": None, "int": None,
         "child": {"code": "01_07_00_00_00", "name": "남성가방", "locked": None, "int": None,
                   "child": [
                       {"code": "01_07_01_00_00", "name": "브리프케이스", "locked": "FALSE", "int": 4564},
                       {"code": "01_07_02_00_00", "name": "백팩", "locked": "TRUE", "int": 4565},
                   ]}},
    ]}}
    rows = flatten_tree(payload)
    assert [r["code"] for r in rows] == [
        "01_00_00_00_00", "01_07_00_00_00", "01_07_01_00_00", "01_07_02_00_00"]
    assert [r["depth"] for r in rows] == [1, 2, 3, 3]
    assert rows[3]["parents"] == "패션잡화 > 남성가방"
    assert rows[0]["locked"] is None and rows[2]["locked"] == "FALSE"


def test_counts_read_the_observed_indexed_pairs_shape():
    """**실측 모양(2026-09-12)**: `"N"` 이름 · `"@N"` 속성 dict, 값은 전부 문자열."""
    from domeggook_category_map import parse_counts

    payload = {"domeggook": {"items": {"item": {
        "0": "패션잡화", "@0": {"no": "1", "id": "01_00_00_00_00", "depth": "1", "itemCnt": "821572"},
        "1": "남성가방", "@1": {"no": "4563", "id": "01_07_00_00_00", "depth": "2", "itemCnt": "25808"},
    }}}}
    counts, seen, unknown = parse_counts(payload)
    assert seen[0] == "shape=indexed-pairs"
    assert counts["01_00_00_00_00"] == {"count": 821572, "depth": "1", "no": "1", "name": "패션잡화"}
    assert counts["01_07_00_00_00"]["count"] == 25808 and counts["01_07_00_00_00"]["name"] == "남성가방"
    assert unknown == {"code": 0, "count": 0}


def test_counts_read_only_keys_that_exist_and_report_unknowns():
    """원문 XML 예시대로 list 로 왔을 때. 키 이름을 지어내지 않고 후보 중 있는 것을 쓴다."""
    from domeggook_category_map import parse_counts

    payload = {"domeggook": {"items": {"item": [
        {"no": 1, "id": "01_00_00_00_00", "depth": 1, "itemCnt": 872195, "name": "패션잡화"},
        {"@no": "4563", "@id": "01_07_00_00_00", "@depth": "2", "@itemCnt": "39808", "#text": "남성가방"},
        {"depth": 3, "name": "코드 없음"},                       # 코드 미확인
        {"id": "09_99_00_00_00", "depth": 2, "name": "수 없음"},  # 상품수 미확인
    ]}}}
    counts, seen, unknown = parse_counts(payload)
    assert seen[0] == "shape=list"
    assert counts["01_00_00_00_00"]["count"] == 872195
    assert counts["01_07_00_00_00"]["count"] == 39808          # @ 접두 키도 읽는다
    assert counts["01_07_00_00_00"]["name"] == "남성가방"
    assert counts["09_99_00_00_00"]["count"] is None            # 지어내지 않는다
    assert unknown == {"code": 1, "count": 1}
    assert "itemCnt" in seen and "@itemCnt" in seen              # 관찰된 키를 남긴다


def test_the_table_has_six_columns_and_carries_the_label():
    from domeggook_category_map import LABEL, build_table

    tree = [{"code": "01_00_00_00_00", "name": "패션잡화", "depth": 1, "locked": None, "parents": ""}]
    counts = {"01_00_00_00_00": {"count": 5, "depth": 1, "no": 1, "name": "패션잡화"}}
    lines = build_table(tree, counts)
    assert LABEL in lines[0]
    for banned in ("정답률", "매칭률 ·"):                       # 매칭률로 읽히면 안 된다
        assert banned not in lines[0] or "매칭률 아님" in lines[0]
    data = [ln for ln in lines if not ln.startswith("#")]
    assert len(data) == 1 and len(data[0].split("\t")) == 6
    assert data[0].split("\t")[3] == "5"


def test_the_script_saves_only_through_write_sanitized():
    src = (Path(__file__).resolve().parents[1] / "scripts/domeggook_category_map.py").read_text(encoding="utf-8")
    assert src.count("write_sanitized(") == 2                    # 목록 · 상품수
    assert "json.dump(" not in src and ".write_text(json.dumps(" not in src, "정제 없이 원문을 쓴다"
    assert "매칭률 아님" in src and "검수 없음" in src
