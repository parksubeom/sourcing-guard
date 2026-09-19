"""인증 조회 캐시 시드를 만든다 — 실조회 결과를 실조회 시각과 함께 옮긴다.

왜 필요한가
-----------
`CertCache` 는 프로세스 메모리(`dict`)다. **재배포하면 0 이 된다.** 국표원
조회가 죽어 있는 동안 배포하면 데모 셋이 전부 "조회 실패" 로 뜬다 - 투표
전날에 그러면 첫 화면에서 이탈한다 (`Claude outputs/sg-final-day.md` §0-2).

그래서 앱 시작 시 캐시에 넣을 값을 파일로 둔다. 이 스크립트가 그 파일을
만든다.

⚠ **R5 를 어기지 않는다.** 값을 손으로 쓰지 않는다 - 국표원에 실제로 조회해서
  받은 레코드를, **그 조회 시각과 함께** 옮기는 것뿐이다. 화면은 시드를 쓸 때
  "YYYY-MM-DD 조회분으로 표시합니다" 라고 말한다 (`verifier.py` stale 절).
  지금 프로세스 메모리에 있는 것과 같은 정보를 같은 규칙으로 두는 것이고,
  달라지는 것은 재시작을 건너간다는 것뿐이다.

⚠ **실호출이다.** 측정으로만 돌리고 회차를 작업로그에 적는다 (CLAUDE.md §6).
  번호 하나에 호출 하나다.

⚠ 방송통신기자재 번호(`MSIP-...` · `R-R-...`)는 **넣지 않는다.** 국표원이
  아니라 전파연구원 소관이고 `rra_client` 가 따로 본다. `CERT_NUMBER_RE` 로
  거른다 - 목록을 손으로 고르면 다음 사람이 기준을 모른다.

쓰는 법
-------
    PYTHONUTF8=1 PYTHONPATH=. python -u scripts/build_cert_seed.py \
        --out sourcing_guard/data/cert_seed.json

    # 어느 번호를 넣을지 먼저 보고 싶으면
    PYTHONUTF8=1 PYTHONPATH=. python -u scripts/build_cert_seed.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.config import settings  # noqa: E402
from sourcing_guard.demos import DEMOS  # noqa: E402
from sourcing_guard.kats_client import (  # noqa: E402
    CERT_NUMBER_RE,
    KatsClient,
    normalize_kc,
)

_ROOT = Path(__file__).resolve().parents[1]
_SAMPLES = (
    _ROOT / "tests/fixtures/도매꾹_정제_2026-09-08/상세.json",
    _ROOT / "tests/fixtures/도매꾹_확장_2026-09-08/상세_확장.json",
)


def _demo_numbers() -> list[str]:
    """데모 문구에 박혀 있는 인증번호. 데모가 단일 출처이므로 거기서 읽는다."""
    out: list[str] = []
    for demo in DEMOS:
        for match in CERT_NUMBER_RE.finditer(demo["text"]):
            key = normalize_kc(match.group(0))
            if key not in out:
                out.append(key)
    return out


def _sample_numbers() -> dict[str, str]:
    """도매꾹 표본의 `detail.safetyCert[].no` → 상품명.

    ⚠ 정제본만 읽는다. 원문 응답에는 제3자 사업자 정보가 들어 있다 (R4).
    """
    found: dict[str, str] = {}
    for path in _SAMPLES:
        if not path.exists():
            continue
        blocks = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(blocks, dict):
            blocks = [blocks]
        for block in blocks:
            items = block["response"]["domeggook"]["item"]
            if isinstance(items, dict):
                items = [items]
            for item in items:
                detail = item.get("detail") or {}
                certs = detail.get("safetyCert") or []
                if isinstance(certs, dict):
                    certs = [certs]
                for cert in certs:
                    if not isinstance(cert, dict):
                        continue
                    raw = (cert.get("no") or "").strip()
                    if not raw or raw == "-":
                        continue
                    # 전파 번호를 여기서 거른다. 국표원 소관이 아니다.
                    if not CERT_NUMBER_RE.fullmatch(normalize_kc(raw)):
                        continue
                    key = normalize_kc(raw)
                    found.setdefault(key, (item["basis"]["title"] or "").strip())
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    demo = _demo_numbers()
    samples = _sample_numbers()
    targets = demo + [k for k in sorted(samples) if k not in demo]

    print(f"데모 번호 {len(demo)} · 표본 번호 {len(samples)} · 합 {len(targets)}")
    for key in targets:
        print(f"  {key:22} {'(데모)' if key in demo else samples.get(key, '')[:44]}")
    if args.dry_run:
        return 0

    if settings.mock_mode:
        print("MOCK_MODE 다. 시드는 실조회로만 만든다 - 중단한다.", file=sys.stderr)
        return 2

    client = KatsClient(
        base_url=settings.kats_base_url,
        service_key=settings.kats_service_key,
        mock=settings.mock_mode,
    )
    if client._mock:  # noqa: SLF001 - 키가 없으면 목으로 떨어진다. 그건 시드가 아니다
        print("인증키가 없어 목 클라이언트가 됐다 - 중단한다.", file=sys.stderr)
        return 2

    entries: list[dict] = []
    failures: list[tuple[str, str]] = []
    for key in targets:
        started = time.time()
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            record = client.lookup_certification(key)
        except Exception as exc:  # 조회 실패는 시드에 넣지 않는다
            failures.append((key, f"{type(exc).__name__}: {exc}"))
            print(f"  FAIL {key:22} {time.time() - started:5.2f}s  {type(exc).__name__}")
            continue
        entries.append(
            {
                "cert_number": key,
                "fetched_at": fetched_at,
                # ⚠ 레코드가 **없는 것**(미조회)도 사실이다. null 로 남긴다 -
                #   빼 버리면 화면이 "조회 실패" 로 가고, 그건 다른 뜻이다.
                "record": asdict(record) if record is not None else None,
            }
        )
        state = getattr(getattr(record, "state", None), "value", None)
        print(
            f"  OK   {key:22} {time.time() - started:5.2f}s  "
            f"{(record.status if record else '(미조회)') or '-'} / {state or '-'}"
        )

    print(f"\n조회됨 {len(entries)} · 실패 {len(failures)}")
    for key, why in failures:
        print(f"  실패 {key}: {why}")

    if args.out is None:
        return 0

    payload = {
        "_기록": (
            "국표원 인증 조회 캐시 시드. `scripts/build_cert_seed.py` 가 실조회로 만든다. "
            "손으로 고치지 않는다 - 값이 낡으면 다시 돌린다."
        ),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": entries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # ⚠ `newline=""` 이 없으면 윈도우에서 파이썬이 `\n` 을 `\r\n` 으로 번역한다.
    #   이 파일의 블롭은 LF 이고, 줄끝이 바뀌면 diff 가 **파일 전체**가 되어
    #   `git blame` 이 죽는다. 2026-09-19 에 실제로 그렇게 커밋했다.
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print(f"→ {args.out} ({args.out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
