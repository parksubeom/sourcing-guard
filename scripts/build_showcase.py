#!/usr/bin/env python
"""[P4] 도매꾹 상품 리스트(showcase) 사본을 만든다 — **총괄이 손으로 한 것을 재현 가능하게.**

왜 스크립트인가 (총괄 지시 2026-09-20 [P4] 할 일 ①)
---------------------------------------------------
총괄이 실호출 121회로 전 구간을 손으로 실측했다. 결과는 맞지만 **재현이 안 된다.**
숫자가 어디서 나왔는지 말할 수 없으면 그 숫자는 근거가 아니다 (R5).

⚠⚠ **국표원 조회가 되는 곳에서 돌려야 한다.** 배포본(도쿄)에서는 막혀 있다.
  한국에서 건당 0.4초쯤이고 74건에 47초였다(총괄 실측). 돌린 환경과 회차를
  작업로그에 적는다 (CLAUDE.md §6).

⚠⚠ **썸네일은 hotlink 하지 않는다.** 도매꾹 약관이 "제공된 이미지를 다운로드
  받아 … 이미지호스팅 서비스에 저장하여 사용하시기 바랍니다" 라고 명시한다.
  받아서 우리가 서빙한다. **원본을 그대로 커밋하지 않는다** - 리포가 공개다.
  `THUMB_MAX_PX` 로 줄인 것만 넣는다.

두 단계다
---------
    collect   도매꾹 목록 8회 · 상세 4회 · 국표원 N회 · 썸네일 N장
              → sourcing_guard/data/showcase.json (결과 없음)
    scan      고른 것을 `/api/v1/scan` 에 넣고 결과를 사본에 붙인다
              → 같은 파일 (결과 있음)

나눈 이유: 수집은 LLM 0회이고 스캔은 상품당 1회다. 한 덩어리로 두면 썸네일을
다시 받으려고 LLM 을 또 쓰게 된다.

쓰는 법
-------
    # ① 수집 (LLM 0회 · 도매꾹 12회 + 국표원 N회)
    PYTHONUTF8=1 PYTHONPATH=. python -u scripts/build_showcase.py collect

    # ② 앱을 실모드로 띄우고 (LLM·국표원 실호출이 나간다 - 측정이다)
    PYTHONUTF8=1 MOCK_MODE=false SYNC_ENABLED=false \\
        python -m uvicorn sourcing_guard.main:app --port 8012

    # ③ 스캔 (LLM N회 · 국표원 N회)
    PYTHONUTF8=1 PYTHONPATH=. python -u scripts/build_showcase.py scan \\
        --base http://127.0.0.1:8012

총괄이 걸린 함정 넷 — 같은 데서 시간 쓰지 말 것
-----------------------------------------------
    ① `getItemView(multiple=true)` 응답은 `r["domeggook"]["item"]` 이 **바로
       리스트**다. 한 겹 더 있다고 가정하면 400건이 1건으로 파싱된다
    ② 상품번호는 `item["basis"]["no"]` 다. `item["no"]` 가 아니다
    ③ 인증번호 추출은 `domeggook_adapter.kc_numbers_from(item)` 을 쓴다.
       새로 짜지 않는다 - `cert=Y`·`useNo=Y` 조건과 고시 인증 항목 desc 의
       번호까지 이미 본다
    ④ 조회 메서드는 `lookup_certification(번호)` 다. `lookup` 이 아니다

⚠ 저장은 `showcase_pii.write_sanitized` 로만 한다 - 남길 목록 밖은 전부
  버려진 뒤에 디스크에 닿는다 (CLAUDE.md §6).

⚠ 프로세스 하나 · `python -u` · 이전 프로세스 확인. 429 를 받으면 **재시도하지
  않고** 그 자리까지를 저장하고 멈춘다 (CLAUDE.md §6).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sourcing_guard.allowed_hosts import ensure_allowed  # noqa: E402
from sourcing_guard.config import _load_dotenv  # noqa: E402
from sourcing_guard.domeggook_adapter import facts_from_item, kc_numbers_from  # noqa: E402
from sourcing_guard.domeggook_client import (  # noqa: E402
    MAX_VIEW_BATCH,
    DomeggookApiError,
    DomeggookClient,
    DomeggookRateLimited,
)
from sourcing_guard.kats_client import (  # noqa: E402
    CERT_NUMBER_RE,
    CertState,
    KatsApiError,
    KatsClient,
)
from sourcing_guard.placeholders import clean  # noqa: E402
from sourcing_guard.showcase_pii import (  # noqa: E402
    residual_of,
    sanitize_list_item,
    write_sanitized,
)

_ROOT = Path(__file__).resolve().parents[1]
OUT = _ROOT / "sourcing_guard" / "data" / "showcase.json"
THUMB_DIR = _ROOT / "sourcing_guard" / "static" / "showcase"
NOTES_DIR = _ROOT / "tests" / "fixtures"

#: 총괄이 고른 카테고리 여덟. **코드가 아니라 지시다** - 바꾸려면 총괄에게 묻는다.
#:
#: ⚠ `기타전기용품` 은 총괄 실측에서 국표원 형식 번호가 **0건**이었다. 그래도
#:   부른다 - 0 인 것도 실측이고, 다음에 바뀌면 그때 알아야 한다 (R3).
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("09_03_06_00_00", "블록"),
    ("09_03_17_00_00", "작동완구"),
    ("09_13_01_00_00", "봉제인형"),
    ("09_03_04_00_00", "물놀이용품"),
    ("09_03_05_10_00", "크레파스"),
    ("09_03_05_03_00", "색연필"),
    ("09_03_03_00_00", "놀이방매트"),
    ("12_16_11_06_00", "기타전기용품"),
)

#: 카테고리당 받는 건수. 총괄 실측과 같아야 대조가 된다 (8 × 50 = 400).
PER_CATEGORY = 50

#: 화면에 올리는 상품 수. 총괄 지시는 "24~30개" 다.
DEFAULT_LIMIT = 30

#: 썸네일 긴 변. **200px 이다** - 카드가 그보다 크게 그리지 않는다. 총괄 실측
#: 30장에 284KB. 리포가 공개이므로 원본(보통 330~1000px)을 넣지 않는다.
THUMB_MAX_PX = 200
#: webp 품질. 80 은 눈으로 구분이 안 되면서 절반 이하로 준다.
THUMB_QUALITY = 80

#: 화면에 올리지 않는 인증상태. **RED 가 나오는 둘이다** (`verifier._CERT_STATE_FINDING`).
#:
#: ⚠⚠ 감추는 것이 아니라 **이 화면의 일이 아니다.** 실제로 팔리고 있는 남의
#:   상품을 우리 화면이 빨간불로 세우는 것은 "상품이나 판매자에 대한 평가가
#:   아니다" 라는 우리 문장과 어긋난다. 취소·표시사용금지 인증을 다루는 자리는
#:   체험 표본(`/samples`)이고, 거기는 우리가 고른 것이라고 밝힌다.
#:
#: ⚠ 뺀 건수는 **보고한다.** 0 이 아니면 그 사실이 기록이다.
EXCLUDED_STATES: frozenset[CertState] = frozenset({CertState.REVOKED, CertState.SUSPENDED})


# ── 작은 도구 ────────────────────────────────────────────────────────
def write_note(path: Path, lines: list[str], must_contain: tuple[str, ...]) -> None:
    """기록 파일을 쓰고 **쓴 것이 성한지 스스로 단정한다.**

    ⚠⚠ 2026-09-20 에 이 스크립트가 바로 그 사고를 냈다. 블록을 고치면서
      쓰는 코드를 같이 지웠는데, 함수가 `None` 을 돌려주고 `SystemExit(None)`
      은 종료코드 0 이라 **화면 출력은 맞고 파일만 안 써진 채 성공으로 보였다.**
      두 번을 그대로 넘겼다.

      CLAUDE.md §6: "파일을 제자리에서 고쳐 쓰는 스크립트는 쓴 뒤에 그 파일이
      아직 성한지 **스스로 단정**해야 한다." 여기가 그 한 줄이다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(chr(10).join(lines), encoding="utf-8", newline="")
    back = path.read_text(encoding="utf-8")
    missing = [t for t in must_contain if t not in back]
    if missing:
        raise RuntimeError(f"{path} 를 썼는데 내용이 없다: {missing}")
    print(f"→ {path} ({path.stat().st_size:,} bytes)")



def _as_int(raw: object) -> int | None:
    """숫자 문자열 → int. **문자열로 흘리지 않는다** (CLAUDE.md §6).

    도매꾹은 `price`·`unitQty` 를 문자열로 준다. 그대로 화면에 넘기면
    비교·합산이 조용히 틀린다 (`"5" > "10"` 이 참이다).
    """
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _view_items(payload: dict) -> list[dict]:
    """`getItemView(multiple=true)` 응답 → 상품 리스트.

    ⚠ 함정 ①. `r["domeggook"]["item"]` 이 **바로 리스트**다. 한 겹 더 있다고
      가정하면 400건이 1건이 된다.
    """
    items = (payload.get("domeggook") or {}).get("item")
    if isinstance(items, dict):
        return [items]
    return [i for i in (items or []) if isinstance(i, dict)]


def _list_items(payload: dict) -> list[dict]:
    lst = (payload.get("domeggook") or {}).get("list") or {}
    items = lst.get("item")
    if isinstance(items, dict):
        return [items]
    return [i for i in (items or []) if isinstance(i, dict)]


def gov_format_numbers(item: dict) -> list[str]:
    """상세 하나에서 **국표원 형식**의 인증번호만.

    ⚠ 함정 ③. 추출은 `kc_numbers_from` 이 한다 - `cert=Y`·`useNo=Y` 조건과
      고시 인증 항목 desc 의 번호까지 이미 본다. 여기서는 **형식만** 거른다:
      `fullmatch` 이므로 "CB061R2170-3018 외 2건" 같은 문장은 떨어진다.
    """
    return [n for n in kc_numbers_from(item) if CERT_NUMBER_RE.fullmatch(n.strip())]


def page_text_of(facts: dict, certs: list[str]) -> str:
    """스캔에 넣을 문자열. **상세의 구조화 필드만**으로 만든다.

    ⚠⚠ `infoDuty` 를 통째로 옮기지 않는다. 거기에는 A/S 전화번호 행이 있고
      (실측 17/100) 그대로 텍스트로 만들면 **그 번호가 LLM 으로 나가고 사본에
      눕는다.** `facts_from_item` 이 이미 고시 항목 이름을 가려서 뽑은 값만
      쓴다 (`showcase_pii.FACT_KEYS`).

    ⚠ 셀러가 붙여넣는 모양과 같은 갈래다 - 상품명 + 고시 표기 몇 줄.
      지어낸 문장을 넣지 않는다 (R5).
    """
    lines = [facts.get("product_name") or ""]
    for label, key in (("모델명", "model_name"), ("제조사", "maker"), ("제조국", "origin")):
        if facts.get(key):
            lines.append(f"{label} {facts[key]}")
    if facts.get("materials"):
        lines.append("재질 " + " · ".join(facts["materials"]))
    if facts.get("target_age"):
        lines.append(f"사용연령 {facts['target_age']}")
    if certs:
        lines.append("KC 인증번호 " + " · ".join(certs))
    return "\n".join(line for line in lines if line.strip())


def save_thumb(url: str, no: str, client: httpx.Client) -> tuple[str | None, int]:
    """썸네일을 받아 **200px webp** 로 저장. (파일명, 바이트) 를 돌려준다.

    ⚠ `ensure_allowed` 를 먼저 부른다. 호스트는 `cdn1.domeggook.com` 이고
      `domeggook.com` 의 하위 도메인이라 통과한다 (R4 표).

    ⚠ 실패해도 던지지 않는다 - 그 상품만 썸네일 없이 간다. 한 장 때문에
      수집이 멈추면 회차만 늘어난다.
    """
    from PIL import Image

    try:
        ensure_allowed(url)
        res = client.get(url, timeout=20.0)
        res.raise_for_status()
        img = Image.open(io.BytesIO(res.content))
        img = img.convert("RGB")
        img.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=THUMB_QUALITY, method=6)
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        (THUMB_DIR / f"{no}.webp").write_bytes(buf.getvalue())
        return f"{no}.webp", buf.getbuffer().nbytes
    except Exception as exc:  # noqa: BLE001 - 한 장 실패가 수집을 멈추면 안 된다
        print(f"    썸네일 실패 {no}: {type(exc).__name__} {exc}")
        return None, 0


# ── ① 수집 ──────────────────────────────────────────────────────────
def collect(limit: int, *, dry_run: bool = False) -> int:
    _load_dotenv()
    key = os.getenv("DOMEGGOOK_API_KEY")
    if not key:
        print("DOMEGGOOK_API_KEY 가 없습니다 (.env)", file=sys.stderr)
        return 2

    dome = DomeggookClient(key)
    t0 = time.time()

    # ── 목록 8회 ────────────────────────────────────────────────────
    listing: dict[str, dict] = {}       # 상품번호 → 정제된 목록 항목
    category_of: dict[str, str] = {}    # 상품번호 → 카테고리 이름
    order_in_cat: dict[str, int] = {}   # 상품번호 → 그 카테고리 안 랭킹 순위
    drop_counts: Counter[str] = Counter()
    for code, name in CATEGORIES:
        try:
            payload = dome.search(ca=code, sz=PER_CATEGORY, so="rd")
        except DomeggookRateLimited as exc:
            print(f"429 - 멈춥니다: {exc}", file=sys.stderr)
            return 1
        except DomeggookApiError as exc:
            print(f"  {name} 목록 실패: {exc}", file=sys.stderr)
            continue
        rows = _list_items(payload)
        for rank, raw in enumerate(rows):
            no = str(raw.get("no") or "").strip()
            if not no:
                continue
            listing[no] = sanitize_list_item(raw, drop_counts)
            category_of[no] = name
            order_in_cat[no] = rank
        print(f"  {name:8} {len(rows):3}건")
    print(f"목록 {len(CATEGORIES)}회 · 후보 {len(listing)}건 · {time.time()-t0:.1f}s")

    # ── 상세 4회 (100개씩) ──────────────────────────────────────────
    nos = list(listing)
    details: dict[str, dict] = {}
    for i in range(0, len(nos), MAX_VIEW_BATCH):
        chunk = nos[i:i + MAX_VIEW_BATCH]
        try:
            payload = dome.view([int(n) for n in chunk])
        except DomeggookRateLimited as exc:
            print(f"429 - 멈춥니다: {exc}", file=sys.stderr)
            return 1
        except DomeggookApiError as exc:
            print(f"  상세 {i//MAX_VIEW_BATCH+1}번째 묶음 실패: {exc}", file=sys.stderr)
            continue
        got = _view_items(payload)
        for item in got:
            no = str(((item.get("basis") or {}).get("no") or "")).strip()   # 함정 ②
            if no:
                details[no] = item
        print(f"  상세 {i+1}~{i+len(chunk)} → {len(got)}건")
    print(f"상세 {len(details)}건 · 도매꾹 호출 {dome.calls}회 · {time.time()-t0:.1f}s")

    # ── 인증번호 ────────────────────────────────────────────────────
    any_cert = 0
    gov_cert: dict[str, list[str]] = {}
    for no, item in details.items():
        if kc_numbers_from(item):
            any_cert += 1
        nums = gov_format_numbers(item)
        if nums:
            gov_cert[no] = nums
    pct = 100.0 * len(gov_cert) / max(1, len(details))
    print(f"인증번호(아무거나) {any_cert}건 · 국표원 형식 {len(gov_cert)}건 ({pct:.0f}%)")

    by_cat = Counter(category_of[no] for no in gov_cert)
    for _code, name in CATEGORIES:
        print(f"    {name:8} {by_cat.get(name, 0):3}")

    if dry_run:
        print("--dry-run - 국표원 조회·썸네일을 건너뜁니다")
        return 0

    # ── 국표원 조회 ─────────────────────────────────────────────────
    from sourcing_guard.config import settings

    kats = KatsClient(
        settings.kats_base_url, settings.kats_service_key, mock=settings.mock_mode
    )
    if kats._mock:  # noqa: SLF001 - 목 모드로 사본을 만들면 화면이 가짜를 말한다
        print("국표원이 목 모드입니다. 실키로 다시 돌리세요 (.env KATS_SERVICE_KEY)",
              file=sys.stderr)
        return 2

    # ⚠⚠ **번호를 전부 조회한다. 첫 번호만 보면 안 된다** (2026-09-20 실측).
    #
    #   처음에 `nums[0]` 만 조회했는데, 상품 48182475 는 번호가 셋이고
    #   **셋째가 '안전인증취소'** 였다. 첫 번호가 적합이라 미리 거르는 그물을
    #   그대로 통과했고, 스캔에 가서야 RED 로 걸렸다 - LLM 한 번을 헛썼고,
    #   무엇보다 사본의 `cert` 가 "이 상품의 인증상태" 인 것처럼 첫 번호만
    #   적고 있었다. 하나라도 취소면 그 상품은 뺀다.
    #
    #   CLAUDE.md §6 "가드를 만들 때 반대 방향도 한 줄로 재라" 의 또 한 번이다 -
    #   주석이 걱정한 것은 "취소를 화면에 올리는 것" 이었고, 실제 구멍은
    #   **번호가 여러 개일 때 첫 번호만 봤다** 였다.
    t1 = time.time()
    lookups = 0
    states: dict[str, list[dict]] = {}
    for no, nums in gov_cert.items():
        rows: list[dict] = []
        for num in nums:
            try:
                rec = kats.lookup_certification(num)
                lookups += 1
            except KatsApiError as exc:
                print(f"    조회 실패 {num}: {exc}")
                continue
            rows.append({
                "number": num,
                "found": rec is not None,
                "state": rec.state.value if rec else None,
                "status": rec.status if rec else None,
                "detail_url": rec.detail_url if rec else None,
            })
        if rows:
            states[no] = rows
    found = sum(1 for rows in states.values() for r in rows if r["found"])
    tally = Counter(r["state"] for rows in states.values() for r in rows if r["found"])
    print(f"국표원 {lookups}회 (상품 {len(states)}건) · 레코드 {found} · "
          f"없음 {lookups-found} · {time.time()-t1:.1f}s")
    for state, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"    {state:12} {n:3}")

    # ── 고르기 ──────────────────────────────────────────────────────
    #
    # 카테고리를 돌아가며 한 장씩 집는다. 한 카테고리가 목록을 덮으면 화면이
    # "블록 가게" 가 된다. 안에서는 도매꾹 랭킹순을 그대로 따른다.
    pool: dict[str, list[str]] = defaultdict(list)
    for no in sorted(states, key=lambda n: order_in_cat.get(n, 10**6)):
        rows = states[no]
        if not any(r["found"] for r in rows):
            continue
        bad = [r["state"] for r in rows if r["found"]
               and CertState(r["state"]) in EXCLUDED_STATES]
        if bad:
            drop_counts[f"인증상태 {bad[0]} 제외"] += 1
            continue
        if not (listing[no].get("thumb") or "").strip():
            drop_counts["썸네일 없음 제외"] += 1
            continue
        pool[category_of[no]].append(no)

    chosen: list[str] = []
    round_no = 0
    while len(chosen) < limit and any(len(v) > round_no for v in pool.values()):
        for _code, cat in CATEGORIES:
            bucket = pool.get(cat) or []
            if len(bucket) > round_no and len(chosen) < limit:
                chosen.append(bucket[round_no])
        round_no += 1
    print(f"고른 것 {len(chosen)}건 (뺀 것: {dict(drop_counts) or '없음'})")

    # ── 썸네일 ──────────────────────────────────────────────────────
    total_bytes = 0
    records: list[dict] = []
    with httpx.Client(follow_redirects=True) as http:
        for no in chosen:
            raw_detail = details[no]
            facts = facts_from_item(raw_detail)
            fact_dict = {
                "product_name": facts.product_name,
                "model_name": facts.model_name,
                "maker": facts.maker,
                "materials": list(facts.materials or []),
                "target_age": facts.target_age,
                "origin": clean((raw_detail.get("detail") or {}).get("country")),
            }
            certs = gov_cert[no]
            record = dict(listing[no])
            record["price"] = _as_int(record.get("price"))
            record["unitQty"] = _as_int(record.get("unitQty"))
            record["cert_numbers"] = certs
            record["certs"] = states[no]
            record["facts"] = {k: v for k, v in fact_dict.items() if v}
            record["page_text"] = page_text_of(fact_dict, certs)
            # ⚠ 개인정보 게이트를 **고르는 단계에서 먼저** 본다. 걸리는 줄을
            #   그냥 두면 `write_sanitized` 가 파일을 안 만들고 던져서
            #   수집 전체가 날아간다 - 한 상품만 빼고 계속 간다.
            left = residual_of(
                {k: v for k, v in record.items() if k != "thumb"}
            )
            if left:
                drop_counts["개인정보 패턴 제외"] += 1
                print(f"    개인정보 패턴으로 제외 {no}: {left}")
                continue
            thumb_file, size = save_thumb(record["thumb"], no, http)
            if not thumb_file:
                drop_counts["썸네일 내려받기 실패"] += 1
                continue
            record["thumb_file"] = thumb_file
            total_bytes += size
            records.append(record)

    print(f"썸네일 {len(records)}장 · {total_bytes/1024:.0f}KB")

    payload = {
        "_기록": (
            "도매꾹 상품 리스트 사본. `scripts/build_showcase.py collect` 가 만든다. "
            "손으로 고치지 않는다 - 고치면 화면이 도매꾹에 없는 상품을 말한다."
        ),
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": date.today().isoformat(),
        "categories": [name for _code, name in CATEGORIES],
        "surveyed": len(details),
        "with_gov_cert": len(gov_cert),
        "items": records,
    }
    counts = write_sanitized(OUT, payload)
    prune_thumbs(records)
    print(f"→ {dest} ({dest.stat().st_size:,} bytes)")
    print(f"   제거기록 {dict(sorted(counts.items()))}")

    _write_notes(
        details, listing, category_of, gov_cert, states, chosen, dome.calls, lookups,
        drop_counts,
    )
    return 0


def _write_notes(details, listing, category_of, gov_cert, states, chosen,
                 dome_calls: int, lookups: int, drop_counts) -> None:
    """실측 수를 사람이 읽는 표로 남긴다. **사본이 아니라 기록이다.**

    ⚠ 상품명은 적지 않는다 - 상호가 제목에 섞여 있고(실측), 기록은 수만
      있으면 된다.
    """
    out = NOTES_DIR / f"showcase_{date.today().isoformat()}"
    out.mkdir(parents=True, exist_ok=True)
    tally = Counter(r["state"] for rows in states.values() for r in rows if r["found"])
    by_cat = Counter(category_of[no] for no in gov_cert)
    lines = [
        f"# showcase 수집 {date.today().isoformat()}",
        "",
        "라벨: **도매꾹 랭킹순 상위 50 × 카테고리 8 · 수집일 기준 판매중 상품.**",
        "매칭률·정답률이 아니다.",
        "",
        f"    도매꾹 호출   {dome_calls}회",
        f"    국표원 호출   {lookups}회 (번호 기준. 상품은 {len(states)}건)",
        f"    상세          {len(details)}건",
        f"    국표원 형식   {len(gov_cert)}건 "
        f"({100.0*len(gov_cert)/max(1,len(details)):.0f}%)",
        f"    화면에 올림   {len(chosen)}건",
        "",
        "## 카테고리별 (국표원 형식 인증번호가 있는 것)",
        "",
    ]
    lines += [f"    {name:8} {by_cat.get(name, 0):3}" for _c, name in CATEGORIES]
    lines += ["", "## 인증상태 (**번호마다** 한 줄. 한 상품에 번호가 둘 이상일 수 있다)", ""]
    lines += [f"    {k:12} {v:3}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1])]
    lines += [
        "",
        "## 수집 단계에서 버린 것",
        "",
        "⚠ 첫 게이트(`sanitize_list_item`)가 목록 항목마다 버린 수다. 파일을",
        "  쓸 때의 제거기록(`showcase_제거기록.json`)과 **다른 층**이다 - 저쪽은",
        "  우리 값까지 포함한 카드 한 장 기준이다.",
        "",
    ]
    lines += [f"    {k:24} {v:5}" for k, v in sorted(drop_counts.items())]
    lines.append("")
    write_note(out / "README.md", lines,
               (f"화면에 올림   {len(chosen)}건", f"국표원 형식   {len(gov_cert)}건"))


# ── ② 스캔 ──────────────────────────────────────────────────────────
def scan(base: str, *, sleep: float = 6.0, only: set[str] | None = None,
         out: Path | None = None) -> int:
    """고른 상품을 `/api/v1/scan` 에 넣고 **응답 그대로** 사본에 붙인다.

    ⚠ 문장을 여기서 만들지 않는다 (R5 · CLAUDE.md §3 ③). 담기는 것은 우리
      서버가 실제로 낸 응답이다.

    ⚠⚠ **RED 가 나오면 화면에서 뺀다** (총괄 지시). 인증상태로 미리 걸렀지만
      리콜 일치는 스캔해 봐야 안다. 뺀 건수는 보고한다 - 0 이 아니면 그 사실이
      기록이다.

    `only` (부분 재기록 · 2026-09-22)
    ---------------------------------
    상품번호 몇 개만 다시 스캔하고 나머지는 **손대지 않는다.** 전량 재기록은
    국표원 조회를 29회 쓴다 - 고칠 카드가 여섯이면 그 비용이 근거 없다.

    ⚠⚠ 부분 재기록에서는 **인증 조회가 성공한 것만 사본에 넣는다.**
      `meta.gov_lookup.cert != "ok"` 면 스캔 자체는 200 을 돌려주지만 그 답은
      조회를 못 한 답이다 - 그걸 사본에 넣으면 화면이 조용히 덜 정확해진다
      (2026-09-08 사고와 같은 모양). 그런 카드는 **목록에서 뺀다.**

    ⚠ 그리고 **고르려던 것 중 첫 번째가 실패하면 통째로 멈춘다.** 죽은 서버에
      나머지 호출을 태우지 않는다 (총괄 2026-09-22). 사본은 한 글자도 안 바뀐다.
    """
    if not OUT.is_file():
        print(f"{OUT} 이 없습니다. 먼저 collect 를 돌리세요.", file=sys.stderr)
        return 2
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    items = payload.get("items") or []
    if not items:
        print("사본이 비어 있습니다", file=sys.stderr)
        return 2

    if only:
        missing = only - {str(it["no"]) for it in items}
        if missing:
            print(f"사본에 없는 상품번호입니다: {sorted(missing)}", file=sys.stderr)
            return 2

    kept: list[dict] = []
    red_rows: list[tuple[str, list[str], list[str]]] = []
    dropped_red = 0
    dropped_lookup: list[tuple[str, str]] = []
    rescanned: list[str] = []
    signals: Counter[str] = Counter()
    with httpx.Client(timeout=180.0) as client:
        for i, item in enumerate(items, 1):
            if only is not None and str(item["no"]) not in only:
                kept.append(item)          # 손대지 않는다
                continue
            t0 = time.time()
            r = client.post(base + "/api/v1/scan", json={"page_text": item["page_text"]})
            if r.status_code != 200:
                print(f"  FAIL {item['no']} HTTP {r.status_code} {r.text[:160]}",
                      file=sys.stderr)
                return 1
            body = r.json()
            sig = body.get("signal")
            meta = body.get("meta") or {}
            # ⚠ **추출 경로를 함께 찍는다.** LLM 이 죽어 휴리스틱으로 떨어져도
            #   스캔은 200 을 돌려준다 - 그 상태로 사본을 만들면 화면이 조용히
            #   덜 정확해진다 (2026-09-08 사고. CLAUDE.md R7).
            print(f'  {i:2}/{len(items)} {item["no"]:>10} {time.time()-t0:5.1f}s  '
                  f'{sig:8} {meta.get("extraction_path"):9} '
                  f'{(meta.get("gov_lookup") or {}).get("cert")}')
            cert_state = (meta.get("gov_lookup") or {}).get("cert")
            if only is not None and cert_state != "ok":
                # 조회를 못 한 답을 사본에 넣지 않는다.
                if not rescanned:
                    # 고르려던 것 중 **첫 번째**다. 서버가 죽었다고 보고 멈춘다.
                    print(f"      인증 조회 {cert_state!r} - 첫 카드부터 실패했습니다. "
                          "사본을 건드리지 않고 멈춥니다.", file=sys.stderr)
                    return 1
                print(f"      인증 조회 {cert_state!r} - 이 카드를 목록에서 뺍니다")
                dropped_lookup.append((str(item["no"]), str(cert_state)))
                continue
            rescanned.append(str(item["no"]))
            if sig == "RED":
                dropped_red += 1
                red_rows.append((item["no"], item.get("cert_numbers") or [],
                                 [f.get("kind") for f in body.get("findings") or []
                                  if f.get("signal") == "RED"]))
                print("      RED - 화면에서 뺍니다 (총괄 지시): "
                      f"{red_rows[-1][2]}")
            else:
                item["result"] = body
                signals[sig] += 1
                kept.append(item)
            # 호출 상한(IP당 분당 12회)에 걸리지 않게 여유를 둔다.
            time.sleep(sleep)

    payload["items"] = kept
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if only is None:
        payload["scanned_at"] = now
        payload["dropped_red"] = dropped_red
    else:
        # ⚠ `scanned_at` 을 덮지 않는다. 23장은 그때 것이고 6장만 지금 것이다 -
        #   하나로 적으면 23장의 조회 시각이 오늘로 둔갑한다 (R5).
        payload["rescanned"] = {"at": now, "items": rescanned,
                                "dropped_lookup": dropped_lookup,
                                "dropped_red": dropped_red}
        if dropped_lookup:
            payload.setdefault("뺀_상품", []).extend(
                {"no": no, "이유": f"인증 조회 {st} - 근거가 셀러 표기와 다른 번호를 "
                                   "가리켜, 판정을 다시 기록할 때까지 제외"}
                for no, st in dropped_lookup)
    # ⚠ `--out` 이면 **진짜 사본을 안 건드린다.** 덮기 전에 대조하려고 둔 길이다
    #   (`record_samples.py` 와 같은 패턴). 썸네일 정리도 그때는 안 한다 -
    #   사본과 썸네일이 갈리는 자리다.
    dest = out or OUT
    counts = write_sanitized(dest, payload)
    if out is None:
        prune_thumbs(kept)
    if out is None:
        _write_red_notes(red_rows)
    print(f"신호 {dict(signals)} · RED 로 뺀 것 {dropped_red}건"
          + (f" · 조회 실패로 뺀 것 {len(dropped_lookup)}건" if dropped_lookup else "")
          + (f" · 다시 기록한 것 {len(rescanned)}건 · 손대지 않은 것 "
             f"{len(kept) - len(rescanned)}건" if only is not None else ""))
    print(f"→ {dest} ({dest.stat().st_size:,} bytes)")
    print(f"   제거기록 {dict(sorted(counts.items()))}")
    return 0


# ── ③ 품목 붙음 실측 (LLM 0회) ───────────────────────────────────────
def screen_titles() -> int:
    """400건의 **상품명만**으로 배치 경로가 어떤 품목을 붙이는지 잰다.

    ⚠⚠ 미완 §1-u 의 증거를 만드는 자리다. 총괄이 배치 경로에서 실제 상품
      오매칭을 봤고(파우치 → 공기주입물놀이기구), **그때 만든 검사가 그것을
      못 잡았다** - "카테고리가 물놀이용품이 아닌데 「물놀이」가 붙으면 이상"
      으로 셌는데 그 상품은 카테고리가 물놀이용품이라 통과했다. 검사가
      카테고리를 믿은 것이다 (CLAUDE.md §6 "가드를 만들 때 반대 방향도 한 줄로
      재라").

      그래서 여기서는 **카테고리를 안 믿는다.** 붙은 품목 이름의 낱말이
      상품명에 실제로 있는지만 본다.

    ⚠ 상품명을 파일로 남기지 않는다 - 상호가 섞여 있다. 걸린 줄만 적는다.
    """
    _load_dotenv()
    key = os.getenv("DOMEGGOOK_API_KEY")
    if not key:
        print("DOMEGGOOK_API_KEY 가 없습니다 (.env)", file=sys.stderr)
        return 2
    from sourcing_guard.batch import screen
    from sourcing_guard.verifier import _grade_book

    book = _grade_book()
    if book is None:
        print("등급표를 못 읽었습니다", file=sys.stderr)
        return 2

    dome = DomeggookClient(key)
    titles: list[tuple[str, str]] = []   # (카테고리, 상품명)
    for code, name in CATEGORIES:
        try:
            payload = dome.search(ca=code, sz=PER_CATEGORY, so="rd")
        except DomeggookApiError as exc:
            print(f"  {name} 목록 실패: {exc}", file=sys.stderr)
            continue
        for raw in _list_items(payload):
            t = str(raw.get("title") or "").strip()
            if t:
                titles.append((name, t))
    print(f"상품명 {len(titles)}건 · 도매꾹 {dome.calls}회")

    report = screen("\n".join(t for _c, t in titles), book)
    rows = {r.line: r for r in report.rows}
    matched = sum(1 for r in report.rows if r.matched_items)
    print(f"품목이 붙은 줄 {matched}/{len(report.rows)}")

    # ── 「물놀이」 계열이 붙은 줄을 **전부** 내놓는다 ──────────────────
    #
    # ⚠⚠ **세는 것이 아니라 내놓는 것이다.** 오매칭인지 아닌지는 상품을 봐야
    #   알고, 그 판단은 총괄이 한다 (R5-b ③). 우리가 자동으로 세려고 만든
    #   규칙이 바로 §1-u 에서 틀린 그 규칙이다 - 처음에 "품목 이름의 낱말이
    #   상품명에 있으면 의심" 으로 셌더니 「놀이방매트 → 매트류」 같은
    #   **정상 매칭 40여 줄**이 걸렸다. 그물을 다시 만들지 않는다.
    #
    # ⚠ 카테고리는 **적기만 한다.** 거르는 데 쓰지 않는다 - 총괄의 검사가
    #   "카테고리가 물놀이용품이 아닌데 붙으면 이상" 으로 세어 실제 오매칭을
    #   놓쳤다 (미완 §1-u). 그 상품의 카테고리가 물놀이용품이었다.
    listed: list[str] = []
    for i, (cat, title) in enumerate(titles, start=1):
        row = rows.get(i)
        if not row or not row.matched_items:
            continue
        if not any(_WATCH_WORD in item for item in row.matched_items):
            continue
        listed.append(
            f"    [{cat}] {title[:70]}" + chr(10) + f"        → {row.matched_items}"
        )
    in_water_cat = sum(1 for line in listed if line.startswith("    [물놀이용품]"))
    print(f"「{_WATCH_WORD}」 계열 품목이 붙은 줄 {len(listed)}건 "
          f"(그중 카테고리가 물놀이용품 {in_water_cat}건)")
    for line in listed:
        print(line)

    out = NOTES_DIR / f"showcase_{date.today().isoformat()}" / "품목붙음.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = [
        f"# 상품명만으로 품목이 붙는가 ({date.today().isoformat()} · LLM 0회)",
        "",
        "라벨: **도매꾹 랭킹순 상위 50 × 카테고리 8 · 배치 경로(상품명만).**",
        "매칭률이지 정답률이 아니다 - 검수하지 않았다.",
        "",
        f"    상품명                  {len(titles)}건",
        f"    품목이 붙음              {matched}건",
        f"    「{_WATCH_WORD}」 계열이 붙음    {len(listed)}건",
        f"      그중 카테고리가 물놀이용품  {in_water_cat}건",
        "",
        f"## 「{_WATCH_WORD}」 계열 품목이 붙은 줄 (전부)",
        "",
        "⚠ **카테고리로 거르지 않았다.** 총괄이 만든 검사가 \"카테고리가",
        "  물놀이용품이 아닌데 「물놀이」가 붙으면 이상\" 으로 세어 실제",
        "  오매칭을 놓쳤다 - 그 상품의 카테고리가 물놀이용품이었다 (미완 §1-u).",
        "",
        "⚠ 오매칭 여부는 **적지 않았다.** 상품을 봐야 아는 판단이라 총괄이 한다",
        "  (R5-b ③).",
        "",
    ]
    body += listed
    body.append("")
    write_note(out, body, (f"「{_WATCH_WORD}」 계열이 붙음    {len(listed)}건",
                           f"품목이 붙음              {matched}건"))
    return 0


#: 미완 §1-u 가 이름을 찍은 낱말. **실측에서 나온 것 하나뿐이다** (R5 ·
#: 크레파스 원칙). 늘릴 때는 어느 실측에서 나왔는지 함께 적는다 - 여기에
#: 짐작으로 낱말을 더하면 그 목록 자체가 §1-u 가 경고한 그물이 된다.
_WATCH_WORD = "물놀이"


def prune_thumbs(records: list[dict]) -> int:
    """사본이 안 쓰는 썸네일을 지운다. **버려진 파일이 리포에 남지 않게.**

    ⚠ 실측에서 두 장이 남았다 (2026-09-20). collect 를 다시 돌리면 고른
      상품이 달라지고, scan 이 RED 를 빼면 그 상품 썸네일도 주인을 잃는다.
      공개 리포라 "왜 있는지 아무도 모르는 이미지" 를 두지 않는다.
    """
    if not THUMB_DIR.is_dir():
        return 0
    keep = {r["thumb_file"] for r in records if r.get("thumb_file")}
    gone = 0
    for path in THUMB_DIR.glob("*.webp"):
        if path.name not in keep:
            path.unlink()
            gone += 1
    if gone:
        print(f"주인 없는 썸네일 {gone}장을 지웠습니다")
    return gone


def _write_red_notes(red_rows) -> None:
    """화면에서 뺀 RED 를 **무엇 때문에 뺐는지**와 함께 남긴다.

    ⚠⚠ 화면이 "빨간불 상품은 없습니다" 라고 말하는 순간 그것은 주장이 된다.
      **무엇을 뺐는지 말할 수 없으면 그 주장은 감춘 것과 구별되지 않는다.**
      상품번호와 걸린 근거 종류만 적는다 - 상품명·판매자는 적지 않는다.
    """
    out = NOTES_DIR / f"showcase_{date.today().isoformat()}" / "RED_제외.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 화면에서 뺀 RED ({date.today().isoformat()})",
        "",
        "총괄 지시 [P4]: 리스트에 RED 상품을 두지 않는다. 인증상태로는 미리",
        "걸렀지만(`EXCLUDED_STATES`) **리콜 일치는 스캔해 봐야 안다.**",
        "",
        "⚠ 뺀 것은 감춘 것이 아니다 - 여기 남긴다. 화면이 \"RED 0건\" 이라고",
        "  말하는 근거가 이 파일이다.",
        "",
        f"    뺀 건수  {len(red_rows)}건",
        "",
    ]
    for no, certs, kinds in red_rows:
        lines.append(f"    {no:>10}  {','.join(certs) or '-':24} {kinds}")
    lines.append("")
    write_note(out, lines, (f"뺀 건수  {len(red_rows)}건",))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=("collect", "scan", "screen"))
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--base", default="http://127.0.0.1:8012")
    ap.add_argument("--sleep", type=float, default=6.0)
    ap.add_argument("--dry-run", action="store_true",
                    help="collect: 도매꾹만 부르고 국표원·썸네일은 건너뛴다")
    ap.add_argument("--only", default=None,
                    help="scan: 이 상품번호들만 다시 스캔한다(쉼표 구분). "
                         "나머지는 손대지 않는다. 전량은 국표원 조회 29회다")
    ap.add_argument("--out", default=None,
                    help="scan: 다른 파일로 내보낸다. 진짜 사본을 덮기 전에 "
                         "대조하려면 쓴다")
    args = ap.parse_args()
    stages = {
        "collect": lambda: collect(args.limit, dry_run=args.dry_run),
        "screen": screen_titles,
        "scan": lambda: scan(
            args.base, sleep=args.sleep,
            only={n.strip() for n in args.only.split(",") if n.strip()} if args.only else None,
            out=Path(args.out) if args.out else None),
    }
    code = stages[args.stage]()
    # ⚠ `SystemExit(None)` 은 **종료코드 0** 이다. 단계가 실수로 아무것도
    #   안 돌려주면 조용히 성공이 된다 - 실제로 그렇게 물렸다 (`write_note`).
    if not isinstance(code, int):
        raise RuntimeError(f"{args.stage} 단계가 종료코드를 안 돌려줬다: {code!r}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
