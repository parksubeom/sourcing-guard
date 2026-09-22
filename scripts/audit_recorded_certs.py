"""미리 만들어 둔 산출물에서 **적힌 번호 vs 근거 URL 의 번호**를 맞춘다.

    python -u scripts/audit_recorded_certs.py

왜 (총괄 2026-09-22)
--------------------
같은 날 우회가 **두 번** 났다:

    showcase.json   옛 `rows[0]` 로 기록된 사본이 `_pick_exact` 를 안 탄다
    cert_seed.json  옛 `rows[0]` 로 만든 시드가 캐시에서 조회를 끝낸다

둘 다 **코드를 고쳤는데 그 코드로 미리 만들어 둔 데이터는 안 고쳐진** 것이다.
그래서 남은 산출물을 전부 센다.

⚠ 실호출 0회. 파일 안에서 두 값을 맞춰 볼 뿐이다.
⚠ 구조가 파일마다 다르다. **`certNum=` 이 든 URL 을 통째로 훑고**, 같은 객체
  안에서 「적힌 번호」로 볼 만한 값을 찾는다 - 스키마를 가정하면 한 파일이
  조용히 빠진다 (그렇게 빠질 뻔했다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing_guard.kats_client import normalize_kc  # noqa: E402

#: 「적힌 값 vs 근거」로 재면 불일치인데 **괜찮은 것**. 이유를 같이 적는다 -
#: 이유 없이 목록에 든 항목은 다음 사람이 지운다 (총괄 2026-09-22).
KNOWN_OK = {
    ("sourcing_guard/data/showcase.json", "CB063R4501-0001A"):
        "certs[].detail_url — collect(9/20) 산출물. `scan` 이 안 건드리고 "
        "**화면에 안 나간다**(카드 키·단건 응답 모두 certs 없음). 재수집 때 사라진다",
    ("sourcing_guard/data/showcase.json", "CB064R2424-9001R"):
        "certs[].detail_url — collect(9/20) 산출물. `scan` 이 안 건드리고 "
        "**화면에 안 나간다**(카드 키·단건 응답 모두 certs 없음). 재수집 때 사라진다",
    ("sourcing_guard/data/cert_seed.json", "HU073506-24001A"):
        "9/19 시드 오염. `cert_seed.load_entries` 가 **싣지 않는다**(라이브 확인: "
        "loaded 24 · skipped 5). 시드를 다시 만들면 사라진다",
    ("sourcing_guard/data/cert_seed.json", "HU073519-24001A"):
        "9/19 시드 오염. `cert_seed.load_entries` 가 **싣지 않는다**(라이브 확인: "
        "loaded 24 · skipped 5). 시드를 다시 만들면 사라진다",
    ("sourcing_guard/data/cert_seed.json", "HU101339-24004B"):
        "9/19 시드 오염. `cert_seed.load_entries` 가 **싣지 않는다**(라이브 확인: "
        "loaded 24 · skipped 5). 시드를 다시 만들면 사라진다",
    ("sourcing_guard/data/cert_seed.json", "SU071354-12001ZZC"):
        "9/19 시드 오염. `cert_seed.load_entries` 가 **싣지 않는다**(라이브 확인: "
        "loaded 24 · skipped 5). 시드를 다시 만들면 사라진다",
    ("sourcing_guard/data/cert_seed.json", "YU101649-22001A"):
        "9/19 시드 오염. `cert_seed.load_entries` 가 **싣지 않는다**(라이브 확인: "
        "loaded 24 · skipped 5). 시드를 다시 만들면 사라진다",
    **{("tests/fixtures/도매꾹_AB_2026-09-08.json", n):
       "2026-09-08 **측정 기록**이다. 그때 코드(`rows[0]`)로 그때 잰 것이라 "
       "기록으로서는 정확하다 - 고치면 기록이 아니게 된다 (R5). 문제는 이 수를 "
       "**현재 성능으로 인용할 때**이고, 그 주의는 docs/E2_유효결과율_재생_"
       "2026-09-09.md · docs/H_구조필드_어댑터_2026-09-12.md 에 달았다"
       for n in ("HU073506-24001A", "HU073519-24001A", "HU101339-24004B",
                 "SU071354-12001ZZC", "YU101649-22001A")},
}

#: 「적힌 값」이 파일에 없어 그 질문으로는 못 재는 파일. 대신 **화면 번호 vs
#: 링크 번호**로 잰다 - 둘 다 화면에 나가는 값이고, 갈리면 그 자체가 결함이다.
_SHOWN_VS_LINK = (
    "sourcing_guard/data/compare_cut.json",
    "sourcing_guard/data/demo_amber_result.json",
)

TARGETS = [
    "sourcing_guard/data/showcase.json",
    "sourcing_guard/data/experience_samples.json",
    "sourcing_guard/data/cert_seed.json",
    "sourcing_guard/data/compare_cut.json",
    "sourcing_guard/data/demo_amber_result.json",
    "tests/fixtures/도매꾹_AB_2026-09-08.json",
    "tests/fixtures/도매꾹_AB_재생_수정후_2026-09-09.json",
]

#: 「셀러가 적은 번호」로 볼 만한 키. 파일마다 이름이 다르고 **리스트일 수 있다.**
_CLAIMED = ("cert_numbers", "kc_numbers", "cert_number", "kc_number", "certNum", "id")


def _cert_in(url: str) -> str | None:
    if "certNum=" not in (url or ""):
        return None
    got = parse_qs(urlsplit(url).query).get("certNum") or []
    return got[0].strip() if got and got[0].strip() else None


def _pick(node: dict) -> set[str]:
    for key in _CLAIMED:
        v = node.get(key)
        if isinstance(v, str) and v.strip():
            return {v.strip()}
        if isinstance(v, list):
            got = {x.strip() for x in v if isinstance(x, str) and x.strip()}
            if got:
                return got
    return set()


def _claimed_here(node: dict) -> set[str]:
    """자신 **과 직계 자식 dict** 에서 「적힌 번호」를 찾는다.

    ⚠⚠ 한 겹 아래를 안 보면 `facts` 와 `findings` 가 **형제**인 구조에서
      짝을 못 짓는다 - 도매꾹 AB 픽스처가 그 모양이고, 근거 URL 108개가
      통째로 안 잡혔다. 그때 출력은 「불일치 0」이었다. **못 잰 것을 깨끗한
      것으로 읽을 뻔했다** (§6 - 0개를 보고 통과하면 검사가 아니다).
    """
    got = _pick(node)
    if got:
        return got
    for v in node.values():
        if isinstance(v, dict):
            got = _pick(v)
            if got:
                return got
    return set()


def walk(node, claimed: frozenset[str], out: list):
    """근거 URL 을 만날 때마다 **바깥에서 내려온 「적힌 번호 집합」**과 짝짓는다.

    ⚠⚠ **가장 가까운 상위로 덮지 않는다.** 처음엔 그렇게 짰는데, 시드에서
      `entries[i].cert_number`(키)가 `record.cert_number`(담긴 것)로 덮여
      **담긴 것끼리 비교**하게 됐고 불일치가 0 으로 나왔다 - 실제로는 5건이다.
      재려는 것은 「셀러가 적은 것 vs 근거」이므로 바깥 것이 이긴다.

    ⚠ 집합으로 든다. 한 상품에 번호가 여럿일 수 있다(실측: 29장 중 1장).
    """
    if isinstance(node, dict):
        here = claimed or frozenset(_claimed_here(node))
        for k, v in node.items():
            if isinstance(v, str):
                got = _cert_in(v)
                if got:
                    out.append((here, got))
            else:
                walk(v, here, out)
    elif isinstance(node, list):
        for v in node:
            walk(v, claimed, out)


_CERT_IN_TEXT = __import__("re").compile(
    r"(?i)\b[A-Z]{1,2}\d{2,}[A-Z]?\d*-\d+[A-Z0-9]{0,4}\b")


def shown_vs_link(doc, out: list):
    """화면이 보여주는 번호와 링크의 certNum 이 같은가."""
    if isinstance(doc, dict):
        url = doc.get("source_url") or ""
        got = _cert_in(url)
        if got:
            txt = doc.get("statement_ko") or doc.get("text") or ""
            shown = _CERT_IN_TEXT.findall(txt)
            out.append((shown, got))
        for v in doc.values():
            shown_vs_link(v, out)
    elif isinstance(doc, list):
        for v in doc:
            shown_vs_link(v, out)


def main() -> int:
    total_pairs = total_bad = 0
    for rel in TARGETS:
        p = Path(rel)
        if not p.is_file():
            print(f"{rel:52s} 없음")
            continue
        doc = json.loads(p.read_text(encoding="utf-8"))
        pairs: list[tuple[str | None, str]] = []
        walk(doc, None, pairs)
        named = [(a, b) for a, b in pairs if a]
        bad = [(a, b) for a, b in named
               if normalize_kc(b) not in {normalize_kc(x) for x in a}
               and (rel, b) not in KNOWN_OK]
        excused = [(a, b) for a, b in named if (rel, b) in KNOWN_OK]
        total_pairs += len(named)
        total_bad += len(bad)
        tail = f" · 알려진 예외 {len({b for _, b in excused})}종" if excused else ""
        print(f"{rel:52s} 근거URL {len(pairs):4d} · 짝지어진 것 {len(named):4d} "
              f"· **불일치 {len(bad)}**{tail}")
        shown = sorted({(tuple(sorted(a)), b) for a, b in bad})
        for a, b in shown[:8]:
            claim = ", ".join(a) if len(a) > 1 else (a[0] if a else "?")
            print(f"      적힌 것 {claim!r:26s} → 근거 {b!r}")
        if len(shown) > 8:
            print(f"      … 그 밖 {len(shown) - 8}종")
    print()
    print("── 「적힌 값」이 없는 파일 — 화면 번호 vs 링크 번호로 잰다 ──")
    for rel in _SHOWN_VS_LINK:
        p = Path(rel)
        if not p.is_file():
            print(f"{rel:52s} 없음"); continue
        rows: list = []
        shown_vs_link(json.loads(p.read_text(encoding="utf-8")), rows)
        bad = [(s_, g) for s_, g in rows
               if not any(normalize_kc(x) == normalize_kc(g) for x in s_)]
        print(f"{rel:52s} 근거 {len(rows)} · **어긋남 {len(bad)}**")
        for s_, g in bad[:5]:
            print(f"      문장 속 {s_} · 링크 {g!r}")
        total_bad += len(bad)

    print(f"\n합계  짝지어진 것 {total_pairs} · 불일치 {total_bad}")
    print("⚠ 짝을 못 지은 근거 URL 은 위 각 줄의 (근거URL - 짝지어진 것) 이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
