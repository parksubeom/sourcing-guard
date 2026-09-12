"""`.env.example` 을 **안내대로 복사하면** 설정이 그대로 나와야 한다.

⚠⚠ 2026-09-12 에 `.env` 를 `.env.example` 에 맞춰 채우다가 찾았다. 그 파일은
  두 키를 **빈 채로** 배포하면서 주석에 기본값을 적어 뒀다:

      EXTRACTOR_ORDER=      "비워 두는 것이 정상입니다. **기본값 gpt,claude**"
      SYNC_ENABLED=         "기본값은 MOCK_MODE 가 false 이면 켬"

  그런데 `os.getenv(name, default)` 의 기본값은 키가 **없을 때만** 쓰인다.
  `KEY=` 는 키가 **있고 값이 빈** 것이라 기본값을 건너뛰었다. 결과:

      EXTRACTOR_ORDER=   →  추출기 **0개**. 기준 추출기가 조용히 사라진다
      SYNC_ENABLED=      →  리콜 동기화 **꺼짐**. 리콜 축이 갱신되지 않는다

  둘 다 **오류 없이** 일어난다. 안내대로 한 사람이 가장 크게 당한다.

⚠ 이 검사가 보는 것은 "코드가 지금 어떻게 도나" 가 아니라 **`.env.example` 의
  약속이 지켜지나** 다. 그래서 기대값을 그 파일의 주석에서 가져왔다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from sourcing_guard.config import Settings

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _example_keys() -> list[str]:
    text = (_ROOT / ".env.example").read_text(encoding="utf-8")
    return [m.group(1) for m in re.finditer(r"^([A-Z_][A-Z0-9_]*)=", text, re.M)]


def _blank_in_example() -> list[str]:
    text = (_ROOT / ".env.example").read_text(encoding="utf-8")
    return [m.group(1) for m in re.finditer(r"^([A-Z_][A-Z0-9_]*)=\s*$", text, re.M)]


def test_an_empty_extractor_order_falls_back_to_the_documented_default(monkeypatch):
    """`EXTRACTOR_ORDER=` 는 **기본값 gpt,claude** 다. 빈 순서가 아니다."""
    monkeypatch.setenv("EXTRACTOR_ORDER", "")
    assert Settings.from_env().extractor_order == ("gpt", "claude")


@pytest.mark.parametrize("raw", ["", "   ", ",", " , ,"])
def test_a_blank_extractor_order_never_leaves_us_with_no_extractor(raw, monkeypatch):
    """공백·쉼표만 있어도 추출기가 0개가 되면 안 된다.

    추출기가 0개면 스캔이 조용히 휴리스틱으로 내려가고, 그러면 발표 숫자의
    기준 추출기가 화면과 갈린다 (CLAUDE.md R7).
    """
    monkeypatch.setenv("EXTRACTOR_ORDER", raw)
    assert Settings.from_env().extractor_order, "추출기가 하나도 없다"


def test_an_empty_sync_enabled_keeps_the_documented_default(monkeypatch):
    """`SYNC_ENABLED=` 는 "MOCK_MODE 가 false 이면 켬" 이다. 끄는 것이 아니다."""
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("SYNC_ENABLED", "")
    assert Settings.from_env().sync_enabled is True

    monkeypatch.setenv("MOCK_MODE", "true")
    assert Settings.from_env().sync_enabled is False


def test_an_explicit_false_still_turns_sync_off(monkeypatch):
    """빈 값을 기본값으로 읽더라도 **명시적인 false 는 그대로 꺼야** 한다."""
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.setenv("SYNC_ENABLED", "false")
    assert Settings.from_env().sync_enabled is False


def test_copying_the_example_verbatim_yields_a_usable_config(monkeypatch):
    """**`.env.example` 을 그대로 복사한 상태**에서 설정이 쓸 만해야 한다.

    비밀만 비운 채로 예시 파일의 값을 그대로 환경에 넣고 확인한다 - 이것이
    새 PC 에서 실제로 하는 일이다 (`docs/새_PC_이전_체크리스트.md` §2-1).
    """
    text = (_ROOT / ".env.example").read_text(encoding="utf-8")
    for key, value in re.findall(r"^([A-Z_][A-Z0-9_]*)=(.*)$", text, re.M):
        monkeypatch.setenv(key, value.strip())
    monkeypatch.setenv("MOCK_MODE", "false")      # 실연동으로 쓰는 상태

    s = Settings.from_env()
    assert s.extractor_order, "예시대로 복사했더니 추출기가 0개다"
    assert s.sync_enabled is True, "예시대로 복사했더니 리콜 동기화가 꺼졌다"
    assert s.watchlist_db_path, "워치리스트 경로가 비었다"


def test_the_env_example_still_lists_every_key_the_settings_need():
    """`.env.example` 이 설정 키를 빠뜨리면 새 PC 에서 조용히 기본값으로 돈다."""
    keys = _example_keys()
    assert len(keys) == len(set(keys)), f"중복 키: {keys}"
    for required in ("MOCK_MODE", "ANTHROPIC_API_KEY", "GPT_API_KEY",
                     "EXTRACTOR_ORDER", "KATS_SERVICE_KEY", "SYNC_ENABLED",
                     "SYNC_TOKEN", "WATCHLIST_DB_PATH", "DOMEGGOOK_API_KEY"):
        assert required in keys, f"{required} 가 .env.example 에 없다"


def test_every_blank_key_in_the_example_is_safe_to_leave_blank(monkeypatch):
    """예시가 **빈 채로 두라고 한 키**는 빈 채로도 설정이 만들어져야 한다.

    새 키를 빈 값으로 예시에 추가하면서 읽는 쪽에서 빈 값을 처리하지 않으면
    여기서 깨진다 - 2026-09-12 에 두 번 그랬다.
    """
    for key in _blank_in_example():
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("MOCK_MODE", "false")
    s = Settings.from_env()          # 예외 없이 만들어져야 한다
    assert s.extractor_order, "빈 값으로 두라는 키 때문에 추출기가 0개가 됐다"
