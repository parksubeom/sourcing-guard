#!/usr/bin/env python
"""[F] 국내 리콜 상품명에 배치 경로로 등급표 품목을 붙인다. LLM 0회 · 네트워크 0회.

    PYTHONPATH=. python -u scripts/recall_names_batch.py

입력   로컬 리콜 사본 (data/watchlist.db · RecallIndex · scope=domestic) 의 product_name
산출물 docs/F_리콜상품명_부착_YYYY-MM-DD.md            요약 + 상위 품목 (사람용)
       tests/fixtures/리콜_표본50_YYYY-MM-DD.tsv        검수용 50건 · 판정·근거 빈칸

⚠⚠ 라벨: **리콜 상품명 · 배치 경로 · 분모 N(실행 시 DB 건수) · 검수 없음.**
  "안 붙은 리콜은 세지 않으니 **'N건 이상'** 으로 쓴다" - 붙은 수는 하한이다. 안 붙었다고
  그 리콜이 우리 축 밖이라는 뜻이 아니다(상품명이 짧거나 어휘가 표에 없을 뿐).
⚠ 분모 4,244 를 하드코딩하지 않는다. 사본은 매일 갱신되어 지금은 4,245 다 - 실행 시 센다.
⚠ 표본 50 = 붙은 것 25 + 안 붙은 것 25, `random.Random(20260912)` 로 뽑아 재현된다.
⚠ 판정은 사람이 한다. 이 스크립트는 후보와 근거 자리만 만든다.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.batch import MAX_ROWS, BatchRow, screen  # noqa: E402
from sourcing_guard.config import settings  # noqa: E402
from sourcing_guard.item_grades import ItemGradeBook  # noqa: E402
from sourcing_guard.kats_client import RecallRecord  # noqa: E402
from sourcing_guard.recall_index import RecallIndex  # noqa: E402
from sourcing_guard.storage import SqliteWatchStore  # noqa: E402

SEED = 20260912
SAMPLE_EACH = 25


def label(n: int) -> str:
    return f"리콜 상품명 · 배치 경로 · 분모 {n:,} · 검수 없음"


def attach(records: list[RecallRecord], book: ItemGradeBook) -> list[tuple[RecallRecord, BatchRow]]:
    """리콜 레코드 → (레코드, 배치 행). 순서를 유지하며 MAX_ROWS 씩 자른다."""
    out: list[tuple[RecallRecord, BatchRow]] = []
    for i in range(0, len(records), MAX_ROWS):
        chunk = records[i:i + MAX_ROWS]
        rep = screen("\n".join((r.product_name or "").replace("\n", " ") for r in chunk),
                     book, limit=len(chunk))
        # ⚠ parse_lines 가 빈 줄·너무 짧은 줄을 버리지 않는지 - 행 수가 같아야 짝이 맞는다.
        assert len(rep.rows) == len(chunk), (len(rep.rows), len(chunk))
        out.extend(zip(chunk, rep.rows))
    return out


def summarize(pairs: list[tuple[RecallRecord, BatchRow]]) -> dict:
    n = len(pairs)
    matched = [(r, b) for r, b in pairs if b.grade or b.matched_items or b.matched_item]
    items: Counter = Counter()
    grades: Counter = Counter()
    for _, b in matched:
        for it in (b.matched_items or ([b.matched_item] if b.matched_item else [])):
            items[it] += 1
        if b.grade:
            grades[b.grade] += 1
    silent_v = Counter(b.verdict.value for _, b in pairs if (r := 1) and not (b.grade or b.matched_items or b.matched_item))
    empty_name = sum(1 for r, _ in pairs if not (r.product_name or "").strip())
    return {"n": n, "matched": len(matched), "pct": (len(matched) / n * 100) if n else 0.0,
            "items": items.most_common(20), "grades": dict(grades.most_common()),
            "silent_verdicts": dict(silent_v.most_common()), "empty_name": empty_name}


def sample(pairs: list[tuple[RecallRecord, BatchRow]], seed: int = SEED, each: int = SAMPLE_EACH):
    rng = random.Random(seed)
    hit = [p for p in pairs if p[1].grade or p[1].matched_items or p[1].matched_item]
    miss = [p for p in pairs if p not in hit]
    return rng.sample(hit, min(each, len(hit))) + rng.sample(miss, min(each, len(miss)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=settings.watchlist_db_path)
    ap.add_argument("--out-doc", default="")
    ap.add_argument("--out-tsv", default="")
    args = ap.parse_args()

    store = SqliteWatchStore(args.db)
    recs = [r for r in RecallIndex(store).all_records() if r.scope == "domestic"]
    if not recs:
        raise SystemExit("국내 리콜 레코드가 0건이다 - DB 경로를 확인할 것")
    book = ItemGradeBook()
    today = f"{date.today():%Y-%m-%d}"
    lab = label(len(recs))
    print(f"{lab} · 배치 경로 · LLM 0회", flush=True)

    t0 = time.monotonic()
    pairs = attach(recs, book)
    s = summarize(pairs)
    elapsed = time.monotonic() - t0

    # ── 표본 50 ──
    out_tsv = Path(args.out_tsv or f"tests/fixtures/리콜_표본50_{today}.tsv")
    with out_tsv.open("w", encoding="utf-8", newline="") as f:
        f.write(f"# {lab} · {today} · 붙은 것 {SAMPLE_EACH} + 안 붙은 것 {SAMPLE_EACH} · Random({SEED})\n")
        f.write("# uid\t리콜 상품명\t붙은 품목\t등급\tverdict\t판정\t근거(품목명·부속서)\n")
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        for r, b in sample(pairs):
            w.writerow([r.uid or "", (r.product_name or "").replace("\t", " "),
                        ";".join(b.matched_items or ([b.matched_item] if b.matched_item else [])),
                        b.grade or "", b.verdict.value, "", ""])

    # ── 문서 ──
    doc = [
        f"# [F] 국내 리콜 상품명 · 등급표 부착 — {today}",
        "",
        f"⚠⚠ 라벨: **{lab}**. 사람이 검수하지 않았다.",
        "",
        "## 결과 — **'N건 이상' 으로 읽는다**",
        f"    국내 리콜 {s['n']:,}건 중 등급표 품목이 붙은 것 **{s['matched']:,}건 이상** ({s['pct']:.1f}%)",
        f"    안 붙은 {s['n'] - s['matched']:,}건은 세지 않는다 - 상품명이 짧거나 어휘가 표에 없을 뿐,",
        f"    그 리콜이 우리 축 밖이라는 뜻이 아니다. (상품명 빈 레코드 {s['empty_name']})",
        f"    배치 경로 {elapsed:.0f}s · LLM 0회 · 네트워크 0회 · 분모는 실행 시 DB 에서 셌다",
        "",
        "## 붙은 등급 분포",
        *[f"    {v:>6}  {k}" for k, v in s["grades"].items()],
        "",
        "## 가장 많이 붙은 법정 품목 (상위 20)",
        *[f"    {v:>6}  {k}" for k, v in s["items"]],
        "",
        "## 안 붙은 쪽의 RowVerdict",
        *[f"    {v:>6}  {k}" for k, v in s["silent_verdicts"].items()],
        "",
        "## 검수",
        f"    `{out_tsv}` — 붙은 것 25 · 안 붙은 것 25. `판정`·`근거` 칸은 비어 있다. 사람이 채운다.",
        "    붙은 25 에서 오부착 비율을, 안 붙은 25 에서 놓친 어휘를 본다 - 둘이 [M-4] 후보와 겹치면 근거가 된다.",
        "",
        "## 왜 이 숫자가 유용한가",
        "    \"리콜된 상품 중 우리 등급표가 어휘를 아는 것이 N건 이상\" - 즉 그 상품이 상세페이지에 오면",
        "    리콜 대조 이전에 품목 축이 먼저 말을 한다. 인증·리콜 축은 이 측정에 없다(상품명만).",
    ]
    out_doc = Path(args.out_doc or f"docs/F_리콜상품명_부착_{today}.md")
    out_doc.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print("\n".join(doc[:24]))
    print(f"\n저장 → {out_doc} · {out_tsv}")


if __name__ == "__main__":
    main()
