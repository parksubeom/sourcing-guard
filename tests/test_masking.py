"""시크릿 마스킹 — [⑦-b-1]. **호출을 하기 전에 만든다.**

식약처 API 는 키가 **URL 경로**에 들어가고 HTTPS 도 안 된다. 배포본이 매일
직접 부르면 키가 평문으로, 그것도 예외 메시지에 URL 째로 남는다.

⚠⚠ **새는 자리를 재고 만들었다. 추측이 아니다** (2026-09-14 실측):

    httpx.HTTPStatusError · ConnectError · ReadTimeout
        str·repr 에 URL 이 안 들어간다            → 새지 않는다
    HostNotAllowedError
        **str · repr · .url 셋 다 샜다**          → 유일하게 확인된 누출
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from sourcing_guard.allowed_hosts import HostNotAllowedError
from sourcing_guard.masking import (
    MASK,
    _KEY_PARAMS,
    looks_like_a_key,
    mask,
    mask_url,
    register_secret,
)

_ROOT = Path(__file__).resolve().parents[1]
KEY = "SECRET-KEY-1234567890abcdef"


@pytest.fixture(autouse=True)
def _registered():
    register_secret(KEY)


# ── 등록된 값은 어디에 있든 지운다 ───────────────────────────────
@pytest.mark.parametrize("text", [
    f"http://openapi.foodsafetykorea.go.kr/api/{KEY}/I0490/json/1/5",   # 경로
    f"https://x.kr/a?aid={KEY}&om=json",                                # 쿼리
    f"요청에 실패했습니다: {KEY}",                                       # 본문
    f'{{"key": "{KEY}"}}',                                              # JSON
])
def test_a_registered_secret_is_removed_wherever_it_sits(text):
    assert KEY not in mask(text)
    assert MASK in mask(text)


def test_a_key_in_the_path_is_removed():
    """식약처가 이 모양이다. **쿼리 이름이 없으므로 이름 규칙으로는 못 잡는다.**"""
    url = f"http://openapi.foodsafetykorea.go.kr/api/{KEY}/I0490/json/1/5"
    assert mask_url(url) == "http://openapi.foodsafetykorea.go.kr/api/***/I0490/json/1/5"


def test_an_unregistered_key_in_a_query_is_still_removed():
    """②의 그물 - 스크립트가 손으로 넣은 키까지."""
    assert "ABCDEFGH12345678" not in mask_url(
        "https://www.domeggook.com/ssl/api/?aid=ABCDEFGH12345678&om=json")


def test_the_mask_is_readable_not_percent_encoded():
    """`%2A%2A%2A` 로 나가면 로그를 훑는 사람이 "이게 키인가" 를 다시 묻는다."""
    assert "aid=***" in mask_url("https://x.kr/a?aid=ABCDEFGH12345678")


def test_a_public_parameter_is_not_hidden():
    """law.go.kr 의 `OC=test` 는 공개 값이다. 가리면 근거 URL 을 못 연다 (R2)."""
    url = "https://www.law.go.kr/DRF/lawService.do?OC=test&target=law&ID=38724"
    assert mask_url(url) == url
    assert "oc" not in _KEY_PARAMS


def test_a_short_value_is_never_registered():
    """짧은 값을 지우면 본문이 `***` 투성이가 되어 오히려 못 읽는다."""
    register_secret("mock")
    assert mask("mock 모드로 돕니다") == "mock 모드로 돕니다"


# ── 확인된 누출 자리 ─────────────────────────────────────────────
def test_the_host_error_never_carries_the_key():
    """**유일하게 확인된 누출 자리.** str · repr · .url 셋 다 본다."""
    # ⚠ **승인 목록에 없는 호스트를 쓴다.** 식약처는 2026-09-14 에 목록에
    #   들어갔으므로 더는 이 예외를 일으키지 않는다 - 같은 모양(키가 경로)의
    #   가상 호스트로 잰다.
    url = f"http://example.invalid/api/{KEY}/I0490/json/1/5"
    with pytest.raises(HostNotAllowedError) as got:
        from sourcing_guard.allowed_hosts import ensure_allowed

        ensure_allowed(url)
    exc = got.value
    for where, text in (("str", str(exc)), ("repr", repr(exc)), (".url", exc.url)):
        assert KEY not in text, where
    assert MASK in exc.url
    # 호스트는 가리지 않는다 - 무엇이 막혔는지 알아야 R4 표를 고친다.
    assert exc.host == "example.invalid"


def test_the_host_error_does_not_keep_a_raw_copy():
    """`self.url` 에 원문을 두면 부르는 쪽이 그것을 찍는다.

    ⚠ 이 검사가 없으면 "예외 메시지는 가렸는데 속성은 안 가렸다" 가 된다.
    """
    src = (_ROOT / "sourcing_guard/allowed_hosts.py").read_text(encoding="utf-8")
    body = src[src.index("class HostNotAllowedError"):]
    assert "self.url = safe" in body
    assert "self.url = url" not in body


# ── 리포에 키가 남지 않는다 ──────────────────────────────────────
@pytest.mark.parametrize("line, caught", [
    ('KATS_SERVICE_KEY = "abc123def456ghi789jkl"', True),
    ("api_key: 3f2a9c4d1e6b8a7f0c5d2e9b4a1f6c3d8e7b2a5f", True),
    ('aid="ABCDEFGH12345678IJKLMNOP"', True),
    ('kats_service_key=os.getenv("KATS_SERVICE_KEY")', False),   # 이름이지 값이 아니다
    ("gpt_api_key: str | None", False),                          # 타입 선언
    ("옛 HEAD  1ebf65f089765c37a9ed6c8d35057dd74f5e95c7", False),  # git 해시
    ("aid=***", False),                                          # 이미 가려진 것
])
def test_a_key_literal_is_found_by_its_position_not_its_shape(line, caught):
    """⚠⚠ **모양만으로는 못 가린다.**

    처음엔 `[0-9a-f]{40}` 로 잡으려 했는데 **git 해시가 전부 걸렸다**
    (CLAUDE.md · test_commit_refs 의 옛 해시). 식약처 키도 40자 16진수라
    모양이 git 해시와 같다 - 구분할 수 없다.

    그래서 모양이 아니라 **자리**를 본다: `키이름 = "긴 리터럴"`. 키가 파일에
    박히는 것은 언제나 그 모양이고 해시는 그 자리에 안 온다.
    """
    assert bool(looks_like_a_key(line)) is caught, line


def test_no_key_literal_is_committed():
    """커밋 전 확인. 키 리터럴이 추적 중인 파일에 있으면 실패한다.

    ⚠ 원자료(fixtures)는 `domeggook_pii` 가 따로 지킨다 - 여기서는 **우리가
      키를 두는 자리**(코드·설정·스크립트·문서)만 본다.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "*.py", "*.yaml", "*.yml", "*.toml", "*.cfg", "*.env",
         "*.html", "*.js", "*.md"],
        capture_output=True, text=True, cwd=_ROOT).stdout.split()
    hits: list[str] = []
    for name in tracked:
        path = _ROOT / name
        if not path.is_file() or "fixtures" in name:
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8",
                                                errors="ignore").splitlines(), 1):
            for found in looks_like_a_key(line):
                hits.append(f"{name}:{i} {found[:8]}…")
    assert hits == [], hits[:6]


def test_dotenv_is_ignored():
    """시크릿은 `.env` 에서만. 그 파일이 추적되면 안 된다."""
    tracked = subprocess.run(["git", "ls-files"], capture_output=True,
                             text=True, cwd=_ROOT).stdout.split()
    assert not [t for t in tracked if t == ".env" or t.endswith("/.env")]
    assert re.search(r"^\.env$", (_ROOT / ".gitignore").read_text(encoding="utf-8"),
                     re.M), ".gitignore 에 .env 가 없다"
