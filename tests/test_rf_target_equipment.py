"""[⑦-a] 전파 적합성평가 대상기자재 표.

⚠⚠ **화면에 연결하지 않았다.** 기준(총괄)은 "새표본235 + 도매꾹239 에서 비대상
  오부착 0" 이었고 실측은 3건이다. 표는 리포에 두고 화면은 "무선 기능 표기가
  있습니다" 를 유지한다 - 등급표를 올릴 때와 같은 기준이다.

  이 파일이 지키는 것은 둘이다: **표가 원자료와 맞는가**, 그리고 **화면에
  조용히 연결되지 않았는가.**
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from sourcing_guard.rf_equipment import example_aliases, rf_book, table, wired_to_screen

_ROOT = Path(__file__).resolve().parents[1]
_YAML = _ROOT / "sourcing_guard/data/rf_target_equipment.yaml"
_RAW = sorted((_ROOT / "tests/fixtures").glob("전파_대상기자재_고시_*.json"))[-1]
TYPES = {"적합인증", "적합등록", "자기적합확인", "적합등록/자기적합확인"}


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return table()["items"]


# ── 원자료와 맞는가 ────────────────────────────────────────────────
def test_the_raw_appendix_is_kept_untouched():
    """원자료는 손대지 않는다 - 파싱이 틀렸을 때 되짚을 곳이 여기뿐이다."""
    raw = json.loads(_RAW.read_text(encoding="utf-8"))
    assert raw["행정규칙일련번호"] == "2100000282888"
    assert raw["별표제목"] == "적합성평가 대상기자재(제3조 관련)"
    assert raw["별표구분"] == "별표"
    assert len(raw["별표내용"]) == 1989


def test_the_appendix_is_chosen_by_title_not_by_number():
    """⚠ 번호로 고르면 **서식**을 집는다 - 응답에 `별표번호 0001` 이 둘이다.

    고시가 개정되면 번호가 밀린다. 제목으로 고른다.
    """
    src = (_ROOT / "scripts/probe_rf_target_equipment.py").read_text(encoding="utf-8")
    assert 'TITLE = "적합성평가 대상기자재(제3조 관련)"' in src
    assert "별표제목" in src
    # 번호로 고르는 코드가 다시 들어오면 안 된다.
    assert '별표번호"] == "0001' not in src


def test_every_row_carries_its_evidence(rows):
    """R2 · R5 — 줄마다 유형·기기부호·출처·원문 행 번호가 있어야 한다."""
    assert len(rows) == 367
    for r in rows:
        assert r["item"], r
        assert r["grade"] in TYPES, r
        assert r["category"] == "rf"
        assert r["source"].startswith("방송통신기자재등의 적합성평가에 관한 고시 별표 1")
        assert isinstance(r["별표행"], int) and r["별표행"] > 0
        # 기기부호는 세로 병합되지만 **빈 줄은 없어야 한다**(위에서 물려받는다).
        assert r["device_code"], r["item"]


def test_the_device_code_of_a_merged_run_is_inherited(rows):
    """⑧⑨⑩ 감자탈피기·전기정미기·전기빵자르개가 ⑦ 의 `KCN12` 를 함께 쓴다."""
    codes = {r["item"]: r["device_code"] for r in rows}
    for item in ("과일껍질깎기", "감자탈피기", "전기정미기", "전기빵자르개"):
        assert codes.get(item) == "KCN12", (item, codes.get(item))


def test_a_name_split_across_two_physical_rows_is_joined(rows):
    """"라.해상이동업무용 디지털선택호출" / "장치의 기기" 가 두 줄에 걸친다."""
    sv = next(r for r in rows if r["device_code"] == "SV")
    assert sv["item"] == "VHF송수신장치"
    assert "장치의 기기" in sv["scope_note"], sv["scope_note"]


def test_a_definition_marker_paragraph_is_not_used_as_the_item_name(rows):
    """11절 소분류의 **`(정의)` 문단**은 이름이 아니다. 이름은 그 위 칸이다.

    ⚠⚠ **이 검사의 범위는 두 문자열뿐이다** - `"(정의)"` 와 `"대표적인 품목"`.
      전 이름(`…definition_paragraph…`)은 그보다 넓게 들리는데, 실제로는
      **제외·조건 문장은 못 잡는다**("…적합성평가 대상에서 제외한다…").
      이름을 읽고 덮였다고 믿으면 안 된다 - 그쪽은 아래 래칫 검사가 센다.
    """
    cln = next(r for r in rows if r["device_code"] == "CLN11")
    assert cln["item"] == "전기청소기류"
    assert "진공청소기" in cln["examples"] and "로봇청소기" in cln["examples"]
    for r in rows:
        assert "(정의)" not in r["item"], r["item"]
        assert "대표적인 품목" not in r["item"], r["item"]


def test_the_examples_come_from_the_notice_not_from_us(rows):
    """별칭은 **고시가 괄호 밖에 적어 둔 대표 품목**이다 (R5).

    ⚠⚠ **"정의 문단 안에 있는가" 만 보면 버그를 지킨다 (⑦-a-2).**

      전 검사는 그것만 봤고, `'포함'` 은 정의 문단에 **당연히** 들어 있다 -
      동사 어미니까. 검사는 통과하고 그 별칭이 정수기 종이컵에 붙었다.
      §6 의 "검사가 기대값을 현재 출력에 맞춰 쓰면 버그를 고정한다" 자리다.

      `A(B, C)` 의 B·C 는 **A 안에서만** 품목명이다. 그러니 예시는 정의 문단의
      **괄호 밖**에 통째로 나와야 한다.

    ⚠ 원자료 전체와 대조하지는 않는다 - 표가 한 낱말을 여러 물리 줄에 걸쳐
      쓰고 그 사이에 왼쪽 칸 글자가 낀다("마이크로 전력 UV 방│출기").
      정의 문단은 파서가 같은 칸의 조각을 이어 붙인 것이고, 그 이어 붙이기가
      맞는지는 위 검사들이 따로 잠근다.
    """
    squash = lambda t: re.sub(r"[\s│┃─━]+", "", t)

    def outside_parens(text: str) -> str:
        out, depth = [], 0
        for ch in text:
            if ch in "(（[":
                depth += 1
            elif ch in ")）]":
                depth = max(0, depth - 1)
                continue
            if depth == 0:
                out.append(ch)
        return "".join(out)

    missing = []
    for r in rows:
        body = r.get("definition", "") or r.get("scope_note", "")
        # 예시 자체가 괄호를 품을 수 있다("전기토스터(팝업, 오븐 포함)").
        # 그 경우 **머리 낱말**이 괄호 밖에 있으면 된다.
        bare = squash(outside_parens(body))
        for x in r.get("examples", []):
            head = squash(outside_parens(x)) or squash(x)
            if head not in bare:
                missing.append((r["device_code"], x))
    assert missing == [], missing[:8]


def test_a_word_from_inside_parentheses_never_becomes_an_alias():
    """⚠⚠ **⑦-a-2 회귀 고정물.** 이 낱말들이 별칭이 되면 오부착이 돌아온다.

    전부 `A(B, C, D)` 의 괄호 안에서만 나오던 조각이다:

        커피메이커? 머신(자동머신, 캡슐, 포함)             → '포함'
        … 전동모터 장난감(드론, 자동차, 보트 등)            → '자동차'
        전동형 롤스크린(전동식 커튼, 셔터, 그릴, 차양, …)   → '셔터'·'그릴'·'차양'
    """
    alias = example_aliases()
    for fragment in ("포함", "자동차", "셔터", "그릴", "차양", "캡슐", "블라인드"):
        assert fragment not in alias, f"괄호 안 조각이 별칭이 됐다: {fragment}"


def test_the_builder_splits_commas_only_outside_parentheses():
    src = (_ROOT / "scripts/build_rf_target_equipment.py").read_text(encoding="utf-8")
    assert "def _split_top(" in src
    assert "depth == 0 and ch == \",\"" in src


def test_the_definition_text_is_kept_so_examples_can_be_traced(rows):
    """예시가 어디서 왔는지 되짚을 수 있게 정의 문단을 남긴다."""
    with_ex = [r for r in rows if r.get("examples")]
    assert len(with_ex) == 75
    for r in with_ex:
        assert r.get("definition"), r["device_code"]


def test_the_aliases_are_what_makes_matching_possible():
    """별칭이 없으면 **0건**이다 - 표 이름이 류 단위라 상품명과 안 겹친다."""
    book = rf_book()
    title = "이에스 로봇청소기 무선청소기 충전청소기 물걸레 청소걸레 밀대"
    assert book.lookup_all(title) == []
    got = book.lookup_all(title, extra_aliases=example_aliases())
    assert [g.item for g in got] == ["전기청소기류"]


# ── 화면에 조용히 연결되지 않았는가 ───────────────────────────────
def test_the_table_is_not_wired_to_the_screen():
    """⚠⚠ **이 검사가 이 파일의 핵심이다.**

    기준은 "비대상 오부착 0" 이었고 실측 3건이다. 표가 생겼다는 이유로
    화면에 붙이면, 정수기 종이컵에 "적합인증 대상입니다" 가 뜬다.
    """
    assert wired_to_screen() is False
    src = _ROOT / "sourcing_guard"
    users = [p.relative_to(_ROOT) for p in src.rglob("*.py")
             if p.name not in ("rf_equipment.py",)
             and "rf_equipment" in p.read_text(encoding="utf-8")]
    assert users == [], f"화면·판정 경로가 전파 표를 쓰고 있다: {users}"
    for page in (src / "static").glob("*.html"):
        assert "적합인증 대상입니다" not in page.read_text(encoding="utf-8"), page.name


def test_the_three_false_attachments_stay_gone(rows):
    """⚠⚠ **이 셋은 이제 회귀 고정물이다.**

    ⑦-a 에서 비대상에 붙었던 세 줄이다. 별칭이 다시 넓어져 이 셋 중 하나라도
    붙으면 **실패해야 한다** - 붙었다는 사실이 곧 조각이 돌아왔다는 뜻이다.
    """
    book, alias = rf_book(), example_aliases()
    for line in (
        "나도컵 꼬깔컵 생수컵 4000매 + 전용 디스펜서 포함 원터치 정수기컵 위생컵",
        "[지앤지] 자동차 시트커버 여름 메쉬 차량용 등받이 방석 카시트 보호 매트 시원한 시트",
        "자동차 킥매트 등받이 보호 시트",
    ):
        got = book.lookup_all(line, extra_aliases=alias)
        assert got == [], (line, [g.item for g in got])


def test_the_known_false_attachment_stays_visible(rows):
    """⚠⚠ **알려진 오부착 1건. 고치지 않고 눈에 보이게 둔다** (⑦-a-3).

        '온풍기 Y36 윈드키스 미니 히터 난풍기' → 동식물용 전기기기류
        머리 `히터` 가 `히터(관상어용·식물용, 동물부화·사육용 히터)` 에서 나왔다.

    떼어낼 규칙 셋을 재 봤는데 **셋 다 이 한 줄에 맞춰 만든 규칙**이었다
    (자세한 것은 `data/rf_target_equipment.yaml` 머리 주석). 그래서 틀린 채로
    두고 적는다.

    ⚠ 이 검사는 **"붙으면 실패" 가 아니다.** 지금 이 줄이 여기 붙는다는
      **사실**을 잠근다 - 나중에 도매꾹239 를 전수분류해서 이 줄이 비대상으로
      판명되면 그때 게이트(비대상 오부착 0)가 스스로 닫힌다.
    """
    book, alias = rf_book(), example_aliases()
    got = book.lookup_all("온풍기 Y36 윈드키스 미니 히터 난풍기 KC인증 대량구매 최신형",
                          extra_aliases=alias)
    assert [g.item for g in got] == ["동식물용 전기기기류"], [g.item for g in got]
    assert "알려진 오부착 1건" in _YAML.read_text(encoding="utf-8")


def test_the_head_word_of_a_parenthesised_example_is_an_alias():
    """`A(B, C)` 의 **A** 는 별칭이다 - 고시가 A 를 품목명으로 적은 것이다.

    ⚠ 꼬리(B·C)는 아니다. ⑦-a-2 가 뺀 쪽이고 여기가 넣는 쪽이다 -
      **머리는 안전하고 꼬리는 안전하지 않다.**
    """
    alias = example_aliases()
    for head in ("전기토스터", "제모기", "전기그릴", "전기밥솥"):
        assert head in alias, f"머리 낱말이 별칭에 없다: {head}"
    for tail in ("포함", "자동차", "셔터", "그릴", "차양", "캡슐"):
        assert tail not in alias, f"괄호 안 조각이 별칭이 됐다: {tail}"


def test_no_alias_is_left_with_an_unclosed_parenthesis():
    """여는 괄호만 남은 별칭은 **영원히 아무것도 못 맞힌다.**

    ⑦-a-2 직후 `rstrip(")")` 때문에 57개가 그랬다 - 상품명에 그 문자열이
    통째로 들어 있어야 맞는데 그런 상품명은 없다.
    """
    broken = [k for k in example_aliases() if k.count("(") != k.count(")")]
    assert broken == [], broken[:6]


# ── 래칫: 제외·조건 문장이 이름인 행 ────────────────────────────────
#
# ⚠⚠ **이 수는 결함이다. 0 이 되어야 한다.** 늘면 실패한다.
#
#   "…적합성평가 대상에서 제외한다…" 라고 적힌 줄에 `자기적합확인` 등급이
#   붙어 있다. 화면에 올라가 있었다면 제외 문장을 품목명 자리에 띄우면서
#   "대상입니다" 라고 말했을 것이다 - §6 이 이름 붙인 **"없는데 있다고 하는"**
#   방향이고 이 제품에서 가장 비싼 오류다.
#
#   원인은 파서의 이름 경계다. `4)` · `⑫` · `o ` 에서 잘라야 하는데 안 자른다.
#   고치는 것은 파서를 다시 만지는 일이라 **본선으로 미뤘다**(프리즈 4일 전).
#   가짜 가드를 두는 것보다 **결함을 눈에 보이게 세어 두는 것**이 낫다.
#
#   ⚠ 커밋의 "버린 행 0" 이 여기서는 미덕이 아니라 대가다. 아무것도 안 버려서
#     제외 조항이 대상 행이 됐다. 94행을 살린 판단은 옳았고, 그 판단이 동시에
#     이것을 들여왔다 - 둘은 같은 결정의 양면이다.
_SENTENCE_NOT_A_NAME = re.compile(r"^o\s|(?:한다|된다)[\s.]|제외한다")

#: 2026-09-14 실측. **줄이면 이 수도 줄여 잠근다.**
_SENTENCE_NAMES_TODAY = 22
#: 그중 examples 가 있어 **매칭에 닿는** 행. 여기가 진짜 위험한 자리다.
_SENTENCE_NAMES_REACHABLE = 2


def test_sentence_shaped_names_do_not_grow(rows):
    hit = [r for r in rows if _SENTENCE_NOT_A_NAME.search(r["item"])]
    reachable = [r for r in hit if r.get("examples")]
    assert len(hit) <= _SENTENCE_NAMES_TODAY, (
        f"제외·조건 문장이 이름인 행이 {len(hit)}개로 늘었다 "
        f"(기준 {_SENTENCE_NAMES_TODAY}). 파서의 이름 경계를 고치세요."
    )
    assert len(reachable) <= _SENTENCE_NAMES_REACHABLE, (
        f"그중 매칭에 닿는 행이 {len(reachable)}개다 "
        f"(기준 {_SENTENCE_NAMES_REACHABLE}): "
        f"{[r['device_code'] for r in reachable]}"
    )
    # 줄었으면 기준도 같이 내린다 - 래칫은 한 방향으로만 돈다.
    assert len(hit) == _SENTENCE_NAMES_TODAY, (
        f"{len(hit)}개로 줄었습니다. _SENTENCE_NAMES_TODAY 를 내리세요."
    )


def test_the_two_reachable_sentence_rows_are_named(rows):
    """닿는 둘이 어느 것인지 적어 둔다. 바뀌면 다시 봐야 한다."""
    hit = [r for r in rows
           if _SENTENCE_NOT_A_NAME.search(r["item"]) and r.get("examples")]
    assert sorted(r["device_code"] for r in hit) == ["IMV11", "LIN"]


def test_the_reason_for_not_wiring_is_written_down():
    """왜 안 붙였는지가 표에 적혀 있어야 한다. 다음 사람이 그냥 켜지 않게.

    ⚠ 오부착이 0 이 된 뒤에도 안 켠다 - 0 은 **필요조건이지 충분조건이
      아니다.** 도매꾹239 는 아직 전수 분류가 없다.
    """
    text = _YAML.read_text(encoding="utf-8")
    assert "화면에 연결하지 않았다" in text
    assert "필요조건이지 충분조건이 아니다" in text
    assert "무선 기능 표기가 있습니다" in text
    # 잃은 것도 적혀 있어야 한다. 이득만 적으면 다음 사람이 비용을 모른다.
    assert "맞는 줄 8개를 잃었다" in text
    for lost in ("무선주전자", "눈썹제모기", "토스트기"):
        assert lost in text, lost


def test_the_measurement_script_fails_while_the_count_is_not_zero():
    """측정 스크립트가 **0이 아니면 실패**해야 한다. 통과하면 열린 줄 안다."""
    src = (_ROOT / "scripts/measure_rf_attachment.py").read_text(encoding="utf-8")
    assert "if wrong:" in src and "return 1" in src
    assert "ItemGradeBook" in src, "같은 매처를 써야 한다"


def test_the_table_is_generated_not_hand_edited():
    text = _YAML.read_text(encoding="utf-8")
    assert "손으로 고치지 않는다" in text
    assert "scripts/build_rf_target_equipment.py" in text
    assert yaml.safe_load(text)["version"] == 1
