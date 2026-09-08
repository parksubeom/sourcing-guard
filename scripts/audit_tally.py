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

import json
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


def load_reviewed_pairs(*sources: str | Path) -> set[tuple[str, str]]:
    """**사람이 실제로 본 (상품명, 품목) 쌍**의 집합.

    ⚠ 이것 없이는 `verdict` 가 부풀린다. 검수 목록은 Claude 추출 기준으로
      만들어졌으므로, 다른 추출기가 **다르게 붙인 쌍은 검수된 적이 없는데도**
      오답·애매 목록에 없다는 이유로 "ok" 로 잡힌다.

      그래서 추출기를 바꿔 재는 측정은 두 숫자를 함께 낸다:
        (1) 검수된 쌍만 정답으로 센 값
        (2) 미검수 N 건을 모두 정답으로 가정한 **상한**
      미검수는 사람이 검수해야 한다 - 코드가 정답 판정을 하지 않는다.

    무엇이 "본 쌍" 인가:
      - 측정 원자료의 `single`·`batch` 에 실제로 붙었던 쌍. 검수표가 두 경로를
        모두 다뤘고, 오답표 항목에도 배치 결과가 들어 있다(다림질 매트 →
        스팀다리미가 그것이다).
      - 오답·애매 목록에 적힌 쌍.
    """
    pairs: set[tuple[str, str]] = set()
    for src in sources:
        rows = json.loads(Path(src).read_text(encoding="utf-8"))
        for r in rows:
            for key in ("single", "batch"):
                for item in r.get(key) or ():
                    pairs.add((r["name"], item))
    wrong, vague = load_audit()
    for bucket in (wrong, vague):
        for name, items in bucket.items():
            for item in items:
                if item:
                    pairs.add((name, item))
    return pairs


def verdict(
    name: str,
    items: list[str] | set[str],
    wrong,
    vague,
    reviewed: set[tuple[str, str]] | None = None,
) -> str:
    """'ok' / 'vague' / 'wrong' / 'unreviewed'.

    붙은 품목이 검수 파일과 겹칠 때만 오답·애매다.

    ⚠ `reviewed` 를 주면 **검수된 적 없는 쌍**을 'unreviewed' 로 가른다.
      주지 않으면 예전 동작 그대로다 - Claude 기준 재생·회귀 락은 원자료가
      그 검수의 출처이므로 미검수가 나올 수 없다.

    ⚠ **쌍 하나라도 미검수면 그 줄은 미검수다.** "하나라도 검수됐으면 ok" 로
      두면 갈림이 새어 나간다 - GPT 가 2번 전기매트에 ['전기매트','전기요'] 를
      붙였을 때 '전기매트' 만 검수됐고 '전기요' 는 검수된 적이 없다. 그 줄을
      정답으로 세면 화면에 뜨는 후보 중 검수 안 된 것이 섞여 들어간다.

    ⚠ **갈림(ITEM_GRADE_SPLIT)은 별도 칸이 아니다.** 83.7% 측정 때와 같이
      후보 전부를 "붙은 것" 으로 모으고(grades_for), 그 쌍들을 이 함수가
      가린다. 측정 중에 이 규칙을 바꾸지 않는다.
    """
    got = set(items)
    if got & wrong.get(name, set()):
        return "wrong"
    if got & vague.get(name, set()):
        return "vague"
    if reviewed is not None and got and not all((name, i) in reviewed for i in got):
        return "unreviewed"
    return "ok"


def tally(
    results: dict[str, list[str]],
    scope=None,
    audit=None,
    reviewed: set[tuple[str, str]] | None = None,
) -> dict[str, int]:
    """상품명 → 붙은 품목 목록을 받아 센다.

    `reviewed` 를 주면 미검수를 따로 뽑고 **정답에서 뺀다.** 그때 `ok_upper`
    가 "미검수를 모두 정답으로 가정한 상한" 이다 - 두 숫자를 함께 보고한다.
    """
    scope = scope or load_scope()
    wrong, vague = audit or load_audit()
    target = [n for n in results if scope.get(n) == "대상"]
    hit = [n for n in target if results[n]]
    calls = {n: verdict(n, results[n], wrong, vague, reviewed) for n in hit}
    bad = [n for n in hit if calls[n] == "wrong"]
    amb = [n for n in hit if calls[n] == "vague"]
    new = [n for n in hit if calls[n] == "unreviewed"]
    ok = len(hit) - len(bad) - len(amb) - len(new)
    return {
        "denominator": len(target),
        "ok": ok,
        "ok_upper": ok + len(new),
        "unreviewed": len(new),
        "vague": len(amb),
        "wrong": len(bad),
        "missed": len(target) - len(hit),
        "off_target": len([n for n in results if results[n] and scope.get(n) == "비대상"]),
        "on_vague": len([n for n in results if results[n] and scope.get(n) == "애매"]),
        "matched_all": len([n for n in results if results[n]]),
    }
