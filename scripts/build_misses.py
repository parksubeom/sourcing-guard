"""「우리가 틀린 것」 페이지의 자료를 만든다. **LLM·네트워크 0회.**

왜 이 페이지인가 (총괄 판정 2026-09-19 §2-C)
-------------------------------------------
심사위원은 정확도 99% 를 믿지 않는다. **틀린 것을 내놓는 팀**은 믿는다.
그리고 그것이 이 제품의 논리와 맞는다 - 우리가 파는 것은 정확도가 아니라
"모르면 모른다고 말한다" 이기 때문이다.

⚠⚠ **집계를 다시 적지 않는다.** 줄을 고르는 것도 세는 것도 `audit_tally.tally`
  와 `verdict` 를 그대로 쓴다. 2026-09-08 에 같은 일을 하는 집계가 셋으로
  갈라져 기획서에 77.8% 를 적었는데 실제는 77.0% 였다. 이 스크립트는 만든 수가
  `baseline.BASELINE` 과 어긋나면 **파일을 만들지 않고 멈춘다.**

⚠ 상호는 한 글자도 안 나간다. 상품명 앞머리 괄호 묶음을 뗀다
  (`record_samples.clean_title` 과 같은 규칙).

쓰는 법
-------
    PYTHONUTF8=1 PYTHONPATH=. python -u scripts/build_misses.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_tally import (  # noqa: E402
    load_audit,
    load_reviewed_pairs,
    load_scope,
    tally,
    verdict,
)
from record_samples import clean_title  # noqa: E402
from replay_single_path import grades_for  # noqa: E402

from sourcing_guard.baseline import BASELINE, BASELINE_EXTRACTOR  # noqa: E402
from sourcing_guard.verifier import RuleBook  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "tests/fixtures/단건경로_gpt.json"
_AUDIT = _ROOT / "tests/fixtures/새표본235_오답.tsv"
_OUT = _ROOT / "sourcing_guard" / "data" / "misses.json"
_SAMPLES = _ROOT / "sourcing_guard" / "data" / "experience_samples.json"

#: 화면에 내보내는 이름. **괄호 묶음을 전부 뗀다** - 앞머리만 떼는
#: `record_samples.clean_title` 보다 세다.
#:
#: ⚠ 이유: 이 목록은 공급사가 붙인 제목을 **그대로** 옮기는 자리라 상호가
#:   가운데·끝에도 들어온다. 실측에서 `…[효정무역]` 이 끝에 있었다. 어느
#:   괄호가 상호이고 어느 것이 규격인지 자동으로 가를 수 없으므로 전부 뗀다 -
#:   남기는 쪽이 위험하다 (총괄 §3 "한 글자도 안 나간다").
# ⚠ 상한 80 이다. 30 으로 뒀다가 `[40cm 월레스와그로밋 … 봉제 안고자는 선물]`
#   한 줄을 놓쳤다 - 도매 제목의 괄호는 길다. 상한 없는 `*` 는 줄 끝까지
#   먹을 수 있어 쓰지 않는다.
_BRACKETS = re.compile(r"[\[(（【][^\])）】]{0,80}[\])）】]")


def display(name: str) -> str:
    return " ".join(_BRACKETS.sub(" ", name).split())


def _reasons() -> dict[tuple[str, str], tuple[str, str]]:
    """검수 파일의 `(상품명, 붙은 품목) → (유형, 왜 틀렸나)`.

    ⚠ 사람이 적은 설명이다. 여기서 문장을 만들지 않는다 (R5).
    """
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for line in _AUDIT.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, item, kind, why = parts[0], parts[1], parts[2], parts[3]
        out[(name, item)] = (kind, why)
    return out


def main() -> int:
    scope = load_scope()
    wrong_tbl, vague_tbl = load_audit()
    reasons = _reasons()

    rows = [r for r in json.loads(_SRC.read_text(encoding="utf-8"))
            if scope.get(r["name"])]
    kats = MagicMock()
    kats.lookup_certification_cached.return_value = MagicMock(record=None)
    rules = RuleBook()
    got = {r["name"]: grades_for(r, kats, rules) for r in rows}

    reviewed = load_reviewed_pairs("tests/fixtures/단건경로_claude_235.json")
    counts = tally(got, scope=scope, reviewed=reviewed)

    base = BASELINE[BASELINE_EXTRACTOR]
    drift = {k: (counts[k], base[k]) for k in
             ("denominator", "ok", "wrong", "missed", "vague", "off_target")
             if counts[k] != base[k]}
    if drift:
        print("기준선과 어긋난다 - 파일을 만들지 않는다:", file=sys.stderr)
        for k, (now, want) in drift.items():
            print(f"  {k}: 지금 {now} · 기준선 {want}", file=sys.stderr)
        return 2

    target = [n for n in got if scope.get(n) == "대상"]
    hit = [n for n in target if got[n]]

    out_wrong, out_vague, out_missed = [], [], []
    for name in hit:
        call = verdict(name, got[name], wrong_tbl, vague_tbl, reviewed)
        if call not in ("wrong", "vague"):
            continue
        # 검수 설명은 **붙은 품목별**로 적혀 있다. 붙은 것 중 설명이 있는 것.
        said = got[name]
        kind, why = "", ""
        for item in said:
            if (name, item) in reasons:
                kind, why = reasons[(name, item)]
                break
        row = {"name": display(name), "said": said, "kind": kind, "why": why}
        (out_wrong if call == "wrong" else out_vague).append(row)

    for name in target:
        if not got[name]:
            out_missed.append({"name": display(name)})

    # ⚠⚠ 체험 표본 열 개 중 **이 목록에 들어 있는 것**을 함께 적는다.
    #   "여기 있는 것은 저희가 맞힌 예입니다" 라고만 두면 그 카드에는 거짓이
    #   된다 - 실측에서 GREEN 한 장(봉제인형)이 미매칭 19 에 있었다.
    #   감추지 말고 그 카드에 적는다. 그게 이 페이지가 존재하는 이유와 같다.
    buckets: dict[str, str] = {}
    if _SAMPLES.exists():
        picked = {clean_title(n): call for n, call in (
            [(n, "missed") for n in target if not got[n]]
            + [(n, verdict(n, got[n], wrong_tbl, vague_tbl, reviewed)) for n in hit]
        ) if call in ("missed", "wrong", "vague")}
        for item in json.loads(_SAMPLES.read_text(encoding="utf-8"))["items"]:
            call = picked.get(item["title"])
            if call:
                buckets[item["cert_number"]] = call

    payload = {
        "_기록": (
            "「우리가 틀린 것」 자료. scripts/build_misses.py 가 만든다 "
            "(LLM·네트워크 0회). 설명은 사람이 검수해 적은 것이고 여기서 "
            "문장을 만들지 않는다."
        ),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "extractor": BASELINE_EXTRACTOR,
        "counts": {k: counts[k] for k in
                   ("denominator", "ok", "wrong", "vague", "missed", "off_target")},
        "wrong": out_wrong,
        "vague": out_vague,
        "missed": out_missed,
        # 번호 → 갈래. 체험 표본 카드가 이것을 보고 스스로 밝힌다.
        "sample_buckets": buckets,
    }

    print(f'대상 {counts["denominator"]} · 정답 {counts["ok"]} · '
          f'오답 {len(out_wrong)} · 애매 {len(out_vague)} · 미매칭 {len(out_missed)}')
    with _OUT.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print(f"→ {_OUT} ({_OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
