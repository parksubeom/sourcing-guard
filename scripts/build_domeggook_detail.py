#!/usr/bin/env python
"""A-4. 정제본에서 (a) 상세 텍스트와 (b) 구조 JSON 을 만든다. 네트워크 없음.

(a) 상세 텍스트 — `tests/fixtures/도매꾹_상세텍스트_<날짜>.txt`
    `상세30.txt` 와 같은 `===== <번호> =====` 형식이라 기존 측정 스크립트가
    그대로 읽는다. A-5 가 이것을 `/api/v1/scan` 의 `page_text` 로 넣는다.

⚠ **이것은 상세페이지 DOM 텍스트가 아니라 API 필드로 조립한 텍스트다.**
  실제 셀러가 붙여 넣는 것보다 깨끗하다 - 광고 문구·중복·레이아웃 잡음이 없다.
  A-5 숫자에 이 조건을 반드시 함께 적어야 한다. 그리고 이미지 안의 글자는
  애초에 오지 않는다(아래).

⚠ **치환 토큰(`[연락처]` 등) 줄을 지우지 않는다.** 셀러가 붙여 넣는 텍스트에도
  A/S 연락처는 있고, 추출기가 그것을 무시하는지도 측정의 일부다. 다만 원문
  연락처가 아니라 토큰이라는 사실을 파일 머리에 적는다.

(b) 구조 JSON — `tests/fixtures/도매꾹_구조_<날짜>.json`
    `safetyCert` · `country` · `manufacturer` · `model` · `infoDuty` 를 그대로
    옮긴 것. **"상세페이지 텍스트를 파싱하지 않아도 되는" 경로**가 실제로
    무엇을 주는지 이 파일이 답한다 (CLAUDE.md R4).

    `seller` 는 없다. `safetyCert[].imgUrl` 은 남긴다 - 이미지 추출 경로
    (`kc_numbers_from_image`)의 입력이다.

⚠ **desc 는 거의 비어 있다.** `desc.contents.item` 에서 태그를 떼면 317건 중
  292건(92%)이 **0자**다. 상세페이지가 통째로 이미지라는 뜻이다. 그래서 (a)의
  본문은 대부분 고시정보 표와 인증 블록이고, 그것이 이 API 가 상세페이지를
  대신하는 실제 범위다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.domeggook_fields import (  # noqa: E402
    html_to_text,
    infoduty_rows,
    is_placeholder,
    safety_certs,
)
from sourcing_guard.domeggook_pii import TOKENS, residual  # noqa: E402

_SCOPE = Path("tests/fixtures/새표본235_대상분류.tsv")
_CERT_KEYS = ("cert", "certType", "certName", "no", "useNo", "exem", "exemTitle",
              "exemContent1", "exemContent2", "useImgUrl", "imgUrl", "useWarning",
              "warning")

_HEADER = """# 도매꾹 Open API 로 조립한 상세 텍스트 — A-4(a)
#
# 만든 것: scripts/build_domeggook_detail.py   재료: {sources}
# 채택 {n}건 (대상 {n_target} · 비대상 {n_out} · 애매 {n_vague})
#
# 형식은 상세30.txt 와 같다. 한 건은 '===== <번호> =====' 로 시작하고 번호는
# 새표본235_대상분류.tsv 의 no 다.
#
# ⚠ 이것은 상세페이지 DOM 텍스트가 아니라 **API 필드로 조립한 텍스트다.**
#   실제 셀러가 붙여 넣는 것보다 깨끗하다 - 광고 문구·중복·레이아웃 잡음이 없다.
#   이 텍스트로 잰 숫자에는 이 조건을 함께 적어야 한다.
#
# ⚠ **이미지 안의 글자는 없다.** desc.contents.item 에서 태그를 떼면 {zero}/{n}건
#   ({zero_pct}%)이 0자다. 상세페이지가 통째로 이미지라는 뜻이고, 그래서 본문은
#   대부분 고시정보 표와 인증 블록이다.
#
# ⚠ **연락처는 원문이 아니라 치환 토큰이다** ({tokens}).
#   저장 전에 제거했다(CLAUDE.md R4). 줄을 지우지 않고 남긴 이유는, 셀러가
#   붙여 넣는 텍스트에도 A/S 연락처는 있고 추출기가 그것을 무시하는지도
#   측정의 일부이기 때문이다.
"""


def load_scope() -> dict[str, tuple[int, str]]:
    out: dict[str, tuple[int, str]] = {}
    for line in _SCOPE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        no, verdict, name, _why = line.split("\t")
        out[name] = (int(no), verdict)
    return out


def load_details(paths: list[Path]) -> dict[str, dict]:
    by_no: dict[str, dict] = {}
    for p in paths:
        for v in json.loads(p.read_text(encoding="utf-8")):
            got = ((v.get("response", {}).get("domeggook") or {}).get("item")) or []
            for it in ([got] if isinstance(got, dict) else got):
                no = str((it.get("basis") or {}).get("no") or "")
                if no:
                    by_no[no] = it
    return by_no


def assemble_text(name: str, item: dict) -> str:
    """상세페이지에서 보이는 순서대로 조립한다."""
    detail = item.get("detail") or {}
    info = detail.get("infoDuty") or {}
    lines: list[str] = [name, ""]

    lines.append("[상품정보]")
    for label, key in (("제조국", "country"), ("제조사", "manufacturer"),
                       ("모델", "model"), ("크기", "size"), ("무게", "weight")):
        v = str(detail.get(key) or "").strip()
        if v and v != "-":
            lines.append(f"{label} : {v}")
    cat = ((item.get("category") or {}).get("current") or {}).get("name")
    if cat:
        lines.append(f"카테고리 : {cat}")
    lines.append("")

    certs = safety_certs(item)
    if certs:
        lines.append("[KC 인증정보]")
        for c in certs:
            for label, key in (("인증구분", "certType"), ("인증종류", "certName"),
                               ("인증번호", "no")):
                v = str(c.get(key) or "").strip()
                if v and v != "-":
                    lines.append(f"{label} : {v}")
            if str(c.get("exem") or "").upper() == "Y":
                lines.append(f"인증면제 : {c.get('exemTitle') or 'Y'}")
            w = str(c.get("warning") or "").strip()
            if w:
                lines.append(f"안내 : {w}")
        lines.append("")

    rows = infoduty_rows(item)
    if rows:
        lines.append(f"[상품 고시정보] {info.get('type') or ''}".rstrip())
        for r in rows:
            lines.append(f"{r.get('name')} : {r.get('desc')}")
        lines.append("")

    body = "\n".join(
        t for t in (
            html_to_text(((item.get("desc") or {}).get("contents") or {}).get("item")),
            html_to_text((item.get("desc") or {}).get("notice")),
        ) if t
    )
    if body:
        lines += ["[상세설명]", body, ""]
    return "\n".join(lines).rstrip() + "\n"


def structured(name: str, no: str, how: str, verdict: str, item: dict) -> dict:
    detail = item.get("detail") or {}
    info = detail.get("infoDuty") or {}
    rows = infoduty_rows(item)
    certs = safety_certs(item)
    body = html_to_text(((item.get("desc") or {}).get("contents") or {}).get("item"))
    return {
        "표본_상품명": name,
        "도매꾹_상품번호": no,
        "채택경로": how,
        "대상분류": verdict,
        "도매꾹_상품명": (item.get("basis") or {}).get("title"),
        "도매꾹_카테고리": ((item.get("category") or {}).get("current") or {}),
        "country": detail.get("country"),
        "manufacturer": detail.get("manufacturer"),
        "model": detail.get("model"),
        "size": detail.get("size"),
        "weight": detail.get("weight"),
        "infoDuty": {
            "type": info.get("type"),
            "item": [
                {
                    "type": r.get("type"),
                    "name": r.get("name"),
                    "desc": r.get("desc"),
                    "내용없음": is_placeholder(r.get("desc")),
                }
                for r in rows
            ],
        },
        "safetyCert": [
            {k: c.get(k) for k in _CERT_KEYS if k in c} for c in certs
        ],
        "desc_본문_길이": len(body),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="tests/fixtures/도매꾹_정제_2026-09-08")
    ap.add_argument("--expand", default="tests/fixtures/도매꾹_확장_2026-09-08")
    ap.add_argument("--out-dir", default="tests/fixtures")
    # ⚠ 파일명 날짜는 **원자료 수집일**이지 조립일이 아니다. 재조립할 때 오늘
    #   날짜로 쓰면 원자료 2026-09-08 과 어긋나고, 참조처 9곳이 깨진다.
    ap.add_argument("--stamp", default="", help="파일명 날짜. 기본은 오늘 (재조립 시 원자료 날짜를 준다)")
    args = ap.parse_args()

    base, expand = Path(args.base), Path(args.expand)
    scope = load_scope()
    adopted = json.loads((expand / "확장채택.json").read_text(encoding="utf-8"))["채택"]
    details = load_details([base / "상세.json", expand / "상세_확장.json"])

    rows: list[tuple[int, str, str, str, dict]] = []
    missing: list[str] = []
    for name, got in adopted.items():
        no = str(got["no"])
        item = details.get(no)
        if item is None:
            missing.append(f"{name} ({no})")
            continue
        sample_no, verdict = scope[name]
        rows.append((sample_no, name, no, got["how"], item))
    rows.sort()

    n = len(rows)
    zero = sum(
        1 for *_x, item in rows
        if not html_to_text(((item.get("desc") or {}).get("contents") or {}).get("item"))
    )
    counts = {"대상": 0, "비대상": 0, "애매": 0}
    for sample_no, name, _no, _how, _item in rows:
        counts[scope[name][1]] += 1

    stamp = args.stamp or f"{date.today():%Y-%m-%d}"
    out_txt = Path(args.out_dir) / f"도매꾹_상세텍스트_{stamp}.txt"
    out_json = Path(args.out_dir) / f"도매꾹_구조_{stamp}.json"

    header = _HEADER.format(
        sources=f"{base.name} + {expand.name}",
        n=n, n_target=counts["대상"], n_out=counts["비대상"], n_vague=counts["애매"],
        zero=zero, zero_pct=round(zero / n * 100) if n else 0,
        tokens=" · ".join(TOKENS),
    )
    chunks = [header]
    for sample_no, name, no, how, item in rows:
        chunks.append(
            f"\n# [{sample_no}] ({scope[name][1]} · {how} · 도매꾹 {no}) {name}\n"
            f"===== {sample_no} =====\n{assemble_text(name, item)}"
        )
    out_txt.write_text("".join(chunks), encoding="utf-8")

    payload = {
        "만든것": "scripts/build_domeggook_detail.py",
        "재료": [str(base), str(expand)],
        "재조립": f"{date.today():%Y-%m-%d}",
        "정제": {
            "치환_토큰": list(TOKENS),
            "설명": "seller·return.addr·thumb 는 저장 단계에서 제거됐다. "
                    "safetyCert[].imgUrl 은 이미지 추출 경로의 입력이라 남긴다.",
        },
        "건수": {"채택": n, **counts, "상세없음": len(missing)},
        "상품": [
            structured(name, no, how, scope[name][1], item)
            for sample_no, name, no, how, item in rows
        ],
    }
    left = residual(payload)
    if left:
        raise SystemExit(f"구조 JSON 에 개인정보 패턴이 남았습니다: {left}")
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    # ── 보고 ────────────────────────────────────────────────────────
    print(f"{'=' * 74}")
    print("A-4 · 정제본에서 조립\n")
    print(f"  (a) 텍스트  {out_txt}   {out_txt.stat().st_size:,} 바이트")
    print(f"  (b) 구조    {out_json}  {out_json.stat().st_size:,} 바이트")
    print(f"\n  채택 {n}건 — 대상 {counts['대상']} · 비대상 {counts['비대상']}"
          f" · 애매 {counts['애매']}")
    if missing:
        print(f"  ⚠ 상세 없음 {len(missing)}건: {missing[:5]}")
    lens = sorted(
        len(html_to_text(((it.get("desc") or {}).get("contents") or {}).get("item")))
        for *_x, it in rows
    )
    print(f"\n  desc.contents.item 태그제거 길이")
    print(f"    0자        {zero}/{n} ({zero / n * 100:.0f}%)")
    print(f"    중앙값     {lens[len(lens) // 2]}자 · 최대 {lens[-1]}자")
    body_lens = sorted(len(assemble_text(name, it)) for _s, name, _n, _h, it in rows)
    print(f"  조립 텍스트 길이 중앙값  {body_lens[len(body_lens) // 2]:,}자"
          f" (최소 {body_lens[0]:,} · 최대 {body_lens[-1]:,})")


if __name__ == "__main__":
    main()
