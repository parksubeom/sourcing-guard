"""배포된 것이 **어느 커밋인가**. 빌드 시점에 박는다.

⚠⚠ 왜 필요한가
--------------
2026-09-11 에 총괄이 `/healthz` 응답의 **필드 유무로 배포 버전을 역추적**해야
했다 - `storage` 키가 없으니 09-08 배포본이구나, 하는 식이다. 그건 추론이지
사실이 아니고, 필드가 우연히 같으면 틀린다.

같은 날 더 비싼 일이 있었다. 배포본이 09-08 자라서 **전파인증 점검 페이지를
"확인됨" 으로 보여주는 코드**가 투표 링크 뒤에 있었다(미완 4-q 결함 3).
"배포본이 무엇인가" 를 한 번에 못 말하면 그런 상태를 며칠 모르고 지나간다.

어떻게 박히나
-------------
`Dockerfile` 이 빌드 인자로 받아 환경변수로 굳힌다:

    fly deploy --build-arg GIT_SHA=$(git rev-parse --short=9 HEAD) \
               --build-arg BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

⚠ 로컬 개발에서는 값이 없다. 그때는 **git 에서 직접 읽는다** - 배포본과 로컬을
  구분할 수 있어야 하므로 `source` 필드로 어디서 온 값인지 함께 말한다.

⚠ git 도 없으면 `None` 이다. **모르는 것을 지어내지 않는다** (R5).
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _from_git() -> str | None:
    """로컬 개발용. 배포 이미지에는 .git 이 없다."""
    if not (_ROOT / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT), "rev-parse", "--short=9", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


@lru_cache(maxsize=1)
def snapshot() -> dict:
    """`/healthz` 가 읽는다. 프로세스 수명 동안 안 바뀌므로 캐시한다."""
    sha = os.getenv("GIT_SHA") or ""
    built_at = os.getenv("BUILT_AT") or ""
    source = "build-arg"
    if not sha:
        sha = _from_git() or ""
        source = "git" if sha else "unknown"
    return {
        "commit": sha or None,
        "built_at": built_at or None,
        # ⚠ 값이 어디서 왔는지 함께 말한다. build-arg 면 배포 이미지이고,
        #   git 이면 로컬에서 돌고 있는 것이다. 섞이면 또 역추적하게 된다.
        "source": source,
        "note": (
            "commit 이 null 이면 빌드 인자가 안 들어간 것입니다. "
            "배포는 --build-arg GIT_SHA=... --build-arg BUILT_AT=... 로 합니다."
        ),
    }
