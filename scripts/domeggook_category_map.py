#!/usr/bin/env python
"""[M-1] 도매꾹 카테고리 지도 - 트리(getCategoryList) + 상품 수(getCat). 호출 2회.

    PYTHONPATH=. python -u scripts/domeggook_category_map.py

산출물 (tests/fixtures/도매꾹_카테고리_YYYY-MM-DD/)
    카테고리_목록.json     getCategoryList 응답 (write_sanitized 경유)
    카테고리_상품수.json   getCat 응답        (write_sanitized 경유)
    카테고리_지도.tsv      코드 · 이름 · 깊이 · 상품수 · 등록제한 · 상위경로
    README.md             라벨 · 회차 · 호출 수 · **관찰된 JSON 모양**

⚠⚠ 라벨: **상품 수 · 도매꾹 getCat · 수집일 기준 · 매칭률 아님 · 검수 없음.**
  이 숫자는 "셀러가 실제로 파는 것의 지도" 이고 우리 정답률과 무관하다.
  기획서·랜딩에 넣지 않는다.

⚠ 원문 문서(참조.md §5)는 XML 예시만 있어 JSON 속성 키가 미확인이다. 첫 응답의
  키를 그대로 README 에 적고, 후보 키(`id`·`@id`·`code` …) 중 **있는 것만** 읽는다.
  없으면 "미확인" 으로 센다 - 지어내지 않는다 (R5).

⚠ 저장은 `write_sanitized` 만 - 카테고리 응답에 개인정보는 없지만 저장 경로를
  하나로 두는 규칙은 응답 종류를 가리지 않는다 (§6).
⚠ 프로세스 하나 · python -u · 이전 프로세스 확인. 도매꾹은 IP 등록제라 개발 PC 에서만.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.config import _load_dotenv  # noqa: E402
from sourcing_guard.domeggook_client import DomeggookApiError, DomeggookClient  # noqa: E402
from sourcing_guard.domeggook_pii import write_sanitized  # noqa: E402

LABEL = "상품 수 · 도매꾹 getCat · 수집일 기준 · 매칭률 아님 · 검수 없음"

# 후보 키 - 원문이 XML 속성이라 JSON 표기가 미확인. 순서대로 있는 것을 쓴다.
_K_CODE = ("id", "@id", "code")
_K_DEPTH = ("depth", "@depth")
_K_COUNT = ("itemCnt", "@itemCnt", "item_cnt", "count")
_K_NO = ("no", "@no")
_K_NAME = ("name", "#text", "text", "item", "$")


def _pick(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return None


def _as_list(x: Any) -> list:
    """XML→JSON 은 원소가 하나면 dict 로 온다. 둘 다 list 로 맞춘다."""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _nodes(container: Any) -> list[dict]:
    """노드 묶음을 list 로. **관찰된 모양(2026-09-12)**: 인덱스 문자열을 키로 한 dict
    (`{"1": {...}, "2": {...}}`). 원문 XML 예시대로면 list 또는 단일 dict 일 수도
    있어 셋 다 받는다 - 어느 쪽이 왔는지는 README 에 적는다."""
    if isinstance(container, dict):
        if "code" in container:                       # 단일 노드가 그대로 온 경우
            return [container]
        return [v for v in container.values() if isinstance(v, dict)]
    return [x for x in _as_list(container) if isinstance(x, dict)]


def flatten_tree(payload: dict) -> list[dict]:
    """getCategoryList 응답 → 평평한 행. 깊이는 경로 길이로 센다.

    실측(2026-09-12): items 와 child 모두 인덱스 dict. 13 / 199 / 1871 / 2954 = 5,037.
    """
    root = payload.get("domeggook", payload)
    rows: list[dict] = []

    def walk(node: dict, path: list[str]) -> None:
        name = str(node.get("name") or "")
        here = path + [name]
        rows.append({
            "code": str(node.get("code") or ""),
            "name": name,
            "depth": len(here),
            "locked": node.get("locked"),
            "parents": " > ".join(path),
        })
        for ch in _nodes(node.get("child")):
            walk(ch, here)

    for top in _nodes(root.get("items")):
        walk(top, [])
    return rows


def _count_entries(item: Any) -> tuple[list[dict], str]:
    """getCat `items.item` → 항목 dict 목록 + 관찰된 모양 이름.

    **관찰된 모양(2026-09-12)**: 인덱스 쌍 dict - `"N"` 이 이름 문자열,
    `"@N"` 이 속성 dict `{no, id, depth, itemCnt}` (값은 전부 문자열).
    원문 XML 예시대로면 list 일 수도 있어 둘 다 받는다.
    """
    if isinstance(item, dict) and item and all(k.lstrip("@").isdigit() for k in item):
        out = []
        for k, v in item.items():
            if k.startswith("@") and isinstance(v, dict):
                e = dict(v)
                e.setdefault("name", item.get(k[1:]))
                out.append(e)
        return out, "indexed-pairs"
    return [x for x in _as_list(item) if isinstance(x, dict)], "list"


def parse_counts(payload: dict) -> tuple[dict[str, dict], list[str], dict[str, int]]:
    """getCat 응답 → {코드: {count, depth, no, name}}, 관찰된 키 목록, 미확인 건수.

    `seen_keys[0]` 에 모양 이름(`shape=…`)을 넣어 README 가 그대로 적는다.
    """
    root = payload.get("domeggook", payload)
    items = root.get("items", {})
    rows, shape = _count_entries(items.get("item") if isinstance(items, dict) else items)
    out: dict[str, dict] = {}
    seen_keys: list[str] = [f"shape={shape}"]
    unknown = {"code": 0, "count": 0}
    for it in rows:
        if not isinstance(it, dict):
            unknown["code"] += 1
            continue
        for k in it:
            if k not in seen_keys:
                seen_keys.append(k)
        code = _pick(it, _K_CODE)
        cnt = _pick(it, _K_COUNT)
        if code is None:
            unknown["code"] += 1
            continue
        if cnt is None:
            unknown["count"] += 1
        out[str(code)] = {
            "count": int(cnt) if cnt is not None and str(cnt).isdigit() else None,
            "depth": _pick(it, _K_DEPTH),
            "no": _pick(it, _K_NO),
            "name": _pick(it, _K_NAME),
        }
    return out, seen_keys, unknown


def build_table(tree: list[dict], counts: dict[str, dict]) -> list[str]:
    lines = [
        f"# 도매꾹 카테고리 지도 · {LABEL} · {date.today():%Y-%m-%d}",
        "# 코드\t이름\t깊이\t상품수\t등록제한\t상위경로",
    ]
    for r in tree:
        c = counts.get(r["code"], {})
        cnt = c.get("count")
        lines.append("\t".join([
            r["code"], r["name"], str(r["depth"]),
            "" if cnt is None else str(cnt),
            "" if r["locked"] is None else str(r["locked"]),
            r["parents"],
        ]))
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--market", default="dome")
    ap.add_argument("--from-saved", default="",
                    help="저장된 정제본 디렉터리에서 표만 다시 만든다. **호출 0회.**")
    args = ap.parse_args()

    if args.from_saved:
        # 파서를 고친 뒤 API 를 다시 부르지 않고 지도를 다시 만든다 - 쿼터를
        # 아끼고, 회차를 늘리지 않는다 (§6 "실호출은 측정에서만").
        out_dir = Path(args.from_saved)
        tree_raw = json.loads((out_dir / "카테고리_목록.json").read_text(encoding="utf-8"))
        cnt_raw = json.loads((out_dir / "카테고리_상품수.json").read_text(encoding="utf-8"))
        tree_counts, cnt_counts, elapsed, calls = {}, {}, 0.0, 0
        print(f"저장본에서 재생성 · 호출 0회 · {out_dir}", flush=True)
    else:
        _load_dotenv()
        key = os.getenv("DOMEGGOOK_API_KEY")
        if not key:
            raise SystemExit("DOMEGGOOK_API_KEY 가 없습니다 (.env)")

        out_dir = Path(args.out or f"tests/fixtures/도매꾹_카테고리_{date.today():%Y-%m-%d}")
        client = DomeggookClient(key, market=args.market)
        t0 = time.monotonic()

        print(f"[1/2] getCategoryList … ", end="", flush=True)
        tree_raw = client.categories()
        print("받음", flush=True)
        print(f"[2/2] getCat market={args.market} withZero=1 … ", end="", flush=True)
        cnt_raw = client.category_counts(with_zero=True)
        print("받음", flush=True)
        elapsed = time.monotonic() - t0
        calls = client.calls

        tree_counts = write_sanitized(out_dir / "카테고리_목록.json", tree_raw)
        cnt_counts = write_sanitized(out_dir / "카테고리_상품수.json", cnt_raw)

    tree = flatten_tree(tree_raw)
    counts, seen_keys, unknown = parse_counts(cnt_raw)
    table = build_table(tree, counts)
    (out_dir / "카테고리_지도.tsv").write_text("\n".join(table) + "\n", encoding="utf-8")

    by_depth: dict[int, int] = {}
    for r in tree:
        by_depth[r["depth"]] = by_depth.get(r["depth"], 0) + 1
    joined = sum(1 for r in tree if counts.get(r["code"], {}).get("count") is not None)
    top2 = sorted(
        ((counts.get(r["code"], {}).get("count") or 0, r["name"], r["code"])
         for r in tree if r["depth"] == 2), reverse=True)[:20]

    tree_codes = {r["code"] for r in tree}
    only_counts = sorted(set(counts) - tree_codes)
    only_tree = sorted(tree_codes - set(counts))

    readme = [
        f"# 도매꾹 카테고리 지도 — {date.today():%Y-%m-%d}",
        "",
        f"⚠ 라벨: **{LABEL}**. 기획서·랜딩에 넣지 않는다.",
        "",
        "## 회차",
        f"    호출 {calls}회 (getCategoryList · getCat) · {elapsed:.1f}s · market={args.market}"
        + ("   ← 저장본 재생성" if args.from_saved else ""),
        f"    개인정보 치환: 목록 {sum(tree_counts.values())} · 상품수 {sum(cnt_counts.values())}  (카테고리 응답 - 0 이 정상)",
        "",
        "## 관찰된 JSON 모양 (R5 - 원문은 XML 예시만 있었다)",
        f"    getCat items.item: {seen_keys}",
        f"    코드 미확인 {unknown['code']} · 상품수 미확인 {unknown['count']}",
        "",
        "## 트리",
        *[f"    깊이 {d}: {n}개" for d, n in sorted(by_depth.items())],
        f"    코드로 상품수를 붙인 행: {joined} / {len(tree)}",
        f"    상품수에만 있는 코드 {len(only_counts)}개: {only_counts[:5]}{' …' if len(only_counts) > 5 else ''}",
        f"    트리에만 있는 코드 {len(only_tree)}개: {only_tree[:5]}{' …' if len(only_tree) > 5 else ''}",
        "",
        "## 중분류(깊이 2) 상품 수 상위 20 — [M-2] 표본 우선순위 ①",
        *[f"    {c:>9,}  {n}  ({code})" for c, n, code in top2],
    ]
    (out_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    print()
    print("\n".join(readme))
    print(f"\n저장 → {out_dir}")


if __name__ == "__main__":
    try:
        main()
    except DomeggookApiError as exc:
        raise SystemExit(f"도매꾹 오류: {exc}")
