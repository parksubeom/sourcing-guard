#!/usr/bin/env python
"""추출기를 바꿔 235건을 다시 잰다. **83.7%(Claude) 와 같은 조건으로.**

왜 필요한가
-----------
발표 숫자(단건 정답률)는 추출 결과를 입력으로 한다. 추출기를 바꾸면
product_name·legal_item_name·category 가 달라지고 그 숫자가 무효가 된다
(CLAUDE.md R7). 그래서 벤더를 바꿀 때는 같은 조건으로 다시 잰다.

⚠ **미검수를 정답으로 세지 않는다.** 검수 목록은 Claude 추출 기준으로
  만들어졌으므로, 다른 추출기가 다르게 붙인 쌍은 검수된 적이 없는데도
  오답·애매 목록에 없다는 이유로 "ok" 로 잡힌다. 두 숫자를 함께 낸다:

      검수된 쌍만 정답으로 센 값
      미검수 N 건을 모두 정답으로 가정한 상한

  미검수 목록은 tsv 로 남겨 검수표에 붙인다. **검수는 사람이 한다** -
  이 스크립트는 정답 판정을 하지 않는다.

⚠ 라벨을 결과에 함께 적는다. "GPT(gpt-5.4-mini) · 단건 · 상품명만 · 분모 135"
  처럼 경로·입력·분모가 없는 숫자는 쓰지 않는다.

⚠ 프로세스는 하나만. 돌리기 전에 이전 백그라운드 프로세스를 확인하고 죽인다.
  진행은 한 줄씩 즉시 흘려보낸다 (`python -u`) - 2026-09-07 에 버퍼링 때문에
  같은 측정을 두 번 돌려 429 를 맞았다 (CLAUDE.md §6).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sourcing_guard.extractor as ex  # noqa: E402
from audit_tally import (  # noqa: E402
    load_audit,
    load_reviewed_pairs,
    load_scope,
    tally,
    verdict,
)
from replay_single_path import grades_for  # noqa: E402
from sourcing_guard.verifier import RuleBook  # noqa: E402

# ⚠ 리포 안의 파일이어야 한다. 2026-09-08 까지 /tmp 를 가리키고 있었고,
#   그러면 발표 숫자 83.7% 와 "검수된 쌍 149개" 둘 다 커밋되지 않은 파일에
#   걸린다. 재생 조건은 사이드카 md 에 적었다.
_CLAUDE_SOURCES = ("tests/fixtures/단건경로_claude_235.json",)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", nargs="+", default=list(_CLAUDE_SOURCES),
                    help="Claude 기준 원자료. 검수된 쌍의 출처이기도 하다")
    ap.add_argument("--scope", default="전부",
                    help="대상 | 비대상 | 애매 | 밖 | 전부")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--label", required=True,
                    help='예: "GPT(gpt-5.4-mini) · 단건 · 상품명만 · 분모 135"')
    ap.add_argument("--out", default="tests/fixtures/단건경로_gpt.json")
    ap.add_argument("--unreviewed-out", default="tests/fixtures/미검수_gpt.tsv")
    args = ap.parse_args()

    scope = load_scope()
    wrong, vague = load_audit()
    reviewed = load_reviewed_pairs(*args.src)

    want = {"밖": {"비대상", "애매"}, "전부": {"대상", "비대상", "애매"}}.get(
        args.scope, {args.scope}
    )
    claude: dict[str, dict] = {}
    for src in args.src:
        for r in json.loads(Path(src).read_text(encoding="utf-8")):
            claude[r["name"]] = r
    rows = [r for r in claude.values() if scope.get(r["name"]) in want]
    rows.sort(key=lambda r: r["no"])
    if args.limit:
        rows = rows[: args.limit]

    print(f"라벨: {args.label}")
    print(f"분모: {len(rows)}건 (scope={args.scope}) · 검수된 쌍 {len(reviewed)}개")
    print(f"추출 순서: {ex.settings.extractor_order} · GPT 모델 {ex.settings.gpt_model}\n")

    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = RuleBook()

    out: list[dict] = []
    started = time.time()
    for i, r in enumerate(rows, 1):
        ex.stats.reset()
        facts = ex.extract(r["name"])
        snap = ex.stats.snapshot()
        vendor = next(iter(snap["by_vendor"]), "heuristic")
        row = {
            "no": r["no"],
            "name": r["name"],
            "vendor": vendor,
            "product_name": facts.product_name,
            "category": facts.category.value if facts.category else None,
            "legal": facts.legal_item_name,
        }
        row["single"] = grades_for(row, kats, rules)
        # 배치는 LLM 을 쓰지 않으므로 Claude 원자료의 값이 그대로 유효하다.
        row["batch"] = r.get("batch") or []
        row["single_claude"] = r.get("single") or []
        out.append(row)

        call = verdict(r["name"], row["single"], wrong, vague, reviewed)
        mark = {"ok": " ", "wrong": "✗", "vague": "~", "unreviewed": "?"}[call]
        same = "=" if row["single"] == row["single_claude"] else "≠"
        print(f"  [{i:3}/{len(rows)}] {mark}{same} {r['no']:>3} "
              f"[{scope.get(r['name'])}] {r['name'][:40]}", flush=True)
        if call == "unreviewed":
            print(f"            미검수 → {row['single']}"
                  f"  (claude {row['single_claude']})", flush=True)

    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    results = {r["name"]: r["single"] for r in out}
    got = tally(results, scope=scope, audit=(wrong, vague), reviewed=reviewed)

    # 미검수 목록을 tsv 로 남긴다. 사람이 검수한다.
    #
    # ⚠ **미검수의 원인이 둘이다.** 가르지 않으면 검수가 느려진다:
    #
    #   (1) 규칙이 바뀌어 생긴 쌍
    #       원자료는 그 시점 코드로 얻은 것이다. 그 뒤 별칭·가드가 늘면
    #       같은 추출 결과에서도 새 쌍이 나온다. 부속서 1(모기장·가방·장갑·
    #       토시·타월)이 그렇게 들어왔고, 그때 눈 검수해서 커밋에 적었다.
    #   (2) 추출이 달라져 생긴 쌍
    #       추출기를 바꾼 효과다. 이쪽이 이 측정에서 새로 보는 것이다.
    #
    #   Claude 원자료를 **현재 코드로 재생**해 같은 쌍이 나오면 (1) 이다.
    #
    # ⚠ (1) 이라고 해서 자동으로 정답이 되는 것은 아니다. 판정은 사람이 한다 -
    #   이 스크립트는 원인만 가른다.
    claude_now = {
        r["name"]: grades_for(r, kats, rules) for r in claude.values()
    }
    unrev = [
        r for r in out
        if verdict(r["name"], r["single"], wrong, vague, reviewed) == "unreviewed"
    ]
    lines = [
        "# 미검수 (상품명, 품목) 쌍 - **사람이 검수해야 한다**",
        f"# {args.label}",
        "#",
        "# 검수 목록은 Claude 추출 기준으로 만들어졌다. 다른 추출기가 다르게",
        "# 붙인 쌍은 검수된 적이 없으므로 정답으로 세지 않았다.",
        "#",
        "# 판정을 적어 새표본235_오답.tsv 의 해당 절로 옮기거나, 정답이면",
        "# [검수했고 정답] 절에 기록할 것.",
        "#",
        "# `**품목**` 이 미검수 쌍이다. 갈림이면 일부만 새 후보일 수 있다.",
        "#",
        "# `원인` 칸:",
        "#   규칙변경  Claude 원자료를 현재 코드로 재생해도 같은 쌍이 나온다.",
        "#             별칭·가드가 늘어 생긴 것이고 추출기와 무관하다.",
        "#   추출차이  재생에서는 안 나온다. 추출기를 바꾼 효과다.",
        "#   ⚠ 규칙변경이라고 자동으로 정답이 되는 것은 아니다. 판정은 사람이 한다.",
        "#",
        "# 상품명\t붙은 품목(GPT)\tclaude 저장값\tclaude 재생(현재 코드)\t원인\t분류\t판정(사람이 적는다)",
    ]
    for r in unrev:
        # 어느 쌍이 미검수인지 표시한다 - 갈림에서 일부만 새 후보일 수 있다.
        marked = " / ".join(
            item if (r["name"], item) in reviewed else f"**{item}**"
            for item in r["single"]
        )
        now = claude_now.get(r["name"], [])
        cause = "규칙변경" if set(now) == set(r["single"]) else "추출차이"
        lines.append(
            f"{r['name']}\t{marked}\t"
            f"{' / '.join(r['single_claude']) or '(없음)'}\t"
            f"{' / '.join(now) or '(없음)'}\t{cause}\t{scope.get(r['name'])}\t"
        )
    Path(args.unreviewed_out).write_text("\n".join(lines) + "\n", encoding="utf-8")

    n = got["denominator"]
    print(f"\n{'=' * 74}")
    print(f"{args.label}\n")
    print(f"  대상 {n}건")
    print(f"    정답(검수된 쌍만)   {got['ok']:3} ({got['ok'] / n * 100:5.1f}%)")
    print(f"    정답 상한(미검수 포함) {got['ok_upper']:3} "
          f"({got['ok_upper'] / n * 100:5.1f}%)   ← 검수 전에는 이 값을 쓰지 않는다")
    print(f"    미검수              {got['unreviewed']:3}")
    print(f"    애매                {got['vague']:3}")
    print(f"    오답                {got['wrong']:3}")
    print(f"    미매칭              {got['missed']:3}")
    print(f"\n  비대상 → 부착        {got['off_target']:3}   ← 0 이 아니면 못 간다")
    print(f"  애매   → 부착        {got['on_vague']:3}")
    vendors: dict[str, int] = {}
    for r in out:
        vendors[r["vendor"]] = vendors.get(r["vendor"], 0) + 1
    print(f"\n  실제 추출 경로       {vendors}")
    print(f"  걸린 시간            {time.time() - started:.0f}초")
    print(f"\n원자료      → {args.out}")
    print(f"미검수 목록 → {args.unreviewed_out}  ({len(unrev)}건)")


if __name__ == "__main__":
    main()
