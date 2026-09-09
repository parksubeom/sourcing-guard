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


def _sections(path: Path | None = None) -> dict[str, dict[str, set[str]]]:
    """검수 파일을 절별로 읽는다. 절 이름 → {상품명: 품목 집합}.

    ⚠ `[검수했고 정답]` 절이 **2026-09-08 부터 기계가 읽는 절**이다. 전에는
      주석뿐이어서 `load_reviewed_pairs` 가 읽지 못했고, 91번(에어핏 러닝
      조끼 백팩)은 그 절에 적혀 있는데도 "미검수" 로 나왔다 - 사람이 검수한
      기록이 코드에 닿지 않은 것이다.

    ⚠ `[고쳐짐...]` 절은 계속 주석이다. 그 절은 "지금은 안 붙는다" 를 적은
      것이므로 붙은 쌍이 없다.
    """
    out: dict[str, dict[str, set[str]]] = {"wrong": {}, "vague": {}, "correct": {}}
    section = None
    for line in (path or AUDIT_FILE).read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            if "--- 오답" in line:
                section = "wrong"
            elif "[애매]" in line:
                section = "vague"
            elif "[검수했고 정답]" in line:
                section = "correct"
            elif "[고쳐짐" in line:
                section = None
            continue
        if not line.strip() or section is None:
            continue
        cells = line.split("\t")
        out[section].setdefault(cells[0], set()).add(
            cells[1].strip() if len(cells) > 1 else ""
        )
    return out


def load_audit(path: Path | None = None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(상품명 → 오답 품목 집합), (상품명 → 애매 품목 집합).

    ⚠ 반환은 둘로 유지한다. `[검수했고 정답]` 절은 `load_correct()` 로 따로
      읽는다 - 여기에 세 번째를 더하면 모든 호출부가 깨진다.
    """
    sec = _sections(path)
    return sec["wrong"], sec["vague"]


def load_correct(path: Path | None = None) -> dict[str, set[str]]:
    """`[검수했고 정답]` 절. 상품명 → 사람이 정답이라 판정한 품목 집합."""
    return _sections(path)["correct"]


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
    # 오답·애매·[검수했고 정답] 세 절 모두 사람이 본 것이다.
    sec = _sections()
    for bucket in (sec["wrong"], sec["vague"], sec["correct"]):
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

#: 재생 기준선. **여기가 한 곳이다** — 스크립트 출력과 `test_docs` 가 같은 값을
#: 본다. 규칙을 고친 뒤 재생해서 이 표와 다르면 **다섯 중 무엇이 움직였는지**
#: 보고에 적는다.
#:
#: ⚠ 2026-09-09 에 이 표가 생긴 이유: 4-e 를 넣었을 때 통과 기준에 없던
#:   `on_vague`(애매 부착)가 1 → 2 로 움직였고 **보고에서 빠졌다.** 기준을
#:   네 개만 세면 다섯째가 조용히 움직인다. 그래서 한 표로 묶고 검사로 잠근다.
#:
#: ⚠ `on_vague` 는 **분모 밖이라 정답률에 안 보인다.** 그러나 화면에는 보인다 -
#:   애매로 판정한 줄에 등급이 붙으면 셀러는 그것을 답으로 읽는다. `off_target`
#:   과 같은 종류다.
#:
#: 재생 명령 (LLM 0회):
#:     PYTHONPATH=. python scripts/replay_single_path.py
#:     PYTHONPATH=. python scripts/replay_single_path.py \
#:       --src tests/fixtures/단건경로_gpt.json
BASELINE: dict[str, dict[str, int]] = {
    # Claude · 단건 · 상품명만 · 분모 대상 135 · 커밋 e61ce1e 되돌린 뒤
    "claude": {
        "denominator": 135,
        "ok": 99,            # 검수된 쌍만 (73.3%)
        "ok_upper": 113,     # 미검수 포함 상한 (83.7%)
        "unreviewed": 14,
        "vague": 2,
        "wrong": 1,
        "missed": 19,
        "off_target": 0,     # ⚠ 0 이 아니면 발표에 쓸 수 없다
        "on_vague": 1,       # 포워드테크 다림질 매트 → 스팀다리미 (오답표에 있던 줄)
    },
    # GPT · 같은 조건
    "gpt": {
        "denominator": 135,
        "ok": 95,            # (70.4%)
        "ok_upper": 113,     # (83.7%) — Claude 와 우연히 같다
        "unreviewed": 18,
        "vague": 2,
        "wrong": 1,
        "missed": 19,
        "off_target": 0,
        "on_vague": 3,       # 넉박스 ×2 → 커피메이커 · 다림질 매트 → 스팀다리미
    },
}

#: 다섯 기준의 **③** — 표본별 매칭 건수. `lookup_all` 기준이고 LLM 이 없다.
#:
#: ⚠ 2026-09-09 에 살렸다. `scripts/measure_matcher.py` 가 자기검사에서 멈춰
#:   ③ 이 죽어 있었고, 그러면 회귀 방어가 둘뿐이다 (미완 4-f).
#:
#: ⚠ **도매꾹239 는 별칭을 만들 때 쓴 표본이다.** 거기서 재면 우리가 맞춘 것을
#:   다시 맞춘 숫자가 나온다 - 발표에 쓰지 않는다. 회귀 감지용 기준선이다.
#:
#: 재생:
#:     PYTHONPATH=. python scripts/measure_matcher.py --sample tests/fixtures/도매꾹239.txt
#:     PYTHONPATH=. python scripts/measure_matcher.py
BASELINE_MATCH: dict[str, dict[str, int]] = {
    # 09-04 로그는 170/239(71.1%)이었다. 지금 168 이고 **차이 2건은 둘 다 오답을
    # 지운 것**이다 - 정답 손실 0 (미완 4-f · 4-g). 개선/악화로 읽지 말 것:
    # 붙는 수가 줄어든 것이 오답을 지운 결과다.
    #
    #   167 → 168  4-g 에서 `'걸이'` 를 부속품명 목록에서 뺐다. `벽걸이히터` 가
    #              `걸이` 로 읽혀 `전기온풍기` 를 잃고 있었다.
    "도매꾹239": {"matched": 168, "total": 239},
    "새표본235": {"matched": 116, "total": 235},
}


#: 애매 부착으로 알려진 줄. 늘면 그 줄을 보고에 적는다 (기준 ⑤).
BASELINE_ON_VAGUE: dict[str, tuple[str, ...]] = {
    "claude": (
        "포워드테크 휴대용 접이식 다림질 매트 다리미판 좌식 걸이형 스팀 다리미 시트",
    ),
    "gpt": (
        "넉박스 커피 찌꺼기통 홈카페 바리스타 커피머신",
        "포워드테크 휴대용 접이식 다림질 매트 다리미판 좌식 걸이형 스팀 다리미 시트",
        "홈카페 넉박스 커피찌꺼기통 바리스타 커피머신",
    ),
}


def compare_baseline(got: dict[str, int], which: str) -> list[str]:
    """기준선과 다른 항목을 사람이 읽을 줄로. 같으면 빈 목록."""
    base = BASELINE.get(which) or {}
    return [
        f"{k}: 기준선 {base[k]} → 지금 {got[k]}"
        for k in base
        if k in got and got[k] != base[k]
    ]


# 미검수 목록에 붙이는 **참고** 근거. 품목명 기준이다.
#
# ⚠ 참고일 뿐 판정이 아니다. 사람이 검수해서 `[검수했고 정답]` 절이나
#   오답·애매 절로 옮겨야 reviewed 에 들어간다.
#
# ⚠ 품목명 기준으로 둔 이유: 측정마다 상품명이 달라지므로 상품명 매핑은
#   금방 낡는다. "이 품목을 붙이기로 한 근거" 는 커밋에 남아 있고 품목이
#   바뀌지 않는 한 유효하다.
REVIEW_NOTES: dict[str, str] = {
    "의류": (
        "930d95a · 안전기준준수 부속서 1 [표 1] 중의류 \"셔츠, 타올, 장갑 … "
        "헤어밴드, 가발, 귀마개, 토시 등\" · 외의류 \"모자, 숄, 머플러, "
        "스카프, 앞치마\". 만 14세 이상이라 어린이 표지어가 있으면 닫힌다"
    ),
    "의류 이외의 섬유제품": (
        "a85a3b5(모기장) · 4592440(가방) · 안전기준준수 부속서 1 [표 1] "
        "기타 제품류 \"가방, 쿠션류, 방석류, 모기장, 커튼, 수의, 덮개 등\". "
        "3.6 이 \"직접 착용하지 않는 제품\" 이라 적어 이 품목으로 보냈다"
    ),
    "공기주입물놀이기구": (
        "안전인증 부속서 7 서문에 연령 범위가 없다. 성인용 표기가 있어도 대상"
    ),
    "완구": "미검수 - 이번 측정에서 처음 붙었다",
    "LED마스크": "미검수 - 이번 측정에서 처음 붙었다",
    "커피메이커": "미검수 - 이번 측정에서 처음 붙었다",
    "전기프라이팬": (
        "미검수 · **의심** - 상위어 승격으로 보인다. legal='프라이팬' 이 "
        "'전기프라이팬' 에 포함돼 확장됐다. 21·23번 냄비와 같은 패턴"
    ),
    "전기면도기": (
        "미검수 · **의심** - 상위어 승격으로 보인다. '면도기' 가 "
        "'전기면도기' 에 포함돼 확장됐다"
    ),
}


def review_note(items: list[str] | set[str]) -> str:
    """미검수 쌍에 붙일 참고 근거. 없으면 빈 문자열."""
    for item in items:
        if item in REVIEW_NOTES:
            return REVIEW_NOTES[item]
    return ""
