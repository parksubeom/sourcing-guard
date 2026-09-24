"""사본 두 판을 **필드 단위로** 대조한다 — 부분 재기록이 무엇을 흔들었나.

    python -u scripts/diff_showcase.py <옛 사본.json> [새 사본.json]

왜 (총괄 2026-09-22)
--------------------
`build_showcase.py scan --only` 는 LLM 추출까지 다시 돈다. 그래서 재조회는
**인증 근거만 고치는 것이 아니고**, 다시 스캔한 카드는 다른 추출 회차에서 온다.

그래서 카드마다 갈라야 한다:

    ⑴ 인증 축 관련만 바뀐 카드   → 반영한다. 이게 고치려던 것이다
    ⑵ 그 밖이 바뀐 카드          → 반영하지 않고 목록에서 뺀다

⚠⚠ **신호가 바뀌었다고 원인을 인증이라 단정하지 않는다.** 어느 축이 바뀌었는지
  축 단위로 대조해서 적는다 - 추론으로 메우면 그게 R1 이 막는 자리다.
⚠ 실호출 0회. 두 파일만 읽는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

NEW = Path("sourcing_guard/data/showcase.json")

#: 인증 축에 속하는 finding 종류. 이 밖이 바뀌면 ⑵ 다.
_CERT_KINDS = {"kc_verified", "kc_not_found", "kc_revoked", "kc_expired",
               "kc_suspended", "kc_under_action", "kc_image_candidate",
               "kc_state_unknown", "lookup_failed"}


def _findings(result: dict) -> list[tuple]:
    return [(f.get("kind"), f.get("signal"), f.get("source_url"),
             f.get("statement_ko")) for f in (result.get("findings") or [])]


def _axes(result: dict) -> dict:
    return {a.get("key"): (a.get("done"), a.get("label"), a.get("note"))
            for a in (result.get("axes") or [])}


def compare(old: dict, new: dict) -> dict:
    """한 카드의 변화. 축별로 나눠 돌려준다."""
    o, n = old.get("result") or {}, new.get("result") or {}
    out: dict[str, list[str]] = {"cert": [], "other": []}

    of, nf = _findings(o), _findings(n)
    if of != nf:
        og = {k for k, *_ in of}
        ng = {k for k, *_ in nf}
        for kind in sorted(og ^ ng):
            bucket = "cert" if kind in _CERT_KINDS else "other"
            out[bucket].append(f"finding {kind} {'사라짐' if kind in og else '생김'}")
        for k in sorted(og & ng):
            a = [x for x in of if x[0] == k]
            b = [x for x in nf if x[0] == k]
            if a != b:
                bucket = "cert" if k in _CERT_KINDS else "other"
                out[bucket].append(f"finding {k} 내용 바뀜")

    oa, na = _axes(o), _axes(n)
    for key in sorted(set(oa) | set(na)):
        if oa.get(key) != na.get(key):
            bucket = "cert" if key == "cert" else "other"
            out[bucket].append(f"축 {key}: {oa.get(key)} → {na.get(key)}")

    of_, nf_ = o.get("facts") or {}, n.get("facts") or {}
    for key in sorted(set(of_) | set(nf_)):
        if of_.get(key) != nf_.get(key):
            bucket = "cert" if key in ("kc_numbers", "kc_numbers_from_image") else "other"
            out[bucket].append(f"facts.{key}: {of_.get(key)!r} → {nf_.get(key)!r}")

    for key in ("signal", "score", "headline", "coverage_note", "extraction_note"):
        if o.get(key) != n.get(key):
            # 신호·점수는 원인을 단정하지 않는다. 축 변화와 함께 읽는다.
            out["other" if key in ("headline", "coverage_note", "extraction_note")
                else "signal"] = out.get(
                "other" if key in ("headline", "coverage_note", "extraction_note")
                else "signal", [])
            (out["other"] if key in ("headline", "coverage_note", "extraction_note")
             else out.setdefault("signal", [])).append(
                f"{key}: {o.get(key)!r} → {n.get(key)!r}")
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    old_p = Path(sys.argv[1])
    new_p = Path(sys.argv[2]) if len(sys.argv) > 2 else NEW
    old = json.loads(old_p.read_text(encoding="utf-8"))
    new = json.loads(new_p.read_text(encoding="utf-8"))
    o_items = {str(i["no"]): i for i in (old.get("items") or [])}
    n_items = {str(i["no"]): i for i in (new.get("items") or [])}

    print(f"옛 사본 {old_p}  {len(o_items)}장")
    print(f"새 사본 {new_p}  {len(n_items)}장")
    # ⚠ 회차가 쌓이므로 전부 찍으면 길어진다. 수와 **마지막 한 벌**만 낸다.
    rounds = new.get("rescans") or ([new["rescanned"]] if new.get("rescanned") else [])
    print(f"재기록 회차 {len(rounds)}회" + (f" · 마지막 {rounds[-1]}" if rounds else ""))
    print()

    gone = sorted(set(o_items) - set(n_items))
    added = sorted(set(n_items) - set(o_items))
    if gone:
        print(f"빠진 카드 {len(gone)}장: {gone}")
    if added:
        print(f"새 카드 {len(added)}장: {added}")

    only_cert, mixed, same = [], [], 0
    for no in sorted(set(o_items) & set(n_items)):
        d = compare(o_items[no], n_items[no])
        changed = {k: v for k, v in d.items() if v}
        if not changed:
            same += 1
            continue
        other = changed.get("other") or []
        (mixed if other else only_cert).append(no)
        tag = "⑵ 인증 밖도 바뀜" if other else "⑴ 인증 축만"
        print(f"\n=== {no}  {tag} ===")
        for bucket in ("cert", "signal", "other"):
            for line in changed.get(bucket) or []:
                print(f"    [{bucket:6s}] {line}")

    print(f"\n안 바뀐 카드 {same}장")
    print(f"⑴ 인증 축만 바뀐 카드 {len(only_cert)}장: {only_cert}")
    print(f"⑵ 그 밖도 바뀐 카드   {len(mixed)}장: {mixed}")
    print(f"   합 {len(only_cert)}+{len(mixed)} = {len(only_cert)+len(mixed)}"
          f"  (안 바뀐 {same} 포함 총 {same+len(only_cert)+len(mixed)}장)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
