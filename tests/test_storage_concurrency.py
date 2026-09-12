"""[①.5] **저장소 공유 커넥션 경합** — 쓰기가 조용히 사라졌다 (2026-09-12).

`sync_loop` 는 이벤트 루프에서, 요청 핸들러는 `run_in_threadpool` 에서 돈다.
둘이 `SqliteWatchStore` 의 커넥션 하나를 공유하는데 `with self._conn:` 의
"트랜잭션 중인가 확인 → COMMIT" 두 단계가 원자적이지 않아, 겹치면 한쪽 커밋이
다른 쪽 트랜잭션을 걷어간다.

    실측 (리눅스 · c80b03c · 8스레드 × 200 = 1,600)
      락 없음   저장 1,047 · 오류 152 · **무음 손실 약 400**
      RLock     저장 1,600 · 오류 0

⚠⚠ **오류보다 무음 손실이 많다.** 예외만 세는 검사는 이 결함을 놓친다 -
  152 는 시끄럽게 실패했지만 400 은 아무 말 없이 사라졌다. 그래서 아래 검사는
  전부 **저장 건수**를 기대값으로 쓴다. 기대값은 "지금 이렇게 나온다" 가 아니라
  **"무엇이 옳은가"** 에서 왔다 - N×M 을 넣었으면 N×M 이 남아야 한다.

⚠ 워치 등록이 조용히 사라지면 셀러는 감시받는다고 믿는 채로 감시되지 않는다.
  이 서비스가 하는 유일한 약속이 그것이다 (CLAUDE.md R6).
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import threading
import time
from datetime import datetime, timezone

import pytest

from sourcing_guard.models import WatchItem
from sourcing_guard.storage import SqliteWatchStore


def _run(threads: list[threading.Thread]) -> None:
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_concurrent_writes_all_survive(tmp_path):
    """스레드 N × 쓰기 M → **저장 N×M · 예외 0.**

    예외 0 만 단정하면 무음 손실을 놓친다. 건수를 먼저 본다.
    """
    store = SqliteWatchStore(tmp_path / "w.db")
    n_threads, per_thread = 8, 200
    errors: list[str] = []

    def writer(k: int) -> None:
        try:
            for i in range(per_thread):
                store.save_miss_report(f"r{k}-{i}", "2026-09-12T00:00:00+00:00", "{}")
        except Exception as exc:                      # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")

    _run([threading.Thread(target=writer, args=(k,)) for k in range(n_threads)])

    stored = len(store.miss_reports())
    assert stored == n_threads * per_thread, (
        f"넣은 것 {n_threads * per_thread} · 남은 것 {stored} → "
        f"**{n_threads * per_thread - stored}건이 조용히 사라졌다.** 오류는 {len(errors)}건."
    )
    assert not errors, f"쓰기 중 예외 {len(errors)}건: {errors[:3]}"


def test_a_long_transaction_does_not_swallow_other_writers(tmp_path):
    """긴 트랜잭션(리콜 수천 행) 중에 다른 스레드가 써도 **둘 다 전부 남는다.**

    실제 모양이다 - 일일 동기화가 `upsert_recalls` 로 수천 행을 쓰는 동안
    셀러가 워치를 등록하거나 오답을 신고한다.

    ⚠ **이 검사는 락 없이도 통과한다 (2026-09-12 실측).** 회귀 가드가 아니다.
      끼어든 쓰기가 커밋을 당겨 가면 대량 쓰기의 남은 행이 **새 트랜잭션**을
      열어 마저 들어가므로, 이 겹침에서는 결국 아무것도 잃지 않는다. 잃는 것은
      `test_concurrent_writes_all_survive` 쪽 모양이다.

      그래도 남긴다 - 총괄이 지정한 시나리오이고, 저장 방식을 바꿀 때(예: 스레드별
      커넥션) 가장 먼저 깨질 자리다. **회귀를 잡는 것은 위 둘이다.**
    """
    store = SqliteWatchStore(tmp_path / "w.db")
    n_rows = 3000
    started = threading.Event()
    errors: list[str] = []

    # ⚠ `rows` 를 **제너레이터**로 준다. `upsert_recalls` 는 이것을
    #   `with self._conn:` **안에서** 소비하므로, 첫 행에서 신호를 주면 다른
    #   스레드가 **트랜잭션이 열린 채로** 끼어든다. 리스트로 주고 호출 직전에
    #   신호하면 대량 쓰기가 먼저 끝나 버려 겹침이 안 생긴다 - 실제로 그렇게
    #   썼다가 락 없이도 통과하는 검사가 됐다.
    def row_stream():
        for i in range(n_rows):
            if i == 0:
                started.set()
                time.sleep(0.05)      # 다른 스레드가 트랜잭션 안으로 들어올 틈
            yield {"uid": f"u{i}", "published_on": "20260912", "payload": "{}"}

    def bulk() -> None:
        try:
            store.upsert_recalls(
                row_stream(), scope="domestic", fetched_at="2026-09-12T00:00:00+00:00"
            )
        except Exception as exc:                      # noqa: BLE001
            errors.append(f"bulk {type(exc).__name__}: {exc}")

    def others() -> None:
        try:
            started.wait(5)
            store.save_miss_report("m1", "2026-09-12T00:00:00+00:00", "{}")
            store.add(WatchItem(
                id="w1",
                owner_id="o1",
                product_name="유아용 블록 완구",
                registered_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
            ))
        except Exception as exc:                      # noqa: BLE001
            errors.append(f"other {type(exc).__name__}: {exc}")

    _run([threading.Thread(target=bulk), threading.Thread(target=others)])

    assert not errors, f"예외: {errors}"
    assert store.recall_count("domestic") == n_rows, (
        f"리콜 {n_rows}행을 넣었는데 {store.recall_count('domestic')}행만 남았다"
    )
    assert len(store.miss_reports()) == 1, "긴 트랜잭션이 신고 1건을 삼켰다"
    assert store.count() == 1, "긴 트랜잭션이 워치 등록을 삼켰다"


def test_every_public_method_takes_the_lock():
    """**재발 가드** — 공개 메서드는 전부 `with self._lock:` 으로 시작한다.

    새 메서드가 락 없이 들어오면 여기서 깨진다. 경합은 재현이 들쭉날쭉해서
    (같은 파일을 8회 돌렸을 때 6회만 깨졌다) 동작 검사만으로는 못 잡는다 -
    **구조를 잠근다.**

    ⚠ 문자열이 아니라 AST 로 본다. `srccheck.code_only` 는 금지 문자열을 찾는
      검사가 자기 주석에 걸리지 않게 하는 도구인데, 여기서는 금지가 아니라
      **필수** 를 보므로 그 함정이 없고 AST 가 더 정확하다.
    """
    src = pathlib.Path(inspect.getsourcefile(SqliteWatchStore)).read_text(encoding="utf-8")
    cls = next(n for n in ast.parse(src).body
               if isinstance(n, ast.ClassDef) and n.name == "SqliteWatchStore")

    missing: list[str] = []
    checked: list[str] = []
    for m in cls.body:
        if not isinstance(m, ast.FunctionDef) or m.name.startswith("_"):
            continue
        checked.append(m.name)
        body = m.body
        if (isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]                            # docstring 은 락 밖이 맞다
        first = body[0] if body else None
        ok = isinstance(first, ast.With) and any(
            isinstance(it.context_expr, ast.Attribute)
            and it.context_expr.attr == "_lock"
            for it in first.items
        )
        if not ok:
            missing.append(m.name)

    assert checked, "공개 메서드를 하나도 못 찾았다 - 검사가 헛돌고 있다"
    assert not missing, (
        "락 없이 도는 공개 메서드가 있습니다: " + ", ".join(missing)
        + "\n  공유 커넥션이라 락 밖에서 쓰면 다른 스레드의 커밋을 걷어갑니다."
        + "\n  메서드 첫 줄을 `with self._lock:` 으로 시작하세요 (docstring 은 밖)."
    )
