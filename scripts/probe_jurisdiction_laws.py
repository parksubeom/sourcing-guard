#!/usr/bin/env python
"""소관 안내에 인용한 **법령 원문을 받아 확인한다** (R5 · 조사용).

    python scripts/probe_jurisdiction_laws.py

`data/jurisdiction_map.yaml` 의 줄마다 `법령`·`조문`·`시행` 이 적혀 있다. 그
값들이 진짜인지 law.go.kr DRF 로 받아 대조한다 - 기억으로 적은 조문 번호가
들어가면 R2 의 근거가 틀린 근거가 된다.

⚠⚠ **이 파일은 2026-09-14 에 처음 생겼다.** 그 전에는 yaml 주석이
  "재현: python scripts/probe_jurisdiction_laws.py" 라고 적고 있었는데
  **그 파일이 없었다** - 문서가 코드보다 앞서 나간 자리다. 다음 사람이
  재현하려다 없는 파일을 찾는다.

⚠ 실호출한다. 정기 실행이 아니라 조사용이다 - `law.go.kr` 은 R4 표에
  "자료 수집 경로" 로 승인돼 있다.

⚠ `SG_LIVE_NET` 은 **pytest 안에서만** 의미가 있다(`tests/conftest.py` 의
  네트워크 차단을 푸는 열쇠다). 스크립트를 직접 돌릴 때는 아무 효과가 없다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import yaml  # noqa: E402

from sourcing_guard.allowed_hosts import ensure_allowed  # noqa: E402

SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL = "https://www.law.go.kr/DRF/lawService.do"
MAP = Path("sourcing_guard/data/jurisdiction_map.yaml")


def _first_article_line(article: dict) -> str:
    """조문 첫 항의 본문. 없으면 조문 제목."""
    hang = article.get("항")
    hang = hang if isinstance(hang, list) else ([hang] if hang else [])
    for h in hang:
        text = (h.get("항내용") or "").strip()
        if text:
            return " ".join(text.split())
    return " ".join((article.get("조문내용") or "").split())


def main() -> int:
    rows = yaml.safe_load(MAP.read_text(encoding="utf-8"))["소관"]
    ensure_allowed(SEARCH)
    bad: list[str] = []
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        for row in rows:
            name = row["법령"]
            found = c.get(SEARCH, params={"OC": "test", "target": "law",
                                          "type": "JSON", "query": name,
                                          "display": 20}).json()
            hits = found["LawSearch"].get("law") or []
            hits = hits if isinstance(hits, list) else [hits]
            hit = next((h for h in hits if h.get("법령명한글") == name), None)
            if hit is None:
                bad.append(f"{name}: 못 찾음")
                continue
            detail = c.get(DETAIL, params={"OC": "test", "target": "law",
                                           "type": "JSON",
                                           "MST": hit["법령일련번호"]}).json()
            info = detail["법령"]["기본정보"]
            ministry = info["소관부처"]["content"]
            effective = str(info.get("시행일자") or "")
            print(f"\n=== {name}")
            print(f"    소관 {ministry}   시행 {effective}")
            # ⚠ yaml 은 괄호로 단서를 붙인다("식품의약품안전처 (보건복지부 공동
            #   소관)"). 앞부분만 대조한다.
            #
            # ⚠⚠ **다르면 실패가 아니라 경고다.** law.go.kr 의 `소관부처` 칸은
            #   값이 하나뿐이라 공동 소관을 담지 못한다 - 그 칸과 우리 문구가
            #   다를 수 있고, 어느 쪽이 맞는지는 이 스크립트가 정할 일이 아니다.
            #   대신 **yaml 이 원문 값을 적어 두게** 하고, 안 적혀 있으면 실패다.
            head_ministry = row["기관"].split(" (")[0].strip()
            if head_ministry != ministry:
                if row.get("소관부처_원문") != ministry:
                    bad.append(
                        f"{name}: 기관이 다른데 yaml 에 원문 값이 없다 "
                        f"(yaml {head_ministry} · 원문 {ministry}) - "
                        "`소관부처_원문` 과 `소관_비고` 를 적으세요"
                    )
                else:
                    print(f"    주의: yaml {head_ministry} · 원문 {ministry} "
                          f"— {row.get('소관_비고', '')}")
            if effective and effective != str(row.get("시행") or ""):
                print(f"    ⚠ yaml 시행 {row.get('시행')} · 원문 {effective} - 갱신 필요")

            # 인용한 조문 번호가 실재하는가. "제30조의2(…)" 모양에서 숫자를 뗀다.
            quoted = row["조문"]
            arts = detail["법령"]["조문"]["조문단위"]
            head = quoted.split("(")[0].strip()          # 예: "제30조의2"
            match = next(
                (a for a in arts
                 if " ".join((a.get("조문내용") or "").split()).startswith(head)),
                None,
            )
            if match is None:
                bad.append(f"{name}: 인용한 조문을 원문에서 못 찾았다 - {head}")
                continue
            print(f"    원문 {_first_article_line(match)[:150]}")
    print()
    if bad:
        print("어긋난 줄:")
        for b in bad:
            print("  -", b)
        return 1
    print(f"소관 {len(rows)}줄 전부 원문과 맞는다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
