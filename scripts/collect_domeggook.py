#!/usr/bin/env python
"""새표본235 상품명으로 도매꾹 상세를 수집한다. 검색 235회 + 상세 3회.

⚠ **채택 규칙: 정확 일치만.** `list.item.title` 을 정규화해서 표본 상품명과
  같은 것만 채택한다. 부분 일치·"가까운 것" 채택은 금지다 - 다른 상품의
  상세를 표본에 섞으면 그 뒤 모든 측정이 거짓이 된다.

    1건 → 채택   0건 → 미확인(0건)   2건 이상 → 전부 기록하고 미확인(복수)

  `kw` 검색이 형태소를 어떻게 분해하는지 우리는 모른다. API 의 채점을 믿지
  않고 `title` 비교를 우리가 한다.

⚠ 표본은 2026-09-06 에 만든 것이다. 판매중지·품절·단종은 검색 결과에 나오지
  않으므로(참조.md) 0건이 "그런 상품이 없다" 가 아니라 "지금 판매중이
  아니다" 일 수 있다. 그 수를 따로 센다.

⚠ 프로세스 하나만. 돌리기 전에 이전 프로세스를 확인하고 죽인다. 진행은
  한 줄씩 즉시 흘려보낸다(`python -u`) - 2026-09-07 에 버퍼링 때문에 같은
  측정을 두 번 돌려 429 를 맞았다 (CLAUDE.md §6).

⚠ 응답 원문을 **가공하지 않고** 저장한다. 텍스트 조립은 A-4 가 한다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.config import _load_dotenv  # noqa: E402
from sourcing_guard.domeggook_client import (  # noqa: E402
    MAX_VIEW_BATCH,
    DomeggookApiError,
    DomeggookClient,
    DomeggookRateLimited,
)

_SAMPLE = Path("tests/fixtures/새표본235.txt")


def norm_title(name: str) -> str:
    """제목 비교용 정규화. 공백·특수문자를 지우고 전각을 반각으로.

    ⚠ 등급표의 `normalize()` 와 **다른 함수다.** 저쪽은 품목명 비교용이라
      한글·영숫자만 남기는데, 상품명에는 숫자·단위·브랜드가 의미를 갖는다.
      여기서는 **공백과 기호만** 지운다 - 더 지우면 다른 상품이 같아진다.
    """
    s = unicodedata.normalize("NFKC", name or "")
    return re.sub(r"[\s\-_/·,.()\[\]{}]+", "", s).upper()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sz", type=int, default=50)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    _load_dotenv()
    key = os.getenv("DOMEGGOOK_API_KEY")
    if not key:
        raise SystemExit("DOMEGGOOK_API_KEY 가 없습니다 (.env)")

    names = [
        line.strip()
        for line in _SAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        names = names[: args.limit]

    out_dir = Path(args.out or f"tests/fixtures/도매꾹_원문_{date.today():%Y-%m-%d}")
    out_dir.mkdir(parents=True, exist_ok=True)

    client = DomeggookClient(key)
    searches: list[dict] = []
    picked: list[dict] = []
    zero: list[str] = []
    multi: list[dict] = []
    started = time.time()

    print(f"검색 {len(names)}건 · sz={args.sz} · 저장 {out_dir}", flush=True)
    for i, name in enumerate(names, 1):
        try:
            res = client.search(name, sz=args.sz)
        except DomeggookRateLimited as exc:
            print(f"\n429 에서 멈춥니다: {exc}", flush=True)
            print(f"  진행 {i - 1}/{len(names)} - 재시도하지 않습니다.", flush=True)
            break
        except DomeggookApiError as exc:
            print(f"  [{i:3}/{len(names)}] !! {name[:36]} — {exc}", flush=True)
            searches.append({"query": name, "error": str(exc)})
            continue

        searches.append({"query": name, "response": res})
        root = res.get("domeggook") or {}
        items = ((root.get("list") or {}).get("item")) or []
        if isinstance(items, dict):
            items = [items]
        want = norm_title(name)
        exact = [it for it in items if norm_title(it.get("title", "")) == want]

        if len(exact) == 1:
            picked.append({"query": name, "no": str(exact[0]["no"]),
                           "title": exact[0].get("title")})
            mark = "채택"
        elif not exact:
            zero.append(name)
            mark = "0건"
        else:
            multi.append({"query": name,
                          "candidates": [
                              {"no": str(it["no"]), "title": it.get("title")}
                              for it in exact
                          ]})
            mark = f"복수{len(exact)}"
        total = (root.get("header") or {}).get("numberOfItems")
        print(f"  [{i:3}/{len(names)}] {mark:<6} 검색결과 {str(total):>6} · {name[:40]}",
              flush=True)

    (out_dir / "검색.json").write_text(
        json.dumps(searches, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # ── 상세 ────────────────────────────────────────────────────────
    views: list[dict] = []
    nos = [p["no"] for p in picked]
    batches = [nos[i:i + MAX_VIEW_BATCH] for i in range(0, len(nos), MAX_VIEW_BATCH)]
    print(f"\n상세 {len(nos)}건 → {len(batches)}회 호출", flush=True)
    for bi, batch in enumerate(batches, 1):
        try:
            res = client.view([int(n) for n in batch])
        except DomeggookRateLimited as exc:
            print(f"429 에서 멈춥니다: {exc}", flush=True)
            break
        except DomeggookApiError as exc:
            print(f"  [{bi}/{len(batches)}] !! {exc}", flush=True)
            views.append({"nos": batch, "error": str(exc)})
            continue
        views.append({"nos": batch, "response": res})
        got = ((res.get("domeggook") or {}).get("item")) or []
        if isinstance(got, dict):
            got = [got]
        print(f"  [{bi}/{len(batches)}] {len(batch)}개 요청 → {len(got)}개 응답",
              flush=True)

    (out_dir / "상세.json").write_text(
        json.dumps(views, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # ── 보고 ────────────────────────────────────────────────────────
    detail_items: list[dict] = []
    for v in views:
        got = ((v.get("response", {}).get("domeggook") or {}).get("item")) or []
        detail_items += [got] if isinstance(got, dict) else got

    status: dict[str, int] = {}
    channel: dict[str, int] = {}
    for it in detail_items:
        st = (it.get("basis") or {}).get("status") or "(없음)"
        status[st] = status.get(st, 0) + 1
        ch = it.get("channel") or {}
        for k in ("dome", "supply"):
            if str(ch.get(k)).lower() == "true":
                channel[k] = channel.get(k, 0) + 1

    print(f"\n{'=' * 74}")
    print(f"수집 · {out_dir}\n")
    print(f"  표본            {len(names)}건")
    print(f"  채택            {len(picked)}건 (정확 일치 1건)")
    print(f"  미확인(0건)     {len(zero)}건   ← 판매중지·품절·단종은 검색에 안 나온다")
    print(f"  미확인(복수)    {len(multi)}건")
    print(f"  상세 응답       {len(detail_items)}건")
    print(f"\n  basis.status    {status}")
    print(f"  channel         {channel}")
    print(f"  호출 수         {client.calls}회 · {time.time() - started:.0f}초")

    (out_dir / "채택.json").write_text(
        json.dumps({"picked": picked, "zero": zero, "multi": multi},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n  채택 목록 → {out_dir / '채택.json'}")


if __name__ == "__main__":
    main()
