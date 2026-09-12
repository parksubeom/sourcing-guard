"""Watchlist persistence (SQLite).

기획서 §6.1: 이 서비스가 유일하게 보증하는 것은 "나중에 리콜 공표되면 가장
먼저 알린다"이다. 메모리 dict 는 재시작 한 번에 등록 상품을 전부 잃고, 그러면
셀러는 자기가 감시받고 있다고 믿는 채로 감시되지 않는다. 조용히 깨지는 약속이
가장 나쁘므로 워치리스트는 디스크에 남긴다.

저장 형식: WatchItem 을 Pydantic JSON 한 칼럼으로 보관한다. 필드를 칼럼으로
쪼개면 모델이 바뀔 때마다 스키마가 따로 놀기 시작한다. 조회에 실제로 쓰는
owner_id 와 status 만 칼럼으로 승격해 인덱스를 건다.

CLAUDE.md R6 관련: 여기는 저장만 한다. 매칭 규칙은 watchlist.py 의 순수 함수에
그대로 남는다.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import RecallAlert, WatchItem, WatchStatus

_log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_items (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    status      TEXT NOT NULL,
    payload     TEXT NOT NULL   -- WatchItem 전체 (Pydantic JSON)
);
CREATE INDEX IF NOT EXISTS idx_watch_owner  ON watch_items(owner_id);
CREATE INDEX IF NOT EXISTS idx_watch_status ON watch_items(status);

-- 리콜 로컬 사본. 투표 기간에 공개 트래픽이 정부 API 를 직접 때리지 않게 하고
-- (핸드오프 §8 인프라 리스크), API 가 죽어도 워치리스트 스윕이 계속 돌게 한다.
--
-- 신규 판정은 publishDate 가 아니라 uid 로 한다. 국내 응답은 정렬 보장이 없고
-- 소량 공표(1건짜리)가 매달 여러 번 끼어들어서, 날짜 비교로는 놓친다.
CREATE TABLE IF NOT EXISTS recalls (
    uid          TEXT NOT NULL,
    scope        TEXT NOT NULL,   -- domestic | overseas
    published_on TEXT,            -- YYYYMMDD
    payload      TEXT NOT NULL,   -- RecallRecord 전체 (JSON)
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (uid, scope)
);
CREATE INDEX IF NOT EXISTS idx_recall_published ON recalls(published_on);
CREATE INDEX IF NOT EXISTS idx_recall_scope     ON recalls(scope);

-- 부적합 방송통신기자재 현황 (전파법). 전파인증 축에서 RED 자격이 있는 유일한
-- 소스다 - 부적합사유·행정처분이 명시되어 "정부 DB 가 문제를 적어둔" 조건을
-- 만족한다 (CLAUDE.md R3-b). 리콜 사본과 같은 방식으로 로컬에 둔다.
CREATE TABLE IF NOT EXISTS rf_noncompliant (
    seq          TEXT PRIMARY KEY,  -- 목록 번호
    company      TEXT,
    cert_number  TEXT,              -- R- 번호와 자기적합확인 관리번호가 섞여 있다
    model        TEXT,
    acted_on     TEXT,              -- 처분일자
    fetched_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rf_nc_cert  ON rf_noncompliant(cert_number);
CREATE INDEX IF NOT EXISTS idx_rf_nc_model ON rf_noncompliant(model);

-- 동기화 진행 상태. 재배포 후 "초기 적재를 다시 해야 하나" 를 판단하고,
-- 캐시 기준일 표시에도 같은 값을 쓴다.
-- 스윕이 찾아낸 알림. **저장하는 이유는 약속 때문이다.**
--
-- 기획서 §6.1: 이 서비스가 유일하게 보증하는 것은 "나중에 리콜 공표되면 가장
-- 먼저 알린다" 다. 알림을 메모리에만 두면 셀러가 화면을 안 보고 있던 사이에
-- 발생한 알림이 사라진다 - 워치리스트를 디스크에 남긴 것과 같은 이유다.
--
-- ⚠ `watch_items.payload` 의 `seen_recall_fingerprints` 는 "다시 알리지
--   않는다" 를 위한 것이고, 이 표는 "무엇을 알렸나" 를 남기는 것이다. 둘은
--   다른 일을 한다 - 지문만 있으면 알림 내용을 복원할 수 없다.
CREATE TABLE IF NOT EXISTS recall_alerts (
    watch_item_id       TEXT NOT NULL,
    recall_fingerprint  TEXT NOT NULL,
    detected_at         TEXT NOT NULL,   -- YYYY-MM-DD
    payload             TEXT NOT NULL,   -- RecallAlert 전체 (Pydantic JSON)
    PRIMARY KEY (watch_item_id, recall_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_alert_detected ON recall_alerts(detected_at);

-- [D-백] 오답 신고. 셀러가 "이 품목이 아닙니다" 를 누른 것.
--
-- ⚠ 신고는 **판정을 바꾸지 않는다** (R1). 여기 쌓인 것을 사람이 검수해서
--   tests/fixtures/새표본235_오답.tsv 로 옮긴다. 이 표는 검수 대기열이다.
-- ⚠ 워치리스트와 같은 볼륨이다 - 재배포마다 사라지면 신고가 헛것이 된다.
-- ⚠ client_ip 는 저장하지 않는다. 레이트리밋에만 쓰고 버린다.
CREATE TABLE IF NOT EXISTS miss_reports (
    id           TEXT PRIMARY KEY,
    reported_at  TEXT NOT NULL,   -- UTC ISO datetime
    payload      TEXT NOT NULL    -- MissReport 전체 (Pydantic JSON)
);
CREATE INDEX IF NOT EXISTS idx_miss_reported ON miss_reports(reported_at);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SqliteWatchStore:
    """WatchItem 저장소.

    스레드 안전: FastAPI 는 요청을 여러 스레드에서 처리하므로 커넥션 하나를
    공유하되 `check_same_thread=False` 로 열고, **모든 공개 메서드가 `_lock`
    안에서 돈다.**

    ⚠⚠ **전에는 락이 없었고, 그래서 쓰기가 조용히 사라졌다 (2026-09-12).**

    이 docstring 은 "쓰기는 짧은 트랜잭션으로 끝낸다. 데모 수준의 동시성에는
    충분하다" 고 적고 있었다. **틀렸다.** `sync_loop` 는 이벤트 루프에서,
    요청 핸들러는 `run_in_threadpool` 에서 돌아 둘이 같은 커넥션을 공유하는데,
    `with self._conn:` 의 "트랜잭션 중인가 확인 → COMMIT" 두 단계가 원자적이지
    않다. 겹치면 한쪽 커밋이 다른 쪽 트랜잭션을 걷어간다.

        실측 (리눅스 · c80b03c · 8스레드 × 200 save_miss_report = 1,600)
          락 없음    저장 1,047 · 오류 152 · **무음 손실 약 400**
          RLock      저장 1,600 · 오류 0

    ⚠ **오류보다 무음 손실이 더 많다.** 예외 수만 세면 이 결함이 안 보인다 -
      그래서 검사는 예외가 아니라 **저장 건수**를 본다. 워치 등록이 조용히
      사라지면 셀러는 감시받는다고 믿는 채로 감시되지 않는다 (R6).

    ⚠ **읽기도 잠근다.** 쓰기만 잠그면 읽기 커서가 끼어들어 같은 커넥션의
      트랜잭션 상태를 흔든다.

    ⚠ **락은 소유자가 하나다.** 호출부가 각자 잠그지 않는다. `RLock` 이라
      공개 메서드끼리 서로 불러도 데드락이 아니다.

    ⚠ **스레드별 커넥션은 하지 않는다.** WAL 잠금·busy timeout 이라는 새 실패
      모양이 생긴다. 필요해지면 본선에서 본다 (미완 §6).
    """

    #: 손상된 DB 를 치우고 새로 시작했을 때 그 사실. `/healthz` 가 읽는다.
    #: ⚠ None 이 정상이다. 값이 있으면 **워치 데이터를 잃었다는 뜻**이다.
    quarantined_from: str | None = None

    #: 열린 커넥션. `_open()` 이 실패하면 **None 으로 남는다** - 그 상태로는
    #: 아무 메서드도 쓸 수 없고, 쓰려 하면 AttributeError 로 바로 드러난다.
    #: 조용히 도는 것보다 낫다. 정상 경로에서는 `__init__` 이 끝날 때 값이 있다.
    _conn: sqlite3.Connection | None = None

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        # ⚠ `_open()` 보다 먼저 만든다 - 아래 모든 메서드가 이 락을 쓴다.
        self._lock = threading.RLock()
        if self._path.parent != Path("."):
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self.quarantined_from = None
        try:
            self._open()
        except sqlite3.DatabaseError as exc:
            # ⚠⚠ **DB 파일이 손상되면 전에는 앱이 부팅조차 못 했다 (4-q).**
            #
            #   실측: 0바이트는 괜찮지만(sqlite 가 새 DB 로 본다) 쓰레기 바이트나
            #   잘린 파일이면 `DatabaseError: file is not a database` /
            #   `database disk image is malformed` 로 **프로세스가 죽는다.**
            #   Fly 에서는 재시작 루프가 되고, 그 사이 **스캔도 함께 죽는다.**
            #
            #   스캔은 이 DB 없이도 된다(리콜 축만 비고 `lookup_failed`). 투표
            #   기간에 저장소 손상으로 전체가 죽는 것보다 스캔이 사는 것이 낫다.
            #
            # ⚠ **손상 파일을 지우지 않는다.** 옆으로 치우고 새로 시작한다 -
            #   사람이 복구할 수 있어야 한다. 조용히 덮어쓰면 워치 데이터가
            #   소리 없이 사라지고, 그러면 "리콜을 가장 먼저 알린다" 는 약속이
            #   깨진 것도 모른다 (R6).
            #
            # ⚠ 그리고 **조용히 넘어가지 않는다.** `/healthz.storage` 가
            #   격리 사실을 말하고, 로그에 error 로 남긴다.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            spoiled = self._path.with_name(f"{self._path.name}.corrupt-{stamp}")
            try:
                self._path.replace(spoiled)
            except OSError:  # pragma: no cover - 파일을 못 옮기면 원래대로 던진다
                raise exc
            for suffix in ("-wal", "-shm"):
                side = Path(str(self._path) + suffix)
                if side.exists():
                    try:
                        side.unlink()
                    except OSError:
                        pass
            _log.error(
                "워치리스트 DB 가 손상되어 격리했습니다: %s → %s (%s). "
                "새 DB 로 시작하므로 **등록된 워치 항목이 비어 있습니다** - "
                "복구하려면 격리 파일을 확인하세요.",
                self._path, spoiled.name, exc,
            )
            self.quarantined_from = spoiled.name
            self._open()

    def _open(self) -> None:
        # ⚠ **커넥션을 만든 곳이 실패 시 닫는다** - 소유자를 하나로 둔다.
        #
        #   전에는 `PRAGMA` 가 던지면 열린 커넥션이 손상 파일을 **잡은 채로
        #   남았다.** 그러면 `__init__` 의 격리가 그 파일을 옆으로 치우려다
        #   Windows 에서 `PermissionError WinError 32`(다른 프로세스가 사용 중)
        #   로 실패하고, `raise exc` 로 떨어져 **격리가 아니라 부팅 실패**가
        #   된다 - 4-q 가 막으려던 바로 그 상태다.
        #
        #   POSIX 는 열린 파일의 rename 이 되므로 배포본(Linux)에서는 보이지
        #   않았고, 4-q 측정이 POSIX 에서만 이뤄져 이 경로가 비어 있었다.
        #
        # ⚠ 정리를 `__init__` 의 except 로 옮기지 않는다. 커넥션을 연 쪽이
        #   닫아야 소유자가 하나로 남는다. 여기서 닫으면 격리 경로가 **양쪽
        #   OS 에서 같은 코드로** 돈다.
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            # 동시 읽기/쓰기에서 잠금 대기를 줄인다.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        except BaseException:
            conn.close()
            self._conn = None
            raise
        self._conn = conn

    # -- writes ------------------------------------------------------------
    def add(self, item: WatchItem) -> WatchItem:
        with self._lock:
            self._upsert(item)
            return item

    def _upsert(self, item: WatchItem) -> None:
        with self._conn:  # 트랜잭션. 예외 시 롤백된다.
            self._conn.execute(
                "INSERT INTO watch_items (id, owner_id, status, payload) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "  owner_id=excluded.owner_id, "
                "  status=excluded.status, "
                "  payload=excluded.payload",
                (item.id, item.owner_id, item.status.value, item.model_dump_json()),
            )

    def mark_swept(self, item_id: str, on: date, new_fingerprints: list[str]) -> None:
        """스윕 결과를 기록한다.

        이미 알린 리콜을 다음 스윕에서 다시 알리지 않으려면 지문이 반드시
        남아야 한다. 지문 저장이 실패하면 셀러는 같은 리콜을 매일 다시 받는다.
        """
        with self._lock:
            item = self.get(item_id)
            if item is None:
                return
            seen = list(item.seen_recall_fingerprints)
            seen.extend(fp for fp in new_fingerprints if fp not in seen)
            self._upsert(item.model_copy(update={"last_swept_at": on, "seen_recall_fingerprints": seen}))

    # -- reads -------------------------------------------------------------
    def get(self, item_id: str) -> WatchItem | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM watch_items WHERE id = ?", (item_id,)
            ).fetchone()
            return WatchItem.model_validate_json(row["payload"]) if row else None

    def active_items(self) -> Iterable[WatchItem]:
        with self._lock:
            return self._by("status = ?", (WatchStatus.ACTIVE.value,))

    def for_owner(self, owner_id: str, *, active_only: bool = True) -> list[WatchItem]:
        with self._lock:
            if active_only:
                return self._by(
                    "owner_id = ? AND status = ?", (owner_id, WatchStatus.ACTIVE.value)
                )
            return self._by("owner_id = ?", (owner_id,))

    def _by(self, where: str, args: tuple) -> list[WatchItem]:
        # id 순 정렬: 스윕 결과가 호출마다 같은 순서로 나오게 한다
        # (watchlist.sweep 의 결정성 계약을 저장 계층에서도 깨지 않기 위해).
        rows = self._conn.execute(
            f"SELECT payload FROM watch_items WHERE {where} ORDER BY id", args
        ).fetchall()
        return [WatchItem.model_validate_json(r["payload"]) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS n FROM watch_items").fetchone()["n"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- recalls -----------------------------------------------------------
    #
    # 신규 판정은 uid 로 한다. publishDate 로 하면 놓친다 — 국내 응답은 정렬
    # 보장이 없고, 대량 공표(50건+) 사이에 1건짜리 소량 공표가 매달 여러 번
    # 끼어든다 (2026-09-01 실측). 놓친 알림은 이 서비스가 하는 유일한 약속을
    # 깨뜨린다 (CLAUDE.md R6).

    def known_recall_uids(self, scope: str) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT uid FROM recalls WHERE scope = ?", (scope,)
            ).fetchall()
            return {r["uid"] for r in rows}

    def upsert_recalls(self, rows: Iterable[dict], *, scope: str, fetched_at: str) -> int:
        """리콜 레코드를 저장하고 '새로 들어온' 건수를 돌려준다.

        rows 는 {uid, published_on, payload} 형태. payload 는 직렬화된 JSON 문자열.
        """
        with self._lock:
            known = self.known_recall_uids(scope)
            new = 0
            with self._conn:
                for row in rows:
                    uid = row.get("uid")
                    if not uid:
                        continue
                    if uid not in known:
                        new += 1
                    self._conn.execute(
                        "INSERT INTO recalls (uid, scope, published_on, payload, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(uid, scope) DO UPDATE SET "
                        "  published_on = excluded.published_on, "
                        "  payload = excluded.payload, "
                        "  fetched_at = excluded.fetched_at",
                        (uid, scope, row.get("published_on"), row["payload"], fetched_at),
                    )
            return new

    def commit_full_load(
        self,
        batches: dict[str, list[dict]],
        *,
        fetched_at: str,
        completed_at: str,
        minimum: int,
    ) -> dict[str, int]:
        """전량 적재와 완료 표시를 한 트랜잭션으로 쓴다.

        둘을 따로 쓰면 사이에서 죽었을 때 상태가 갈린다. 특히 위험한 방향은
        "표시는 있는데 데이터가 없는" 쪽이다 - 그러면 다음 실행이 증분으로
        넘어가 과거 구간이 영원히 안 들어오고, 스캔은 조용히 "리콜 이력 없음"
        을 돌려준다 (CLAUDE.md R6).

        minimum 미만이면 완료로 찍지 않고 ValueError 를 던진다. 정부 API 가
        2004(No Data)나 빈 resultData 를 돌려줘도 그건 오류가 아니라서 호출부가
        성공으로 읽는다 - 실제로 그렇게 0건 적재가 완료로 기록됐다.

        ⚠ 최소치는 "이번 배치가 몇 건인가" 로 잰다. 테이블 전체 건수로 재면
          빈 배치가 기존 데이터에 업혀서 통과한다 - 37,313건이 이미 있는 상태에서
          정부 API 가 두 스코프 모두 빈 응답을 주면, 아무것도 안 쓰고도 total 이
          37,313 이라 검사를 통과하고 initial_load_at 이 새로 찍힌다. 그러면
          "이 시각에 전량을 다시 받았다"는 거짓 기록이 남고, 다음 실행은 증분으로
          넘어가 그 구간이 영원히 비어 있게 된다. 반쪽 적재가 완료로 기록되던
          것(af4280e / d4920ca)과 같은 유형이다.

          스코프별로도 비어 있으면 안 된다. run_sync 의 `len(batches) == len(SCOPES)`
          는 두 스코프가 예외 없이 끝났는지만 보지, 행이 왔는지는 보지 않는다.
          국내가 0건이어도 국외 33,070건에 묻혀 합계는 통과한다.
        """
        with self._lock:
            counts: dict[str, int] = {}
            # 쓰기 전에 배치부터 잰다. 트랜잭션 안에서 재도 결과는 같지만, 검사가
            # 저장소 상태와 무관하다는 것이 코드에서 바로 보이는 편이 낫다.
            sizes = {
                scope: sum(1 for row in rows if row.get("uid"))
                for scope, rows in batches.items()
            }
            batch_total = sum(sizes.values())
            # minimum <= 0 은 "타당성 검사를 걸지 않는다" 는 명시적 옵트아웃이다
            # (스텁으로 두세 건만 넣는 테스트가 쓴다). 프로덕션 기본값은 1000 이다.
            if minimum > 0:
                empty = sorted(scope for scope, n in sizes.items() if n == 0)
                if empty:
                    raise ValueError(
                        f"전량 적재 배치에 {', '.join(empty)} 스코프가 비어 있어 완료로 "
                        "기록하지 않습니다. 정부 API 가 빈 응답을 돌려줬을 수 있습니다."
                    )
                if batch_total < minimum:
                    raise ValueError(
                        f"전량 적재 배치가 {batch_total}건뿐이라 완료로 기록하지 않습니다 "
                        f"(기대 {minimum}건 이상, 스코프별 {sizes}). "
                        "정부 API 가 빈 응답을 돌려줬을 수 있습니다."
                    )

            with self._conn:
                for scope, rows in batches.items():
                    known = self.known_recall_uids(scope)
                    new = 0
                    for row in rows:
                        uid = row.get("uid")
                        if not uid:
                            continue
                        if uid not in known:
                            new += 1
                        self._conn.execute(
                            "INSERT INTO recalls (uid, scope, published_on, payload, fetched_at) "
                            "VALUES (?, ?, ?, ?, ?) "
                            "ON CONFLICT(uid, scope) DO UPDATE SET "
                            "  published_on = excluded.published_on, "
                            "  payload = excluded.payload, "
                            "  fetched_at = excluded.fetched_at",
                            (uid, scope, row.get("published_on"), row["payload"], fetched_at),
                        )
                    counts[scope] = new

                self._conn.execute(
                    "INSERT INTO sync_state (key, value) VALUES ('initial_load_at', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (completed_at,),
                )
            return counts

    def recall_payloads(self, *, scope: str | None = None) -> list[str]:
        with self._lock:
            if scope:
                rows = self._conn.execute(
                    "SELECT payload FROM recalls WHERE scope = ? ORDER BY uid", (scope,)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT payload FROM recalls ORDER BY scope, uid"
                ).fetchall()
            return [r["payload"] for r in rows]

    def replace_rf_noncompliant(self, rows: list[dict], *, fetched_at: str) -> int:
        """부적합 현황을 통째로 교체한다.

        증분이 아니라 전량 교체인 이유: 목록에 안정적인 uid 가 없고(번호가 최신
        기준 역순이라 새 건이 들어오면 밀린다), 2,748건이라 전량이 가볍다.

        빈 목록으로 덮어쓰지 않는다 - 수집이 실패했는데 테이블을 비우면 RED
        소스가 조용히 사라진다 (반쪽 적재를 완료로 기록하던 것과 같은 함정).
        """
        with self._lock:
            if not rows:
                raise ValueError("빈 목록으로 부적합 현황을 덮어쓸 수 없습니다")
            with self._conn:
                self._conn.execute("DELETE FROM rf_noncompliant")
                self._conn.executemany(
                    "INSERT OR REPLACE INTO rf_noncompliant"
                    " (seq, company, cert_number, model, acted_on, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (r["seq"], r.get("company"), r.get("cert_number"),
                         r.get("model"), r.get("acted_on"), fetched_at)
                        for r in rows
                    ],
                )
            return len(rows)

    def rf_noncompliant_rows(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, company, cert_number, model, acted_on FROM rf_noncompliant"
            ).fetchall()
            return [dict(r) for r in rows]

    def rf_noncompliant_count(self) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) AS n FROM rf_noncompliant"
            ).fetchone()["n"]

    def recall_count(self, scope: str | None = None) -> int:
        with self._lock:
            if scope:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM recalls WHERE scope = ?", (scope,)
                ).fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) AS n FROM recalls").fetchone()
            return row["n"]

    def latest_published_on(self) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(published_on) AS d FROM recalls"
            ).fetchone()
            return row["d"] if row and row["d"] else None

    # -- sync state --------------------------------------------------------

    # -- 스윕 알림 --------------------------------------------------------
    def save_alerts(self, alerts: "Iterable[RecallAlert]") -> int:
        """새 알림을 남긴다. 이미 있는 (항목, 지문) 쌍은 무시한다.

        ⚠ 돌려주는 것은 **실제로 새로 들어간 수**다. `sweep()` 이 낸 수가
          아니다 - 같은 리콜을 두 번 세면 "새 알림 N" 이 거짓이 된다.
        """
        with self._lock:
            rows = [
                (a.watch_item_id, a.recall_fingerprint, a.detected_at.isoformat(),
                 a.model_dump_json())
                for a in alerts
            ]
            if not rows:
                return 0
            with self._conn:
                before = self._conn.execute(
                    "SELECT COUNT(*) FROM recall_alerts"
                ).fetchone()[0]
                self._conn.executemany(
                    "INSERT OR IGNORE INTO recall_alerts "
                    "(watch_item_id, recall_fingerprint, detected_at, payload) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
                after = self._conn.execute(
                    "SELECT COUNT(*) FROM recall_alerts"
                ).fetchone()[0]
            return after - before

    # ── [D-백] 오답 신고 ───────────────────────────────────────────
    def save_miss_report(self, report_id: str, reported_at: str, payload_json: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO miss_reports (id, reported_at, payload) VALUES (?, ?, ?)",
                    (report_id, reported_at, payload_json),
                )

    def miss_reports(self, *, since: str | None = None) -> list[tuple[str, str, str]]:
        """(id, reported_at, payload) 를 오래된 것부터. 내보내기 스크립트가 읽는다."""
        with self._lock:
            if since:
                rows = self._conn.execute(
                    "SELECT id, reported_at, payload FROM miss_reports "
                    "WHERE reported_at >= ? ORDER BY reported_at", (since,)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, reported_at, payload FROM miss_reports ORDER BY reported_at"
                ).fetchall()
            return [(r["id"], r["reported_at"], r["payload"]) for r in rows]

    def miss_report_snapshot(self) -> dict:
        """`/healthz` 용. 몇 건 쌓였고 마지막이 언제인가 - 검수 대기열의 길이다."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n, MAX(reported_at) AS last FROM miss_reports"
            ).fetchone()
            return {"total": int(row["n"]), "last_reported_at": row["last"]}

    def alerts_for_owner(self, owner_id: str) -> list["RecallAlert"]:
        """이 소유자의 저장된 알림. 최근 것 먼저."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT a.payload FROM recall_alerts a "
                "JOIN watch_items w ON w.id = a.watch_item_id "
                "WHERE w.owner_id = ? "
                "ORDER BY a.detected_at DESC, a.recall_fingerprint",
                (owner_id,),
            ).fetchall()
            from .models import RecallAlert

            return [RecallAlert.model_validate_json(r[0]) for r in rows]

    def alert_count(self, *, owner_id: str | None = None) -> int:
        with self._lock:
            if owner_id is None:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM recall_alerts"
                ).fetchone()[0]
            return self._conn.execute(
                "SELECT COUNT(*) FROM recall_alerts a "
                "JOIN watch_items w ON w.id = a.watch_item_id WHERE w.owner_id = ?",
                (owner_id,),
            ).fetchone()[0]

    def get_sync_state(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM sync_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_sync_state(self, key: str, value: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO sync_state (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

    def sync_snapshot(self) -> dict:
        with self._lock:
            return {
                "initial_load_at": self.get_sync_state("initial_load_at"),
                "last_sync_at": self.get_sync_state("last_sync_at"),
                "last_sync_error": self.get_sync_state("last_sync_error"),
                "recalls": {
                    "domestic": self.recall_count("domestic"),
                    "overseas": self.recall_count("overseas"),
                },
                "latest_published_on": self.latest_published_on(),
                # 전파인증 축의 유일한 RED 소스다. 0 이면 RED 가 한 번도 안 뜬다 -
                # 조용히 비어 있는 것을 healthz 가 말해줘야 한다.
                "rf_noncompliant": {
                    "count": self.rf_noncompliant_count(),
                    "synced_at": self.get_sync_state("rf_noncompliant_synced_at"),
                },
            }
