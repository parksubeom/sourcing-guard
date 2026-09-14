"""식약처 회수·판매중지(I0490) 응답을 **디스크에 닿기 전에** 줄인다.

왜 이 모듈이 있나
------------------
총괄 판단 (2026-09-14): `ADDR`(업소 주소) · `TELNO`(업소 전화)는 **제3자
사업자 정보**다. 우리는 모델명·상품명으로 대조하므로 이 둘을 쓰지 않는다.
쓰지 않는 개인정보는 **받는 즉시 버린다** — `.gitignore` 로 막는 것은
"커밋하지 않는다" 일 뿐 원문이 디스크에 남는 구조는 그대로다 (CLAUDE.md §6).

`IMG_FILE_PATH`(회수 이미지) · `LCNS_NO`(인허가번호)도 뺀다.

⚠⚠ **도매꾹과 반대 방향이다 — 여기는 남길 목록(allowlist)이다.**

    domeggook_pii   지울 것을 적는다. 목록에 없는 **새 필드는 남는다.**
    mfds_pii        남길 것을 적는다. 목록에 없는 **새 필드는 버려진다.**

  도매꾹은 우리가 쓰는 필드가 많고 구조가 깊어 지울 목록이 현실적이었다.
  식약처는 **우리가 쓰는 필드가 11개뿐**이라 남길 목록으로 쓸 수 있고,
  그러면 API 가 필드를 늘려도 기본이 "버린다" 가 된다. 지울 목록이었으면
  새 필드가 조용히 디스크에 눕는다.

남기는 필드 (총괄 지정 · 2026-09-14)
------------------------------------
    PRDTNM             제품명            ← 대조 대상
    BSSHNM             업소명            ← 화면 표시. 법인명이지 연락처가 아니다
    RTRVLPRVNS         회수 사유
    BRCDNO             바코드
    PRDLST_CD          품목 분류 코드
    PRDLST_CD_NM       품목 분류명
    RTRVL_GRDCD_NM     회수 등급
    CRET_DTM           등록일   ← ⚠ **공표일자가 아니다** (아래)
    RTRVLDSUSE_SEQ     회수 일련번호
    MNFDT              제조일자
    DISTBTMLMT         유통기한

빼는 필드
---------
    ADDR · TELNO           제3자 사업자 정보. 대조에 안 쓴다
    IMG_FILE_PATH          회수 이미지 경로
    LCNS_NO                인허가번호
    (그 밖의 모든 필드)     남길 목록에 없으면 버린다

⚠ **`CRET_DTM` 은 등록일이고 공표일자가 아니다** (총괄 확인). 화면 기준일을
  적을 때 "식약처 등록일 YYYY-MM-DD 기준" 이라고 쓴다. 국표원 리콜의
  공표일자와 같은 칸에 놓으면 안 된다 — 다른 뜻이다.

✅ **봉투를 봤다 (2026-09-14 20:51 KST · 실호출 4회 · 376건 전량).**

    행 경로   .I0490.row
    total     376
    행 필드   19개

  `rows_of()` 는 봉투 경로를 **가정하지 않고** 구조를 훑어 찾는다(만들 때는
  실호출 0회였다). 실측에서 `.I0490.row` 를 스스로 찾아냈다.

⚠⚠ **총괄 목록에 없던 필드가 4개 왔다.** 남길 목록이 자동으로 버렸다:

    FRMLCUNIT · PRDLST_REPORT_NO · PRDLST_TYPE · RTRVLPLANDOC_RTRVLMTHD

  **지울 목록이었으면 넷 다 디스크에 남았다.** 방향을 뒤집은 이유가 여기서
  실측으로 확인됐다. 넷 중 쓸 것이 있는지는 총괄이 정한다 - 우리가 목록을
  늘리지 않는다.

  남길 11개·일부러 버리는 4개는 **전부 실재**했다(19 = 11 + 4 + 4).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

#: 남기는 필드. **이 목록 밖은 전부 버린다.**
KEEP_FIELDS: tuple[str, ...] = (
    "PRDTNM",
    "BSSHNM",
    "RTRVLPRVNS",
    "BRCDNO",
    "PRDLST_CD",
    "PRDLST_CD_NM",
    "RTRVL_GRDCD_NM",
    "CRET_DTM",
    "RTRVLDSUSE_SEQ",
    "MNFDT",
    "DISTBTMLMT",
)

#: **이름을 알고 일부러 버리는** 것. 남길 목록에 없으면 어차피 버려지지만,
#: 이 셋은 총괄이 이름을 찍어 지시했으므로 따로 세서 사이드카에 적는다 -
#: "지웠다" 를 세지 않으면 지워졌는지 알 수 없다.
DROPPED_ON_PURPOSE: tuple[str, ...] = ("ADDR", "TELNO", "IMG_FILE_PATH", "LCNS_NO")

#: 자유 텍스트 필드. 잔존 검사는 **여기만** 본다.
#:
#: ⚠⚠ **코드·번호 필드를 검사에서 뺀 것이 핵심이다.** 바코드는 13자리 숫자고
#:   일련번호도 숫자다 - 전화번호 정규식을 거기 걸면 정상 값이 개인정보로
#:   읽혀 수집이 멈춘다. 도매꾹에서 인증번호 `YU101649-22001` 이 대표번호
#:   패턴에 걸렸던 것과 같은 자리다. 모양이 아니라 **자리**로 가린다.
_TEXT_FIELDS: frozenset[str] = frozenset(
    {"PRDTNM", "BSSHNM", "RTRVLPRVNS", "PRDLST_CD_NM", "RTRVL_GRDCD_NM"}
)

#: 행인지 알아보는 표지. 남기거나 일부러 버리는 이름이 하나라도 있으면 행이다.
_ROW_MARKERS: frozenset[str] = frozenset(KEEP_FIELDS) | frozenset(DROPPED_ON_PURPOSE)

# ── 잔존 패턴 ────────────────────────────────────────────────────────
#
# ⚠ 앞뒤 경계를 둔다. 도매꾹과 같은 이유다(숫자열 안에 박힌 조각을 전화번호로
#   읽는 사고).
_NOT_BEFORE = r"(?<![0-9A-Za-z\-])"
_NOT_AFTER = r"(?![0-9\-])"

_PHONE = re.compile(
    _NOT_BEFORE + r"(?:0\d{1,2}-\d{3,4}-\d{4}|1[568]\d{2}-\d{4})" + _NOT_AFTER
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: 주소. **세 토막을 요구한다** - 시도 + 시군구(1~2) + 로/길/읍/면/동/리.
#:
#: ⚠⚠ **실측 376건이 처음 판을 반증했다 (2026-09-14).** 처음엔
#:   `[가-힣]{2,4}도\s*[가-힣]+[시군구]` 였는데 **`황색포도상구균` 이 5건
#:   걸렸다** - `황색포도`(4자+도) + `상구`(구로 끝남). 모양으로 가린 자리다.
#:
#:   그래서 (1) 시도는 **닫힌 목록**으로, (2) 토막 사이에 **공백을 요구**하고,
#:   (3) 마지막에 로/길/읍/면/동/리를 요구한다. `전남 구례군 산수유` 같은
#:   원산지 표기는 두 토막이라 안 걸린다 - 그것은 개인정보가 아니다.
#:
#: ⚠⚠ **그물을 성기게 하지 않는다. 정확하게 한다.** 시도를 닫힌 목록으로
#:   바꾼 것은 **좁힌** 것이지 성기게 한 것이 아니다.
#:
#:   ⚠ 전에 이 자리에 "그물은 성길수록 오탐이 적다" 고 적혀 있었다. 고친
#:     것은 맞았는데 **적힌 이유가 그 수정과 달랐다** - 다음 사람이 그
#:     문장을 원칙으로 읽고 진짜로 성기게 만들면 개인정보가 샌다.
#:
#:   ⚠⚠ **방향도 뒤집혀 있었다.** "잔존이 걸리면 수집이 멈추니 오탐이
#:     비싸다" 고 적었는데 **놓치는 것이 멈추는 것보다 비싸다.** 멈추면
#:     사람이 30분 쓰고, 개인정보가 디스크에 닿으면 되돌릴 수 없다.
#:     CLAUDE.md §6 이 이미 "정제 뒤에도 패턴이 남으면 파일을 만들지 않고
#:     던진다" 로 못 박아 뒀다 - **멈추는 것은 비용이 아니라 설계다.**
#:
#: ⚠ `ADDR` 은 남길 목록 밖이라 애초에 안 들어온다. 이 그물은 **자유
#:   텍스트에 섞여 든 주소**만 잡는다.
_ADDR = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별시|광역시|특별자치시|특별자치도|특별자치|북도|남도|도)?\s+"
    r"(?:[가-힣]{1,6}[시군구]\s+){1,2}"
    r"[가-힣0-9]{1,10}(?:로|길|읍|면|동|리)\b"
)


def sanitize_row(row: dict, counts: dict[str, int]) -> dict:
    """행 하나. 남길 목록만 남긴 **새 dict** 를 돌려준다."""
    out = {k: row[k] for k in KEEP_FIELDS if k in row}
    for k in row:
        if k in out:
            continue
        label = f"{k} 제거" if k in DROPPED_ON_PURPOSE else "목록 밖 필드 제거"
        counts[label] = counts.get(label, 0) + 1
    return out


def looks_like_a_row(o: Any) -> bool:
    return isinstance(o, dict) and bool(_ROW_MARKERS & set(o))


def rows_of(payload: Any) -> tuple[list[dict], str]:
    """봉투 안에서 행 목록과 **그 경로**를 찾는다.

    ⚠ 경로를 가정하지 않는다 (R5 · 실호출 전이라 봉투를 못 봤다). 가장 많은
      행을 담은 목록을 고르고, 어디서 찾았는지 함께 돌려준다 - ⑦-b-3 에서
      그 값을 기록한다.
    """
    best: tuple[list[dict], str] = ([], "")

    def walk(o: Any, path: str) -> None:
        nonlocal best
        if isinstance(o, list):
            rows = [x for x in o if looks_like_a_row(x)]
            if len(rows) > len(best[0]):
                best = (rows, path or ".")
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}")

    walk(payload, "")
    if not best[0] and looks_like_a_row(payload):
        return [payload], "."
    return best


def sanitize(payload: Any, counts: dict[str, int] | None = None) -> tuple[dict, dict]:
    """응답 하나를 **우리 모양**으로 줄인다.

    ⚠⚠ **저쪽 봉투를 저장하지 않는다.** 봉투에는 우리가 안 본 필드가 있고,
      그것을 그대로 두면 남길 목록이 무의미해진다. 행만 뽑아 우리 그릇에
      담는다 - `{"출처": …, "행": [...]}`.
    """
    counts = {} if counts is None else counts
    rows, path = rows_of(payload)
    counts["행"] = counts.get("행", 0) + len(rows)
    clean = {
        "출처": "식약처 회수·판매중지 I0490",
        "행_경로": path,
        "남긴_필드": list(KEEP_FIELDS),
        "행": [sanitize_row(r, counts) for r in rows],
    }
    return clean, counts


def residual(clean: dict) -> list[str]:
    """정제 뒤에도 남은 것. 비어 있어야 한다.

    둘을 본다:
      ① 남길 목록 **밖의 키**가 행에 남았나 — allowlist 가 샌 것이다
      ② 자유 텍스트 안에 전화·이메일·주소 패턴이 있나 — 회수 사유에
         "문의 02-123-4567" 처럼 올 수 있다
    """
    found: list[str] = []
    for i, row in enumerate(clean.get("행") or []):
        if not isinstance(row, dict):
            found.append(f"행[{i}] 가 dict 가 아니다")
            continue
        for k in row:
            if k not in KEEP_FIELDS:
                found.append(f"행[{i}].{k} (남길 목록 밖)")
        for k in _TEXT_FIELDS & set(row):
            v = row[k]
            if not isinstance(v, str):
                continue
            for rx, name in ((_PHONE, "전화"), (_EMAIL, "이메일"), (_ADDR, "주소")):
                if rx.search(v):
                    found.append(f"행[{i}].{k} ({name})")
                    break
    return sorted(set(found))


class ResidualPiiError(RuntimeError):
    """정제 뒤에도 개인정보 패턴이 남았다. **저장하지 않는다.**

    ⚠ 고칠 곳은 저장 경로가 아니라 이 모듈의 남길 목록·치환이다.
    """

    def __init__(self, paths: list[str]) -> None:
        super().__init__(
            "정제 뒤에도 개인정보 패턴이 남아 저장을 멈췄습니다:\n  "
            + "\n  ".join(paths[:20])
            + ("\n  …" if len(paths) > 20 else "")
            + "\nsourcing_guard/mfds_pii.py 의 남길 목록을 고치세요."
        )
        self.paths = paths


def write_sanitized(path: Path, payload: Any) -> dict[str, int]:
    """**식약처 응답을 저장하는 유일한 경로다.**

    정제 → 잔존 검사 → 기록. 잔존이 있으면 **파일을 만들지 않고 던진다.**
    무엇을 몇 개 지웠는지 사이드카(`<파일명>.정제.json`)에 적는다.
    """
    clean, counts = sanitize(payload)
    left = residual(clean)
    if left:
        raise ResidualPiiError(left)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    # ⚠ 이름이 내용과 반대로 읽히면 안 된다 (2026-09-14 총괄 지적). 앞이
    #   **수집본**(남긴 11필드)이고 뒤가 **제거기록**(무엇을 지웠나)이다.
    #   전에는 `<파일>.정제.json` 이라 앞이 원문으로 읽혔다 - §6 은 "원문 응답은
    #   커밋에 넣지 않는다" 이고, 지키고 있는데 이름이 안 지킨 것처럼 보였다.
    side = path.with_name(path.stem + "_제거기록" + path.suffix)
    side.write_text(
        json.dumps(
            {
                "대상": path.name,
                "남긴_필드": list(KEEP_FIELDS),
                "이름_찍어_버린_필드": list(DROPPED_ON_PURPOSE),
                "건수": dict(sorted(counts.items())),
                "잔존": left,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return counts
