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

    # 설정만 보고 "LLM 모드" 라고 적으면 안 된다. 키가 400 을 돌려주던 때
    # 11건 전부 폴백됐는데도 리포트는 LLM 이라고 표시했다.
    #
    # 출력 모양으로 추론하는 것도 안 된다. LLM 이 정직하게 product_name=None 을
    # 내거나 상품명이 마침 첫 줄과 같으면 휴리스틱으로 오인된다 - 실제로 11건
    # 중 4건을 그렇게 오탐했다. 추출기가 직접 센 값을 읽는다.
    from sourcing_guard.extractor import stats as ex_stats

    ex_stats.reset()

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
    from sourcing_guard.config import settings

    configured = not settings.mock_mode and bool(settings.anthropic_api_key)
    llm_ok = ex_stats.llm
    if llm_ok:
        mode = f"LLM ({settings.extractor_model}) — 호출 성공 {llm_ok}/{len(CASES)}건"
    elif configured:
        mode = "휴리스틱 (LLM 호출이 전부 실패해 폴백됨)"
    else:
        mode = "휴리스틱 (키 없음 또는 MOCK_MODE)"

    print(f"\n추출 모드   {mode}")
    print(f"표본 {len(CASES)}건 (전부 KC 번호 없음 — 구매대행 소싱 상황)")

    if ex_stats.llm_failures:
        print(f"\n⚠ {ex_stats.llm_failures}건이 LLM 호출 실패로 휴리스틱에 떨어졌습니다. 로그를 확인하세요.")
    elif llm_ok and llm_ok < len(CASES):
        print(f"\n※ {len(CASES) - llm_ok}건은 상한·설정으로 휴리스틱을 썼습니다(호출 실패 아님).")
    elif configured and not llm_ok:
        print("\n⚠ 키가 설정돼 있는데 LLM 호출이 한 건도 성공하지 못했습니다.")
        print("  아래 수치는 전부 휴리스틱 결과입니다. 로그에서 원인을 확인하세요.")
    elif not configured:
        print("\n※ ANTHROPIC_API_KEY 설정 + MOCK_MODE=false 로 다시 돌리면 LLM 정확도가 나옵니다.")
        print("  두 수치의 차이가 'AI 를 왜 쓰는가' 의 답입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
