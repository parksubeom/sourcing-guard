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

_SLIME = "완구 매직액체 슬라임 장난감 KC 인증번호 CB061R2170-3018 대상연령 3세 이상"

DEMOS: list[dict[str, str]] = [
    {
        "tone": "green",
        "title": "인증 조회됨 · 리콜 없음",
        "note": "도매꾹 슬라임 (CB061R2170-3018)",
        "text": _SLIME,
    },
    {
        "tone": "amber",
        "title": "같은 상품에 재질 한 줄 추가",
        "note": '"PVC 재질" 표기가 더해지면 신호가 바뀝니다',
        "text": _SLIME + " 재질 PVC",
    },
    {
        "tone": "red",
        "title": "인증은 적합인데 리콜된 상품",
        "note": "모형완구 기차놀이 (CB067R317-5002)",
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

_PREVIEW_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "demo_amber_result.json"

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
        # ⚠ 리콜 축 주석에서 **시각에 매인 절**을 뗀다. `_axes` 는
        #   "2026-09-08 공표분까지 · 오늘 12:33 갱신" 처럼 쓰는데, 이 카드는
        #   얼어 있으므로 "오늘 … 갱신" 은 **내일이면 거짓**이다. 앞 절(무엇과
        #   대조했나)만 남긴다 - 그것은 그 실측이 실제로 대조한 범위다.
        "axes": [{**a, "note": (a.get("note") or "").split(" · ")[0]}
                 for a in raw["axes"]],
        # 화면이 " — " 에서 두 줄로 나눈다. **문장은 안 바꾼다.**
        "headline": raw["headline"],
        "product_name": raw["product_name"],
        "rows": rows,
        "grade_source_url": (grade or {}).get("source_url"),
        "recall_data_as_of": raw.get("recall_data_as_of"),
    }
