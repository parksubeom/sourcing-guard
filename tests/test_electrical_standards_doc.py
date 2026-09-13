"""[I] 문서의 숫자가 원자료와 같은지 본다. **네트워크 없이** 검사한다.

⚠ 문서가 코드·원자료보다 앞서 나가는 것이 이 저장소의 반복 결함이다. 숫자를
  적을 때마다 가드를 같이 만든다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DOC = _ROOT / "docs/I_전기용품안전기준_조사.md"
_RAW = _ROOT / "tests/fixtures/전기용품_안전기준_고시_2026-09-12.json"


def test_the_notice_count_matches_the_fixture():
    raw = json.loads(_RAW.read_text(encoding="utf-8"))
    doc = _DOC.read_text(encoding="utf-8")
    n = raw["전기용품_안전기준_건수"]
    assert n == len(raw["고시"]), "픽스처 자체가 어긋난다"
    assert f"**{n}건**" in doc, f"문서가 {n}건이라고 말하지 않는다"
    assert f"총 {raw['총건수']}건" in doc


def test_the_doc_keeps_the_numbers_it_could_not_reproduce():
    """⚠ 옛 기록 75·37 을 지우지 않고 **재현 못 했다**고 적는다.

    도매꾹 개인정보 실측의 "84/100" 과 같은 처리다 - 옛 수를 옮겨 적지 않고
    다시 잰 수를 쓰되, 옛 수가 있었다는 사실은 남긴다 (CLAUDE.md R4 정정 절).
    """
    doc = _DOC.read_text(encoding="utf-8")
    assert "**75건**" in doc and "**37건**" in doc
    assert "재구성하지 못했다" in doc


def test_the_doc_says_the_clause_cannot_be_cited():
    """[I] 의 결론 - 조문을 인용할 수 없어서 룰을 못 넣는다."""
    doc = _DOC.read_text(encoding="utf-8")
    assert "조문을 인용할 수 없다" in doc
    # 대조 증거가 수치로 있어야 한다 (빈 조문내용 · 별표 없음).
    assert "2,233" in doc and "1,569,120" in doc
    assert "`''` (빈 문자열)" in doc


def test_the_doc_matches_the_rule_db():
    """electrical 룰이 실제로 1건·draft·review_excluded 인지 코드와 대조한다."""
    import yaml

    data = yaml.safe_load((_ROOT / "sourcing_guard/data/hazard_rules.yaml").read_text(
        encoding="utf-8"))
    rules = data["rules"] if isinstance(data, dict) and "rules" in data else data
    elec = [r for r in rules
            if "electrical" in (r.get("applies_to") or [])]
    assert len(elec) == 1, f"electrical 룰이 {len(elec)}건이다 - 문서를 갱신해라"
    (rule,) = elec
    assert rule["id"] == "KC-ELEC-LED-PERF"
    assert rule["status"] == "draft"
    assert rule.get("review_excluded"), "검수 제외 사유가 없다"
    assert rule.get("annex_no") is None, "부속서 번호가 생겼다 - 문서를 갱신해라"

    doc = _DOC.read_text(encoding="utf-8")
    assert "KC-ELEC-LED-PERF" in doc and "review_excluded" in doc
    # verified 가 0 이라는 주장.
    assert not [r for r in elec if r["status"] == "verified"]


def test_the_doc_is_marked_as_investigation_only():
    """⚠ 코드를 짜지 않았다는 것을 문서가 스스로 말한다 (총괄 지시 · R5)."""
    doc = _DOC.read_text(encoding="utf-8")
    assert "조사만 했다" in doc
    assert "제출(9/20) 전에는 하지 않는다" in doc
    assert "착수 조건" in doc


def test_the_led_figures_come_from_the_press_release_source():
    """[I 정정 4 · 2026-09-13] LED 수치가 **원자료와 같고 URL 이 붙어 있어야** 한다.

    ⚠⚠ 이 문서가 `국표원 해외직구 안전성조사(2025-06)` 이라 적고 있었다.
      **수치(22/10)는 맞았고 날짜와 출처가 틀렸다.** 22/10 은 2026-08-06
      산업통상부 건이고, 2025-06 건은 [G-2] 가 원문을 못 찾아 **수록하지
      않기로** 한 것이다.

      `hazard_rules.yaml` 은 `143b48c` 에서 이미 고쳐졌는데 이 문서만 낡아
      있었다 - 같은 사실이 두 곳에 있었고 한쪽만 고쳐졌다 (§6).

    ⚠ 숫자가 맞으면 출처를 안 보게 된다. 그래서 **수치와 URL 을 함께** 잠근다.
    """
    press = json.loads(
        (_ROOT / "sourcing_guard/static/data/안전성조사_보도자료.json").read_text(
            encoding="utf-8"))
    doc = _DOC.read_text(encoding="utf-8")

    led_rows = []
    for survey in press["조사"]:
        for item in survey.get("품목별") or []:
            if "LED" in item.get("품목", "") and item.get("조사_수"):
                led_rows.append((survey, item))
    assert led_rows, "원자료에 LED 조사 수치가 없다"

    for survey, item in led_rows:
        pair = f"{item['조사_수']}개 중 {item['부적합_수']}개"
        assert pair in doc, f"{survey['게시일']} 의 LED {pair} 가 문서에 없다"
        assert survey["게시일"] in doc, f"{survey['게시일']} 이 문서에 없다"
        assert survey["url"] in doc, f"{survey['게시일']} 의 원문 URL 이 문서에 없다"

    # ⚠ 수록하지 않기로 한 출처가 근거로 되살아나면 안 된다.
    assert "2025-06" not in doc.split("정정 (2026-09-13)")[0], (
        "본문에 미수록 출처 2025-06 이 다시 근거로 쓰였다"
    )
