#!/usr/bin/env python
"""[E-2] 유효 결과율의 **첫 눈금**을 재생 경로에서 읽는다. LLM 0회.

무엇을 세나
-----------
`has_specific_finding()` — "이 상품에 대해 구체적인 것을 하나라도 말했나".
매칭률과 다른 지표다. 매칭이 올라도 화면이 "확인 필요" 세 줄뿐이면 셀러에게
준 것이 없다.

⚠⚠ **이 값은 `재생값` 이고 `/healthz` 의 `results.rate` 는 `런타임값` 이다.**
  이름이 같으니 문서에서 반드시 갈라 적을 것:

      재생값    저장된 추출 결과 + 지금 코드. 표본이 고정이고 재현된다.
      런타임값  프로세스가 실제로 처리한 스캔. 실트래픽이지만 누적이고 휘발성.

  **실트래픽이 아니다.** 새표본235 는 우리가 모은 상품명이고 상세 109 는 도매꾹
  실상품이지만 우리가 고른 것이다. 첫 눈금이지 사용 통계가 아니다.

⚠ 기획서·랜딩에 넣지 않는다. `docs/` 보고서로만 남긴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sourcing_guard.models import ItemCategory, ProductFacts  # noqa: E402
from sourcing_guard.scorer import has_specific_finding  # noqa: E402
from sourcing_guard.verifier import RuleBook, split_cert_regimes, verify  # noqa: E402

_CLAUDE = Path("tests/fixtures/단건경로_claude_235.json")
_AB = Path("tests/fixtures/도매꾹_AB_2026-09-08.json")
_DETAIL = Path("tests/fixtures/도매꾹_상세텍스트_2026-09-08.txt")


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:5.1f}%" if whole else "    -"


def _kinds_left(findings) -> list[str]:
    """유효 결과가 0 일 때 **무엇이 남았나.** 어느 축이 비어 침묵하는지 보인다."""
    return sorted({f.kind.value for f in findings})


# ── ⓐ 새표본235 · 상품명만 ─────────────────────────────────────────
def measure_new_sample(src: Path) -> dict:
    from audit_tally import load_scope

    scope = load_scope()
    rows = json.loads(src.read_text(encoding="utf-8"))
    # ⚠ 네트워크 0회. 인증 축은 이 원자료에 인증번호가 없어 애초에 비어 있다.
    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = RuleBook()

    buckets: dict[str, dict] = {
        k: {"n": 0, "specific": 0, "silent": []} for k in ("대상", "비대상", "애매")
    }
    for r in rows:
        name = r["name"]
        cls = scope.get(name)
        if cls not in buckets:
            continue
        try:
            category = ItemCategory(r.get("category") or "unclassified")
        except ValueError:
            category = ItemCategory.UNCLASSIFIED
        facts = ProductFacts(
            product_name=r.get("product_name") or None,
            category=category,
            legal_item_name=r.get("legal") or None,
        )
        findings = verify(facts, kats, rules, raw_text=name)
        b = buckets[cls]
        b["n"] += 1
        if has_specific_finding(findings):
            b["specific"] += 1
        else:
            b["silent"].append((name, _kinds_left(findings)))
    return buckets


# ── ⓑ 상세 109 · 두 조건 ────────────────────────────────────────────
def measure_domeggook(src: Path, detail: Path) -> dict:
    from measure_domeggook_ab import split_details
    from replay_domeggook_ab import facts_from

    from sourcing_guard.config import settings
    from sourcing_guard.kats_client import KatsClient
    from sourcing_guard.noncompliant_index import NoncompliantIndex
    from sourcing_guard.recall_index import RecallIndex
    from sourcing_guard.rra_client import RraClient
    from sourcing_guard.storage import SqliteWatchStore

    rows = json.loads(src.read_text(encoding="utf-8"))["행"]
    detail_text = split_details(detail)

    store = SqliteWatchStore(settings.watchlist_db_path)
    recalls = RecallIndex(store)
    noncompliant = NoncompliantIndex(store)
    kats = KatsClient(settings.kats_base_url, settings.kats_service_key,
                      mock=settings.mock_mode)
    rra = RraClient(mock=settings.mock_mode)
    rules = RuleBook()
    today = date.today()

    print(f"  리콜 색인 as_of={recalls.as_of} · 부적합 비어있나={noncompliant.is_empty()}")
    print(f"  KATS mock={kats._mock} · RRA mock={rra._mock}")
    if recalls.is_empty():
        print("  ⚠ 리콜 색인이 비었다 - 리콜 축이 통째로 조용해진다. 값을 쓰지 말 것.")

    out: dict[str, dict] = {}
    for cond in ("name_only", "detail"):
        n = specific = 0
        silent: list[tuple[int, str, list[str]]] = []
        axis: Counter = Counter()
        for r in rows:
            stored = (r[cond] or {}).get("facts") or {}
            facts = split_cert_regimes(facts_from(stored))
            raw = r["name"] if cond == "name_only" else detail_text.get(r["no"], "")
            findings = verify(facts, kats, rules, recalls, rra, noncompliant,
                              raw_text=raw)
            n += 1
            if has_specific_finding(findings):
                specific += 1
                # 어느 축이 값을 만들었나 - 상세 조건의 이득을 축별로 본다.
                for f in findings:
                    from sourcing_guard.models import SPECIFIC_FINDING_KINDS
                    if f.kind in SPECIFIC_FINDING_KINDS:
                        axis[f.kind.value] += 1
            else:
                silent.append((r["no"], r["name"], _kinds_left(findings)))
        out[cond] = {"n": n, "specific": specific, "silent": silent, "axis": axis}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(_CLAUDE))
    ap.add_argument("--ab", default=str(_AB))
    ap.add_argument("--detail", default=str(_DETAIL))
    ap.add_argument("--max-silent", type=int, default=20)
    ap.add_argument("--skip-domeggook", action="store_true")
    args = ap.parse_args()

    print("유효 결과율 · **재생** · LLM 0회")
    print("⚠ 실트래픽이 아니다. /healthz 의 런타임값과 이름만 같다.\n")

    print("=" * 68)
    print(f"ⓐ 새표본235 · 상품명만 · 원자료 {args.src}")
    print("=" * 68)
    buckets = measure_new_sample(Path(args.src))
    total_n = sum(b["n"] for b in buckets.values())
    total_s = sum(b["specific"] for b in buckets.values())
    print(f"  전체            {total_s:3}/{total_n:3} = {_pct(total_s, total_n)}")
    for cls in ("대상", "비대상", "애매"):
        b = buckets[cls]
        note = ""
        if cls == "비대상":
            note = "   ← 낮은 것이 정상이다 (안 붙이는 게 맞는 줄)"
        elif cls == "대상":
            note = "   ← 낮으면 문제다"
        print(f"  {cls:4}          {b['specific']:3}/{b['n']:3} = {_pct(b['specific'], b['n'])}{note}")

    silent = buckets["대상"]["silent"]
    print(f"\n  유효 결과 0 인 **대상** 상품 {len(silent)}건"
          f" (최대 {args.max_silent}건 표시)")
    print("  ⚠ 남는 finding 이 어느 축이 비어 침묵하는지 말해 준다.")
    for name, kinds in silent[: args.max_silent]:
        print(f"     {name[:46]:48} {kinds}")
    if len(silent) > args.max_silent:
        print(f"     … 그 밖 {len(silent) - args.max_silent}건")
    left = Counter(k for _n, ks in silent for k in ks)
    print("\n  침묵한 줄에 남은 finding 종류 (건수)")
    for k, c in left.most_common():
        print(f"     {c:4}  {k}")

    if args.skip_domeggook:
        return
    print()
    print("=" * 68)
    print(f"ⓑ 상세 109 · 두 조건 나란히 · 원자료 {args.ab}")
    print("=" * 68)
    ab = measure_domeggook(Path(args.ab), Path(args.detail))
    print()
    for cond, label in (("name_only", "상품명만"), ("detail", "상세")):
        d = ab[cond]
        print(f"  [{label:4}]  {d['specific']:3}/{d['n']:3} = {_pct(d['specific'], d['n'])}")
    gain = ab["detail"]["specific"] - ab["name_only"]["specific"]
    print(f"\n  상세가 올린 것: **+{gain}건** "
          f"({_pct(ab['name_only']['specific'], ab['name_only']['n']).strip()}"
          f" → {_pct(ab['detail']['specific'], ab['detail']['n']).strip()})")
    print("  ⚠ A-5 가 인증 축을 살린 이득이 이 한 숫자다.")

    print("\n  값을 만든 축 (구체적 finding 건수 · 조건별)")
    keys = sorted(set(ab["name_only"]["axis"]) | set(ab["detail"]["axis"]))
    print(f"     {'finding':28} {'상품명만':>8} {'상세':>6}")
    for k in keys:
        a = ab["name_only"]["axis"].get(k, 0)
        b = ab["detail"]["axis"].get(k, 0)
        mark = "  ←" if b > a else ""
        print(f"     {k:28} {a:8} {b:6}{mark}")

    ds = ab["detail"]["silent"]
    print(f"\n  상세 조건에서도 유효 결과 0 인 상품 {len(ds)}건"
          f" (최대 {args.max_silent}건)")
    for no, name, kinds in ds[: args.max_silent]:
        print(f"     [{no:3}] {name[:42]:44} {kinds}")
    if len(ds) > args.max_silent:
        print(f"     … 그 밖 {len(ds) - args.max_silent}건")


if __name__ == "__main__":
    main()
