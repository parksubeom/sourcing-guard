#!/usr/bin/env python
"""[I] 전기용품 안전기준 고시의 **구조**를 확인한다. 조사용 · law.go.kr DRF.

묻는 것은 하나다: **조문을 인용할 수 있는가.**

`hazard_rules.yaml` 은 룰마다 `clause`(조항)와 `source_url` 을 요구한다 (R5 · §5).
어린이·생활용품은 고시 본문에 부속서가 있어 인용할 수 있는데, 전기용품에서는
안 된다는 것을 이 스크립트가 보여준다.

⚠ 실호출한다. 정기 실행이 아니라 **조사용 1회**다 - `law.go.kr` 은 R4 표에
  "자료 수집 경로" 로 승인돼 있다. 받은 목록은 픽스처로 남기므로 문서는
  네트워크 없이 검사된다.

    python scripts/probe_electrical_standards.py

⚠ `SG_LIVE_NET` 은 **pytest 안에서만** 의미가 있다(`tests/conftest.py` 의 §7
  네트워크 차단을 푸는 열쇠다). 스크립트를 직접 돌릴 때는 아무 효과가 없어
  전에 적어 두었던 `SG_LIVE_NET=1 ...` 는 **오해를 부르는 주문**이었다.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from sourcing_guard.allowed_hosts import ensure_allowed  # noqa: E402

SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL = "https://www.law.go.kr/DRF/lawService.do"
#: ⚠ 파일명 날짜는 **원자료 수집일**이다. 2026-09-13 에 전수로 다시
#:   받았으므로 09-12 판을 이 이름으로 옮겼다 (CLAUDE.md `--stamp` 교훈).
OUT = Path("tests/fixtures/전기용품_안전기준_고시_2026-09-13.json")

#: 대조군 — **우리 verified 21건이 실제로 나온 고시들**.
#:
#: ⚠⚠ 2026-09-13 정정. 전에 여기 「안전확인대상생활용품의 안전기준」 하나만
#:   적고 "우리 룰 21건이 이 고시의 부속서에서 나왔다" 고 썼는데 **틀렸다.**
#:   `hazard_rules.yaml` 을 `source_url` 로 세면:
#:
#:       17건  어린이제품 공통안전기준            (고시 제2022-220호 3.1.x)
#:        2건  공급자적합성확인대상생활용품의 안전기준  (부속서 9 속눈썹 열 성형기)
#:        2건  안전확인대상생활용품의 안전기준       (부속서 52 안전모 · 46 레이저)
#:
#:   대조군이 하나면 "저쪽은 되는데 이쪽은 안 된다" 의 '저쪽' 을 잘못 가리킨다.
#:   셋 다 받아 구조를 비교한다.
CONTROLS = (
    "어린이제품 공통안전기준",
    "공급자적합성확인대상 생활용품의 안전기준",
    "안전확인대상생활용품의 안전기준",
)


#: 조문 자리에 들어온 **안내문**. 조문이 아니다.
#:
#: ⚠⚠ 2026-09-13 실측: `조문내용` 이 비어 있지 않은 3건(KC 60335-2-17 ·
#:   KC 60884-1 · KC 62619)의 내용이 전부 이것이었다 -
#:   "「…」의 자세한 내용은 상단 메뉴 "<img …>"버튼을 이용하십시오." (75~80자)
#:
#:   그래서 "조문내용이 비었나" 만 세면 **71/74** 가 나오지만, "조문이 있나" 로
#:   세면 **0/74** 다. 후자가 우리가 묻는 것이다 - 인용할 조문이 있는가.
_BOILERPLATE = "자세한 내용은 상단 메뉴"


def _clause_text(body: object) -> str:
    """`조문내용` 을 문자열로. **모양이 고시마다 다르다** (R5).

    ⚠ 전기용품 74건은 전부 `str` 인데 생활용품 고시는 `list` 로 온다 -
      2026-09-13 에 `.strip()` 이 터져서 알았다. 받은 모양을 가정하지 않는다.
    """
    if isinstance(body, str):
        return body.strip()
    if isinstance(body, list):
        return " ".join(str(x) for x in body).strip()
    return str(body).strip() if body else ""


def _has_clause(body: object) -> bool:
    """조문 **본문**이 있는가. 빈값도, 첨부를 보라는 안내문도 아니어야 한다."""
    text = _clause_text(body)
    return bool(text) and _BOILERPLATE not in text


def _get(url: str, params: dict) -> dict:
    return _get_sized(url, params)[0]


def _get_sized(url: str, params: dict) -> tuple[dict, int]:
    """JSON 과 **응답 바이트 수**를 함께 돌려준다.

    ⚠ 바이트 수가 이 조사의 증거다 - 전기용품 고시는 2KB, 생활용품 고시는
      1.5MB 다. 크기 차이가 "조문이 본문에 있나" 를 한눈에 보여준다.
    """
    ensure_allowed(url)
    r = httpx.get(url, params=params, timeout=60.0)
    r.raise_for_status()
    return r.json(), len(r.content)


def main() -> None:
    DISPLAY = 100
    d = _get(SEARCH, {"OC": "test", "target": "admrul", "type": "JSON",
                      "query": "전기용품 안전기준", "display": str(DISPLAY), "page": "1"})
    root = d["AdmRulSearch"]
    rows = root["admrul"]
    # ⚠ 한 페이지에 다 안 들어오면 **조용히 잘린 목록으로 세게 된다.**
    total = int(root["totalCnt"])
    assert total <= DISPLAY, (
        f"검색 결과가 {total}건이라 display={DISPLAY} 로는 잘린다 - 페이지를 돌려라"
    )
    assert len(rows) == total, f"받은 행 {len(rows)} != totalCnt {total}"
    elec = [x for x in rows if x["행정규칙명"].startswith("전기용품 안전기준(")]
    print(f"검색 총건수 {root['totalCnt']} · 「전기용품 안전기준(…)」 {len(elec)}건")

    # 구조 대조 - 전기용품 한 건 vs **우리 룰이 실제로 나온 고시 셋**.
    print("\n무엇이 다른가 (같은 DRF · 같은 target)")
    print(f"{'고시':<44} {'JSON':>10} {'조문내용':>8} {'별표':>6} 첨부")
    for name in ("전기용품 안전기준(KC 60598-1)", *CONTROLS):
        hit = next((x for x in rows if x["행정규칙명"] == name), None)
        if hit is None:
            # 검색어가 "전기용품 안전기준" 이라 생활용품 고시는 결과에 없다.
            # 이름으로 다시 찾는다.
            found = _get(SEARCH, {"OC": "test", "target": "admrul", "type": "JSON",
                                  "query": name, "display": "20"})["AdmRulSearch"]
            cands = found.get("admrul") or []
            if isinstance(cands, dict):
                cands = [cands]
            hit = next((x for x in cands if x["행정규칙명"] == name), None)
            if hit is None:
                print(f"{name:<44} **못 찾음**")
                continue
        # ⚠ 여기도 `_get` 을 거친다 - 허용 호스트 검사를 우회하는 호출을 남기지
        #   않는다. 크기를 재야 해서 `_raw` 로 바이트도 함께 받는다.
        raw, size = _get_sized(DETAIL, {"OC": "test", "target": "admrul",
                                        "type": "JSON",
                                        "ID": hit["행정규칙일련번호"]})
        # ⚠ 래퍼를 벗긴다. 2026-09-13 에 이 한 줄을 빠뜨려 표가 **전부 "빈값"**
        #   으로 나왔다 - 앞서 단독으로 잰 값(1,569,120B · 조문 있음 · 별표 있음)
        #   과 어긋나서 알아챘다. 두 수가 안 맞으면 내 쪽을 먼저 의심한다.
        svc = raw.get("AdmRulService") or {}
        att = svc.get("첨부파일") or {}
        names = att.get("첨부파일명") if isinstance(att, dict) else att
        print(f"{name:<44} {size:>9,}B "
              f"{'있음' if _has_clause(svc.get('조문내용')) else '**없음**':>8} "
              f"{'있음' if svc.get('별표') else '없음':>6} "
              f"{names if isinstance(names, list) else names}")

    # ── 74건 **전수** — 1건으로 74건을 말하지 않는다 (정정 2) ──────────
    #
    # ⚠⚠ 2026-09-13 이전에는 `KC 60598-1` **한 건**을 받아 보고 "고시 74건의
    #   조문내용이 빈 문자열" 이라 적었다. **잰 것이 아니었다.** 전수로 센다.
    print(f"\n전수 조사 ({len(elec)}건) …", flush=True)
    detail: list[dict] = []
    for i, x in enumerate(elec, 1):
        svc, size = _get_sized(DETAIL, {"OC": "test", "target": "admrul",
                                        "type": "JSON",
                                        "ID": x["행정규칙일련번호"]})
        root_d = svc.get("AdmRulService") or {}
        att = root_d.get("첨부파일") or {}
        names = att.get("첨부파일명") if isinstance(att, dict) else att
        names = names if isinstance(names, list) else ([names] if names else [])
        detail.append({
            "이름": x["행정규칙명"],
            "일련번호": x["행정규칙일련번호"],
            "발령일자": x.get("발령일자"),
            "json_bytes": size,
            "조문내용_빔": not _clause_text(root_d.get("조문내용")),
            "조문내용_길이": len(_clause_text(root_d.get("조문내용"))),
            # ⚠ 이것이 우리가 묻는 것이다 - 인용할 조문이 있는가.
            "조문_있음": _has_clause(root_d.get("조문내용")),
            "별표_있음": bool(root_d.get("별표")),
            "첨부": names,
            "첨부_pdf": any(str(n).lower().endswith(".pdf") for n in names),
        })
        if i % 10 == 0 or i == len(elec):
            print(f"  {i}/{len(elec)}", flush=True)

    empty = sum(1 for d2 in detail if d2["조문내용_빔"])
    no_annex = sum(1 for d2 in detail if not d2["별표_있음"])
    with_pdf = sum(1 for d2 in detail if d2["첨부_pdf"])
    with_att = sum(1 for d2 in detail if d2["첨부"])
    with_clause = sum(1 for d2 in detail if d2["조문_있음"])
    n = len(detail)
    print(f"\n  (a) 조문내용이 **빈 문자열**인 건수  {empty}/{n}")
    print(f"  (b) 별표(부속서)가 없는 건수        {no_annex}/{n}")
    print(f"  (c) 첨부에 PDF 가 있는 건수          {with_pdf}/{n}   (첨부 자체는 {with_att}/{n})")
    print(f"  (d) **인용할 조문이 있는 건수**      {with_clause}/{n}   ← 우리가 묻는 것")
    for d2 in detail:
        if not d2["조문내용_빔"]:
            print(f"    · 빈값 아님: {d2['이름']} ({d2['조문내용_길이']}자) → "
                  f"조문 {'있음' if d2['조문_있음'] else '**아님 - 첨부 안내문**'}")
        if not d2["첨부_pdf"] and d2["첨부"]:
            print(f"    · PDF 아닌 첨부: {d2['이름']} → {d2['첨부']}")

    # ── 09-07 의 75 는 어떤 셈이었나 (정정 2 덤) ──────────────────────
    by_name = sum(1 for x in rows if "전기용품 안전기준" in x["행정규칙명"])
    print(f"\n  이름에 '전기용품 안전기준' 이 **포함**된 건수  {by_name}")
    print(f"  괄호형 「전기용품 안전기준(…)」 만                {len(elec)}")
    print("  → 09-07 의 75 가 '포함' 셈이면 맞는다: "
          f"{by_name} {'== 75 ✅' if by_name == 75 else '!= 75'}")

    OUT.write_text(json.dumps({
        "만든것": "scripts/probe_electrical_standards.py",
        "받은날": f"{date.today():%Y-%m-%d}",
        "원천": "law.go.kr DRF lawSearch.do · target=admrul · query='전기용품 안전기준' · OC=test",
        "총건수": root["totalCnt"],
        "전기용품_안전기준_건수": len(elec),
        "⚠": "제3자 개인정보 없음 - 법령 고시 목록이다. 도매꾹 응답과 달리 마스킹 대상이 아니다.",
        # ⚠ 제외한 6건이 무엇인지 문서만 말하지 않게 **검색 결과 전부**를 남긴다.
        "검색결과_전체": [{"이름": x["행정규칙명"], "발령일자": x.get("발령일자"),
                          "종류": x.get("행정규칙종류")} for x in rows],
        "이름에_포함된_건수": by_name,
        "전수조사": {
            "조문내용_빈_건수": empty,
            "별표_없는_건수": no_annex,
            "첨부_pdf_있는_건수": with_pdf,
            "첨부_있는_건수": with_att,
            # ⚠ 이것이 [I] 의 결론을 떠받치는 수다.
            "인용할_조문이_있는_건수": with_clause,
            "분모": n,
        },
        "고시": detail,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
