"""리콜 로컬 동기화.

왜 필요한가 (핸드오프 §8 인프라 리스크):
  투표 기간 18일 동안 낯선 사람들이 링크를 눌러댄다. 스캔마다 정부 API 를
  직접 때리면 트래픽이 그대로 국표원으로 간다. 로컬 사본이 있으면 공개
  트래픽이 정부 API 를 건드리지 않고, API 가 죽어도 워치리스트 스윕이 돈다.

수집 전략 (2026-09-01 실측으로 확정):
  초기 적재  conditionKey=all & conditionValue=%   2회
             국내 4,243건 5.42MB 2.0초 / 국외 33,070건 32.84MB 5.7초
  일일 동기화 conditionKey=publishDate & YYYYMM     당월 + 전월 = 4회
             국내 3KB / 국외 398KB, 0.2초. 전량의 1% 다.

  ⚠ all=% 는 설계서에 명시된 사용법이 아니라 초기 적재 1회에만 쓴다.
    일일 동기화는 설계서에 있는 conditionKey=publishDate 안에 머문다.
    다만 접두 매칭(202609 -> 그 달 전체) 자체는 설계서 밖 동작이다 (§7).

  당월만 받으면 월초에 전월 마지막 공표를 놓친다. 그래서 전월도 함께 받는다.

신규 판정은 publishDate 가 아니라 uid 로 한다. 국내 응답은 정렬 보장이 없고,
대량 공표(50건+) 사이에 1건짜리 소량 공표가 매달 여러 번 끼어든다. 날짜로
비교하면 놓치고, 놓친 알림은 이 서비스가 하는 유일한 약속을 깨뜨린다 (R6).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone

from .kats_client import KatsApiError, KatsClient
from .storage import SqliteWatchStore

_log = logging.getLogger(__name__)

SCOPES = ("domestic", "overseas")
SYNC_INTERVAL_SECONDS = 24 * 60 * 60  # 리콜은 공표되는 것이지 실시간으로 안 바뀐다


@dataclass
class SyncReport:
    mode: str                       # "initial" | "incremental"
    started_at: str
    finished_at: str | None = None
    fetched: dict[str, int] = field(default_factory=dict)
    new: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def month_windows(today: date | None = None) -> list[str]:
    """당월 + 전월. 월초에 전월 마지막 공표를 놓치지 않기 위해서다."""
    d = today or date.today()
    cur = f"{d.year:04d}{d.month:02d}"
    py, pm = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    return [cur, f"{py:04d}{pm:02d}"]


def _persist(store: SqliteWatchStore, records, *, scope: str, fetched_at: str) -> int:
    rows = []
    for r in records:
        if not r.uid:
            # uid 가 없으면 신규 판정을 할 수 없다. 저장하면 매번 새 것으로 보인다.
            continue
        rows.append({
            "uid": r.uid,
            "published_on": r.announced_on,
            "payload": json.dumps(asdict(r), ensure_ascii=False),
        })
    return store.upsert_recalls(rows, scope=scope, fetched_at=fetched_at)


def run_sync(
    kats: KatsClient,
    store: SqliteWatchStore,
    *,
    force_initial: bool = False,
    today: date | None = None,
) -> SyncReport:
    """한 번 동기화한다. 예외를 밖으로 던지지 않는다.

    동기화 실패가 앱을 죽이면 안 된다. 정부 API 가 죽어도 스캔은 계속돼야 한다.
    실패는 리포트와 sync_state 에 남기고, 호출부가 /healthz 로 노출한다.
    """
    done_before = store.get_sync_state("initial_load_at")
    mode = "initial" if (force_initial or not done_before) else "incremental"
    report = SyncReport(mode=mode, started_at=_now())
    fetched_at = report.started_at

    for scope in SCOPES:
        overseas = scope == "overseas"
        records = []
        try:
            if mode == "initial":
                records = kats.recalls_all(overseas=overseas)
            else:
                for window in month_windows(today):
                    records.extend(kats.recalls_published_on(window, overseas=overseas))
        except KatsApiError as exc:
            # kats_client 가 이미 health 에 기록했다. 여기서는 이 스코프만 건너뛴다.
            report.errors.append(f"{scope}: {exc}")
            _log.warning("리콜 동기화 실패 (%s): %s", scope, exc)
            continue
        except Exception as exc:  # noqa: BLE001 — 어떤 예외도 앱을 죽이면 안 된다
            report.errors.append(f"{scope}: {type(exc).__name__}: {exc}")
            _log.exception("리콜 동기화 중 예상치 못한 오류 (%s)", scope)
            continue

        report.fetched[scope] = len(records)
        try:
            report.new[scope] = _persist(store, records, scope=scope, fetched_at=fetched_at)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{scope} 저장: {type(exc).__name__}: {exc}")
            _log.exception("리콜 저장 실패 (%s)", scope)

    report.finished_at = _now()

    # 초기 적재는 두 스코프가 모두 성공했을 때만 완료로 친다. 반쪽 적재를
    # 완료로 기록하면 다음 실행이 증분으로 넘어가 빈 구간이 영구히 남는다.
    if mode == "initial" and report.ok and len(report.fetched) == len(SCOPES):
        store.set_sync_state("initial_load_at", report.finished_at)

    store.set_sync_state("last_sync_at", report.finished_at)
    store.set_sync_state("last_sync_error", "; ".join(report.errors) if report.errors else "")

    _log.info(
        "리콜 동기화 %s: 수집 %s / 신규 %s / 오류 %d",
        mode, report.fetched, report.new, len(report.errors),
    )
    return report


async def sync_loop(
    kats: KatsClient,
    store: SqliteWatchStore,
    *,
    interval: int = SYNC_INTERVAL_SECONDS,
) -> None:
    """앱 수명 동안 도는 백그라운드 루프.

    시작 시 1회 실행한다. 재배포하면 몇 시간 공백이 생기는데, 뜨자마자 한 번
    돌면 그 공백이 사라진다. 증분은 400KB 라 부담이 없다.

    cron 머신을 따로 두지 않는 이유: 머신 하나에 볼륨 하나인데 cron 머신을
    붙이면 볼륨 공유 설정이 늘고, 그게 투표 기간에 깨질 지점을 하나 더 만든다.
    """
    while True:
        try:
            await asyncio.to_thread(run_sync, kats, store)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 루프가 죽으면 동기화가 조용히 멈춘다
            _log.exception("동기화 루프에서 예상치 못한 오류. 다음 주기에 재시도한다")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
