"""rewrite 전 커밋 해시가 살아 있는 참조에 남아 있지 않은지 잠근다.

⚠ 2026-09-09 에 author·committer 이메일만 바꾸는 rewrite 로 **커밋 해시
  168개가 전부 바뀌었다.** 그때 살아 있는 참조 71건을 새 해시로 옮겼다.

  죽은 참조는 단순한 오타가 아니다. `단건경로_claude_235.md` 는 발표 숫자를
  어느 커밋에서 쟀는지 적어 재현 좌표로 쓰고, `measure_matcher.py` 는 09-04
  로그와 대조하려고 옛 커밋을 worktree 로 체크아웃한다 - 참조가 어긋나면
  **숫자를 어디서 쟀는지 되짚을 수 없다.** 이 저장소의 반복 결함이 "문서가
  코드보다 앞서 나감" 이고, 이것이 그 결함의 가장 비싼 형태다.

⚠⚠ **"실재하는가" 로 검사하면 안 된다.** 처음에 `git cat-file -e` 로 짰다가
  검증에서 실패했다 - 옛 커밋 168개는 **여전히 실재한다.** 백업 ref
  (`backup/pre-rewrite-2026-09-09` · 로컬 `backup/local-2026-09-01`)가
  reachable 하게 붙들고 있고 그 백업은 원격에도 있다. 그래서 실재 검사는
  전부 통과하며 아무것도 잡지 못한다.

  잡아야 하는 것은 "존재하지 않는 해시" 가 아니라 **"rewrite 전 해시를 아직
  가리키는 참조"** 다. 그래서 대응표의 옛 해시 열과 **문자열로** 대조한다.
  백업을 나중에 지워도, 안 지워도 같게 동작한다.

⚠ `docs/작업로그_*.md` 는 검사 대상이 **아니다.** 과거 날짜 작업로그는 그 날의
  기록이므로 고치지 않는다 - 옛 해시가 남아 있는 것이 정상이고,
  `docs/해시_대응표_rewrite_2026-09-09.md` 로 새 해시를 찾는다.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TABLE = _ROOT / "docs/해시_대응표_rewrite_2026-09-09.md"
_HEX = re.compile(r"\b[0-9a-f]{7,10}\b")
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build", "dist-cdn"}
_SUFFIXES = {".md", ".py", ".yaml", ".yml"}

#: 이 두 갈래는 옛 해시를 **일부러** 담는다. 빼는 것이 실수가 아니다.
_EXEMPT = ("작업로그_", "해시_대응표_")

#: rewrite 전 **옛 HEAD**. 백업이 어디 있는지 가리키는 좌표이므로 새 해시로
#: 바꾸면 틀린다 - `backup/pre-rewrite-2026-09-09` 가 가리키는 것은 이것이다.
#:
#: ⚠ 이 예외는 **하나뿐이어야 한다.** 늘어나면 그것은 "갱신을 미룬 참조" 를
#:   예외로 덮은 것이다. 아래 검사가 개수를 잠근다.
_OLD_HEAD = "1ebf65f089765c37a9ed6c8d35057dd74f5e95c7"
_INTENTIONAL = {_OLD_HEAD[:length] for length in range(7, 11)} | {_OLD_HEAD}

#: 표 행: `| 2026-09-08 | `옛9자` | `새9자` | 제목 |`
_ROW = re.compile(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*`([0-9a-f]{9})`\s*\|\s*`([0-9a-f]{9})`\s*\|")


def _rows() -> list[tuple[str, str, str]]:
    return _ROW.findall(_TABLE.read_text(encoding="utf-8"))


def _live_files() -> list[Path]:
    out = []
    for p in sorted(_ROOT.rglob("*")):
        if not p.is_file() or p.suffix not in _SUFFIXES:
            continue
        rel = p.relative_to(_ROOT)
        if any(d in rel.parts for d in _SKIP_DIRS):
            continue
        if any(tag in str(rel) for tag in _EXEMPT):
            continue
        out.append(p)
    return out


def test_the_mapping_document_survives():
    """대응표가 없으면 작업로그의 옛 해시를 되짚을 길이 사라진다."""
    assert _TABLE.exists(), "해시 대응표가 사라졌습니다"
    text = _TABLE.read_text(encoding="utf-8")
    assert len(_rows()) == 168, f"대응표 행이 168개가 아닙니다: {len(_rows())}"
    # 옛 히스토리를 어디서 찾는지 문서가 말해야 한다.
    assert "backup/pre-rewrite-2026-09-09" in text
    assert "1ebf65f089765c37a9ed6c8d35057dd74f5e95c7" in text


def test_no_pre_rewrite_hash_remains_in_live_references():
    """살아 있는 참조가 rewrite 전 해시를 가리키지 않는다.

    ⚠ 여기서 깨지면 **참조를 지우지 말고** 대응표로 새 해시를 찾아 옮길 것.
    """
    old_by_prefix: dict[str, str] = {}
    for _date, old, new in _rows():
        for length in range(7, 10):
            old_by_prefix.setdefault(old[:length], new[:length])

    stale: list[str] = []
    for p in _live_files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            for tok in sorted(set(_HEX.findall(line))):
                if tok in _INTENTIONAL:
                    continue
                if tok in old_by_prefix:
                    stale.append(
                        f"{p.relative_to(_ROOT)}:{lineno}  {tok} → {old_by_prefix[tok]}"
                    )
    assert not stale, (
        "rewrite 전 해시가 살아 있는 참조에 남아 있습니다 - 대응표로 옮기세요:\n  "
        + "\n  ".join(stale)
    )


@pytest.mark.skipif(
    subprocess.run(
        ["git", "-C", str(_ROOT), "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True,
    ).stdout.strip() != "false",
    reason="shallow clone 에서는 새 해시를 확인할 수 없다",
)
def test_the_new_hashes_in_the_table_are_real_commits():
    """대응표의 **새** 해시 쪽은 이 저장소에 실재한다.

    ⚠ 옛 해시 쪽은 확인하지 않는다 - 백업 ref 유무에 따라 답이 달라지므로
      검사에 넣으면 백업을 지운 날 이유 없이 깨진다.
    """
    missing = []
    for _date, _old, new in _rows():
        got = subprocess.run(
            ["git", "-C", str(_ROOT), "cat-file", "-e", f"{new}^{{commit}}"],
            capture_output=True,
        )
        if got.returncode != 0:
            missing.append(new)
    assert not missing, f"대응표의 새 해시가 실재하지 않습니다: {missing[:5]}"


def test_worklogs_are_exempt_on_purpose():
    """작업로그가 대상에서 빠진 것이 실수가 아님을 코드로 적어 둔다."""
    src = Path(__file__).read_text(encoding="utf-8")
    assert "_EXEMPT" in src and "작업로그_" in src
    logs = sorted((_ROOT / "docs").glob("작업로그_*.md"))
    assert logs, "작업로그가 없다 - 이 검사의 전제가 바뀌었나"
    # 실제로 옛 해시가 남아 있어야 정상이다 - 남아 있음을 확인해 둔다.
    olds = {old for _d, old, _n in _rows()}
    joined = "\n".join(p.read_text(encoding="utf-8") for p in logs)
    assert any(o[:7] in joined for o in olds), (
        "작업로그에 옛 해시가 하나도 없다 - 누가 작업로그를 고쳤나"
    )


def test_the_only_intentional_old_hash_is_the_pre_rewrite_head():
    """의도적 예외가 옛 HEAD 하나뿐임을 잠근다.

    ⚠ 예외를 늘려 검사를 통과시키는 것이 이 가드를 무력화하는 가장 쉬운 길이다.
      옛 HEAD 는 백업 좌표라서 새 해시로 옮길 수 없지만, 그 밖의 옛 해시는
      전부 옮길 수 있고 옮겨야 한다.
    """
    assert _OLD_HEAD == "1ebf65f089765c37a9ed6c8d35057dd74f5e95c7"
    # 길이별 접두 4개(7~10자) + 40자 전체 = 5개. 그 이상이면 다른 해시가 섞였다.
    assert len(_INTENTIONAL) == 5, f"의도적 예외가 늘었습니다: {sorted(_INTENTIONAL)}"
    # 옛 HEAD 는 대응표의 옛 해시 열에 실제로 있어야 한다 - 없으면 좌표가 틀렸다.
    olds = {old for _d, old, _n in _rows()}
    assert _OLD_HEAD[:9] in olds, "옛 HEAD 가 대응표에 없습니다 - 좌표를 확인하세요"
