#!/usr/bin/env python
"""[⑦-a] 전파 적합성평가 **대상기자재 표**(별표 1)를 받아 원자료로 남긴다.

    python scripts/probe_rf_target_equipment.py

⚠ 실호출한다. 정기 실행이 아니라 **자료 수집 1회**다 - `law.go.kr` 은 R4 표에
  "고시·별표·부속서 원문 (DRF OpenAPI)" 로 승인돼 있다.

⚠⚠ **ID 는 `행정규칙일련번호` 다** (2100000282888). `행정규칙ID`(38724)를 넣으면
  "없습니다" 가 온다. 총괄이 확인한 값이고 응답 기본정보로 다시 확인한다.

⚠⚠ **별표는 번호가 아니라 제목으로 고른다.** 고시가 개정되면 번호가 밀린다.
  실제로 이 응답에는 별표가 30개 있고 `별표번호 0001` 이 **둘**이다
  (별표 1 과 서식 1) - 번호로 고르면 서식을 집는다.

⚠ 간헐적 connection reset 이 난다. 세 번까지 3초 간격으로 다시 건다.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sourcing_guard.allowed_hosts import ensure_allowed  # noqa: E402

DETAIL = "https://www.law.go.kr/DRF/lawService.do"

#: 총괄 확인값 (2026-09-14). 시행 20260724 · 국립전파연구원.
ADMRUL_SEQ = "2100000282888"

#: **번호가 아니라 이것으로 고른다.**
TITLE = "적합성평가 대상기자재(제3조 관련)"

OUT_DIR = Path("tests/fixtures")


def fetch(seq: str = ADMRUL_SEQ, *, tries: int = 3, gap: float = 3.0) -> dict:
    last: Exception | None = None
    ensure_allowed(DETAIL)
    for attempt in range(1, tries + 1):
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as c:
                r = c.get(DETAIL, params={"OC": "test", "target": "admrul",
                                          "type": "JSON", "ID": seq})
            r.raise_for_status()
            return r.json()
        except Exception as exc:                      # noqa: BLE001 - 무엇이든 다시 건다
            last = exc
            print(f"  재시도 {attempt}/{tries}: {type(exc).__name__} {str(exc)[:80]}")
            if attempt < tries:
                time.sleep(gap)
    raise SystemExit(f"세 번 다 실패했습니다: {last!r}")


def pick(doc: dict, title: str = TITLE) -> dict:
    units = doc["AdmRulService"]["별표"]["별표단위"]
    units = units if isinstance(units, list) else [units]
    hit = [u for u in units if (u.get("별표제목") or "").strip() == title]
    if len(hit) != 1:
        titles = [u.get("별표제목") for u in units][:12]
        raise SystemExit(
            f"제목 {title!r} 로 고른 별표가 {len(hit)}개입니다. 고시가 바뀌었을 수 "
            f"있습니다 - 앞쪽 제목들: {titles}"
        )
    return hit[0]


def main() -> int:
    doc = fetch()
    info = doc["AdmRulService"]["행정규칙기본정보"]
    print(f"행정규칙 {info['행정규칙명']}")
    print(f"  일련번호 {info['행정규칙일련번호']} · ID {info['행정규칙ID']}")
    print(f"  시행 {info['시행일자']} · 발령 {info['발령번호']} · "
          f"소관 {info['소관부처명']} · 현행 {info['현행여부']}")
    if str(info["행정규칙일련번호"]) != ADMRUL_SEQ:
        return print("⚠ 일련번호가 요청과 다릅니다 - 확인하세요") or 1

    unit = pick(doc)
    lines = unit["별표내용"]
    lines = lines[0] if lines and isinstance(lines[0], list) else lines
    print(f"\n별표 {unit['별표번호']}({unit['별표구분']}) {unit['별표제목']!r}")
    print(f"  원문 {len(lines)}행")

    out = OUT_DIR / f"전파_대상기자재_고시_{date.today().isoformat()}.json"
    out.write_text(json.dumps({
        "받은날": date.today().isoformat(),
        "행정규칙명": info["행정규칙명"],
        "행정규칙일련번호": info["행정규칙일련번호"],
        "행정규칙ID": info["행정규칙ID"],
        "시행일자": info["시행일자"],
        "발령번호": info["발령번호"],
        "소관부처명": info["소관부처명"],
        "별표제목": unit["별표제목"],
        "별표번호": unit["별표번호"],
        "별표구분": unit["별표구분"],
        "별표서식파일링크": unit.get("별표서식파일링크"),
        "별표서식PDF파일링크": unit.get("별표서식PDF파일링크"),
        # ⚠ **원자료는 손대지 않는다.** 줄 하나도 고치지 않고 그대로 담는다 -
        #   파싱이 틀렸을 때 되짚을 곳이 여기뿐이다.
        "별표내용": lines,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  저장 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
