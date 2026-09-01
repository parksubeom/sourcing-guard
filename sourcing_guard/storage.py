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

import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

from .models import WatchItem, WatchStatus

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

-- 동기화 진행 상태. 재배포 후 "초기 적재를 다시 해야 하나" 를 판단하고,
-- 캐시 기준일 표시에도 같은 값을 쓴다.
CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SqliteWatchStore:
    """WatchItem 저장소.

    스레드 안전: FastAPI 는 요청을 여러 스레드에서 처리하므로 커넥션을 공유하되
    `check_same_thread=False` 로 열고 쓰기는 짧은 트랜잭션으로 끝낸다. 데모
    수준의 동시성에는 충분하고, 늘어나면 커넥션 풀로 바꾼다.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if self._path.parent != Path("."):
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 동시 읽기/쓰기에서 잠금 대기를 줄인다.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- writes ------------------------------------------------------------
    def add(self, item: WatchItem) -> WatchItem:
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
        item = self.get(item_id)
        if item is None:
            return
        seen = list(item.seen_recall_fingerprints)
        seen.extend(fp for fp in new_fingerprints if fp not in seen)
        self._upsert(item.model_copy(update={"last_swept_at": on, "seen_recall_fingerprints": seen}))

    # -- reads -------------------------------------------------------------
    def get(self, item_id: str) -> WatchItem | None:
        row = self._conn.execute(
            "SELECT payload FROM watch_items WHERE id = ?", (item_id,)
        ).fetchone()
        return WatchItem.model_validate_json(row["payload"]) if row else None

    def active_items(self) -> Iterable[WatchItem]:
        return self._by("status = ?", (WatchStatus.ACTIVE.value,))

    def for_owner(self, owner_id: str, *, active_only: bool = True) -> list[WatchItem]:
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
        return self._conn.execute("SELECT COUNT(*) AS n FROM watch_items").fetchone()["n"]

    def close(self) -> None:
        self._conn.close()

    # -- recalls -----------------------------------------------------------
    #
    # 신규 판정은 uid 로 한다. publishDate 로 하면 놓친다 — 국내 응답은 정렬
    # 보장이 없고, 대량 공표(50건+) 사이에 1건짜리 소량 공표가 매달 여러 번
    # 끼어든다 (2026-09-01 실측). 놓친 알림은 이 서비스가 하는 유일한 약속을
    # 깨뜨린다 (CLAUDE.md R6).

    def known_recall_uids(self, scope: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT uid FROM recalls WHERE scope = ?", (scope,)
        ).fetchall()
        return {r["uid"] for r in rows}

    def upsert_recalls(self, rows: Iterable[dict], *, scope: str, fetched_at: str) -> int:
        """리콜 레코드를 저장하고 '새로 들어온' 건수를 돌려준다.

        rows 는 {uid, published_on, payload} 형태. payload 는 직렬화된 JSON 문자열.
        """
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
        """
        counts: dict[str, int] = {}
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

            total = self._conn.execute(
                "SELECT COUNT(*) AS n FROM recalls"
            ).fetchone()["n"]
            if total < minimum:
                # 롤백된다. 적재도 표시도 남지 않는다.
                raise ValueError(
                    f"전량 적재 결과가 {total}건뿐이라 완료로 기록하지 않습니다 "
                    f"(기대 {minimum}건 이상). 정부 API 가 빈 응답을 돌려줬을 수 있습니다."
                )
            self._conn.execute(
                "INSERT INTO sync_state (key, value) VALUES ('initial_load_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (completed_at,),
            )
        return counts

    def recall_payloads(self, *, scope: str | None = None) -> list[str]:
        if scope:
            rows = self._conn.execute(
                "SELECT payload FROM recalls WHERE scope = ? ORDER BY uid", (scope,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT payload FROM recalls ORDER BY scope, uid"
            ).fetchall()
        return [r["payload"] for r in rows]

    def recall_count(self, scope: str | None = None) -> int:
        if scope:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM recalls WHERE scope = ?", (scope,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM recalls").fetchone()
        return row["n"]

    def latest_published_on(self) -> str | None:
        row = self._conn.execute(
            "SELECT MAX(published_on) AS d FROM recalls"
        ).fetchone()
        return row["d"] if row and row["d"] else None

    # -- sync state --------------------------------------------------------

    def get_sync_state(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_sync_state(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO sync_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def sync_snapshot(self) -> dict:
        return {
            "initial_load_at": self.get_sync_state("initial_load_at"),
            "last_sync_at": self.get_sync_state("last_sync_at"),
            "last_sync_error": self.get_sync_state("last_sync_error"),
            "recalls": {
                "domestic": self.recall_count("domestic"),
                "overseas": self.recall_count("overseas"),
            },
            "latest_published_on": self.latest_published_on(),
        }
