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

# 전량 적재가 성공했다면 이보다는 훨씬 많다 (2026-09-01 실측 37,313건).
# 이 아래로 떨어졌는데 적재 완료로 기록돼 있으면 상태가 어긋난 것이다.
MIN_PLAUSIBLE_RECALLS = 1000


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


def _rows(records) -> list[dict]:
    out = []
    for r in records:
        if not r.uid:
            # uid 가 없으면 신규 판정을 할 수 없다. 저장하면 매번 새 것으로 보인다.
            continue
        out.append({
            "uid": r.uid,
            "published_on": r.announced_on,
            "payload": json.dumps(asdict(r), ensure_ascii=False),
        })
    return out


def _persist(store: SqliteWatchStore, records, *, scope: str, fetched_at: str) -> int:
    return store.upsert_recalls(_rows(records), scope=scope, fetched_at=fetched_at)


def run_sync(
    kats: KatsClient,
    store: SqliteWatchStore,
    *,
    force_initial: bool = False,
    today: date | None = None,
    on_updated=None,
    min_plausible: int = MIN_PLAUSIBLE_RECALLS,
) -> SyncReport:
    """한 번 동기화한다. 예외를 밖으로 던지지 않는다.

    동기화 실패가 앱을 죽이면 안 된다. 정부 API 가 죽어도 스캔은 계속돼야 한다.
    실패는 리포트와 sync_state 에 남기고, 호출부가 /healthz 로 노출한다.
    """
    # 적재 완료 표시와 실제 데이터가 어긋나면 초기 적재를 다시 한다.
    #
    # 실제로 겪었다 - initial_load_at 은 찍혀 있는데 recalls 테이블에 255건(당월+
    # 전월 증분분)만 있었다. 그 상태에서는 다음 실행도 증분이라 영원히 복구되지
    # 않고, 그동안 스캔은 조용히 "리콜 이력 없음" 을 돌려준다. 놓친 리콜은 이
    # 서비스가 하는 유일한 약속을 깨뜨린다 (CLAUDE.md R6).
    #
    # 임계값은 넉넉하게 잡는다. 정확한 전량 건수를 박아두면 정부 쪽 건수가
    # 줄었을 때 매번 전량을 다시 받는다.
    done_before = store.get_sync_state("initial_load_at")
    stored = store.recall_count()
    looks_incomplete = bool(done_before) and stored < min_plausible
    if looks_incomplete:
        _log.warning(
            "초기 적재 완료로 기록돼 있으나 리콜이 %d건뿐입니다(기대 %d건 이상). "
            "전량을 다시 받습니다.", stored, min_plausible,
        )
    mode = "initial" if (force_initial or not done_before or looks_incomplete) else "incremental"
    report = SyncReport(mode=mode, started_at=_now())
    fetched_at = report.started_at

    # 초기 적재는 두 스코프를 다 모은 뒤 한 트랜잭션으로 쓴다. 스코프마다
    # 따로 커밋하고 마지막에 완료를 찍으면, 중간에 죽었을 때 "표시는 있는데
    # 데이터는 반쪽" 인 상태가 남는다. 그 상태는 다음 실행이 증분으로 넘어가
    # 영원히 복구되지 않는다.
    batches: dict[str, list[dict]] = {}

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
        if mode == "initial":
            batches[scope] = _rows(records)
            continue
        try:
            report.new[scope] = _persist(store, records, scope=scope, fetched_at=fetched_at)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"{scope} 저장: {type(exc).__name__}: {exc}")
            _log.exception("리콜 저장 실패 (%s)", scope)

    report.finished_at = _now()

    if mode == "initial":
        # 두 스코프가 모두 성공했을 때만 쓴다. 반쪽 적재를 완료로 기록하면
        # 다음 실행이 증분으로 넘어가 빈 구간이 영구히 남는다.
        if report.ok and len(batches) == len(SCOPES):
            try:
                report.new = store.commit_full_load(
                    batches,
                    fetched_at=fetched_at,
                    completed_at=report.finished_at,
                    minimum=min_plausible,
                )
            except ValueError as exc:
                # 빈 응답이 성공으로 읽힌 경우. 적재도 표시도 롤백된다.
                report.errors.append(str(exc))
                _log.error("전량 적재를 완료로 기록하지 않았습니다: %s", exc)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"전량 저장: {type(exc).__name__}: {exc}")
                _log.exception("전량 적재 저장 실패")
        else:
            _log.warning(
                "전량 적재가 반쪽입니다(성공 스코프 %s). 완료로 기록하지 않습니다.",
                sorted(batches),
            )

    store.set_sync_state("last_sync_at", report.finished_at)
    store.set_sync_state("last_sync_error", "; ".join(report.errors) if report.errors else "")

    # 메모리 인덱스가 갱신된 사본을 다시 읽게 한다. 안 부르면 스캔이 재시작
    # 전까지 옛 사본으로 대조하고, 새로 공표된 리콜을 놓친다.
    #
    # ⚠ 조건은 "무언가 썼는가" 다. 이전에는 `any(report.new.values())` 였는데
    #   report.new 는 '처음 본 uid 수' 라서, 이미 알던 레코드를 갱신만 한
    #   경우에 0 이 된다. 그러면 디스크는 새 값인데 서빙 인덱스가 옛 값을
    #   계속 들고 있다.
    #
    #   실제로 겪었다. 제조사 필드를 recallCmpnyName 으로 바꾸고 프로덕션에
    #   force_initial 재적재를 돌렸는데, 전량(4,243+33,070)을 다시 받아 payload
    #   를 덮어썼음에도 new=0 이라 invalidate 가 안 불렸다. 그래서 '이케아' 조회가
    #   옛 makerName 기준 28건을 계속 돌려줬다 (새 값은 37건).
    #
    #   같은 함정이 평시에도 있다. 정부가 기존 공표의 내용을 정정하면 uid 는
    #   그대로이므로 new=0 이고, 정정된 내용이 재시작 전까지 반영되지 않는다.
    wrote_something = bool(report.fetched) and any(report.fetched.values())
    if on_updated is not None and wrote_something:
        try:
            on_updated()
        except Exception:  # noqa: BLE001 — 콜백 실패가 동기화를 실패로 만들면 안 된다
            _log.exception("동기화 후 콜백 실패")

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
    on_updated=None,
) -> None:
    """앱 수명 동안 도는 백그라운드 루프.

    시작 시 1회 실행한다. 재배포하면 몇 시간 공백이 생기는데, 뜨자마자 한 번
    돌면 그 공백이 사라진다. 증분은 400KB 라 부담이 없다.

    cron 머신을 따로 두지 않는 이유: 머신 하나에 볼륨 하나인데 cron 머신을
    붙이면 볼륨 공유 설정이 늘고, 그게 투표 기간에 깨질 지점을 하나 더 만든다.
    """
    while True:
        try:
            await asyncio.to_thread(run_sync, kats, store, on_updated=on_updated)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 루프가 죽으면 동기화가 조용히 멈춘다
            _log.exception("동기화 루프에서 예상치 못한 오류. 다음 주기에 재시도한다")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
