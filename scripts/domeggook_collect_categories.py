#!/usr/bin/env python
"""[M-2] 중분류마다 상품 100건의 **제목**을 모은다. 카테고리당 호출 1회.

    PYTHONPATH=. python -u scripts/domeggook_collect_categories.py \\
        --map tests/fixtures/도매꾹_카테고리_2026-09-12/카테고리_지도.tsv

산출물 (tests/fixtures/도매꾹_표본_YYYY-MM-DD/)
    상품명.tsv     코드 · 카테고리 · 상품번호 · 제목            ← [M-3] 배치 경로 입력
    수집_요약.tsv  코드 · 카테고리 · itemCnt(getCat) · numberOfItems(list) · 받은 건수 · 오류
    README.md      라벨 · 회차 · 호출 수 · 429/오류 · 걸린 시간

⚠⚠ 라벨: **매칭률 아님 · 검수 없음 · 도매꾹 랭킹순 상위 100 · 수집일 기준.**
  이 표본으로 재는 것은 전부 매칭률이고 정답률이 아니다. 기획서·랜딩 금지.

⚠ 응답 JSON 을 그대로 저장하지 않는다 - 199개 × ~120KB ≈ 24MB 라 리포에 못 둔다.
  대신 **응답마다 `sanitize()` + `residual()` 게이트를 메모리에서 통과시킨 뒤**
  `no`·`title` 만 뽑아 TSV 로 쓴다. `새표본235.txt` 와 같은 성격의 파일이다.
  게이트에 걸리면(잔존 개인정보) 그 카테고리는 건너뛰고 오류 열에 적는다.

⚠ 프로세스 하나 · python -u · 이전 프로세스 확인. 429 를 받으면 **재시도하지 않고**
  그 자리까지를 저장하고 멈춘다 - 부분 결과도 라벨과 함께 남긴다.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.config import _load_dotenv  # noqa: E402
from sourcing_guard.domeggook_client import (  # noqa: E402
    DomeggookApiError,
    DomeggookClient,
    DomeggookRateLimited,
)
from sourcing_guard.domeggook_pii import ResidualPiiError, residual, sanitize  # noqa: E402

LABEL = "매칭률 아님 · 검수 없음 · 도매꾹 랭킹순 상위 100 · 수집일 기준"
SZ = 100


def _cell(x) -> str:
    return " ".join(str(x if x is not None else "").replace("\t", " ").split())


def read_map(path: Path, depth: int = 2) -> list[dict]:
    """카테고리_지도.tsv 에서 중분류(깊이 2)만. 열: 코드 이름 깊이 상품수 등록제한 상위경로."""
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        c = ln.split("\t")
        if len(c) >= 4 and c[2] == str(depth):
            rows.append({"code": c[0], "name": c[1], "item_cnt": c[3]})
    return rows


def gate_and_project(payload: dict) -> tuple[list[tuple[str, str]], int | None]:
    """응답 → [(no, title)], header.numberOfItems. **개인정보 게이트를 먼저 통과**한다.

    ⚠ 게이트 뒤의 값만 밖으로 나간다. 잔존이 있으면 ResidualPiiError 를 던진다 -
      부르는 쪽이 그 카테고리를 건너뛰고 오류 열에 적는다.
    """
    clean, _ = sanitize(payload)
    left = residual(clean)
    if left:
        raise ResidualPiiError(left)
    root = clean.get("domeggook", clean)
    header = root.get("header") or {}
    total = header.get("numberOfItems")
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    lst = root.get("list") or {}
    items = lst.get("item") if isinstance(lst, dict) else lst
    if isinstance(items, dict):
        items = [items]
    out = []
    for it in items or []:
        if isinstance(it, dict) and it.get("no") is not None and it.get("title"):
            out.append((str(it["no"]), _cell(it["title"])))
    return out, total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="카테고리_지도.tsv")
    ap.add_argument("--out", default="")
    ap.add_argument("--market", default="dome")
    ap.add_argument("--limit", type=int, default=0, help="앞 N개 카테고리만 (시험용)")
    ap.add_argument("--so", default="rd", help="정렬. 기본 rd 도매꾹랭킹순 (참조.md §2)")
    args = ap.parse_args()

    _load_dotenv()
    key = os.getenv("DOMEGGOOK_API_KEY")
    if not key:
        raise SystemExit("DOMEGGOOK_API_KEY 가 없습니다 (.env)")

    cats = read_map(Path(args.map))
    if args.limit:
        cats = cats[: args.limit]
    out_dir = Path(args.out or f"tests/fixtures/도매꾹_표본_{date.today():%Y-%m-%d}")
    out_dir.mkdir(parents=True, exist_ok=True)
    client = DomeggookClient(key, market=args.market)

    print(f"중분류 {len(cats)}개 · sz={SZ} · so={args.so} · 저장 {out_dir}", flush=True)
    t0 = time.monotonic()
    titles: list[tuple[str, str, str, str]] = []
    summary: list[dict] = []
    stopped = ""
    for i, c in enumerate(cats, 1):
        err = ""
        got, total = [], None
        try:
            payload = client.search(ca=c["code"], so=args.so, sz=SZ, pg=1)
            got, total = gate_and_project(payload)
        except DomeggookRateLimited as exc:
            stopped = f"429 at {i}/{len(cats)} ({c['code']})"
            print(f"\n⚠ {stopped} - 재시도하지 않는다. 여기까지 저장.", flush=True)
            summary.append({**c, "total": "", "got": 0, "err": "429"})
            break
        except ResidualPiiError as exc:
            err = f"pii:{len(exc.paths) if hasattr(exc, 'paths') else '?'}"
        except DomeggookApiError as exc:
            err = f"api:{exc}"[:60]
        for no, title in got:
            titles.append((c["code"], c["name"], no, title))
        summary.append({**c, "total": "" if total is None else total, "got": len(got), "err": err})
        print(f"[{i:3}/{len(cats)}] {c['code']} {c['name'][:14]:14} "
              f"itemCnt={c['item_cnt']:>7} numberOfItems={'' if total is None else total:>7} "
              f"받음={len(got):3} {err}", flush=True)
    elapsed = time.monotonic() - t0

    # 압축 TSV 만 쓴다 - 응답 JSON 은 쓰지 않는다 (머리 주석 참조).
    with (out_dir / "상품명.tsv").open("w", encoding="utf-8", newline="") as f:
        f.write(f"# {LABEL} · {date.today():%Y-%m-%d} · 코드\t카테고리\t상품번호\t제목\n")
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        for row in titles:
            w.writerow(row)
    with (out_dir / "수집_요약.tsv").open("w", encoding="utf-8", newline="") as f:
        f.write(f"# {LABEL} · 코드\t카테고리\titemCnt(getCat)\tnumberOfItems(list)\t받은건수\t오류\n")
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        for s in summary:
            w.writerow([s["code"], s["name"], s["item_cnt"], s["total"], s["got"], s["err"]])

    n_err = sum(1 for s in summary if s["err"])
    full = sum(1 for s in summary if s["got"] == SZ)
    readme = [
        f"# 도매꾹 중분류 표본 — {date.today():%Y-%m-%d}",
        "",
        f"⚠ 라벨: **{LABEL}**. 기획서·랜딩에 넣지 않는다.",
        "",
        "## 회차",
        f"    호출 {client.calls}회 · {elapsed:.0f}s · market={args.market} · so={args.so} · sz={SZ}",
        f"    카테고리 {len(summary)}/{len(cats)} 처리 · 제목 {len(titles):,}건 · 100건 다 받은 카테고리 {full}",
        f"    오류 {n_err}건" + (f" · **중단: {stopped}**" if stopped else ""),
        "",
        "## 저장 형태",
        "    응답 JSON 은 저장하지 않았다 (199×~120KB ≈ 24MB). sanitize()+residual() 게이트를",
        "    메모리에서 통과시킨 뒤 no·title 만 TSV 로 썼다 - 새표본235.txt 와 같은 성격.",
        "",
        "## itemCnt(getCat) 와 numberOfItems(list) 가 다른 이유 후보",
        "    판매중지·품절·단종은 목록에 안 나온다(참조.md). 두 값의 차이가 그 규모다 - 수집_요약.tsv.",
    ]
    (out_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print()
    print("\n".join(readme))
    print(f"\n저장 → {out_dir}")


if __name__ == "__main__":
    main()
