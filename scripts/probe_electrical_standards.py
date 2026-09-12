#!/usr/bin/env python
"""[I] 전기용품 안전기준 고시의 **구조**를 확인한다. 조사용 · law.go.kr DRF.

묻는 것은 하나다: **조문을 인용할 수 있는가.**

`hazard_rules.yaml` 은 룰마다 `clause`(조항)와 `source_url` 을 요구한다 (R5 · §5).
어린이·생활용품은 고시 본문에 부속서가 있어 인용할 수 있는데, 전기용품에서는
안 된다는 것을 이 스크립트가 보여준다.

⚠ 실호출한다. 정기 실행이 아니라 **조사용 1회**다 - `law.go.kr` 은 R4 표에
  "자료 수집 경로" 로 승인돼 있다. 받은 목록은 픽스처로 남기므로 문서는
  네트워크 없이 검사된다.

    SG_LIVE_NET=1 python scripts/probe_electrical_standards.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sourcing_guard.allowed_hosts import ensure_allowed  # noqa: E402

SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL = "https://www.law.go.kr/DRF/lawService.do"
OUT = Path("tests/fixtures/전기용품_안전기준_고시_2026-09-12.json")

#: 대조군. 우리 룰 21건이 실제로 이 고시의 부속서에서 나왔다.
CONTROL = "안전확인대상생활용품의 안전기준"


def _get(url: str, params: dict) -> dict:
    ensure_allowed(url)
    r = httpx.get(url, params=params, timeout=40.0)
    r.raise_for_status()
    return r.json()


def main() -> None:
    d = _get(SEARCH, {"OC": "test", "target": "admrul", "type": "JSON",
                      "query": "전기용품 안전기준", "display": "100", "page": "1"})
    root = d["AdmRulSearch"]
    rows = root["admrul"]
    elec = [x for x in rows if x["행정규칙명"].startswith("전기용품 안전기준(")]
    print(f"검색 총건수 {root['totalCnt']} · 「전기용품 안전기준(…)」 {len(elec)}건")

    # 구조 대조 - 전기용품 한 건 vs 생활용품 한 건.
    print("\n무엇이 다른가 (같은 DRF · 같은 target)")
    print(f"{'고시':<44} {'JSON':>10} {'조문내용':>8} {'별표':>6} 첨부")
    for name in (f"전기용품 안전기준(KC 60598-1)", CONTROL):
        hit = next(x for x in rows if x["행정규칙명"] == name)
        raw = httpx.get(DETAIL, params={"OC": "test", "target": "admrul",
                                        "type": "JSON",
                                        "ID": hit["행정규칙일련번호"]}, timeout=60.0)
        svc = raw.json()["AdmRulService"]
        att = svc.get("첨부파일") or {}
        names = att.get("첨부파일명") if isinstance(att, dict) else att
        print(f"{name:<44} {len(raw.content):>9,}B "
              f"{'있음' if svc.get('조문내용') else '**빈값**':>8} "
              f"{'있음' if svc.get('별표') else '없음':>6} "
              f"{names if isinstance(names, list) else names}")

    OUT.write_text(json.dumps({
        "만든것": "scripts/probe_electrical_standards.py",
        "받은날": f"{date.today():%Y-%m-%d}",
        "원천": "law.go.kr DRF lawSearch.do · target=admrul · query='전기용품 안전기준' · OC=test",
        "총건수": root["totalCnt"],
        "전기용품_안전기준_건수": len(elec),
        "⚠": "제3자 개인정보 없음 - 법령 고시 목록이다. 도매꾹 응답과 달리 마스킹 대상이 아니다.",
        "고시": [{"이름": x["행정규칙명"], "발령일자": x.get("발령일자"),
                  "일련번호": x.get("행정규칙일련번호"), "종류": x.get("행정규칙종류")}
                 for x in elec],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
