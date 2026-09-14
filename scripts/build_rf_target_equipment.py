#!/usr/bin/env python
"""[⑦-a] 전파 대상기자재 표를 `data/rf_target_equipment.yaml` 로 옮긴다.

    python scripts/build_rf_target_equipment.py

원자료는 `scripts/probe_rf_target_equipment.py` 가 받아 둔 fixture 다.
**원자료는 손대지 않는다** - 파싱이 틀렸을 때 되짚을 곳이 거기뿐이다.

⚠⚠ **표가 세로 병합·줄바꿈이 심하다.** 옮기면서 판단한 것 넷을 적어 둔다:

  ① 행의 정체는 **기기부호**다. `○` 가 든 줄이 행의 시작이고, 그 아래
     `○` 없는 줄은 이름이 이어지는 줄이다.
  ② 병합된 상위 이름은 **왼쪽 열이 아래로 늘어나는** 모양이다. 빈 칸은 위에서
     물려받고, 표지(`가.` `1)` `①`)가 없는 칸은 **앞 이름의 나머지**다 -
     "라.해상이동업무용 디지털선택호출" / "장치의 기기" 가 두 행에 걸친다.
  ③ 기기부호도 세로 병합된다. ⑧⑨⑩ 감자탈피기·전기정미기·전기빵자르개가
     ⑦ 과일껍질깎기의 `KCN12` 를 함께 쓴다.
  ④ **가장 깊은 칸이 늘 이름인 것은 아니다.** 11절은 소분류 칸이 정의 문단
     ("o (정의) … o 대표적인 품목은 다음과 같다. - 진공청소기, …")이라
     이름은 그 위 칸(`1) 전기청소기류`)이고, 정부가 적어 둔 **대표 품목**을
     `examples` 로 따로 담는다. 우리가 지어낸 이름이 아니다 (R5).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BOX = "─━┈┉┅┄├┤┬┴┼┝┥┿┏┓┗┛┌┐└┘╋┠┨┯┷"
VBAR = "│┃"
SEC = re.compile(r"^\s*(\d+)\.\s*(\S.*)$")
NOTE = re.compile(r"※\s*비\s*고")
MARKER = re.compile(r"^\s*(?:[가-힣][.)]|\d+\s*[.)]|[①-⑳]|[a-zA-Z][.)]|o\s)")
STRIP_MARK = re.compile(
    r"^\s*(?:[가-힣][.)]\s*|\d+\s*[.)]\s*|[①-⑳]\s*|[a-zA-Z][.)]\s*)+")
DEFN = re.compile(r"o\s*\(정의\)|대표적인\s*품목")
EXAMPLES = re.compile(r"대표적인\s*품목은\s*다음과\s*같다\.?\s*(.*)$", re.S)

FIELDS_A = ["전자파적합성", "무선", "유선", "전자파흡수율", "전자파강도",
            "적합인증", "적합등록", "자기적합확인", "기기부호", "기타사항"]
FIELDS_B = ["전자파적합성", "전자파인체보호", "적합등록", "자기적합확인", "기기부호"]
TYPES = ("적합인증", "적합등록", "자기적합확인")

SRC = "방송통신기자재등의 적합성평가에 관한 고시 별표 1 (적합성평가 대상기자재)"

HEADER = """# 전파 적합성평가 대상기자재 — [⑦-a] · 생성물
#
# ⚠⚠ **손으로 고치지 않는다.** `scripts/build_rf_target_equipment.py` 가 만든다.
#   원자료는 `tests/fixtures/{원자료}` 이고 그것도 손대지 않는다.
#
# ⚠⚠ **화면에 연결하지 않았다 (2026-09-14 · 총괄 기준 ④).**
#   기준은 "새표본235 + 도매꾹239 에서 비대상 오부착 0" 이었다. 실측은 3건이다:
#
#       '나도컵 꼬깔컵 생수컵 … 정수기컵 위생컵'   → 주방용 전기 액체가열기기류
#       '[지앤지] 자동차 시트커버 … 카시트 …'     → 게임기구류 및 오락기구류
#       '자동차 킥매트 등받이 보호 시트'           → 게임기구류 및 오락기구류
#
#   그래서 표는 리포에 두고 화면은 "무선 기능 표기가 있습니다" 를 유지한다.
#   등급표를 올릴 때와 같은 기준이다.
#
# 출처  「방송통신기자재등의 적합성평가에 관한 고시」 별표 1
#       행정규칙일련번호 {일련번호} · 시행 {시행} · 국립전파연구원
#       ⚠ ID 는 `행정규칙일련번호` 다. `행정규칙ID`(38724)를 넣으면 "없습니다".
#       ⚠ 별표는 **번호가 아니라 제목으로** 고른다 - 응답에 별표가 30개 있고
#         `별표번호 0001` 이 둘이다(별표 1 과 서식 1).
#
# 옮긴 수 ({받은날})
#       별표 원문 {원문행}행 · 표 행 {표행} · 옮긴 행 {옮긴행} · 버린 행 0
#       대표 품목이 딸린 행 {예시행}
#
# 옮기면서 판단한 것 넷은 만든 스크립트 머리 주석에 적었다(세로 병합·표지 없는
# 이어짐·기기부호 병합·정의 문단). 그중 하나만 여기 옮긴다:
#
#   ⚠ **가장 깊은 칸이 늘 이름인 것은 아니다.** 11절 소분류는 정의 문단이라
#     이름은 그 위 칸(`1) 전기청소기류`)이고, 문단 안의 "대표적인 품목" 을
#     `examples` 로 담았다. **정부가 적어 둔 이름이지 우리가 지어낸 것이
#     아니다** (R5).
#
# `grade` 는 적합성평가 유형이다(적합인증 | 적합등록 | 자기적합확인).
# `ItemGradeBook` 이 그 열쇠로 읽으므로 이름을 맞춰 뒀다 - 같은 매처를 쓰라는
# 지시가 스키마를 정한다.

version: 1
받은날: "{받은날}"
화면연결: false          # 비대상 오부착 3건 · 위 주석 참조

"""


def _cells(line: str) -> tuple[list[str], bool]:
    raw = re.split(f"[{VBAR}]", line)
    if len(raw) < 2:
        return [], False
    body = raw[1:-1] if raw[-1].strip() == "" else raw[1:]
    out, cut = [], False
    for cell in body:
        m = re.search(f"[{BOX}]", cell)
        if m:
            out.append(cell[: m.start()])
            cut = True
            break
        out.append(cell)
    return out, cut


def group_rows(lines: list[str]) -> tuple[list[dict], list[tuple]]:
    rows, dropped = [], []
    section, in_body, cur = None, False, None
    for i, line in enumerate(lines):
        m = SEC.match(line)
        if m and VBAR[0] not in line:
            section, in_body, cur = f"{m.group(1)}. {m.group(2).strip()}", False, None
            continue
        if section is None:
            continue
        if not in_body:
            if "━" in line:                 # 머리말과 본문을 가르는 굵은 선
                in_body = True
            continue
        if NOTE.search(line):               # 표 아래 비고에서 이 절이 끝난다
            in_body, cur = False, None
            continue
        if VBAR[0] not in line:
            continue
        fields = FIELDS_B if section.startswith("11.") else FIELDS_A
        n = len(fields)
        cells, cut = _cells(line)
        if not cells:
            continue
        if cut or len(cells) <= n:
            if cur:
                cur["cont"].append(cells)
            else:
                dropped.append((i, "앞선 행이 없는 이어짐", line[:70]))
            continue
        names, vals = cells[:-n], cells[-n:]
        d = dict(zip(fields, (v.strip() for v in vals)))
        if not any("○" in d.get(t, "") for t in TYPES):
            if cur:
                cur["cont"].append(names)
            else:
                dropped.append((i, "유형 칸이 비었고 앞선 행도 없다", line[:70]))
            continue
        cur = {"section": section, "line": i, "head": names, "cont": [],
               "fields": d, "types": [t for t in TYPES if "○" in d.get(t, "")]}
        rows.append(cur)
    return rows, dropped


def resolve(rows: list[dict]) -> list[dict]:
    ctx: dict[int, str] = {}
    out: list[dict] = []
    last = None
    for r in rows:
        if r["section"] != last:
            ctx, last = {}, r["section"]
        parts = [[c] for c in r["head"]]
        for cells in r["cont"]:
            for k, c in enumerate(cells):
                if k < len(parts):
                    parts[k].append(c)
        levels = [" ".join(" ".join(p).split()) for p in parts]
        deepest = max((k for k, t in enumerate(levels) if t), default=-1)
        resolved = []
        for k, text in enumerate(levels):
            if text:
                if k < deepest and not MARKER.match(text) and ctx.get(k):
                    ctx[k] = " ".join(f"{ctx[k]} {text}".split())
                else:
                    ctx[k] = text
                    for deep in [d for d in ctx if d > k]:
                        del ctx[deep]
            resolved.append(ctx.get(k, ""))
        if not r["fields"].get("기기부호") and out:
            r["fields"]["기기부호"] = out[-1]["fields"].get("기기부호", "")
            r["부호_물려받음"] = True
        r["levels"] = [t for t in resolved if t]
        out.append(r)
    return out


#: 대표 품목 목록에서 **낱말 조각을 걸러낸다.**
#:
#: ⚠⚠ 처음엔 `-,·` 로 다 잘랐더니 "포함" · "방향" · "주거" · "초음파" 같은
#:   조각이 별칭이 됐고, 그 별칭이 엉뚱한 상품에 붙었다(실측: 초음파가습기가
#:   "산업용·과학용 전파응용기기류" 로, 블루투스 스피커가 "게임기구류" 로).
#:   `·` 는 낱말 **안**에서도 쓰인다("산업용·과학용", "냉장?냉동기기") -
#:   그것으로 자르면 조각이 나온다. `,` 와 줄머리 `-` 로만 자른다.
_FRAGMENT = re.compile(r"^(?:포함|방향|주거|상업용|산업용|식물용|기타|등|및|또는)$")


def _examples_from(text: str) -> list[str]:
    out = []
    for piece in re.split(r"(?:^|\s)-\s|,", " ".join(text.split())):
        t = piece.strip(" .·?")
        # 괄호가 한쪽만 남은 조각은 잘린 것이다.
        if t.count("(") != t.count(")"):
            t = t.split("(")[0].strip()
        if not (2 <= len(t) <= 30) or DEFN.search(t) or _FRAGMENT.match(t):
            continue
        out.append(t)
    return out


def to_entry(r: dict) -> dict | None:
    """행 하나 → yaml 항목. 이름이 안 나오면 None."""
    levels = r["levels"]
    if not levels:
        return None
    # 가장 깊은 칸이 정의 문단이면 그 위 칸이 이름이다.
    idx = len(levels) - 1
    while idx >= 0 and DEFN.search(levels[idx]):
        idx -= 1
    if idx < 0:
        return None
    item = STRIP_MARK.sub("", levels[idx]).strip()
    # `4) 공기질 조절기류 ※ 공기청정기/가습기/제습기` 처럼 표 안에 붙은 주석은
    # 이름에서 떼어 scope_note 로 보낸다.
    item, _, tail = item.partition("※")
    item = item.strip()
    if not item:
        return None
    examples: list[str] = []
    defn = ""
    for lv in levels[idx + 1:]:
        if DEFN.search(lv):
            defn = lv
            m = EXAMPLES.search(lv)
            if m:
                examples += _examples_from(m.group(1))
    note_parts = [levels[k] for k in range(idx)] + ([tail.strip()] if tail.strip() else [])
    return {
        "item": item,
        "grade": "/".join(r["types"]),          # 적합인증 | 적합등록 | 자기적합확인
        "category": "rf",
        "division": r["section"],
        "scope_note": " ".join(" ".join(note_parts).split())[:400],
        "device_code": r["fields"].get("기기부호", ""),
        "source": SRC,
        "examples": list(dict.fromkeys(examples))[:24],
        # ⚠ **자르지 않는다.** 이 문단이 예시의 출처 증명이다 - 400자에서
        #   자르니 뒤쪽 예시 15건이 "출처 없는 말" 로 읽혔다.
        "definition": " ".join(defn.split()),
        "line": r["line"],
    }


def main() -> int:
    src = sorted(Path("tests/fixtures").glob("전파_대상기자재_고시_*.json"))[-1]
    doc = json.loads(src.read_text(encoding="utf-8"))
    lines = doc["별표내용"]
    raw, dropped = group_rows(lines)
    rows = resolve(raw)
    entries, skipped = [], []
    for r in rows:
        e = to_entry(r)
        (entries.append(e) if e else
         skipped.append((r["line"], r["fields"].get("기기부호"), "이름 칸을 못 찾았다")))
    print(f"원자료 {src.name}")
    print(f"  별표 원문 {len(lines)}행 · 표 행 {len(rows)} · 옮긴 행 {len(entries)} "
          f"· 버린 행 {len(skipped) + len(dropped)}")
    for x in (dropped + skipped)[:10]:
        print("   버림", x)
    print(f"  대표 품목이 딸린 행 {sum(1 for e in entries if e['examples'])}")
    Path("/tmp/rf_entries.json").write_text(
        json.dumps({"받은날": doc["받은날"], "items": entries},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    out = Path("sourcing_guard/data/rf_target_equipment.yaml")
    out.write_text(_render(doc, src, lines, rows, entries), encoding="utf-8")
    print(f"  저장 {out}")
    return 0


def _q(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render(doc: dict, src: Path, lines: list, rows: list, entries: list) -> str:
    head = HEADER.format(
        원자료=src.name, 받은날=doc["받은날"], 시행=doc["시행일자"],
        일련번호=doc["행정규칙일련번호"], 원문행=len(lines),
        표행=len(rows), 옮긴행=len(entries),
        예시행=sum(1 for e in entries if e["examples"]),
    )
    body = ["items:"]
    for e in entries:
        body.append(f"  - item: {_q(e['item'])}")
        # ⚠ 이름을 `grade` 로 둔다. `ItemGradeBook` 이 그 열쇠로 읽기 때문이다 -
        #   총괄 지시의 `type` 과 같은 값이고, 같은 매처를 쓰라는 지시가
        #   스키마를 정한다. 두 이름을 같이 두지 않는다 (§6).
        body.append(f"    grade: {_q(e['grade'])}       # 적합성평가 유형")
        body.append("    category: rf")
        body.append(f"    division: {_q(e['division'])}")
        body.append(f"    device_code: {_q(e['device_code'])}")
        body.append(f"    scope_note: {_q(e['scope_note'])}")
        body.append(f"    source: {_q(e['source'])}")
        body.append(f"    별표행: {e['line']}")
        if e["definition"]:
            # 예시가 어디서 왔는지 되짚을 수 있게 정의 문단을 남긴다.
            body.append(f"    definition: {_q(e['definition'])}")
        if e["examples"]:
            body.append("    examples:                 # 고시가 적어 둔 대표 품목")
            for x in e["examples"]:
                body.append(f"      - {_q(x)}")
    return head + "\n".join(body) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
