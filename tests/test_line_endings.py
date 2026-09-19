"""저장소에 들어가는 텍스트는 **언제나 LF** 다.

왜 이 검사가 생겼나 (2026-09-20)
--------------------------------
윈도우에서 파이썬 텍스트 모드(`write_text`)로 파일을 다시 썼더니 여섯 파일이
`\\n` → `\\r\\n` 으로 번역돼 나갔다. 검사는 하나도 안 깨졌는데 **diff 가
죽었다** - `kats_client.py` 의 변경이 메서드 하나인데 diff 가 파일
전체(2,119줄)가 됐고, `git blame` 이 1,000줄을 그 커밋으로 가리켰다.

이 저장소가 "왜 그렇게 정했나" 를 되짚는 방법이 blame 이다. 그것을 잃는 것이
이 결함의 값이다.

⚠⚠ **작업본이 아니라 인덱스를 본다.** 이 개발 PC 의 작업본에는 CRLF 파일이
  187개 있다 - `core.autocrlf` 가 true 이던 시절 체크아웃의 흔적이고, 저장소
  블롭은 그때도 LF 였다. 작업본을 검사하면 **이 기계에서만 실패하는 검사**가
  된다 (CLAUDE.md §6 - `test_commit_refs` 가 NFC/NFD 로 정확히 그렇게 됐다).

⚠ `git ls-files --eol` 의 `i/` 칸이 인덱스(=커밋되는 내용)의 줄끝이다.
  git 이 직접 말해 주는 값이라 기계를 안 탄다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _ls_files_eol() -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "ls-files", "--eol"],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        pytest.skip("git 저장소가 아니다")
    rows = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        fields, _, path = line.partition("\t")
        index_eol = fields.split()[0]          # 'i/lf' · 'i/crlf' · 'i/mixed' · 'i/-text'
        rows.append((index_eol, path))
    return rows


def test_no_tracked_text_file_has_crlf_in_the_index():
    bad = [p for eol, p in _ls_files_eol() if eol in ("i/crlf", "i/mixed")]
    assert not bad, (
        "커밋되는 내용에 CRLF 가 있습니다. diff 가 파일 전체가 되어 blame 이 죽습니다:\n  "
        + "\n  ".join(bad[:20])
        + "\n\n고치는 법: 파일을 쓸 때 open(..., newline=\"\") · 이미 들어갔으면 "
          "git add --renormalize <파일>"
    )


def test_the_repository_declares_the_rule():
    """⚠ 스크립트마다 `newline=\"\"` 를 챙기는 것으로는 못 막는다.

    기계가 바뀌면 또 난다 - 어제는 macOS, 오늘은 Windows 다. 저장소가 막는다.
    """
    attrs = (_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attrs, ".gitattributes 가 줄끝 규칙을 선언하지 않는다"


def test_scripts_that_write_data_files_ask_for_lf():
    """자료 파일을 만드는 스크립트는 `newline=\"\"` 로 연다.

    `.gitattributes` 가 뒤를 받치지만, 스크립트가 CRLF 를 뱉으면 **작업본과
    인덱스가 매번 달라져** 사람이 diff 를 볼 때 흔들린다. 두 겹으로 막는다.
    """
    for name in ("build_cert_seed.py", "record_samples.py", "build_misses.py"):
        path = _ROOT / "scripts" / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        assert "write_text(" not in src, (
            f"{name} 이 write_text 를 쓴다 - 윈도우에서 \\n 이 \\r\\n 으로 번역된다. "
            'open(..., newline="") 을 쓸 것'
        )
