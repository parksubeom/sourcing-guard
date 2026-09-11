#!/usr/bin/env python
"""[M-4] 별칭 후보 자동 **발굴** — 안 붙은 상품명의 반복 어절 상위 100. LLM 0회.

    PYTHONPATH=. python -u scripts/domeggook_alias_candidates.py \\
        --titles tests/fixtures/도매꾹_표본_2026-09-12/상품명.tsv

산출물 (같은 디렉터리)
    별칭후보.tsv      어절 · 빈도 · 카테고리수 · 표에있나 · 예상품명3 · 판정(빈) · 근거(빈)
    어절빈도_전체.tsv  노이즈를 거르지 않은 상위 300 — 후보 파일이 무엇을 가렸는지 볼 수 있게

⚠⚠ **자동으로 별칭에 넣지 않는다.** 이 스크립트는 `item_grades.yaml`·`ALIASES` 를 한 글자도
  건드리지 않는다. 사람이 `판정`·`근거` 칸을 채운 줄만, 지금까지의 규칙대로 넣는다 -
  표 품목명·부속서 열거에 근거가 있어야 하고, 다섯 기준을 다 재고, 애매·비대상 부착이
  늘면 넣지 않는다. [M-3] 에서 '물놀이'→공기주입물놀이기구 같은 용도어 겹침이 이미
  실물로 나왔다 - 별칭은 넓히는 쪽이라 표본 0건이면 넣지 않는다 (CLAUDE.md §5).

⚠ 라벨: **후보 · 자동 삽입 금지 · 검수 전 · 매칭률 아님.**
⚠ 어절 = 공백·구분자(/ | , + ·)로 나눈 것. 형태소가 아니다 - 그래서 '기모장갑' 과 '장갑' 은
  다른 어절이다. 그것이 지시였고, 형태소 분석기를 넣으면 또 하나의 판정기가 된다.
⚠ 노이즈 목록은 **읽기 편의**다. 판정이 아니므로 전체 파일에는 그대로 둔다.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.batch import screen  # noqa: E402
from sourcing_guard.item_grades import ALIASES, ItemGradeBook  # noqa: E402

LABEL = "후보 · 자동 삽입 금지 · 검수 전 · 매칭률 아님"
TOP = 100
TOP_ALL = 300

_SPLIT = re.compile(r"[\s/|,+·∙•]+")
_STRIP = re.compile(r"^[\[\(\{<\"'*~★☆■□◆◇▶▷#]+|[\]\)\}>\"'*~★☆■□◆◇▶▷#!?.]+$")
_NUMERIC = re.compile(r"^[\d.,~\-x×*]+(?:[a-zA-Z%℃]+)?$")
#: 읽기 편의로 후보 파일에서만 뺀다. 판정이 아니다 - 전체 파일에는 남는다.
_NOISE = {
    "무료배송", "당일발송", "당일출고", "국내배송", "국내발송", "빠른배송", "무배", "사은품",
    "땡처리", "특가", "최저가", "정품", "신상", "신상품", "인기", "추천", "세트", "선물",
    "남녀공용", "남녀", "여성", "남성", "남자", "여자", "공용", "대형", "소형", "중형",
    "1개", "2개", "3개", "1p", "2p", "1세트", "택1", "1+1", "묶음", "낱개", "벌크", "박스",
    "도매", "도매꾹", "도매매", "업소용", "가정용", "다용도", "휴대용", "미니", "고급", "프리미엄",
}


def tokenize(title: str) -> list[str]:
    out = []
    for raw in _SPLIT.split(title):
        t = _STRIP.sub("", raw).strip()
        if len(t) < 2 or _NUMERIC.match(t):
            continue
        out.append(t)
    return out


def in_table(token: str, book: ItemGradeBook) -> str:
    """표에 이미 있는 어절인가 - 있는데 안 붙었으면 가드·조건 때문이다."""
    if book.names_an_item(token):
        return "품목명"
    if token in ALIASES:
        return "별칭"
    return ""


def collect_silent(titles_path: Path, book: ItemGradeBook, limit_cats: int = 0):
    """카테고리별 배치 경로를 다시 돌려 **안 붙은** 제목만 모은다."""
    groups: dict[str, tuple[str, list[str]]] = {}
    for r in csv.reader((ln for ln in titles_path.read_text(encoding="utf-8").splitlines()
                         if ln and not ln.startswith("#")), delimiter="\t"):
        if len(r) >= 4:
            groups.setdefault(r[0], (r[1], []))[1].append(r[3])
    codes = list(groups)[:limit_cats] if limit_cats else list(groups)
    silent: list[tuple[str, str]] = []          # (카테고리명, 제목)
    n_total = 0
    for i, code in enumerate(codes, 1):
        name, titles = groups[code]
        rep = screen("\n".join(titles), book, limit=len(titles) or 1)
        n_total += len(rep.rows)
        for row in rep.rows:
            if not (row.grade or row.matched_items or row.matched_item):
                silent.append((name, row.product_name))
        if i % 20 == 0 or i == len(codes):
            print(f"  [{i:3}/{len(codes)}] 침묵 누적 {len(silent):,}", flush=True)
    return silent, n_total


def count_tokens(silent: list[tuple[str, str]]):
    freq: Counter = Counter()
    cats: dict[str, set] = defaultdict(set)
    examples: dict[str, list[str]] = defaultdict(list)
    for cat, title in silent:
        seen = set()
        for t in tokenize(title):
            if t in seen:
                continue
            seen.add(t)
            freq[t] += 1
            cats[t].add(cat)
            if len(examples[t]) < 3:
                examples[t].append(title)
    return freq, cats, examples


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--titles", required=True)
    ap.add_argument("--limit", type=int, default=0, help="앞 N개 카테고리만 (시험용)")
    args = ap.parse_args()

    book = ItemGradeBook()
    out_dir = Path(args.titles).parent
    print(f"배치 경로 재실행 · 안 붙은 제목만 모음 · LLM 0회", flush=True)
    t0 = time.monotonic()
    silent, n_total = collect_silent(Path(args.titles), book, args.limit)
    freq, cats, examples = count_tokens(silent)
    elapsed = time.monotonic() - t0

    def row(tok: str) -> list[str]:
        return [tok, str(freq[tok]), str(len(cats[tok])), in_table(tok, book),
                " ‖ ".join(e[:60] for e in examples[tok]), "", ""]

    head = f"# {LABEL} · {date.today():%Y-%m-%d} · 안 붙은 제목 {len(silent):,} / {n_total:,}"
    cand = [t for t, _ in freq.most_common() if t not in _NOISE][:TOP]
    with (out_dir / "별칭후보.tsv").open("w", encoding="utf-8", newline="") as f:
        f.write(head + "\n# 어절\t빈도\t카테고리수\t표에있나\t예상품명\t판정\t근거(품목명·부속서)\n")
        f.write("# 판정·근거는 사람이 채운다. 채운 줄만, 다섯 기준을 재고 넣는다. 노이즈 목록은 읽기 편의 - 전체 파일 참조\n")
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        for t in cand:
            w.writerow(row(t))
    with (out_dir / "어절빈도_전체.tsv").open("w", encoding="utf-8", newline="") as f:
        f.write(head + " · 노이즈 미제거 상위 " + str(TOP_ALL) + "\n# 어절\t빈도\t카테고리수\t표에있나\n")
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        for t, n in freq.most_common(TOP_ALL):
            w.writerow([t, n, len(cats[t]), in_table(t, book)])

    already = [t for t in cand if in_table(t, book)]
    print()
    print(head)
    print(f"  {elapsed:.0f}s · 서로 다른 어절 {len(freq):,} · 후보 {len(cand)} · 그중 표에 이미 있는 어절 {len(already)}: {already[:12]}")
    print(f"  상위 25:")
    for t in cand[:25]:
        print(f"    {freq[t]:5}  {len(cats[t]):3}카테고리  {in_table(t, book) or '-':4}  {t}")
    print(f"\n저장 → {out_dir / '별칭후보.tsv'} · {out_dir / '어절빈도_전체.tsv'}")


if __name__ == "__main__":
    main()
