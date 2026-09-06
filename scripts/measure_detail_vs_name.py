#!/usr/bin/env python3
"""상품명만 vs 상세 전체 - 같은 30건을 두 조건으로 재고 나란히 적는다.

⚠ **매칭률 하나만 재지 않는다.** 넷을 잰다.
    품목 매칭 (정답/애매/오답)   ← 오답이 같이 오르는지가 핵심이다
    kc_numbers 추출 건수
    target_age 추출 건수        → CHILD_CATCH_ALL 이 몇 건 켜지나
    materials 추출 건수         → 유해물질 규칙이 몇 건 걸리나

⚠ **모든 숫자에 입력 조건을 함께 적는다.** "34.6%" 가 아니라
  "상품명만 · 대상 136 기준 34.6%" 로 적는다. 조건이 빠진 숫자는 다시 물어야 한다.

비용: 30건 × 2조건 = LLM 60회. 일일 상한 500 의 12% 다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.item_grades import ItemGradeBook  # noqa: E402

_SAMPLE = Path("tests/fixtures/새표본235.txt")
_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")
_WRONG = Path("tests/fixtures/새표본235_오답.tsv")
_DETAIL = Path("tests/fixtures/상세30.txt")

# 「전자상거래 등에서의 상품 등의 정보제공에 관한 고시」(공정거래위원회 2022-15)
# Ⅲ.1 이 요구하는 항목 이름들. 상세페이지에 '상품 고시정보' 표가 실제로 있는지
# 세는 데 쓴다 - 40개 품목군 중 '품명 및 모델명' 은 17개, 'KC 인증정보' 는
# 13개 품목군에만 요구된다(원문 확인).
_NOTICE_MARKERS = ("품명 및 모델명", "품명및모델명", "KC 인증", "KC인증",
                   "상품 고시정보", "상품고시정보", "제품 주소재", "인증ㆍ허가")


def split_details(path: Path) -> dict[int, str]:
    """'===== <번호> =====' 로 잘라 번호→본문."""
    raw = path.read_text(encoding="utf-8")
    out: dict[int, str] = {}
    cur: int | None = None
    buf: list[str] = []
    for line in raw.splitlines():
        m = re.match(r"^=====\s*(\d+)\s*=====\s*$", line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur, buf = int(m.group(1)), []
            continue
        if line.startswith("#"):
            continue
        if cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return {k: v for k, v in out.items() if v}


def scan(url: str, text: str) -> dict:
    """실패를 조용히 삼키지 않는다 - 429 를 '추출 실패' 로 읽으면 숫자가 뒤집힌다."""
    out = subprocess.run(
        ["curl", "-s", "--max-time", "180", "-w", "\n%{http_code}",
         "-X", "POST", f"{url}/api/v1/scan",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"page_text": text}, ensure_ascii=False)],
        capture_output=True, text=True).stdout
    body, _, code = out.rpartition("\n")
    if code.strip() != "200":
        raise RuntimeError(f"HTTP {code.strip() or '없음'} — {body[:160]}")
    return json.loads(body)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://sourcing-guard.fly.dev")
    ap.add_argument("--gap", type=float, default=5.5)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    details = split_details(_DETAIL)
    if not details:
        raise SystemExit(
            f"{_DETAIL} 에 붙여넣은 본문이 없습니다.\n"
            "  '===== <번호> =====' 줄 아래에 상세페이지 텍스트를 채워 주십시오."
        )

    names = [l.strip() for l in _SAMPLE.read_text(encoding="utf-8").splitlines() if l.strip()]
    scope = {}
    for line in _SCOPE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        no, verdict, name, _why = line.split("\t")
        scope[int(no)] = (verdict, name)

    wrong, vague, section = set(), set(), None
    for line in _WRONG.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            if "--- 오답" in line:
                section = "wrong"
            elif "[애매]" in line:
                section = "vague"
            elif "[검수했고 정답]" in line or "[고쳐짐" in line:
                section = None
            continue
        if not line.strip() or section is None:
            continue
        (wrong if section == "wrong" else vague).add(line.split("\t")[0])

    book = ItemGradeBook()
    rows = []
    for i, (no, detail) in enumerate(sorted(details.items())):
        verdict, name = scope[no]
        if verdict != "대상":
            print(f"  ⚠ [{no}] 은 '{verdict}' 로 분류돼 있습니다 - 표본에서 빼십시오")
        if i:
            time.sleep(args.gap)
        by_name = scan(args.url, name)
        time.sleep(args.gap)
        by_detail = scan(args.url, detail)
        rows.append({
            "no": no, "name": name,
            "notice_table": any(m in detail for m in _NOTICE_MARKERS),
            "detail_chars": len(detail),
            "name_only": by_name, "detail": by_detail,
        })
        print(f"  [{no:3}] 잼 · 고시표 {'있음' if rows[-1]['notice_table'] else '없음'}")

    def tally(payload: dict, raw_for_rules: str) -> dict:
        facts = payload.get("facts") or {}
        items = [c["item"] for f in payload.get("findings", [])
                 for c in (f.get("detail") or {}).get("candidates", [])]
        kinds = [f.get("kind") for f in payload.get("findings", [])]
        return {
            "matched": bool(items),
            "items": items,
            "kc": len(facts.get("kc_numbers") or []),
            "age": bool(facts.get("target_age")),
            "materials": len(facts.get("materials") or []),
            "catch_all": "child_catch_all" in kinds,
            "hazard": sum(1 for k in kinds if k == "hazard_rule_applies"),
        }

    print("\n" + "=" * 72)
    print("조건별 결과 — ⚠ 숫자에는 항상 입력 조건을 함께 적는다")
    print("=" * 72)
    for cond in ("name_only", "detail"):
        label = "상품명만" if cond == "name_only" else "상세 전체"
        t = [tally(r[cond], r["name"]) for r in rows]
        n = len(t)
        ok = sum(1 for r, x in zip(rows, t) if x["matched"] and r["name"] not in wrong and r["name"] not in vague)
        amb = sum(1 for r, x in zip(rows, t) if x["matched"] and r["name"] in vague)
        bad = sum(1 for r, x in zip(rows, t) if x["matched"] and r["name"] in wrong)
        print(f"\n[{label}]  n={n}")
        print(f"  품목 매칭   정답 {ok} · 애매 {amb} · 오답 {bad} · 미매칭 {n - ok - amb - bad}")
        print(f"  kc_numbers  {sum(1 for x in t if x['kc'])}건")
        print(f"  target_age  {sum(1 for x in t if x['age'])}건  → CHILD_CATCH_ALL {sum(1 for x in t if x['catch_all'])}건")
        print(f"  materials   {sum(1 for x in t if x['materials'])}건  → 유해물질 규칙 {sum(x['hazard'] for x in t)}건")

    got = sum(1 for r in rows if r["notice_table"])
    print(f"\n'상품 고시정보' 표가 있는 것  {got}/{len(rows)}건")
    print(f"상세 길이 중앙값  {sorted(r['detail_chars'] for r in rows)[len(rows)//2]:,}자")

    print("\n── 상세로 새로 걸린 것 (오답인지 눈으로 볼 것) ──")
    for r in rows:
        a = tally(r["name_only"], r["name"]); b = tally(r["detail"], r["name"])
        if b["matched"] and not a["matched"]:
            print(f"  [{r['no']}] {r['name'][:52]}\n        → {b['items']}")
    print("── 상세로 없어진 것 ──")
    for r in rows:
        a = tally(r["name_only"], r["name"]); b = tally(r["detail"], r["name"])
        if a["matched"] and not b["matched"]:
            print(f"  [{r['no']}] {r['name'][:52]}  {a['items']} → 없음")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
