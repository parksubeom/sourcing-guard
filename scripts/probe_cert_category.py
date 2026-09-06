#!/usr/bin/env python3
"""KC인증 DB 의 categoryName · certDiv 가 무엇으로 오는지 소량 탐침.

가장 큰 미사용 데이터다. cert/certificationList.json 이 productName ·
categoryName · certDiv 를 주는데, 지금 category_name 은 받아만 두고 아무도
쓰지 않는다.

이게 표의 품목명과 같은 어휘이거나 결정론적으로 매핑되면, 손으로 만든 별칭의
상당 부분이 필요 없어진다. LLM 없이 정부 데이터끼리 잇는 것이라 R1 과 무관하다.

확인할 것 셋:
  (a) categoryName 이 561 표의 품목명과 같은 어휘인가.
      픽스처 예가 "전기기기>관상 및 애완용 전기기기" 로 계층형이다.
      표는 평면이므로 매핑이 필요할 수 있다.
  (b) certDiv 가 표의 등급(안전인증/안전확인/공급자적합성확인)과 일치하는가.
  (c) 전량 조회 규모. 리콜은 국내 4천·국외 3만이었지만 인증은 자릿수가 다를 수
      있다.

⚠ **소량으로만 친다.** conditionValue=% 전량 조회는 설계서 밖 사용법이고
  (핸드오프 §4), 규모를 모르는 채로 던지면 정부 서버에 부담이다. 이 스크립트는
  검색어당 numOfRows 를 작게 두고 totalCount 만 읽는다.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.config import Settings  # noqa: E402
from sourcing_guard.kats_client import KatsClient  # noqa: E402

# 표본에서 미매칭 덩어리로 눈에 띈 말들. 표의 품목명이 아니라 **셀러가 쓰는 말**을
# 넣는다 - 인증 DB 가 셀러 어휘를 알아듣는지가 알고 싶은 것이다.
_TERMS = ["에어프라이어", "전기오븐", "헤어드라이기", "블루투스스피커",
          "필통", "줄넘기", "책가방", "놀이방매트", "전기주전자", "가습기"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", nargs="*", default=_TERMS)
    ap.add_argument("--rows", type=int, default=20, help="검색어당 가져올 행 수")
    ap.add_argument("--gap", type=float, default=1.5, help="호출 간격(초)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    st = Settings.from_env()
    if st.mock_mode:
        raise SystemExit('mock 모드다. 실 API 를 쳐야 의미가 있다.')
    client = KatsClient(st.kats_base_url, st.kats_service_key)
    op = "certification"
    got: dict[str, list[dict]] = {}

    for i, term in enumerate(args.terms):
        if i:
            time.sleep(args.gap)
        params = client._query(op, "product_name", term)
        params["numOfRows"] = str(args.rows)
        try:
            rows = client._call(op, params)
        except Exception as exc:  # noqa: BLE001
            print(f"  {term:14} 실패: {type(exc).__name__} {exc}")
            continue
        got[term] = rows
        cats = collections.Counter(r.get("categoryName") for r in rows)
        divs = collections.Counter(r.get("certDiv") for r in rows)
        print(f"\n[{term}]  {len(rows)}행")
        for c, n in cats.most_common(4):
            print(f"    categoryName  {n:3}  {c}")
        for d, n in divs.most_common():
            print(f"    certDiv       {n:3}  {d}")
        for r in rows[:2]:
            print(f"    예) {str(r.get('productName'))[:34]:36} | {r.get('certNum')}")

    if args.out:
        Path(args.out).write_text(json.dumps(got, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
