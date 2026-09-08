"""검수 파일을 읽고 정답·애매·오답을 가리는 **단 하나의** 구현.

⚠ 2026-09-08 에 이 파일이 생긴 이유: 같은 일을 하는 집계가 **셋**으로
  갈라져 있었고 서로 달랐다.

    scripts/measure_single_path_full.py   실 API 측정
    scripts/replay_single_path.py         저장 답 재생 (그날 급히 만들었다)
    tests/test_item_grades.py             회귀 락

  갈라진 결과로 기획서에 77.8% 를 적었는데 실제는 77.0% 였다. 이 저장소의
  반복 결함이 문서가 코드보다 앞서 나가는 것이고, 그 원인이 이번에는
  **측정 도구가 여럿인 것**이었다. 그래서 하나로 모은다.

⚠ 검수 파일은 **(상품명, 붙은 품목)** 쌍이다. 상품명만 보면 같은 상품에
  다른(맞는) 품목이 붙어 고쳐져도 계속 오답으로 센다 - 145번 곰돌이비치타월
  (오답으로 적힌 것은 `공기주입물놀이기구`, 지금 붙는 것은 `의류`)과
  네온T 무드등(적힌 것 `선풍기`, 지금 `가습기`)이 그랬다.
"""
from __future__ import annotations

from pathlib import Path

SCOPE_FILE = Path("tests/fixtures/새표본235_대상분류.tsv")
AUDIT_FILE = Path("tests/fixtures/새표본235_오답.tsv")


def load_scope(path: Path | None = None) -> dict[str, str]:
    """상품명 → 대상 / 비대상 / 애매."""
    out: dict[str, str] = {}
    for line in (path or SCOPE_FILE).read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        _no, verdict, name, _why = line.split("\t")
        out[name] = verdict
    return out


def load_audit(path: Path | None = None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(상품명 → 오답 품목 집합), (상품명 → 애매 품목 집합)."""
    wrong: dict[str, set[str]] = {}
    vague: dict[str, set[str]] = {}
    section = None
    for line in (path or AUDIT_FILE).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            if "--- 오답" in line:
                section = "wrong"
            elif "[애매]" in line:
                section = "vague"
            elif "[검수했고 정답]" in line or "[고쳐짐" in line:
                section = None
            continue
        if not line.strip() or section is None:
            continue
        cells = line.split("\t")
        bucket = wrong if section == "wrong" else vague
        bucket.setdefault(cells[0], set()).add(cells[1].strip() if len(cells) > 1 else "")
    return wrong, vague


def verdict(name: str, items: list[str] | set[str], wrong, vague) -> str:
    """'ok' / 'vague' / 'wrong'. 붙은 품목이 검수 파일과 겹칠 때만 오답·애매다."""
    got = set(items)
    if got & wrong.get(name, set()):
        return "wrong"
    if got & vague.get(name, set()):
        return "vague"
    return "ok"


def tally(results: dict[str, list[str]], scope=None, audit=None) -> dict[str, int]:
    """상품명 → 붙은 품목 목록을 받아 네 칸으로 센다."""
    scope = scope or load_scope()
    wrong, vague = audit or load_audit()
    target = [n for n in results if scope.get(n) == "대상"]
    hit = [n for n in target if results[n]]
    bad = [n for n in hit if verdict(n, results[n], wrong, vague) == "wrong"]
    amb = [n for n in hit if verdict(n, results[n], wrong, vague) == "vague"]
    return {
        "denominator": len(target),
        "ok": len(hit) - len(bad) - len(amb),
        "vague": len(amb),
        "wrong": len(bad),
        "missed": len(target) - len(hit),
        "off_target": len([n for n in results if results[n] and scope.get(n) == "비대상"]),
        "on_vague": len([n for n in results if results[n] and scope.get(n) == "애매"]),
        "matched_all": len([n for n in results if results[n]]),
    }
