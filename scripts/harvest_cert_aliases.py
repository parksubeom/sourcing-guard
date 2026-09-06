#!/usr/bin/env python3
"""KC인증 DB 에서 (통칭 → 법령 품목명) 후보를 역방향으로 긁는다.

⚠ **역방향이다.** 표의 품목명 596개로 정방향 수집하면 완구 14만 행을 받는다.
  미매칭 상품에서 사람이 뽑은 토큰으로만 검색한다.

두 가지를 뽑는다.
  1. productName 의 괄호 안팎    "전기오븐기기(에어프라이어)" → 에어프라이어 = 전기오븐기기
  2. categoryName 마지막 마디     "전기기기>주방용 전열기구>전기오븐기기" → 전기오븐기기

⚠ **여기서 나온 것을 그대로 ALIASES 에 붓지 않는다.** '매트' 를 치면
  '침대 매트리스' 가 나오는데, 표본의 매트는 놀이방매트·EVA 퍼즐매트라
  부속서 24 매트류 쪽이다. 그대로 넣으면 6건이 통째로 오답이 된다.
  이 스크립트는 **후보만** 낸다. 검수는 사람이 한다.

⚠ numOfRows 는 무시된다. 검색어 하나가 14만 행일 수 있다(완구). 큰 품목은
  --max-rows 로 잘라 괄호만 뽑고 나머지는 버린다.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.config import Settings  # noqa: E402
from sourcing_guard.item_grades import ItemGradeBook, normalize  # noqa: E402
from sourcing_guard.kats_client import KatsClient  # noqa: E402

_PAREN = re.compile(r"^\s*(?P<outer>[^()（）]+?)\s*[(（]\s*(?P<inner>[^()（）]+?)\s*[)）]\s*$")

# certDiv 정규화. 구법 표기가 섞여 있다 - 완구 14만 건 중 24% 가 구법이다.
#
# ⚠ **이 매핑이 틀리면 등급이 뒤집힌다. 가장 비싼 오류다.**
#   근거: 「전기용품 및 생활용품 안전관리법」 부칙과 「어린이제품 안전 특별법」
#   부칙이 구법의 안전인증/자율안전확인을 각각 안전인증/안전확인으로 승계한다.
#   자율안전확인 → 안전확인 은 이름만 바뀐 같은 제도다.
_CERT_DIV = {
    "안전인증대상 전기용품": "안전인증",
    "안전확인대상 전기용품": "안전확인",
    "공급자적합성확인대상 전기용품": "공급자적합성확인",
    "안전인증대상 생활용품": "안전인증",
    "안전확인대상 생활용품": "안전확인",
    "공급자적합성확인대상 생활용품": "공급자적합성확인",
    "안전확인 대상": "안전확인",
    "안전인증 대상": "안전인증",
    "자율안전확인 대상": "안전확인",      # 구법. 지금의 안전확인
    "공급자적합성확인 대상": "공급자적합성확인",
}


def norm_div(raw: str | None) -> str | None:
    """certDiv 의 마지막 마디를 현행 등급어로 옮긴다. 모르면 None."""
    if not raw:
        return None
    tail = raw.split(">")[-1].strip()
    return _CERT_DIV.get(tail)


def last_segment(raw: str | None) -> str | None:
    """categoryName 의 마지막 마디. 마디 수가 2~4로 흔들린다."""
    if not raw or not raw.strip():
        return None
    return raw.split(">")[-1].strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("terms", nargs="+")
    ap.add_argument("--gap", type=float, default=2.0)
    ap.add_argument("--max-rows", type=int, default=20000,
                    help="이 수를 넘으면 앞부분만 보고 나머지는 버린다")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    st = Settings.from_env()
    if st.mock_mode:
        raise SystemExit("mock 모드다. 실 API 를 쳐야 의미가 있다.")
    client = KatsClient(st.kats_base_url, st.kats_service_key)
    book = ItemGradeBook()
    in_table = {normalize(n) for r in book._rows for n in (r["item"],)}

    report: dict[str, dict] = {}
    for i, term in enumerate(args.terms):
        if i:
            time.sleep(args.gap)
        params = client._query("certification", "product_name", term)
        try:
            rows = client._call("certification", params)
        except Exception as exc:  # noqa: BLE001
            print(f"[{term}] 실패: {type(exc).__name__} {exc}")
            continue
        total = len(rows)
        rows = rows[: args.max_rows]

        pairs: collections.Counter = collections.Counter()
        cats: collections.Counter = collections.Counter()
        divs: collections.Counter = collections.Counter()
        for r in rows:
            seg = last_segment(r.get("categoryName"))
            if seg:
                cats[seg] += 1
            d = norm_div(r.get("certDiv"))
            divs[d or f"?? {r.get('certDiv')}"] += 1
            m = _PAREN.match(str(r.get("productName") or ""))
            if m:
                pairs[(m.group("inner"), m.group("outer"))] += 1

        print(f"\n[{term}]  {total}행" + (f" (앞 {len(rows)}행만 봄)" if total > len(rows) else ""))
        print("  categoryName 마지막 마디 → 표에 있나")
        for seg, n in cats.most_common(5):
            print(f"    {n:6}  {seg[:40]:42} {'표에 있음' if normalize(seg) in in_table else '표에 없음'}")
        print("  certDiv 정규화")
        for d, n in divs.most_common(5):
            print(f"    {n:6}  {d}")
        print("  괄호 쌍 (통칭 → 법령 품목명)")
        for (inner, outer), n in pairs.most_common(8):
            mark = "표에 있음" if normalize(outer) in in_table else "표에 없음"
            print(f"    {n:6}  {inner[:22]:24} → {outer[:30]:32} {mark}")

        report[term] = {
            "total": total, "seen": len(rows),
            "categories": [[s, n, normalize(s) in in_table] for s, n in cats.most_common(20)],
            "cert_divs": [[d, n] for d, n in divs.most_common()],
            "paren_pairs": [[i2, o, n, normalize(o) in in_table]
                            for (i2, o), n in pairs.most_common(60)],
        }

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
