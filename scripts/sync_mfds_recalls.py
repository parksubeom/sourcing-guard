#!/usr/bin/env python
"""[⑦-b-3] 식약처 회수·판매중지(I0490)를 받아 **정제본 사본**을 만든다.

    python -u scripts/sync_mfds_recalls.py --out tests/fixtures/식약처회수_2026-09-14.json

⚠⚠ **배포본은 이 호스트를 부르지 않는다** (CLAUDE.md R4 · 총괄 판단).
  키가 URL **경로**에 들어가고 HTTPS 가 안 된다. 여기서 받아 사본을 만들고
  앱은 사본만 읽는다. fly secret 에 키를 넣지 않는다.

⚠⚠ **HTTP 200 이 성공이 아니다.** 실측(2026-09-14 17:15 KST):

      HTTP 200 · total_count='0'
      RESULT={'CODE': 'ERROR-503',
              'MSG': '09시~19시에는 서비스가 제한됩니다. 이용에 참고바랍니다.'}

  상태 코드만 보면 "받았다" 가 되고 빈 목록이 정상처럼 흐른다 - `resultCode`
  를 안 봐서 kats·rra 양쪽에서 이미 겪은 자리다 (CLAUDE.md §6). 그래서
  `RESULT.CODE` 를 보고, **모르는 코드는 성공이 아니다** (R3).

⚠ **시간 제한의 방향에 주의.** 09~19시 **동안** 막힌다 - 그 시간대에 열리는
  것이 아니다. 우리 메모가 처음에 거꾸로 적혀 있었다. 부르려면 19시 이후나
  09시 이전이어야 한다.

⚠ 저장은 `mfds_pii.write_sanitized` 로만 한다. ADDR·TELNO·IMG_FILE_PATH·
  LCNS_NO 를 포함해 **남길 목록 밖은 전부** 버려진 뒤에 디스크에 닿는다.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sourcing_guard.allowed_hosts import ensure_allowed  # noqa: E402
from sourcing_guard.config import _load_dotenv  # noqa: E402
from sourcing_guard.masking import mask_url, register_secret  # noqa: E402
from sourcing_guard.mfds_pii import write_sanitized  # noqa: E402

SERVICE = "I0490"

#: 정상 응답 코드. **실측이다** (2026-09-14 20:51 KST · 관례값 → 실측값):
#:
#:     RESULT = {'CODE': 'INFO-000', 'MSG': '정상처리되었습니다.'}
#:
#: ⚠ 모르는 코드는 성공이 아니다 (R3). 목록을 늘릴 때는 실제로 받은 코드만.
OK_CODES: tuple[str, ...] = ("INFO-000",)

#: 한 번에 받는 행 수. **100 으로 4회에 376건을 다 받았다** (2026-09-14 실측).
#: 상한이 얼마인지는 여전히 모른다 - 알 필요가 없어 안 늘린다 (R5).
PAGE = 100


class MfdsError(RuntimeError):
    """응답이 성공이 아니다. 빈 목록을 정상으로 흘리지 않는다."""


def _url(key: str, start: int, end: int) -> str:
    return (f"http://openapi.foodsafetykorea.go.kr/api/{key}/{SERVICE}"
            f"/json/{start}/{end}")


def fetch(key: str, start: int, end: int, *, tries: int = 3,
          gap: float = 3.0, client=None) -> dict:
    """한 페이지. 3회·3초 재시도. **주소는 마스킹해서만 찍는다.**"""
    url = _url(key, start, end)
    ensure_allowed(url)
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            if client is not None:
                r = client.get(url)
            else:
                with httpx.Client(timeout=60) as c:
                    r = c.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as exc:                      # noqa: BLE001
            last = exc
            print(f"    재시도 {attempt}/{tries}: {type(exc).__name__} "
                  f"{mask_url(str(exc))[:70]}")
            if attempt < tries:
                time.sleep(gap)
    raise MfdsError(f"세 번 다 실패했습니다: {type(last).__name__}")


def body(doc: dict) -> dict:
    """봉투에서 서비스 블록을 꺼내고 **성공인지 본다.**"""
    block = doc.get(SERVICE)
    if not isinstance(block, dict):
        raise MfdsError(f"{SERVICE} 블록이 없습니다 - 키={list(doc)[:6]}")
    result = block.get("RESULT") or {}
    code = str(result.get("CODE") or "")
    if code not in OK_CODES:
        # MSG 는 상태 문구다(개인정보 아님). 그대로 보여야 왜 멈췄는지 안다.
        raise MfdsError(f"성공 코드가 아닙니다: CODE={code!r} MSG={result.get('MSG')!r}")
    return block


def collect(key: str, *, page: int = PAGE, limit: int | None = None,
            client=None) -> tuple[list[dict], int, int]:
    """전량. (행, 총건수, 실호출 회차)."""
    rows: list[dict] = []
    calls = 0
    start = 1
    total = 0
    while True:
        end = start + page - 1
        doc = fetch(key, start, end, client=client)
        calls += 1
        block = body(doc)
        total = int(block.get("total_count") or 0)
        got = block.get("row") or []
        got = got if isinstance(got, list) else [got]
        rows.extend(got)
        print(f"  {start:>6}~{end:<6} {len(got):>4}행  (누계 {len(rows)}/{total})")
        if not got or len(rows) >= total or (limit and len(rows) >= limit):
            break
        start = end + 1
    return rows, total, calls


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=f"tests/fixtures/식약처회수_{date.today()}.json")
    ap.add_argument("--page", type=int, default=PAGE)
    ap.add_argument("--limit", type=int, default=None,
                    help="시험용. 이 수를 넘으면 멈춘다")
    args = ap.parse_args()

    _load_dotenv()
    key = os.getenv("MFDS_API_KEY")
    if not key:
        raise SystemExit("MFDS_API_KEY 가 없습니다 (.env)")
    # ⚠ **호출보다 먼저 등록한다.** 예외 메시지·로그에 키가 남지 않게 한다.
    register_secret(key)

    print(f"식약처 {SERVICE} 수집 · 주소 {mask_url(_url(key, 1, args.page))}")
    rows, total, calls = collect(key, page=args.page, limit=args.limit)

    out = Path(args.out)
    counts = write_sanitized(out, {SERVICE: {"row": rows}})
    print()
    print(f"총건수 {total} · 받은 행 {len(rows)} · **실호출 {calls}회**")
    print(f"정제 건수 {dict(sorted(counts.items()))}")
    print(f"→ {out}  (사이드카 {out.name}.정제.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
