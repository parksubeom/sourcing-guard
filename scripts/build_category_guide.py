#!/usr/bin/env python
"""[M-5] 카테고리 가이드 — 카테고리별로 **관찰된** 등급·부속서·소관을 표 하나로.

    PYTHONPATH=. python -u scripts/build_category_guide.py

산출물
    sourcing_guard/data/category_guide.tsv       배포본이 읽는다 (화면이 그린다)
    docs/M5_카테고리_가이드_YYYY-MM-DD.md          사람용

⚠⚠ **라벨: 매칭률 · 배치 경로 · 검수 없음 · 카테고리당 ≤100건 · 도매꾹 랭킹순.**
  사람이 검수하지 않았으므로 여기 숫자는 전부 **매칭률**이고 정답률이 아니다.
  71% 시절의 실수가 정확히 "매칭률을 정답률처럼 쓴 것" 이다.

⚠⚠ **연결은 관찰된 매칭만** (R5 · [M-5] 지시). 카테고리 이름으로 "이 카테고리는
  완구다" 를 정하지 않는다 - 그 카테고리의 상품명에서 **실제로 붙은 품목**만
  적고, 그 품목의 등급·부속서는 등급표·규칙 DB에서 그대로 읽는다.

⚠ **"관찰 안 됨" 은 "비대상" 이 아니다.** 우리가 못 붙인 것이지 의무가 없다는
  뜻이 아니다 - 그렇게 적는 순간 판정이 된다 (R3 · §9).

⚠ [M-3] 커버리지 지도와 **같은 배치 경로**를 돌린다. 붙음 수가 다르면 둘 중
  하나가 낡은 것이므로 **멈춘다** - 두 문서가 다른 숫자를 말하는 것이 이
  저장소의 반복 결함이다.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from sourcing_guard.batch import screen  # noqa: E402
from sourcing_guard.item_grades import ItemGradeBook  # noqa: E402
from sourcing_guard.models import ItemCategory, ProductFacts  # noqa: E402
from sourcing_guard.scoping import notice_jurisdictions  # noqa: E402
from sourcing_guard.verifier import RuleBook  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
LABEL = "매칭률 · 배치 경로 · 검수 없음 · 카테고리당 ≤100건 · 도매꾹 랭킹순"

TITLES = _ROOT / "tests/fixtures/도매꾹_표본_2026-09-12/상품명.tsv"
CAT_MAP = _ROOT / "tests/fixtures/도매꾹_카테고리_2026-09-12/카테고리_지도.tsv"
COVERAGE = _ROOT / "tests/fixtures/도매꾹_표본_2026-09-12/커버리지.tsv"
OUT_TSV = _ROOT / "sourcing_guard/data/category_guide.tsv"

COLUMNS = ("코드", "카테고리", "대분류", "상품수", "표본n", "붙음", "붙음%",
           "관찰된_품목", "관찰된_등급", "등급근거", "유해물질_부속서", "소관안내")


def read_titles(path: Path) -> dict[str, tuple[str, list[str]]]:
    out: dict[str, tuple[str, list[str]]] = {}
    for r in csv.reader((ln for ln in path.read_text(encoding="utf-8").splitlines()
                         if ln and not ln.startswith("#")), delimiter="\t"):
        if len(r) < 4:
            continue
        out.setdefault(r[0], (r[1], []))[1].append(r[3])
    return out


def read_parents(path: Path) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        c = ln.split("\t")
        if len(c) >= 6:
            out[c[0]] = (c[5].split(" > ")[0] if c[5] else c[1], c[3])
    return out


def read_coverage(path: Path) -> dict[str, int]:
    """[M-3] 의 붙음 수. **대조용이다.**"""
    out: dict[str, int] = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("#"):
            continue
        c = ln.split("\t")
        if len(c) >= 6:
            out[c[0]] = int(c[5])
    return out


def grade_table() -> dict[str, dict]:
    """품목명 → 등급표 행. **yaml 을 읽기만 한다** (safe_dump 금지 · §6)."""
    rows: dict[str, dict] = {}
    for name in ("item_grades.yaml", "child_item_grades.yaml"):
        raw = yaml.safe_load((_ROOT / "sourcing_guard/data" / name)
                             .read_text(encoding="utf-8")) or {}
        for r in raw.get("items", []):
            rows.setdefault(r["item"], r)
    return rows


_CATEGORY_OF = {
    "children": ItemCategory.CHILDREN_TOY,
    "household": ItemCategory.HOUSEHOLD,
    "electrical": ItemCategory.ELECTRICAL,
}


def annexes_for(item: str, row: dict, book: RuleBook) -> list[str]:
    """그 품목에 걸리는 유해물질 부속서 이름. **규칙 DB 가 답한다.**"""
    cat = _CATEGORY_OF.get(str(row.get("category") or ""), ItemCategory.UNCLASSIFIED)
    facts = ProductFacts(product_name=item, legal_item_name=item, category=cat)
    seen: list[str] = []
    for rule in book.applying_to(facts):
        base = rule.legal_basis.split("(")[0].strip()
        if base not in seen:
            seen.append(base)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="앞 N개만 (시간 재기)")
    ap.add_argument("--out-tsv", default=str(OUT_TSV))
    ap.add_argument("--out-doc", default="")
    args = ap.parse_args()

    groups = read_titles(TITLES)
    parents = read_parents(CAT_MAP)
    expected = read_coverage(COVERAGE)
    grades = grade_table()
    book = ItemGradeBook()
    rules = RuleBook()

    codes = list(groups)[: args.limit] if args.limit else list(groups)
    print(f"카테고리 {len(codes)}개 · 제목 {sum(len(groups[c][1]) for c in codes):,}건 "
          f"· 배치 경로 · LLM 0회 · 네트워크 0회", flush=True)

    out_rows: list[list[str]] = []
    mismatch: list[str] = []
    t0 = time.monotonic()
    for i, code in enumerate(codes, 1):
        name, titles = groups[code]
        parent, item_cnt = parents.get(code, ("", ""))
        report = screen("\n".join(titles), book, limit=len(titles) or 1)

        items: Counter = Counter()
        for r in report.rows:
            for it in (r.matched_items or ([r.matched_item] if r.matched_item else [])):
                items[it] += 1
        matched = sum(1 for r in report.rows
                      if r.grade or r.matched_items or r.matched_item)

        # ⚠ [M-3] 과 같은 수여야 한다. 다르면 둘 중 하나가 낡았다.
        if code in expected and expected[code] != matched:
            mismatch.append(f"{code} {name}: 지도 {expected[code]} · 지금 {matched}")

        grade_counts: Counter = Counter()
        sources: list[str] = []
        annexes: list[str] = []
        for item, n in items.items():
            row = grades.get(item)
            if not row:
                continue
            grade_counts[str(row.get("grade") or "")] += n
            src = str(row.get("source") or "")
            if src and src not in sources:
                sources.append(src)
            for a in annexes_for(item, row, rules):
                if a not in annexes:
                    annexes.append(a)

        # ⚠⚠ **건수를 붙인다.** 100건 중 1건이 걸린 표지어를 건수 없이 적으면
        #   "이 카테고리는 화장품 소관" 으로 읽힌다 - 실제로 남성가방에
        #   '화장품 파우치' 1건 때문에 화장품법이 붙었다(미완 §1-d 의 그 오탐).
        #   안내 축은 판정이 아니므로, 읽는 사람이 세기를 볼 수 있어야 한다.
        juris_hits: Counter = Counter()
        juris_label: dict[str, str] = {}
        for title in titles:
            for j in notice_jurisdictions(title):
                key = str(j.get("key") or "")
                juris_hits[key] += 1
                juris_label[key] = (f"{j.get('법령')}"
                                    f"({j.get('소관부처_대표') or j.get('기관')})")
        juris_txt = "; ".join(f"{juris_label[k]}({n}건)"
                              for k, n in juris_hits.most_common())

        out_rows.append([
            code, name, parent, item_cnt, str(len(report.rows)), str(matched),
            f"{matched / len(report.rows) * 100:.1f}" if report.rows else "0.0",
            "; ".join(f"{k}({v})" for k, v in items.most_common()),
            "; ".join(f"{k}({v})" for k, v in grade_counts.most_common()),
            "; ".join(sources),
            "; ".join(annexes),
            juris_txt,
        ])
        if i % 20 == 0 or i == len(codes):
            print(f"  [{i:3}/{len(codes)}] {name[:14]:14} 붙음 {matched:3}/{len(report.rows):3}"
                  f"  {time.monotonic() - t0:5.1f}s", flush=True)

    if mismatch:
        print("\n⚠⚠ [M-3] 커버리지 지도와 붙음 수가 다릅니다 - 멈춥니다:")
        for m in mismatch[:10]:
            print("  -", m)
        raise SystemExit(1)

    out = Path(args.out_tsv)
    out.parent.mkdir(parents=True, exist_ok=True)
    head = (
        f"# [M-5] 카테고리 가이드 · {LABEL} · {date.today():%Y-%m-%d}\n"
        "# ⚠ 여기 숫자는 전부 **매칭률**이고 정답률이 아니다. 사람이 검수하지 않았다.\n"
        "# ⚠ '관찰 안 됨'(붙음 0)은 **비대상이 아니다.** 우리가 못 붙인 것이다 (R3).\n"
        "# ⚠ 연결은 관찰된 매칭만 (R5). 카테고리 이름으로 품목을 정하지 않는다.\n"
        "# 생성: PYTHONPATH=. python -u scripts/build_category_guide.py  (LLM 0 · 네트워크 0)\n"
        "# " + "\t".join(COLUMNS) + "\n"
    )
    out.write_text(head + "".join("\t".join(r) + "\n" for r in out_rows),
                   encoding="utf-8")
    said = sum(1 for r in out_rows if int(r[5]) > 0)

    # ── 사람용 문서 ────────────────────────────────────────────
    doc_path = Path(args.out_doc or
                    _ROOT / f"docs/M5_카테고리_가이드_{date.today():%Y-%m-%d}.md")
    ordered = sorted(out_rows, key=lambda r: -int(r[5]))
    lines = [
        f"# [M-5] 카테고리 가이드 — {date.today():%Y-%m-%d}",
        "",
        f"⚠⚠ **라벨: {LABEL}.** 여기 숫자는 전부 **매칭률**이고 정답률이 아니다.",
        "  사람이 검수하지 않았다 - 71% 시절의 실수가 정확히 \"매칭률을 정답률처럼",
        "  쓴 것\" 이다. 기획서·랜딩에 넣지 않는다.",
        "",
        "⚠⚠ **붙음 0 은 \"비대상\" 이 아니다.** 우리가 못 붙인 것이지 의무가 없다는",
        "  뜻이 아니다 - 그렇게 적는 순간 판정이 된다 (R3 · §9).",
        "",
        "⚠ **연결은 관찰된 매칭만** (R5). 카테고리 이름으로 품목을 정하지 않았다 -",
        "  그 카테고리 상품명을 배치 경로에 넣어 **붙은 것만** 옮겼다.",
        "",
        "⚠ 자료 정본은 `sourcing_guard/data/category_guide.tsv` 이고 화면(`/guide`)이",
        "  그것을 그린다. 이 문서는 같은 자료의 사람용 사본이다 - **숫자를 여기서",
        "  옮겨 적지 말고 재생을 돌릴 것** (LLM 0 · 네트워크 0).",
        "",
        "## 전체",
        "",
        "```",
        f"카테고리 {len(out_rows)} · 제목 {sum(int(r[4]) for r in out_rows):,}건",
        f"말할 수 있는 카테고리 {said} · 아직 침묵 {len(out_rows) - said}",
        f"유해물질 부속서가 붙은 카테고리 {sum(1 for r in out_rows if r[10])}",
        f"소관 표기가 관찰된 카테고리 {sum(1 for r in out_rows if r[11])}",
        "```",
        "",
        "## 말할 수 있는 카테고리 (붙음 순)",
        "",
        "| 카테고리 | 대분류 | 붙음 | 관찰된 품목 | 관찰된 등급 | 소관 표기 관찰 |",
        "|---|---|---|---|---|---|",
    ]
    for r in ordered:
        if int(r[5]) == 0:
            continue
        lines.append(
            f"| {r[1]} | {r[2]} | {r[5]}/{r[4]} ({r[6]}%) | {r[7][:70]} | "
            f"{r[8][:46]} | {r[11][:46]} |")
    quiet = [r for r in ordered if int(r[5]) == 0]
    lines += [
        "",
        f"## 아직 침묵하는 카테고리 {len(quiet)}개",
        "",
        "⚠ **비대상이라는 뜻이 아니다.** 이 표본에서 우리 등급표에 걸린 상품명이",
        "  없었다는 뜻이다. 낮은 것이 정상인 대분류(식품·여행 등)인지는 읽는",
        "  사람이 대분류 이름을 보고 판단한다 - 우리가 적으면 판정이다.",
        "",
        "```",
    ]
    lines += ["  " + ", ".join(x[1] for x in quiet[i:i + 6])
              for i in range(0, len(quiet), 6)]
    lines += ["```", ""]
    doc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print()
    print(f"카테고리 {len(out_rows)} · 말할 수 있는 카테고리 {said} · 침묵 {len(out_rows) - said}")
    print(f"→ {doc_path}")
    print(f"[M-3] 붙음 수와 전부 일치 ({len(expected)}개 대조)")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
