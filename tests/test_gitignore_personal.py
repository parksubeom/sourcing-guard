"""시피님 개인 자료 폴더가 **`git add -A` 로 들어가지 않는지** 잠근다.

⚠⚠ 리포 루트에 `해커톤1/`·`해커톤2/`·`해커톤3/` 이 있다. CLAUDE.md·기획서·
  `extractor.py`·`hazard_rules.yaml` 의 **옛 사본**이고 우리 소스가 아니다.
  섞이면 다음 사람이 어느 것이 정본인지 못 가린다 - 이 저장소의 반복 결함
  (문서가 코드보다 앞서 나감)을 파일 단위로 재현하는 일이다.

⚠ **`git check-ignore` 를 믿지 않는다.** 이름이 NFD 라 인자로 준 문자열과
  정규화가 달라 "무시 안 됨" 이라 답한다. **`git add -A` 가 실제로 무엇을
  담는지**가 정본이다 - 그래서 이 검사는 `--dry-run` 으로 그것을 본다.
"""
from __future__ import annotations

import subprocess
import unicodedata
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=_ROOT, capture_output=True,
                          text=True, check=True).stdout


def _personal_dirs() -> list[str]:
    """루트의 개인 자료 폴더. **원시 이름**으로 돌려준다 (NFD 일 수 있다)."""
    import os

    return sorted(n for n in os.listdir(_ROOT)
                  if (_ROOT / n).is_dir()
                  and unicodedata.normalize("NFC", n).startswith("해커톤"))


def test_the_folders_are_still_there_and_untouched():
    """⚠ 내용을 건드리지 않는다. **있다는 것만** 확인한다.

    없어졌으면 시피님이 옮긴 것이고, 그러면 이 검사는 조용히 통과한다.
    """
    dirs = _personal_dirs()
    if not dirs:
        pytest.skip("개인 자료 폴더가 없다 - 옮겼거나 이 클론에 없다")
    assert all((_ROOT / d).is_dir() for d in dirs)


def test_git_add_all_does_not_stage_them():
    """⚠⚠ **이것이 정본 검사다.** `git add -A --dry-run` 이 담는 것을 본다."""
    dirs = _personal_dirs()
    if not dirs:
        pytest.skip("개인 자료 폴더가 없다")
    out = _git("add", "-A", "--dry-run", "--", ".")
    staged = [ln for ln in out.splitlines()
              if "해커톤" in unicodedata.normalize("NFC", ln)]
    assert not staged, (
        "개인 자료가 `git add -A` 에 담긴다:\n  " + "\n  ".join(staged[:8])
        + "\n.gitignore 의 `/해커톤*/` 를 확인하라 - 이름이 NFD 면 NFD 패턴도 필요하다"
    )


def test_the_ignore_rule_carries_both_normalizations():
    """NFC 와 NFD 를 **둘 다** 적는다.

    ⚠ 이 맥은 `core.precomposeunicode=true` 라 NFC 패턴만으로도 걸리지만,
      그 설정이 false 인 클론에서는 안 걸린다. 설정에 기대지 않는다.
    """
    text = (_ROOT / ".gitignore").read_text(encoding="utf-8")
    nfc = unicodedata.normalize("NFC", "해커톤")
    nfd = unicodedata.normalize("NFD", "해커톤")
    assert f"/{nfc}*/" in text, "NFC 패턴이 없다"
    assert f"/{nfd}*/" in text, "NFD 패턴이 없다 - 설정이 다른 클론에서 샌다"
    # 왜 두 형태인지가 적혀 있어야 한다 - 없으면 다음 사람이 중복으로 보고 지운다.
    assert "precomposeunicode" in text


#: 2026-09-13 현재 **이미 추적 중인** 개인 자료 파일 수 (커밋 `14225f1`).
#:
#: ⚠⚠ 총괄도 나도 "미추적" 이라 믿었는데 **틀렸다.** `git check-ignore` 가
#:   "무시 안 됨" 이라 답한 이유가 이것이다 - git 은 **이미 추적 중인 파일에
#:   `.gitignore` 를 적용하지 않는다.** 모순이 아니었다.
#:
#: ⚠ 추적에서 빼는 것은 리포에서 파일이 사라지는 변경이라 **시피님 판단**이다.
#:   여기서는 **늘어나지 않는 것**만 잠근다.
ALREADY_TRACKED = 18


def _tracked() -> list[str]:
    return [p for p in _git("ls-files", "-z").split("\0")
            if p and "해커톤" in unicodedata.normalize("NFC", p)]


def test_the_tracked_copies_do_not_grow():
    """⚠ 이미 들어간 18개는 시피님 판단 대기. **늘어나면 실패한다.**"""
    tracked = _tracked()
    assert len(tracked) <= ALREADY_TRACKED, (
        f"개인 자료가 {len(tracked)}개로 늘었다 (알려진 {ALREADY_TRACKED}개)"
    )
    if len(tracked) < ALREADY_TRACKED:
        pytest.skip(f"{ALREADY_TRACKED} → {len(tracked)} 로 줄었다 - 상수를 낮춰라")


def test_no_secret_shaped_value_sits_in_the_tracked_copies():
    """⚠⚠ 공개 리포다. 추적 중인 사본에 **키·개인정보 모양**이 없어야 한다.

    2026-09-13 실측: 18개 전부 0건. 늘어나면 잡는다.
    """
    import re

    pats = {
        "API 키": re.compile(r"(sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{30,})"),
        "서비스키": re.compile(
            r"(?i)(service_?key|aid)\s*[=:]\s*['\"]?[A-Za-z0-9%+/=_\-]{16,}"),
        "사업자번호": re.compile(r"\b\d{3}-\d{2}-\d{5}\b"),
        "전화번호": re.compile(r"\b01[016-9]-?\d{3,4}-?\d{4}\b"),
        "IP": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    }
    bad = []
    for path in _tracked():
        body = _git("show", f"HEAD:{path}")
        for label, rx in pats.items():
            if rx.search(body):
                bad.append(f"{unicodedata.normalize('NFC', path)} · {label}")
    assert not bad, "추적 중인 개인 자료에 민감 패턴:\n  " + "\n  ".join(bad)
