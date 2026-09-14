"""안내 축 셋 — [L-2] 지재권 · [L-1(다)] 소관 · [⑦-d] 원산지 (2026-09-14).

⚠⚠ **판정이 아니다.** 셋 다 지켜야 할 것이 같다:

    신호등을 바꾸지 않는다 · 등급을 붙이지 않는다 · 검증을 끄지 않는다
    다섯 숫자 0/0/0/0/0
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sourcing_guard.kats_client import KatsClient
from sourcing_guard.models import (
    NON_SPECIFIC_FINDING_KINDS,
    FindingKind,
    ItemCategory,
    ProductFacts,
    Signal,
)
from sourcing_guard.scorer import _PENALTY, score
from sourcing_guard.verifier import RuleBook, verify

_ROOT = Path(__file__).resolve().parents[1]
_KATS = KatsClient(None, None, mock=True)
_RULES = RuleBook()

NOTICE_KINDS = (
    FindingKind.IP_MARKER_NOTICE,
    FindingKind.JURISDICTION_NOTICE,
    FindingKind.ORIGIN_MISMATCH,
)


def _run(facts: ProductFacts, raw_text: str | None = None):
    return verify(facts, _KATS, _RULES, raw_text=raw_text)


def _of(findings, kind):
    return [f for f in findings if f.kind is kind]


# ── 공통: 판정을 건드리지 않는다 ─────────────────────────────────────
@pytest.mark.parametrize("kind", NOTICE_KINDS)
def test_a_notice_never_costs_points(kind):
    assert _PENALTY[kind] == 0, kind


@pytest.mark.parametrize("kind", NOTICE_KINDS)
def test_a_notice_is_not_counted_as_a_specific_result(kind):
    """안내는 "구체적인 것을 줬다" 가 아니다 - 지표가 부풀면 안 된다."""
    assert kind in NON_SPECIFIC_FINDING_KINDS, kind


@pytest.mark.parametrize("kind", NOTICE_KINDS)
def test_a_notice_never_carries_a_signal_colour(kind):
    from sourcing_guard.models import _FINDING_GROUP, FindingGroup

    assert _FINDING_GROUP[kind.value] is FindingGroup.CONTEXT, kind


def test_the_signal_is_identical_with_and_without_the_notices():
    """표기어를 더해도 신호·점수가 그대로다.

    ⚠ **이 검사가 이 축의 전부다.** 안내가 신호를 바꾸면 그것은 판정이다.
    """
    base = ProductFacts(product_name="블록 완구 세트",
                        category=ItemCategory.CHILDREN_TOY)
    marked = ProductFacts(product_name="갤럭시워치 호환 블록 완구 세트 카시트",
                          category=ItemCategory.CHILDREN_TOY)
    a, b = _run(base), _run(marked)
    assert [f.kind for f in b if f.kind in NOTICE_KINDS], "안내가 안 붙었다 - 아무것도 안 쟀다"
    assert score(base, a).signal == score(marked, b).signal
    assert score(base, a).score == score(marked, b).score


# ── [L-2] 지재권 표기어 ───────────────────────────────────────────
def test_the_ip_notice_quotes_the_marker_and_refuses_to_judge():
    f = _run(ProductFacts(product_name="갤럭시워치 호환 스트랩"))
    line = _of(f, FindingKind.IP_MARKER_NOTICE)
    assert len(line) == 1
    assert line[0].statement_ko == (
        "'호환' 표기가 있습니다. 상표·디자인권은 이 도구가 확인하지 않습니다 — "
        "권리자·KIPRIS 확인 필요"
    )
    assert line[0].signal is Signal.UNKNOWN
    assert line[0].source_url == "https://www.law.go.kr/법령/상표법"
    assert line[0].detail["kipris_url"].startswith("https://www.kipris.or.kr/")


def test_the_ip_notice_never_names_a_brand():
    """**브랜드명 사전을 만들지 않는다 (R5).**

    걸린 문장에 '갤럭시워치' 가 있어도 우리 문장은 표기어만 인용한다 - 어느
    브랜드의 권리인지는 우리가 말할 수 있는 것이 아니다.
    """
    f = _run(ProductFacts(product_name="갤럭시워치 호환 스트랩"))
    line = _of(f, FindingKind.IP_MARKER_NOTICE)[0]
    assert "갤럭시" not in line.statement_ko
    src = (_ROOT / "sourcing_guard/data/ip_markers.yaml").read_text(encoding="utf-8")
    for brand in ("샤넬", "구찌", "나이키", "애플", "삼성", "갤럭시", "루이비통"):
        assert f'key: "{brand}' not in src, f"브랜드명이 표지어로 들어왔다: {brand}"


@pytest.mark.parametrize("name, hit", [
    ("갤럭시워치 호환 스트랩", "호환"),
    ("이지심플 미니선반/이케아st", "st"),
    ("[21st ScooTer] 킥보드 헬멧", None),   # 숫자 뒤 st 는 연도 표기다
    ("best 운동화 스니커즈", None),          # 영문 낱말 속 st
    ("네일클리퍼 네일아트", None),            # '리퍼' 를 안 넣은 이유
    ("라이트 카피바라 필통", None),           # '카피' 를 안 넣은 이유
    ("프리스타일 헌팅캡 패션모자", None),       # '스타일' 을 안 넣은 이유
    ("블록 완구 세트", None),
])
def test_only_the_markers_that_actually_fired_are_in_the_table(name, hit):
    """크레파스 원칙 — 후보 13개 중 **둘만** 남았다. 버린 이유를 검사로 잠근다."""
    from sourcing_guard.ip_markers import ip_marker_in

    assert ip_marker_in(name) == hit, name


def test_the_marker_table_records_counts_and_false_positives():
    """R5 — 넣은 표지어마다 **몇 건 걸렸고 무엇이 오탐인지** 적혀 있어야 한다."""
    import yaml

    doc = yaml.safe_load(
        (_ROOT / "sourcing_guard/data/ip_markers.yaml").read_text(encoding="utf-8"))
    assert doc["코퍼스"] == {"도매꾹_제목": 18938, "새표본": 235}
    for row in doc["표지어"]:
        m = row["실측"]
        assert isinstance(m["도매꾹"], int) and isinstance(m["새표본"], int), row["key"]
        assert m["도매꾹"] + m["새표본"] > 0, f"{row['key']} 는 표본에서 0건이다"
        assert m["진짜_예"], row["key"]
        assert "오탐_예" in m, f"{row['key']} 에 오탐 예가 없다 (빈 목록이라도 적는다)"


# ── [L-1(다)] 소관 안내 ───────────────────────────────────────────
def test_a_car_seat_keeps_all_three_axes_and_gets_one_notice():
    """카시트는 **검증을 끄지 않는다.** 축 셋을 그대로 수행하고 안내 한 줄."""
    from sourcing_guard.scorer import score as _score

    facts = ProductFacts(product_name="유아용 카시트 어린이 보호장치",
                         target_age="12개월 이상",
                         category=ItemCategory.CHILDREN_TOY)
    findings = _run(facts, raw_text="유아용 카시트 어린이 보호장치 대상연령 12개월")
    notices = _of(findings, FindingKind.JURISDICTION_NOTICE)
    assert len(notices) == 1, [f.kind.value for f in findings]
    assert "카시트" in notices[0].statement_ko
    assert "국토교통부" in notices[0].statement_ko
    assert "인증·리콜 대조는 그대로 수행했습니다" in notices[0].statement_ko
    # 축 셋이 그대로 돈다 - 안내가 검증을 끄지 않았다.
    assert [a.key for a in _score(facts, findings).axes] == ["cert", "recall", "hazard"]
    # 그리고 out_of_scope 로 단락되지 않았다.
    assert FindingKind.OUT_OF_SCOPE not in {f.kind for f in findings}


def test_a_cosmetics_pouch_is_still_verified():
    """'화장품' 낱말 하나로 파우치의 리콜 대조를 끄지 않는다.

    실측(도매꾹 18,938): '화장품' 163건 중 **53건(32.5%)이 화장품을 넣는
    용기·도구**다 - 파우치·필통·케이스·세면백.
    """
    facts = ProductFacts(product_name="캐릭터 대용량 파우치 필통 화장품 케이스",
                         category=ItemCategory.CHILDREN_STATIONERY)
    findings = _run(facts)
    assert FindingKind.OUT_OF_SCOPE not in {f.kind for f in findings}
    assert len(_of(findings, FindingKind.JURISDICTION_NOTICE)) == 1


def test_a_hard_cosmetics_signal_still_short_circuits():
    """반대 방향 - 하드 신호는 그대로 단락한다. 넓히면서 반대쪽을 깨지 않았나."""
    from sourcing_guard.scoping import out_of_scope_reason

    assert out_of_scope_reason("기능성화장품 수분크림 EWG 그린등급")
    assert out_of_scope_reason("화장품책임판매업자 에스앤비코리아")
    # 낱말 하나는 단락하지 않는다.
    assert out_of_scope_reason("여행용 화장품 파우치") is None


# ── [⑦-d] 원산지 대조 ────────────────────────────────────────────
@pytest.mark.parametrize("page_text, rows", [
    ("관상어용히터 인증번호 JU071047-12002C 제조국: 베트남", 1),   # 다르다
    ("관상어용히터 인증번호 JU071047-12002C 제조국: 중국", 0),     # 같다
    ("관상어용히터 인증번호 JU071047-12002C", 0),                 # 페이지에 없다
    ("관상어용히터 인증번호 JU071047-12002C 제조국: 상세정보 별도표기", 0),  # 값이 아니다
    ("관상어용히터 인증번호 JU071047-12002C 제조국 또는 원산지 : 수입산_아시아_베트남", 1),
    # 한 페이지에 둘이면 고르지 않는다 - 고르는 순간 판정이다 (R1).
    ("관상어용히터 인증번호 JU071047-12002C 제조국: 베트남 원산지: 중국", 0),
])
def test_origin_is_compared_only_when_both_sides_are_known(page_text, rows):
    facts = ProductFacts(product_name="관상어용히터",
                         kc_numbers=["JU071047-12002C"])
    got = _of(_run(facts, raw_text=page_text), FindingKind.ORIGIN_MISMATCH)
    assert len(got) == rows, [f.statement_ko for f in got]


def test_the_origin_line_does_not_say_which_side_is_wrong():
    facts = ProductFacts(product_name="관상어용히터", kc_numbers=["JU071047-12002C"])
    line = _of(_run(facts, raw_text="인증번호 JU071047-12002C 제조국: 베트남"),
               FindingKind.ORIGIN_MISMATCH)[0]
    assert "'중국'" in line.statement_ko and "'베트남'으로" in line.statement_ko
    assert "판단하지 않습니다" in line.statement_ko
    for banned in ("허위", "거짓", "위반", "속이", "원산지 표시 위반"):
        assert banned not in line.statement_ko
    # 되짚을 수 있게 원문을 남긴다 - 정규화가 틀렸을 때 필요하다.
    assert line.detail["registered_raw"] == "중국"


def test_an_unknown_country_word_never_becomes_a_mismatch():
    """모르는 말을 나라로 세지 않는다.

    ⚠ 그러면 '상세정보 별도표기' 와 '중국' 이 서로 다른 나라가 되어 **가짜
      불일치**가 된다. 없는데 있다고 하는 쪽이 더 비싸다 (§6).
    """
    from sourcing_guard.origin import normalize_country

    for junk in ("상세정보 별도표기", "상세설명참조", "수입산", "-", "", None, "별도표기"):
        assert normalize_country(junk) is None, junk
    assert normalize_country("수입산_아시아_중국") == "중국"
    assert normalize_country("국산_충청남도_보령시") == "대한민국"


# ── 화면 ────────────────────────────────────────────────────────
def test_the_screen_sends_the_seller_to_kipris_without_a_prefilled_query():
    """검색어를 주소에 담지 않는다 - KIPRIS 검색 폼은 POST 다 (실측).

    반쯤 채워진 주소를 쓰면 셀러가 "검색된 줄" 알고 빈 화면을 읽는다.
    """
    html = (_ROOT / "sourcing_guard/static/index.html").read_text(encoding="utf-8")
    assert "kipris_url" in html and "data-copy" in html
    assert "queryText" not in html, "검색어를 주소에 담고 있다"
    src = (_ROOT / "sourcing_guard/data/ip_markers.yaml").read_text(encoding="utf-8")
    assert "?tab=trademark" in src
    assert "queryTextTop=" not in src.split("# ⚠⚠ **검색어를 주소에")[0]
