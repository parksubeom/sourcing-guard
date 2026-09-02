"""골든셋 회귀 테스트.

실제 도매·구매대행 상세페이지 11건에서 뽑은 판정 정답을 고정한다. 11건 전부
KC 인증번호가 없다 — 구매대행 소싱 상품은 인증정보가 없는 것이 정상이고,
우리 서비스의 본체는 그럴 때 무엇을 확인해야 하는지 답하는 것이다.

이 테스트는 리콜 인덱스 없이 돈다(추출·분류·범위 판정은 리콜과 독립적이다).
리콜 매칭 자체는 test_recall_index / test_watchlist 가 따로 검증한다.

⛔ 통과 수를 커버리지로 읽지 말 것. 11건 전부 기대 신호가 unknown 이고,
KC 번호·이미지·무선 케이스가 각각 0건이다. 즉 데모 3종이 쓰는 KC 번호 경로와
전파인증 축은 이 셋이 전혀 덮지 않는다. 무엇이 비었고 왜 지금 채우지 않는지는
golden/golden_set.yaml 머리말의 ⛔ 블록에 적어뒀다. 아래
test_gap_note_still_matches_the_data 가 그 노트를 데이터와 맞춰 지킨다.

────────────────────────────────────────────────────────────────
기본은 목 모드다 (CLAUDE.md §7: 테스트가 네트워크에 의존하면 안 된다)
────────────────────────────────────────────────────────────────
이 파일은 케이스마다 extract() 를 부르므로, 개발자 .env 에 키가 들어오면
케이스마다 실제 Anthropic API 를 때린다 — 실측 2026-09-01 로 이 파일의 한
테스트가 43초였다. conftest.py 의 autouse 픽스처가 목 모드를 강제한다.

실제 LLM 으로 재는 것은 계측이지 회귀 테스트가 아니다:

    SG_LIVE_LLM=1 pytest tests/test_golden_set.py   # 같은 단정을 LLM 으로
    python scripts/golden_report.py                 # 필드별 정확도 리포트

목 모드에서도 신호·필수 finding·필수 추출은 그대로 단정한다. 품목 분류만
느슨해지는데, 기대값이 LLM 답으로 갱신돼 있고 휴리스틱은 키워드로만 분류하기
때문이다 (아래 used_llm 분기 참조).
"""

from pathlib import Path

import yaml

from sourcing_guard.extractor import extract
from sourcing_guard.kats_client import KatsClient
from sourcing_guard.scorer import score
from sourcing_guard.verifier import RuleBook, verify

_GOLDEN = yaml.safe_load(
    (Path(__file__).parent / "golden" / "golden_set.yaml").read_text(encoding="utf-8")
)["cases"]
_KATS = KatsClient(None, None, mock=True)
_RULES = RuleBook()


def _run(text: str):
    from sourcing_guard.extractor import stats

    before = stats.llm
    facts = extract(text)
    used_llm = stats.llm > before
    findings = verify(facts, _KATS, _RULES, None)
    return facts, findings, score(facts, findings), used_llm


def _ids():
    return [c["id"] for c in _GOLDEN]


import pytest  # noqa: E402


@pytest.mark.parametrize("case", _GOLDEN, ids=_ids())
def test_golden_case(case):
    facts, findings, result, used_llm = _run(case["text"])
    kinds = {f.kind.value for f in findings}
    exp = case["expect"]

    if "signal" in exp:
        # Signal enum 은 대문자('UNKNOWN'), 골든셋은 소문자로 읽기 쉽게 적는다.
        assert result.signal.value.lower() == exp["signal"].lower(), (
            f"{case['id']}: 신호 기대 {exp['signal']}, 실제 {result.signal.value}"
        )

    if "category" in exp:
        # 품목 분류는 LLM 이 실제로 돌았을 때만 검증한다.
        #
        # 기대값이 LLM 답으로 갱신돼 있다(household/electrical). 휴리스틱은
        # 키워드로만 분류해 의자·휴지통·LED 를 unclassified 로 낸다. CI 에는
        # 키가 없어 휴리스틱으로 도는데, 거기서 품목을 단정하면 "휴리스틱이
        # 기대값이다" 로 되돌아가고 갱신한 의미가 사라진다.
        #
        # 나머지 단정(신호·필수추출·필수finding)은 두 모드 모두에서 지킨다 —
        # 그것들이 실제로 사용자가 보는 결과다.
        # 기대값을 목록으로 적을 수 있다. 판단이 갈릴 수 있는 입력에서 LLM 이
        # 두 답 사이를 오가는데, 사용자가 보는 신호가 같으면 둘 다 받는다.
        # 어느 경우에 목록을 썼고 실측이 어땠는지는 골든셋 주석에 적는다.
        want = exp["category"]
        want = set(want) if isinstance(want, list) else {want}
        if used_llm:
            assert facts.category.value in want, (
                f"{case['id']}: 품목 기대 {sorted(want)}, 실제 {facts.category.value}"
            )
        else:
            assert facts.category.value in want | {"unclassified"}, (
                f"{case['id']}: 휴리스틱 모드인데 품목이 {facts.category.value} 입니다"
            )

    for kind in exp.get("must_find", []):
        assert kind in kinds, f"{case['id']}: finding '{kind}' 없음. 실제: {sorted(kinds)}"

    for token in exp.get("must_extract", []):
        haystack = " ".join(facts.materials + facts.substances_mentioned + facts.kc_numbers)
        assert token in haystack, (
            f"{case['id']}: '{token}' 추출 실패. materials={facts.materials}"
        )


def test_no_sample_has_a_kc_number_in_its_pasted_text():
    """붙여넣은 상품정보 표에 KC 번호가 없다는 것 자체가 시장 사실이다.

    이 전제가 깨지면(표본이 바뀌면) 골든셋의 성격이 달라진 것이므로 알린다.

    ⚠ 범위는 text 다. 골든셋 text 는 원본 캡처의 '상품정보 표' 만 옮겨 적은
      것이고, KC 마크는 보통 그 표가 아니라 페이지 하단 이미지에 붙는다.
      그래서 이 테스트가 통과한다고 "원본 페이지에 인증번호가 없었다" 가
      되지는 않는다.

      원본 캡처 11장이 저장소에 없어 이미지 쪽은 확인하지 못했다. 캡처가
      확보되면 골든셋에 images 를 배선하고 led-penlight 부터 다시 봐야 한다
      (근거와 순서는 golden_set.yaml 머리말에 적어뒀다).
    """
    without = [c["id"] for c in _GOLDEN if not extract(c["text"]).kc_numbers]
    assert len(without) == len(_GOLDEN), (
        f"KC 번호가 있는 표본이 생겼습니다: {set(_ids()) - set(without)}. "
        "골든셋 성격이 바뀌었으니 정답을 재검토하세요."
    )


def test_out_of_scope_items_short_circuit_to_a_single_finding():
    """식품·화장품은 '판별 못 함' 이 아니라 '소관 아님' 이다.

    OUT_OF_SCOPE 는 나머지 검증을 건너뛰고 단일 finding 으로 끝나야 한다 —
    화장품에 '재질 확인 요청' 을 붙이면 엉뚱하다.
    """
    for cid in ("cleansing-foam", "skinfoou-ampoule", "bamboo-salt-set"):
        case = next(c for c in _GOLDEN if c["id"] == cid)
        _, findings, _, _ = _run(case["text"])
        assert [f.kind.value for f in findings] == ["out_of_scope"], cid


def test_bear_keyring_is_not_forced_into_toy_category():
    """인형 붙은 키링을 완구로 단정하면 품목 오판정이다 (R1).

    액세서리이므로 완구 기준(프탈레이트·납)을 자동으로 들이대지 않는다.
    """
    case = next(c for c in _GOLDEN if c["id"] == "bear-keyring")
    facts, _, _, _ = _run(case["text"])
    assert facts.category.value != "children_toy"


# ---------------------------------------------------------------------------
# 소관 밖 판정의 오탐 — 리콜된 완구를 통째로 놓치게 만든다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "모형완구 기차놀이 제우스 완구 장난감 KC 인증번호 CB067R317-5002",
    "자동차 장난감",
    "유아차",
    "젤리 슬라임 완구",
    "아이스크림 인형",
    "크림색 캔버스 가방",
    "소금인형 장식품",
])
def test_common_words_do_not_trigger_out_of_scope(text):
    """한국어 부분 문자열 매칭에는 단어 경계가 없다.

    "차" 한 글자가 기차놀이·자동차·유아차에 걸렸고, OUT_OF_SCOPE 가 인증·리콜
    검증을 통째로 건너뛰므로 데모용 리콜 상품이 식품으로 판정돼 RED 가
    사라졌다. 한두 글자 일반 명사를 힌트로 쓰지 않는다.
    """
    from sourcing_guard.scoping import out_of_scope_reason

    assert out_of_scope_reason(text) is None, f"'{text}' 가 소관 밖으로 오판됩니다"


@pytest.mark.parametrize("text,expect", [
    ("코시앙 클렌징폼 EWG 그린등급 화장품책임판매업자", "화장품"),
    ("850C 죽염 천일염 통후추 선물세트", "식품"),
    ("스킨푸드 앰플 화장품제조업자", "화장품"),
    ("의료기기 혈압계", "의료기기"),
])
def test_real_out_of_scope_items_are_still_caught(text, expect):
    """오탐을 줄이면서 진짜 소관 밖을 놓치면 안 된다."""
    from sourcing_guard.scoping import out_of_scope_reason

    reason = out_of_scope_reason(text)
    assert reason and expect in reason, f"'{text}' -> {reason}"


def test_in_scope_evidence_wins_over_a_scope_hint():
    """완구·어린이 표기가 있으면 소관 밖으로 단락하지 않는다.

    OUT_OF_SCOPE 는 인증·리콜 검증을 건너뛴다. 애매하면 검증하는 쪽이 안전하다 —
    놓친 리콜이 불필요한 안내보다 비싸다 (R6).
    """
    from sourcing_guard.scoping import out_of_scope_reason

    assert out_of_scope_reason("화장품 놀이세트 어린이 완구") is None
    assert out_of_scope_reason("화장품 클렌징폼 EWG") is not None


def test_recalled_toy_demo_still_reaches_red():
    """데모 클라이맥스가 살아 있는가. 이 케이스가 발표의 마지막 장면이다."""
    from sourcing_guard.models import FindingKind

    facts = extract("모형완구 기차놀이 제우스 완구 장난감 KC 인증번호 CB067R317-5002")
    findings = verify(facts, _KATS, _RULES, None)
    kinds = {f.kind for f in findings}

    assert FindingKind.OUT_OF_SCOPE not in kinds
    assert facts.kc_numbers == ["CB067R317-5002"]


def test_out_of_scope_needs_code_agreement_not_just_the_llm():
    """LLM 이 out_of_scope 라 해도 코드가 근거를 못 찾으면 단락하지 않는다.

    OUT_OF_SCOPE 는 인증·리콜 검증을 통째로 건너뛰는 유일한 분류다. 그런데 LLM
    분류는 완전히 결정론적이지 않다 - 진주 귀걸이를 10회 돌렸더니 2회
    out_of_scope 로 흔들렸다(액세서리는 공통안전기준 1항 제외 대상이 아니므로
    오분류다). 같은 페이지가 20% 확률로 검증을 건너뛰면 놓친 리콜이 생긴다 (R6).
    """
    from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts

    # LLM 이 out_of_scope 라 했지만 본문에 화장품·식품 표기가 없는 경우
    facts = ProductFacts(
        product_name="귤팩토리 진주 귀걸이",
        category=ItemCategory.OUT_OF_SCOPE,
    )
    findings = verify(facts, _KATS, _RULES, None)
    kinds = {f.kind for f in findings}

    assert FindingKind.OUT_OF_SCOPE not in kinds, "LLM 단독으로 단락했습니다"
    assert len(findings) > 1, "검증을 건너뛰었습니다"


def test_code_evidence_still_short_circuits():
    """오탐을 막으면서 진짜 소관 밖을 놓치면 안 된다.

    화장품책임판매업자·EWG 같은 표기는 흔들리지 않는 하드 신호다.
    """
    from sourcing_guard.models import FindingKind, ItemCategory, ProductFacts

    facts = ProductFacts(
        product_name="코시앙 클렌징폼",
        substances_mentioned=["화장품책임판매업자", "EWG"],
        category=ItemCategory.UNCLASSIFIED,   # LLM 이 놓쳐도 코드가 잡는다
    )
    findings = verify(facts, _KATS, _RULES, None)

    assert [f.kind for f in findings] == [FindingKind.OUT_OF_SCOPE]


def test_golden_categories_document_the_llm_answer():
    """기대값이 LLM 답으로 갱신됐다는 사실을 고정한다.

    되돌리려면 이 테스트를 먼저 봐야 한다 - 휴리스틱 시절 값으로 조용히
    돌아가면 LLM 을 켠 의미가 사라진다.
    """
    by_id = {c["id"]: c["expect"].get("category") for c in _GOLDEN}
    assert by_id["zabara-chair"] == "household"
    assert by_id["slim-bin"] == "household"
    assert by_id["led-penlight"] == "electrical"


# ---------------------------------------------------------------------------
# 커버리지 구멍을 적어둔 노트가 낡지 않게
#
# golden_set.yaml 머리말에 "이 셋이 덮지 않는 경로" 를 적어뒀다. 누군가 구멍을
# 채우면 그 노트가 거짓이 되는데, 노트는 주석이라 아무도 고쳐주지 않는다.
# 그래서 노트의 수치를 여기서 다시 재고 어긋나면 실패시킨다.
# ---------------------------------------------------------------------------


def test_gap_note_still_matches_the_data():
    """머리말의 "이미지 0건 · KC 0건 · 무선 0건 · 전부 unknown" 을 재측정한다.

    실패하면 골든셋이 좋아졌다는 뜻이다. 케이스를 되돌리지 말고
    golden_set.yaml 머리말의 ⛔ 블록을 갱신할 것.
    """
    import re

    from sourcing_guard.kats_client import CERT_NUMBER_RE

    wireless = ("무선", "블루투스", "bluetooth", "wifi", "와이파이", "페어링")
    n_img = sum(
        1 for c in _GOLDEN
        if {"image", "images", "image_b64"} & set(c)
        or re.search(r"(?i)\.(png|jpg|jpeg)", c["text"])
    )
    n_kc = sum(1 for c in _GOLDEN if CERT_NUMBER_RE.findall(c["text"]))
    n_rf = sum(
        1 for c in _GOLDEN
        if any(w in c["text"].lower() for w in wireless)
    )
    signals = {c["expect"]["signal"] for c in _GOLDEN}

    assert (n_img, n_kc, n_rf) == (0, 0, 0), (
        f"골든셋이 넓어졌다 (이미지 {n_img} · KC {n_kc} · 무선 {n_rf}). "
        "golden_set.yaml 머리말의 ⛔ 블록을 갱신할 것."
    )
    assert signals == {"unknown"}, (
        f"기대 신호가 늘었다: {sorted(signals)}. 머리말의 ⛔ 블록을 갱신할 것."
    )


def test_gap_note_is_present_in_the_yaml():
    """노트 자체가 지워지면 통과 수를 커버리지로 오독하게 된다."""
    text = (Path(__file__).parent / "golden" / "golden_set.yaml").read_text(encoding="utf-8")
    assert "이 회귀 셋이 덮지 않는 경로" in text
    assert "1523955" in text          # 통과 수가 커버리지가 아니라는 실례
