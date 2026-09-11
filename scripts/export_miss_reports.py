#!/usr/bin/env python
"""[D-백] 오답 신고를 `새표본235_오답.tsv` 와 **같은 4열 TSV** 로 내보낸다.

    상품명 \\t 붙은 품목 \\t 유형 \\t 왜 오답인가

⚠ **유형·왜 오답인가 칸은 비어 있다.** 판정은 사람이 한다 - 여기서 채우면
  신고가 곧 판정이 된다(R1). 검수자가 채운 뒤 `tests/fixtures/새표본235_오답.tsv`
  로 옮기고, 옮긴 줄은 별칭·가드 수정의 근거가 된다.

⚠ 데이터 행 **앞**에 `# id=… reported_at=… path=…` 주석 한 줄을 둔다. 오답표
  자체가 `#` 주석을 허용하므로 같은 로더가 읽고, 신고 출처는 잃지 않는다.

⚠ 셀 안의 탭·줄바꿈은 공백으로 바꾼다. 안 그러면 열이 어긋난다.

    PYTHONPATH=. python scripts/export_miss_reports.py --out /tmp/신고.tsv
    PYTHONPATH=. python scripts/export_miss_reports.py --since 2026-09-12
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.storage import SqliteWatchStore  # noqa: E402

_NAME_MAX = 120


def _cell(text: str | None) -> str:
    """탭·줄바꿈을 공백으로. 열이 어긋나면 로더가 조용히 틀린다."""
    return " ".join((text or "").replace("\t", " ").split())


def _product_name(page_text: str) -> str:
    """붙여 넣은 원문의 **첫 비어 있지 않은 줄**을 상품명으로 본다.

    ⚠ 추출기가 뽑은 product_name 이 아니다 - 신고 시점 값을 다시 만들지 않는다.
      원문 첫 줄이 상품명인 것은 도매꾹·새표본 관행이고, 아니면 검수자가 고친다.
    """
    for line in page_text.splitlines():
        if line.strip():
            return _cell(line)[:_NAME_MAX]
    return _cell(page_text)[:_NAME_MAX]


def rows_for(store: SqliteWatchStore, *, since: str | None = None) -> list[str]:
    """TSV 줄 목록. 주석 줄과 데이터 줄이 섞여 있다 - 오답표와 같은 규약."""
    out = [
        "# 오답 신고 내보내기 · 검수 전 · 상품명 | 붙은 품목 | 유형 | 왜 오답인가",
        "#",
        "# ⚠ 유형·왜 오답인가 칸은 비어 있다. 사람이 채운 뒤 새표본235_오답.tsv 로 옮긴다.",
        "# ⚠ 신고는 판정을 바꾸지 않았다 (R1). 이 파일은 검수 대기열이다.",
        "#",
    ]
    for report_id, reported_at, payload in store.miss_reports(since=since):
        d = json.loads(payload)
        out.append(
            f"# id={report_id} reported_at={reported_at} "
            f"path={d.get('extraction_path')} vendor={d.get('extractor_vendor')} "
            f"model={d.get('extractor_model')}"
        )
        out.append("\t".join([
            _product_name(d.get("page_text", "")),
            ";".join(_cell(x) for x in d.get("matched_items", [])),
            "",                                  # 유형 - 사람이 채운다
            _cell(d.get("note")),                # 셀러가 적은 말이 있으면 단서로
        ]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="기본: settings.watchlist_db_path")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD 이후만")
    ap.add_argument("--out", default="-", help="파일 경로. '-' 면 stdout")
    args = ap.parse_args()

    if args.db is None:
        from sourcing_guard.config import settings
        args.db = settings.watchlist_db_path
    store = SqliteWatchStore(args.db)
    lines = rows_for(store, since=args.since)
    text = "\n".join(lines) + "\n"
    if args.out == "-":
        sys.stdout.write(text)
    else:
        Path(args.out).write_text(text, encoding="utf-8")
        n = sum(1 for ln in lines if ln and not ln.startswith("#"))
        print(f"{args.out} · 신고 {n}건", file=sys.stderr)


if __name__ == "__main__":
    main()
