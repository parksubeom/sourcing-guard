#!/usr/bin/env python
"""리콜 원문 링크가 실제로 살아 있는지 잰다 (핸드오프 ⑤).

왜 재는가
--------
근거 링크는 눌렀을 때 그 리콜을 볼 수 있어야 근거다 (CLAUDE.md R2). 국외
recallUrl 은 외국 기관의 원출처 주소라 우리가 관리하지 못하고, 오래된 공표일수록
만료돼 있을 수 있다. 죽은 링크를 셀러에게 보여주면 한 번 헛걸음한 뒤로 다른
링크도 안 누른다.

(로컬 사본 실측: URL 이 붙은 국외 공표는 2019~2026년분이다.)

무엇을 재는가
-------------
  ① 필드 채움률          scope 별로 detail_url 이 얼마나 오는가
  ② 정적 판별 통과율     is_usable_recall_url() 을 통과하는 비율
  ③ 실제 응답            표본을 실제로 열어 본 결과
       live        2xx 이고 원래 경로에 머물렀다
       redirected  2xx 이지만 호스트 루트/메인으로 떨어졌다  → 근거가 아니다
       dead        404 등, 그 문서가 없다
       unmeasured  403·429(봇 차단) · TLS · DNS · 타임아웃. 링크 상태를
                   말해주지 않으므로 비율 계산에서 뺀다

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
import ssl
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
TIMEOUT = 20
WORKERS = 6

# ⚠ 브라우저 헤더로 보낸다. 처음에 "sourcing-guard-linkcheck/1.0" 으로 보냈더니
#   cpsc.gov 가 전부 403 을 돌려줘 '죽은 링크' 로 집계됐다. 같은 URL 을 브라우저
#   UA 로 순차 요청하니 8/8 이 200 이었다. 봇 차단은 링크가 죽은 것이 아니다.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    "Connection": "close",
}

# ⚠ certifi 번들을 명시한다. 윈도우 파이썬 기본 신뢰 저장소로는 ec.europa.eu ·
#   rappel.conso.gouv.fr 이 전부 SSLCertVerificationError 였다. 첫 측정에서
#   52.1% 가 '오류' 로 잡힌 원인이 이것이고, 링크 상태와는 아무 상관이 없었다.
try:
    import certifi

    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:      # pragma: no cover - certifi 는 httpx 가 끌고 온다
    _SSL = ssl.create_default_context()

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
    """(분류, 비고). HEAD 를 거절하는 서버가 많아 GET 으로 간다.

    ⚠ "우리가 못 열었다" 와 "없어졌다" 를 섞지 않는다. 403(봇 차단) · TLS ·
      DNS · 타임아웃은 링크 상태에 대해 아무 말도 해주지 않으므로 unmeasured
      로 뺀다. 이걸 dead 에 넣으면 멀쩡한 근거 링크를 걷어내게 된다.
    """
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL) as r:
            final = r.geturl()
            code = r.status
            # 본문을 조금만 읽는다. 전량을 받으면 느리고 남의 대역폭을 쓴다.
            r.read(2048)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            return ("unmeasured", f"HTTP {e.code} (차단)")
        return ("dead", f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001 — 계측이므로 어떤 실패도 분류만 한다
        return ("unmeasured", type(e).__name__)

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

    order = ("live", "redirected", "dead", "unmeasured")
    for sc, c in sorted(by_scope.items()):
        n = sum(c.values())
        parts = "  ".join(f"{k} {c[k]:4d} ({c[k]/n:5.1%})" for k in order)
        print(f"  {sc:9s} n={n:4d}   {parts}")
        measured = n - c["unmeasured"]
        if measured:
            print(f"  {'':9s} 측정된 {measured}건 기준 — "
                  f"live {c['live']/measured:5.1%}  "
                  f"redirected {c['redirected']/measured:5.1%}  "
                  f"dead {c['dead']/measured:5.1%}")

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
