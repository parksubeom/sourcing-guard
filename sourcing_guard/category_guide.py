"""[M-5] 카테고리 가이드 — 화면이 그릴 자료를 읽는다.

⚠⚠ **여기 숫자는 매칭률이고 정답률이 아니다.** 사람이 검수하지 않았다.
  71% 시절의 실수가 정확히 "매칭률을 정답률처럼 쓴 것" 이다 - 그래서 `LABEL`
  을 자료와 함께 내보내고, 화면이 그것을 반드시 그린다
  (`tests/test_guide.py` 가 잠근다).

⚠⚠ **`붙음 0` 은 "비대상" 이 아니다.** 우리가 못 붙인 것이지 의무가 없다는
  뜻이 아니다 - 그렇게 적는 순간 판정이 된다 (R3 · §9).

⚠ 자료는 `data/category_guide.tsv` 이고 `scripts/build_category_guide.py` 가
  만든다 (LLM 0 · 네트워크 0). 손으로 고치지 않는다 - 손으로 유지하는 목록은
  반드시 낡는다 (§6).

⚠ 이 모듈은 **판정하지 않는다.** 안내 축이고, 신호등·등급·다섯 숫자를
  건드리지 않는다 (미완 §1-d).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "data" / "category_guide.tsv"

#: 자료에 붙는 라벨. **화면이 반드시 그린다.**
LABEL = "매칭률 · 배치 경로 · 검수 없음 · 카테고리당 ≤100건 · 도매꾹 랭킹순"

COLUMNS = ("코드", "카테고리", "대분류", "상품수", "표본n", "붙음", "붙음%",
           "관찰된_품목", "관찰된_등급", "등급근거", "유해물질_부속서", "소관안내")


@dataclass(frozen=True)
class GuideRow:
    code: str
    category: str
    parent: str
    item_count: int
    sampled: int
    matched: int
    matched_pct: float
    items: str          # "의류(39); 휴대폰(2)"
    grades: str         # "안전기준준수(39); 공급자적합성확인(2)"
    grade_sources: str
    annexes: str
    jurisdictions: str

    @property
    def observed(self) -> bool:
        """이 카테고리에서 등급이 **하나라도** 붙었나.

        ⚠ 이름이 아니라 관찰이다. "이 카테고리는 대상/비대상" 을 우리가
          적는 것은 판정이다 (R5·R3).
        """
        return self.matched > 0

    def as_dict(self) -> dict:
        return {
            "code": self.code, "category": self.category, "parent": self.parent,
            "item_count": self.item_count, "sampled": self.sampled,
            "matched": self.matched, "matched_pct": self.matched_pct,
            "items": self.items, "grades": self.grades,
            "grade_sources": self.grade_sources, "annexes": self.annexes,
            "jurisdictions": self.jurisdictions, "observed": self.observed,
        }


def _int(v: str) -> int:
    try:
        return int(v)
    except ValueError:
        return 0


@lru_cache(maxsize=1)
def rows(path: Path | None = None) -> tuple[GuideRow, ...]:
    out: list[GuideRow] = []
    for line in (path or _PATH).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        c = line.split("\t")
        if len(c) < len(COLUMNS):
            c = c + [""] * (len(COLUMNS) - len(c))
        out.append(GuideRow(
            code=c[0], category=c[1], parent=c[2],
            item_count=_int(c[3]), sampled=_int(c[4]), matched=_int(c[5]),
            matched_pct=float(c[6] or 0), items=c[7], grades=c[8],
            grade_sources=c[9], annexes=c[10], jurisdictions=c[11],
        ))
    return tuple(out)


def summary() -> dict:
    """화면 머리에 그릴 수. **하드코딩 금지라 여기서 센다.**"""
    rs = rows()
    return {
        "label": LABEL,
        "categories": len(rs),
        "observed": sum(1 for r in rs if r.observed),
        "silent": sum(1 for r in rs if not r.observed),
        "titles": sum(r.sampled for r in rs),
        "with_annex": sum(1 for r in rs if r.annexes),
        "with_jurisdiction": sum(1 for r in rs if r.jurisdictions),
    }
