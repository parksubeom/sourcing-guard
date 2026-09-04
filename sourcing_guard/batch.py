"""대량 검사 - 상품명 여러 줄을 한 번에 스크리닝한다.

셀러는 상품을 하나씩 보고 등록하지 않는다. 도매매·온채널에서 **200개 단위로
엑셀을 다운로드**해 전송 프로그램으로 오픈마켓에 일괄 업로드한다. 하루 600개를
올리는 사례도 있다. 한 건씩 붙여넣는 화면은 그 작업 흐름과 어긋난다.

그래서 상품명을 여러 줄 받아 한 번에 판정한다. 셀러가 엑셀에서 상품명 열을
복사해 붙이면 그것이 곧 200줄이다 - 엑셀 파싱 없이도 실사용이 된다.

**LLM 예산이 이 기능의 제약이다.** 일일 상한이 500회인데 200건을 전건 LLM 에
보내면 한 번에 40% 를 쓴다. 그래서 두 단계로 나눈다:

    1단계  상품명만으로 판단 가능한 것을 걸러낸다 (LLM 0회, 로컬 조회)
    2단계  남은 것만 LLM 에 보낸다

실측(도매꾹 실상품 200건): 144건이 1단계에서 등급 확정 -> LLM 72% 절감.

⚠ 배치는 상품명만 본다. 상세페이지가 없으니 재질·연령을 알 수 없고, 유해물질
   기준과 리콜 모델명 매칭이 약해진다. 그래서 배치 결과는 **1차 선별**이고,
   RED·AMBER 로 걸러진 것을 단건 검사로 다시 보는 흐름이다. 이 한계를 결과에
   명시한다 (R3 - 안 본 것을 봤다고 말하지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .item_grades import ItemGrade, ItemGradeBook
from .kats_client import CERT_NUMBER_RE
from .models import Signal
from .rra_client import extract_rf_numbers

# 한 번에 받는 상한.
#
# ⚠ 처음 200 으로 둔 근거("도매매·온채널 엑셀 다운로드 상한 200개")는
#   조작된 조사 보고에서 온 것이라 2026-09-04 에 철회됐다. 다시 쟀다.
#
# 실측(도매꾹 실상품을 반복해 만든 입력, 줄당 평균 41자):
#
#     줄 수   처리시간   줄당      응답 크기
#      200     164ms   0.82ms     94 KB
#      500     409ms   0.82ms    233 KB
#     1000    1136ms   1.14ms    465 KB
#     2000    1666ms   0.83ms    931 KB
#
# 처리 시간은 선형이고 줄당 0.82ms 다 - LLM 을 안 쓰므로 병목이 없다.
# 상한을 정하는 것은 처리 시간이 아니라 **입력 상한과 화면**이다.
#
#   입력  BatchRequest.text 가 60,000자다. 이 표본 기준 약 1,450줄에서
#         막힌다. 상품명이 길면(도매 상품명은 100자를 넘기도 한다) 600줄에서
#         막힐 수도 있다.
#   화면  500줄이면 결과 카드가 500개다. 판정별로 접어서 그리지만 펼치면
#         그만큼 DOM 이 생긴다. 가상 스크롤 없이 감당하는 선을 500 으로 둔다.
#
# 그래서 500 이다. 1000 도 시간(1.1초)은 되지만 응답이 465KB 이고 화면이
# 무거워진다. 셀러가 실제로 그 이상을 붙여넣는다는 근거가 아직 없으므로
# 늘리지 않는다 - 근거 없이 정한 숫자로 돌아가지 않기 위해서다.
MAX_ROWS = 500

# 상품명이 이보다 짧으면 판단할 근거가 없다.
_MIN_NAME_LEN = 4


class RowVerdict(str, Enum):
    """배치 한 줄의 결론. 단건 검사의 Signal 보다 거칠다.

    배치는 상품명만 보므로 단건과 같은 확신을 가질 수 없다. 그래서 신호등을
    그대로 쓰지 않고 **"다시 볼 것" 을 가리는 등급**으로 둔다.
    """

    NEEDS_REVIEW = "needs_review"      # 단건 검사로 다시 봐야 한다
    CERT_REQUIRED = "cert_required"     # 인증번호가 반드시 있어야 하는 품목이다
    ABSENCE_NORMAL = "absence_normal"   # 번호가 조회 DB 에 없는 것이 정상인 등급
    CHECK_SUPPLIER = "check_supplier"   # 등급이 갈려 공급처 확인이 필요하다
    OUT_OF_SCOPE = "out_of_scope"       # 우리 소관이 아니다
    UNDECIDED = "undecided"             # 상품명만으로는 가릴 수 없다


@dataclass
class BatchRow:
    line: int
    product_name: str
    verdict: RowVerdict = RowVerdict.UNDECIDED
    reason: str = ""
    grade: str | None = None
    matched_item: str | None = None
    # 등급이 갈리면 후보를 다 담는다. 한쪽을 고르지 않는다 (R3).
    grade_candidates: list[str] = field(default_factory=list)
    # 품목 후보도 다 담는다. 갈릴 때 matched_item 은 비운다 - 대표 하나를
    # 고르면 연관 검색어에서 온 후보가 대표가 될 수 있다.
    matched_items: list[str] = field(default_factory=list)
    cert_numbers: list[str] = field(default_factory=list)
    rf_numbers: list[str] = field(default_factory=list)
    # 2단계(LLM)로 넘길 대상인가. 1단계에서 결론이 난 것은 넘기지 않는다.
    needs_llm: bool = False


@dataclass
class BatchReport:
    rows: list[BatchRow]
    truncated: int = 0          # 상한을 넘겨 잘린 줄 수
    llm_candidates: int = 0     # 2단계로 넘어갈 줄 수

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in self.rows:
            out[row.verdict.value] = out.get(row.verdict.value, 0) + 1
        return out

    @property
    def review_first(self) -> list[BatchRow]:
        """다시 볼 것부터. 셀러는 200줄을 다 읽지 않는다."""
        order = {
            RowVerdict.NEEDS_REVIEW: 0,
            RowVerdict.CERT_REQUIRED: 1,
            RowVerdict.CHECK_SUPPLIER: 2,
            RowVerdict.UNDECIDED: 3,
            RowVerdict.ABSENCE_NORMAL: 4,
            RowVerdict.OUT_OF_SCOPE: 5,
        }
        return sorted(self.rows, key=lambda r: (order[r.verdict], r.line))


def parse_lines(raw: str, *, limit: int = MAX_ROWS) -> tuple[list[str], int]:
    """붙여넣은 텍스트를 상품명 목록으로.

    엑셀에서 열을 복사하면 줄바꿈으로 구분된다. 탭이 섞여 오면(여러 열을 함께
    복사한 경우) 첫 칸을 상품명으로 본다 - 도매매·온채널 폼이 상품명을 앞쪽에
    두기 때문이다.
    """
    names: list[str] = []
    for line in (raw or "").splitlines():
        cell = line.split("\t")[0].strip() if "\t" in line else line.strip()
        # 엑셀 열 머리글이 함께 복사되는 일이 흔하다.
        if not cell or cell in {"상품명", "제품명", "품명", "name", "product_name"}:
            continue
        names.append(cell)

    truncated = max(0, len(names) - limit)
    return names[:limit], truncated


def screen(
    raw: str,
    grades: ItemGradeBook,
    *,
    limit: int = MAX_ROWS,
) -> BatchReport:
    """1단계 - 상품명만으로 판단 가능한 것을 걸러낸다. LLM 을 쓰지 않는다.

    여기서 결론이 나면 2단계(LLM)로 넘기지 않는다. 실측에서 200건 중 144건이
    이 단계에서 등급까지 확정됐다.
    """
    names, truncated = parse_lines(raw, limit=limit)
    rows: list[BatchRow] = []

    for i, name in enumerate(names, start=1):
        row = BatchRow(line=i, product_name=name)

        if len(name.strip()) < _MIN_NAME_LEN:
            row.verdict = RowVerdict.UNDECIDED
            row.reason = "상품명이 너무 짧아 판단할 근거가 없습니다."
            rows.append(row)
            continue

        # 인증번호는 형태가 정해진 하드 데이터라 정규식이 확실하다. 있으면
        # 단건 검사로 보내 실제 조회를 받아야 한다 - 배치에서는 조회하지 않는다
        # (200건 x 정부 API 호출은 예의에 어긋나고 느리다).
        row.cert_numbers = [m.group(0) for m in CERT_NUMBER_RE.finditer(name)]
        row.rf_numbers = extract_rf_numbers(name)

        candidates = grades.lookup_all(name)
        if candidates:
            _apply_grades(row, candidates)
        elif row.cert_numbers or row.rf_numbers:
            row.verdict = RowVerdict.NEEDS_REVIEW
            row.reason = (
                "인증번호가 보입니다. 실제 유효 여부는 단건 검사에서 조회됩니다."
            )
        else:
            # 상품명만으로는 품목을 특정하지 못했다. 상세페이지를 읽어야 한다.
            row.verdict = RowVerdict.UNDECIDED
            row.reason = "상품명만으로 품목을 특정하지 못했습니다."
            row.needs_llm = True

        rows.append(row)

    return BatchReport(
        rows=rows,
        truncated=truncated,
        llm_candidates=sum(1 for r in rows if r.needs_llm),
    )


def _apply_grades(row: BatchRow, candidates: list[ItemGrade]) -> None:
    """등급 후보로 결론을 낸다. 갈리면 한쪽을 고르지 않는다 (R3).

    합의 등급이면 후보가 여럿이어도 단정할 수 있다 - 어느 것을 골라도 등급이
    같기 때문이다. 갈리면 후보를 다 담고 확인을 요청한다.
    """
    row.grade_candidates = sorted({c.grade for c in candidates})

    if len(row.grade_candidates) > 1:
        # ⚠ 갈릴 때 대표 품목 하나를 고르지 않는다. 단건 화면에서 세 겹으로
        #   막은 "한쪽 단정" 을 여기서 하는 셈이 된다.
        #
        #   실측에서 드러났다 - "보조배터리 10000 … 선풍기조끼 쿨링조끼 …"
        #   가 candidates[0] 로 '선풍기' 를 대표로 달았다. 연관 검색어에서
        #   온 후보이고, 셀러는 보조배터리를 팔면서 선풍기를 보게 된다.
        #
        #   품목도 등급처럼 전부 담는다. 어느 것이 맞는지는 우리가 아니라
        #   공급처가 안다.
        row.matched_items = [c.item for c in candidates]
        row.verdict = RowVerdict.CHECK_SUPPLIER
        row.reason = (
            f"세부품목이 갈립니다({' / '.join(row.grade_candidates)}). "
            "어느 쪽인지 공급처에 확인하세요."
        )
        return

    # 등급이 하나로 모이면 어느 품목을 골라도 결론이 같다.
    row.matched_item = candidates[0].item
    row.matched_items = [c.item for c in candidates]

    row.grade = row.grade_candidates[0]

    if row.grade in {"공급자적합성확인", "안전기준준수"}:
        # 인증번호가 조회 DB 에 없는 것이 정상인 등급이다 (R3-b).
        row.verdict = RowVerdict.ABSENCE_NORMAL
        row.reason = (
            f"{row.grade} 대상으로 조회됩니다. 정부 조회 DB 에 번호가 없는 것이 "
            "정상입니다."
        )
        return

    # 안전인증·안전확인 - 번호가 반드시 있어야 한다.
    #
    # ⚠ 여기서 "상품명에 인증번호가 없다" 를 경고로 내면 안 된다. 상품명에
    #   인증번호를 적는 셀러는 거의 없다 - 번호는 상세페이지에 있다. 그렇게
    #   하면 규제 품목 전부가 경고가 되고(실측 200건 중 104건), 셀러는 전부
    #   무시한다. R3-b 가 미조회를 RED 로 두지 않은 것과 같은 이유다.
    #
    #   배치가 할 일은 "번호가 없다" 가 아니라 **"이 품목은 번호가 있어야
    #   한다" 를 알려주는 것**이다. 번호 확인은 단건 검사의 몫이다.
    if row.cert_numbers:
        row.verdict = RowVerdict.NEEDS_REVIEW
        row.reason = (
            f"{row.grade} 대상이고 상품명에 인증번호가 보입니다. 실제 유효 "
            "여부는 단건 검사에서 조회됩니다."
        )
    else:
        row.verdict = RowVerdict.CERT_REQUIRED
        row.reason = (
            f"{row.grade} 대상입니다. 인증번호가 반드시 있어야 하니 상세페이지"
            "에서 번호를 확인한 뒤 단건 검사로 유효 여부를 조회하세요."
        )
