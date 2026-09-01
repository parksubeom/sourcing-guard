#!/usr/bin/env python3
"""골든셋 정확도 리포트.

    python scripts/golden_report.py

발표 자료용 숫자를 뽑는다. 추출 필드별 정확도와 신호 일치율을 낸다.
휴리스틱 모드(키 없음)와 LLM 모드(ANTHROPIC_API_KEY 있음)를 자동 선택한다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sourcing_guard.extractor import extract
from sourcing_guard.kats_client import KatsClient
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify

ROOT = Path(__file__).resolve().parent.parent
CASES = yaml.safe_load((ROOT / "tests/golden/golden_set.yaml").read_text(encoding="utf-8"))["cases"]
KATS = KatsClient(None, None, mock=True)
RULES = RuleBook()


def main() -> int:
    sig_hit = find_hit = ext_hit = 0
    sig_tot = find_tot = ext_tot = 0
    rows = []

    for c in CASES:
        facts = extract(c["text"])
        findings = verify(facts, KATS, RULES, None)
        result = score(facts, findings)
        kinds = {f.kind.value for f in findings}
        exp = c["expect"]

        s_ok = f_ok = e_ok = True
        if "signal" in exp:
            sig_tot += 1
            s_ok = result.signal.value.lower() == exp["signal"].lower()
            sig_hit += s_ok
        for k in exp.get("must_find", []):
            find_tot += 1
            hit = k in kinds
            find_hit += hit
            f_ok &= hit
        for t in exp.get("must_extract", []):
            ext_tot += 1
            hay = " ".join(facts.materials + facts.substances_mentioned + facts.kc_numbers)
            hit = t in hay
            ext_hit += hit
            e_ok &= hit

        mark = "OK" if (s_ok and f_ok and e_ok) else "XX"
        rows.append(f"  [{mark}] {c['id']:20s} {result.signal.value.lower()}")

    print("골든셋 정확도 리포트")
    print("=" * 44)
    print("\n".join(rows))
    print("=" * 44)
    if sig_tot:
        print(f"신호 일치     {sig_hit}/{sig_tot}  ({100*sig_hit//sig_tot}%)")
    if find_tot:
        print(f"finding 적중  {find_hit}/{find_tot}  ({100*find_hit//find_tot}%)")
    if ext_tot:
        print(f"추출 적중     {ext_hit}/{ext_tot}  ({100*ext_hit//ext_tot}%)")
    print(f"\n표본 {len(CASES)}건 (전부 KC 번호 없음 — 구매대행 소싱 상황)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
