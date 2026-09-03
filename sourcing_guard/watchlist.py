"""Watchlist sweep — deterministic recall matching (기획서 §3-4단계).

No LLM here (CLAUDE.md R1). Matching is string normalisation plus explicit
tiers, so an alert can always be explained to a seller in one sentence.

Storage is abstracted behind WatchRepository so v1 can ship on SQLite and
move later without touching the matching rules.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Protocol

from .kats_client import RecallRecord, is_cert_number, normalize_kc, recall_evidence
from .models import MatchStrength, RecallAlert, WatchItem, WatchStatus, matched_on_label

# Model names shorter than this produce too many coincidental hits
# ("A1", "100") to be worth alerting on.
_MIN_EXACT_LEN = 3

# 포함 매칭에서 "짧은 쪽"이 가져야 하는 최소 길이.
#
# ⚠ 두 문자열 중 긴 쪽이 아니라 짧은 쪽을 재야 한다. 포함 관계의 식별력은
#   짧은 쪽에서 나온다 - 'S' 가 'MB120S' 안에 있다는 사실은 아무것도 말해주지
#   않는다. 이전 구현은 `len(wm) >= 5 or len(rm) >= 5` 였고, 우리 쪽이 길면
#   리콜 쪽이 1자여도 통과했다. 실측(로컬 사본 37,313건):
#
#     'MB-120S' 를 감시   →  일치 137건. 걸린 리콜 모델명은
#                            'S'(33) '1'(20) '2'(25) '12'(35) '120'(30) 등 13종
#
#   저 조각들은 모델명이 아니라 정부 데이터를 쪼갠 부스러기다 - 괄호 주석
#   ('뱀','렌치'), 콤마 목록('FR','FS'), 슬래시 조각('62/6150' → '62').
#
#   임계값별 실측 (현실 입력 기준 역검증 3,000건 / 무관 상품 3종 오탐):
#     OR  >= 5   재현율 95.1%   오탐 105.3건   ← 이전
#     min >= 4   재현율 94.6%   오탐   3.3건
#     min >= 5   재현율 94.0%   오탐   0.0건   ← 채택
#
#   min>=5 가 잃는 1.1pp 를 전수 확인했다. 23건 전부 역검증이 부스러기를 감시
#   모델명으로 뽑은 경우였다 - '품번' '번호' '품명'(필드 라벨), '주황' '크림'
#   '살색'(색상 주석), 'L' '02' '19'. 셀러가 입력할 문자열이 아니다. 즉 실질
#   재현율 손실은 0 이고, 진짜 짧은 모델명('솔로X')은 exact 티어가 잡는다.
_MIN_CONTAIN_LEN = 5
_MIN_TOKEN_OVERLAP = 2

# 매칭 키의 식별력. 여기서 걸리면 강도를 낮춘다 (버리지 않는다).
#
# 프로덕션 실측(2026-09-01)에서 "펜을 검사했는데 블라인드가 뜬다" 계열 오탐이
# 전부 여기서 나왔다. 무관한 상품 6종을 넣어 RED 로 나간 리콜을 셌다:
#
#   '153'   숫자만 3자      정확 일치 1건   2014 국외 'LED 전등'(Greenline)
#   'M1000' 글자 1 + 숫자   포함 일치 6건   로봇 잔디깎이·전기 냄비·유아용
#                                           드레스·체인형 조명기구·휴대용 축전지
#   'GP-500' 'BLK-100' 'A1' '1000'                  0건
#
# 두 오탐은 문자열로는 진짜 일치와 구분되지 않는다. 'M1000' 이 'HRM1000' 안에
# 있는 것과 'BLK100' 이 'BLK100A' 안에 있는 것은 같은 모양이다. 가르는 것은
# 제품 문맥인데 그건 우리가 판정할 것이 아니다 (R1).
#
# 그래서 임계값을 올려 매칭을 없애는 대신 강도를 낮춘다. 약한 일치는 화면에서
# '참고' 구획으로 가고 알림도 계속 나간다 - 놓친 알림이 이 서비스가 하는 유일한
# 약속을 깨뜨린다 (R6). 바뀌는 것은 빨간불을 켜느냐뿐이다.
#
# ── 값을 정한 실측 (로컬 사본 37,313건, 2026-09-01) ─────────────────────
#
# ① 숫자만인 모델명 — 같은 숫자열을 쓰는 서로 다른 리콜이 몇 건인가
#
#     자릿수   모델 수   평균 충돌   2건 이상
#        2        83      6.31       85.5%
#        3       502      2.15       46.8%    ← '153' 이 여기
#        4     1,273      1.30       18.3%    ← 절벽. 여기부터 대체로 유일하다
#        5     1,762      1.19       10.3%
#        6     1,623      1.12       10.2%    이후 평평
#
#   3→4 에서 꺾이므로 4 로 잡는다. 처음에 6 으로 뒀다가 4·5자리(3,035개)를
#   통째로 버리는 것이라 재현율만 7.8pp 깎였다.
#
# ② 포함 매칭 — 짧은 쪽 글자 수
#
#   글자 수 자체는 충돌률을 예측하지 못했다 (길이 5~6, 각 200 표본):
#     글자 0개 32.0% / 1개 17.0% / 2개 17.5% / 3개 이상 23.5%
#   숫자부가 '00' 으로 끝나는지도 갈라봤으나 마찬가지였다 (37.5% vs 25.0%).
#
#   그래도 글자 2개를 요구한다. 근거는 개별 충돌률이 아니라 격자 탐색의
#   끝단 성적이다 — 이 조건 하나가 남은 오탐 6건을 전부 없애면서 재현율은
#   0.43pp 만 쓴다. 겹침 비율(짧은 쪽/긴 쪽) 게이트도 재봤는데 오탐은 더 못
#   줄이면서 재현율을 1pp 더 먹어서 넣지 않았다.
#
# ③ 격자 탐색 (오탐 = 무관 상품 6종이 RED 로 무는 리콜 수,
#                재현율 = 역검증 3,000건이 RED 로 되돌아오는 비율)
#
#     숫자만  글자   오탐   재현율
#      없음    -      7    96.03%   ← 강등 전
#        3     0      7    96.03%
#        4     0      6    94.63%
#        4     2      0    94.20%   ← 채택
#        5     2      0    91.23%
#        6     2      0    88.20%
#
#   오탐 0 을 만드는 가장 싼 점이다. 잃는 1.83pp 는 버려지는 것이 아니라
#   '참고' 로 내려가는 것이라, 알림은 그대로 나가고 화면에도 남는다.
_MIN_DIGITS_ONLY_LEN = 4
_MIN_ALPHA_IN_CONTAIN = 2


def _alpha_count(s: str) -> int:
    return sum(1 for c in s if c.isalpha())


def _exact_is_distinctive(key: str) -> bool:
    """정확 일치를 '확인된 문제' 로 낼 만큼 식별력이 있는가.

    숫자만인 짧은 모델명은 서로 다른 상품이 우연히 공유한다 - 볼펜 '153' 과
    2014년 LED 전등이 그랬다. 글자가 하나라도 있으면 그 자체로 식별력이 붙는다.
    """
    return _alpha_count(key) > 0 or len(key) >= _MIN_DIGITS_ONLY_LEN


def _contain_is_distinctive(shorter: str) -> bool:
    """포함 일치의 식별력은 짧은 쪽이 전부다.

    글자 하나 + 둥근 숫자('M1000')는 다른 모델 코드 안에 우연히 들어간다 -
    'AM1000PTK' 'HRM1000' 'BYC100M1000D' 'JM1000' 이 전부 걸렸다.
    """
    return _alpha_count(shorter) >= _MIN_ALPHA_IN_CONTAIN

# 모델명 칸에 들어오지만 모델명이 아닌 값. 정규화한 형태로 둔다.
#
# "펜을 검사했는데 창문블라인드 리콜이 떴다" 의 원인이다. 인증 표시 문구가
# 양쪽 모델명 칸에 다 들어간다 - 정부 리콜 데이터에도, 셀러 상세페이지에도.
#
# ⚠ _exact_is_distinctive 로는 못 막는다. 그 검사는 "글자가 하나라도 있으면
#   식별력이 있다" 인데, '안전품질표시'·'MODEL'·'BLACK' 은 전부 글자다.
#   식별력 문제가 아니라 애초에 모델명이 아닌 값이라 층을 따로 둔다.
#
# 로컬 사본 37,313건의 모델명 조각을 전수로 세서 뽑았다 (2026-09-01).
# 괄호 안은 사본에 실제로 나온 건수다.
#
#   인증·규제 라벨   공급자적합성(153) 비대상(113) 안전품질표시(61) 안전품질(32)
#   필드 라벨       바코드(139) MODEL(87) 제품명(71) REF(50) ITEMNO(28) SKU(20)
#   색상명          BLACK(50) WHITE(48) BLUE(44) PINK(38) GREEN(32) RED(23)
#   순수 숫자       100 110 120 130 140 150 2020~2022 (각 20~31)
#
# 실측 효과 (2026-09-03, 현재 코드 기준): 셀러 모델명이 이 값들이었을 때
#   '안전품질표시' 61건 · '공급자적합성확인' 154건 · 'MODEL' 276건 · 'BLACK' 183건
# 이 걸렸다. 제외 후 전부 0건.
#
# ⚠ 격하가 아니라 제외인 이유: '비대상' 일치는 정보량이 0 이다. 참고 정보로
#   내려도 수백 건 소음이 그대로 남고, 소음이 된 경고는 꺼진 경고와 같다.
_MODEL_PLACEHOLDERS = {
    # 인증·규제 라벨
    "공급자적합성", "공급자적합성확인", "공급자적합성대상", "비대상", "안전품질표시",
    "안전품질", "안전확인", "안전인증", "자율안전확인", "KC인증", "해당없음", "미상",
    "해당사항없음", "전기용품안전",
    # 필드 라벨 (값이 아니라 필드 이름이 들어온 것)
    "바코드", "BARCODE", "MODEL", "제품명", "상품명", "품명", "품번", "모델명",
    "번호", "LOT번호", "REF", "ITEMNO", "EAN", "EAN코드", "ART", "CODE", "SKU",
    # 색상명 (옵션 표기가 모델명 칸에 들어온 것)
    "BLACK", "WHITE", "BLUE", "PINK", "GREEN", "RED", "ORANGE", "PURPLE",
    "YELLOW", "GREY", "GRAY", "BROWN", "BEIGE", "NAVY", "IVORY",
    # 순수 숫자 (치수·연도)
    "100", "110", "120", "130", "140", "150", "2020", "2021", "2022",
}

# 제조사 칸에 들어오지만 업체명이 아닌 값.
#
# 빈 문자열 가드로 중국어·그리스문자만인 이름과 '-' 는 막았지만, 정규화 후에도
# 남는 자리표시자가 있다. 사본 실측: '미상' 1,417건 · '0' 1,026건.
# 셀러 제조사가 '미상' 이면 오탐 134건이 걸렸다.
_MAKER_PLACEHOLDERS = {
    "미상", "0", "회사정보없음", "정보없음", "해당없음", "해당사항없음", "없음",
    "불명", "NA", "UNKNOWN", "NONE", "NULL", "기타",
}


def is_model_placeholder(normalized: str) -> bool:
    """정규화된 모델명이 '모델명 아님' 인가.

    양쪽에 같은 기준을 적용한다 - 셀러가 적은 값에만 쓰면 정부 데이터의
    자리표시자가 남고, 정부 쪽에만 쓰면 셀러가 적은 자리표시자가 남는다.
    """
    return normalized in _MODEL_PLACEHOLDERS


def is_maker_placeholder(normalized: str) -> bool:
    """정규화된 제조사가 '업체명 아님' 인가."""
    return normalized in _MAKER_PLACEHOLDERS


_STOPWORDS = {
    "세트", "정품", "무료배송", "당일발송", "신상", "특가", "대용량", "고급",
    "SET", "NEW", "HOT", "FREE",
}


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------
def normalize_model(raw: str | None) -> str:
    """Collapse a model string to comparable form.

    Sourcing pages write the same model as 'BLK-100', 'ＢＬＫ 100', 'blk100'.
    """
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw).upper()
    return re.sub(r"[^A-Z0-9가-힣]", "", s)


def tokenize_name(raw: str | None) -> set[str]:
    if not raw:
        return set()
    s = unicodedata.normalize("NFKC", raw).upper()
    tokens = {t for t in re.split(r"[^A-Z0-9가-힣]+", s) if len(t) >= 2}
    return tokens - _STOPWORDS


def recall_fingerprint(r: RecallRecord) -> str:
    """Stable id for a recall notice, so repeat sweeps do not re-alert."""
    parts = "|".join(
        [
            r.scope,
            r.uid or "",          # 서버가 주는 안정적인 id. 있으면 이게 가장 정확하다
            r.model_name or "",
            r.product_name or "",
            r.maker or "",
            r.announced_on or "",
        ]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Match:
    strength: MatchStrength
    matched_on: str


def _recall_models(r: RecallRecord) -> list[str]:
    """리콜 레코드가 담고 있는 모델명들을 정규화해서 돌려준다.

    recallModelName 은 콤마로 묶인 목록이다 (설계서 p.11). 통짜 문자열로 비교하면
    'A,B,C' 리콜에서 B 를 감시 중인 셀러가 알림을 받지 못한다. 놓친 알림은 이
    서비스가 하는 유일한 약속을 깨뜨린다 (CLAUDE.md R6).
    """
    raw = r.models or ([r.model_name] if r.model_name else [])
    return [
        m
        for m in (normalize_model(x) for x in raw)
        if m and not is_model_placeholder(m)
    ]


_TIER_ORDER = {MatchStrength.WEAK: 0, MatchStrength.STRONG: 1, MatchStrength.EXACT: 2}


def match(item: WatchItem, r: RecallRecord) -> Match | None:
    """Return the strongest match tier, or None.

    축을 전부 재고 가장 강한 것을 돌려준다. 이전에는 첫 히트에서 바로 반환했는데,
    식별력 강등이 생기면서 그러면 안 되게 됐다 - 모델명이 약하게 맞았다고 해서
    인증번호 정확 일치를 못 보고 지나치면 진짜 일치를 놓친다 (R6).
    """
    best: Match | None = None

    def offer(strength: MatchStrength, axis: str) -> None:
        nonlocal best
        if best is None or _TIER_ORDER[strength] > _TIER_ORDER[best.strength]:
            best = Match(strength, axis)

    wm = normalize_model(item.model_name)
    if is_model_placeholder(wm):
        # 셀러 페이지의 '안전품질표시' 같은 문구를 모델명으로 읽은 경우.
        # 이걸로 매칭하면 무관한 품목의 리콜이 붙는다.
        wm = ""
    recall_models = _recall_models(r)

    if wm and len(wm) >= _MIN_EXACT_LEN and wm in recall_models:
        offer(
            MatchStrength.EXACT if _exact_is_distinctive(wm) else MatchStrength.WEAK,
            "model_name",
        )

    # 리콜 레코드에 인증번호가 따로 실려 온다 (certNum, 콤마 목록). 모델명 표기가
    # 흔들려도 인증번호가 같으면 확실하다.
    #
    # 인증번호에는 식별력 검사를 걸지 않는다. 형태가 정해진 하드 데이터라
    # (CERT_NUMBER_RE, 리콜 실데이터 1,631건으로 검증) 우연 충돌이 다르다.
    watched_kc = {n for n in (normalize_kc(k) for k in item.kc_numbers) if n}
    if watched_kc:
        # "공급자적합성" 같은 자리표시자는 인증번호가 아니다. 걸러내지 않으면
        # 같은 자리표시자를 가진 서로 다른 상품이 전부 일치로 잡힌다.
        recall_kc = {
            n
            for n in (normalize_kc(c) for c in r.cert_numbers if is_cert_number(c))
            if n
        }
        if watched_kc & recall_kc:
            offer(MatchStrength.EXACT, "kc_number")
        else:
            # 예전 공표는 인증번호를 모델명 칸에 적어 둔 경우가 있다.
            for n in watched_kc:
                if len(n) >= _MIN_EXACT_LEN and any(n in rm for rm in recall_models):
                    offer(MatchStrength.EXACT, "kc_number")
                    break

    if wm:
        for rm in recall_models:
            # 짧은 쪽을 잰다. 긴 쪽으로 재면 1자 부스러기가 전부 통과한다.
            if min(len(wm), len(rm)) >= _MIN_CONTAIN_LEN and (wm in rm or rm in wm):
                shorter = wm if len(wm) <= len(rm) else rm
                offer(
                    MatchStrength.STRONG
                    if _contain_is_distinctive(shorter)
                    else MatchStrength.WEAK,
                    "model_name",
                )

    if best is not None and best.strength is MatchStrength.EXACT:
        return best

    # ⚠ 정규화 결과가 빈 문자열이면 후보에서 뺀다. 모델명 쪽은 `if wm:` 과
    #   _recall_models 의 `if m` 이 이미 걸러내는데, 제조사 쪽에 같은 가드가
    #   없어서 `"" == ""` 로 게이트를 통과했다.
    #
    #   normalize_model 은 [A-Z0-9가-힣] 만 남기므로 중국어·그리스문자만인
    #   업체명과 '-' 가 모두 "" 가 된다. 로컬 사본에서 15,937건(42.7%)이
    #   여기 해당한다. 실측: 제조사 '深圳市特格尔科技有限公司' 로 감시하면
    #   maker='-' 인 리콜과 맞아떨어져 4~15건이 걸렸다.
    #
    #   137건 오탐(ee7011c)과 같은 모양이다 - 비교의 한쪽이 비었는데 통과했다.
    watched_maker = normalize_model(item.maker)
    recall_maker = normalize_model(r.maker)
    if is_maker_placeholder(watched_maker) or is_maker_placeholder(recall_maker):
        # '미상'·'0' 은 업체명이 아니다. 빈 문자열 가드로는 못 막는다 -
        # 정규화 결과가 비어 있지 않기 때문이다. 같은 자리표시자를 가진 서로
        # 다른 업체가 전부 같은 업체로 취급된다 (실측 오탐 134건).
        watched_maker = recall_maker = ""
    if watched_maker and recall_maker and watched_maker == recall_maker:
        overlap = tokenize_name(item.product_name) & tokenize_name(r.product_name)
        if len(overlap) >= _MIN_TOKEN_OVERLAP:
            offer(MatchStrength.WEAK, "maker+product")

    return best


# ---------------------------------------------------------------------------
# sweep
# ---------------------------------------------------------------------------
class WatchRepository(Protocol):
    """저장소 계약. sweep() 자체는 이걸 쓰지 않는다 — 순수 함수로 남기려고
    호출자가 데이터를 넣어주고 결과를 저장한다. 구현은 storage.SqliteWatchStore.
    """

    def add(self, item: WatchItem) -> WatchItem: ...
    def get(self, item_id: str) -> WatchItem | None: ...
    def active_items(self) -> Iterable[WatchItem]: ...
    def for_owner(self, owner_id: str, *, active_only: bool = True) -> list[WatchItem]: ...
    def mark_swept(self, item_id: str, on: date, new_fingerprints: list[str]) -> None: ...


def sweep(
    items: Iterable[WatchItem],
    recalls: Iterable[RecallRecord],
    *,
    today: date,
    min_strength: MatchStrength = MatchStrength.WEAK,
) -> list[RecallAlert]:
    """Compare watched items against a day's recall records.

    Pure function: caller supplies the data and persists the result. Same
    inputs always yield the same alerts, in the same order.
    """
    order = {MatchStrength.WEAK: 0, MatchStrength.STRONG: 1, MatchStrength.EXACT: 2}
    floor = order[min_strength]
    recalls = list(recalls)

    alerts: list[RecallAlert] = []
    for item in items:
        if item.status is not WatchStatus.ACTIVE or not item.is_matchable():
            continue
        seen = set(item.seen_recall_fingerprints)
        for r in recalls:
            fp = recall_fingerprint(r)
            if fp in seen:
                continue
            m = match(item, r)
            if m is None or order[m.strength] < floor:
                continue
            label, url = recall_evidence(r.detail_url)
            alerts.append(
                RecallAlert(
                    watch_item_id=item.id,
                    recall_fingerprint=fp,
                    strength=m.strength,
                    matched_on=m.matched_on,
                    statement_ko=_statement(item, r, m),
                    source_label=label,
                    source_url=url,
                    announced_on=r.announced_on,
                    reason=r.reason,
                    detected_at=today,
                )
            )
            seen.add(fp)
    return alerts


def _fmt_date(yyyymmdd: str | None) -> str | None:
    """YYYYMMDD -> '2026-07-23'. 원본 그대로 화면에 내보내면 읽히지 않는다."""
    if not yyyymmdd or len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return None
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _statement(item: WatchItem, r: RecallRecord, m: Match) -> str:
    """무엇이 어느 강도로 맞았는지를 문구에 담는다.

    "리콜입니다" 가 아니라 "유사 일치하는 항목이 공표되었습니다, 원문 확인
    필요" 로 쓴다 (CLAUDE.md R6). 무엇으로 맞았는지까지 있어야 셀러가 알림을
    열고 1초 만에 자기 상품인지 가릴 수 있다 - 없으면 약한 일치가 반복될 때
    알림 자체를 끄게 되고, 그러면 진짜 리콜도 못 본다.
    """
    where = "국내" if r.scope == "domestic" else "해외"
    when = _fmt_date(r.announced_on) or "공표일 미상"
    subject = item.model_name or item.product_name or "등록하신 상품"
    recalled = (r.product_name or "").strip()
    what = f" ({matched_on_label(m.matched_on)} 기준)"
    tail = f" 리콜된 제품은 '{recalled}' 입니다." if recalled else ""
    return (
        f"'{subject}' 과(와) {m.strength.label_ko}하는 항목이 "
        f"{where} 리콜 공표({when})에 등록되었습니다{what}.{tail} "
        "원문에서 확인해 주세요."
    )
