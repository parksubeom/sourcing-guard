#!/usr/bin/env python
"""리콜 원문 링크가 실제로 살아 있는지 잰다 (핸드오프 ⑤).

왜 재는가
--------
근거 링크는 눌렀을 때 그 리콜을 볼 수 있어야 근거다 (CLAUDE.md R2). 국외
리콜은 2009년부터 쌓여 있고 recallUrl 은 외국 기관의 원출처 주소라, 오래된
공표일수록 만료돼 있을 가능성이 높다. 죽은 링크를 셀러에게 보여주면 한 번
헛걸음한 뒤로 다른 링크도 안 누른다.

무엇을 재는가
-------------
  ① 필드 채움률          scope 별로 detail_url 이 얼마나 오는가
  ② 정적 판별 통과율     is_usable_recall_url() 을 통과하는 비율
  ③ 실제 응답            표본을 실제로 열어 본 결과
       live        2xx 이고 원래 경로에 머물렀다
       redirected  2xx 이지만 호스트 루트/메인으로 떨어졌다  → 근거가 아니다
       dead        4xx / 5xx
       error       DNS·TLS·타임아웃

돌리는 법
---------
    python scripts/probe_recall_urls.py --sample 400
    python scripts/probe_recall_urls.py --scope overseas --all      # 전수(느리다)

로컬 리콜 사본이 있어야 한다. 없으면 먼저:
    python -c "from sourcing_guard.main import _kats,_store; \\
               from sourcing_guard.sync import run_sync; print(run_sync(_kats,_store))"

⚠ 이 스크립트는 계측용이다. 서버 런타임에서 링크를 확인하지 않는다 - 스캔마다
  외부로 요청을 날리면 응답이 그 사이트 지연에 묶이고, 외국 기관 서버에 우리
  트래픽이 그대로 간다. 여기서 잰 결과를 kats_client 의 정적 규칙에 반영한다.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sourcing_guard.config import settings                      # noqa: E402
from sourcing_guard.kats_client import is_usable_recall_url     # noqa: E402
from sourcing_guard.storage import SqliteWatchStore             # noqa: E402

# 외국 기관 서버를 두드리는 것이므로 조심스럽게 간다.
TIMEOUT = 12
WORKERS = 8
UA = "Mozilla/5.0 (compatible; sourcing-guard-linkcheck/1.0)"

# 경로가 없는 것과 같은 취급. kats_client._DEAD_PATHS 와 같은 뜻이지만 여기서는
# "리다이렉트로 여기 도착했는가" 를 보는 용도라 따로 둔다.
ROOTISH = {"", "/", "/index.html", "/index.htm", "/index.jsp", "/index.php",
           "/main", "/main.do", "/home", "/default.aspx"}


def load_urls(scope: str | None) -> list[tuple[str, str, str]]:
    """(scope, announced_on, detail_url) 목록. detail_url 이 있는 것만."""
    store = SqliteWatchStore(settings.watchlist_db_path)
    out: list[tuple[str, str, str]] = []
    for payload in store.recall_payloads(scope=scope):
        try:
            d = json.loads(payload)
        except ValueError:
            continue
        url = (d.get("detail_url") or "").strip()
        if url:
            out.append((d.get("scope") or "?", d.get("announced_on") or "", url))
    return out


def field_stats(scope: str | None) -> dict[str, dict[str, int]]:
    """scope 별 채움률과 정적 판별 통과율."""
    store = SqliteWatchStore(settings.watchlist_db_path)
    agg: dict[str, Counter] = defaultdict(Counter)
    for payload in store.recall_payloads(scope=scope):
        try:
            d = json.loads(payload)
        except ValueError:
            continue
        sc = d.get("scope") or "?"
        agg[sc]["total"] += 1
        url = (d.get("detail_url") or "").strip()
        if url:
            agg[sc]["has_url"] += 1
            if is_usable_recall_url(url):
                agg[sc]["usable"] += 1
    return {k: dict(v) for k, v in agg.items()}


def probe(url: str) -> tuple[str, str]:
    """(분류, 비고). HEAD 를 거절하는 서버가 많아 GET 으로 간다."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            final = r.geturl()
            code = r.status
            # 본문을 조금만 읽는다. 전량을 받으면 느리고 남의 대역폭을 쓴다.
            r.read(2048)
    except urllib.error.HTTPError as e:
        return ("dead", f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001 — 계측이므로 어떤 실패도 분류만 한다
        return ("error", type(e).__name__)

    if code >= 400:
        return ("dead", f"HTTP {code}")
    before, after = urlparse(url), urlparse(final)
    path = (after.path or "").rstrip("/").lower()
    if path in ROOTISH and not after.query:
        return ("redirected", f"→ {final}")
    if before.netloc != after.netloc and path in ROOTISH:
        return ("redirected", f"→ {final}")
    return ("live", final if final != url else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["domestic", "overseas"], default=None)
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--all", action="store_true", help="표본이 아니라 전수")
    ap.add_argument("--seed", type=int, default=20260901)
    args = ap.parse_args()

    print("=== ① 필드 채움률 · ② 정적 판별 ===")
    for sc, st in sorted(field_stats(args.scope).items()):
        total, has, usable = st.get("total", 0), st.get("has_url", 0), st.get("usable", 0)
        if not total:
            continue
        print(f"  {sc:9s} 전체 {total:6,d}  "
              f"URL 있음 {has:6,d} ({has/total:6.1%})  "
              f"정적 판별 통과 {usable:6,d} ({usable/total:6.1%})")

    rows = load_urls(args.scope)
    if not rows:
        print("\n리콜 사본에 detail_url 이 없습니다. 초기 적재를 먼저 돌리세요.")
        return 1

    targets = [r for r in rows if is_usable_recall_url(r[2])]
    if not args.all:
        random.Random(args.seed).shuffle(targets)
        targets = targets[: args.sample]

    print(f"\n=== ③ 실제 응답 ({len(targets):,d}건 / 동시 {WORKERS}) ===")
    verdicts: list[tuple[str, str, str, str, str]] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for (sc, on, url), (verdict, note) in zip(
            targets, pool.map(lambda t: probe(t[2]), targets)
        ):
            verdicts.append((sc, on, url, verdict, note))

    by_scope: dict[str, Counter] = defaultdict(Counter)
    by_year: dict[str, Counter] = defaultdict(Counter)
    for sc, on, _url, verdict, _note in verdicts:
        by_scope[sc][verdict] += 1
        by_year[(on or "????")[:4]][verdict] += 1

    order = ("live", "redirected", "dead", "error")
    for sc, c in sorted(by_scope.items()):
        n = sum(c.values())
        parts = "  ".join(f"{k} {c[k]:4d} ({c[k]/n:5.1%})" for k in order)
        print(f"  {sc:9s} n={n:4d}   {parts}")

    print("\n  공표 연도별 (live 비율)")
    for year in sorted(by_year):
        c = by_year[year]
        n = sum(c.values())
        if n < 5:
            continue
        print(f"    {year}  n={n:4d}  live {c['live']/n:5.1%}  "
              f"redirected {c['redirected']/n:5.1%}  dead {c['dead']/n:5.1%}")

    print("\n  죽은 링크 예시")
    shown = 0
    for sc, on, url, verdict, note in verdicts:
        if verdict in ("dead", "redirected") and shown < 12:
            print(f"    [{verdict:10s}] {on} {url[:80]}  {note[:60]}")
            shown += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
