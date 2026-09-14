#!/usr/bin/env python
"""[⑦-c] 유아용·아동용 섬유제품 부속서의 **적용범위**를 원문으로 읽는다.

    python scripts/probe_child_textile_scope.py

⚠ 실호출한다. 정기 실행이 아니라 **자료 수집 1회**다 - `law.go.kr` 은 R4 표에
  "고시·별표·부속서 원문 (DRF OpenAPI)" 로 승인돼 있다.

왜 필요한가 (CLAUDE.md R5-b)
---------------------------
「안전기준준수대상생활용품의 안전기준」 부속서 1(가정용 섬유제품)의 적용범위
첫 문장이 **"유아용 및 아동용 섬유제품을 제외한 만 14세 이상의"** 다. 그런데
우리 표에서 「유아용 섬유제품」은 **안전확인**, 「아동용 섬유제품」은
**공급자적합성확인** 이다 - 등급이 두 단계 다르다. 어느 쪽인지는 **고시가
정한다.** 우리 감각이 아니다.

조회 경로 (R5-b 에 적힌 다섯 단계)
  ① lawSearch 로 **현행 행정규칙일련번호를 먼저** 찾는다 (웹 admRulSeq 는 옛 판)
  ② lawService 는 `ID=<행정규칙일련번호>`
  ③ 별표·부속서는 **제목으로** 고른다
  ④ 3회 · 3초 재시도
  ⑤ `별표내용` 은 중첩 리스트일 수 있다 - 평탄화한다
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sourcing_guard.allowed_hosts import ensure_allowed  # noqa: E402

SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL = "https://www.law.go.kr/DRF/lawService.do"

OUT_DIR = Path("tests/fixtures")


def _get(url: str, params: dict, *, tries: int = 3, gap: float = 3.0) -> dict:
    ensure_allowed(url)
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as c:
                r = c.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except Exception as exc:                      # noqa: BLE001
            last = exc
            print(f"    재시도 {attempt}/{tries}: {type(exc).__name__} {str(exc)[:70]}")
            if attempt < tries:
                time.sleep(gap)
    raise SystemExit(f"세 번 다 실패했습니다: {last!r}")


def search(query: str) -> list[dict]:
    """현행 행정규칙 목록. **일련번호는 여기서 얻는다.**"""
    doc = _get(SEARCH, {"OC": "test", "target": "admrul", "type": "JSON",
                        "query": query, "display": "100"})
    body = doc.get("AdmRulSearch") or {}
    rows = body.get("admrul") or []
    return rows if isinstance(rows, list) else [rows]


def detail(seq: str) -> dict:
    return _get(DETAIL, {"OC": "test", "target": "admrul", "type": "JSON", "ID": seq})


def flatten(value) -> str:
    """`별표내용` 은 문자열·리스트·중첩 리스트로 온다."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(flatten(v) for v in value)
    return str(value)


def units(doc: dict) -> list[dict]:
    block = (doc.get("AdmRulService") or {}).get("별표") or {}
    rows = block.get("별표단위") or []
    return rows if isinstance(rows, list) else [rows]


def main() -> int:
    # ── ① 현행 일련번호를 찾는다 ─────────────────────────────────
    print("[1] lawSearch - 어린이제품 안전기준 고시")
    rows = search("어린이제품")
    for r in rows:
        print(f"    {r.get('행정규칙일련번호')}  {r.get('행정규칙명')}  "
              f"시행 {r.get('시행일자')}  현행 {r.get('현행연혁코드')}")

    # ── ② 섬유 부속서를 가진 고시를 고른다 ───────────────────────
    print()
    print("[2] 각 고시의 별표·부속서 제목에서 '섬유' 를 찾는다")
    found: list[tuple[str, str, str, dict]] = []
    for r in rows:
        seq = str(r.get("행정규칙일련번호") or "")
        name = r.get("행정규칙명") or ""
        if not seq:
            continue
        doc = detail(seq)
        info = (doc.get("AdmRulService") or {}).get("행정규칙기본정보") or {}
        us = units(doc)
        hits = [u for u in us if "섬유" in (u.get("별표제목") or "")]
        print(f"    {seq} {name[:44]:<44} 별표 {len(us):>3}개 · 섬유 {len(hits)}건"
              f" · 시행 {info.get('시행일자')}")
        for u in hits:
            print(f"        └ {u.get('별표번호')} {u.get('별표제목')}")
            found.append((seq, name, info.get("시행일자") or "", u))
        time.sleep(1.0)

    # ── ③ 적용범위를 뽑는다 ─────────────────────────────────────
    print()
    print("[3] 적용범위 원문")
    out = []
    for seq, name, enforced, u in found:
        text = flatten(u.get("별표내용"))
        title = u.get("별표제목") or ""
        # "1. 적용범위" 부터 다음 번호 항목 직전까지.
        m = re.search(r"적용\s*범위(.{0,1200}?)(?:\n\s*2\s*[.．]|\Z)", text, re.S)
        scope = re.sub(r"\s+", " ", (m.group(1) if m else text[:600])).strip()
        print()
        print(f"  ── {name} / {title}")
        print(f"     일련번호 {seq} · 시행 {enforced}")
        print(f"     {scope[:700]}")
        out.append({"행정규칙일련번호": seq, "행정규칙명": name, "시행일자": enforced,
                    "별표번호": u.get("별표번호"), "별표제목": title,
                    "적용범위": scope, "전문": text})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "어린이제품_섬유_부속서_2026-09-14.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"원자료 {len(out)}건 → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
