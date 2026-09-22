"""미리 만들어 둔 산출물의 「적힌 번호 vs 근거 번호」를 잠근다.

왜 (2026-09-22)
---------------
`_pick_exact`(정확 일치)를 넣었는데 **같은 날 두 번 우회당했다**:

    showcase.json   옛 `rows[0]` 로 기록된 사본이 조회를 아예 안 한다
    cert_seed.json  옛 `rows[0]` 로 만든 시드가 **캐시에서 조회를 끝낸다**

고침은 코드에 닿고 데이터에는 안 닿는다. 그래서 산출물을 검사로 묶는다.

⚠ 실호출 0회. 파일 안에서 두 값을 맞춰 볼 뿐이다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "audit_recorded_certs", _ROOT / "scripts" / "audit_recorded_certs.py")
_AUDIT = importlib.util.module_from_spec(_SPEC)
sys.modules["audit_recorded_certs"] = _AUDIT
_SPEC.loader.exec_module(_AUDIT)


def _mismatches(rel: str) -> list[tuple[frozenset, str]]:
    import json

    from sourcing_guard.kats_client import normalize_kc

    p = _ROOT / rel
    pairs: list = []
    _AUDIT.walk(json.loads(p.read_text(encoding="utf-8")), frozenset(), pairs)
    named = [(a, b) for a, b in pairs if a]
    return [(a, b) for a, b in named
            if normalize_kc(b) not in {normalize_kc(x) for x in a}
            and (rel, b) not in _AUDIT.KNOWN_OK]


@pytest.mark.parametrize("rel", _AUDIT.TARGETS)
def test_no_recorded_artifact_points_at_a_different_number(rel):
    """근거가 **셀러가 적지 않은 번호**를 가리키면 그것이 거짓 GREEN 의 씨앗이다.

    실측으로 확정됐다 (2026-09-22 · 실호출):
        셀러가 적은 CB064R2424-9001  → **기간만료**
        근처 번호   CB064R2424-9001r → 적합   ← 사본이 GREEN 근거로 쓰던 것
    두 번호는 **인증상태가 다르다.** 우리는 「적합」이라고 말했고 그 셀러의
    번호는 만료였다.
    """
    if not (_ROOT / rel).is_file():
        pytest.skip(f"{rel} 없음")
    bad = _mismatches(rel)
    assert not bad, [(sorted(a), b) for a, b in bad][:8]


def test_the_audit_actually_pairs_things_up():
    """**짝을 못 지으면 「불일치 0」이 나온다.** 그건 깨끗한 것이 아니다.

    이 도구는 만들면서 두 번 그렇게 틀렸다 - 한 번은 가장 가까운 상위로 덮어
    「담긴 것끼리」 비교했고(시드 불일치 0 · 실제 5), 한 번은 형제 노드를 못
    이어 근거 URL 108개가 통째로 안 잡혔다. 둘 다 출력이 깨끗해 보였다.
    """
    import json

    seen = {}
    for rel in _AUDIT.TARGETS:
        p = _ROOT / rel
        if not p.is_file():
            continue
        pairs: list = []
        _AUDIT.walk(json.loads(p.read_text(encoding="utf-8")), frozenset(), pairs)
        seen[rel] = (len(pairs), len([1 for a, _ in pairs if a]))

    # 근거 URL 이 있는 파일은 **짝도 지어져야** 한다. 「적힌 값」이 없는 파일은
    # 화면-링크 검사로 따로 본다 (_SHOWN_VS_LINK).
    for rel, (urls, paired) in seen.items():
        if rel in _AUDIT._SHOWN_VS_LINK or urls == 0:
            continue
        assert paired == urls, f"{rel}: 근거 {urls}개 중 {paired}개만 짝지었다"
    assert sum(u for u, _ in seen.values()) > 200, "볼 근거 URL 이 너무 적다 - 침묵이다"


def test_every_known_exception_says_why():
    """이유 없이 목록에 든 항목은 **다음 사람이 지운다** (총괄 2026-09-22).

    반대쪽도 잠근다 - 이미 나은 항목이 목록에 남아 있으면 그것도 실패다.
    """
    assert _AUDIT.KNOWN_OK, "예외 목록이 비었다 - 그러면 이 검사는 침묵이다"
    for (rel, num), why in _AUDIT.KNOWN_OK.items():
        assert len(why) > 20, f"{rel} {num} 의 이유가 너무 짧다: {why!r}"
    # 반대쪽 - 파일에서 사라진 번호가 목록에 남아 있으면 그것도 실패다.
    # 안 잡으면 다 나은 뒤에도 목록이 조용히 커진 채로 남는다.
    stale = []
    for rel, num in _AUDIT.KNOWN_OK:
        if not (_ROOT / rel).is_file():
            continue
        if num not in {b for _, b in _all_pairs(rel)}:
            stale.append((rel, num))
    assert not stale, f"파일에 없는 번호가 예외 목록에 남아 있다: {stale}"


def _all_pairs(rel: str):
    import json

    pairs: list = []
    p = _ROOT / rel
    if p.is_file():
        _AUDIT.walk(json.loads(p.read_text(encoding="utf-8")), frozenset(), pairs)
    return pairs


def test_shown_number_equals_the_linked_number():
    """「적힌 값」이 없는 파일은 **화면 번호 vs 링크 번호**로 잰다.

    둘 다 화면에 나가는 값이고, 갈리면 그 자체가 결함이다.
    """
    import json

    from sourcing_guard.kats_client import normalize_kc

    checked = 0
    for rel in _AUDIT._SHOWN_VS_LINK:
        p = _ROOT / rel
        if not p.is_file():
            continue
        rows: list = []
        _AUDIT.shown_vs_link(json.loads(p.read_text(encoding="utf-8")), rows)
        assert rows, f"{rel}: 볼 근거가 없다"
        for shown, link in rows:
            assert any(normalize_kc(x) == normalize_kc(link) for x in shown), (
                f"{rel}: 문장은 {shown} 인데 링크는 {link!r}")
            checked += 1
    assert checked >= 2, f"{checked}건만 봤다"
