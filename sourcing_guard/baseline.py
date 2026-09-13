"""발표 숫자의 **단일 출처**.

⚠⚠ 왜 `scripts/` 가 아니라 패키지에 있나
-----------------------------------------
랜딩이 "70.4% · 사람이 검수한 135건" 과 "0건" 을 **그 자리에서 그려야** 한다
(design/README §10-2 · 하드코딩 금지). 전에는 HTML 에 숫자를 적고 검사가
`audit_tally.BASELINE` 과 대조했는데, 그것은 같은 숫자를 **두 곳에 적는**
것이라 §6 이 막는 모양 그대로다 - 한쪽만 고치면 나머지가 거짓말을 계속한다.

그래서 리터럴을 여기 한 곳에 두고 `/healthz` 와 `scripts/audit_tally.py` 가
같은 것을 읽는다. **값은 한 글자도 바뀌지 않았다** - 자리만 옮겼다.

⚠ 이름은 그대로 `audit_tally.BASELINE` 로도 닿는다(재수출). CLAUDE.md §6 의
  `[기준선 변경]` 커밋 규칙과 스무 곳 남짓의 기존 import 가 그 이름을 쓴다.
"""

from __future__ import annotations


#: 재생 기준선. **여기가 한 곳이다** — 스크립트 출력과 `test_docs` 가 같은 값을
#: 본다. 규칙을 고친 뒤 재생해서 이 표와 다르면 **다섯 중 무엇이 움직였는지**
#: 보고에 적는다.
#:
#: ⚠ 2026-09-09 에 이 표가 생긴 이유: 4-e 를 넣었을 때 통과 기준에 없던
#:   `on_vague`(애매 부착)가 1 → 2 로 움직였고 **보고에서 빠졌다.** 기준을
#:   네 개만 세면 다섯째가 조용히 움직인다. 그래서 한 표로 묶고 검사로 잠근다.
#:
#: ⚠ `on_vague` 는 **분모 밖이라 정답률에 안 보인다.** 그러나 화면에는 보인다 -
#:   애매로 판정한 줄에 등급이 붙으면 셀러는 그것을 답으로 읽는다. `off_target`
#:   과 같은 종류다.
#:
#: 재생 명령 (LLM 0회):
#:     PYTHONPATH=. python scripts/replay_single_path.py
#:     PYTHONPATH=. python scripts/replay_single_path.py \
#:       --src tests/fixtures/단건경로_gpt.json
#: **기준 추출기.** 발표 숫자는 이쪽이다 (2026-09-11 결정 · CLAUDE.md R7).
#:
#: ⚠ 화면이 GPT 로 돌므로 기준도 GPT 다. 둘이 갈리면 "이 숫자가 어느 추출기
#:   것인가" 를 말할 수 없고, 실제로 09-08 ~ 09-11 사이 그 상태였다.
BASELINE_EXTRACTOR = "gpt"

BASELINE: dict[str, dict[str, int]] = {
    # Claude · 단건 · 상품명만 · 분모 대상 135 · 커밋 e61ce1e 되돌린 뒤
    #
    # ⚠ **2026-09-11 부터 대조군이다.** 기준은 `BASELINE_EXTRACTOR` 쪽이고
    #   이쪽은 "추출기를 바꿔도 등급 결과가 크게 안 흔들린다"(상한 둘 다 113)
    #   의 증거로 남긴다. 지우지 않는다.
    "claude": {
        "denominator": 135,
        "ok": 99,            # 검수된 쌍만 (73.3%)
        "ok_upper": 113,     # 미검수 포함 상한 (83.7%)
        "unreviewed": 14,
        "vague": 2,
        "wrong": 1,
        "missed": 19,
        "off_target": 0,     # ⚠ 0 이 아니면 발표에 쓸 수 없다
        "on_vague": 1,       # 포워드테크 다림질 매트 → 스팀다리미 (오답표에 있던 줄)
    },
    # GPT · 같은 조건. **이쪽이 기준이다** (BASELINE_EXTRACTOR).
    "gpt": {
        "denominator": 135,
        "ok": 95,            # (70.4%)
        "ok_upper": 113,     # (83.7%) — Claude 와 우연히 같다
        "unreviewed": 18,
        "vague": 2,
        "wrong": 1,
        "missed": 19,
        "off_target": 0,
        "on_vague": 3,       # 넉박스 ×2 → 커피메이커 · 다림질 매트 → 스팀다리미
    },
}

#: **배치(대량 검사) 경로**의 같은 다섯 숫자. LLM 없이 `lookup_all` 로만 돈다.
#:
#: ⚠⚠ **2026-09-13 에 이 표를 만든 이유: 제출문이 배치를 상한 하나로만 적고
#:   있었다.** "대량 검사 경로는 82.2% 입니다" 라고 썼는데 82.2% 는 `ok_upper`
#:   (111/135)이고 검수된 정답은 **96(71.1%)** 이다. 바로 앞 문장이 "검수 전
#:   숫자를 검수된 숫자처럼 쓰지 않는다" 인데 그 다음 문장이 그걸 어겼다.
#:
#:   숫자가 `test_item_grades` 에 하드코딩된 111 과 제출문의 82.2% 두 곳에
#:   따로 있었고, 둘을 잇는 것이 없었다 (§6 "같은 판단을 두 곳에 적지 마라").
#:   이제 여기가 한 곳이다.
#:
#: ⚠ 단건과 다른 값인 것이 정상이다. 배치는 상품명만 보고 LLM 추출을 안 탄다 -
#:   `product_name` 정리가 없으니 원제목 그대로 매칭한다.
#:
#: 재생 (LLM 0회):
#:     PYTHONPATH=. python -c "
#:     import sys; sys.path.insert(0,'scripts')
#:     from audit_tally import batch_tally; print(batch_tally())"
BASELINE_BATCH: dict[str, int] = {
    "denominator": 135,
    "ok": 96,            # 검수된 쌍만 (71.1%)
    "ok_upper": 111,     # 미검수 포함 상한 (82.2%)
    "unreviewed": 15,
    "vague": 2,
    "wrong": 1,
    "missed": 21,
    "off_target": 0,     # ⚠ 0 이 아니면 발표에 쓸 수 없다
    "on_vague": 2,
}


#: 다섯 기준의 **③** — 표본별 매칭 건수. `lookup_all` 기준이고 LLM 이 없다.
#:
#: ⚠ 2026-09-09 에 살렸다. `scripts/measure_matcher.py` 가 자기검사에서 멈춰
#:   ③ 이 죽어 있었고, 그러면 회귀 방어가 둘뿐이다 (미완 4-f).
#:
#: ⚠ **도매꾹239 는 별칭을 만들 때 쓴 표본이다.** 거기서 재면 우리가 맞춘 것을
#:   다시 맞춘 숫자가 나온다 - 발표에 쓰지 않는다. 회귀 감지용 기준선이다.
#:
#: 재생:
#:     PYTHONPATH=. python scripts/measure_matcher.py --sample tests/fixtures/도매꾹239.txt
#:     PYTHONPATH=. python scripts/measure_matcher.py
BASELINE_MATCH: dict[str, dict[str, int]] = {
    # 09-04 로그는 170/239(71.1%)이었다. 지금 168 이고 **차이 2건은 둘 다 오답을
    # 지운 것**이다 - 정답 손실 0 (미완 4-f · 4-g). 개선/악화로 읽지 말 것:
    # 붙는 수가 줄어든 것이 오답을 지운 결과다.
    #
    #   167 → 168  4-g 에서 `'걸이'` 를 부속품명 목록에서 뺐다. `벽걸이히터` 가
    #              `걸이` 로 읽혀 `전기온풍기` 를 잃고 있었다.
    "도매꾹239": {"matched": 168, "total": 239},
    "새표본235": {"matched": 116, "total": 235},
}


#: 애매 부착으로 알려진 줄. 늘면 그 줄을 보고에 적는다 (기준 ⑤).
BASELINE_ON_VAGUE: dict[str, tuple[str, ...]] = {
    "claude": (
        "포워드테크 휴대용 접이식 다림질 매트 다리미판 좌식 걸이형 스팀 다리미 시트",
    ),
    "gpt": (
        "넉박스 커피 찌꺼기통 홈카페 바리스타 커피머신",
        "포워드테크 휴대용 접이식 다림질 매트 다리미판 좌식 걸이형 스팀 다리미 시트",
        "홈카페 넉박스 커피찌꺼기통 바리스타 커피머신",
    ),
}
