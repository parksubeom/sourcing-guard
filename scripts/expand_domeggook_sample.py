#!/usr/bin/env python
"""A-3″ 분모를 늘린다. **채택 규칙은 손대지 않는다.**

1차 수집(`collect_domeggook.py`)이 대상 135 중 57건만 채택했다. 분모가 절반
이하면 숫자의 방향은 보이지만 크기는 말할 수 없다. 그래서 둘을 한다.

(1) 0건 95건 — 검색 실패와 사라짐을 가른다
--------------------------------------------
**검색어만** 바꿔 다시 친다. 채택 판정은 그대로 `title` 정규화 정확 일치다.

    2차   [대괄호]·(괄호)·슬래시 뒤 꼬리를 떼고 **앞 3토큰**
    3차   **앞 2토큰** + sz=200

2·3차에서 정확 일치가 나오면 "검색 실패" 였던 것이고, 세 번 다 검색 결과가
0이면 "사라짐 추정" 이다. 결과는 있는데 정확 일치가 없으면 "검색실패-미해결" -
우리 검색어나 제목 정규화로 못 찾은 것이고, 사라졌다고 말할 근거는 없다.

⚠ **비교 대상은 짧게 만든 검색어가 아니라 원래 표본 상품명이다.** 앞 2토큰으로
  찾았다고 그 상품이 표본 상품인 것은 아니다.

(2) 복수 40건 — 임의로 고르지 않고 일치 검사로 채택
---------------------------------------------------
같은 제목 상품 **전부**를 `view` 로 받아 아래가 정규화 후 모두 같으면 채택한다.
하나라도 다르면 "복수-불일치" 로 빼고 **달랐던 필드명을 적는다.**

    infoDuty.type
    infoDuty.item[] 중 type=item 인 것들의 (name, desc)
    safetyCert[].{cert, certType, certName, no, exem}
    detail.country · detail.manufacturer · detail.model

가까운 것을 고르는 게 아니라 **같은 것을 확인하는 것**이다. 같으면 어느 것을
쓰든 측정값이 같으므로 첫 번째를 쓴다.

⚠ 저장은 `domeggook_pii.write_sanitized()` 를 거친다 (CLAUDE.md R4 · §6).
⚠ 프로세스 하나만. `python -u`. 429 는 재시도하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.domeggook_client import (  # noqa: E402
    MAX_VIEW_BATCH,
    DomeggookApiError,
    DomeggookClient,
    DomeggookRateLimited,
)
from sourcing_guard.domeggook_fields import infoduty_rows, safety_certs  # noqa: E402
from sourcing_guard.domeggook_pii import residual, write_sanitized  # noqa: E402
from sourcing_guard.config import _load_dotenv  # noqa: E402

_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")

# 비교할 필드. 여기에 없는 것이 달라도 같은 상품으로 본다 - 재고·가격·배송은
# 셀러마다 다르고 우리 측정에 안 쓴다.
_CERT_KEYS = ("cert", "certType", "certName", "no", "exem")


def norm_title(name: str) -> str:
    """`collect_domeggook.norm_title` 과 **같아야 한다.**"""
    s = unicodedata.normalize("NFKC", name or "")
    return re.sub(r"[\s\-_/·,.()\[\]{}]+", "", s).upper()


def norm_field(value) -> str:
    """필드 비교용. NFKC + 공백 제거.

    ⚠ 기호는 지우지 않는다 - 인증번호의 하이픈은 의미가 있다.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


_BRACKETED = re.compile(r"[\[\(][^\]\)]*[\]\)]")
_AFTER_SLASH = re.compile(r"/.*$", re.S)


def _strip_decorations(name: str) -> str:
    """[괄호] 묶음을 통째로 빼고, 첫 슬래시 뒤를 자른다.

    ⚠ "괄호·슬래시 **뒤** 꼬리를 뗀다" 를 글자 그대로 "첫 괄호 이후 전부" 로
      읽으면 안 된다. 상품명 앞머리에 `[겨울필수템]` 처럼 홍보 딱지가 붙은
      줄이 있어서, 그렇게 자르면 검색어가 **빈 문자열**이 된다. 그래서
      괄호는 위치에 상관없이 **묶음만** 빼고, 슬래시는 뒤를 자른다.
    """
    head = _BRACKETED.sub(" ", name)
    head = _AFTER_SLASH.sub(" ", head)
    return re.sub(r"[\[\]\(\)]", " ", head)


def query_2nd(name: str) -> str:
    """괄호 묶음·슬래시 뒤 꼬리를 떼고 앞 3토큰."""
    return " ".join(_strip_decorations(name).split()[:3])


def query_3rd(name: str) -> str:
    """앞 2토큰. 괄호만 떼고 슬래시는 살린다 - 3차는 더 넓게 던진다."""
    head = re.sub(r"[\[\]\(\)]", " ", _BRACKETED.sub(" ", name))
    return " ".join(head.split()[:2])


def exact_matches(res: dict, want: str) -> tuple[list[dict], int]:
    """정확 일치 후보들과 검색 결과 총건수."""
    root = res.get("domeggook") or {}
    items = ((root.get("list") or {}).get("item")) or []
    if isinstance(items, dict):
        items = [items]
    total = (root.get("header") or {}).get("numberOfItems")
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = len(items)
    return [it for it in items if norm_title(it.get("title", "")) == want], total


def fingerprint(item: dict) -> dict:
    """일치 검사에 쓰는 필드만 뽑아 정규화한다."""
    detail = item.get("detail") or {}
    info = detail.get("infoDuty") or {}
    rows = sorted(
        (norm_field(r.get("name")), norm_field(r.get("desc")))
        for r in infoduty_rows(item)
        if r.get("type") == "item"
    )
    certs = sorted(
        tuple(norm_field(c.get(k)) for k in _CERT_KEYS) for c in safety_certs(item)
    )
    return {
        "infoDuty.type": norm_field(info.get("type")),
        "infoDuty.item": rows,
        "safetyCert": certs,
        "detail.country": norm_field(detail.get("country")),
        "detail.manufacturer": norm_field(detail.get("manufacturer")),
        "detail.model": norm_field(detail.get("model")),
    }


def differing_fields(prints: list[dict]) -> list[str]:
    first = prints[0]
    return [k for k in first if any(p.get(k) != first[k] for p in prints[1:])]


def view_all(client: DomeggookClient, nos: list[str], log: list[dict]) -> dict[str, dict]:
    """상품번호 → 상세. 배치로 부른다."""
    out: dict[str, dict] = {}
    uniq = list(dict.fromkeys(nos))
    batches = [uniq[i:i + MAX_VIEW_BATCH] for i in range(0, len(uniq), MAX_VIEW_BATCH)]
    for bi, batch in enumerate(batches, 1):
        try:
            res = client.view([int(n) for n in batch])
        except DomeggookRateLimited as exc:
            print(f"  429 에서 멈춥니다: {exc}", flush=True)
            break
        except DomeggookApiError as exc:
            print(f"  [{bi}/{len(batches)}] !! {exc}", flush=True)
            log.append({"nos": batch, "error": str(exc)})
            continue
        log.append({"nos": batch, "response": res})
        got = ((res.get("domeggook") or {}).get("item")) or []
        if isinstance(got, dict):
            got = [got]
        for it in got:
            no = str((it.get("basis") or {}).get("no") or "")
            if no:
                out[no] = it
        print(f"  [{bi}/{len(batches)}] {len(batch)}개 요청 → {len(got)}개 응답",
              flush=True)
    return out


def load_scope() -> dict[str, tuple[int, str]]:
    scope: dict[str, tuple[int, str]] = {}
    for line in _SCOPE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        no, verdict, name, _why = line.split("\t")
        scope[name] = (int(no), verdict)
    return scope


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="tests/fixtures/도매꾹_정제_2026-09-08")
    ap.add_argument("--out", default="")
    ap.add_argument("--limit-zero", type=int, default=0)
    args = ap.parse_args()

    _load_dotenv()
    key = os.getenv("DOMEGGOOK_API_KEY")
    if not key:
        raise SystemExit("DOMEGGOOK_API_KEY 가 없습니다 (.env)")

    base = Path(args.base)
    adopted = json.loads((base / "채택.json").read_text(encoding="utf-8"))
    out_dir = Path(args.out or f"tests/fixtures/도매꾹_확장_{date.today():%Y-%m-%d}")
    out_dir.mkdir(parents=True, exist_ok=True)

    scope = load_scope()
    client = DomeggookClient(key)
    started = time.time()

    # ── (1) 0건 재검색 ──────────────────────────────────────────────
    zero = adopted["zero"]
    if args.limit_zero:
        zero = zero[: args.limit_zero]
    retry_log: list[dict] = []
    retry_result: dict[str, dict] = {}
    print(f"(1) 0건 재검색 {len(zero)}건 × 2회", flush=True)
    stopped = False
    for i, name in enumerate(zero, 1):
        if stopped:
            break
        want = norm_title(name)
        record: dict = {"name": name, "rounds": []}
        for label, query, sz in (("2차", query_2nd(name), 50),
                                 ("3차", query_3rd(name), 200)):
            if not query:
                record["rounds"].append(
                    {"round": label, "query": query, "skipped": "검색어가 비었다"}
                )
                continue
            try:
                res = client.search(query, sz=sz)
            except DomeggookRateLimited as exc:
                print(f"\n429 에서 멈춥니다: {exc}", flush=True)
                print(f"  진행 {i - 1}/{len(zero)} - 재시도하지 않습니다.", flush=True)
                stopped = True
                break
            except DomeggookApiError as exc:
                record["rounds"].append(
                    {"round": label, "query": query, "error": str(exc)}
                )
                continue
            retry_log.append(
                {"query": query, "round": label, "for": name, "response": res}
            )
            hits, total = exact_matches(res, want)
            record["rounds"].append({
                "round": label, "query": query, "total": total,
                "exact": [{"no": str(h["no"]), "title": h.get("title")}
                          for h in hits],
            })
            if hits:
                break

        retry_result[name] = record
        hit = next((r for r in record["rounds"] if r.get("exact")), None)
        counted = [r for r in record["rounds"] if "total" in r]
        if hit:
            mark = f"일치{len(hit['exact'])}"
        elif not counted:
            mark = "호출실패"
        elif all(r["total"] == 0 for r in counted):
            mark = "결과0"
        else:
            mark = "불일치"
        print(f"  [{i:3}/{len(zero)}] {mark:<6} · {name[:44]}", flush=True)

    write_sanitized(out_dir / "재검색.json", retry_log)

    # ── (2) 복수 후보 상세 ──────────────────────────────────────────
    # 1차 복수 + 재검색에서 새로 나온 복수를 함께 다룬다.
    groups: list[dict] = [
        {"name": m["query"], "source": "1차",
         "nos": [c["no"] for c in m["candidates"]]}
        for m in adopted["multi"]
    ]
    for name, rec in retry_result.items():
        hit = next((x for x in rec["rounds"] if x.get("exact")), None)
        if hit and len(hit["exact"]) > 1:
            groups.append({"name": name, "source": hit["round"],
                           "nos": [e["no"] for e in hit["exact"]]})

    single_new = {
        name: next(x for x in rec["rounds"] if x.get("exact"))["exact"][0]["no"]
        for name, rec in retry_result.items()
        if (h := next((x for x in rec["rounds"] if x.get("exact")), None))
        and len(h["exact"]) == 1
    }

    need = [n for g in groups for n in g["nos"]] + list(single_new.values())
    view_log: list[dict] = []
    print(f"\n(2) 상세 {len(set(need))}건 "
          f"(복수 후보 {sum(len(g['nos']) for g in groups)} · 2·3차 채택 {len(single_new)})",
          flush=True)
    details = view_all(client, need, view_log)
    write_sanitized(out_dir / "상세_확장.json", view_log)

    for g in groups:
        prints = [fingerprint(details[n]) for n in g["nos"] if n in details]
        g["received"] = len(prints)
        if len(prints) < 2:
            g["verdict"] = "판정불가(상세 부족)"
            g["differs"] = []
            continue
        diff = differing_fields(prints)
        g["differs"] = diff
        g["verdict"] = "복수-불일치" if diff else f"복수-일치 {len(prints)}건"
        if not diff:
            g["picked"] = g["nos"][0]

    # ── 보고 ────────────────────────────────────────────────────────
    first_pick = {p["query"]: p["no"] for p in adopted["picked"]}
    final: dict[str, dict] = {
        name: {"no": no, "how": "1차"} for name, no in first_pick.items()
    }
    for name, no in single_new.items():
        rnd = next(x for x in retry_result[name]["rounds"] if x.get("exact"))["round"]
        final[name] = {"no": no, "how": rnd}
    for g in groups:
        if g.get("picked"):
            final[g["name"]] = {"no": g["picked"], "how": f"복수일치({g['source']})"}

    buckets: dict[str, list[str]] = {
        "채택-1차": [], "채택-2·3차": [], "채택-복수일치": [],
        "사라짐 추정": [], "복수-불일치": [], "검색실패-미해결": [],
    }
    multi_names = {g["name"]: g for g in groups}
    for name, (_no, verdict) in scope.items():
        if verdict != "대상":
            continue
        f = final.get(name)
        if f and f["how"] == "1차":
            buckets["채택-1차"].append(name)
        elif f and f["how"] in ("2차", "3차"):
            buckets["채택-2·3차"].append(name)
        elif f:
            buckets["채택-복수일치"].append(name)
        elif name in multi_names:
            buckets["복수-불일치"].append(name)
        elif name in retry_result:
            rounds = [r for r in retry_result[name]["rounds"] if "total" in r]
            if rounds and all(r["total"] == 0 for r in rounds):
                buckets["사라짐 추정"].append(name)
            else:
                buckets["검색실패-미해결"].append(name)
        else:
            buckets["검색실패-미해결"].append(name)

    payload = {
        "채택": final,
        "재검색": retry_result,
        "복수판정": groups,
        "분류별_대상": {k: sorted(v) for k, v in buckets.items()},
    }
    left = residual(payload)
    if left:
        raise SystemExit(f"확장 결과에 개인정보 패턴이 남았습니다: {left}")
    (out_dir / "확장채택.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    n_target = sum(1 for v in scope.values() if v[1] == "대상")
    total = sum(len(v) for v in buckets.values())
    adopted_n = (len(buckets["채택-1차"]) + len(buckets["채택-2·3차"])
                 + len(buckets["채택-복수일치"]))

    print(f"\n{'=' * 74}")
    print(f"A-3″ 확장 · {out_dir}\n")
    print(f"  대상 채택  {len(buckets['채택-1차'])} → {adopted_n}"
          f"   (1차 {len(buckets['채택-1차'])}"
          f" · 2·3차 +{len(buckets['채택-2·3차'])}"
          f" · 복수일치 +{len(buckets['채택-복수일치'])})")
    print(f"  사라짐 추정        {len(buckets['사라짐 추정'])}")
    print(f"  복수-불일치        {len(buckets['복수-불일치'])}")
    print(f"  검색실패-미해결    {len(buckets['검색실패-미해결'])}")
    print(f"  ────────────────────────")
    print(f"  합                 {total}  (대상 {n_target})"
          f"  {'✅' if total == n_target else '❌ 합이 맞지 않는다'}")

    diff_count: dict[str, int] = {}
    for g in groups:
        for d in g["differs"]:
            diff_count[d] = diff_count.get(d, 0) + 1
    print(f"\n  복수 그룹 {len(groups)}개 — 판정")
    ok = sum(1 for g in groups if g["verdict"].startswith("복수-일치"))
    print(f"    일치 {ok} · 불일치 {sum(1 for g in groups if g['verdict'] == '복수-불일치')}"
          f" · 판정불가 {sum(1 for g in groups if g['verdict'] == '판정불가(상세 부족)')}")
    if diff_count:
        print("    달랐던 필드 (그룹 수)")
        for k, v in sorted(diff_count.items(), key=lambda x: -x[1]):
            print(f"      {k:26} {v}")
    print(f"\n  호출 수  {client.calls}회 · {time.time() - started:.0f}초")
    print(f"  → {out_dir / '확장채택.json'}")


if __name__ == "__main__":
    main()
