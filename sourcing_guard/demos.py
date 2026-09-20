"""데모 3종. 서버가 단일 출처다.

프론트에 문구를 따로 적으면 서버의 면제 목록과 갈라진다. 그러면 상한을
넘긴 순간 투표자가 버튼을 눌러도 429 를 본다 - 핸드오프 §9 가 "클릭 한 번에
결과가 나와야 한다" 고 적어둔 그 화면이다.

세 케이스는 발표 대본과 같다:
  정상        인증 조회됨, 리콜 없음
  주의        같은 인증번호인데 상세페이지에 "PVC 재질" 한 줄이 더해짐
  위험        인증은 '적합' 인데 프탈레이트 49.5배 초과로 리콜명령
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import Finding
from .scorer import _axes

_SLIME = "완구 매직액체 슬라임 장난감 KC 인증번호 CB061R2170-3018 대상연령 3세 이상"

#: ⚠ `example` 는 **카드에 보여 줄 인증번호**다. `text` 안에 실제로 들어
#:   있어야 한다 - 화면이 없는 번호를 예시로 내밀면 눌렀을 때 다른 것이
#:   검사된다. `tests/test_demos.py` 가 대조한다 (R5).
DEMOS: list[dict[str, str]] = [
    {
        "tone": "green",
        # ⚠ "리콜 없음" 이 아니라 **"리콜 일치 없음"** 이다 (2026-09-20 총괄 §1).
        #   우리가 한 것은 공표 목록과의 대조이고, 공표되지 않은 결함은
        #   대조할 수 없다 - `_axes` docstring 이 같은 말을 적고 있다 (§9).
        "title": "인증 조회됨 · 리콜 일치 없음",
        "note": "상세페이지에 인증번호가 적혀 있는 상품입니다.",
        "example": "CB061R2170-3018",
        "text": _SLIME,
    },
    {
        "tone": "amber",
        "title": "같은 상품에 재질 한 줄 추가",
        # ⚠ "신호가 바뀝니다" 는 우리 화면의 사정이고, 셀러에게 값이 있는
        #   것은 **적용 기준이 달라진다** 는 사실이다 (총괄 §1).
        "note": '"PVC 재질" 한 줄이 더해지면 적용 기준이 달라집니다.',
        "example": "CB061R2170-3018 + PVC",
        "text": _SLIME + " 재질 PVC",
    },
    {
        "tone": "red",
        # ⚠ 위험만은 "적합" 을 그대로 쓴다 - 정부 DB 가 인증상태를 그렇게
        #   적어 두었고, 그런데도 리콜된 상품이라는 것이 이 예시의 전부다
        #   (R3-b).
        "title": "인증은 적합인데 리콜된 상품",
        "note": "인증은 적합하지만 리콜 이력이 있는지 확인해보세요.",
        "example": "CB067R317-5002",
        "text": "모형완구 기차놀이 제우스 완구 장난감 KC 인증번호 CB067R317-5002",
    },
]

DEMO_TEXTS: tuple[str, ...] = tuple(d["text"] for d in DEMOS)


# ── 랜딩 히어로의 "예시 결과" 카드 ──────────────────────────────────
#
# ⚠⚠ **랜딩은 `/api/v1/scan` 을 부르지 않는다.** 부르면 방문마다 LLM 호출이
#   나가고, 상한을 넘기는 순간 투표자가 **첫 화면에서 429** 를 본다 (핸드오프
#   §9 가 "클릭 한 번에 결과가 나와야 한다" 고 적어 둔 그 화면이다).
#
#   대신 배포본에서 **실측 1회**로 뜬 결과를 파일로 두고 그것을 그린다.
#   지어낸 문구가 아니라 우리 서버가 실제로 낸 문장이다 (R5).
#
# ⚠ 문장 형식이 바뀌면 `tests/test_landing_preview.py` 가 깨진다. 그때
#   **다시 재서** 파일을 갱신한다 - 손으로 고치면 화면이 없는 문장을 말한다.

# ⚠ **`tests/` 가 아니라 패키지 안이다.** 처음에 tests/fixtures/ 에 뒀더니
#   배포본에서 카드가 안 그려졌다 - Dockerfile 이 `sourcing_guard/` 와
#   `scripts/` 만 담는다. 인수 검사가 잡았고, 잡은 것이 맞다: 이것은 시험
#   자료가 아니라 **앱이 화면에 내는 런타임 자료**다.
_PREVIEW_PATH = Path(__file__).resolve().parent / "data" / "demo_amber_result.json"

#: 예시 카드에 그리는 근거 줄. 열여덟 줄을 다 그리면 히어로가 900px 을 넘는다.
#: 하나는 **주의의 이유**(규제 물질 표기), 하나는 **정상으로 확인된 것**
#: (인증 조회)이라 한 카드 안에서 두 신호를 다 보여 준다.
_PREVIEW_KINDS = ("substance_mentioned", "kc_verified")


@lru_cache(maxsize=1)
def preview() -> dict | None:
    """예시 결과 카드가 읽는 값. 파일이 없으면 **None 이다.**

    ⚠ 빈 껍데기를 만들지 않는다 - 화면은 None 이면 카드를 안 그린다. 없는 것을
      있는 것처럼 그리면 그 순간 R5 를 어긴다.
    """
    try:
        raw = json.loads(_PREVIEW_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    by_kind = {f["kind"]: f for f in raw.get("findings", [])}
    rows = [by_kind[k] for k in _PREVIEW_KINDS if k in by_kind]
    grade = by_kind.get("item_grade_matched") or by_kind.get("item_grade_split")
    return {
        "signal": raw["signal"],
        # ⚠⚠ **축은 파일에서 읽지 않고 다시 계산한다** (2026-09-20).
        #
        #   파일에 적힌 `axes` 는 그날 `_axes` 가 낸 문자열이라, 축 문구가
        #   바뀌면 **랜딩만 옛말을 한다.** 실제로 그렇게 됐다 - "수록됨" 이
        #   "기준 14건" 으로 바뀌었는데 이 카드는 "수록됨" 을 들고 있었다.
        #   `_axes` 는 순수 함수이고 입력(findings)은 그 실측 그대로이므로,
        #   다시 부르는 것은 **지어내는 것이 아니라 같은 계산**이다 (§6 오너 하나).
        #
        # ⚠ `recall_synced_at` 은 넘기지 않는다. "오늘 12:33 갱신" 은 얼어 있는
        #   카드에서 **내일이면 거짓**이다 - 전에는 문자열을 " · " 로 잘라
        #   떼어냈는데, 그 자르기가 뒤에 붙는 다른 절("일치 항목 없음")까지
        #   같이 잘랐다. 애초에 안 만드는 것이 맞다.
        "axes": _axes(
            [Finding.model_validate(f) for f in raw.get("findings", [])],
            raw.get("recall_data_as_of"),
        ),
        # 화면이 " — " 에서 두 줄로 나눈다. **문장은 안 바꾼다.**
        "headline": raw["headline"],
        "product_name": raw["product_name"],
        "rows": rows,
        "grade_source_url": (grade or {}).get("source_url"),
        "recall_data_as_of": raw.get("recall_data_as_of"),
    }
