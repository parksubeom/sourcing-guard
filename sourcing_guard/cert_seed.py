"""인증 조회 캐시 시드 — 재배포로 잃은 캐시를 파일에서 되살린다.

왜 있나
-------
`CertCache` 는 프로세스 메모리다. **재배포하면 0 이 된다.** 국표원 조회가
죽어 있는 동안 배포하면 데모 셋이 전부 "조회 실패" 로 뜬다
(`Claude outputs/sg-final-day.md` §0-2). 투표 전날에 그러면 첫 화면에서
이탈한다.

⚠ **값을 지어내지 않는다** (R5). 파일에 있는 것은 `scripts/build_cert_seed.py`
  가 국표원에 **실제로 조회해서 받은 레코드**와 **그 조회 시각**이다. 이
  모듈은 그것을 캐시에 얹기만 한다.

⚠ 얹을 때 `CertCache.seed()` 를 쓴다 — `put()` 이 아니다. 이유는 그 메서드의
  주석에 있다. 요약하면 **시드는 fresh 가 아니다.** 살아 있는 API 가 있으면
  밀려나고, 없으면 "조회분으로 표시합니다" 를 달고 나간다.

깨진 시드는 어떻게 하나 — **건너뛴다. 던지지 않는다**
------------------------------------------------
두 가지를 다 피해야 한다.

    시작 시 예외      앱이 안 뜬다. 데이터 한 줄 때문에 서비스를 죽이지 않는다
    조용한 수용       미래 시각·깨진 번호를 그대로 얹으면 화면이 거짓을 말한다

그래서 **줄 단위로 거르고 센다.** 걸러진 줄은 시드가 없는 것과 같아져 화면이
"조회 실패" 로 간다 - 그건 정직한 상태다 (R3). 몇 줄을 걸렀는지는 로그와
`stats()` 에 남는다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .kats_client import CERT_NUMBER_RE, CertRecord, CertState, normalize_kc

_log = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parent / "data" / "cert_seed.json"


@dataclass(frozen=True)
class SeedEntry:
    cert_number: str
    fetched_at: str
    record: CertRecord | None


@dataclass(frozen=True)
class SeedStats:
    """무엇을 몇 개 읽었고 몇 개를 새로 얹었고 몇 개를 걸렀나.

    ⚠ `loaded` 와 `applied` 를 가른다. 같은 프로세스에서 두 번 얹으면 두 번째는
      **새로 넣은 것이 0** 이다(이미 있는 값을 안 덮으므로). 하나로 두면
      "시드가 비었다" 와 "이미 얹혀 있다" 가 같은 0 으로 보인다 - 실제로 검사
      하나가 그렇게 깨졌다.
    """

    loaded: int = 0      # 파일에서 읽어 쓸 수 있는 줄
    applied: int = 0     # 이번에 캐시에 새로 넣은 줄
    skipped: int = 0     # 걸러진 줄
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"loaded": self.loaded, "applied": self.applied,
                "skipped": self.skipped, "reasons": list(self.reasons)}


def _parse_when(raw: Any, *, now: datetime) -> str | None:
    """과거 ISO 시각인가. 미래·빈칸·해석 불가는 전부 거절한다.

    미래 시각을 받아들이면 화면이 아직 오지 않은 날짜로 "조회분" 을 말한다.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        when = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when > now:
        return None
    return raw.strip()


def _parse_record(raw: Any, key: str) -> tuple[bool, CertRecord | None]:
    """(해석했나, 레코드). 레코드가 **없는 것**(미조회)도 사실이라 None 을 허용한다."""
    if raw is None:
        return True, None
    if not isinstance(raw, dict):
        return False, None
    try:
        state = CertState(raw.get("state"))
    except ValueError:
        # 모르는 상태값을 UNKNOWN 으로 반올림하지 않는다 (R3). 그 줄은 버린다.
        return False, None
    fields = {f: raw.get(f) for f in CertRecord.__dataclass_fields__ if f != "state"}
    fields["cert_number"] = fields.get("cert_number") or key
    try:
        return True, CertRecord(state=state, **fields)
    except TypeError:
        return False, None


def load_entries(path: Path | None = None, *, now: datetime | None = None
                 ) -> tuple[list[SeedEntry], SeedStats]:
    """시드 파일을 읽어 유효한 줄만 돌려준다. 파일이 없으면 빈 목록이다."""
    target = SEED_PATH if path is None else path
    at = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], SeedStats()
    except (OSError, ValueError) as exc:
        return [], SeedStats(skipped=0, reasons=(f"파일을 읽지 못했다: {exc}",))

    rows = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return [], SeedStats(reasons=("entries 가 목록이 아니다",))

    out: list[SeedEntry] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            reasons.append("줄이 객체가 아니다")
            continue
        key = normalize_kc(str(row.get("cert_number") or ""))
        if not key or not CERT_NUMBER_RE.fullmatch(key):
            reasons.append(f"인증번호 형식이 아니다: {row.get('cert_number')!r}")
            continue
        if key in seen:
            reasons.append(f"중복: {key}")
            continue
        when = _parse_when(row.get("fetched_at"), now=at)
        if when is None:
            reasons.append(f"조회 시각이 과거 ISO 가 아니다: {key}")
            continue
        ok, record = _parse_record(row.get("record"), key)
        if not ok:
            reasons.append(f"레코드를 해석하지 못했다: {key}")
            continue
        seen.add(key)
        out.append(SeedEntry(cert_number=key, fetched_at=when, record=record))

    return out, SeedStats(loaded=len(out), skipped=len(reasons), reasons=tuple(reasons))


def apply_to(client: Any, path: Path | None = None, *,
             now: datetime | None = None) -> SeedStats:
    """시드를 클라이언트 캐시에 얹는다. 목 모드에서도 해가 없다(조회가 캐시를 안 본다).

    ⚠ 이미 캐시에 있는 번호는 **덮지 않는다.** 살아 있는 조회로 받은 값이
      파일보다 새롭다.
    """
    entries, stats = load_entries(path, now=now)
    cache = getattr(client, "_cert_cache", None)
    if cache is None:
        return SeedStats(loaded=stats.loaded, skipped=stats.skipped,
                         reasons=stats.reasons + ("캐시가 없는 클라이언트다",))
    applied = 0
    for entry in entries:
        if cache.get(entry.cert_number, allow_stale=True) is not None:
            continue
        cache.seed(entry.cert_number, entry.record, entry.fetched_at)
        applied += 1
    if stats.skipped:
        _log.warning("인증 캐시 시드 %d줄을 걸렀다: %s", stats.skipped,
                     "; ".join(stats.reasons[:5]))
    _log.info("인증 캐시 시드 %d건을 새로 얹었다 (파일 %d건)", applied, stats.loaded)
    return SeedStats(loaded=stats.loaded, applied=applied,
                     skipped=stats.skipped, reasons=stats.reasons)
