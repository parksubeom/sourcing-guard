"""도매꾹 응답에서 제3자 개인정보를 **디스크에 닿기 전에** 제거한다.

왜 이 모듈이 있나
------------------
2026-09-08 수집 100건에서 제3자 사업자·개인 정보가 나왔다. 전자상거래법
표시 의무로 상품 페이지에 공개된 정보이지만, **공개된 것과 우리 리포에 모아
두는 것은 다르다.** 제출용 저장소이고 한 번 커밋하면 git 히스토리에서
지우기 어렵다.

처음 조치는 `.gitignore` 였다. 그것은 "커밋하지 않는다" 일 뿐 **원문이
디스크에 남는 구조는 그대로**였다. 그래서 저장 경로 자체를 바꾼다 -
`write_sanitized()` 를 거치지 않으면 응답을 저장할 수 없다.

무엇을 어떻게 하나
------------------
| 처리 | 대상 |
|---|---|
| **제거** | `seller` 전체(`id`·`nick` 포함) · `return.addr` · `thumb` · `desc.license` |
| **치환** | `desc.contents.*` · `desc.notice` · `desc.comment[].memo` · `detail.infoDuty.item[].desc` 안의 사업자번호·전화·이메일 |
| **통째 치환** | A/S 책임자·연락처 고시항목의 `desc` |
| **손대지 않음** | `detail.safetyCert` — 인증번호다 |

⚠ **`detail.safetyCert` 를 치환 대상에 넣으면 안 된다.** 인증번호가 전화번호
  모양을 띤다. 실측 2건:

      YU101649-22001    ← '1649-2200' 이 대표번호 패턴에 걸린다
      HU071406-18008A   ← '1406-1800' 도 걸린다

  이 프로젝트에서 가장 중요한 필드를 마스킹하면 정상 인증이 "미조회" 가 된다
  (CLAUDE.md R3-b). 그래서 치환은 **위 표의 자유텍스트 필드에만** 건다.
  경계 조건(`_NOT_BEFORE`/`_NOT_AFTER`)도 이 사고를 막기 위한 것이다.

⚠ **남은 것이 있으면 저장하지 않고 던진다.** 위 목록은 우리가 본 100건에서
  나온 것이고, 새 필드에 개인정보가 오면 목록에 없다. `residual()` 이 정제
  결과 전체를 다시 훑어 패턴이 남아 있으면 경로를 들고 예외를 던진다 -
  조용히 디스크에 눕는 쪽보다 수집이 멈추는 쪽이 낫다.

실측 (2026-09-08 · 상세 100건)
------------------------------
    seller.company.cno     100/100 필드 존재 · 98/100 실제 번호 (2건은 '--')
    seller.company.boss     98/100
    seller.company.addr     98/100
    seller.company.phone   100/100 필드 존재 · 98/100 실제 번호
    seller.id              100/100 · seller.nick 90/100
    return.addr.address1   100/100   ← 반품 주소. 앞선 기록에 없던 곳이다
    return.addr.mobile      83/100
    return.addr.phone       60/100
    infoDuty.item[].desc     17/100 실제 전화번호
    desc(계) 전화번호         5/100
    desc(계) 사업자번호        0/100   ← 앞선 기록의 '84/100' 은 재현되지 않는다

⚠ 마지막 줄이 정정이다. `tests/fixtures/도매꾹_수집_2026-09-08/README.md` 와
  커밋 e1ffbcd 이 "desc HTML 안 사업자번호 84/100" 이라 적었는데, 같은 원문을
  다시 재면 하이픈 표기 사업자번호는 **0건**이다. desc 안 '사업자' 문자열은
  2건이고 그것도 `사업자회원전용` 이라는 도매꾹 UI 라벨이다. 84 라는 수가
  어느 계산에서 나왔는지 재구성하지 못했다 - 그래서 옛 수를 옮겨 적지 않고
  다시 잰 수를 쓴다.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .domeggook_fields import CONTACT_NAME_MARKERS, is_placeholder

# ── 패턴 ────────────────────────────────────────────────────────────
#
# ⚠ 앞뒤 경계를 둔다. 인증번호·이미지 ID 안에 박힌 숫자열을 전화번호로 읽는
#   사고를 막는 유일한 장치다(위 주석의 YU101649-22001).
_NOT_BEFORE = r"(?<![0-9A-Za-z\-])"
_NOT_AFTER = r"(?![0-9\-])"

_CNO = re.compile(_NOT_BEFORE + r"\d{3}-\d{2}-\d{5}" + _NOT_AFTER)
# 지역·휴대(0으로 시작) + 대표번호 15xx/16xx/18xx.
_PHONE = re.compile(
    _NOT_BEFORE + r"(?:0\d{1,2}-\d{3,4}-\d{4}|1[568]\d{2}-\d{4})" + _NOT_AFTER
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_TOKEN_CNO = "[사업자번호]"
_TOKEN_PHONE = "[전화]"
_TOKEN_EMAIL = "[이메일]"
_TOKEN_CONTACT = "[연락처]"

#: 치환 토큰 전부. 정제본을 읽는 쪽이 "이 줄은 원문이 아니다" 를 알아야 한다.
TOKENS: tuple[str, ...] = (_TOKEN_CNO, _TOKEN_PHONE, _TOKEN_EMAIL, _TOKEN_CONTACT)

# 연락처를 담는 고시 항목을 가리는 조각은 `domeggook_fields` 에 있다 -
# 측정 쪽도 같은 목록을 봐야 한다.

# residual() 이 건너뛰는 곳. 인증번호는 전화번호 모양일 수 있다.
_RESIDUAL_SKIP = (".detail.safetyCert",)


def _redact_text(s: str, counts: dict[str, int]) -> str:
    """자유텍스트 한 덩이. 치환 건수를 센다."""
    for rx, token, key in (
        (_CNO, _TOKEN_CNO, "사업자번호"),
        (_PHONE, _TOKEN_PHONE, "전화"),
        (_EMAIL, _TOKEN_EMAIL, "이메일"),
    ):
        s, n = rx.subn(token, s)
        if n:
            counts[key] = counts.get(key, 0) + n
    return s


def _redact_in_place(container: Any, key: Any, counts: dict[str, int]) -> None:
    v = container[key]
    if isinstance(v, str):
        container[key] = _redact_text(v, counts)


def _drop(container: dict, key: str, counts: dict[str, int], label: str) -> None:
    if key in container:
        del container[key]
        counts[label] = counts.get(label, 0) + 1


def sanitize_item(item: dict, counts: dict[str, int]) -> dict:
    """상품 하나. 원본을 바꾸지 않고 정제 사본을 돌려준다."""
    it = copy.deepcopy(item)

    _drop(it, "seller", counts, "seller 제거")
    _drop(it, "thumb", counts, "thumb 제거")
    if isinstance(it.get("return"), dict):
        _drop(it["return"], "addr", counts, "return.addr 제거")

    desc = it.get("desc")
    if isinstance(desc, dict):
        _drop(desc, "license", counts, "desc.license 제거")
        contents = desc.get("contents")
        if isinstance(contents, dict):
            for k in list(contents):
                _redact_in_place(contents, k, counts)
        elif isinstance(contents, str):
            _redact_in_place(desc, "contents", counts)
        _redact_in_place(desc, "notice", counts)
        comment = desc.get("comment")
        if isinstance(comment, dict):
            comment = [comment]
        for entry in comment or []:
            if isinstance(entry, dict) and "memo" in entry:
                _redact_in_place(entry, "memo", counts)

    detail = it.get("detail")
    if isinstance(detail, dict):
        info = detail.get("infoDuty")
        if isinstance(info, dict):
            rows = info.get("item")
            if isinstance(rows, dict):
                rows = [rows]
            for row in rows or []:
                if not isinstance(row, dict) or "desc" not in row:
                    continue
                name = str(row.get("name") or "")
                if any(m in name for m in CONTACT_NAME_MARKERS):
                    # 항목 자체가 연락처다. 패턴에 안 걸리는 표기(괄호·공백
                    # 변형·"담당자 김OO 010 1234 5678")도 있으므로 값을 통째로
                    # 바꾼다.
                    #
                    # ⚠ 단, "상세설명참조" 류는 **남긴다.** 연락처가 아니고,
                    #   A-5 가 세는 "채워져 있지만 내용은 없는" 비율이 이
                    #   값으로 결정된다. 통째로 [연락처] 로 덮으면 그 측정이
                    #   불가능해진다 - 개인정보를 지우는 것과 측정 신호를
                    #   지우는 것은 다르다.
                    if is_placeholder(row["desc"]):
                        counts["연락처항목 placeholder 유지"] = (
                            counts.get("연락처항목 placeholder 유지", 0) + 1
                        )
                    elif row["desc"] and row["desc"] != _TOKEN_CONTACT:
                        row["desc"] = _TOKEN_CONTACT
                        counts["연락처항목 치환"] = counts.get("연락처항목 치환", 0) + 1
                else:
                    _redact_in_place(row, "desc", counts)
    return it


def sanitize_list_item(item: dict, counts: dict[str, int]) -> dict:
    """검색 결과의 상품 한 줄.

    검색 응답에는 패턴에 걸리는 개인정보가 없었다(235건 0건). 다만
    `list.item.id` 는 **셀러 계정 ID** 이므로 `seller.id` 와 같은 성격이고,
    `thumb` 도 상세와 같이 뺀다. 우리가 쓰는 것은 `no` 와 `title` 이다.
    """
    it = copy.deepcopy(item)
    _drop(it, "id", counts, "list.item.id 제거")
    _drop(it, "thumb", counts, "list.item.thumb 제거")
    return it


def sanitize(payload: Any, counts: dict[str, int] | None = None) -> tuple[Any, dict]:
    """응답 하나(또는 응답들을 담은 구조)를 정제한다.

    `getItemView` · `getItemList` 응답 어느 쪽이든 받는다. 우리가 저장하는
    모양(`[{"query":…, "response":…}, …]`)도 그대로 받는다.
    """
    counts = {} if counts is None else counts

    if isinstance(payload, list):
        return [sanitize(p, counts)[0] for p in payload], counts
    if not isinstance(payload, dict):
        return payload, counts

    if "response" in payload or "nos" in payload or "query" in payload:
        out = dict(payload)
        if isinstance(out.get("response"), dict):
            out["response"] = sanitize(out["response"], counts)[0]
        return out, counts

    root = payload.get("domeggook")
    if not isinstance(root, dict):
        return copy.deepcopy(payload), counts

    out_root = dict(root)

    items = root.get("item")
    if isinstance(items, dict):
        out_root["item"] = sanitize_item(items, counts)
    elif isinstance(items, list):
        out_root["item"] = [
            sanitize_item(i, counts) if isinstance(i, dict) else i for i in items
        ]

    lst = root.get("list")
    if isinstance(lst, dict):
        rows = lst.get("item")
        new_lst = dict(lst)
        if isinstance(rows, dict):
            new_lst["item"] = sanitize_list_item(rows, counts)
        elif isinstance(rows, list):
            new_lst["item"] = [
                sanitize_list_item(r, counts) if isinstance(r, dict) else r
                for r in rows
            ]
        out_root["list"] = new_lst

    return {"domeggook": out_root}, counts


def residual(payload: Any) -> list[str]:
    """정제 뒤에도 패턴이 남은 경로. 비어 있어야 한다.

    ⚠ 이것이 "목록에 없는 새 필드" 를 잡는 장치다. 우리가 본 100건 밖에서
      개인정보가 오면 제거 목록에 없고, 그때 조용히 저장되지 않게 한다.
    """
    found: list[str] = []

    def walk(o: Any, path: str) -> None:
        if any(skip in path for skip in _RESIDUAL_SKIP):
            return
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for v in o:
                walk(v, f"{path}[]")
        elif isinstance(o, str):
            for rx, name in ((_CNO, "사업자번호"), (_PHONE, "전화"), (_EMAIL, "이메일")):
                if rx.search(o):
                    found.append(f"{path} ({name})")
                    break

    walk(payload, "")
    return sorted(set(found))


class ResidualPiiError(RuntimeError):
    """정제 뒤에도 개인정보 패턴이 남았다. **저장하지 않는다.**

    ⚠ 고칠 곳은 저장 경로가 아니라 `sanitize()` 의 제거·치환 목록이다.
      새 경로가 나왔으면 이 모듈 머리의 표에 적고 처리를 추가한다.
    """

    def __init__(self, paths: list[str]) -> None:
        super().__init__(
            "정제 뒤에도 개인정보 패턴이 남아 저장을 멈췄습니다:\n  "
            + "\n  ".join(paths[:20])
            + ("\n  …" if len(paths) > 20 else "")
            + "\nsourcing_guard/domeggook_pii.py 의 제거·치환 목록을 고치세요."
        )
        self.paths = paths


def write_sanitized(path: Path, payload: Any) -> dict[str, int]:
    """**도매꾹 응답을 저장하는 유일한 경로다.**

    정제 → 잔존 검사 → 기록. 잔존이 있으면 파일을 만들지 않고 던진다.
    치환 건수를 사이드카(`<파일명>.정제.json`)에 함께 적는다 - "무엇을 몇 개
    지웠나" 가 재현성의 일부다.
    """
    clean, counts = sanitize(payload)
    left = residual(clean)
    if left:
        raise ResidualPiiError(left)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    side = path.with_suffix(path.suffix + ".정제.json")
    side.write_text(
        json.dumps(
            {
                "대상": path.name,
                "치환_토큰": list(TOKENS),
                "건수": dict(sorted(counts.items())),
                "잔존": left,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return counts
