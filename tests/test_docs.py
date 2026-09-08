"""제출 서류에 대한 회귀 테스트.

기획서는 심사위원이 읽는 문서다. 틀린 기준치가 남아 있으면 코드가 아무리
정확해도 발표에서 그 숫자를 공개하게 된다. 문서도 테스트 대상으로 둔다.
"""

from pathlib import Path

import pytest
import yaml

from sourcing_guard.models import FindingKind
from sourcing_guard.scorer import _HARD_RED

PROPOSAL = Path("01_기획서_안심소싱돋보기.md")
RULES = Path("sourcing_guard/data/hazard_rules.yaml")


@pytest.fixture(scope="module")
def proposal() -> str:
    return PROPOSAL.read_text(encoding="utf-8")


@pytest.mark.parametrize("retired", ["300mg/kg", "300 mg/kg"])
def test_proposal_does_not_cite_the_retired_lead_limit(proposal, retired):
    """'납 300 mg/kg' 은 완구 부속서의 옛 기준치이며 100 으로 개정됐다.

    공통안전기준의 납 기준은 용출 90 / 함유량 100(페인트·표면코팅 90)이다.
    초기 기획안이 300 을 반복해서 적고 있었다.
    """
    assert retired not in proposal, (
        f"기획서에 폐지된 기준치 '{retired}' 가 있습니다. "
        "공통안전기준의 납 기준은 용출 90 / 함유량 100 입니다."
    )


def test_proposal_limits_match_the_rule_book(proposal):
    """기획서가 인용한 수치는 규칙 DB 와 같은 출처에서 와야 한다.

    문서와 코드가 각자 숫자를 들고 있으면 한쪽만 고쳐지고 조용히 갈라진다.
    실제로 '납 300' 이 그렇게 남아 있었다.
    """
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}

    expected = {
        "KC-COMMON-3.1.1-PB": (90, "납 용출"),
        "KC-COMMON-3.1.2-PB": (100, "총 납 함유량"),
        "KC-COMMON-3.1.3-PHT": (0.1, "프탈레이트 총합"),
    }
    for rule_id, (value, label) in expected.items():
        assert by_id[rule_id]["limit_value"] == value, label

    for cited in ("90mg/kg", "100mg/kg", "0.1%"):
        assert cited in proposal, f"기획서에 '{cited}' 인용이 없습니다"


def _table_row(proposal: str, signal: str) -> str:
    """기획서 §3 신호등 표에서 한 행을 뽑는다."""
    rows = [ln for ln in proposal.splitlines() if ln.startswith(f"| {signal} ")]
    assert len(rows) == 1, f"{signal} 행을 특정하지 못했습니다: {len(rows)}건"
    return rows[0]


def test_proposal_traffic_light_matches_the_scorer(proposal):
    """기획서의 신호등 표는 scorer 의 실제 동작과 같아야 한다 (CLAUDE.md R3-b).

    RED 는 정부 DB 가 문제를 적어둔 경우에만 준다. 미조회는 AMBER 다.
    전안법 위해도 최하단인 공급자적합성확인(SCoC) 대상은 제조·수입자가 스스로
    시험해 확인하므로 조회 DB 에 번호가 없는 것이 정상이기 때문이다.

    §6.1 은 이 내용으로 고쳐졌는데 §3 표만 "미조회 → RED" 로 남아 있었다.
    심사위원이 읽는 문서라 코드가 아무리 정확해도 발표에서 틀린 동작을 설명하게 된다.
    """
    assert FindingKind.KC_NOT_FOUND not in _HARD_RED, (
        "scorer 가 미조회를 RED 로 되돌렸습니다. 기획서 §3 표와 §6.1 도 함께 고치세요 (R3-b)."
    )

    red = _table_row(proposal, "🔴 RED")
    assert "미조회" not in red, (
        f"기획서 RED 행이 미조회를 RED 로 적고 있습니다 (코드는 AMBER): {red}"
    )

    amber = _table_row(proposal, "🟡 AMBER")
    assert "미조회" in amber, (
        f"기획서 AMBER 행에 미조회가 없습니다: {amber}"
    )


def test_proposal_phthalate_count_matches_the_rule_book(proposal):
    """기획서가 인용한 프탈레이트 물질 수는 규칙 DB 가 실제로 담은 수와 같아야 한다.

    확보한 원문(2020년판)은 6종이다. 현행 고시를 인용한 2차 자료에는 DIBP 가
    더해져 7종이라는 기술이 있으나 원문 미확인이다 (docs/규칙DB_검수목록.md §2).
    기획서가 7종이라고 단정하면 검증 안 된 값을 제출 서류에 싣는 것이다 (R5).
    """
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in raw["rules"]}
    covered = len(by_id["KC-COMMON-3.1.3-PHT"]["substances_covered"])

    assert f"프탈레이트 {covered}종" in proposal, (
        f"규칙 DB 는 프탈레이트 {covered}종을 담고 있는데 기획서 표기가 다릅니다. "
        "원문에서 확인한 수만 적으세요 (R5)."
    )


def test_no_rule_is_promoted_without_a_reviewer():
    """verified 승격은 사람이 원문을 대조한 기록과 함께여야 한다 (CLAUDE.md R5)."""
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    bad = [
        r["id"]
        for r in raw["rules"]
        if r.get("status") == "verified" and not (r.get("verified_by") and r.get("verified_at"))
    ]
    assert not bad, f"검수자 기록 없이 verified 로 승격된 룰: {bad}"


def test_phthalate_rule_carries_all_seven_current_substances():
    """현행 제2022-220호 3.1.3 은 7종이다 (p.3 표, 2026-09-01 원문 대조).

    DIBP(CAS 84-69-5)는 2022-12-14 개정에서 추가됐다. 2020년판(6종)으로
    되돌아가면 규제 물질 하나를 조용히 놓친다.
    """
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    pht = {r["id"]: r for r in raw["rules"]}["KC-COMMON-3.1.3-PHT"]

    names = [m["name"] for m in pht["substances_covered"]]
    assert names == ["DEHP", "DBP", "BBP", "DINP", "DIDP", "DnOP", "DIBP"]

    dibp = next(m for m in pht["substances_covered"] if m["name"] == "DIBP")
    assert dibp["cas"] == "84-69-5"
    assert "substances_pending" not in pht, "원문 확인이 끝났으니 pending 은 비어야 한다"


def test_rule_book_cites_the_current_gazette():
    """모든 룰의 legal_basis 는 현행 고시(제2022-220호)를 인용해야 한다.

    원문 텍스트 전체가 아니라 legal_basis 필드만 본다. "2020년판은 6종이었다"
    같은 이력 주석은 정당하고, 금지 대상은 근거 인용이다.
    """
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    stale = [
        r["id"]
        for r in raw["rules"]
        if "2019-201" in r.get("legal_basis", "") or "2019-0201" in r.get("legal_basis", "")
    ]
    assert not stale, f"폐지된 고시를 인용하는 룰: {stale}"

    # 규칙 DB 에 고시가 둘 이상 들어온다. 공통안전기준(제2022-220호)과
    # 안전확인 안전기준 부속서는 별개 고시이므로, "모든 룰이 공통기준을 인용" 은
    # 더 이상 참이 아니다. id 접두로 갈라서 각자의 근거를 요구한다.
    for rule in raw["rules"]:
        basis = rule.get("legal_basis", "")
        if rule["id"].startswith("KC-COMMON-"):
            assert "제2022-220호" in basis, f"{rule['id']}: 공통기준 고시 번호 없음"
        elif rule["id"].startswith("KC-ANNEX"):
            assert "부속서" in basis, f"{rule['id']}: 부속서 근거 없음"
        elif rule["id"].startswith("KC-SDOC"):
            # 공급자적합성확인 기준 부속서. 2026-09-07 에 부속서 17(마스크)·
            # 15(킥보드)를 수집했다. 이 고시는 IEC 채택본이 아니라 한국어로
            # 쓰인 구체 요건이라 기준치가 숫자로 나온다.
            assert "공급자적합성확인대상생활용품" in basis, (
                f"{rule['id']}: 공급자적합성확인 고시 근거 없음 - {basis!r}"
            )
            assert "부속서" in rule.get("clause", ""), (
                f"{rule['id']}: clause 에 부속서 번호가 없다 - {rule.get('clause')!r}"
            )
        elif rule["id"].startswith(("KC-LIFE-", "KC-ELEC-")):
            # 생활용품·전기용품(전안법). 원문을 확인하면 부속서 번호까지
            # 특정되므로 근거가 "부속서 52(승차용 안전모)" 형태가 되고,
            # 아직 특정 못 했으면 상위 법률만 적는다. 둘 다 허용한다.
            assert "부속서" in basis or "전기용품 및 생활용품 안전관리법" in basis, (
                f"{rule['id']}: 전안법·부속서 근거 없음 - {basis!r}"
            )
        else:
            raise AssertionError(f"{rule['id']}: 근거 체계를 알 수 없는 id 접두")


# ---------------------------------------------------------------------------
# 시험방법·쪽번호 — 기준치만 대조하면 이 필드들이 틀린 채로 verified 가 된다.
#
# 실제로 그럴 뻔했다. 첫 대조는 기준치와 CAS 만 봤고, 시험방법 3건과 쪽번호
# 8건이 원문과 다른 채로 남아 있었다 (2026-09-02 원문 재확인으로 정정).
# ---------------------------------------------------------------------------


def _rules() -> dict:
    raw = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    return {r["id"]: r for r in raw["rules"]}


def test_nitrosamine_test_method_matches_the_decree():
    """원문 p.8 4.1.4 는 부속서 6 을 가리킨다. 식약처고시가 아니다.

    출처가 아예 다른 문서라, 셀러가 이걸 보고 엉뚱한 규격으로 시험을 의뢰하게
    된다. 기준치가 맞다고 룰 전체가 맞는 것이 아니다.
    """
    by_id = _rules()
    for rule_id in ("KC-COMMON-3.1.4-NITROSAMINE", "KC-COMMON-3.1.4-NITROSATABLE"):
        method = by_id[rule_id]["test_method"]
        assert "부속서 6" in method, f"{rule_id}: 원문 p.8 4.1.4 와 다릅니다"
        assert "식약처" not in method, f"{rule_id}: 폐기된 출처가 되살아났습니다"


def test_phthalate_test_method_does_not_invent_an_analysis_technique():
    """원문 p.8 4.1.3 은 "부록 C에 따른다" 뿐이다.

    부록 C 는 확보한 9쪽 PDF 에 없다. 분석기법을 적으려면 부록 확보 후에 한다 (R5).
    """
    method = _rules()["KC-COMMON-3.1.3-PHT"]["test_method"]
    assert "부록 C" in method
    assert "GC-MS" not in method, "원문에 없는 분석기법이 되살아났습니다 (R5)"


def test_source_pages_match_the_current_decree():
    """현행 제2022-220호의 쪽 배치. 2020년판과 다르다 (3.1.1 이 p.3 -> p.2)."""
    expected_by_clause = {"3.1.1": 2, "3.1.2": 3, "3.1.3": 3,
                          "3.1.4": 4, "3.1.5": 4, "3.1.6": 4}
    for rule_id, rule in _rules().items():
        # 부속서는 별개 문서라 쪽 배치가 다르다. 이 가드는 공통기준 전용이다.
        if not rule_id.startswith("KC-COMMON-"):
            continue
        clause = rule["clause"].split()[0]
        want = expected_by_clause[clause]
        assert rule["source_page"] == want, (
            f"{rule_id}: source_page {rule['source_page']} != 원문 p.{want}"
        )


def test_promoted_rules_carry_the_current_decree_number():
    """폐지된 고시 번호로 verified 를 달면 근거가 틀린 채로 프로덕션에 나간다.

    규칙 DB 에 고시가 셋이라 체계별로 요구가 다르다. 공통안전기준만 번호를
    본문에 적고, 부속서·전안법은 부속서 번호나 법령명으로 특정된다.
    """
    for rule_id, rule in _rules().items():
        if rule.get("status") != "verified":
            continue
        basis = rule["legal_basis"]
        if rule_id.startswith("KC-COMMON-"):
            assert "제2022-220호" in basis, rule_id
        else:
            # 부속서에서 온 것은 부속서 번호로 특정되고, verified_source 에
            # 어느 조문을 눈으로 대조했는지 남는다.
            assert "부속서" in basis, rule_id
            assert rule.get("verified_source"), (
                f"{rule_id}: verified 인데 무엇을 대조했는지 없다"
            )


def test_the_handoff_log_names_the_real_install_command():
    """작업로그가 없는 파일을 시키면 집에서 첫 명령부터 막힌다.

    2026-09-03 에 실제로 겪었다 - `pip install -e ".[dev]"` 를 적었는데
    이 저장소에는 pyproject.toml 이 없다. 깨끗한 클론으로 돌려보고 찾았다.
    """
    root = Path(__file__).resolve().parents[1]
    log = root / "docs" / "작업로그_2026-09-03.md"
    text = log.read_text(encoding="utf-8")

    assert "requirements.txt" in text
    # 없는 파일을 시키지 않는다.
    for absent in ("pyproject.toml", "poetry", "Pipfile"):
        if not (root / absent).exists():
            assert f'install -e ".[dev]"' not in text, absent
    assert (root / "requirements.txt").exists()


def test_the_proposal_numbers_match_the_code():
    """기획서에 적은 실측 숫자가 코드와 어긋나면 심사에서 그대로 드러난다.

    이 저장소의 반복 결함이 문서와 코드가 어긋나는 것이다. 기획서는 제출
    서류라 비용이 특히 크므로, 바뀌면 검사가 깨지게 한다.

    ⚠ 44/56은 **상품 단위**다. 한 상품에 원문 일치가 하나라도 있으면 44%
      쪽으로 센다. 후보 단위로 세면 39/61이 되는데, 한 상품이 후보를 여럿
      내면(청소기 하나가 넷) 부풀기 때문이다. 기획서도 그 단위를 밝힌다.
    """
    import collections
    import pathlib as _p

    import yaml as _yaml

    from sourcing_guard.batch import MAX_ROWS
    from sourcing_guard.item_grades import ItemGradeBook

    root = Path(__file__).resolve().parents[1]
    doc = (root / "01_기획서_안심소싱돋보기.md").read_text(encoding="utf-8")

    # 등급표 건수와 등급별 분포
    grades = _yaml.safe_load(
        (root / "sourcing_guard" / "data" / "item_grades.yaml").read_text(encoding="utf-8")
    )["items"]
    assert f"**{len(grades)}건**" in doc, len(grades)
    counts = collections.Counter(r["grade"] for r in grades)
    for grade, n in counts.items():
        assert f"| {grade} | {n} |" in doc, (grade, n)

    # 실측 - 새 표본 235건. **분모는 235 가 아니라 안전관리대상 135** 이다.
    #
    # ⚠ 표에 없는 물건에 품목을 붙이면 셀러에게 없는 의무를 만든다. 그래서
    #   분모에서 비대상 53·애매 47 을 뺀다. 다만 두 분모를 나란히 적어야 한다.
    #
    # ⚠ **발표 숫자는 단건 경로다** - 데모가 단건이기 때문이다. 배치 경로
    #   숫자는 대량 검사 기능을 설명할 때만 쓴다. 여기서는 배치를 코드로
    #   재검증하고, 단건은 저장된 원자료(tests/fixtures/단건경로_136건.json)와
    #   문서가 어긋나지 않는지만 본다.
    import json as _json

    book = ItemGradeBook()
    scope: dict[str, str] = {}
    for line in (root / "tests" / "fixtures" / "새표본235_대상분류.tsv").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.startswith("#") or not line.strip():
            continue
        _no, verdict, name, _why = line.split("\t")
        scope[name] = verdict

    wrong, vague, section = set(), set(), None
    for line in (root / "tests" / "fixtures" / "새표본235_오답.tsv").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.startswith("#"):
            if "--- 오답" in line:
                section = "wrong"
            elif "[애매]" in line:
                section = "vague"
            elif "[검수했고 정답]" in line or "[고쳐짐" in line:
                section = None
            continue
        if not line.strip() or section is None:
            continue
        (wrong if section == "wrong" else vague).add(line.split("\t")[0])

    names = list(scope)
    target = [n for n in names if scope[n] == "대상"]
    assert len(target) == 135, len(target)
    assert f"안전관리대상   {len(target)}건" in doc

    import sys as _sys

    _sys.path.insert(0, "scripts")
    from audit_tally import tally as _tally

    results = {n: sorted({g.item for g in book.lookup_all(n)}) for n in names}
    got = _tally(results, scope=scope)
    b_ok, b_vague, b_wrong = got["ok"], got["vague"], got["wrong"]
    b_pct = round(b_ok / len(target) * 100, 1)
    # ⚠ 정렬 공백은 자릿수에 따라 달라진다 - 숫자가 세 자리가 되면 한 칸
    #   줄어든다. 표 정렬을 지키려고 문서 쪽을 억지로 맞추지 말고 여기서
    #   공백을 접어 비교한다.
    def _flat(t: str) -> str:
        return " ".join(t.split())

    assert _flat(f"정답 {b_ok}건 ({b_pct}%) · 애매 {b_vague} · 오답 {b_wrong}") in _flat(
        doc
    ), (b_ok, b_pct)

    # 단건 경로 - 발표 숫자다. 문서에 적힌 값이 원자료와 맞는지 본다.
    single = {
        r["name"]: r["single"]
        for r in _json.loads(
            (root / "tests" / "fixtures" / "단건경로_136건.json").read_text(encoding="utf-8")
        )
    }
    assert single, "단건 원자료가 비었다"
    assert "단건 경로 · 대상 135 중" in doc
    assert _flat("정답 113건 (83.7%)") in _flat(doc)
    assert '화면에는 "비대상입니다"를 출력하지 않습니다' in doc

    # ⚠ 오부착률은 **실측한 값만** 적는다. 2026-09-07 까지 이 자리에 40.9% 가
    #   있었는데 그것은 전체 235 기준 **매칭률**이었고 오부착률이 아니었다.
    #   비대상 100건을 단건 경로로 실제로 돌린 값이 아래다 (docs/비대상_오부착_실측).
    assert "비대상  53건 →  0건 부착" in doc
    assert "애매    47건 →  2건 부착" in doc
    assert "**40.9%**" not in doc, "안 잰 숫자가 돌아왔다"

    # 대량 검사 상한
    assert f"{MAX_ROWS}줄" in doc, MAX_ROWS


def test_the_coverage_unit_change_is_recorded_in_the_rules_doc():
    """커버리지 단위가 품목군 → 품목으로 바뀐 것을 CLAUDE.md §5 가 말하는지 잠근다.

    ⚠ 이 검사는 예전에 "household 를 coverage 에 넣지 않는 것이 의도다" 를
      잠갔다. 2026-09-07 에 단위를 좁혀 상태가 바뀌었다 - 이제 household 의
      verified 룰 4건이 실제로 쓰이고, 룰 없는 품목은 계속 회색이다.

    ⚠ 정본은 CLAUDE.md §5 다. coverage 를 건드릴 사람이 읽는 문서가 거기다.
    """
    from sourcing_guard.models import ItemCategory, ProductFacts
    from sourcing_guard.verifier import RuleBook

    root = Path(__file__).resolve().parents[1]
    rules_doc = (root / "CLAUDE.md").read_text(encoding="utf-8")

    assert "커버리지 단위는 **품목**이다" in rules_doc
    assert "coverage.categories` 는 **서술용으로만 남겼다.**" in rules_doc
    assert "R3 위반" in rules_doc
    # GREEN 조건을 건드리지 않았다는 사실이 남아야 한다.
    assert "GREEN 조건은 건드리지 않았다" in rules_doc
    # rule_type 갈래도 같은 절에 적혀 있어야 한다.
    assert "rule_type` 으로 나눈다" in rules_doc
    for rule_id in ("KC-LIFE-HELMET-PERF",):
        assert rule_id in rules_doc or "안전모" in rules_doc

    # 문서가 말하는 대로 코드가 동작하는가.
    book = RuleBook()
    assert book.covers(ProductFacts(product_name="승차용 안전모",
                                    category=ItemCategory.HOUSEHOLD))
    assert not book.covers(ProductFacts(product_name="우산 양산",
                                        category=ItemCategory.HOUSEHOLD))


def test_the_submission_draft_uses_only_the_audited_rate():
    """제출문에 71%·24% 가 들어가지 않는지 잠근다.

    ⚠ 71% 는 별칭을 만들 때 쓴 표본(도매꾹239)의 매칭률이고, 24% 는 새 표본의
      **검수 전** 매칭률이다. 심사 서류에 검수 안 된 숫자를 쓰면 그대로
      드러난다. 발표 숫자는 새표본235 전수 검수 정답률 20.0% 하나다.

    ⚠ 세 항목·세 길이가 다 있어야 한다. 폼의 글자 수 제한을 아직 모르므로
      확인될 때까지 셋을 유지한다.
    """
    root = Path(__file__).resolve().parents[1]
    draft = (root / "docs" / "제출문_초안.md").read_text(encoding="utf-8")

    body = draft[draft.index("## 1. 해결하려는 문제"):]
    for banned in ("71%", "24%"):
        assert banned not in body, f"제출문 본문에 검수 전 숫자 '{banned}' 가 있습니다"
    # 두 분모를 나란히 쓴다 - 한쪽만 쓰면 분모를 유리하게 바꾼 것이 된다.
    assert "71.1%" in body and "40.9%" in body

    for item in ("## 1. 해결하려는 문제", "## 2. AI 활용 방식", "## 3. 사용한 AI 도구"):
        assert item in draft, item
    assert draft.count("### 200자") == 3
    assert draft.count("### 500자") == 3
    assert draft.count("### 1000자") == 3

    # 제출 항목 넷 중 링크는 이미 있다.
    assert "https://sourcing-guard.fly.dev" in draft

    # R1 을 제약이 아니라 설계 선택으로 쓴다 - 심사 기준이 "AI 활용의 적절성" 이다.
    assert "손해배상 사유" in draft


def test_the_handoff_schedule_matches_the_real_contest_dates():
    """핸드오프 일정표가 실제 대회 일정과 같은지 잠근다.

    ⚠ 이전 판이 "9/19 제출, 9/20 예비일" 로 적고 **참가 신청 마감(9/18)을
      아예 빠뜨렸다.** 신청을 놓치면 나머지가 전부 무의미하다.
      날짜를 기억으로 적지 않는다 - R5 는 코드뿐 아니라 일정에도 해당한다.
    """
    root = Path(__file__).resolve().parents[1]
    doc = (root / "00_프로젝트_핸드오프.md").read_text(encoding="utf-8")

    schedule = doc[doc.index("## 8. 남은 일정"):]
    assert "참가 신청 마감" in schedule
    assert "**9/18**" in schedule
    assert "프로젝트 제출 마감" in schedule
    assert "**9/20**" in schedule
    assert "event.wanted.co.kr" in schedule
    # 폼을 직접 못 봤다는 사실이 남아 있어야 한다.
    assert "폼 자체를 본 것이 아니다" in schedule


def test_every_measurement_tool_shares_one_tally():
    """집계 구현이 **하나**여야 한다.

    ⚠ 2026-09-08 사고다. 같은 일을 하는 집계가 셋이었고 서로 달랐다:

        scripts/measure_single_path_full.py   실 API 측정
        scripts/replay_single_path.py         저장 답 재생
        tests/test_item_grades.py             회귀 락

      갈라진 결과로 기획서에 77.8% 를 적었는데 실제는 77.0% 였다. 두 군데가
      어긋나 있었다 - verifier 의 카테고리 게이트를 건너뛴 것과,
      ITEM_GRADE_SPLIT(두 등급으로 갈리는 줄)을 미매칭으로 센 것.

      이 저장소의 반복 결함이 문서가 코드보다 앞서 나가는 것이고, 이번
      원인은 **측정 도구가 여럿인 것**이었다. 그래서 하나로 모으고 여기서
      잠근다.
    """
    root = Path(__file__).resolve().parents[1]
    helper = root / "scripts" / "audit_tally.py"
    assert helper.exists(), "공용 집계 헬퍼가 없다"

    users = [
        root / "scripts" / "measure_single_path_full.py",
        root / "scripts" / "replay_single_path.py",
        root / "tests" / "test_item_grades.py",
    ]
    for path in users:
        src = path.read_text(encoding="utf-8")
        assert "audit_tally import" in src, f"{path.name} 이 공용 헬퍼를 안 쓴다"
        # 자기 파서를 다시 만들지 않았는지 - 절 표지를 직접 찾으면 갈라진 것이다.
        assert "--- 오답" not in src, f"{path.name} 에 파서가 되살아났다"

    # 헬퍼는 붙은 품목까지 본다 - 상품명만 보면 고쳐진 오답도 계속 오답이다.
    src = helper.read_text(encoding="utf-8")
    assert "def verdict(" in src
    assert "got & wrong.get(name" in src

    # 재생은 verify() 를 통과해야 한다 - lookup_all 직접 호출은 게이트를 건너뛴다.
    replay = (root / "scripts" / "replay_single_path.py").read_text(encoding="utf-8")
    assert "verify(" in replay


def test_the_tally_does_not_score_unreviewed_pairs_as_correct():
    """검수된 적 없는 (상품명, 품목) 쌍을 정답으로 세지 않는다.

    ⚠ **세 번 지적된 결함이다.** 검수 목록은 Claude 추출 기준으로 만들어졌다.
      다른 추출기가 다르게 붙인 쌍은 검수된 적이 없는데도 오답·애매 목록에
      없다는 이유로 "ok" 로 잡힌다. 그러면 추출기를 바꿀 때마다 정답률이
      공짜로 오른다 - 아무도 그 답을 본 적이 없는데.

    ⚠ 쌍 하나라도 미검수면 그 줄이 미검수다. "하나라도 검수됐으면 ok" 는
      갈림에서 새어 나간다 (GPT 가 전기매트에 ['전기매트','전기요'] 를 붙인
      경우 - '전기요' 는 검수된 적이 없다).

    ⚠ 코드가 정답 판정을 하지 않는다. 미검수는 tsv 로 뽑아 사람이 검수한다.
    """
    import sys

    sys.path.insert(0, "scripts")
    from audit_tally import load_reviewed_pairs, tally, verdict

    reviewed = {("A", "완구"), ("B", "전기매트")}

    # 검수된 쌍만 정답이다.
    assert verdict("A", ["완구"], {}, {}, reviewed) == "ok"
    # 갈림에서 일부만 검수됐으면 미검수다.
    assert verdict("B", ["전기매트", "전기요"], {}, {}, reviewed) == "unreviewed"
    # 아예 다른 품목이면 미검수다.
    assert verdict("A", ["전기방석"], {}, {}, reviewed) == "unreviewed"
    # 오답·애매 목록이 미검수보다 우선한다 - 이미 사람이 본 것이다.
    assert verdict("A", ["전기방석"], {"A": {"전기방석"}}, {}, reviewed) == "wrong"
    # reviewed 를 안 주면 예전 동작 - Claude 기준 재생·락이 그 경로다.
    assert verdict("A", ["전기방석"], {}, {}) == "ok"

    # tally 는 두 숫자를 낸다: 검수된 값과 미검수 포함 상한.
    scope = {"A": "대상", "B": "대상", "C": "대상"}
    results = {"A": ["완구"], "B": ["전기매트", "전기요"], "C": ["전기방석"]}
    got = tally(results, scope=scope, audit=({}, {}), reviewed=reviewed)
    assert got["ok"] == 1, got
    assert got["unreviewed"] == 2, got
    assert got["ok_upper"] == 3, got

    # 실제 원자료로 쌍 집합이 만들어지는지 - 형식이 바뀌면 여기서 깨진다.
    root = Path(__file__).resolve().parents[1]
    src = root / "tests" / "fixtures" / "단건경로_136건.json"
    if src.exists():
        pairs = load_reviewed_pairs(src)
        assert pairs, "원자료에서 검수된 쌍을 못 읽었다"
        assert all(isinstance(p, tuple) and len(p) == 2 for p in pairs)


def test_the_comparison_script_reports_both_numbers_and_dumps_unreviewed():
    """추출기 대조 스크립트가 두 숫자를 내고 미검수를 파일로 남기는지.

    ⚠ "미검수 포함 상한" 만 보고하면 부풀린 숫자가 발표로 새어 나간다.
      두 숫자를 함께 내고, 상한 쪽에는 "검수 전에는 이 값을 쓰지 않는다" 를
      화면에 적는다.
    """
    root = Path(__file__).resolve().parents[1]
    src = (root / "scripts" / "compare_extractors.py").read_text(encoding="utf-8")

    assert "load_reviewed_pairs" in src
    assert "reviewed=reviewed" in src
    assert "정답(검수된 쌍만)" in src
    assert "정답 상한(미검수 포함)" in src
    assert "검수 전에는 이 값을 쓰지 않는다" in src
    # 미검수 목록을 파일로 남긴다 - 사람이 검수한다.
    assert "unreviewed_out" in src
    assert "사람이 검수해야 한다" in src
    # 라벨을 강제한다 - 경로·입력·분모 없는 숫자는 쓰지 않는다.
    assert '"--label", required=True' in src
    # 비대상 부착이 결과에 보여야 한다 - 0 이 아니면 못 간다.
    assert "비대상 → 부착" in src
