#!/usr/bin/env python3
"""정부 리콜 제품명에 셀러 껍데기를 씌운 합성 표본.

정답을 아는 채로 대량 측정할 수 있는 것이 핵심 이점이다. 씨앗은 리콜
전기·생활용품 중 **품목명이 등급표에 정확히 있는 것만** 골랐다 - 그래야
정답이 확정되고 오답을 자동 판정할 수 있다.

⚠ 이것으로 잴 수 있는 것과 없는 것을 구분해야 한다.

    잰다    수식어·브랜드·스펙·연관품목에 흔들리지 않는가
    못 잰다 셀러 말을 알아듣는가

  정부가 "충전식 휴대전등" 이라 쓴 것을 셀러는 "랜턴" 이라 부르는데, 그
  대응은 생성으로 만들 수 없고 실데이터에만 있다. 합성 정확도를 실제
  매칭률로 읽으면 안 된다.

⚠ 껍데기 어휘를 우리 파서의 _MODIFIERS 로 채우면 시험지를 우리가 만들고
  우리가 푸는 셈이 된다. 아래 목록은 실데이터에서 캤다 - 시피님 실상품
  30건과 리콜 국외 제품명의 상위 어절이며, 우리 _MODIFIERS 와 겹치는 것은
  60개 중 4개뿐이다.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random

# ── 껍데기 어휘. 전부 실데이터 출처다 ────────────────────────────────
# 시피님 실상품 30건에서
BRANDS = ("신일", "샤오미", "스노우맨", "다이슨", "쿠쿠", "한일", "보아르", "오아",
          "루메나", "아이닉", "일렉트로맨", "휴테크")
PRE_MODS = ("미니", "휴대용", "접이식", "무선", "충전식", "탁상용", "감성", "고급형",
            "슬림", "대용량", "초경량", "다용도", "프리미엄", "가정용")
USES = ("캠핑용", "차량용", "사무실", "실내", "야외", "여행용", "업소용", "선물용",
        "베란다", "현관", "주방", "욕실")
SPECS = ("14인치", "10000mAh", "1.7L", "500ml", "30W", "5W", "15W", "1000개",
         "20구", "3단", "7엽", "5.3", "20L", "2구")
MODELS = ("SIF-B1424CL", "WPB25ZM", "LPL-01", "KM-2200", "HV-500", "XT-9",
          "DW-1200", "AC-77", "PRO-3", "MAX-II")
COLORS = ("화이트", "블랙", "퍼플", "브라운", "실버", "아이보리")
TAILS = ("세트", "정품", "무료배송", "당일발송", "해외구매", "리뷰이벤트")


def build(seed_item: str, decoys: list[str], rng: random.Random) -> str:
    """씨앗 품목명에 껍데기를 씌운다.

    연관 품목 섞기는 도매 상품명의 전형이다 - "무드등 선풍기 가습기" 처럼
    다른 품목명을 끼워 넣는다. 실제로 이 패턴이 오답 3건을 만들었다.
    """
    parts: list[str] = []
    if rng.random() < 0.45:
        parts.append(rng.choice(BRANDS))
    for _ in range(rng.randint(0, 2)):
        parts.append(rng.choice(PRE_MODS))
    if rng.random() < 0.30:
        parts.append(rng.choice(USES))

    parts.append(seed_item)

    # 연관 품목 섞기. 정답은 여전히 seed_item 이다.
    for _ in range(rng.randint(0, 2)):
        if decoys and rng.random() < 0.5:
            parts.append(rng.choice(decoys))

    for pool, prob in ((SPECS, 0.5), (MODELS, 0.25), (COLORS, 0.3), (TAILS, 0.25)):
        if rng.random() < prob:
            parts.append(rng.choice(pool))
    return " ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seeds", help="[[품목명, 등급, 품목군], ...] JSON")
    ap.add_argument("-n", "--count", type=int, default=1000)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args()

    seeds = json.loads(pathlib.Path(args.seeds).read_text(encoding="utf-8"))
    rng = random.Random(args.seed)
    names = [s[0] for s in seeds]

    rows = []
    for _ in range(args.count):
        item, grade, category = rng.choice(seeds)
        # 미끼는 씨앗 자신을 빼고 고른다
        decoys = [n for n in rng.sample(names, min(6, len(names))) if n != item]
        rows.append(
            {
                "title": build(item, decoys, rng),
                "answer_item": item,
                "answer_grade": grade,
                "category": category,
            }
        )
    pathlib.Path(args.out).write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{len(rows)}건 → {args.out}")


if __name__ == "__main__":
    main()
