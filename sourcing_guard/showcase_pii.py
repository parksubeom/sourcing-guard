"""도매꾹 상품 리스트(showcase) 응답을 **디스크에 닿기 전에** 줄인다.

왜 이 모듈이 있나
------------------
총괄 지시 (2026-09-20 [P4] 할 일 ②): 총괄이 손으로 만든 JSON 은 결과가 맞지만
**코드로 강제된 것이 아니다.** CLAUDE.md §6 은 "수집 뒤 마스킹" 이 아니라
"디스크에 닿기 전에" 제거하라고 적는다.

⚠⚠ **`domeggook_pii` 가 아니라 `mfds_pii` 를 본보기로 삼는다 — 남길 목록이다.**

    domeggook_pii   지울 것을 적는다. 목록에 없는 **새 필드는 남는다.**
    mfds_pii        남길 것을 적는다. 목록에 없는 **새 필드는 버려진다.**
    showcase_pii    남길 것을 적는다. ← 여기

  CLAUDE.md §6: "쓰는 필드를 셀 수 있으면 남길 목록 쪽이 강하다." 카드가
  그리는 것은 **여섯 필드**뿐이라 셀 수 있다. 지울 목록이었으면 도매꾹이
  `getItemList` 에 필드를 하나 늘리는 날 그것이 조용히 리포에 눕는다 -
  식약처에서 실제로 그렇게 됐고(총괄 목록에 없던 필드 4개), 남길 목록이
  자동으로 버렸다.

남기는 필드 (총괄 지정 · 2026-09-20)
------------------------------------
    no        상품번호     ← 카드 키 · 상세 조회 키
    title     상품제목     ← 카드 제목 · 스캔 입력
    thumb     썸네일 URL   ← **받아서 우리가 서빙한다.** 아래 ⚠⚠
    url       상품 URL     ← "도매꾹에서 보기" 원문 링크
    price     가격
    unitQty   최소구매수량

⚠⚠ **`thumb` 는 게이트를 통과하지만 사본에는 남지 않는다.**
  도매꾹 약관이 "제공된 이미지를 다운로드 받아 … 이미지호스팅 서비스에
  저장하여 사용하시기 바랍니다" 라고 적는다. 그래서 hotlink 하지 않는다.
  **원본 URL 을 사본에 남기면 다음 사람이 그것을 `<img src>` 에 넣는다** -
  남기지 않는 것이 그 경로를 아예 없애는 방법이다. 받는 쪽
  (`scripts/build_showcase.py`)이 URL 을 쓰고, 화면에 나가는 기록에는
  우리가 저장한 파일 이름(`thumb_file`)만 적는다.

이름을 찍어 버리는 것
---------------------
    id        판매자 아이디    ← 총괄이 이름을 찍어 지시
    nick      판매자 닉네임
    seller    판매자 블록 전체 (`company.cno`·`boss`·`addr`·`phone`)

  남길 목록 밖이라 어차피 버려지지만 **세서 사이드카에 적는다** - "지웠다" 를
  세지 않으면 지워졌는지 알 수 없다 (CLAUDE.md §6).

⚠ **`detail.safetyCert` 는 마스킹 대상이 아니다** (CLAUDE.md R4). 인증번호가
  전화번호 모양을 띤다(`YU101649-22001`). 이 프로젝트에서 가장 중요한 필드를
  마스킹하면 정상 인증이 "미조회" 가 되어 R3-b 를 정면으로 어긴다. 그래서
  잔존 검사는 `_TEXT_KEYS` 에 적힌 **자리**만 본다 - 모양이 아니라 자리로
  가리는 것은 `mfds_pii` 와 같은 원칙이다.

우리가 덧붙이는 것
------------------
카드 한 장은 도매꾹에서 온 여섯 필드 + **우리가 만든 값**으로 이뤄진다.
우리 값도 목록에 없으면 버린다 - 그래야 "남길 목록" 이 한 겹이 아니다.

    thumb_file   우리가 저장한 썸네일 파일 이름 (200px webp)
    cert_numbers 국표원 형식 인증번호 (safetyCert + 고시 인증 항목에서 뽑은 것)
    cert         국표원 조회 결과 요약 (번호 · 상태 · 원문 링크)
    facts        상세의 구조화 필드 중 스캔 입력이 되는 것 (아래)
    page_text    위 facts 로 만든 스캔 입력 문자열
    result       `/api/v1/scan` 응답 그대로

⚠ `facts` 도 남길 목록이다 (`FACT_KEYS`). 상세 응답에는 A/S 전화번호가 든
  `infoDuty` 행이 있고(실측 17/100), 상세를 통째로 받아 텍스트로 만들면
  그 번호가 LLM 으로 나가고 사본에 눕는다. 우리가 쓰는 항목 이름은
  `domeggook_adapter` 가 이미 세어 뒀으므로 그 결과만 받는다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .mfds_pii import text_residual

#: 도매꾹 `getItemList` 항목에서 **남기는** 필드. 이 목록 밖은 전부 버린다.
KEEP_FIELDS: tuple[str, ...] = ("no", "title", "thumb", "url", "price", "unitQty")

#: **이름을 찍어 버리는** 것 (총괄 지시). 세서 사이드카에 적는다.
DROPPED_ON_PURPOSE: tuple[str, ...] = ("id", "nick", "seller")

#: 상세에서 스캔 입력으로 쓰는 값. `domeggook_adapter.facts_from_item` 이
#: 이미 고시 항목 이름을 가려서 뽑은 것만 받는다.
FACT_KEYS: tuple[str, ...] = (
    "product_name",
    "model_name",
    "maker",
    "materials",
    "target_age",
    "origin",
)

#: 우리가 덧붙이는 값 중 사본에 남는 것.
#:
#: ⚠ `thumb` 는 여기 없다 - 머리 주석의 hotlink 절 참조. 게이트는 통과하되
#:   기록에는 안 남긴다.
OWN_KEYS: tuple[str, ...] = (
    "thumb_file",
    "cert_numbers",
    "cert",
    "facts",
    "page_text",
    "result",
)

#: 잔존 검사가 보는 **자리**. 모양이 아니라 자리로 가린다.
#:
#: ⚠⚠ `cert_numbers` · `no` · `url` · `thumb_file` 은 **일부러 뺐다.**
#:   인증번호가 전화번호 모양이고(`YU101649-22001`), 상품번호는 숫자열이며
#:   URL 에는 하이픈 숫자가 섞인다. 거기에 전화번호 그물을 걸면 정상 값이
#:   개인정보로 읽혀 수집이 멈춘다 (`mfds_pii._TEXT_FIELDS` 와 같은 자리).
_TEXT_KEYS: frozenset[str] = frozenset({
    "title", "page_text", "product_name", "model_name", "maker",
    "target_age", "origin", "materials",
})


class ResidualPiiError(RuntimeError):
    """정제 뒤에도 개인정보 패턴이 남았다. **저장하지 않는다.**

    ⚠ 고칠 곳은 저장 경로가 아니라 이 모듈의 남길 목록이다. 부르는 쪽이
      한 상품만 버리고 계속 갈 수도 있다 - `residual_of` 를 먼저 불러
      걸리는 상품을 세고 빼면 된다. 다만 **쓰는 순간에는 예외 없이 던진다.**
    """

    def __init__(self, paths: list[str]) -> None:
        super().__init__(
            "정제 뒤에도 개인정보 패턴이 남아 저장을 멈췄습니다:\n  "
            + "\n  ".join(paths[:20])
            + ("\n  …" if len(paths) > 20 else "")
            + "\nsourcing_guard/showcase_pii.py 의 남길 목록을 고치세요."
        )
        self.paths = paths


def sanitize_list_item(item: dict, counts: dict[str, int] | None = None) -> dict:
    """`getItemList` 항목 하나 → 남길 목록만 담은 **새 dict**.

    ⚠ 원본을 고치지 않는다. 새 dict 를 만드는 것이 "목록 밖은 애초에 안
      옮긴다" 를 구조로 강제하는 방법이다.
    """
    counts = {} if counts is None else counts
    out = {k: item[k] for k in KEEP_FIELDS if k in item}
    for k in item:
        if k in out:
            continue
        label = f"{k} 제거" if k in DROPPED_ON_PURPOSE else "목록 밖 필드 제거"
        counts[label] = counts.get(label, 0) + 1
    return out


def sanitize_facts(facts: dict, counts: dict[str, int] | None = None) -> dict:
    """상세에서 뽑은 값 → `FACT_KEYS` 만."""
    counts = {} if counts is None else counts
    out = {k: facts[k] for k in FACT_KEYS if k in facts and facts[k] not in (None, [], "")}
    for k in facts:
        if k not in FACT_KEYS:
            counts["facts 목록 밖 필드 제거"] = counts.get("facts 목록 밖 필드 제거", 0) + 1
    return out


def sanitize_record(record: dict, counts: dict[str, int] | None = None) -> dict:
    """카드 한 장. 도매꾹 다섯 필드 + 우리 값, **둘 다 남길 목록**을 거친다.

    ⚠ `thumb` 는 여기서 떨어진다 (머리 주석). 받는 쪽이 이미 썼고, 사본에
      남기면 화면이 hotlink 할 길이 생긴다. 떨어뜨린 것도 **센다.**

    ⚠ `sanitize_list_item` 을 여기서 다시 부르지 않는다 - 그러면 우리 값
      (`result`·`facts`)이 전부 "목록 밖" 으로 세어져 제거기록이 거짓이 된다.
    """
    counts = {} if counts is None else counts
    keep = [k for k in KEEP_FIELDS if k != "thumb"] + list(OWN_KEYS)
    out: dict[str, Any] = {}
    for k in keep:
        if k not in record:
            continue
        out[k] = sanitize_facts(record[k], counts) if k == "facts" else record[k]
    for k in record:
        if k in out:
            continue
        if k == "thumb":
            label = "thumb 원본 URL 제거"
        elif k in DROPPED_ON_PURPOSE:
            label = f"{k} 제거"
        else:
            label = "목록 밖 필드 제거"
        counts[label] = counts.get(label, 0) + 1
    return out


def _walk_strings(node: Any, path: str, key: str | None, out: list[tuple[str, str, str]]) -> None:
    """(경로, 키, 값) 을 훑는다. **자리 이름을 함께 들고 다닌다.**"""
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_strings(v, f"{path}.{k}", k, out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk_strings(v, f"{path}[{i}]", key, out)
    elif isinstance(node, str) and key is not None:
        out.append((path, key, node))


def residual_of(record: dict) -> list[str]:
    """카드 한 장에 남은 것. 비어 있어야 한다.

    둘을 본다:
      ① 남길 목록 **밖의 키**가 남았나 — allowlist 가 샌 것이다
      ② `_TEXT_KEYS` 자리의 문자열에 전화·이메일·주소 패턴이 있나

    ⚠ 패턴은 여기서 다시 쓰지 않는다. 소유자는 `mfds_pii.text_residual` 이다
      (CLAUDE.md §6 - 같은 판단을 두 곳에 적지 마라).
    """
    found: list[str] = []
    allowed = set(KEEP_FIELDS) | set(OWN_KEYS)
    allowed.discard("thumb")
    for k in record:
        if k not in allowed:
            found.append(f"{k} (남길 목록 밖)")
    rows: list[tuple[str, str, str]] = []
    _walk_strings(record, "", None, rows)
    for path, key, value in rows:
        if key not in _TEXT_KEYS:
            continue
        name = text_residual(value)
        if name:
            found.append(f"{path} ({name})")
    return sorted(set(found))


def write_sanitized(path: Path, payload: dict) -> dict[str, int]:
    """**도매꾹 상품 리스트를 저장하는 유일한 경로다.**

    정제 → 잔존 검사 → 기록. 잔존이 있으면 **파일을 만들지 않고 던진다.**
    무엇을 몇 개 지웠는지 사이드카(`<파일명>_제거기록.json`)에 적는다.

    ⚠ 사이드카 이름은 `mfds_pii` 와 같은 규칙이다 - 앞이 수집본, 뒤가
      제거기록. 반대로 읽히면 원문을 커밋한 것처럼 보인다.
    """
    counts: dict[str, int] = {}
    items = [sanitize_record(r, counts) for r in payload.get("items") or []]
    counts["상품"] = len(items)
    clean = {k: v for k, v in payload.items() if k != "items"}
    clean["남긴_필드"] = list(KEEP_FIELDS)
    clean["items"] = items

    left = sorted({f"items[{i}] {m}" for i, r in enumerate(items) for m in residual_of(r)})
    if left:
        raise ResidualPiiError(left)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(clean, ensure_ascii=False, indent=1) + "\n")
    side = path.with_name(path.stem + "_제거기록" + path.suffix)
    with side.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(
            {
                "대상": path.name,
                "남긴_필드": list(KEEP_FIELDS),
                "우리가_덧붙인_필드": list(OWN_KEYS),
                "이름_찍어_버린_필드": list(DROPPED_ON_PURPOSE),
                "건수": dict(sorted(counts.items())),
                "잔존": left,
            },
            ensure_ascii=False,
            indent=1,
        ) + "\n")
    return counts
