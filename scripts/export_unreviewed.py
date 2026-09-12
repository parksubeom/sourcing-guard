#!/usr/bin/env python
"""미검수 (상품명, 품목) 쌍을 **재생에서 직접 뽑는다.** LLM·네트워크 0회.

왜 스크립트인가
---------------
2026-09-11 에 손으로 만든 `미검수_gpt.tsv` 가 **20줄**이었는데 재생값은
**18** 이었다. 그 사이 규칙이 바뀌어 두 쌍이 검수 목록과 만난 것인데, 파일은
그대로 남아 "검수할 것이 20개" 라고 말했다.

⚠⚠ **사람이 손으로 유지하는 검수 목록은 반드시 낡는다.** 규칙을 고칠 때마다
  미검수 집합이 움직이기 때문이다. 그래서 (1) 재생에서 뽑고 (2) 재생값과
  파일 줄 수가 다르면 실패하는 검사를 붙인다
  (`tests/test_unreviewed_tsv.py`).

사용
----
    python scripts/export_unreviewed.py                     # 화면에만
    python scripts/export_unreviewed.py --out tests/fixtures/미검수_gpt_2026-09-12.tsv

⚠ `--out` 없이 돌리면 파일을 쓰지 않는다. `measure_domeggook_fields.py` 에서
  같은 모양으로 한 번 낡았다 - 화면만 보고 "쟀다" 로 넘어가면 파일은 그대로다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sourcing_guard.models import ItemCategory, ProductFacts  # noqa: E402
from sourcing_guard.verifier import RuleBook, verify  # noqa: E402
from audit_tally import (  # noqa: E402
    load_audit,
    load_reviewed_pairs,
    load_scope,
    verdict,
)

#: 검수 목록의 정본. Claude 원자료로 만들어졌다 - 다른 추출기가 다르게 붙인
#: 쌍은 검수된 적이 없으므로 미검수다 (R7).
REVIEWED_SRC = "tests/fixtures/단건경로_claude_235.json"

HEADER = """\
# 미검수 (상품명, 품목) 쌍 - **사람이 검수해야 한다**
# GPT(gpt-5.4-mini) · 단건 · 상품명만 · 분모 135
#
# ⚠⚠ **이 파일은 손으로 고치지 않는다.** `scripts/export_unreviewed.py` 가
#   재생에서 직접 뽑는다. 규칙을 고치면 미검수 집합이 움직이므로 손으로 두면
#   반드시 낡는다 - 2026-09-11 판(20줄)이 실제로 그랬다.
#
# 재생 명령 (LLM 0회):
#   python scripts/export_unreviewed.py --out tests/fixtures/미검수_gpt_{stamp}.tsv
#
# 검수 목록은 Claude 추출 기준으로 만들어졌다. 다른 추출기가 다르게 붙인 쌍은
# 검수된 적이 없으므로 정답으로 세지 않았다 (R7).
#
# `**품목**` 이 미검수 쌍이다. 갈림이면 일부만 새 후보일 수 있다.
#
# `원인` 칸:
#   규칙변경  Claude 원자료를 현재 코드로 재생해도 같은 쌍이 나온다.
#             별칭·가드가 늘어 생긴 것이고 추출기와 무관하다.
#   추출차이  재생에서는 안 나온다. 추출기를 바꾼 효과다.
#   ⚠ 규칙변경이라고 자동으로 정답이 되는 것은 아니다. 판정은 사람이 한다.
#
# 판정을 적어 `새표본235_오답.tsv` 의 해당 절로 옮기거나, 정답이면
# [검수했고 정답] 절에 기록할 것.
#
# 뽑은 날: {stamp}
#   [② 미검수] {n_target}줄   대상 135 중 · **이것이 ② 집계다**
#   [부록]     {n_other}줄   애매·비대상 줄의 미검수 쌍. ② 에 안 들어가지만
#              화면에는 뜨고 ⑤·④ 로 세어진다. 검수는 필요하다.
#
# 상품명\tGPT\tclaude 재생(현재 코드)\t원인\t분류\t판정
"""


def _grades(row: dict, kats, rules: RuleBook) -> list[str]:
    try:
        category = ItemCategory(row.get("category") or "unclassified")
    except ValueError:
        category = ItemCategory.UNCLASSIFIED
    facts = ProductFacts(
        product_name=row.get("product_name") or None,
        category=category,
        legal_item_name=row.get("legal") or None,
    )
    found = verify(facts, kats, rules, raw_text=row["name"])
    return sorted(
        {c["item"] for f in found for c in (f.detail or {}).get("candidates", []) or []}
    )


def collect(src: str = "tests/fixtures/단건경로_gpt.json") -> list[dict]:
    """미검수 줄을 재생해서 뽑는다. 정본 집계(`tally`)와 같은 판정을 쓴다."""
    scope = load_scope()
    wrong, vague = load_audit()
    reviewed = load_reviewed_pairs(REVIEWED_SRC)

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = RuleBook()

    rows = [r for r in json.loads(Path(src).read_text(encoding="utf-8"))
            if scope.get(r["name"])]
    claude = {r["name"]: r for r in
              json.loads(Path(REVIEWED_SRC).read_text(encoding="utf-8"))}

    out: list[dict] = []
    for r in rows:
        got = _grades(r, kats, rules)
        if not got:
            continue
        if scope[r["name"]] == "대상":
            # 정본 집계(`tally`)와 **같은 판정**을 쓴다. 여기서 조건을 다시
            # 적으면 ② 와 이 파일이 갈린다 (§6).
            if verdict(r["name"], got, wrong, vague, reviewed) != "unreviewed":
                continue
        else:
            # ⚠⚠ 애매·비대상 줄은 ② 미검수 집계에 **안 들어간다**(분모가 대상
            #   135 다). 그래도 **검수해야 할 쌍이다** - 화면에는 뜨고 ⑤ 애매
            #   부착·④ 비대상 부착으로 세어진다.
            #
            #   2026-09-11 판 파일이 이 둘을 섞어 20줄이었고, 재생값 18 과
            #   어긋났다. **빼지 않고 절을 나눈다** - 빼면 검수 대기가 조용히
            #   사라진다.
            if not [g for g in got if (r["name"], g) not in reviewed]:
                continue
        # 같은 상품을 Claude 원자료로 재생하면 같은 쌍이 나오는가.
        peer = claude.get(r["name"])
        replay = _grades(peer, kats, rules) if peer else []
        new_pairs = [g for g in got if (r["name"], g) not in reviewed]
        out.append({
            "name": r["name"],
            "gpt": got,
            "replay": replay,
            "새쌍": new_pairs,
            "원인": "규칙변경" if set(new_pairs) & set(replay) else "추출차이",
            "분류": scope[r["name"]],
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="tests/fixtures/단건경로_gpt.json")
    ap.add_argument("--out", default="")
    ap.add_argument("--stamp", default="", help="파일 안에 적을 날짜. 기본은 오늘")
    args = ap.parse_args()

    rows = collect(args.src)
    stamp = args.stamp or f"{date.today():%Y-%m-%d}"
    target = [r for r in rows if r["분류"] == "대상"]
    other = [r for r in rows if r["분류"] != "대상"]
    print(f"원자료 {args.src} · 검수 목록 {REVIEWED_SRC}")
    print(f"  [② 미검수] {len(target)}줄  ← 재생의 ② 와 같아야 한다")
    print(f"  [부록]     {len(other)}줄  (애매·비대상 · ② 밖)")
    by: dict[str, int] = {}
    for r in target:
        by[r["원인"]] = by.get(r["원인"], 0) + 1
    print(f"  ② 원인별 {by}")
    for label, group in (("② 미검수", target), ("부록", other)):
        for r in group:
            print(f"  [{label}][{r['분류']}] {r['name'][:48]:<50} {r['새쌍']}  {r['원인']}")

    if not args.out:
        print("\n⚠ --out 을 안 줬으므로 **파일을 쓰지 않았다.**")
        return

    def _line(r: dict) -> str:
        marked = " / ".join(f"**{g}**" if g in r["새쌍"] else g for g in r["gpt"])
        replay = " / ".join(r["replay"]) or "(없음)"
        return f"{r['name']}\t{marked}\t{replay}\t{r['원인']}\t{r['분류']}\t\n"

    body = HEADER.format(stamp=stamp, n_target=len(target), n_other=len(other))
    body += "\n# ── [② 미검수] 대상 135 중 · 이것이 ② 집계다 ──\n"
    body += "".join(_line(r) for r in target)
    body += ("\n# ── [부록] 애매·비대상 줄의 미검수 쌍 ──\n"
             "# ⚠ ② 에 안 들어간다(분모가 대상 135 다). 그래도 화면에는 뜨고\n"
             "#   ⑤ 애매 부착·④ 비대상 부착으로 세어지므로 검수는 필요하다.\n")
    body += "".join(_line(r) for r in other)
    Path(args.out).write_text(body, encoding="utf-8")
    print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
