"""제출문 세 항목 × 세 길이의 글자 수를 센다.

손으로 세지 않는다. 2026-09-13 에 표의 값이 실제와 최대 174자 어긋나 있었고
(AI 활용 방식 1000자판: 표 964 · 실제 1138), 폼 제한이 1000자면 그대로 잘린다.

세는 방법
    마크다운 기호(`**`, 백틱)를 뺀 뒤 **연속 공백·줄바꿈을 공백 하나로** 접어
    길이를 센다. 공백은 포함한다 - 폼이 공백을 세지 않는다는 근거가 없다.

    ⚠ 폼의 실제 계산 방식은 **아직 모른다**(로그인해서 확인 전). 이 값은
      보수적으로 큰 쪽이다. 폼이 공백을 빼고 센다면 여유가 더 있다.

사용
    PYTHONUTF8=1 python scripts/count_submission_chars.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_DOC = Path(__file__).resolve().parents[1] / "docs" / "제출문_초안.md"
_ITEMS = ("해결하려는 문제", "AI 활용 방식", "사용한 AI 도구")


def measure(text: str) -> int:
    """마크다운 기호를 빼고 공백을 접어 센다."""
    stripped = re.sub(r"\*\*|`", "", text).strip()
    return len(re.sub(r"\s+", " ", stripped))


def variants(doc: str, title: str) -> dict[int, int]:
    block = re.search(
        rf"^## \d+\. {re.escape(title)}\n(.*?)(?=^## |\Z)", doc, re.S | re.M
    )
    if not block:
        raise SystemExit(f"'{title}' 절을 찾지 못했습니다 - 제출문 구조가 바뀌었습니다.")
    out: dict[int, int] = {}
    for m in re.finditer(r"^### (\d+)자\n(.*?)(?=^### |\Z)", block.group(1), re.S | re.M):
        body = re.sub(r"^---\s*$", "", m.group(2), flags=re.M)
        out[int(m.group(1))] = measure(body)
    return out


def main() -> int:
    doc = _DOC.read_text(encoding="utf-8")
    over = 0
    print(f"{'항목':16s} " + " ".join(f"{n}자판".rjust(11) for n in (200, 500, 1000)))
    for title in _ITEMS:
        v = variants(doc, title)
        cells = []
        for limit in (200, 500, 1000):
            n = v.get(limit)
            if n is None:
                cells.append("-".rjust(11))
                continue
            mark = " 초과" if n > limit else ""
            if n > limit:
                over += 1
            cells.append(f"{n}{mark}".rjust(11))
        print(f"{title:16s} " + " ".join(cells))
    if over:
        print(f"\n⚠ 목표를 넘는 판이 {over}개 있습니다. 폼 제한이 그 길이면 잘립니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
