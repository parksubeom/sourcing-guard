#!/usr/bin/env python3
"""「전기용품 및 생활용품 안전관리 운용요령」 세부품목 별표 → item_grades.yaml.

셀러가 "이 품목이 안전인증 대상인가 안전확인 대상인가" 를 알려면 품목 목록이
있어야 한다. 그동안 우리는 이걸 몰라서 kc_tier_unknown 으로 내보냈다.

⚠ KC 규격번호(KC 60598-2-1 등)는 뽑지 않는다. 이 별표에 없기도 하고(세 별표
  통틀어 4건뿐이며 전부 게임기구 비고의 범위 한정 참조), 있더라도 셀러가 그
  번호로 할 수 있는 일이 없다 - 시험기관이 시험을 설계할 때 쓰는 규격 코드지
  소싱 판단 정보가 아니다.

원문 구조 (HWP 선형 추출 기준):
    분류 / 품목 / 세부품목            <- 표 머리
    1. 전선 및 전원코드
    대상 없음
    2. 전기기기용                     <- 분류가 줄바꿈된다
    스위치
    전기기기용 제어소자                <- 품목인데 '가.' 접두가 없다
    ① 온도조절기
    비고: 교류전압을 사용하는 제품에 한하며 ...

접두 없는 줄이 분류 연속인지 품목인지는 **다음 줄을 보고** 가른다. 품목이면
바로 뒤에 세부품목(①)이 온다.

⚠ 비고의 범위 한정을 반드시 살린다. 직류전원장치의 "정격출력이 1 kVA 이하인
  것에 한정" 을 버리면 1kVA 초과 제품에 잘못된 등급을 말하게 된다.
"""

from __future__ import annotations

import argparse
import pathlib
import re

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

# 파일 접두 + 별표 번호 -> (등급, 우리 품목 분류)
#
# 전기용품과 생활용품이 별개 별표다. 전기용품만 넣었을 때 골든셋·데모 19건 중
# 3건만 대상이었다 - 휴지통·토트백·키링처럼 셀러가 실제로 소싱하는 것이 전부
# 생활용품이라 빠졌다.
TABLES = {
    ("별표", "1"): ("안전인증", "electrical"),
    ("별표", "2"): ("안전확인", "electrical"),
    ("별표", "3"): ("공급자적합성확인", "electrical"),
    ("생활별표", "4"): ("안전인증", "household"),
    ("생활별표", "5"): ("안전확인", "household"),
    ("생활별표", "6"): ("공급자적합성확인", "household"),
    ("생활별표", "7"): ("안전기준준수", "household"),
}

_DIV = re.compile(r"^(\d{1,2})\.\s*(.*)$")
_ITEM = re.compile(r"^([가-힣])\s*\.\s*(.*)$")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse(lines: list[str]) -> list[dict]:
    """표 한 장을 (분류, 품목, 세부품목, 비고) 로 편다."""
    rows: list[dict] = []
    division = ""
    item = ""
    pending_div = False          # 방금 'N.' 을 봤다 - 다음 줄이 이어질 수 있다

    def nxt(i: int) -> str:
        return lines[i + 1] if i + 1 < len(lines) else ""

    for i, raw in enumerate(lines):
        line = _clean(raw)
        if not line or line.startswith("====="):
            continue
        if line in ("분류", "품목", "세부품목") or line.startswith("[별표"):
            continue

        m = _DIV.match(line)
        if m:
            new_div = _clean(m.group(2))
            if new_div != division:
                division, item = new_div, ""
            pending_div = True
            continue

        m = _ITEM.match(line)
        if m:
            item = _clean(m.group(2))
            pending_div = False
            continue

        if line[0] in CIRCLED:
            name = _clean(line[1:])
            # 개정으로 빠진 항목. "삭제<2023. 3. 20.>" 형태로 자리만 남는다.
            # 품목으로 넣으면 셀러 상품명이 여기 붙을 일은 없지만, 표 건수를
            # 부풀리고 등급 통계를 흐린다.
            if re.match(r"^삭제", name) or name in ("-", ""):
                pending_div = False
                continue
            if name:
                rows.append({"division": division, "item": item or division, "detail": name, "note": ""})
            pending_div = False
            continue

        if line.startswith("비고"):
            # 직전 세부품목들이 속한 품목 전체에 걸린다.
            note = _clean(re.sub(r"^비고\s*[:：]?\s*", "", line))
            for r in reversed(rows):
                if r["item"] != (item or division):
                    break
                r["note"] = note
            pending_div = False
            continue

        if "대상 없음" in line or "대상없음" in line:
            pending_div = False
            continue

        # 접두 없는 줄. 다음 줄이 세부품목이면 품목, 아니면 분류 연속이다.
        after = _clean(nxt(i))
        if after and after[0] in CIRCLED:
            item = line
        elif pending_div:
            division = _clean(f"{division} {line}")
        else:
            item = line
        pending_div = False

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scratch", help="별표N_hwp.txt 가 있는 디렉터리")
    ap.add_argument("-o", "--out", default="sourcing_guard/data/item_grades.yaml")
    args = ap.parse_args()

    src = pathlib.Path(args.scratch)
    out: list[dict] = []
    for (prefix, no), (grade, category) in TABLES.items():
        text = (src / f"{prefix}{no}_hwp.txt").read_text(encoding="utf-8", errors="replace")
        for row in parse(text.splitlines()):
            out.append(
                {
                    "item": row["detail"],
                    "grade": grade,
                    "category": category,
                    "division": row["division"],
                    "scope_note": row["note"],
                    "source": f"전기용품 및 생활용품 안전관리 운용요령 별표 {no}",
                }
            )

    lines = [
        "# 전기용품 세부품목 등급표.",
        "#",
        "# 「전기용품 및 생활용품 안전관리 운용요령」 별표 1~7 을 그대로 옮긴 것이다.",
        "# 별표 1~3 이 전기용품, 4~7 이 생활용품이다.",
        "# 셀러가 \"이 품목이 안전인증 대상인가\" 를 알아야 인증번호 부재의 의미가",
        "# 정해진다 - 안전인증·안전확인 대상이면 번호가 있어야 하고, 공급자적합성확인",
        "# 대상이면 없는 것이 정상이다 (CLAUDE.md R3-b).",
        "#",
        "# ⚠ KC 규격번호는 넣지 않는다. 이 별표에 없고(세 별표 통틀어 4건뿐이며 전부",
        "#   게임기구 비고의 범위 한정 참조), 있더라도 셀러가 그 번호로 할 수 있는",
        "#   일이 없다 - 시험기관이 쓰는 규격 코드지 소싱 판단 정보가 아니다.",
        "#",
        "# ⚠ scope_note 는 버리지 않는다. 직류전원장치의 \"정격출력이 1 kVA 이하인",
        "#   것에 한정\" 을 빼면 1kVA 초과 제품에 잘못된 등급을 말하게 된다.",
        "#",
        "# 생성: scripts/parse_item_grades.py",
        "",
        "items:",
    ]
    for r in out:
        lines.append(f"  - item: {_q(r['item'])}")
        lines.append(f"    grade: {r['grade']}")
        lines.append(f"    category: {r['category']}")
        lines.append(f"    division: {_q(r['division'])}")
        if r["scope_note"]:
            lines.append(f"    scope_note: {_q(r['scope_note'])}")
        lines.append(f"    source: {_q(r['source'])}")
    pathlib.Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(out)}건 → {args.out}")


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


if __name__ == "__main__":
    main()
