#!/usr/bin/env python3
"""「어린이제품 안전 특별법 시행규칙」 별표 1~3 → child_item_grades.yaml.

561건 표(운용요령 별표 1~7)는 전기·생활용품뿐이라 완구·학용품·유아용품이
아예 없다. 그래서 새 표본에서 못 맞춘 것 중 크레파스·색연필·물감·지우개가
"판별 못 함" 으로 남았다 - 매칭 규칙 문제가 아니라 표에 그 품목이 없었다.

세 고시(안전인증 2024-198 · 안전확인 2025-146 · 공급자적합성 2025-25)에는
품목 목록이 **없다**. 고시는 안전기준(부속서)만 담고, 품목은 시행규칙으로
넘긴다. 세 고시 제2조가 똑같이 말한다:

    "…「어린이제품 안전 특별법 시행규칙」 별표 1(2·3)에 따른
      안전인증대상어린이제품별로 부속서를 적용한다"

시행규칙 제2조도 같은 방향을 가리킨다:

    ① 법 제2조제9호  안전인증대상어린이제품       → 별표 1
    ② 법 제2조제11호 안전확인대상어린이제품       → 별표 2
    ③ 법 제2조제12호 공급자적합성확인대상어린이제품 → 별표 3

전안법이 운용요령 별표에 품목을 둔 것과 같은 구조다.

⚠ **별표 3 제2호의 포괄 규정을 반드시 살린다.**

    "개별 안전기준이 없는 공급자적합성확인대상어린이제품은
     어린이제품 공통안전기준을 적용한다"

  전기·생활용품에서는 "표에 없음 = 비대상" 이 성립하지 않는다는 것을 우리가
  추론해야 했지만(docs/표에_없음은_비대상이_아니다.md), 어린이제품은 원문이
  명시한다. 목록 35건에 없어도 어린이제품이면 공통안전기준이 적용된다 -
  이건 "판별 못 함" 이 아니라 확정된 답이다. 그래서 주석이 아니라 catch_all
  필드로 남긴다.

원문 구조:
    별표 1·2   "1. 유아용 섬유제품" 처럼 숫자 항
    별표 3     "가. 어린이용 가죽제품" 처럼 가나다 항 (1호 아래)
    둘 다 품목 다음 줄부터 적용 안전기준이 붙는다 - 우리는 품목만 쓴다.

받는 법:
    law.go.kr DRF lawService.do (target=law, MST=286387) 로 별표 링크를 얻고
    flSeq 로 HWP 를 받아 scripts/hwp2txt.py 로 텍스트화한다. 561건과 같은 경로다.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_LETTERS = "가나다라마바사아자차카타파하거너더러머버서어저"

# 별표 → (등급, 출처 표기). 시행규칙 제2조 각 항이 지정한 대응이다.
_SOURCES = {
    "1": ("안전인증", "어린이제품 안전 특별법 시행규칙 별표 1"),
    "2": ("안전확인", "어린이제품 안전 특별법 시행규칙 별표 2"),
    "3": ("공급자적합성확인", "어린이제품 안전 특별법 시행규칙 별표 3"),
}

_CATCH_ALL_TEXT = (
    "개별 안전기준이 없는 공급자적합성확인대상어린이제품은 "
    "어린이제품 공통안전기준을 적용한다."
)


def _items(text: str, *, lettered: bool) -> list[str]:
    """품목 줄만 뽑는다. '삭제' 항은 버린다."""
    pat = re.compile(rf"^([{_LETTERS}])\.\s*(.+)$") if lettered else re.compile(r"^(\d+)\.\s*(.+)$")
    out: list[str] = []
    for line in text.splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        name = m.group(2).strip()
        # "2. 개별 안전기준이 없는 …" 은 품목이 아니라 포괄 규정이다.
        if name.startswith("삭제") or name.startswith("개별 안전기준이 없는"):
            continue
        out.append(name)
    return out


def build(txt_dir: Path) -> str:
    rows: list[tuple[str, str, str]] = []
    for no, (grade, source) in _SOURCES.items():
        path = next(txt_dir.glob(f"별표{no}_*.txt"))
        rows += [(n, grade, source)
                 for n in _items(path.read_text(encoding="utf-8"), lettered=(no == "3"))]

    out = [
        "# 어린이제품 세부품목 등급표.",
        "#",
        "# 「어린이제품 안전 특별법 시행규칙」 별표 1~3 을 그대로 옮긴 것이다.",
        "# 별표 1 이 안전인증, 2 가 안전확인, 3 이 공급자적합성확인 대상이다.",
        "#",
        "# ⚠ **아직 판정에 연결하지 않았다.** item_grades.yaml(561건)만 verifier 가",
        "#   읽는다. 561건 표를 처음 넣을 때와 같은 순서다 - 먼저 자료를 넣고,",
        "#   합칠 때의 충돌을 실측한 뒤에 연결한다.",
        "#",
        "# ⚠ 스키마는 item_grades.yaml 과 같다. 나중에 합칠 때 변환이 없어야 한다.",
        "#   다만 category 값 'children' 은 ItemCategory 에 아직 없다 - 거기엔",
        "#   CHILDREN_TOY/STATIONERY/TEXTILE 셋만 있고 총칭이 없다. 어느 쪽으로",
        "#   맞출지는 연결할 때 정한다. 지금 enum 을 늘리면 추출 프롬프트까지",
        "#   건드리게 되고, 재봐야 아는 것을 미리 설계하는 셈이 된다.",
        "#",
        "# 생성: scripts/parse_child_item_grades.py",
        "",
        "# 목록에 없는 어린이제품이 어디로 가는지. 주석이 아니라 필드로 둔다 -",
        "# 화면이 이 문장을 그대로 쓸 수 있어야 한다.",
        "#",
        "# 전기·생활용품에서는 '표에 없음 = 비대상' 이 성립하지 않는다는 것을",
        "# 우리가 추론해야 했지만, 어린이제품은 원문이 명시한다. 그래서 목록에",
        "# 없어도 '판별 못 함' 이 아니라 확정된 답을 줄 수 있다.",
        "catch_all:",
        "  applies_to: 어린이제품",
        "  grade: 공급자적합성확인",
        "  standard: 어린이제품 공통안전기준",
        f'  source: "어린이제품 안전 특별법 시행규칙 별표 3 제2호"',
        f'  source_text: "{_CATCH_ALL_TEXT}"',
        '  statement_ko: "목록에 없는 어린이제품도 안전관리 대상에서 빠지지 않습니다. '
        '개별 안전기준이 없으면 어린이제품 공통안전기준이 적용되는 '
        '공급자적합성확인 대상입니다."',
        "",
        "items:",
    ]
    for item, grade, source in rows:
        out += [
            f'  - item: "{item}"',
            f"    grade: {grade}",
            "    category: children",
            '    division: ""',
            '    scope_note: ""',
            f'    source: "{source}"',
        ]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--txt-dir", default="/tmp/kid",
                    help="hwp2txt.py 로 변환한 별표1~3 텍스트가 있는 디렉터리")
    ap.add_argument("--out", default="sourcing_guard/data/child_item_grades.yaml")
    args = ap.parse_args()
    Path(args.out).write_text(build(Path(args.txt_dir)), encoding="utf-8")
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
