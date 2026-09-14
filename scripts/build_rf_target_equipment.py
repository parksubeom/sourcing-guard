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
#
#   비대상 오부착은 **0 이다**(⑦-a-2 에서 0 이 됐다). 그래도 안 올린다 -
#   0 은 **필요조건이지 충분조건이 아니다.** 지금 0 은 "분류해 둔 표본에서 0"
#   이고 도매꾹239 의 {분류없음}줄은 아직 분류 자체가 없다. 등급표를 올릴 때
#   우리가 쓴 자는 "비대상 부착 0" **과** "표본이 전수 분류돼 있다" 둘이었다.
#   선행조건은 `docs/미완_목록.md` 에 적었다.
#   그동안 화면은 **"무선 기능 표기가 있습니다"** 를 그대로 쓴다.
#
# ── ⑦-a-2 괄호 안 쉼표로는 자르지 않는다 (2026-09-14) ──────────────
#
#   전에는 `A(B, C, D)` 를 쉼표마다 잘라 B·C·D 를 따로 별칭으로 만들었다.
#   그 조각이 오부착을 만들었다 - **원인은 '정수기'·'카시트' 가 아니라
#   '포함' 과 '자동차' 였다**(찍어서 확인했다. 앞의 둘은 별칭에 없었다):
#
#       '나도컵 … 정수기컵 위생컵'        별칭 '포함'   → 주방용 전기 액체가열기기류
#       '[지앤지] 자동차 시트커버 …'      별칭 '자동차' → 게임기구류 및 오락기구류
#       '자동차 킥매트 등받이 보호 시트'   별칭 '자동차' → 게임기구류 및 오락기구류
#
#   `A(B, C, D)` 는 "A 인데 B·C·D 형태도 포함한다" 는 뜻이고, B·C·D 는 A 안
#   에서만 품목명이다. 바깥으로 떼어내면 **고시가 안 쓴 뜻**이 된다 - 빼는
#   것이 R5 이고 두는 것이 R5 위반이다. 목록을 손으로 고른 것이 아니다.
#
#   ── 잰 값 (빌더를 실제로 다시 돌려서) ──
#
#       별칭        509 → {별칭}
#       새표본235   붙은 줄 50 → 32 · 대상 36 → 23 · 비대상 3 → **0** · 애매 11 → 9
#       도매꾹239   붙은 줄 73 → 52 · 대상  9 →  9 · 분류없음 64 → 43
#
#   ⚠ **공짜가 아니었다. 맞는 줄 8개를 잃었다** - 무선주전자·커피포트 4 ·
#     전동 눈썹제모기 3 · 가정용 토스트기 1. 셋 다 머리가 괄호 앞에 있었고,
#     아래 ⑦-a-3 에서 **머리 낱말을 넣어 되찾았다**(덤으로 전기밥솥 3줄).
#
#   ⚠ 새표본235 에서 잃은 13줄은 **전부 틀린 품목이 붙어 있던 줄**이다 -
#     블루투스 스피커→게임기구류 · 무선청소기→주방용 액체가열 · 전기그릴→
#     전동형스크린류 · 놀이방매트→게임기구류. 대상 상품이지만 답이 틀렸다.
#     "대상/비대상" 은 **상품**의 분류이지 붙은 품목이 맞았는지가 아니다.
#
# ── ⑦-a-3 머리 낱말을 별칭으로 넣었다 (2026-09-14) ────────────────
#
#   `A(B, C)` 에서 **A 가 품목명이고 괄호는 A 를 좁히는 말**이다. A 를 별칭으로
#   내는 것은 고시를 읽는 것이지 지어내는 것이 아니다 (R5). ⑦-a-2 에서 꼬리를
#   뺀 것과 **같은 축의 반대쪽**이다 - 머리는 안전하고 꼬리는 안전하지 않다.
#
#   함께 `example_aliases()` 의 `rstrip(")")` 을 뺐다. 합친 예시에 걸리면
#   **여는 괄호만 남은 문자열**이 되어 영원히 아무것도 못 맞힌다
#   (`'전기토스터(팝업, 오븐 포함'` · ⑦-a-2 직후 57개가 그랬다).
#
#   ── 잰 값 (빌더·매처를 실제로 다시 돌려서) ──
#
#       별칭        466 → 540
#       새표본235   붙은 줄 32 → 38 · 대상 23 → 29 · 애매 9 · **비대상 0 유지**
#       도매꾹239   붙은 줄 52 → 67 · 대상  9 →  9 · 분류없음 43 → 58 · **비대상 0 유지**
#
#       새로 붙은 21줄 = 맞음 20 · 틀림 1
#         전기그릴·전기오븐 6 → 주방용 전열기기류     (이번엔 제 품목으로 붙는다)
#         무선주전자·커피포트 4 · 전기밥솥 3 → 주방용 전기 액체가열기기류
#         눈썹제모기 3 → 이?미용기기류 · 토스트기 1 → 주방용 전열기기류
#         전기히터·온풍기 3 → 전열기구류
#
#   ⚠⚠ **알려진 오부착 1건 — 고치지 않고 적어 둔다.**
#
#       '온풍기 Y36 윈드키스 미니 히터 난풍기'  → 동식물용 전기기기류
#       머리 `히터` 가 `히터(관상어용·식물용, 동물부화·사육용 히터)` 에서 나왔다.
#
#     떼어낼 규칙 셋을 재 봤고 **셋 다 이 한 줄에 맞춰 만든 규칙**이었다:
#       머리가 괄호 안에 다시 나오면 뺀다  → 제모기·보일러·거품기까지 같이 빠진다
#                                          (제모기는 되찾으려던 3줄이다)
#       괄호 첫 원소가 '…용' 이면 뺀다     → 표 전체에서 걸리는 것이 이 한 줄뿐
#       머리 2자는 빼고 3자 이상만 쓴다    → 79개 머리 중 2자는 '히터' 하나뿐
#
#     셋째가 제일 유혹적이고 제일 나쁘다 - **지금 출력에 맞춰 숫자를 고른 것**
#     이고, §6 의 "검사가 기대값을 현재 출력에 맞춰 쓰면 버그를 고정한다" 와
#     같은 일을 규칙 형태로 하는 것이다. 그래서 **틀린 채로 두고 적는다.**
#     이 줄은 도매꾹239 의 분류없음 칸이라 게이트(비대상 오부착)는 0 그대로다.
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
화면연결: false          # 오부착은 0 이지만 도매꾹239 가 미분류다 · 위 주석

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


#: 대표 품목 목록을 **고시의 문법대로** 가른다.
#:
#: ⚠⚠ **괄호 안의 쉼표로는 자르지 않는다 (2026-09-14 · ⑦-a-2).**
#:
#:   `A(B, C, D)` 는 "A 인데 B·C·D 형태도 포함한다" 는 뜻이다. B·C·D 는 **A 안
#:   에서만** 품목명이고, 바깥으로 떼어내면 고시가 안 쓴 뜻이 된다 - 빼는 것이
#:   R5 이고 두는 것이 R5 위반이다.
#:
#:   처음엔 깊이를 안 보고 잘라서 이런 조각이 별칭이 됐다:
#:
#:       커피메이커? 머신(자동머신, 캡슐, 포함)      → '포함'
#:       … 전동모터 장난감(드론, 자동차, 보트 등)     → '자동차'
#:       전동형 롤스크린(전동식 커튼, 셔터, 그릴, …)  → '셔터'·'그릴'·'차양'
#:
#:   그 조각이 실제로 오부착을 만들었다 - 정수기 종이컵이 '포함' 으로,
#:   자동차 시트커버가 '자동차' 로 붙었다.
#:
#: ⚠ `·` 로는 애초에 자르지 않는다. 낱말 **안**에서도 쓰인다("산업용·과학용").
_OPEN, _CLOSE = "(（[", ")）]"
#: 목록 끝의 맺음말. 품목이 아니다.
_TAIL = re.compile(r"^(?:등|및|또는|기타)$")


def _split_top(text: str) -> list[str]:
    """쉼표와 줄머리 `-` 로 가르되 **괄호 밖에서만** 가른다."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        if depth == 0 and ch == ",":
            out.append("".join(buf))
            buf = []
        elif depth == 0 and ch == "-" and (i == 0 or text[i - 1] == " ") \
                and i + 1 < len(text) and text[i + 1] == " ":
            out.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


def _examples_from(text: str) -> list[str]:
    out = []
    for piece in _split_top(" ".join(text.split())):
        t = piece.strip(" .·?")
        # 괄호가 한쪽만 남은 조각은 **줄바꿈에 잘린 것**이다. 여는 괄호 앞까지만.
        if t.count("(") != t.count(")"):
            t = t.split("(")[0].strip()
        if not (2 <= len(t) <= 30) or DEFN.search(t) or _TAIL.match(t):
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


def _alias_count(entries: list[dict]) -> int:
    """`rf_equipment.example_aliases()` 와 같은 규칙으로 센다."""
    seen: set[str] = set()
    for e in entries:
        for raw in e["examples"]:
            word = str(raw).strip().rstrip(")")
            if 2 <= len(word) <= 20:
                seen.add(word)
    return len(seen)


def _q(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render(doc: dict, src: Path, lines: list, rows: list, entries: list) -> str:
    head = HEADER.format(
        원자료=src.name, 받은날=doc["받은날"], 시행=doc["시행일자"],
        일련번호=doc["행정규칙일련번호"], 원문행=len(lines),
        표행=len(rows), 옮긴행=len(entries),
        예시행=sum(1 for e in entries if e["examples"]),
        별칭=_alias_count(entries),
        분류없음=43,
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
