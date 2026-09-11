#!/usr/bin/env python
"""[H] 구조 필드 어댑터 측정 — 190건(대상 109) · LLM 0회 · 네트워크 0회.

    PYTHONPATH=. python -u scripts/measure_h_adapter.py

재는 것
    1. 어댑터 필드 채움률  product_name · model · maker · kc_numbers · materials · target_age
    2. 값 아닌 값을 거른 수  "해당없음" · "상세설명참조" · "-"  (R3)
    3. infoDuty.type ↔ 등급표 품목명 겹침  (지시의 ⚠ - 매핑하지 않는다는 근거)
    4. 어댑터 vs LLM(AB detail.facts) 대조 - 같은 109건에서 kc_numbers · model · maker 가 같은가.
       ⚠ 어느 쪽이 맞는지는 모른다. 갈리는 줄을 검수용으로 뽑는다.

⚠ 라벨: **구조 필드 · 어댑터 · LLM 0회 · 표본 190 (대상 109) · 검수 없음.**
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.domeggook_adapter import NOT_A_VALUE, facts_from_item, infoduty_type  # noqa: E402
from sourcing_guard.domeggook_fields import is_placeholder  # noqa: E402
from sourcing_guard.item_grades import ALIASES, ItemGradeBook  # noqa: E402
from sourcing_guard.kats_client import normalize_kc  # noqa: E402

LABEL = "구조 필드 · 어댑터 · LLM 0회 · 표본 190 (대상 109) · 검수 없음"


def load_items(paths: list[Path]) -> dict[str, dict]:
    """정제본 `[{nos, response}]` → {상품번호: item}."""
    out: dict[str, dict] = {}
    for p in paths:
        if not p.exists():
            continue
        for entry in json.loads(p.read_text(encoding="utf-8")):
            root = (entry.get("response") or {}).get("domeggook") or entry.get("response") or {}
            items = root.get("item")
            for it in (items if isinstance(items, list) else [items]):
                if isinstance(it, dict):
                    no = str((it.get("basis") or {}).get("no") or "")
                    if no:
                        out[no] = it
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="tests/fixtures/도매꾹_정제_2026-09-08")
    ap.add_argument("--expand", default="tests/fixtures/도매꾹_확장_2026-09-08")
    ap.add_argument("--struct", default="tests/fixtures/도매꾹_구조_2026-09-08.json")
    ap.add_argument("--ab", default="tests/fixtures/도매꾹_AB_2026-09-08.json")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    items = load_items([Path(args.base) / "상세.json", Path(args.expand) / "상세_확장.json"])
    struct = {str(s["도매꾹_상품번호"]): s for s in json.loads(Path(args.struct).read_text(encoding="utf-8"))["상품"]}
    # ⚠ AB 의 `no` 는 **표본 행 번호**(1~235)이고 도매꾹 상품번호가 아니다. 처음에 상품번호로
    #   조인해 0건이 나왔다. 구조 JSON 의 `표본_상품명` 과 AB 의 `name` 이 같은 문자열이다.
    ab = {r["name"]: r for r in json.loads(Path(args.ab).read_text(encoding="utf-8"))["행"]}
    book = ItemGradeBook()
    today = f"{date.today():%Y-%m-%d}"

    nos = [no for no in struct if no in items]
    print(f"{LABEL} · 구조 {len(struct)} · 정제본에서 찾음 {len(nos)}", flush=True)

    fill = collections.Counter(); filtered = collections.Counter(); types = collections.Counter()
    by_cls = collections.defaultdict(collections.Counter)
    disagree = []
    agree = collections.Counter(); compared = 0
    for no in nos:
        it = items[no]; cls = struct[no]["대상분류"]
        det = it.get("detail") or {}
        # 값 아닌 값 (필터 전 원값 기준)
        for k in ("model", "manufacturer"):
            raw = str(det.get(k) or "").strip()
            key = re.sub(r"\s+", "", raw).lower()
            if raw and key in NOT_A_VALUE: filtered[(k, "해당없음류")] += 1
            elif raw and is_placeholder(raw): filtered[(k, "placeholder")] += 1
            elif raw == "-": filtered[(k, "-")] += 1
        f = facts_from_item(it)
        for k in ("product_name", "model_name", "maker", "target_age"):
            if getattr(f, k): fill[k] += 1; by_cls[cls][k] += 1
        if f.kc_numbers: fill["kc_numbers"] += 1; by_cls[cls]["kc_numbers"] += 1
        if f.materials: fill["materials"] += 1; by_cls[cls]["materials"] += 1
        types[infoduty_type(it) or "(없음)"] += 1
        # LLM 대조 (대상 109 만 AB 에 있다)
        r = ab.get(struct[no]["표본_상품명"])
        if r and (r.get("detail") or {}).get("facts"):
            compared += 1
            lf = r["detail"]["facts"]
            a_kc = {normalize_kc(x) for x in f.kc_numbers}; l_kc = {normalize_kc(x) for x in (lf.get("kc_numbers") or [])}
            same_kc = a_kc == l_kc
            same_model = (f.model_name or "").strip() == (lf.get("model_name") or "").strip()
            same_maker = (f.maker or "").strip() == (lf.get("maker") or "").strip()
            agree["kc"] += same_kc; agree["model"] += same_model; agree["maker"] += same_maker
            if (lf.get("model_name") or "").strip() in ("해당없음", "-"): agree["llm_model_해당없음"] += 1
            if not (same_kc and same_model and same_maker):
                disagree.append((no, struct[no]["도매꾹_상품명"][:40],
                                 sorted(a_kc), sorted(l_kc), f.model_name, lf.get("model_name"), f.maker, lf.get("maker")))

    overlap = sum(c for t, c in types.items() if book.names_an_item(t))
    strip = lambda s: re.sub(r"\(.*?\)", "", s).strip()
    overlap2 = sum(c for t, c in types.items() if book.names_an_item(strip(t)))
    n = len(nos)

    doc = [
        f"# [H] 도매꾹 구조 필드 → ProductFacts 어댑터 — 측정 {today}",
        "",
        f"⚠ 라벨: **{LABEL}**.",
        "",
        "## 1. 어댑터 필드 채움률 (LLM 0회 · 값 아닌 값은 뺀 뒤)",
        f"    표본 {n} (대상 {sum(1 for x in nos if struct[x]['대상분류']=='대상')} · 비대상 {sum(1 for x in nos if struct[x]['대상분류']=='비대상')} · 애매 {sum(1 for x in nos if struct[x]['대상분류']=='애매')})",
        *[f"    {k:13} {fill[k]:4} / {n}  ({fill[k]/n*100:5.1f}%)   대상 {by_cls['대상'][k]:3} · 비대상 {by_cls['비대상'][k]:3} · 애매 {by_cls['애매'][k]:3}"
          for k in ("product_name", "model_name", "maker", "kc_numbers", "materials", "target_age")],
        "",
        "## 2. 값 아닌 값을 거른 수 (R3) — 그대로 넘겼으면 그 값으로 리콜 대조를 했다",
        *[f"    {k:13} {why:10} {c:4}" for (k, why), c in sorted(filtered.items())],
        "",
        "## 3. infoDuty.type(고시 품목분류) ↔ 등급표 품목명 — **매핑하지 않는 근거**",
        f"    종류 {len(types)} · 등급표 품목명과 같은 상품 {overlap} / {n} · 괄호 제거 후 {overlap2} / {n}",
        *[f"    {c:4}  {t}{'   ← 등급표 품목명' if book.names_an_item(t) else ''}" for t, c in types.most_common(12)],
        "    고시 품목분류는 전안법 품목군이 아니다. 어댑터는 legal_item_name 을 항상 None 으로 둔다.",
        "",
        "## 4. 어댑터 vs LLM(AB · 상세 조건) — 같은 상품에서 같은 값을 뽑았나",
        f"    대조 {compared}건 · kc_numbers 일치 {agree['kc']} · model 일치 {agree['model']} · maker 일치 {agree['maker']}",
        f"    LLM 이 model_name 에 '해당없음'/'-' 를 넣은 줄: {agree['llm_model_해당없음']}   ← LLM 경로의 같은 구멍",
        "    ⚠ 어느 쪽이 맞는지는 모른다. 갈리는 줄은 아래 - 검수 대상.",
        "",
        "| no | 상품 | 어댑터 kc | LLM kc | 어댑터 model | LLM model | 어댑터 maker | LLM maker |",
        "|---|---|---|---|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} | {e} | {f_} | {g} | {h} |" for a, b, c, d, e, f_, g, h in disagree[:40]],
        f"",
        f"갈리는 줄 {len(disagree)} / {compared} (표는 40개까지)",
    ]
    out = Path(args.out or f"docs/H_구조필드_어댑터_{today}.md")
    out.write_text("\n".join(doc) + "\n", encoding="utf-8")
    print("\n".join(doc[:34]))
    print(f"\n갈리는 줄 {len(disagree)} / {compared} · 저장 → {out}")


if __name__ == "__main__":
    main()
