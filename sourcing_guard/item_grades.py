"""품목 등급 조회. "이 품목이 안전인증 대상인가" 를 답한다.

인증번호 부재의 의미는 등급에 따라 완전히 다르다 - 안전인증·안전확인 대상이면
번호가 있어야 하고, 공급자적합성확인 대상이면 없는 것이 정상이다 (CLAUDE.md
R3-b). 그동안 이걸 몰라서 전부 kc_tier_unknown 으로 내보냈다.

매칭 순서는 (1) 수식어 제거 (2) 정확 일치 (3) 별칭 (4) 접두 확장 (5) 역방향 포함이다.

⚠ 어절 매칭은 쓰지 않는다. 'LED 5W 초소형 펜라이트' 를 어절로 맞추면 'LED'
  하나로 LED등기구(안전인증)에 붙는데, 정답은 충전식 휴대전등(안전확인)이라
  등급이 뒤집힌다. 리콜 매칭에서 '153' 이 볼펜과 LED 전등을 잇던 것과 같은
  뿌리다 - 짧고 흔한 토큰은 식별력이 없다.

⚠ 별칭 키도 같은 기준을 따른다. 2~3글자 흔한 단어를 키로 쓰지 않는다
  ('LED' '전등' '가방'). 테스트가 이를 강제한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from .matcher import (
    Confidence,
    Judgement,
    chemical_rival_wins,
    has_consumable_hint,
    judge,
)

_PATH = Path(__file__).parent / "data" / "item_grades.yaml"
_CHILD_PATH = Path(__file__).parent / "data" / "child_item_grades.yaml"

# 상품명에 붙지만 품목을 가리지 않는 말. 떼고 나서 별칭 사전을 본다.
#
# 이걸 먼저 해야 사전이 쓸데없이 커지지 않는다 - 'LED 5W 초소형 펜라이트' 를
# 통째로 키에 넣으면 '휴대용 LED 펜라이트' 는 또 못 맞춘다.
_MODIFIERS = (
    # 크기·형태
    "초소형", "소형", "대형", "중형", "미니", "슬림", "컴팩트", "휴대용", "휴대",
    "접이식", "폴딩", "원터치", "자동", "수동", "무선", "유선", "충전식", "건전지식",
    # 마케팅
    "프리미엄", "고급", "정품", "신상", "특가", "세트", "세트상품", "1+1",
    "다용도", "가정용", "업소용", "산업용", "실내용", "실외용", "야외용",
)

# 규격 표기. 5W · 220V · 3.5mm · 12색 · 100매 같은 것.
_SPEC = re.compile(
    r"\b\d+(?:\.\d+)?\s*"
    r"(?:W|kW|V|kV|A|mA|Hz|kHz|mm|cm|m|kg|g|ml|L|㎸A|kVA|인치|색|매|구|단|개|피스|P)\b",
    re.IGNORECASE,
)


def strip_modifiers(name: str) -> str:
    """상품명에서 수식어와 규격 표기를 뗀다.

    'LED 5W 초소형 펜라이트' -> 'LED 펜라이트'

    ⚠ **어절 단위로만 뗀다.** 부분 문자열로 지우면 '자동' 이 '자동차용' 을
      파괴해서 '자동차용 타이어' 가 '차용 타이어' 가 되고, 그 결과 접두 확장이
      '승용차용 타이어' 로 잘못 붙는다 - 실제로 겪었다.

      한국어 부분 문자열 매칭에는 단어 경계가 없다. 이 세션에서 '차' 가
      '기차놀이' 를 식품으로 판정하게 만든 것과 같은 뿌리다.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name)
    s = _SPEC.sub(" ", s)
    kept = [tok for tok in s.split() if tok not in _MODIFIERS]
    return " ".join(kept).strip() or s.strip()


# 표가 '전기' · '전동' 을 붙이는 습관이 있다 - 전기토스터 · 전기프라이팬 ·
# 전기스탠드. 셀러는 그냥 토스터 · 프라이팬 · 스탠드라고 쓴다.
#
# 양방향으로 본다: 상품명에 붙여보고, 떼어보고. 이 규칙 하나가 별칭 여러 건을
# 대신한다 - 사전을 작게 유지하는 것이 목표다.
_PREFIXES = ("전기", "전동")


def prefix_variants(name: str) -> list[str]:
    """접두어를 붙이거나 뗀 변형들. 원본이 맨 앞이다."""
    out = [name]
    for p in _PREFIXES:
        if name.startswith(p):
            out.append(name[len(p):].strip())
        else:
            out.append(f"{p}{name}")
            out.append(f"{p} {name}")
    return [v for v in out if v]


def normalize(name: str) -> str:
    """비교용 정규화. 공백·기호를 지우고 대문자로."""
    s = unicodedata.normalize("NFKC", name or "").upper()
    return re.sub(r"[^0-9A-Z가-힣]", "", s)


# 셀러 어휘 -> 법령 어휘.
#
# ⚠ 작게 유지한다. 564건 전부에 별칭을 붙이려 하면 대부분 쓰이지 않는 항목에
#   시간을 쓴다. 골든셋·데모에 나오는 것부터 시작하고 실제 상품을 넣어보며 늘린다.
#
# ⚠ 키는 4글자 이상이거나, 짧더라도 그 도메인에서만 쓰이는 말이어야 한다.
#   'LED' 나 '전등' 같은 짧고 흔한 키를 넣으면 등급이 뒤집힌다.
# 2글자 별칭 키 예외. 짧지만 그 물건에만 쓰이는 말이라 허용한다.
#
# 기준은 "짧다" 가 아니라 "흔하다" 다. 리콜 실데이터 37,313건으로 실측했다:
#
#   랜턴  28건 - 스카이랜턴 · LED랜턴 · 랜턴 스틱. 전부 진짜 랜턴  ✅
#   헬멧 164건 - 자전거 헬멧 · 스케이트 헬멧. 전부 진짜 헬멧      ✅
#   매트 369건 - **매트리스**가 섞인다. 침대와 전기매트는 다른 물건  ❌
#   의자 613건 - 유아용 식탁의자 등. 표에 의자 항목이 5개나 있다     ❌
#   조명 1,412건 - 너무 넓다                                  ❌
_SHORT_KEY_EXCEPTIONS = {"랜턴", "헬멧"}


# 값이 튜플이면 후보를 다 낸다 - 원문이 갈라 두지 않은 말을 우리가
# 한쪽으로 갈라서 단정하지 않기 위한 것이다.
ALIASES: dict[str, str | tuple[str, ...]] = {
    # 조명 - 손에 드는 것과 천장에 다는 것은 등급이 다르다
    "펜라이트": "충전식 휴대전등",
    "손전등": "충전식 휴대전등",
    "플래시라이트": "충전식 휴대전등",
    "후레쉬": "충전식 휴대전등",
    # 음향
    "이어폰": "무선 헤드셋",
    "무선이어폰": "무선 헤드셋",
    "블루투스이어폰": "무선 헤드셋",
    # 전원
    "충전기": "직류전원장치",
    "어댑터": "직류전원장치",
    "전원어댑터": "직류전원장치",
    "adaptor": "직류전원장치",
    "adapter": "직류전원장치",
    # --- 아래는 실상품 표본 30건에서 실제로 못 맞춘 것만 추가했다 --------
    # 561건 중 절반이 B2B 부품이라, 안 쓰일 항목에 별칭을 붙이면 시간만 든다.
    #
    # ⚠ 조명은 원문 정의로 갈랐다. 표의 분류가 셋이다:
    #     LED등기구(안전인증)      천장·벽에 설치하는 조명기구
    #     충전식 휴대전등(안전확인)  손에 드는 것. 펜라이트·랜턴·손전등
    #     체인형 조명기구(안전확인)  줄조명·앵두전구·트리 장식
    #   등급이 안전인증 vs 안전확인으로 갈리므로 뒤집히면 셀러에게 잘못된
    #   의무를 말한다. 처음에 랜턴·줄조명을 LED등기구로 보낸 것이 오답이었다.
    "랜턴": "충전식 휴대전등",
    "줄조명": "체인형 조명기구",
    "앵두전구": "체인형 조명기구",
    "알전구": "체인형 조명기구",
    "트리조명": "체인형 조명기구",
    "텐트장식": "체인형 조명기구",
    "자두전구": "체인형 조명기구",
    "알조명": "체인형 조명기구",
    # ⚠ 센서등·정원등은 **한쪽으로 단정하지 않는다.**
    #
    #   원문(운용요령 별표 1·2)의 갈림 기준은 전원 방식이지 용도가 아니다.
    #     별표 1 11.나 일반조명기구      ④ LED등기구            안전인증
    #     별표 2 11.다 그밖의 조명기구   ② 충전식 휴대전등       안전확인
    #   같은 이름이 양쪽에 있는 항목들이 그 기준을 드러낸다 - 할로겐등기구는
    #   "전자회로가 있는"(별표1) 과 "구동장치가 없는"(별표2) 로만 갈리고,
    #   투광조명기구도 구동장치 유무로 갈린다. 즉 상시전원을 받아 구동장치를
    #   품은 것이 별표 1 이다.
    #
    #   '센서등' 은 원문에 없는 셀러 말이고, 실제 상품은 양쪽에 다 걸린다:
    #     "간편부착 무선 센서라이트 LED센서등 건전지형"   건전지 · 부착
    #     "DGITEM LED무선센서등 충전식 라이트"           충전식 · 휴대
    #     "태양광정원등 태양광조명 센서등 가로등 공장등"   태양광 · 고정
    #   앞의 둘은 상시전원이 아니고, 셋째는 고정이지만 태양광이다. 벽에
    #   붙는다는 이유로 LED등기구(안전인증)로 보내면 안전확인 대상에
    #   안전인증 의무를 말하게 된다 - 등급이 뒤집힌다.
    #
    #   그래서 후보를 둘 다 낸다. 등급이 갈리므로 grades_agree 가 None 을
    #   돌리고, 셀러는 "전원 방식을 확인하라" 는 답을 받는다 (CLAUDE.md R3).
    "센서등": ("LED등기구", "충전식 휴대전등"),
    "센서라이트": ("LED등기구", "충전식 휴대전등"),
    "정원등": ("LED등기구", "충전식 휴대전등"),
    # 현관등은 상시전원 고정 조명이라 갈리지 않는다.
    "현관등": "LED등기구",
    # ⚠ '무드등' 은 별칭에 넣지 않는다. 체인형·충전식·LED등기구 어느 것이든
    #   될 수 있고, 도매 상품명이 연관 검색어로 붙이는 대표적인 말이다.
    #   실제로 이것 때문에 선풍기·가습기 상품이 LED등기구로 갔다(오답 3건).
    # 난방·온열
    "온풍기": "전기온풍기",
    "손난로": "전기손난로",
    # 주방
    "전기포트": "전기주전자",
    "무선주전자": "전기주전자",
    # 생활
    "물놀이": "공기주입물놀이기구",
    "수영링": "공기주입물놀이기구",
    "헬멧": "자전거용 안전모",
    "미끄럼방지매트": "미끄럼 방지 타일",
    "자동우산": "우산",
    "접이식우산": "우산",
    "양우산": "우산",
    "스탠드조명": "전기스탠드",
    "책상조명": "전기스탠드",
    "LED스탠드": "전기스탠드",
    "유아스탠드": "전기스탠드",
    # --- 도매꾹 실상품 239건에서 못 맞춘 것 (원문 확인 후) -------------
    #
    # ⚠ 전지. 원문이 갈라 준다 - 후보를 둘로 낼 필요가 없다.
    #     별표 1 10.나 단전지(안전인증) 비고 1
    #       "스마트폰, 노트북컴퓨터에 적용되는 에너지밀도 700 Wh/L 이상,
    #        최대 충전전압 4.4 V 이상의 단전지(리튬계)에 한정한다"
    #       → 보조배터리가 아니다. 완제품에 들어가는 셀 부품이다.
    #     별표 1·2 비고 2 (같은 문구가 양쪽에 있다)
    #       "일상생활에서 전지를 사용하는 자에게 판매되는 단전지(리튬계)는
    #        전지(리튬계)로 간주하며, 해당 안전기준의 요구사항을 충족하여야
    #        한다"
    #       → 소비자에게 팔리는 리튬 충전지는 셀 하나짜리라도 「전지」다.
    #     별표 2 파. 전지(충전지만 해당한다) ① 전지 → 안전확인
    #   보조배터리는 셀을 묶은 팩이므로 애초에 단전지가 아니고, 소비자
    #   판매용이므로 두 경로가 모두 「전지」로 모인다.
    "보조배터리": "전지",
    "보조베터리": "전지",      # 셀러 오타. 표본에 실제로 있다
    "파워뱅크": "전지",
    # 주방. 표의 액체가열기기가 전부 안전인증이라 후보를 다 내도 갈리지 않는다
    "멀티쿠커": ("전기스팀쿠커", "전기냄비", "전기밥솥"),
    "라이스쿠커": "전기밥솥",
    "무선포트": "전기주전자",
    "커피포트": "전기주전자",
    "토스트기": "전기토스터",
    "토스터기": "전기토스터",
    "와플메이커": "와플기기",     # 표에 '와플기기' 가 따로 있다
    # 믹서·블렌더는 표가 주서믹서기·혼합기 양쪽에 두 등급으로 두었다.
    # 갈리는 대로 내보내 확인을 요청한다.
    "믹서기": ("주서믹서기", "혼합기"),
    "블렌더": ("주서믹서기", "혼합기"),
    "블랜더": ("주서믹서기", "혼합기"),
    # ⚠ 청소기는 '청소기' 를 키로 쓰지 않는다. 수동 밀대청소기·회전청소기가
    #   전기용품이 아닌데 같이 걸린다(표본에 3건). 전기 제품에만 붙는
    #   앞말을 키로 쓴다. 표의 청소기 넷이 모두 안전인증이라 후보를 다 내도
    #   등급은 하나로 모인다.
    "차량용청소기": ("진공청소기", "물흡입청소기", "전기바닥청소기", "스팀청소기"),
    "핸디청소기": ("진공청소기", "물흡입청소기", "전기바닥청소기", "스팀청소기"),
    "욕실청소기": ("진공청소기", "물흡입청소기", "전기바닥청소기", "스팀청소기"),
    "에어청소기": ("진공청소기", "물흡입청소기", "전기바닥청소기", "스팀청소기"),
    # 미용
    "고데기": "전기머리인두",
    # ⚠ '고대기' 오타는 넣지 않는다. 표본에서 이 오타가 나온 유일한 상품이
    #   "고데기 걸이 정리 고대기 고데기 거치대" 즉 거치대였다. 오타 별칭은
    #   부속어 가드를 우회해서 들어온다.
    "제모기": "전기면도기",
    # ⚠ '안마기' 를 키로 쓰지 않는다. 옥혈침기·지압봉 같은 수동 제품이
    #   '가정용안마기' 를 연관 검색어로 달고 있다(표본에 4건). 전기 제품에만
    #   붙는 앞말을 쓴다.
    #
    #   셀러가 전원 방식을 답하면 그때 넓은 키를 쓸 수 있다 -
    #   ALIASES_IF_POWERED 를 볼 것.
    "전동안마기": "전기마사지기",
    "유선안마기": "전기마사지기",
    "전기안마기": "전기마사지기",
    # 생활. 부속서 6 = "가정에서 세탁물을 건조하기 위해 사용하는 건조대"
    #   ⚠ '건조대' 단독은 키로 쓰지 않는다 - 식기건조대는 세탁물이 아니다.
    "빨래건조대": "간이 빨래걸이",
    "실내건조대": "간이 빨래걸이",
    "빨래걸이": "간이 빨래걸이",
}


# 셀러가 "전원을 쓴다" 고 답했을 때만 쓰는 별칭.
#
# '안마기'·'마사지기' 는 그 자체로는 전동인지 수동인지 알 수 없다. 표본에서
# 미매칭 5건 중 4건이 이 갈래였다:
#
#   "지압봉 안마기 어깨마사지기 발지압봉"        손으로 누른다 → 표에 없다
#   "문어발 USB 진동 마사지기"                 전동 → 전기마사지기(안전인증)
#
# 상품명만으로는 못 가른다. '안마기' 를 그냥 키로 쓰면 수동 제품이 안전인증
# 대상으로 붙어 오답이 되고, 안 쓰면 전동 제품을 놓친다. 셀러가 "전원을
# 쓰나요" 에 답하면 그때 붙인다.
#
# ⚠ 전원을 쓴다고 답해도 배터리·태양광은 여기 넣지 않는다. 표의 '전기마사지기'
#   가 어느 전원까지 담는지 원문에서 확인하지 않았다 (R5). mains 만 쓴다.
ALIASES_IF_MAINS: dict[str, str | tuple[str, ...]] = {
    "안마기": "전기마사지기",
    "마사지기": "전기마사지기",
    "맛사지기": "전기마사지기",
    "안마의자": "전기마사지기",
}

# 두 품목이 함께 보일 때 어느 쪽이 본체인가.
#
# "의자방석" 은 방석이지 의자가 아니다. 그런데 '의자' 를 닫아 두면 방석도 의자도
# 답을 못 준다 - 실측에서 의자 계열 8건이 전부 미매칭이었다.
#
# 닫는 대신 **경쟁 관계를 적는다.** 더 구체적인 쪽이 이긴다:
#
#   "메모리폼 의자방석 쿠션방석"     방석이 이긴다 -> 의류 이외의 섬유제품
#   "무중력의자 리클라이너"          경쟁자가 없다 -> 의자
#   "국산 8단 전기방석 전기요"       전기방석이 이긴다 (표에 그 이름이 있다)
#
# 방석은 부속품이 아니라 **별개 품목**이다. 부속서 1 기타 제품류가 "쿠션류,
# 방석류" 를 명시하고, 표에 '의류 이외의 섬유제품'(안전기준준수)이 있다.
# 그래서 is_accessory 질문으로는 못 가른다 - 셀러가 방석을 팔면서 "부속품
# 입니다" 를 누를 이유가 없다. 갈림이 본체 vs 부속품이 아니라 품목 A vs B 다.
#
# ⚠ 경쟁 품목은 **양쪽 다 표에 있을 때만** 적는다. 한쪽이 비대상이면 경쟁이
#   아니라 그냥 오답이고, 그건 부속어·부정어 신호가 처리한다.
_RIVAL_ITEMS: dict[str, tuple[tuple[str, ...], str]] = {
    # 키(닫혀 있던 말): (이 말들이 함께 보이면 양보한다, 양보해서 갈 품목)
    "의자": (("방석", "쿠션"), "의류 이외의 섬유제품"),
}


def rival_wins(normalized_name: str, key: str) -> str | None:
    """이 상품명에서 경쟁 품목이 이기는가. 이기면 그 품목명을 돌려준다."""
    rule = _RIVAL_ITEMS.get(key)
    if rule is None:
        return None
    rivals, target = rule
    if any(normalize(r) in normalized_name for r in rivals):
        return target
    return None


# 역방향 포함 매칭(품목명이 상품명 안에 들어 있는가)에서 키로 쓰지 않는 말.
#
# "신일 BLDC 무선 선풍기 써큘레이터" 처럼 셀러는 브랜드·수식어를 앞뒤에 붙인다.
# 정확 일치만 보면 표에 '선풍기' 가 있어도 못 찾는다. 그래서 품목명이 상품명
# 안에 있는지도 본다 - 다만 아무 말이나 키로 쓰면 등급이 뒤집힌다.
#
# ⚠ 아래 단어들은 여러 품목에 공통으로 들어가 식별력이 없다. 'LED' 를 키로
#   쓰면 펜라이트가 LED등기구(안전인증)에 붙는데 정답은 충전식 휴대전등
#   (안전확인)이다. 리콜 매칭에서 '153' 이 볼펜과 LED 전등을 잇던 것과 같은
#   뿌리다 - 짧고 흔한 토큰은 식별력이 없다.
#
# ⚠ '의자' 는 여기서 뺐다. 닫아 두면 방석도 의자도 답을 못 주는데(실측 8건이
#   전부 미매칭), 방석은 부속품이 아니라 별개 품목이라 부속어 신호로도 못
#   가린다. 대신 _RIVAL_ITEMS 로 "방석·쿠션이 함께 보이면 양보한다" 를 적었다.
_WEAK_CONTAIN_KEYS = {
    "LED", "전지", "코드", "전선", "매트", "조명", "기구", "전기", "히터",
    "램프", "전등", "케이블", "배터리", "충전", "스위치", "기기", "장치", "용품",
    # 어린이제품 표를 합치면서 들어온 3글자 이름. 실측에서 오답 11건을 전부
    # 이 셋이 만들었다 - 도매 상품명에서 부속품이 본체 이름을 그대로 달기
    # 때문이다.
    #
    #     유모차 컵홀더 · 유모차 고리 · 유모차 모기장 · 기저귀 가방(유모차 언급)
    #     목발형 보행기(성인 보행보조기) · 보행기튜브(물놀이 튜브) 3건
    #     학용품보관 필통
    #
    # 이건 새 규칙이 아니라 이미 있던 원칙이다 - "짧고 흔한 토큰은 식별력이
    # 없다". 정확 일치와 별칭으로는 여전히 걸린다.
    "유모차", "보행기", "학용품",
}

# 포함 매칭 키의 최소 길이. 2글자는 우연 충돌이 심하다.
_MIN_CONTAIN_LEN = 3


# 별칭 바로 뒤에 오면 그 출현을 본체로 세지 않는 말.
#
# 도매에서 부속품은 본체 품목명을 그대로 달고 팔린다 - "고데기 거치대",
# "토스터기 선반", "면도기 걸이". 거치대는 고데기가 아니다. 실측에서 오답
# 5건이 전부 이 모양이었다.
#
# ⚠ **출현 단위로만 뺀다.** 상품명에 부속어가 있다고 별칭을 통째로 막으면
#   "무선 고속충전기 거치대" 처럼 본체가 충전기인 상품을 놓친다. 표에도
#   '휴대전화 전지 충전기(충전 거치대를 포함한다)' 가 있다 - 거치대를
#   포함한 본체는 본체다.
_ACCESSORY_SUFFIXES = (
    "거치대", "홀더", "걸이", "행거", "보관함", "정리함", "선반", "받침대",
    "커버", "케이스", "카바", "덮개", "필터", "리필", "부속", "전용필터",
    # 안전모 부속품. 실측에서 "안전모 햇빛가리개"·"안전모 속모자" 처럼 본체
    # 품목명을 그대로 달고 팔리는 것이 8건 중 6건이었다. 안전모 매칭이 되면
    # 곧 오답이 되므로 미리 막는다.
    "햇빛가리개", "그늘막", "차양막", "목가리개", "선캡", "속모자", "두건",
    "내피", "차단막", "가리개", "차광막", "그늘이",
    # 그 밖에 실측에서 본 부속·소모품
    "스트랩", "브라켓", "정리대",
    # ⚠ 여기에 넣지 않은 말들 - 부속품처럼 보이지만 본체 품목명이기도 하다.
    #   파우치  "우산 … 파우치" 에서 우산 본체를 부속품으로 오판했다(실측 1건)
    #   매트    전기매트·전기온수매트가 표에 있는 품목이다
    #   망      방충망이 품목이다
    #   패드·밴드·주머니·수납·다이  단독 품목이거나 흔해서 오탐이 크다
    #
    #   부속어는 "본체가 아님" 을 뜻해야 한다. 본체일 수 있는 말을 넣으면
    #   정답이 죽는다 - 늘리는 방향이 항상 이득은 아니다.
)

# 별칭 바로 뒤에 오면 그 물건이 아니라는 뜻인 말. "고데기없이 웨이브".
_NEGATION_SUFFIXES = ("없이", "없는", "없이도", "미포함", "제외")


def names_the_subject(normalized_name: str, normalized_key: str) -> bool:
    """이 말이 상품의 본체를 가리키는가.

    키가 나오는 자리마다 바로 뒤를 본다. 모든 자리가 부속어나 부정어로
    이어지면 본체가 아니다. 한 자리라도 그냥 나오면 본체로 본다.
    """
    tails = _ACCESSORY_SUFFIXES + _NEGATION_SUFFIXES
    at = normalized_name.find(normalized_key)
    if at < 0:
        return False
    while at >= 0:
        rest = normalized_name[at + len(normalized_key):]
        if not any(rest.startswith(t) for t in map(normalize, tails)):
            return True
        at = normalized_name.find(normalized_key, at + 1)
    return False


# 접미 한 글자가 화학제와 기기를 가른다 - '제습제' 는 '제습기' 가 아니다.
#
# 실측(실상품 30건 + 도매꾹 239건 + 리콜 제품명 41,800건)에서 어간+'제' 가
# 실제로 나타난 짝은 셋뿐이다:
#
#   제습기 vs 제습제        3건 - 전부 염화칼슘 제습제였다 (오답이었다)
#   가습기 vs 가습제       14건 - 전부 "공기청정기(가습, 제습기능 있음)" 다.
#                                쉼표가 지워져 '가습'+'제습기능' 이 들러붙어
#                                생긴 것이고, 가습기 자체는 안 나온다
#   페인트제거기 vs 페인트제거제  2건 - 전부 "페인트 제거제" 였다 (막는 게 맞다)
#
# **존재 검사가 아니라 개수 비교를 쓴다.** 존재만 보면 위 두 번째 짝처럼
# 낱말 경계가 지워져 생긴 '제' 형태가 정상 기기를 막는다 - "가습기 (가습,
# 제습 기능)" 같은 상품명이 그렇게 죽는다. 도매 상품명은 본 품목을 여러 번
# 반복하므로, 어느 쪽이 더 많이 나오는지가 무엇을 파는지에 가깝다.
def chemical_variant_dominates(normalized_name: str, normalized_key: str) -> bool:
    """상품명에서 어간+'제'(화학제)가 어간+'기'(기기)보다 더 많이 나오는가."""
    if not normalized_key.endswith("기") or len(normalized_key) < 3:
        return False
    chem = normalized_key[:-1] + "제"
    if chem not in normalized_name:
        return False
    return normalized_name.count(chem) > normalized_name.count(normalized_key)

def split_aliases(item: str) -> list[str]:
    """품목명 하나가 실은 여러 이름인 경우를 쪼갠다.

    표에 '백열등기구·전기스탠드' 처럼 가운뎃점으로 두 이름을 묶어 둔 항목이
    있다. 통째로만 키로 쓰면 셀러가 '고정형 백열등기구' 라고 쓸 때 못 찾는다.
    쪼개서 각각 키로 쓰면 느슨한 일치 없이 잡힌다 - 위험이 없다.

    괄호 안의 범위 한정은 이름이 아니므로 떼고 본다.
    """
    base = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", item)
    parts = [base] + re.split(r"[·ㆍ‧]", base)
    out: list[str] = []
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip(" ,")
        if name and name not in out:
            out.append(name)
    return out


# 길이 규칙의 예외. 짧지만 경쟁 규칙이 지켜 주는 키다.
#
# '의자' 는 2글자라 _MIN_CONTAIN_LEN 에 걸린다. 그런데 길이 규칙의 목적은
# 우연 충돌을 막는 것이고, _RIVAL_ITEMS 가 이미 그 자리를 지키고 있다 -
# 방석·쿠션이 함께 보이면 양보한다. 규칙이 있는 키만 예외로 둔다.
_SHORT_KEYS_WITH_RIVALS = frozenset(_RIVAL_ITEMS)


def is_usable_contain_key(normalized: str) -> bool:
    """이 품목명을 '상품명 안에 있는가' 검사의 키로 쓸 수 있는가."""
    if normalized in {normalize(k) for k in _SHORT_KEYS_WITH_RIVALS}:
        return True
    if len(normalized) < _MIN_CONTAIN_LEN:
        return False
    return normalized not in {normalize(w) for w in _WEAK_CONTAIN_KEYS}


def _is_subsequence(short: str, long: str) -> bool:
    """short 의 모든 글자가 long 에 순서대로 나타나는가."""
    it = iter(long)
    return all(ch in it for ch in short)


# 접두 확장에서 상품명 쪽이 가져야 하는 최소 길이. 짧으면 아무 데나 걸린다.
_MIN_EXPAND_LEN = 3

# 접두 확장에서 허용하는 최대 삽입 글자 수. 품목명이 상품명보다 이만큼까지만
# 길 수 있다. 너무 크게 두면 '보행차' 가 '보행자 안전 보조 손잡이차' 에 붙는다.
_MAX_EXPAND_GAP = 3


def is_prefix_expansion(query: str, item: str) -> bool:
    """상품명이 품목명의 '수식어 빠진 형태' 인가.

    표는 정식 명칭을 쓰고 셀러는 줄여 쓴다 - '고령자용 보행차' 와
    '고령자용 보행보조차' 는 같은 물건이다. 이 관계만 허용한다.

        허용   보행차   ⊂ 보행보조차     (글자가 순서대로 다 들어 있다)
               정수기   ⊂ 전기정수기
        금지   배터리팩   vs 노트북 컴퓨터  (관계 없음)
               스마트워치 vs 스마트폰      ('스마트' 만 겹치고 끝이 다르다)

    ⚠ 부분열(subsequence) 관계로 판단한다. 지시된 사례 7개로 검증했다 -
      '스마트워치' 는 '워치' 가 '스마트폰' 에 없어 걸리지 않고, '보행차' 는
      보/행/차가 '보행보조차' 에 순서대로 있어 걸린다.

    ⚠ 삽입 글자 수를 제한한다. 제한이 없으면 짧은 질의가 긴 품목명에 무조건
      부분열로 걸린다 - 리콜에서 '153' 이 아무 데나 걸리던 것과 같은 모양이다.
    """
    if len(query) < _MIN_EXPAND_LEN:
        return False
    if not (0 < len(item) - len(query) <= _MAX_EXPAND_GAP):
        return False
    return _is_subsequence(query, item)


@dataclass(frozen=True)
class ItemGrade:
    item: str
    grade: str
    category: str
    division: str
    scope_note: str
    source: str
    matched_by: str          # exact | alias | expand | contains
                             # legal_name | legal_name_contains
    # 매처가 이 후보를 얼마나 믿는지, 그리고 왜 그렇게 판정했는지.
    # 매칭/미매칭 이분법으로는 "안전모인 건 알지만 어느 안전모인지 모른다" 를
    # 표현할 수 없어 아는 것까지 버리게 된다.
    confidence: str = "likely"
    match_reason: str = ""


class ItemGradeBook:
    """세부품목 등급표."""

    def __init__(self, path: Path | None = None,
                 child_path: Path | None = None) -> None:
        raw = yaml.safe_load((path or _PATH).read_text(encoding="utf-8"))
        self._rows = list(raw["items"])

        # 어린이제품 표를 **같은 색인에** 넣는다.
        #
        # 두 표를 나눠 두 번 조회하는 방법도 있지만, 합칠 때의 충돌을 먼저
        # 쟀더니 나눌 이유가 없었다:
        #     이름이 정확히 같은데 등급이 다름   0건
        #     어린이 쪽이 구체형인 관계        16건  (유아용 의자 ⊃ 의자)
        #     겹치지 않음                     19건
        #
        # 16건 전부 어린이 쪽 이름이 더 길다. _contain_keys 가 이미 길이순
        # 정렬이라 '유아용 의자' 가 '의자' 보다 먼저 걸린다 - 새 개념이
        # 필요 없다. 나누면 오히려 "어느 표를 볼지" 를 먼저 판정해야 하고,
        # 그건 상품이 어린이제품인지 우리가 단정하는 일이 된다.
        child_raw = yaml.safe_load(
            (child_path or _CHILD_PATH).read_text(encoding="utf-8")
        )
        self._rows += list(child_raw["items"])

        # 목록에 없는 어린이제품이 어디로 가는지. 「어린이제품 안전 특별법
        # 시행규칙」 별표 3 제2호가 문장으로 적고 있어, 우리가 추론하지 않고
        # 그대로 옮긴 것이다.
        #
        # ⚠ 아무 때나 꺼내면 안 된다. 상품이 어린이제품이라는 것이 확인된
        #   뒤에만이다. 어린이제품인지 모르는 상태에서 "어린이제품이면
        #   공통안전기준이 적용됩니다" 를 붙이면 모든 상품에 붙는 소음이 된다.
        self.child_catch_all: dict = child_raw["catch_all"]
        # ⚠ 한 이름이 여러 등급에 걸린다. 표에 '공기청정기' 가 안전확인과
        #   공급자적합성확인 양쪽에 있고, '전기스탠드' 는 전자회로 유무로
        #   안전인증·안전확인이 갈린다 - 이런 이름이 24건이다.
        #
        #   먼저 만난 하나만 담으면 나머지를 조용히 버리게 된다. 등급이
        #   갈리는 것을 모른 채 한쪽을 단정하면, 공급자적합성확인 대상에
        #   "번호가 있어야 한다" 고 말하게 된다 (CLAUDE.md R3-b). 전부 담고
        #   갈리면 grades_agree 가 None 을 돌려 확인을 요청하게 한다.
        self._by_name: dict[str, list[dict]] = {}
        for row in self._rows:
            for name in split_aliases(row["item"]):
                self._by_name.setdefault(normalize(name), []).append(row)

        # 역방향 포함 매칭용. **긴 품목명이 먼저** 와야 한다 -
        # '자전거용 안전모' 가 '안전모' 보다 먼저 걸려야 등급이 정확해진다.
        keys: dict[str, list[dict]] = {}
        for row in self._rows:
            for name in split_aliases(row["item"]):
                key = normalize(name)
                if is_usable_contain_key(key):
                    keys.setdefault(key, []).append(row)
        self._contain_keys: list[tuple[str, list[dict]]] = sorted(
            keys.items(), key=lambda pair: -len(pair[0])
        )

    def __len__(self) -> int:
        return len(self._rows)

    def lookup_all(
        self, product_name: str | None, *, extra_aliases: dict | None = None
    ) -> list[ItemGrade]:
        """상품명에서 보이는 품목 후보를 **전부** 돌려준다. 강한 순.

        도매 상품명은 연관 검색어를 다 붙이는 것이 전형이다 - "미니 무선 탁상용
        무드등 선풍기 가습기" 하나에 세 품목이 들어 있다. 하나를 고르면 어느
        것이든 틀릴 수 있으므로 모르면 단정하지 않는다 (CLAUDE.md R3).

        단계 순서:
          (1) 정확 일치 - 표의 이름과 그대로 같다
          (2) 역방향 포함 - 표의 이름이 상품명 안에 있다
          (3) 접두 확장 - 상품명이 표 이름의 수식어 빠진 형태다
          (4) 별칭 - 우리가 만든 대응표

        ⚠ 별칭이 마지막이다. 표는 법령 원문이고 별칭은 우리 추정이다.
          추정이 원문을 이기면 안 된다 - 처음에 별칭을 먼저 봤더니 '무드등'
          별칭이 표에 그대로 있는 '선풍기'·'가습기' 를 이겨 오답이 났다.
        """
        if not product_name:
            return []

        stripped = strip_modifiers(product_name)
        intact = normalize(product_name)
        forms = [intact]
        if normalize(stripped) != intact:
            forms.append(normalize(stripped))

        found: list[ItemGrade] = []
        seen: set[tuple[str, str]] = set()

        consumable = has_consumable_hint(product_name)

        def offer(rows: list[dict] | None, how: str, key: str = "") -> None:
            """후보를 매처에 거쳐 담는다.

            1단계(검색)가 찾아온 것을 2단계(매처)가 가린다. 매처는 거부하는
            쪽으로만 강하다 - 참을 만들어내지 않는다.
            """
            # dedupe 를 이름만으로 하면 안 된다 - 표에 '주서' 가 안전인증과
            # 안전확인 양쪽에 같은 이름으로 있어서 한쪽이 사라진다.
            for row in rows or ():
                mark = (row["item"], row["grade"])
                if mark in seen:
                    continue
                probe = key or normalize(row["item"])
                verdict = judge(
                    normalized_name=intact,
                    normalized_key=probe,
                    matched_by=how,
                    # 정확 일치는 상품명 전체가 품목명이라 부속어 검사가 무의미하다.
                    names_subject=True if how == "exact" else names_the_subject(intact, probe),
                    chemical_dominates=(
                        False if how == "exact"
                        else chemical_variant_dominates(intact, probe)
                    ),
                    consumable_hint=consumable,
                    # 화학제 검사는 **목적지 품목명**으로 한다. 별칭 키
                    # ('손난로')가 아니라 그 별칭이 가리키는 품목
                    # ('전기손난로')이 화학제와 자리를 다투기 때문이다.
                    chemical_rival=chemical_rival_wins(product_name, row["item"]),
                )
                if not verdict.accepted:
                    continue
                seen.add(mark)
                grade = self._to_grade(row, how)
                found.append(
                    replace(
                        grade,
                        confidence=verdict.confidence.value,
                        match_reason=verdict.reason,
                    )
                )

        # (1) 정확 일치
        for base in (product_name, stripped):
            for candidate in prefix_variants(base):
                offer(self._by_name.get(normalize(candidate)), "exact")

        # (2) 역방향 포함. 긴 품목명이 먼저 - '자전거용 안전모' 가 '안전모'
        #     보다 앞서야 등급이 정확해진다.
        #
        # ⚠ **수식어를 뗀 형태로는 포함 검사를 하지 않는다.** normalize 가
        #   띄어쓰기를 지우므로, 가운데 토큰을 빼면 양옆이 들러붙어 원문에
        #   없던 낱말이 생긴다. 실제로 "2.1A충전기 가정용 충전기" 에서
        #   '가정용' 을 떼자 "…충전기충전기…" 가 되어 표의 '전기충전기'
        #   (교류 30V 초과 250V 이하 - 벽 콘센트에 꽂는 것)에 붙었다.
        #   휴대폰 충전기가 그 품목일 리 없다.
        #
        #   뗀 형태가 필요하지도 않다. 띄어쓰기가 이미 지워졌으므로 진짜
        #   포함 관계는 원본 형태에서 그대로 보인다 - '무선 전기 주전자' 는
        #   원본만으로도 '전기주전자' 를 담고 있다.
        for key, rows in self._contain_keys:
            # 부속어 가드는 포함 매칭에도 적용한다 - "전동 칫솔거치대" 는
            # 표의 '전동칫솔' 을 그대로 담고 있지만 칫솔이 아니다.
            #
            # 경쟁 품목이 이기면 이 후보를 양보하고 그쪽을 담는다.
            # "의자방석" 은 방석이지 의자가 아니다 - 둘 다 표에 있는 품목이라
            # 부속어 신호로는 못 가른다.
            winner = rival_wins(intact, key)
            if winner is not None:
                # ⚠ 본체 검사는 **경쟁 키**('의자')로 한다. 목적지 품목명
                #   ('의류 이외의 섬유제품')은 상품명에 없는 것이 정상이라,
                #   그 이름으로 검사하면 항상 거부되고 양보가 착지하지 않는다.
                #
                #   별칭 단계가 같은 함정을 이미 알고 있다 - 거기 주석이
                #   "본체 검사는 별칭 키로 한다" 라고 적고 있다. 경쟁 단계만
                #   그 처리가 빠져 있었고, 실측에서 방석 3건이 양보 대상에
                #   붙지 못한 채 미매칭으로 남았다.
                offer(self._by_name.get(normalize(winner)), "contains", key)
                continue
            offer(rows, "contains", key)

        # (3) 접두 확장
        for nb in forms:
            if not is_usable_contain_key(nb):
                continue
            for key, rows in self._contain_keys:
                if is_prefix_expansion(nb, key):
                    offer(rows, "expand")

        # (4) 별칭 - 우리 추정이므로 마지막이다
        alias_table = dict(ALIASES)
        if extra_aliases:
            # 셀러가 답해 준 사실이 있을 때만 열리는 별칭. 기본 사전을
            # 덮어쓰지 않고 더한다.
            alias_table.update(extra_aliases)
        for target in forms:
            for key, legal in alias_table.items():
                if not names_the_subject(target, normalize(key)):
                    continue
                for name in (legal,) if isinstance(legal, str) else legal:
                    # ⚠ 본체 검사는 **별칭 키**로 한다. 목적지 품목명은 상품명에
                    #   없는 것이 정상이다 - '랜턴' 을 '충전식 휴대전등' 으로
                    #   보내는데, 그 이름으로 본체 검사를 하면 항상 거부된다.
                    #
                    #   화학제 검사만 목적지로 한다 - '제습기' 로 보내는 별칭이
                    #   생기면 화학제 상품에 붙기 때문이다.
                    if chemical_variant_dominates(target, normalize(name)):
                        continue
                    offer(self._by_name.get(normalize(name)), "alias", normalize(key))

        return found

    def lookup(self, product_name: str | None) -> ItemGrade | None:
        """가장 강한 후보 하나. 후보가 여럿이면 lookup_all 을 쓸 것."""
        found = self.lookup_all(product_name)
        return found[0] if found else None

    @staticmethod
    def grades_agree(candidates: list[ItemGrade]) -> str | None:
        """후보들의 등급이 하나로 모이면 그 등급, 갈리면 None.

        셋 다 같은 등급이면 오히려 확실해진다 - 상품명에 무드등·선풍기·가습기가
        다 들어 있어도 전부 안전인증이면 "무엇이든 안전인증 대상" 이라고 말할
        수 있다. 등급이 갈릴 때만 확인을 요청한다.
        """
        grades = {c.grade for c in candidates}
        return grades.pop() if len(grades) == 1 else None

    def lookup_legal_name(self, legal_name: str | None) -> list[ItemGrade]:
        """LLM 이 옮긴 법령 품목명을 표에서 조회한다.

        **표가 검증자다.** LLM 은 이름만 내놓고 등급은 표에서 결정론적으로
        읽으므로, LLM 이 등급을 지어낼 수 없다 (CLAUDE.md R1).

        정확 일치를 먼저 보고, 없으면 **표의 품목명이 LLM 답을 포함하는지**
        본다. 방향이 이것뿐인 이유:

          표 561건 중 75건(13%)에 법령 수식이 붙어 있다 - '무선스피커 시스템'·
          '전기오븐기기'·'형광등기구'·'할로겐등기구'. LLM 이 자연스럽게 답하면
          이 75건은 영원히 안 맞는다. 검증자가 자기 표기법을 강요하는 것이지
          LLM 이 틀린 게 아니다.

        ⚠ 이 완화는 **LLM 답에만** 허용한다. 셀러 상품명에는 절대 쓰지 않는다.
          위험도가 다르다:

            셀러 상품명  '신일 BLDC 무선 선풍기 써큘레이터 캠핑용 탁상 휴대용'
                         브랜드·수식어·연관검색어·부속품이 섞여 있어 포함이
                         물면 엉뚱한 품목이 걸린다
            LLM 답       '무선스피커'
                         이미 정리된 품목명 하나라 포함이 물 것은 표의 수식뿐

          LLM 이 추출을 이미 끝냈다. 남은 것은 어휘 정렬이지 추출이 아니다.

        ⚠ 포함으로 걸린 것은 **possible** 이다. 표기가 정확히 같지 않았으니
          likely 로 올리지 않는다. 후보가 여럿이면 부르는 쪽의 합의·갈림
          로직이 그대로 받는다 - 여기서 하나를 골라 단정하지 않는다 (R3).
        """
        key = normalize(legal_name or "")
        if not key:
            return []

        exact = self._by_name.get(key)
        if exact:
            return [self._to_grade(row, "legal_name") for row in exact]

        # 표가 수식을 붙인 형태를 찾는다. 두 모양이 있고 둘 다 필요하다:
        #
        #   뒤·앞에 붙는다   무선스피커 ⊂ 무선스피커**시스템**
        #                    안전모     ⊂ **자전거용**안전모
        #   가운데 끼어든다   전기그릴   ⊂ 전기**거치식**그릴
        #
        # 앞의 것은 부분 문자열, 뒤의 것은 부분열이다. **새 관계를 만들지
        # 않고** 셀러 상품명 경로에서 이미 검증된 is_prefix_expansion 을
        # 그대로 쓴다 - 삽입 글자 수 제한이 이미 들어 있어 짧은 답이 긴
        # 품목명에 무조건 걸리는 것을 막는다.
        #
        # 짧은 답이 여럿을 물 수 있고, 그때는 갈림으로 확인을 요청하는 것이
        # 정확한 동작이다 - 하나를 골라 단정하지 않는다 (R3).
        seen: set[tuple[str, str]] = set()
        out: list[ItemGrade] = []
        for name, rows in self._by_name.items():
            if key not in name and not is_prefix_expansion(key, name):
                continue
            for row in rows:
                mark = (row["item"], row["grade"])
                if mark in seen:
                    continue
                seen.add(mark)
                out.append(self._to_grade(row, "legal_name_contains"))
        return out

    @staticmethod
    def _to_grade(row: dict, how: str) -> ItemGrade:
        return ItemGrade(
            item=row["item"],
            grade=row["grade"],
            category=row["category"],
            division=row.get("division", ""),
            scope_note=row.get("scope_note", ""),
            source=row["source"],
            matched_by=how,
        )
