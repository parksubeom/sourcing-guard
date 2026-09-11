"""[4-o] `FindingKind` 를 키로 쓰는 **모든 표**를 한 곳에서 잠근다.

왜 만들었나
-----------
2026-09-11 에 `SCOPE_UNDETERMINED` 를 추가하니 `score()` 가 **KeyError** 를
던졌다 - `_PENALTY` 에 완전성 검사가 없었다. 그 finding 이 나오는 모든 스캔이
500 이 됐을 것이다.

`SPECIFIC`/`NON_SPECIFIC` 은 합=전체 검사가 있었는데 `_PENALTY` 는 없었다.
그러면 **다른 표에도 같은 구멍이 있을 수 있다** - 그래서 전부 찾아 각각
"완전해야 하는가 / 부분집합이어도 되는가" 를 정하고 여기 적는다.

두 갈래
-------
**완전해야 하는 표** — 빠지면 터지거나 조용히 틀린다. 임포트 시점에 단정한다.

    scorer._PENALTY                 빠지면 score() 가 KeyError → 스캔 500
    models.SPECIFIC | NON_SPECIFIC  빠지면 지표에서 그 kind 가 사라진다

**부분집합이어도 되는 표** — 특정 kind 만 특별히 다루는 것이 의도다. 다만
**새 kind 가 조용히 들어오면 알아채야** 하므로 현재 구성을 여기 박아 둔다.

⚠⚠ **이 파일이 깨지는 방식은 둘이다.**

    (가) 완전성 단정 실패 → 새 kind 를 그 표에 넣어야 한다
    (나) 부분집합 스냅샷 불일치 → 표를 **의도적으로** 바꿨으면 여기를 갱신하고,
         아니면 실수다. 갱신할 때 "왜 그 kind 가 들어가고/빠지나" 를 한 줄
         적을 것.

⚠ 새 `FindingKind` 를 추가할 때는 `models.py` 의 enum 선언 위 주석(표 목록)을
  먼저 읽을 것. 어디를 손봐야 하는지 거기 적혀 있다.

실제로 kind 를 추가하면 이 순서로 막힌다 (2026-09-11 에 실물로 확인)
------------------------------------------------------------------
    1. **앱 부팅이 실패한다**
         RuntimeError: _PENALTY 에 없는 FindingKind 가 있습니다 …
       → `scorer._PENALTY` 에 감점을 정해 넣는다.
       ⚠ 이 단계에서는 pytest 도 수집 단계에서 죽으므로 아래 체크리스트를
         **못 본다.** 순서가 그렇다 - 가장 비싼 구멍(스캔 500)을 먼저 막는다.

    2. **`test_a_new_finding_kind_forces_a_review_of_every_table` 이 깨지며
       나머지 표 목록을 보여준다.** 하나씩 검토하고 숫자를 갱신한다.

    3. 분류를 안 정했으면 `test_the_specific_split_is_complete_and_disjoint`
       가 깨진다. SPECIFIC / NON_SPECIFIC 중 하나를 골라 **이유와 함께** 넣는다.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from sourcing_guard import scorer, verifier
from sourcing_guard.models import (
    NON_SPECIFIC_FINDING_KINDS,
    SPECIFIC_FINDING_KINDS,
    FindingKind,
)

_ROOT = Path(__file__).resolve().parents[1]
_ALL = set(FindingKind)


# ── ① 완전해야 하는 표 ─────────────────────────────────────────────
def test_penalty_is_complete():
    """빠지면 `score()` 가 KeyError → 그 finding 이 나오는 모든 스캔이 500."""
    missing = _ALL - set(scorer._PENALTY)
    assert not missing, sorted(k.value for k in missing)


def test_penalty_asserts_at_import_time():
    """검사를 안 돌려도 **앱이 부팅할 때** 터져야 한다.

    ⚠ `.get(kind, 0)` 으로 바꾸지 말 것. KeyError 는 없어지지만 감점이 필요한
      kind 를 추가했을 때 **조용히 0** 이 되어 위험을 놓치는 쪽으로 틀린다.
    """
    src = inspect.getsource(scorer)
    assert "_MISSING_PENALTY" in src and "raise RuntimeError" in src
    assert "_PENALTY[f.kind]" in src, "get(…, 0) 으로 바뀌었다 - 조용히 틀린다"


def test_the_specific_split_is_complete_and_disjoint():
    """빠지면 그 kind 가 유효 결과율 계산에서 사라진다."""
    assert SPECIFIC_FINDING_KINDS | NON_SPECIFIC_FINDING_KINDS == _ALL, sorted(
        k.value for k in _ALL - SPECIFIC_FINDING_KINDS - NON_SPECIFIC_FINDING_KINDS
    )
    assert not (SPECIFIC_FINDING_KINDS & NON_SPECIFIC_FINDING_KINDS)


# ── ② 부분집합이어도 되는 표 ───────────────────────────────────────
#
# ⚠ 값을 바꾸려면 **왜** 를 함께 적을 것. 숫자만 맞추면 이 검사가 무의미해진다.
_SUBSETS: dict[str, tuple[set[str], str]] = {
    "scorer._HARD_RED": (
        {"kc_revoked", "kc_suspended", "recall_match", "rf_noncompliant"},
        # R3-b: 부재는 증거가 아니다. 정부 DB 가 **적극적으로 문제를 적어둔**
        # 것만 RED 다. 미조회·번호없음은 AMBER 이므로 여기 없는 것이 맞다.
        "정부 DB 가 문제를 적어둔 것만 (R3-b)",
    ),
    "scorer._UNKNOWN_HEADLINE_FIRST": (
        {"out_of_scope", "age_out_of_child_range"},
        # "확정된 판단" 이라 조회 실패보다 먼저 말해야 하는 것들.
        "확정된 판단이라 먼저 말한다",
    ),
    "scorer._UNKNOWN_HEADLINE": (
        {"coverage_gap", "lookup_failed"},
        "축이 빠진 사유. 확정된 판단이 있으면 그 뒤로 밀린다",
    ),
    "verifier._CERT_STATE_FINDING": (
        {"kc_verified", "kc_revoked", "kc_expired", "kc_suspended", "kc_under_action"},
        # certState 를 키로 하는 표다. FindingKind 는 **값**이므로 인증 조회
        # 결과로 나올 수 있는 kind 만 있으면 된다.
        "certState → kind 매핑. 인증 조회 결과 kind 만",
    ),
}


def _kinds_in(obj) -> set[str]:
    out = set()
    if isinstance(obj, dict):
        items = list(obj.keys()) + list(obj.values())
    else:
        items = list(obj)
    stack = list(items)
    while stack:
        x = stack.pop()
        if isinstance(x, FindingKind):
            out.add(x.value)
        elif isinstance(x, (tuple, list, set, frozenset)):
            stack.extend(x)
    return out


@pytest.mark.parametrize("name", sorted(_SUBSETS))
def test_subset_tables_have_not_drifted(name):
    """부분집합 표의 구성이 바뀌면 여기서 알아챈다."""
    mod_name, attr = name.split(".")
    mod = {"scorer": scorer, "verifier": verifier}[mod_name]
    expected, why = _SUBSETS[name]
    actual = _kinds_in(getattr(mod, attr))
    assert actual == expected, (
        f"{name} 이 바뀌었습니다 ({why}).\n"
        f"  들어온 것: {sorted(actual - expected)}\n"
        f"  빠진 것  : {sorted(expected - actual)}\n"
        f"  의도한 변경이면 tests/test_finding_kind_tables.py 의 _SUBSETS 를 "
        f"갱신하고 **왜** 를 한 줄 적으세요."
    )
    # 부분집합이라는 사실 자체도 지킨다 - 완전해지면 갈래가 바뀐 것이다.
    assert expected < {k.value for k in _ALL}, f"{name} 이 완전해졌다 - 갈래 재검토"


# ── ③ 새 kind 가 들어오면 체크리스트를 보여준다 ────────────────────
def test_a_new_finding_kind_forces_a_review_of_every_table():
    """kind 수가 바뀌면 **어느 표를 손봐야 하는지** 알려주며 깨진다.

    ⚠ 이 숫자만 고치고 넘어가지 말 것. 아래 목록을 하나씩 보고 "이 kind 가
      여기 들어가야 하나" 를 판단한 뒤 고치는 것이 이 검사의 목적이다.
    """
    assert len(_ALL) == 31, (
        f"FindingKind 가 {len(_ALL)} 개가 됐습니다. 아래를 **하나씩** 검토하세요:\n"
        "  [완전해야 함] scorer._PENALTY          - 빠지면 스캔이 500 이 된다\n"
        "  [완전해야 함] models.SPECIFIC/NON      - 빠지면 유효 결과율에서 사라진다\n"
        "  [부분집합]    scorer._HARD_RED         - 정부 DB 가 문제를 적어둔 것만 (R3-b)\n"
        "  [부분집합]    scorer._UNKNOWN_HEADLINE(_FIRST)\n"
        "  [부분집합]    verifier._CERT_STATE_FINDING\n"
        "  [부분집합]    scorer._signal_for 안의 AMBER 집합\n"
        "  [부분집합]    scorer._axes 안의 인증 축 집합\n"
        "  [화면]        static/index.html 의 kind 별 문구\n"
        "  검토 후 이 숫자를 갱신하세요."
    )


def test_models_lists_the_tables_next_to_the_enum():
    """`FindingKind` 선언 옆에 **이 enum 을 키로 쓰는 표 목록**이 있다.

    다음에 kind 를 추가하는 사람이 가장 먼저 보는 곳이 거기다.
    """
    src = (_ROOT / "sourcing_guard/models.py").read_text(encoding="utf-8")
    head = src[: src.index("class FindingKind")]
    tail = src[src.index("class FindingKind"):][:3000]
    block = head[-2500:] + tail
    for token in ("_PENALTY", "_HARD_RED", "SPECIFIC_FINDING_KINDS",
                  "test_finding_kind_tables"):
        assert token in block, f"enum 옆 표 목록에 '{token}' 이 없다"


def test_the_sweep_that_found_these_tables_is_written_down():
    """어떻게 찾았는지가 적혀 있어야 다음에 다시 찾을 수 있다."""
    src = Path(__file__).read_text(encoding="utf-8")
    assert "KeyError" in src and "500" in src
    # 실제로 지금 소스에 우리가 모르는 큰 표가 또 있는지 훑는다.
    found = []
    for p in sorted((_ROOT / "sourcing_guard").rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Dict, ast.Set)):
                try:
                    u = ast.unparse(node)
                except Exception:
                    continue
                if u.count("FindingKind.") >= 4:
                    found.append(f"{p.relative_to(_ROOT)}:{node.lineno}")
    # 알고 있는 자리 수. 늘면 새 표가 생긴 것이다.
    # ⚠ 7 이다 - 처음에 6 으로 적었다가 실측에서 틀렸다. 세어 보고 적을 것.
    #   models 2 · scorer 4(_PENALTY · _HARD_RED · _signal_for AMBER · _axes 인증)
    #   · verifier 1(_CERT_STATE_FINDING)
    assert len(found) == 7, (
        "FindingKind 를 4개 이상 담은 자리가 바뀌었습니다:\n  "
        + "\n  ".join(found)
        + "\n  새 표면 _SUBSETS 에 추가하거나 완전성 단정을 붙이세요."
    )
