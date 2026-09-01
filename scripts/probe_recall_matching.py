#!/usr/bin/env python
"""리콜 매칭 오탐 추적 · 규칙 변경 재검증 (핸드오프 ④).

무엇을 하나
-----------
  trace   상품 하나를 넣으면 어떤 리콜이 어느 강도로 무엇 때문에 걸렸는지
          전부 보여준다. "펜을 검사했는데 왜 블라인드가 뜨나" 를 추적하는 도구다.

  eval    규칙을 바꾸기 전후로 두 가지를 함께 잰다. 하나만 재면 반드시 틀린다.
            오탐  무관한 상품이 '확인된 문제'(exact/strong) 로 잡히는 건수
            재현율 리콜 원문에서 뽑은 모델명으로 그 리콜 자신을 다시 찾는 비율

왜 둘을 같이 재나
-----------------
매칭을 조이면 오탐은 반드시 줄고 재현율은 반드시 준다. 한쪽만 보면 항상
"개선됐다" 는 결론이 나온다. 놓친 리콜은 이 서비스가 하는 유일한 약속을
깨뜨리므로 (CLAUDE.md R6) 재현율 손실을 눈으로 보고 결정해야 한다.

돌리는 법
---------
    python scripts/probe_recall_matching.py trace "모나미 153 볼펜" --model 153 --maker 모나미
    python scripts/probe_recall_matching.py eval --sample 3000

로컬 리콜 사본이 있어야 한다 (data/watchlist.db 의 recalls 테이블).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sourcing_guard.config import settings                # noqa: E402
from sourcing_guard.kats_client import RecallRecord       # noqa: E402
from sourcing_guard.models import MatchStrength, ProductFacts, WatchItem  # noqa: E402
from sourcing_guard.storage import SqliteWatchStore       # noqa: E402
from sourcing_guard import watchlist as wl                # noqa: E402

TODAY = date(2026, 9, 1)
CONFIRMED = (MatchStrength.EXACT, MatchStrength.STRONG)


def load_records() -> list[RecallRecord]:
    store = SqliteWatchStore(settings.watchlist_db_path)
    out: list[RecallRecord] = []
    for payload in store.recall_payloads():
        try:
            out.append(RecallRecord(**json.loads(payload)))
        except (ValueError, TypeError):
            continue
    return out


def probe_item(product: str, model: str | None, maker: str | None) -> WatchItem:
    facts = ProductFacts(product_name=product, model_name=model, maker=maker)
    return WatchItem.from_facts(id="__probe__", owner_id="__probe__", facts=facts, on=TODAY)


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------
def cmd_trace(args) -> int:
    records = load_records()
    item = probe_item(args.product, args.model, args.maker)
    print(f"상품   : {args.product}")
    print(f"모델명 : {args.model!r} → 정규화 {wl.normalize_model(args.model)!r}")
    print(f"제조사 : {args.maker!r} → 정규화 {wl.normalize_model(args.maker)!r}")
    print(f"리콜 사본: {len(records):,d}건\n")

    hits = []
    for r in records:
        m = wl.match(item, r)
        if m is not None:
            hits.append((r, m))

    by = Counter(m.strength.value for _, m in hits)
    confirmed = [(r, m) for r, m in hits if m.strength in CONFIRMED]
    print(f"일치 {len(hits)}건  " + "  ".join(f"{k} {v}" for k, v in sorted(by.items())))
    print(f"이 중 '확인된 문제'(RED) 로 나가는 것 {len(confirmed)}건\n")

    wm = wl.normalize_model(args.model)
    for r, m in sorted(hits, key=lambda p: p[1].strength.value):
        models = wl._recall_models(r)
        why = ""
        if m.matched_on == "model_name" and wm:
            culprit = next((rm for rm in models if rm == wm or wm in rm or rm in wm), "")
            why = f"  ← 리콜 모델명 조각 {culprit!r}"
        elif m.matched_on == "maker+product":
            overlap = wl.tokenize_name(item.product_name) & wl.tokenize_name(r.product_name)
            why = f"  ← 겹친 단어 {sorted(overlap)}"
        print(f"  [{m.strength.value:6s}/{m.matched_on:13s}] "
              f"{(r.announced_on or '')[:8]} {r.scope:8s} "
              f"{(r.product_name or '')[:28]:28s}{why}")
    return 0


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------
# 무관한 상품. 하나라도 '확인된 문제' 로 잡히면 그건 오탐이다.
# 실제로 셀러가 붙여넣은 모양 그대로 둔다.
FALSE_POSITIVE_PROBES = [
    ("모나미 153 볼펜 흑색 12개입", "153", "모나미"),
    ("학생용 중성펜 0.38 검정 20개", "M-1000", "심천시문구유한공사"),
    ("젤펜 0.5mm 세트 10색", "GP-500", "동아연필"),
    ("유아용 원목 블록 완구 100피스", "BLK-100", "우드토이"),
    ("아동용 백팩", "A1", "가방나라"),
    ("무선 마우스", "1000", "로지텍"),
]

# 진짜 일치. 조여도 이건 계속 RED 여야 한다.
TRUE_POSITIVE_PROBES = [
    ("블록완구", "MB-120S", None),
]


def back_check(records: list[RecallRecord], sample: int, seed: int):
    """리콜 원문에서 셀러 입력을 흉내 낸 뒤 그 리콜을 다시 찾는가.

    같은 문자열로 되찾는 것이라 상한이 100% 다. 여기서 떨어지는 만큼이
    규칙을 조여서 잃는 진짜 일치다.
    """
    usable = [r for r in records if wl._recall_models(r)]
    rng = random.Random(seed)
    rng.shuffle(usable)
    return usable[:sample]


def cmd_eval(args) -> int:
    records = load_records()
    print(f"리콜 사본 {len(records):,d}건\n")

    print("=== 오탐 — 무관한 상품이 '확인된 문제' 로 잡히는가 ===")
    fp_total = 0
    for product, model, maker in FALSE_POSITIVE_PROBES:
        item = probe_item(product, model, maker)
        hits = [(r, m) for r in records if (m := wl.match(item, r)) is not None]
        confirmed = [(r, m) for r, m in hits if m.strength in CONFIRMED]
        weak = len(hits) - len(confirmed)
        fp_total += len(confirmed)
        sample = ", ".join(sorted({(r.product_name or "?")[:14] for r, _ in confirmed})[:4])
        print(f"  {model:10s} {product[:22]:22s}  RED {len(confirmed):4d}  참고 {weak:4d}"
              + (f"   예: {sample}" if sample else ""))
    print(f"  합계 RED {fp_total}건\n")

    print("=== 재현율 — 진짜 일치를 계속 잡는가 ===")
    for product, model, maker in TRUE_POSITIVE_PROBES:
        item = probe_item(product, model, maker)
        hits = [(r, m) for r in records if (m := wl.match(item, r)) is not None]
        confirmed = [m for _, m in hits if m.strength in CONFIRMED]
        print(f"  {model:10s} RED {len(confirmed)}건 / 전체 {len(hits)}건")

    picked = back_check(records, args.sample, args.seed)
    tiers: Counter = Counter()
    for r in picked:
        model = (r.model_name or "").split(",")[0].strip()
        item = probe_item(r.product_name or "상품", model, r.maker)
        m = wl.match(item, r)
        tiers[m.strength.value if m else "miss"] += 1
    n = sum(tiers.values())
    hit = tiers["exact"] + tiers["strong"]
    print(f"\n  역검증 {n:,d}건 (리콜 원문 모델명으로 그 리콜 되찾기)")
    print(f"    확인된 문제로 되찾음 {hit:,d} ({hit/n:6.2%})")
    for k in ("exact", "strong", "weak", "miss"):
        print(f"      {k:6s} {tiers[k]:5d} ({tiers[k]/n:6.2%})")

    if tiers["weak"] or tiers["miss"]:
        print("\n  RED 에서 빠진 역검증 예시")
        shown = 0
        for r in picked:
            if shown >= 10:
                break
            model = (r.model_name or "").split(",")[0].strip()
            item = probe_item(r.product_name or "상품", model, r.maker)
            m = wl.match(item, r)
            if m is None or m.strength not in CONFIRMED:
                tier = m.strength.value if m else "miss"
                print(f"    [{tier:5s}] 모델 {model[:24]!r:26s} 제품 {(r.product_name or '')[:24]}")
                shown += 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trace")
    t.add_argument("product")
    t.add_argument("--model", default=None)
    t.add_argument("--maker", default=None)
    t.set_defaults(fn=cmd_trace)

    e = sub.add_parser("eval")
    e.add_argument("--sample", type=int, default=3000)
    e.add_argument("--seed", type=int, default=20260901)
    e.set_defaults(fn=cmd_eval)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
