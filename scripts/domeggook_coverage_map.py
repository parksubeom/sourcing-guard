#!/usr/bin/env python
"""[M-3] 커버리지 지도 — 카테고리별로 배치 경로(LLM 0회)를 돌려 "어디서 말할 수 있고
어디서 통째로 침묵하나" 를 카테고리 이름으로 말할 수 있게 한다.

    PYTHONPATH=. python -u scripts/domeggook_coverage_map.py \\
        --titles tests/fixtures/도매꾹_표본_2026-09-12/상품명.tsv \\
        --map    tests/fixtures/도매꾹_카테고리_2026-09-12/카테고리_지도.tsv

산출물
    docs/M_커버리지지도_YYYY-MM-DD.md            표 + 읽는 법 (사람용)
    tests/fixtures/도매꾹_표본_YYYY-MM-DD/커버리지.tsv  기계용 (같은 숫자)

⚠⚠ 라벨: **매칭률 · 배치 경로 · 검수 없음 · 카테고리당 ≤100건 · 도매꾹 랭킹순.**
  사람이 검수하지 않았으므로 여기 숫자는 전부 **매칭률**이고 정답률이 아니다.
  71% 시절의 실수가 정확히 "매칭률을 정답률처럼 쓴 것" 이다. 기획서·랜딩 금지.

⚠ "대상 축인가" 는 카테고리 **이름으로 판정하지 않는다**(R5·R3). 관찰로 채운다 -
  그 카테고리에서 등급이 하나라도 붙었으면 "관찰됨", 아니면 "관찰 안 됨". 대분류
  이름은 읽는 사람이 "식품·여행이면 낮은 것이 정상이겐다" 를 스스로 판단하도록
  옆에 둔다. 우리가 "이 카테고리는 비대상" 이라고 적는 것은 판정이다.

⚠ 배치 경로는 상품명만 본다. 인증·리콜 축은 여기 없다 - 이 지도는 **품목 축**의
  커버리지다. 침묵의 이유는 `RowVerdict` + `reason` 으로 적는다.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.batch import BatchRow, screen  # noqa: E402
from sourcing_guard.item_grades import ItemGradeBook  # noqa: E402

LABEL = "매칭률 · 배치 경로 · 검수 없음 · 카테고리당 ≤100건 · 도매꾹 랭킹순"


def read_titles(path: Path) -> dict[str, tuple[str, list[str]]]:
    """상품명.tsv → {코드: (카테고리명, [제목…])} (입력 순서 유지)."""
    out: dict[str, tuple[str, list[str]]] = {}
    for r in csv.reader((ln for ln in path.read_text(encoding="utf-8").splitlines()
                         if ln and not ln.startswith("#")), delimiter="\t"):
        if len(r) < 4:
            continue
        code, name, _no, title = r[0], r[1], r[2], r[3]
        out.setdefault(code, (name, []))[1].append(title)
    return out


def read_parents(map_path: Path) -> dict[str, tuple[str, str]]:
    """지도 TSV → {코드: (대분류, itemCnt)}. 대분류는 상위경로의 첫 토큰."""
    out = {}
    for ln in map_path.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        c = ln.split("\t")
        if len(c) >= 6:
            out[c[0]] = (c[5].split(" > ")[0] if c[5] else c[1], c[3])
    return out


def summarize(rows: list[BatchRow]) -> dict:
    """한 카테고리의 배치 결과 → 지도 한 행의 숫자. 순수 함수."""
    n = len(rows)
    matched = [r for r in rows if r.grade or r.matched_items or r.matched_item]
    silent = [r for r in rows if r not in matched]
    items: Counter = Counter()
    for r in matched:
        for it in (r.matched_items or ([r.matched_item] if r.matched_item else [])):
            items[it] += 1
    verdicts = Counter(r.verdict.value for r in silent)
    reasons = Counter((r.reason or "").strip() for r in silent)
    return {
        "n": n,
        "matched": len(matched),
        "matched_pct": (len(matched) / n * 100) if n else 0.0,
        "top_items": items.most_common(5),
        "silent": len(silent),
        "silent_pct": (len(silent) / n * 100) if n else 0.0,
        "silent_verdicts": dict(verdicts.most_common()),
        "silent_reasons": dict(reasons.most_common(3)),
        "axis_observed": bool(matched),          # 이름이 아니라 관찰로
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--titles", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--limit", type=int, default=0, help="앞 N개 카테고리만 (시간 재기)")
    ap.add_argument("--out-doc", default="")
    ap.add_argument("--out-tsv", default="")
    args = ap.parse_args()

    groups = read_titles(Path(args.titles))
    parents = read_parents(Path(args.map))
    codes = list(groups)
    if args.limit:
        codes = codes[: args.limit]
    book = ItemGradeBook()
    today = f"{date.today():%Y-%m-%d}"

    print(f"카테고리 {len(codes)}개 · 제목 {sum(len(groups[c][1]) for c in codes):,}건 · 배치 경로 · LLM 0회", flush=True)
    t0 = time.monotonic()
    results: list[tuple[str, str, str, str, dict]] = []
    for i, code in enumerate(codes, 1):
        name, titles = groups[code]
        parent, item_cnt = parents.get(code, ("", ""))
        t1 = time.monotonic()
        report = screen("\n".join(titles), book, limit=len(titles) or 1)
        s = summarize(report.rows)
        results.append((code, name, parent, item_cnt, s))
        top = ", ".join(f"{k} {v}" for k, v in s["top_items"][:3])
        print(f"[{i:3}/{len(codes)}] {name[:12]:12} n={s['n']:3} 붙음 {s['matched_pct']:5.1f}% "
              f"침묵 {s['silent_pct']:5.1f}%  {time.monotonic()-t1:4.1f}s  {top}", flush=True)
    elapsed = time.monotonic() - t0

    # ── TSV ──
    out_tsv = Path(args.out_tsv or Path(args.titles).with_name("커버리지.tsv"))
    with out_tsv.open("w", encoding="utf-8", newline="") as f:
        f.write(f"# {LABEL} · {today} · 코드\t카테고리\t대분류\titemCnt\tn\t붙음\t붙음%\t침묵%\t축관찰\t상위품목\t침묵verdict\n")
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        for code, name, parent, item_cnt, s in results:
            w.writerow([code, name, parent, item_cnt, s["n"], s["matched"], f"{s['matched_pct']:.1f}",
                        f"{s['silent_pct']:.1f}", "관찰됨" if s["axis_observed"] else "관찰 안 됨",
                        "; ".join(f"{k}({v})" for k, v in s["top_items"]),
                        "; ".join(f"{k}({v})" for k, v in s["silent_verdicts"].items())])

    # ── 문서 ──
    total_n = sum(s["n"] for *_, s in results)
    total_m = sum(s["matched"] for *_, s in results)
    by_parent: dict[str, list[dict]] = defaultdict(list)
    for code, name, parent, item_cnt, s in results:
        by_parent[parent].append({"name": name, **s})
    all_items: Counter = Counter()
    for *_, s in results:
        for k, v in s["top_items"]:
            all_items[k] += v
    all_silent_v: Counter = Counter()
    for *_, s in results:
        all_silent_v.update(s["silent_verdicts"])

    doc = [
        f"# [M-3] 도매꾹 커버리지 지도 — {today}",
        "",
        f"⚠⚠ 라벨: **{LABEL}**. 사람이 검수하지 않았으므로 **전부 매칭률**이고 정답률이",
        "  아니다. 71% 시절의 실수가 정확히 매칭률을 정답률처럼 쓴 것이다. 기획서·랜딩에 넣지 않는다.",
        "",
        "⚠ 이 지도는 **품목 축**의 커버리지다. 배치 경로는 상품명만 보므로 인증·리콜 축은 없다.",
        "⚠ \"축 관찰\" 은 카테고리 이름으로 판정한 것이 아니다 - 그 카테고리에서 등급이 하나라도",
        "  붙었으면 \"관찰됨\". 낮은 것이 정상인지 문제인지는 대분류 이름을 보고 **사람이** 가른다.",
        "",
        "## 전체",
        f"    카테고리 {len(results)} · 제목 {total_n:,} · 등급 붙음 {total_m:,} ({total_m/total_n*100:.1f}%) · 침묵 {total_n-total_m:,}",
        f"    배치 경로 {elapsed:.0f}s · LLM 0회 · 네트워크 0회",
        "",
        "## 침묵의 이유 (RowVerdict · 전체)",
        *[f"    {v:>7}  {k}" for k, v in all_silent_v.most_common()],
        "",
        "## 가장 많이 붙은 법정 품목 (상위 20 · 상품 수)",
        *[f"    {v:>5}  {k}" for k, v in all_items.most_common(20)],
        "",
        "## 대분류별 — 여기는 말할 수 있다 / 여기는 통째로 침묵한다",
        "",
        "| 대분류 | 중분류 | n | 붙음 | 붙음% | 축 관찰 | 상위 품목 |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for parent in sorted(by_parent, key=lambda p: -sum(x["matched"] for x in by_parent[p])):
        for x in sorted(by_parent[parent], key=lambda x: -x["matched_pct"]):
            top = ", ".join(f"{k}({v})" for k, v in x["top_items"][:3])
            doc.append(f"| {parent} | {x['name']} | {x['n']} | {x['matched']} | {x['matched_pct']:.1f} | "
                       f"{'관찰됨' if x['axis_observed'] else '관찰 안 됨'} | {top} |")
    doc += [
        "",
        "## 읽는 법",
        "- **붙음%가 높은 곳**: 등급표가 이 카테고리 어휘를 안다. 다만 붙었다고 맞은 것이 아니다 - [M-4]",
        "  별칭 후보와 사람 검수가 그 다음이다.",
        "- **붙음%가 0 인 곳**: 두 가지다. (가) 전안법 축 밖(식품·여행·콘텐츠) - 침묵이 옳다.",
        "  (나) 축 안인데 표가 어휘를 모른다 - [M-4]·[M-5] 대상. 가르는 것은 사람이다.",
        "- 침묵 verdict 가 `undecided` 면 \"상품명만으로 못 가렸다\" 이고, `out_of_scope` 면 코드가",
        "  타 소관 표기를 찾은 것이다.",
        "",
        f"기계용 같은 숫자: `{out_tsv}`",
    ]
    out_doc = Path(args.out_doc or f"docs/M_커버리지지도_{today}.md")
    out_doc.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print()
    print("\n".join(doc[:22]))
    print(f"\n저장 → {out_doc} · {out_tsv}")


if __name__ == "__main__":
    main()
