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
import unicodedata
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TABLE = _ROOT / "docs/해시_대응표_rewrite_2026-09-09.md"
_HEX = re.compile(r"\b[0-9a-f]{7,10}\b")
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build", "dist-cdn"}
_SUFFIXES = {".md", ".py", ".yaml", ".yml"}

#: 이 두 갈래는 옛 해시를 **일부러** 담는다. 빼는 것이 실수가 아니다.
_EXEMPT = ("작업로그_", "해시_대응표_")


def _nfc(text: str) -> str:
    """한글 파일명을 비교하기 전에 반드시 거친다.

    ⚠⚠ **macOS 는 파일명을 NFD(분해형)로 들고, 소스의 문자열 리터럴은
      NFC(결합형)다.** 같은 "작업로그_" 가 바이트로 다르다. 그래서
      `Path.glob("작업로그_*.md")` 와 `str(path).startswith("작업로그_")` 가
      **파일시스템에 따라 조용히 0건을 돌려준다** - `exists()` 는 OS 가
      정규화를 맞춰 주므로 통과하는데 glob·문자열 비교만 어긋나서 더 헷갈린다.

    이 함수가 없어서 실제로 사고가 났다. 이 가드를 처음 짰을 때 개발 PC(NFC)
    에서는 4건 전부 통과했지만, 새 PC 를 재현한 트리(NFD)에서는 작업로그 예외가
    먹지 않아 97건이 전부 "죽은 참조" 로 잡히고 `glob` 은 빈 목록을 줬다.
    [E-1] 이 지적한 "내 PC 에서만 통과하는 검사" 를 가드 자체가 저지른 것이다.
    """
    return unicodedata.normalize("NFC", text)

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
        # ⚠ 반드시 NFC 정규화 후 비교한다 - `_nfc` 주석 참조.
        if any(tag in _nfc(str(rel)) for tag in _EXEMPT):
            continue
        out.append(p)
    return out


def _worklogs() -> list[Path]:
    """`docs/작업로그_*.md`. ⚠ `glob` 을 쓰지 않는다 - `_nfc` 주석 참조."""
    docs = _ROOT / "docs"
    if not docs.is_dir():
        return []
    return sorted(
        p for p in docs.iterdir()
        if p.is_file() and p.suffix == ".md" and _nfc(p.name).startswith("작업로그_")
    )


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


#: git 저장소가 아니거나 shallow 면 옛/새 커밋을 확인할 수 없다.
#: ⚠ 이 skip 은 **하나뿐이어야 한다.** 나머지 3건은 git 없이도 돈다 - 대응표
#:   자체의 정합성(행 수·형식·백업 좌표)과 살아 있는 참조는 파일만 있으면
#:   검사된다. "git 없으면 전부 skip" 으로 만들면 아무것도 지키지 않는다.
_HAS_GIT_HISTORY = (
    (_ROOT / ".git").exists()
    and subprocess.run(
        ["git", "-C", str(_ROOT), "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True,
    ).stdout.strip() == "false"
)


@pytest.mark.skipif(
    not _HAS_GIT_HISTORY,
    reason="git 저장소가 아니거나 shallow clone 이라 커밋 실재를 확인할 수 없다",
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
    logs = _worklogs()
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


def test_korean_filenames_are_compared_after_nfc_normalization():
    """한글 파일명 비교가 정규화를 거치는지 잠근다.

    ⚠ 이 가드가 실제로 NFD 트리에서 깨진 뒤에 추가했다. `glob` 으로 되돌리면
      개발 PC 에서는 통과하고 새 PC · CI 에서만 깨진다 - 가장 나쁜 종류의 검사다.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    assert "_nfc(" in src and "unicodedata.normalize" in src

    # ⚠ 소스 문자열 검사로 짜면 **이 검사의 설명 주석 자체에 걸린다.** 실제로
    #   걸렸다 - 정적 자산 이모지 검사에 내 주석의 기호가 걸린 것과 같은 종류다.
    #   그래서 문자열이 아니라 **실제 호출**을 본다.
    import ast

    bad = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in {"glob", "rglob"}):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if any(ord(ch) > 0x7F for ch in arg.value):
                    bad.append(f"{fn.attr}({arg.value!r}) at line {node.lineno}")
    assert not bad, (
        "glob 패턴에 비ASCII 문자가 있습니다 - NFD 파일시스템에서 0건이 됩니다: "
        + ", ".join(bad)
    )

    # 실물로 확인한다 - NFD 로 적어도 같은 파일을 찾아야 한다.
    nfd = unicodedata.normalize("NFD", "작업로그_")
    assert nfd != "작업로그_", "이 검사의 전제(NFC != NFD)가 깨졌다"
    assert _nfc(nfd) == "작업로그_"

    # 작업로그가 예외 대상에서 실제로 빠졌는가.
    live = {_nfc(str(p.relative_to(_ROOT))) for p in _live_files()}
    assert not any("작업로그_" in name for name in live), (
        "작업로그가 검사 대상에 들어왔다 - 정규화가 안 먹었다"
    )


def test_the_backup_ref_is_documented_as_permanent_in_three_places():
    """백업 ref 가 **영구 보존**임을 세 문서가 말한다.

    ⚠⚠ 이 ref 를 지우면 `docs/작업로그_*.md` 의 옛 해시 97건이 죽은 링크가
      되고, 대응표의 옛 해시 열이 조회 불가가 된다. 44KB 짜리 ref 하나가
      6개월 뒤 "왜 09-04 로그의 해시가 main 에 없나" 에 대한 답 전부를 붙들고
      있다.

    ⚠ 원격에 실제로 있는지는 여기서 확인하지 않는다 - 네트워크에 의존하면
      검사가 환경마다 갈린다([E-1]). 확인하는 것은 **우리가 그것을 지우지 않기로
      적어 뒀는가** 다. 사람이 지우려 할 때 읽는 것이 문서이기 때문이다.
    """
    ref = "backup/pre-rewrite-2026-09-09"
    targets = {
        "CLAUDE.md": _ROOT / "CLAUDE.md",
        "대응표": _TABLE,
        "작업로그": _ROOT / "docs/작업로그_2026-09-09.md",
    }
    for label, path in targets.items():
        assert path.exists(), f"{label} 이 없다: {path}"
        text = path.read_text(encoding="utf-8")
        assert ref in text, f"{label} 에 백업 ref 이름이 없다"
        assert "영구 보존" in text or "지우지 않는다" in text, (
            f"{label} 이 보존을 말하지 않는다 - 누가 정리하다 지운다"
        )

    # 지우면 무엇을 잃는지가 적혀 있어야 한다. 이유 없는 금지는 지켜지지 않는다.
    rules = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "97건" in rules, "지우면 잃는 것(작업로그 97건)이 적혀 있지 않다"


def test_the_rewrite_rule_is_in_the_coding_rules():
    """되돌릴 수 없는 공유 변경은 총괄 확인 없이 하지 않는다 - 2026-09-09 위반.

    ⚠ 이 검사는 규칙 문장의 **존재**만 본다. 절차는 코드가 강제할 수 없다.
      그래서 최소한 문장이 사라지지 않게 잠근다.
    """
    rules = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for token in ("히스토리 rewrite", "force push", "총괄 확인 없이 하지 않는다"):
        assert token in rules, f"§6 에 '{token}' 이 없다"
    # 왜인지가 함께 있어야 한다.
    assert "해시가" in rules and "검증 좌표" in rules


def test_the_new_pc_checklist_tells_existing_clones_how_to_recover():
    """rewrite 이후 기존 클론은 pull 이 아니라 reset --hard 다."""
    text = (_ROOT / "docs/새_PC_이전_체크리스트.md").read_text(encoding="utf-8")
    assert "git fetch --all" in text
    assert "git reset --hard origin/main" in text
    # ⚠ reset --hard 는 변경을 버린다 - 그 경고가 함께 있어야 한다.
    assert "git status --short" in text, "확인 절차 없이 reset 을 권하고 있다"
    # pull 을 먼저 하면 안 되는 이유도 적혀 있어야 한다.
    assert "divergent" in text or "머지 커밋" in text
