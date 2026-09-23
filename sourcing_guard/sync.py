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
import time
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

#: 실패한 스코프를 다시 부르는 간격(초)과 횟수. **간격이 넓고 횟수가 적다.**
#:
#: ⚠⚠ 이 수는 **장애가 얼마나 오래 가나**에서 왔지 감으로 정한 것이 아니다.
#:   2026-09-21~22 관측:
#:
#:       09-22 00:53  domestic 502 · overseas 성공
#:       09-22 01:16  둘 다 502
#:       09-22 07:28  domestic 502 · overseas 성공
#:       09-22 09:24  **둘 다 성공**        ← 07:28 실패로부터 1시간 56분
#:
#:   분 단위 재시도로는 안 잡힌다. 그리고 원인이 **origin 쪽**이라(우리 릴레이가
#:   아니다 - PC 직결도 같은 시간대에 죽었다) 짧은 간격으로 두들겨도 안 듣는다.
#:   60분 × 3회면 3시간 창이고, 관측된 1시간 56분을 덮는다.
#:
#: ⚠ 잰 범위: 한 번의 「실패→성공」 간격뿐이다(1시간 56분). 표본 하나로 정한
#:   수이므로, 더 긴 장애를 보면 다시 정한다.
#:
#: ⚠ 호출 비용: 실패한 스코프의 윈도 2개 × 최대 3회 = **하루 최대 +6회.**
#:   평시가 4회이므로 최악 10회다. 국표원 공개 상한을 우리는 모르지만(R5)
#:   어느 해석으로도 과하지 않다.
#:
#: ⚠⚠ **사용자 조회 경로에는 재시도를 넣지 않는다.** 거기서는 빨리 실패해
#:   UNKNOWN 으로 내려가는 것이 옳고(R3), 기다리는 사람이 있다.
#:   여기는 배경이라 **기다리는 사람이 없다** - 대가가 완전히 다르다
#:   (`kats_client.py:150` 의 무재시도 규칙은 그쪽 것이다).
RETRY_GAP_SECONDS = 60 * 60
RETRY_MAX = 3


def _scope_err(scope: str, msg: str) -> str:
    """스코프 오류 한 줄. **접두 규칙을 한 곳에 둔다.**

    재시도가 성공하면 그 스코프의 옛 오류를 걷어내야 `report.ok` 가 참이 된다.
    걷어내는 쪽과 만드는 쪽이 접두를 따로 적으면 갈린다 (§6).
    """
    return f"{scope}: {msg}"


def _drop_scope_errors(report: "SyncReport", scope: str) -> None:
    """그 스코프가 **결국 성공했으므로** 앞선 오류를 지운다."""
    head = f"{scope}:"
    report.errors = [e for e in report.errors if not e.startswith(head)]


@dataclass
class SyncReport:
    mode: str                       # "initial" | "incremental"
    started_at: str
    finished_at: str | None = None
    fetched: dict[str, int] = field(default_factory=dict)
    new: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    #: 스코프별 재시도 횟수. 0 이면 한 번에 됐다. `/healthz` 가 낸다 -
    #: 재시도가 **실제로 듣는지**를 이 수로만 알 수 있다.
    retried: dict[str, int] = field(default_factory=dict)

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


def sync_noncompliant(
    rra, store: SqliteWatchStore, *, on_updated=None, min_plausible: int = 100
) -> dict:
    """부적합 방송통신기자재 현황을 전량 교체한다. 예외를 밖으로 던지지 않는다.

    리콜과 분리한 이유: 소스가 다르고(전파법 vs 전안법), 실패해도 서로에게
    영향을 주면 안 된다. 275페이지 순차 수집이라 리콜(2회 호출)보다 오래 걸린다.

    빈 목록으로는 덮어쓰지 않는다 - 수집이 실패했는데 테이블을 비우면 RED 소스가
    조용히 사라진다 (반쪽 적재를 완료로 기록하던 것과 같은 함정).
    """
    report = {"ok": True, "count": 0, "error": None, "finished_at": _now()}
    try:
        rows = rra.fetch_noncompliant()
    except Exception as exc:  # noqa: BLE001
        report.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        _log.warning("부적합 현황 수집 실패: %s", exc)
        return report

    if len(rows) < min_plausible:
        report.update(ok=False, error=f"수집 {len(rows)}건 — 최소치 미만이라 반영하지 않음")
        _log.error("부적합 현황이 %d건뿐이라 덮어쓰지 않습니다", len(rows))
        return report

    try:
        report["count"] = store.replace_rf_noncompliant(rows, fetched_at=_now())
        store.set_sync_state("rf_noncompliant_synced_at", report["finished_at"])
        if on_updated is not None:
            on_updated()
    except Exception as exc:  # noqa: BLE001
        report.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        _log.exception("부적합 현황 저장 실패")
    return report


def run_sync(
    kats: KatsClient,
    store: SqliteWatchStore,
    *,
    force_initial: bool = False,
    today: date | None = None,
    on_updated=None,
    min_plausible: int = MIN_PLAUSIBLE_RECALLS,
    retry_gap: float = 0.0,
    retry_max: int = 0,
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

    def _one_scope(scope: str) -> bool:
        """한 스코프를 받아 저장한다. 성공하면 True.

        ⚠ 재시도가 **이 함수를 다시 부른다.** 수집 로직을 두 벌로 적으면
          한쪽만 고쳐져 갈린다 (§6).
        """
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
            report.errors.append(_scope_err(scope, str(exc)))
            _log.warning("리콜 동기화 실패 (%s): %s", scope, exc)
            return False
        except Exception as exc:  # noqa: BLE001 — 어떤 예외도 앱을 죽이면 안 된다
            report.errors.append(_scope_err(scope, f"{type(exc).__name__}: {exc}"))
            _log.exception("리콜 동기화 중 예상치 못한 오류 (%s)", scope)
            return False

        report.fetched[scope] = len(records)
        if mode == "initial":
            batches[scope] = _rows(records)
            return True
        try:
            report.new[scope] = _persist(store, records, scope=scope, fetched_at=fetched_at)
        except Exception as exc:  # noqa: BLE001
            report.errors.append(_scope_err(scope, f"저장: {type(exc).__name__}: {exc}"))
            _log.exception("리콜 저장 실패 (%s)", scope)
            return False
        return True

    for scope in SCOPES:
        _one_scope(scope)

    # ── 실패한 스코프만 다시 부른다 ──────────────────────────────────────
    #
    # ⚠⚠ **증분 모드에서만** 한다. 초기 적재는 전량이라 무겁고, "두 스코프가
    #   모두 성공했을 때만 완료로 기록" 하는 규칙이 있어 반쪽 재시도가 그 규칙을
    #   흔든다.
    #
    # ⚠ 성공하면 그 스코프의 **옛 오류를 걷어낸다.** 안 걷으면 `report.ok` 가
    #   거짓으로 남아 `last_sync_ok_at` 이 안 찍힌다 - 실제로는 다 받았는데
    #   화면이 "갱신 안 됨" 이라고 말하게 된다.
    #
    # ⚠ 기다리는 사람이 없다. 60분을 자도 아무도 안 막힌다.
    if mode == "incremental" and retry_max > 0:
        for attempt in range(1, retry_max + 1):
            failed = [s for s in SCOPES if s not in report.fetched]
            if not failed:
                break
            _log.warning("리콜 동기화 재시도 %d/%d (%s) - %d초 뒤",
                         attempt, retry_max, ",".join(failed), retry_gap)
            if retry_gap > 0:
                time.sleep(retry_gap)
            for scope in failed:
                report.retried[scope] = report.retried.get(scope, 0) + 1
                if _one_scope(scope):
                    _drop_scope_errors(report, scope)
                    _log.info("리콜 동기화 재시도 성공 (%s · %d회째)",
                              scope, report.retried[scope])

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

    # ⚠⚠ **전부 받아 온 때만** 쓰는 시각. `last_sync_at`(시도 시각)과 다르다.
    #
    #   2026-09-15~18 에 safetykorea.kr 호출이 사흘 실패하는 동안 화면이
    #   "2026-09-17 14:21 갱신" 이라고 말했다 - **아무것도 못 받아 온 시도의
    #   시각**이다. 셀러를 안심시키려고 넣은 문장이 정반대로 작동했다.
    #
    # ⚠⚠ **조건이 `wrote_something` 이 아니라 `report.ok` 다** (2026-09-22).
    #
    #   전에는 `on_updated` 와 같은 조건을 썼고, 주석이 그 이유로 §6 "같은 판단을
    #   두 곳에 적지 마라" 를 들었다. **거꾸로 당겨 쓴 것이다.** §6 이 금지하는
    #   것은 같은 판단을 두 곳에 적는 것이지, **다른 두 질문을 한 조건으로
    #   합치라**가 아니다. 둘은 다른 질문이다:
    #
    #       on_updated       메모리 인덱스를 다시 읽어야 하나  = **쓴 게 있나**
    #       last_sync_ok_at  화면이 최신이라고 말해도 되나      = **전부 성공했나**
    #
    #   합쳐 뒀더니 `any()` 가 **양쪽으로** 틀렸다. 실제 `run_sync` 를 돌려 잰
    #   진리표다 (2026-09-22):
    #
    #       A 둘 다 성공·신규 있음  fetched {'domestic':1,'overseas':1}  ok True   찍힘  ✅
    #       B domestic 만 실패      fetched {'overseas':1}              ok False  찍힘  ❌
    #       C 둘 다 성공·둘 다 0건  fetched {'domestic':0,'overseas':0} ok True   안찍힘 ❌
    #       D 둘 다 실패            fetched {}                          ok False  안찍힘 ✅
    #
    #   B 가 2026-09-21·22 에 실제로 났다 - domestic 이 502 인데 화면은 "갱신됨"
    #   이라고 말했다. 셀러 상품은 **국내** 리콜에 걸리므로 틀리는 방향이 나쁜
    #   쪽이다 (R6). 2026-09-15~18 버그와 같은 병이고, 그때 막은 것은 "전부
    #   실패" 뿐이라 "일부 실패" 가 남아 있었다.
    #
    #   ⚠ C 는 지금 0줄이다. 증분이 `month_windows` 로 **당월+전월 두 달치를
    #     전부** 받으므로(신규만이 아니다) 스코프 합계가 0 이 되려면 두 달 내내
    #     공표가 0 이어야 한다. 국내 4,249건·해외 33,181건 규모에서는 안 난다.
    #     "확률이 낮다" 가 아니라 **왜 안 나는지**가 근거다 - 윈도 수가 줄거나
    #     신규만 받는 방식으로 바뀌면 그때 C 가 살아난다.
    #
    #   ⚠ `on_updated` 는 `wrote_something` 그대로다. B 에서 overseas 를 실제로
    #     썼으므로 인덱스는 다시 읽어야 **맞다.**
    #
    #   ⚠ `last_sync_at` 은 **그대로 둔다.** `/healthz` 가 "언제 시도했고 무엇이
    #     틀렸나" 를 말하는 값이라 없애면 관측이 약해진다.
    if report.ok:
        store.set_sync_state("last_sync_ok_at", report.finished_at)

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


#: 부팅 뒤 **첫** 동기화까지 기다리는 초. 주기(`SYNC_INTERVAL_SECONDS`)와 다르다.
#:
#: 주의(중요): 배포 직후 곧바로 정부 API 를 때리면 502 가 잦다 - 실측으로
#:   9/20·9/21 두 번 다 그랬고, 다음 주기에는 성공했다. 그 사이 `/healthz` 의
#:   `last_sync_error` 가 채워져 **우리가 고장난 것처럼 보인다.**
FIRST_SYNC_DELAY_SECONDS = 60


async def sync_loop(
    kats: KatsClient,
    store: SqliteWatchStore,
    *,
    interval: int = SYNC_INTERVAL_SECONDS,
    on_updated=None,
    rra=None,
    on_noncompliant_updated=None,
    first_delay: int = FIRST_SYNC_DELAY_SECONDS,
    retry_gap: float = RETRY_GAP_SECONDS,
    retry_max: int = RETRY_MAX,
) -> None:
    """앱 수명 동안 도는 백그라운드 루프.

    시작 시 1회 실행한다. 재배포하면 몇 시간 공백이 생기는데, 뜨자마자 한 번
    돌면 그 공백이 사라진다. 증분은 400KB 라 부담이 없다.

    cron 머신을 따로 두지 않는 이유: 머신 하나에 볼륨 하나인데 cron 머신을
    붙이면 볼륨 공유 설정이 늘고, 그게 투표 기간에 깨질 지점을 하나 더 만든다.

    부적합 방송통신기자재 현황도 여기서 함께 받는다. rra 를 주지 않으면 건너뛴다.

    ⚠ 리콜 다음에 돌린다. 275페이지 순차 수집이라 실측 약 5분(페이지당 1.1초)
      걸리는데, 리콜 대조가 그동안 막히면 안 된다. sync_noncompliant 는 예외를
      밖으로 던지지 않으므로 실패해도 루프가 죽지 않는다.
    """
    # ⚠⚠ **첫 시도를 조금 늦춘다** (2026-09-21). 배포 직후 바로 돌면
    #   `safetykorea.kr` 이 502 를 주는 일이 잦고, 그러면 `last_sync_error` 가
    #   채워진 채로 `/healthz` 가 뜬다 - 다음 주기에 성공하면 비워지지만 그
    #   사이 우리가 고장난 것처럼 보인다. 실측: 9/20·9/21 배포 직후 두 번.
    #
    # ⚠ "시작 시 1회" 자체는 유지한다 - 재배포로 생긴 공백을 메우는 것이
    #   그 목적이고, 1분 늦는다고 그 목적이 깨지지 않는다.
    # ⚠ 검사는 `first_delay=0` 으로 부른다. 기본값을 0 으로 두면 이 지연이
    #   있으나 마나가 된다.
    if first_delay > 0:
        try:
            await asyncio.sleep(first_delay)
        except asyncio.CancelledError:
            raise

    # ⚠⚠ **부팅 동기화와 평시 동기화를 갈라 센다** (2026-09-22).
    #
    #   주기가 24시간인데 우리는 하루에 여러 번 배포한다. 배포마다 프로세스가
    #   새로 떠서 부팅 동기화 한 번을 돌고, 24시간이 오기 전에 또 배포된다.
    #   그래서 **평시 경로가 한 번도 실행된 적이 없을 수 있고, 우리는 그것을
    #   알 방법이 없었다** - 502 관측 넷이 전부 배포 직후였던 것이 우연이
    #   아니라 구조였다.
    #
    #   주기를 줄이면 「리콜은 공표되는 것이지 실시간이 아니다」라는 근거가
    #   깨지고, 배포를 멈추면 개발이 멈춘다. 그래서 **동작을 안 바꾸고 관측만**
    #   더한다 - `/healthz` 가 `boot`/`periodic` 을 따로 센다.
    #
    #   ⚠ 이 수는 **프로세스 메모리가 아니라 DB** 에 쌓는다. 재배포하면 0 이
    #     되는 값으로는 "평시가 한 번이라도 돌았나" 에 영영 답할 수 없다.
    kind = "boot"
    while True:
        try:
            store.set_sync_state(f"sync_count_{kind}",
                                 str(int(store.get_sync_state(f"sync_count_{kind}") or 0) + 1))
            store.set_sync_state("last_sync_kind", kind)
        except Exception:  # noqa: BLE001 — 세는 일이 동기화를 막으면 안 된다
            _log.exception("동기화 회차를 세지 못했다")
        try:
            await asyncio.to_thread(run_sync, kats, store, on_updated=on_updated,
                                    retry_gap=retry_gap, retry_max=retry_max)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 루프가 죽으면 동기화가 조용히 멈춘다
            _log.exception("동기화 루프에서 예상치 못한 오류. 다음 주기에 재시도한다")

        if rra is not None:
            try:
                report = await asyncio.to_thread(
                    sync_noncompliant, rra, store, on_updated=on_noncompliant_updated
                )
                _log.info("부적합 현황 동기화: %s", report)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _log.exception("부적합 현황 동기화에서 예상치 못한 오류")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        kind = "periodic"
