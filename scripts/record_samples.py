"""체험 표본 기록본을 만든다 — 우리가 실제로 낸 결과를 그대로 얼린다.

왜 기록본인가 (총괄 판정 2026-09-19 §2)
--------------------------------------
표본 버튼을 면제 지문으로 늘리면 투표 18일 × 공개 접근 × 10개 = **뚜껑 없는
비용**이다. 그리고 투표자의 첫 10초에 LLM 6초 대기가 붙는다.

그래서 랜딩 미리보기와 같은 방식으로 간다 - **실측 1회를 파일로 두고 그린다.**
화면에는 "지금 다시 검사" 가 함께 있고, 그것은 면제가 아닌 **일반 예산 안의**
`/api/v1/scan` 을 부른다.

⚠ **값을 지어내지 않는다** (R5). 여기 담기는 것은 우리 서버가 실제로 낸
  응답 그대로다. 문구를 손으로 고치면 화면이 없는 문장을 말한다.

표본 고르기 (총괄 §3)
--------------------
**기간만료 3 · 안전인증취소 2 를 반드시 넣는다.** 인증번호가 버젓이 적힌 실제
도매 상품인데 인증이 만료·취소된 것 - 인증번호만 보는 셀러가 놓치는 자리이고,
이 제품이 존재하는 이유다. 적합만 늘어놓으면 "잘 되네" 로 끝난다.

순서는 **적합 → 만료 → 취소**. 첫 카드가 빨강이면 "겁주는 서비스" 로 읽힌다.

⚠ 상호·공급사명은 한 글자도 안 나간다. 상품명 앞머리의 `[상호]` 꼴을 뗀다
  (`tests/test_experience_samples.py` 가 잠근다).

쓰는 법
-------
    # 실모드로 앱을 띄운다 (LLM·국표원 실호출이 나간다 - 측정이다)
    PYTHONUTF8=1 MOCK_MODE=false SYNC_ENABLED=false \
        python -m uvicorn sourcing_guard.main:app --port 8012

    PYTHONUTF8=1 PYTHONPATH=. python -u scripts/record_samples.py \
        --base http://127.0.0.1:8012
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "sourcing_guard" / "data" / "experience_samples.json"
_SAMPLES = (
    _ROOT / "tests/fixtures/도매꾹_정제_2026-09-08/상세.json",
    _ROOT / "tests/fixtures/도매꾹_확장_2026-09-08/상세_확장.json",
)

#: 고른 열 개. **순서가 화면 순서다** - 적합 → 만료 → 취소.
#:
#: ⚠ 번호는 `data/cert_seed.json` 에 있어야 한다. 시드에 없는 번호를 표본에
#:   넣으면 재배포 뒤 국표원이 죽어 있을 때 그 카드만 "조회 실패" 가 된다.
#:   `tests/test_experience_samples.py` 가 대조한다.
#:
#: ⚠ 첫 카드는 **초록불이 나오는 것**으로 둔다. 적합 다섯을 전부 전기용품으로
#:   고르면 유해물질 축이 미수록이라 신호가 전부 UNKNOWN 이 되고, 화면이
#:   "모름투성이" 로 읽힌다 - 고치려던 바로 그 인상이다 (총괄 §2 (3)).
#:   어린이제품은 공통안전기준이 수록돼 있어 세 축이 다 답한다.
CHOSEN: tuple[str, ...] = (
    # 적합 5 — 품목을 흩는다
    "CB063R10777-3001",   # 봉제인형 (완구) · GREEN 이 나오는 유일한 적합 표본
    "CB025H0054-4001",    # 놀이방매트 (합성수지제 어린이용품)
    "HU101339-24004",     # PD 충전기 (직류전원장치)
    "XH070736-23002A",    # USB 전기방석 (전기방석)
    "YU102043-24001",     # 무선 차량용 청소기 (전지)
    # 기간만료 3 — '반납' 도 행정 사유라 같은 갈래다 (R3-b)
    "B362R241-8002A",     # 12색 블럭 색연필 (완구)
    "CA011R017-7001",     # 아동 물놀이 튜브 (어린이용물놀이기구)
    "SU071354-12001",     # 전기주전자 (반납)
    # 안전인증취소 2 — 이 둘이 제품의 이유다
    "CA011R021-4001",     # 물놀이 튜브
    "HU072693-20003J",    # 전기 그릴
)

#: 상품명 앞머리의 `[상호]` · `(상호)` 꼴. 홍보 문구인지 상호인지 자동으로
#: 가를 수 없으므로 **앞머리 괄호 묶음은 전부 뗀다** - 남기는 쪽이 위험하다.
_SHOP_PREFIX = re.compile(r"^\s*(?:[\[(（【][^\])）】]{0,20}[\])）】]\s*)+")


def _titles() -> dict[str, str]:
    """정제본에서 인증번호 → 상품명. ⚠ 정제본만 읽는다 (R4)."""
    found: dict[str, str] = {}
    for path in _SAMPLES:
        blocks = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(blocks, dict):
            blocks = [blocks]
        for block in blocks:
            items = block["response"]["domeggook"]["item"]
            if isinstance(items, dict):
                items = [items]
            for item in items:
                for cert in (item.get("detail") or {}).get("safetyCert") or []:
                    if not isinstance(cert, dict):
                        continue
                    no = (cert.get("no") or "").strip().upper()
                    if no and no != "-":
                        found.setdefault(no, (item["basis"]["title"] or "").strip())
    return found


def clean_title(raw: str) -> str:
    return _SHOP_PREFIX.sub("", raw).strip()


def sample_text(title: str, cert_number: str) -> str:
    """셀러가 붙여넣는 모양. 상품명 + 인증번호."""
    return f"{title} KC 인증번호 {cert_number}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8012")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    titles = _titles()
    seed = {r["cert_number"] for r in json.loads(
        (_ROOT / "sourcing_guard/data/cert_seed.json").read_text(encoding="utf-8")
    )["entries"]}

    plan = []
    for num in CHOSEN:
        raw = titles.get(num)
        if raw is None:
            print(f"표본에 쓸 상품명을 못 찾았다: {num}", file=sys.stderr)
            return 2
        if num not in seed:
            print(f"시드에 없는 번호다: {num}", file=sys.stderr)
            return 2
        title = clean_title(raw)
        plan.append({"cert_number": num, "title": title,
                     "text": sample_text(title, num), "raw_title": raw})

    for p in plan:
        mark = " ←접두제거" if p["title"] != p["raw_title"] else ""
        print(f'  {p["cert_number"]:18} {p["title"][:56]}{mark}')
    if args.dry_run:
        return 0

    out = []
    with httpx.Client(timeout=120.0) as client:
        for i, p in enumerate(plan, 1):
            t0 = time.time()
            r = client.post(args.base + "/api/v1/scan",
                            json={"page_text": p["text"]})
            if r.status_code != 200:
                print(f"  FAIL {p['cert_number']} HTTP {r.status_code} {r.text[:160]}")
                return 1
            body = r.json()
            out.append({
                "cert_number": p["cert_number"],
                "title": p["title"],
                "text": p["text"],
                "result": body,
            })
            print(f'  {i:2}/{len(plan)} {p["cert_number"]:18} {time.time()-t0:5.1f}s  '
                  f'{body["signal"]:8} {body["meta"].get("gov_lookup", {}).get("cert")}')
            # IP당 분당 12회 제한이 있다. 여유를 둔다.
            time.sleep(6)

    payload = {
        "_기록": (
            "체험 표본 기록본. `scripts/record_samples.py` 가 실제 /api/v1/scan "
            "응답을 그대로 담는다. 손으로 고치지 않는다 - 고치면 화면이 없는 "
            "문장을 말한다."
        ),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": out,
    }
    with _OUT.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print(f"→ {_OUT} ({_OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
