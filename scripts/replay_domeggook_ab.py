#!/usr/bin/env python
"""A-5 의 두 조건을 **저장된 추출 결과로 재생**한다. LLM 0회.

`도매꾹_AB_2026-09-08.json` 은 각 상품을 두 조건(상품명만 / 상세)으로 스캔한
전체 응답을 담고 있다. 그 안의 `facts` 를 `ProductFacts` 로 되돌려 verifier·
scorer 만 다시 돌리면, **추출을 다시 하지 않고** 결정론 코드 변경의 효과를
잰다 (R7: 추출기를 바꾸면 235 를 다시 재야 하지만, verifier·scorer 변경은
재생으로 된다).

⚠ **A-5 보고서 숫자와 직접 비교하지 말 것.** 저쪽은 **배포본**에서 잰 것이고
  이것은 **로컬 재생**이다. 리콜 색인 동기화 시점·KATS 캐시가 달라 절대값이
  어긋날 수 있다. 그래서 이 스크립트는 항상 **두 조건을 같은 실행에서** 재고,
  비교는 "같은 실행 안의 변경 전 대비 변경 후" 로만 한다.

⚠ 네트워크를 쓴다 — KATS 인증 조회(safetykorea.kr)와 전파 조회(emsit). 둘 다
  R4 승인 호스트다. 인증번호는 28개 정도이고 캐시가 앞에 있다. LLM 은 부르지
  않는다.

⚠ 리콜·부적합 색인은 로컬 SQLite(`data/watchlist.db`)에서 온다. 그 DB 가 없거나
  비어 있으면 리콜 축이 통째로 조용해지므로, 건수를 먼저 찍고 0 이면 멈춘다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.config import settings  # noqa: E402
from sourcing_guard.kats_client import KatsClient  # noqa: E402
from sourcing_guard.models import ItemCategory, ProductFacts  # noqa: E402
from sourcing_guard.noncompliant_index import NoncompliantIndex  # noqa: E402
from sourcing_guard.recall_index import RecallIndex  # noqa: E402
from sourcing_guard.rra_client import RraClient  # noqa: E402
from sourcing_guard.scorer import score  # noqa: E402
from sourcing_guard.storage import SqliteWatchStore  # noqa: E402
from sourcing_guard.verifier import RuleBook, split_cert_regimes, verify  # noqa: E402

_AB = Path("tests/fixtures/도매꾹_AB_2026-09-08.json")
_DETAIL = Path("tests/fixtures/도매꾹_상세텍스트_2026-09-08.txt")
_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")

_FACT_KEYS = (
    "product_name", "model_name", "maker", "materials", "substances_mentioned",
    "kc_numbers", "kc_numbers_from_image", "rf_numbers", "wireless_hints",
    "target_age", "legal_item_name", "source_page_url", "raw_language",
)


def facts_from(stored: dict) -> ProductFacts:
    """저장된 facts dict → ProductFacts. 모르는 키는 버린다."""
    data = {k: stored.get(k) for k in _FACT_KEYS if stored.get(k) is not None}
    try:
        data["category"] = ItemCategory(stored.get("category") or "unclassified")
    except ValueError:
        data["category"] = ItemCategory.UNCLASSIFIED
    try:
        return ProductFacts(**data)
    except Exception:
        return ProductFacts(product_name=stored.get("product_name"),
                            category=data["category"])


def load_audit():
    sys.path.insert(0, "scripts")
    from audit_tally import load_audit as _la, load_scope as _ls

    return _ls(), _la()


def candidates(findings) -> list[str]:
    return [c["item"] for f in findings
            for c in (f.detail or {}).get("candidates", [])]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(_AB))
    ap.add_argument("--detail", default=str(_DETAIL))
    ap.add_argument("--label", required=True,
                    help='예: "변경 전 (7bcd492)" — 숫자에 붙일 라벨')
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    payload = json.loads(Path(args.src).read_text(encoding="utf-8"))
    rows = payload["행"]
    scope, (wrong, vague) = load_audit()

    # ⚠ **`raw_text` 를 반드시 넘긴다.** 배포본 scan() 이 `raw_text=req.page_text`
    #   를 넘기고, 표지어 게이트(어린이·합성수지·전원)가 그것을 본다. 안 넘기면
    #   같은 facts 로도 매칭이 줄어든다 - 실측: 상세 조건 정답 84 → 79.
    sys.path.insert(0, "scripts")
    from measure_domeggook_ab import split_details

    detail_text = split_details(Path(args.detail))

    store = SqliteWatchStore(settings.watchlist_db_path)
    recalls = RecallIndex(store)
    noncompliant = NoncompliantIndex(store)
    kats = KatsClient(settings.kats_base_url, settings.kats_service_key,
                      mock=settings.mock_mode)
    rra = RraClient(mock=settings.mock_mode)
    rules = RuleBook()
    today = date.today()

    n_dom = len(recalls.domestic) if hasattr(recalls, "domestic") else -1
    print(f"라벨: {args.label}")
    print(f"원자료: {args.src} · {len(rows)}행 × 2조건")
    print(f"리콜 색인: as_of={recalls.as_of} · 부적합 비어있나={noncompliant.is_empty()}")
    if noncompliant.is_empty():
        print("⚠ 부적합 색인이 비었다 - RF_NONCOMPLIANT 축이 조용해진다.")
    print(f"KATS mock={kats._mock} · RRA mock={rra._mock}\n")

    out_rows = []
    for cond in ("name_only", "detail"):
        tallies = {
            "matched": 0, "ok": 0, "vague": 0, "wrong": 0,
            "kc": 0, "rf": 0, "kc_verified": 0, "kc_revoked": 0,
            "kc_expired": 0, "kc_not_found": 0, "rf_not_found": 0,
            "recall_match": 0, "out_of_scope": 0,
        }
        signals: Counter = Counter()
        red_rows: list[tuple[int, str, list[str]]] = []
        per_row = {}
        for r in rows:
            stored = (r[cond] or {}).get("facts") or {}
            facts = split_cert_regimes(facts_from(stored))
            raw = r["name"] if cond == "name_only" else detail_text.get(r["no"], "")
            findings = verify(facts, kats, rules, recalls, rra, noncompliant,
                              raw_text=raw)
            res = score(facts, findings, recall_data_as_of=recalls.as_of,
                        today=today)
            items = candidates(findings)
            kinds = Counter(f.kind.value for f in findings)
            name = r["name"]
            if items:
                tallies["matched"] += 1
                if name in wrong:
                    tallies["wrong"] += 1
                elif name in vague:
                    tallies["vague"] += 1
                else:
                    tallies["ok"] += 1
            if facts.kc_numbers:
                tallies["kc"] += 1
            if facts.rf_numbers:
                tallies["rf"] += 1
            for key, kind in (("kc_verified", "kc_verified"),
                              ("kc_revoked", "kc_revoked"),
                              ("kc_expired", "kc_expired"),
                              ("kc_not_found", "kc_not_found"),
                              ("rf_not_found", "rf_cert_not_found"),
                              ("recall_match", "recall_match"),
                              ("out_of_scope", "out_of_scope")):
                tallies[key] += kinds.get(kind, 0)
            signals[res.signal.value] += 1
            if res.signal.value == "RED":
                red_rows.append((r["no"], name, sorted(
                    f.kind.value for f in findings if f.signal.value == "RED")))
            per_row[r["no"]] = {
                "signal": res.signal.value, "items": items,
                "kc": list(facts.kc_numbers), "rf": list(facts.rf_numbers),
                "kinds": dict(kinds),
            }
        label = "상품명만" if cond == "name_only" else "상세"
        n = len(rows)
        print(f"[{label}]  n={n}")
        print(f"  품목 매칭   정답 {tallies['ok']} · 애매 {tallies['vague']}"
              f" · 오답 {tallies['wrong']} · 미매칭 {n - tallies['matched']}")
        print(f"  kc 있는 행 {tallies['kc']} · rf 있는 행 {tallies['rf']}")
        print(f"  kc_verified {tallies['kc_verified']}"
              f" · revoked {tallies['kc_revoked']}"
              f" · expired {tallies['kc_expired']}"
              f" · not_found {tallies['kc_not_found']}")
        print(f"  rf_cert_not_found {tallies['rf_not_found']}"
              f" · recall_match {tallies['recall_match']}"
              f" · out_of_scope {tallies['out_of_scope']}")
        print(f"  신호등 {dict(signals)}")
        if red_rows:
            print(f"  RED {len(red_rows)}건")
            for no, name, kinds_red in red_rows:
                print(f"    [{no:>3}] {name[:40]:<42} {kinds_red}")
        print()
        out_rows.append({"조건": label, "집계": tallies,
                         "신호등": dict(signals),
                         "RED": [{"no": no, "name": nm, "kinds": k}
                                 for no, nm, k in red_rows],
                         "행별": per_row})

    if args.out:
        Path(args.out).write_text(
            json.dumps({"라벨": args.label, "원자료": args.src,
                        "리콜_as_of": recalls.as_of, "조건별": out_rows},
                       ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"원자료 → {args.out}")


if __name__ == "__main__":
    main()
