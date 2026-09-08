#!/usr/bin/env python
"""A-5 앞부분. **LLM 없이** 도매꾹 필드가 실제로 무엇을 주는지 센다.

세 가지를 잰다. 첫 줄이 가장 중요하다.

1. **"채워져 있지만 내용은 없는" 비율**
   고시 항목이 값을 갖고 있지만 그 값이 "상세설명참조"·"[상세정보 별도표기]"
   류인 경우다. 참조.md §7 이 탐침 1건에서 6개 중 5개가 이 류였다고 적었고,
   **그 비율이 이 API 가 상세페이지를 대신하는 정도다.** 이 숫자가 다음 결정을
   정한다.

2. **인증번호 축** — `cert=Y` · `no≠'-'` · `exem=Y` · SafetyKorea 조회 성공/실패
   우리 서비스의 첫 빨간불이 여기서 나온다. `safetyCert` 는 공급사가 입력한
   값이므로(CLAUDE.md R4) **대조가 우리 일이다.**

   ⚠ **번호를 제도별로 갈라서 조회한다.** `certType` 이 `방송통신기자재` 인
     번호는 전파인증(적합성평가)이고 **SafetyKorea 소관이 아니다.** 그것을
     SafetyKorea 에 물으면 당연히 안 나오는데, 그 0 을 "인증 없음" 으로 읽으면
     R3-b 를 정면으로 어긴다 - 부재는 증거가 아니다. 전파 쪽 대조는
     `rra_client`(emsit/rra)의 일이다.

3. **`desc.contents.item` 태그 제거 후 텍스트 길이 분포** — 중앙값 · 0인 비율

⚠ SafetyKorea 조회는 `KATS_SERVICE_KEY` 가 있어야 실호출한다. 없으면 목으로
  돌고 그 사실을 보고에 적는다 - 목 결과를 실측으로 보고하면 안 된다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.config import settings  # noqa: E402
from sourcing_guard.domeggook_fields import INFODUTY_CERT, is_placeholder  # noqa: E402
from sourcing_guard.kats_client import KatsApiError, KatsClient  # noqa: E402
from sourcing_guard.rra_client import is_rf_number  # noqa: E402

_STRUCT = Path("tests/fixtures/도매꾹_구조_2026-09-08.json")


#: `certType` 이 이것이면 전파인증(적합성평가)이고 **SafetyKorea 소관이 아니다.**
RF_CERT_TYPE = "방송통신기자재"


def cert_axis(rows: list[dict]) -> dict:
    """인증 블록을 제도별로 가른다.

    ⚠ **`certType` 으로 가른다. 번호 모양으로 가르지 않는다.** 도매꾹이 제도를
      직접 적어 주고, 번호 모양은 우리 정규식이 못 잡는 표기가 있다 - 실측에서
      `MSIP-CMI-*` 2개가 `rra_client.RF_NUMBER_RE` 를 통과하지 못했다.

    ⚠ 전파 번호를 SafetyKorea 에 물으면 당연히 안 나오는데, 그 0 을 "인증 없음"
      으로 읽으면 R3-b 를 정면으로 어긴다. 그래서 **묻지 않는다.**
    """
    out: dict = {
        "블록있음": [r for r in rows if r["safetyCert"]],
        "cert_Y": [], "번호실제": [], "exem_Y": [], "이미지만": [],
        "kats": {}, "rf": [], "certType": Counter(),
    }
    for r in rows:
        for c in r["safetyCert"]:
            out["certType"][(c.get("certType"), c.get("certName"))] += 1
            if str(c.get("cert") or "").upper() == "Y":
                out["cert_Y"].append(r)
            if str(c.get("exem") or "").upper() == "Y":
                out["exem_Y"].append(r)
            raw = str(c.get("no") or "").strip()
            if raw and raw != "-" and str(c.get("useNo") or "").upper() != "N":
                out["번호실제"].append(r)
                if str(c.get("certType") or "") == RF_CERT_TYPE:
                    out["rf"].append((raw, r.get("표본_상품명", "")))
                else:
                    out["kats"].setdefault(
                        r.get("도매꾹_상품번호", ""), []
                    ).append(raw)
            elif str(c.get("useImgUrl") or "").upper() == "Y" and c.get("imgUrl"):
                out["이미지만"].append(r)
    return out


def pct(n: int, d: int) -> str:
    return f"{n / d * 100:.1f}%" if d else "—"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--struct", default=str(_STRUCT))
    ap.add_argument("--scope", default="대상",
                    help="대상 / 전체 - 분모를 무엇으로 할지")
    ap.add_argument("--no-lookup", action="store_true",
                    help="SafetyKorea 조회를 건너뛴다")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    payload = json.loads(Path(args.struct).read_text(encoding="utf-8"))
    rows = payload["상품"]
    if args.scope == "대상":
        rows = [r for r in rows if r["대상분류"] == "대상"]
    n = len(rows)
    if not n:
        raise SystemExit("분모가 0 입니다")

    print(f"{'=' * 74}")
    print(f"A-5 앞부분 · 도매꾹 필드 실측 (LLM 없음)")
    print(f"  재료 {args.struct}")
    print(f"  분모 {args.scope} {n}건 (채택 {payload['건수']['채택']} 중)")
    print(f"{'=' * 74}")

    # ── 1. 채워져 있지만 내용은 없는 ────────────────────────────────
    item_rows = [e for r in rows for e in r["infoDuty"]["item"]
                 if e["type"] == "item"]
    empty_rows = [e for e in item_rows if e["내용없음"]]
    all_empty = [r for r in rows
                 if (its := [e for e in r["infoDuty"]["item"] if e["type"] == "item"])
                 and all(e["내용없음"] for e in its)]
    cert_rows = [e for r in rows for e in r["infoDuty"]["item"]
                 if INFODUTY_CERT in (e["name"] or "")]
    cert_empty = [e for e in cert_rows if e["내용없음"]]

    print("\n[1] 채워져 있지만 내용은 없는 비율  ← 이 숫자가 다음 결정을 정한다\n")
    print(f"  고시 항목(type=item) {len(item_rows)}줄 중 내용 없음"
          f"  **{len(empty_rows)}줄 ({pct(len(empty_rows), len(item_rows))})**")
    print(f"  항목 전부가 내용 없는 상품          {len(all_empty)}/{n}"
          f" ({pct(len(all_empty), n)})")
    print(f"  '법에 의한 인증·허가' 항목          {len(cert_rows)}건 중"
          f" 내용 없음 {len(cert_empty)} ({pct(len(cert_empty), len(cert_rows))})")

    per_product = sorted(
        len([e for e in r["infoDuty"]["item"]
             if e["type"] == "item" and e["내용없음"]])
        / max(1, len([e for e in r["infoDuty"]["item"] if e["type"] == "item"]))
        for r in rows
    )
    print(f"  상품별 내용없음 비율 중앙값         "
          f"{per_product[len(per_product) // 2] * 100:.0f}%")

    worst = Counter(e["name"] for e in empty_rows)
    print("\n  내용 없음이 많은 항목 (상위 8)")
    for name, c in worst.most_common(8):
        tot = sum(1 for e in item_rows if e["name"] == name)
        print(f"    {c:3}/{tot:<3} {pct(c, tot):>6}  {name[:56]}")

    # ── 2. 인증번호 축 ──────────────────────────────────────────────
    axis = cert_axis(rows)
    has_block, cert_y, no_real, exem_y, img_only = (
        axis["블록있음"], axis["cert_Y"], axis["번호실제"], axis["exem_Y"],
        axis["이미지만"],
    )
    numbers, rf_numbers, cert_types = axis["kats"], axis["rf"], axis["certType"]

    print(f"\n[2] 인증번호 축\n")
    print(f"  safetyCert 블록이 있는 상품    {len(has_block)}/{n}"
          f" ({pct(len(has_block), n)})")
    print(f"    cert=Y                       {len(cert_y)}")
    print(f"    no 가 실제 값 (≠'-', useNo≠N) {len(no_real)}")
    print(f"    exem=Y (면제 표기)            {len(exem_y)}")
    print(f"    번호 없이 이미지만            {len(img_only)}"
          f"   ← kc_numbers_from_image 경로")
    print(f"\n  certType 분포 (인증 블록 {sum(cert_types.values())}개)")
    for (t, nm), c in cert_types.most_common():
        print(f"    {c:3}  {str(t):<18} {nm}")
    print(f"\n  ⚠ **제도가 섞여 있다.** 번호 {len(no_real)}개 중"
          f" 전파(방송통신기자재) {len(rf_numbers)}개는 **SafetyKorea 소관이"
          f" 아니다.**")
    print(f"     SafetyKorea 에 물을 수 있는 번호는 {sum(len(v) for v in numbers.values())}개"
          f" · 상품 {len(numbers)}/{n}건 ({pct(len(numbers), n)}).")

    lookup_report: dict = {"건너뜀": True}
    if not args.no_lookup and numbers:
        client = KatsClient(settings.kats_base_url, settings.kats_service_key)
        live = not client._mock
        print(f"\n  SafetyKorea 대조 — {'실호출' if live else '⚠ 목 모드 (키 없음)'}")
        found, missing, failed = [], [], []
        for dome_no, nums in sorted(numbers.items()):
            for raw in nums:
                try:
                    rec = client.lookup_certification(raw)
                except KatsApiError as exc:
                    failed.append((raw, str(exc)[:60]))
                    continue
                (found if rec else missing).append((raw, rec))
        flat = sum(len(v) for v in numbers.values())
        print(f"    번호 {flat}개 — 조회됨 {len(found)}"
              f" · 조회 안 됨 {len(missing)} · 호출 실패 {len(failed)}")
        print(f"    조회됨 {pct(len(found), flat)}")
        if found:
            st = Counter(r.state.value if r else "?" for _no, r in found)
            print(f"    상태 분포 {dict(st)}")
            bad = [(raw, r) for raw, r in found
                   if r and r.state.value not in ("ok",)]
            if bad:
                print(f"    ⚠ **상태가 'ok' 가 아닌 것 {len(bad)}건** — R3-b 의"
                      f" 적극적 증거다")
                for raw, r in bad:
                    print(f"      {r.state.value:<9} {raw:<20}"
                          f" {(r.status or '')[:16]} · {(r.product_name or '')[:26]}")
        if missing:
            print("    조회 안 된 번호")
            for raw, _ in missing:
                print(f"      {raw}")
        if failed:
            print(f"    호출 실패 예: {failed[:3]}")
        lookup_report = {
            "실호출": live, "번호수": flat, "조회됨": len(found),
            "조회안됨": len(missing), "호출실패": len(failed),
            "조회안된번호": [raw for raw, _ in missing],
            "상태분포": dict(Counter(r.state.value if r else "?" for _no, r in found)),
            "상태가_ok_아닌것": [
                {"번호": raw, "상태": r.state.value, "원문": r.status,
                 "제품명": r.product_name}
                for raw, r in found if r and r.state.value != "ok"
            ],
        }
        if not live:
            print("    ⚠ 목 모드 결과다. 실측으로 보고하지 말 것.")

    if rf_numbers:
        print(f"\n  전파인증 번호 {len(rf_numbers)}개 — **SafetyKorea 에 묻지 않았다**")
        for raw, nm in sorted(rf_numbers):
            mark = "RF_NUMBER_RE 인식" if is_rf_number(raw) else "⚠ 정규식 미인식"
            print(f"    {raw:<24} {mark:<18} {nm[:30]}")
        unmatched = [raw for raw, _ in rf_numbers if not is_rf_number(raw)]
        if unmatched:
            print(f"    ⚠ `rra_client.RF_NUMBER_RE` 가 못 잡는 표기 {len(unmatched)}개:"
                  f" {unmatched}")
            print(f"      MSIP-CMI-* 는 미래창조과학부 시절 전파인증 번호다."
                  f" 정규식은 R-[CRI]-* 와 KCC-* 만 본다.")

    # ── 3. desc 길이 ────────────────────────────────────────────────
    lens = sorted(r["desc_본문_길이"] for r in rows)
    zero = sum(1 for x in lens if x == 0)
    print(f"\n[3] desc.contents.item 태그 제거 후 텍스트 길이\n")
    print(f"  0자      {zero}/{n} ({pct(zero, n)})")
    print(f"  중앙값   {lens[len(lens) // 2]}자")
    print(f"  평균     {statistics.mean(lens):.0f}자 · 최대 {lens[-1]}자")
    buckets = {
        "0": zero,
        "1-99": sum(1 for x in lens if 0 < x < 100),
        "100-499": sum(1 for x in lens if 100 <= x < 500),
        "500+": sum(1 for x in lens if x >= 500),
    }
    print(f"  분포     {buckets}")

    print(f"\n{'=' * 74}")
    print("한 줄 결론")
    print(f"  고시 항목의 {pct(len(empty_rows), len(item_rows))} 가 '내용 없음' 이고,")
    print(f"  상세 본문은 {pct(zero, n)} 가 0자이며,")
    print(f"  SafetyKorea 에 대조할 수 있는 인증번호는 {pct(len(numbers), n)} 에만 있다.")
    print("  → 이 API 가 대신해 주는 것은 상세페이지가 아니라 **구조화된 고시·인증")
    print("     필드 몇 개**다. 그것도 절반 넘게 비어 있다.")

    if args.out:
        out = {
            "분모": {"기준": args.scope, "n": n},
            "내용없음": {
                "항목줄": len(item_rows), "내용없음줄": len(empty_rows),
                "전부빈상품": len(all_empty),
                "인증항목": len(cert_rows), "인증항목_내용없음": len(cert_empty),
                "항목별": dict(worst),
            },
            "인증번호축": {
                "블록있음": len(has_block), "cert_Y": len(cert_y),
                "번호실제": len(no_real), "exem_Y": len(exem_y),
                "이미지만": len(img_only),
                "certType분포": {f"{t} / {nm}": c
                                 for (t, nm), c in cert_types.items()},
                "전파번호": [raw for raw, _ in rf_numbers],
                "전파번호_정규식미인식": [raw for raw, _ in rf_numbers
                                        if not is_rf_number(raw)],
                "KATS_번호있는상품": len(numbers),
                "대조": lookup_report,
            },
            "desc길이": {"0자": zero, "중앙값": lens[len(lens) // 2],
                         "최대": lens[-1], "분포": buckets},
        }
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"\n원자료 → {args.out}")


if __name__ == "__main__":
    main()
