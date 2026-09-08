"""4-d-3. **어느 번호가 어느 제도인지 verifier 가 정한다.** 추출기가 아니다.

전안법 KC 와 전파법 적합성평가는 별개 제도이고 조회 기관도 다르다
(SafetyKorea vs emsit/RRA). 추출기 프롬프트가 "KC 번호를 rf_numbers 에 넣지
마십시오" 라고 적어 둬도 **반대 방향으로는 새는 것을 막지 못한다.**

⚠ 프롬프트로 고치지 않는다 - 바꾸면 R7 에 따라 235건을 LLM 으로 다시 재야
  한다. 번호 형식은 하드 데이터이므로 결정론적 코드가 가린다(추출기의
  `CERT_NUMBER_RE` 병합과 같은 계열).
"""
from __future__ import annotations

from sourcing_guard.models import ProductFacts
from sourcing_guard.verifier import split_cert_regimes

def test_rf_number_in_kc_numbers_is_moved_to_the_rf_axis():
    """**같은 번호로 두 축에서 "조회되지 않습니다" 가 뜨던 것을 막는다.**

    실측(2026-09-08): 추출기가 `MSIP-CMI-DVT-Rainbow`(전파번호)를
    `kc_numbers` 에 담아 왔다. 그러면

        kc_not_found      AMBER   SafetyKorea 에 없다 (소관이 아니니 당연하다)
        rf_cert_not_found AMBER   전파 쪽에도 없다

    가 함께 떴다. 앞의 것은 **소관이 아닌 DB 에 물어서 안 나온 것**이고,
    부재를 증거로 읽는 R3-b 위반의 입구다.

    ⚠ 프롬프트로 고치지 않는다 - 바꾸면 R7 에 따라 235건을 다시 재야 한다.
      번호 형식은 하드 데이터이므로 결정론적 코드가 가린다.
    """
    facts = ProductFacts(
        product_name="LED 무드등 블루투스 스피커",
        kc_numbers=["MSIP-CMI-DVT-Rainbow", "CB061R2170-3018"],
        rf_numbers=[],
    )
    got = split_cert_regimes(facts)
    assert got.kc_numbers == ["CB061R2170-3018"]
    assert got.rf_numbers == ["MSIP-CMI-DVT-Rainbow"]


def test_split_cert_regimes_is_idempotent():
    """`verify()` 머리와 `main.py` 양쪽에서 부른다. 두 번 불러도 같아야 한다."""
    once = split_cert_regimes(
        ProductFacts(kc_numbers=["R-R-nDC-A205", "CB061R2170-3018"])
    )
    twice = split_cert_regimes(once)
    assert (once.kc_numbers, once.rf_numbers) == (twice.kc_numbers, twice.rf_numbers)
    assert once.kc_numbers == ["CB061R2170-3018"]
    assert once.rf_numbers == ["R-R-nDC-A205"]


def test_split_cert_regimes_does_not_duplicate_or_touch_kc_only_input():
    # 이미 rf_numbers 에 있으면 중복을 만들지 않는다.
    dup = split_cert_regimes(
        ProductFacts(kc_numbers=["MSIP-CMI-DVT-Rainbow"],
                     rf_numbers=["MSIP-CMI-DVT-Rainbow"])
    )
    assert dup.kc_numbers == []
    assert dup.rf_numbers == ["MSIP-CMI-DVT-Rainbow"]

    # 옮길 것이 없으면 아무것도 바꾸지 않는다.
    same = ProductFacts(kc_numbers=["CB061R2170-3018"], rf_numbers=[])
    assert split_cert_regimes(same).kc_numbers == ["CB061R2170-3018"]


def test_main_corrects_the_facts_it_shows_on_screen():
    """화면의 "읽은 값" 패널과 findings 가 어긋나면 안 된다.

    `verify()` 안에서만 가르면 findings 는 맞지만 `score(facts, ...)` 에
    넘어가는 facts 는 원본이라, 화면에는 전파번호가 KC 번호로 남는다.
    """
    from pathlib import Path

    src = Path("sourcing_guard/main.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    assert "facts = split_cert_regimes(facts)" in code
    # verify 보다 먼저 불러야 한다.
    assert code.index("facts = split_cert_regimes(facts)") < code.index("findings = verify(")
