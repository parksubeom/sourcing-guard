"""Adapter for 국가기술표준원 「제품 안전인증 및 리콜 정보」 (data.go.kr 15116894).

CLAUDE.md R5: field names and endpoint paths are NOT hardcoded from memory.

The dataset is registered as API type "LINK", meaning the operation spec lives
in the provider's own HWP interface document on safetykorea.kr rather than in a
machine-readable schema. Rather than guess, this client reads the endpoint and
field mapping from `data/kats_field_map.yaml`, which is populated by running:

    python scripts/probe_kats_schema.py --base-url ... --op certification

Until that file is filled in, MOCK_MODE serves fixtures so the rest of the
pipeline is developable and testable on day 1.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
import yaml

_MAP_PATH = Path(__file__).parent / "data" / "kats_field_map.yaml"
_CFG: dict[str, Any] = yaml.safe_load(_MAP_PATH.read_text(encoding="utf-8")) or {}
_MOCK_STATES: dict[str, list[str]] = _CFG.get("cert_states", {})
_MOCK_FIELDS: dict[str, str] = (
    _CFG.get("operations", {}).get("certification", {}).get("fields", {})
)

# 설계서 p.18 의 인증번호별 상세 팝업 템플릿. 근거 링크(R2)의 유일한 출처다.
_CERT_DETAIL_TEMPLATE: str = _CFG.get("public_urls", {}).get("cert_detail", "")

# 설계서 v2.0 확인 사항: 인증키는 헤더로 보내며 이름이 대소문자를 구분한다 (p.2).
_AUTH_HEADER = "AuthKey"

# 결과 코드 (설계서 p.19).
_CODE_SUCCESS = "2000"
_CODE_NO_DATA = "2004"

_CODE_HINTS = {
    "4000": "인증키가 유효하지 않습니다. AuthKey 헤더 값과 대소문자를 확인하세요.",
    "4001": "등록되지 않은 IP 입니다. 호출 IP 를 제품안전정보센터에 등록해야 합니다.",
    "4005": "요청 파라미터가 올바르지 않습니다. conditionKey 값을 확인하세요.",
}


class KatsApiError(RuntimeError):
    """API 가 HTTP 200 과 함께 돌려준 실패 코드.

    조용히 빈 목록으로 넘기면 인증/IP 문제가 "조회 결과 없음"으로 둔갑한다.
    """

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        hint = _CODE_HINTS.get(code, "")
        super().__init__(f"SafetyKorea API 오류 {code}: {message} {hint}".strip())


_log = logging.getLogger(__name__)


# 설계 문제(키 무효·IP 미등록)와 일시 장애를 갈라야 한다. 전자에 대고 셀러에게
# "잠시 후 다시 시도하세요" 라고 하면 거짓말이다 — 우리가 고치기 전엔 계속 실패한다.
OPERATOR_FAULT_CODES = frozenset({"4000", "4001", "4005"})


class KatsHealth:
    """정부 API 호출 상태를 프로세스 메모리에 들고 있는다.

    영속 저장을 하지 않는 이유: 헬스체크가 자주 불리므로 매번 볼륨 I/O 를 태울
    이유가 없고, 알고 싶은 것은 "3일 전에 4001 이 났었나" 가 아니라 "지금
    정상인가" 다. 과거 이력이 필요하면 그건 헬스체크가 아니라 로그가 할 일이다.
    재시작으로 초기화되는 것이 오히려 맞다.
    """

    def __init__(self) -> None:
        self.last_error_code: str | None = None
        self.last_error_at: str | None = None
        self.last_error_message: str | None = None
        self.consecutive_failures: int = 0

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self, code: str, message: str = "") -> None:
        from datetime import datetime, timezone

        self.last_error_code = code
        self.last_error_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.last_error_message = message or None
        self.consecutive_failures += 1

    def is_operator_fault(self) -> bool:
        """우리 설정 문제인가. 셀러에게 '다시 시도' 를 권하면 안 되는 경우다."""
        return self.last_error_code in OPERATOR_FAULT_CODES

    def snapshot(self) -> dict:
        return {
            "last_error_code": self.last_error_code,
            "last_error_at": self.last_error_at,
            "consecutive_failures": self.consecutive_failures,
        }


health = KatsHealth()


class CertState(str, Enum):
    """certState 를 신호등 관점으로 분류한 것 (설계서 p.5, p.8)."""

    OK = "ok"                      # 적합
    REVOKED = "revoked"            # 안전인증취소·안전확인신고 효력상실 (처벌)
    # 기간만료·반납은 행정 사유다. 완구 인증의 67% 가 기간만료라 RED 로 두면
    # 정상 상품에 빨간불이 반복된다 (CLAUDE.md R3-b, 2026-09-01 실측).
    EXPIRED = "expired"            # 기간만료·반납
    SUSPENDED = "suspended"        # 표시 사용금지
    UNDER_ACTION = "under_action"  # 개선명령·청문실시
    UNKNOWN = "unknown"            # 매핑에 없는 값


def is_state_not_stated(raw: str | None, states: dict[str, list[str]] | None = None) -> bool:
    """상태가 '없다' 는 뜻인가 (값 미표기) — 해석 실패와 구분한다.

    실데이터에 certState 가 "-" 인 레코드가 있다(완구 43건). 이건 상태가 아니라
    값이 비어 있다는 뜻이다. 판정은 UNKNOWN 으로 같지만 문구는 갈라야 한다.
    "해석하지 못했습니다" 는 우리 잘못처럼 들린다.
    """
    v = (raw or "").strip()
    st = _CFG.get("cert_states", {}) if states is None else states
    return v in set(st.get("cert_state_not_stated", ()))


def classify_cert_state(raw: str | None, states: dict[str, list[str]]) -> CertState:
    """원문 상태 문자열 -> CertState.

    매핑에 없으면 UNKNOWN 이다. 임의로 '적합'으로 추측하지 않는다 (CLAUDE.md R3).

    미분류 값은 로그에 남긴다. 설계서 열거값(10종) 밖의 상태가 실제로 존재하고
    ("취소" 가 그랬다), 새 상태가 조용히 UNKNOWN 으로 떨어지면 진짜 취소된
    인증을 놓치게 된다. 로그가 있어야 나중에 알아챌 수 있다.
    """
    if not raw:
        return CertState.UNKNOWN
    s = raw.strip()
    for bucket in (
        CertState.OK,
        CertState.REVOKED,
        CertState.EXPIRED,
        CertState.SUSPENDED,
        CertState.UNDER_ACTION,
    ):
        if s in states.get(bucket.value, ()):
            return bucket

    if not is_state_not_stated(s, states):
        # 자리표시자는 이미 아는 값이라 로그를 남기지 않는다. 새 상태값만 남긴다.
        _log.warning(
            "미분류 certState: %r — cert_states 매핑에 추가할지 검토 필요 "
            "(CLAUDE.md R3: 임의로 '적합'으로 추측하지 않음)",
            s,
        )
    return CertState.UNKNOWN


# 리콜 레코드의 certNum 에는 인증번호 대신 자리표시자 문자열이 오기도 한다.
# 설계서 p.10 예시의 "공급자적합성" 이 그것이다. 인증번호로 취급해 매칭에 쓰면
# 서로 다른 상품이 같은 자리표시자를 공유해 엉뚱하게 일치한다.
# 명시 목록은 로그 노이즈를 줄이는 용도다. 판별의 원칙은 아래 is_cert_number()
# 에 있다 — 인증번호 패턴을 하나도 못 찾으면 자리표시자로 본다. 그래야
# 미등록 신종("비대상" 54건, "공급자적합성대상" 19건이 그랬다)도 자동으로 걸린다.
CERT_PLACEHOLDERS = frozenset({
    "공급자적합성", "공급자적합성대상", "비대상",
    "해당없음", "해당사항없음", "없음", "N/A", "-",
    "(제품에 표시 없음)", "(인증모델: )",
})


def is_cert_number(value: str) -> bool:
    """실제 인증번호처럼 보이는가. 자리표시자와 구분한다.

    판별 원칙: CERT_NUMBER_RE 가 인증번호를 하나도 못 찾으면 자리표시자다.
    완전 일치 목록만 쓰면 새 자리표시자가 나올 때마다 통과한다 — 실제로
    "비대상"(54건), "공급자적합성대상"(19건)이 목록에 없어 통과하고 있었다.
    전화번호로 보이는 "0505-502-0100" 도 이 원칙으로 자동으로 걸린다.

    자리표시자를 인증번호로 취급하면 같은 값을 가진 서로 다른 상품이 전부
    일치로 잡힌다.
    """
    v = (value or "").strip()
    if not v or v in CERT_PLACEHOLDERS:
        return False
    return bool(CERT_NUMBER_RE.search(_denoise(v)))


# 인증번호 패턴. 리콜 실데이터 약 1,700건(완구·학용품·아동섬유·전기용품,
# 2026-09-01)으로 확정했다. 설계서에는 형태 규정이 없어 실측으로 정했다.
#
#   접두 1~2글자   B363R871-5002   ← B계열이 네 품목군 전부에 있고 학용품은 36%
#   대소문자 무시   cb064a3166-2004chC
#   하이픈 뒤 접미  -5003CH, -2004chC (1글자가 아니다)
#
# 접두 4·6·7글자가 각 1건 있으나(아동섬유) 1,700건 중 3건이라 버린다.
# 놓쳐도 모델명 매칭이 남는다.
CERT_NUMBER_RE = re.compile(r"(?i)\b[A-Z]{1,2}\d{2,}[A-Z]?\d*-\d+[A-Z0-9]{0,4}\b")

# 실데이터에 HTML 조각이 그대로 들어온다(완구 certNum 96건). 구분자로 다루지 않고
# 잡음으로 지운다 — 구분자를 열거해 자르는 방식은 새 구분자가 나오면 깨진다.
_NOISE_RE = re.compile(r"<\s*br\s*/?\s*>?|[\r\n]+", re.I)
# 한 겹 중첩까지 받는다. "(인증모델 : RC미니카(New 배틀미니 레이서))" 같은 값이
# 실데이터에 9건 있고, [^)]* 로는 안쪽 괄호에서 끊겨 이름이 잘린다.
_PAREN_RE = re.compile(r"\((?:([^()]*(?:\([^()]*\)[^()]*)*))\)")

# 판매 채널 표시이지 모델명이 아니다(실데이터 9건). 모델 후보에 넣으면 서로 다른
# 상품이 "온라인" 하나로 엮인다.
_NOT_A_MODEL = {"온라인", "오프라인", "제품", "-", "–", "—"}
# 괄호 안 라벨. "(인증모델 : 대왕버블건)" 에서 값만 남긴다.
_MODEL_LABEL_RE = re.compile(r"^\s*(?:인증)?모델(?:명)?\s*[:：]?\s*", re.I)


def _denoise(raw: Any) -> str:
    return _NOISE_RE.sub(" ", str(raw)) if raw not in (None, "") else ""


def extract_cert_numbers(raw: Any) -> list[str]:
    """문자열에서 인증번호를 전부 찾아낸다 (화이트리스트 추출).

    구분자로 자르지 않는다. 실데이터의 구분자는 콤마만이 아니라 슬래시·괄호·
    <br>·줄바꿈·공백이 뒤섞여 있고, 새 형태가 계속 나온다. "어떻게 자를까"
    대신 "무엇을 찾을까" 로 접근하면 구분자가 늘어도 깨지지 않는다.

        '(배터리) ZU10282-19001, (충전기)SU07706-17003'
            -> ['ZU10282-19001', 'SU07706-17003']

    통짜 문자열로 비교하면 다중 인증번호 리콜을 전부 놓친다. 놓친 알림은 이
    서비스가 하는 유일한 약속을 깨뜨린다 (CLAUDE.md R6).
    """
    seen: list[str] = []
    for m in CERT_NUMBER_RE.findall(_denoise(raw)):
        v = normalize_kc(m)
        if v and v not in seen:
            seen.append(v)
    return seen


def extract_model_hints(raw: Any) -> list[str]:
    """인증번호를 걷어낸 나머지에서 모델명 후보를 꺼낸다.

    certNum 필드에 "(인증모델 : 대왕버블건)" 처럼 모델명이 함께 오는 경우가
    완구만 110건이다. 버리면 매칭 단서를 잃는다 (CLAUDE.md R6 — 알림은 놓치는
    쪽이 훨씬 비싸다).

    모델명과 인증번호를 쌍으로 묶지는 않는다. 각각을 후보 목록에 넣는 것만으로
    매칭은 되고, 쌍 파싱은 정확도 대비 복잡도가 맞지 않는다 (v1 범위).
    """
    text = _denoise(raw)
    hints: list[str] = []

    def _add(v: str) -> None:
        v = _MODEL_LABEL_RE.sub("", v).strip().strip("-–—:：<>").strip()
        if not v or len(v) < 2 or v in _NOT_A_MODEL:
            return
        if CERT_NUMBER_RE.fullmatch(v) or v not in hints:
            if not CERT_NUMBER_RE.fullmatch(v):
                hints.append(v)

    # ① 괄호 안 — "(인증모델 : 대왕버블건)" 형태 (완구만 110건)
    for inner in _PAREN_RE.findall(text):
        _add(inner)

    # ② 괄호 밖 잔여 텍스트 — 인증번호와 괄호를 걷어낸 나머지.
    #    "WF24A95** : HU072172-21013 / WF25B96** : HU072172-22017" 처럼
    #    모델명이 괄호 없이 인증번호와 나란히 오는 형태를 잡는다.
    #    쌍으로 묶지는 않는다 — 각각 후보에 넣는 것만으로 매칭은 되고,
    #    쌍 파싱은 정확도 대비 복잡도가 맞지 않는다 (v1 범위).
    residual = _PAREN_RE.sub(" ", text)
    residual = CERT_NUMBER_RE.sub(" ", residual)
    for token in re.split(r"[,/:：]", residual):
        _add(token)

    return hints


def split_list_field(raw: Any) -> list[str]:
    """모델명 목록 분해. 인증번호와 달리 형태 규칙이 없어 구분자로 자른다.

    recallModelName 은 99.4% 가 인증번호 패턴이 아니라(2026-09-01 실측) 화이트
    리스트 추출을 쓸 수 없다. 콤마·슬래시로 자르고, 괄호 안은 별도 후보로 남긴다.
    """
    if raw in (None, ""):
        return []
    text = _denoise(raw)
    parts = [p.strip() for p in re.split(r"[,/]", text)]
    out = [p for p in parts if p and p not in {"-", "–", "—"}]
    for hint in extract_model_hints(raw):
        if hint not in out:
            out.append(hint)
    return out


@dataclass(frozen=True)
class CertRecord:
    cert_number: str
    product_name: str | None
    model_name: str | None
    maker: str | None
    status: str | None            # certState 원문 값. 화면에 그대로 보여준다
    state: CertState              # 위 값을 분류한 것. 판정은 이쪽을 쓴다
    detail_url: str | None
    brand_name: str | None = None
    category_name: str | None = None
    maker_country: str | None = None
    importer: str | None = None
    import_div: str | None = None
    cert_div: str | None = None
    cert_date: str | None = None


@dataclass(frozen=True)
class RecallRecord:
    product_name: str | None
    model_name: str | None        # 원문 그대로. 콤마 목록일 수 있다
    maker: str | None
    reason: str | None
    announced_on: str | None
    detail_url: str | None
    scope: str  # "domestic" | "overseas"
    models: list[str] = field(default_factory=list)        # model_name 을 분해한 것
    cert_numbers: list[str] = field(default_factory=list)  # certNum 을 분해한 것
    brand_name: str | None = None
    recall_type: str | None = None
    action_guide: str | None = None   # 소비자 행동요령. 국내/국외 필드명이 다르다
    uid: str | None = None


def normalize_kc(raw: str) -> str:
    """Normalise a KC number for comparison.

    Sellers type these in wildly inconsistent forms across KR/CN pages:
    'KC-12345', 'ＫＣ 12345', 'XU-12345-6789', '인증번호:12345'.
    """
    s = unicodedata.normalize("NFKC", raw).upper()
    for token in ("인증번호", "认证号", "KC인증", "KC", ":", "：", " ", "\u200b"):
        s = s.replace(token, "")
    return s.strip("-_/")


class KatsClient:
    def __init__(
        self,
        base_url: str | None,
        service_key: str | None,
        mock: bool = False,
        timeout: float = 8.0,
    ) -> None:
        self._map: dict[str, Any] = (
            yaml.safe_load(_MAP_PATH.read_text(encoding="utf-8")) or {}
        )
        # 호스트는 설계서에 고정된 값이라 매핑에서 온다. .env 의 KATS_BASE_URL 은
        # 시험용 오버라이드일 뿐이다. 정말로 없는 것은 인증키뿐이므로 목 모드
        # 판정도 키 유무로만 한다.
        self._base = (base_url or self._map.get("base_url") or "").rstrip("/")
        self._key = service_key
        self._mock = mock or not (self._base and service_key)
        self._client = httpx.Client(timeout=timeout)

    # -- public ------------------------------------------------------------
    def lookup_certification(self, kc_number: str) -> CertRecord | None:
        key = normalize_kc(kc_number)
        if self._mock:
            return _mock_cert(key)
        rows = self._call("certification", self._query("certification", "cert_number", key))
        if not rows:
            return None
        return self._to_cert(rows[0])

    def search_recalls(
        self,
        *,
        product_name: str | None = None,
        model_name: str | None = None,
        cert_number: str | None = None,
    ) -> list[RecallRecord]:
        term = (model_name or product_name or "").strip()
        if self._mock:
            return _mock_recalls(term or (cert_number or ""))
        if not term and not cert_number:
            return []

        out: list[RecallRecord] = []

        # 인증번호는 국내리콜 조회가 받는 가장 강한 키다 (설계서 p.9). 모델명 표기가
        # 흔들려도 인증번호가 같으면 확실히 잡힌다. 국외리콜에는 certNum 검색이 없다.
        if cert_number:
            rows = self._call(
                "recall_domestic",
                self._query("recall_domestic", "cert_number", normalize_kc(cert_number)),
            )
            out.extend(self._to_recall(r, "domestic") for r in rows)

        if term:
            # 모델명이 있으면 모델명으로, 없으면 제품명으로 찾는다. conditionKey 가
            # 검색 대상 필드를 정하므로 무엇으로 찾는지 명시해야 한다 (p.9, p.15).
            logical = "model_name" if model_name else "product_name"
            for op, scope in (("recall_domestic", "domestic"), ("recall_overseas", "overseas")):
                rows = self._call(op, self._query(op, logical, term))
                out.extend(self._to_recall(r, scope) for r in rows)
        return out

    def recalls_published_on(self, date_prefix: str, *, overseas: bool = False) -> list[RecallRecord]:
        """공표일자로 받는다. 로컬 동기화용.

        conditionValue 는 접두 부분 매칭이 된다 (2026-09-01 실측):
            "20260723"  그 날짜         국내 53건
            "202607"    그 달 전체       국내 55건 79KB / 국외 239건 353KB, 0.2초
            "2026"      그 해 전체       국내 116건 / 국외 2,406건

        범위 문법(~ - ,)은 통하지 않는다.

        ⚠ 접두 매칭은 설계서에 없는 동작이다. 막히면 날짜 하나씩 도는 방식으로
          후퇴해야 한다 (핸드오프 §7). 동기화가 갑자기 0건을 반환하면 이걸 의심할 것.

        설계서 p.2 의 "최대 1,000줄" 은 실측과 다르다. 국외 전량 33,070건이 단일
        응답으로 왔다. 상한 때문에 날짜를 자르는 것이 아니라, 매일 38MB 를 받지
        않기 위해 자른다.
        """
        if self._mock:
            return []
        op = "recall_overseas" if overseas else "recall_domestic"
        rows = self._call(op, self._query(op, "published_on", date_prefix))
        scope = "overseas" if overseas else "domestic"
        return [self._to_recall(r, scope) for r in rows]

    def recalls_all(self, *, overseas: bool = False) -> list[RecallRecord]:
        """전량을 한 번에 받는다. 초기 적재 전용.

        국내 4,243건 5.42MB 2.0초 / 국외 33,070건 32.84MB 5.7초 (2026-09-01 실측).

        ⚠ conditionKey=all & conditionValue=% 는 설계서에 명시된 사용법이 아니다.
          conditionValue 는 검색어 자리인데 와일드카드로 전량을 받는 것이다.
          신청서 안내문에 "개발 명세서 포맷을 어길 시 별도 통보 없이 인증이
          취소될 수 있다" 고 되어 있으므로 **초기 적재 1회에만** 쓴다.
          반복 호출에는 recalls_published_on 의 월 단위 접두 조회를 쓸 것.

        ⚠ conditionValue 를 비우면 전량이 아니라 4005 다. % 를 넣어야 한다.
        """
        if self._mock:
            return []
        op = "recall_overseas" if overseas else "recall_domestic"
        rows = self._call(op, self._query(op, "all", "%"))
        scope = "overseas" if overseas else "domestic"
        return [self._to_recall(r, scope) for r in rows]

    # -- internals ---------------------------------------------------------
    def _op(self, op: str) -> dict[str, Any]:
        cfg = self._map.get("operations", {}).get(op)
        if not cfg:
            raise RuntimeError(
                f"'{op}' 의 엔드포인트 매핑이 없습니다. "
                "scripts/probe_kats_schema.py 를 먼저 실행해 "
                "data/kats_field_map.yaml 을 채우세요. (CLAUDE.md R5)"
            )
        return cfg

    def _param(self, op: str, logical: str) -> str:
        return self._op(op)["params"][logical]

    def _query(self, op: str, search_by: str, value: str) -> dict[str, str]:
        """conditionKey + conditionValue 쌍을 만든다 (설계서 p.3, p.9, p.15).

        검색 대상 필드명이 오퍼레이션마다 다르다 (모델명이 인증에서는 modelName,
        리콜에서는 recallModelName). 논리 이름으로 받아 매핑에서 꺼낸다.
        """
        cfg = self._op(op)
        keys = cfg.get("condition_keys", {})
        if search_by not in keys:
            raise RuntimeError(
                f"'{op}' 에 '{search_by}' 검색 조건이 매핑되어 있지 않습니다. "
                "data/kats_field_map.yaml 의 condition_keys 를 확인하세요."
            )
        return {
            cfg["params"]["condition_key"]: keys[search_by],
            cfg["params"]["query"]: value,
        }

    def _call(self, op: str, params: dict[str, str]) -> list[dict]:
        cfg = self._op(op)
        # 인증은 HTTP 헤더 AuthKey. 쿼리 파라미터가 아니며 대소문자를 구분한다
        # (설계서 v2.0 p.2).
        query = {**cfg.get("defaults", {}), **params}
        resp = self._client.get(
            f"{self._base}/{cfg['path'].lstrip('/')}",
            params=query,
            headers={_AUTH_HEADER: self._key or ""},
        )
        try:
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPStatusError as exc:
            # 인증키가 틀리면 JSON 4000 이 아니라 302 로 온다(실측:
            # error/accessDeniedByKey.json 으로 리다이렉트). 설계서와 다르다.
            code = "4000" if exc.response.status_code in (301, 302, 401, 403) else "http"
            health.record_failure(code, f"HTTP {exc.response.status_code}")
            raise KatsApiError(code, f"HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            health.record_failure("network", type(exc).__name__)
            raise KatsApiError("network", str(exc)) from exc

        # 설계서 p.19: HTTP 200 이어도 resultCode 로 실패를 알린다. 이걸 안 보면
        # 인증 실패(4000)나 IP 미등록(4001)을 "조회 결과 없음"으로 착각하고,
        # 그러면 멀쩡한 인증번호에 RED 를 띄우게 된다.
        code = str(payload.get("resultCode", "")) if isinstance(payload, dict) else ""
        if code == _CODE_NO_DATA:
            health.record_success()
            return []
        if code and code != _CODE_SUCCESS:
            msg = str(payload.get("resultMsg", ""))
            health.record_failure(code, msg)
            if code in OPERATOR_FAULT_CODES:
                # 셀러가 다시 시도해도 우리가 고치기 전엔 계속 실패한다.
                _log.error(
                    "SafetyKorea API 설정 문제 %s: %s — 인증키/IP 등록을 확인하세요 "
                    "(연속 실패 %d회)", code, msg, health.consecutive_failures,
                )
            raise KatsApiError(code, msg)
        health.record_success()

        rows: Any = payload
        for step in cfg["rows_path"]:            # 설계서 기준 ["resultData"]
            rows = rows.get(step) if isinstance(rows, dict) else None
        if rows is None:
            return []
        if isinstance(rows, dict):               # 상세 조회는 객체 하나로 온다
            rows = [rows]
        return rows or []

    def _to_cert(self, row: dict) -> CertRecord:
        f = self._op("certification")["fields"]
        g = lambda key: row.get(f.get(key, "")) if f.get(key) else None  # noqa: E731
        raw_state = g("status")
        return CertRecord(
            cert_number=str(row.get(f["cert_number"], "")),
            product_name=g("product_name"),
            model_name=g("model_name"),
            maker=g("maker"),
            status=raw_state,
            state=classify_cert_state(raw_state, self._map.get("cert_states", {})),
            detail_url=g("detail_url") or cert_evidence_url(row.get(f["cert_number"], "")),
            brand_name=g("brand_name"),
            category_name=g("category_name"),
            maker_country=g("maker_country"),
            importer=g("importer"),
            import_div=g("import_div"),
            cert_div=g("cert_div"),
            cert_date=g("cert_date"),
        )

    def _to_recall(self, row: dict, scope: str) -> RecallRecord:
        # 국내/국외는 필드 의미가 다르다. reason 과 action_guide 를 매핑에서 각각
        # 가져오는 이유가 그것이다. 하드코딩하면 국외 리콜에 위해내용 대신
        # 소비자 행동요령이 표시된다 (설계서 p.14 vs p.17).
        op = "recall_domestic" if scope == "domestic" else "recall_overseas"
        f = self._op(op)["fields"]
        g = lambda key: row.get(f.get(key, "")) if f.get(key) else None  # noqa: E731
        models_raw = g("model_name")
        uid = g("uid")
        return RecallRecord(
            product_name=g("product_name"),
            model_name=models_raw,
            maker=g("maker"),
            reason=g("reason"),
            announced_on=g("announced_on"),
            detail_url=g("detail_url"),
            scope=scope,
            # certNum 필드에서 두 종류를 뽑는다 — 인증번호와, 함께 적힌 모델명.
            # "(인증모델 : 대왕버블건)" 을 버리면 매칭 단서를 잃는다 (R6).
            models=split_list_field(models_raw) + [
                h for h in extract_model_hints(g("cert_numbers"))
                if h not in split_list_field(models_raw)
            ],
            cert_numbers=extract_cert_numbers(g("cert_numbers")),
            brand_name=g("brand_name"),
            recall_type=g("recall_type"),
            action_guide=g("action_guide"),
            uid=str(uid) if uid else None,
        )


def cert_evidence_url(cert_number: str) -> str:
    """근거 링크(R2)로 쓰는 인증번호별 상세 조회 팝업.

    설계서 p.18 의 "인증번호 상세 조회 (신)" URL 이다. 인증키가 필요 없어서
    셀러가 그대로 눌러 원문을 확인할 수 있다.

    후보 세 개를 실측(도쿄 리전)한 결과 이 주소만 쓴다:

      release/certDetail           200 이지만 설계서에 없는 주소다. 문서화되지
                                   않은 엔드포인트는 예고 없이 바뀌고, 파라미터가
                                   없어 특정 인증번호를 가리키지 못한다.
      release/certificationsearch  설계서 p.18 에 있으나 GET 에 405.
      search/searchPop?certNum=    200, 인증키 불필요, 인증번호별. 존재하지 않는
                                   번호도 빈 결과가 나오므로 미조회 케이스의
                                   근거로 그대로 쓸 수 있다.

    조회에 사용한 정규화 번호로 링크해야 화면 문구와 링크가 같은 대상을 가리킨다.
    주소는 매핑에서 읽는다 (CLAUDE.md R5).
    """
    return _CERT_DETAIL_TEMPLATE.format(cert_number=normalize_kc(cert_number))


# ---------------------------------------------------------------------------
# Fixtures for MOCK_MODE. Clearly fake so they can never be mistaken for real
# lookups: every mock record is tagged.
# ---------------------------------------------------------------------------
_MOCK_ROWS = {
    # 설계서 3.2.1 예시와 같은 모양. 실제 응답 필드명으로 목을 만들면 매핑 오류가
    # 목 모드에서도 드러난다.
    "JU071047-12002C": {
        "certNum": "JU071047-12002C", "certState": "적합",
        "certDiv": "전기용품안전관리법 대상>자율안전확인 대상",
        "productName": "[MOCK] 관상어용히터", "modelName": "SH-100",
        "categoryName": "전기기기>관상 및 애완용 전기기기", "brandName": None,
        "makerName": "[MOCK] Sanhu Factory", "makerCntryName": "중국",
        "importerName": "[MOCK] 수입사", "importDiv": "수입", "certDate": "20130719",
    },
    # 조회는 되지만 취소된 인증. 이게 초록불로 통과하면 안 된다.
    "CB123A123-1234": {
        "certNum": "CB123A123-1234", "certState": "안전인증취소",
        "certDiv": "어린이제품 특별법 대상>안전확인 대상",
        "productName": "[MOCK] 유아용섬유제품", "modelName": "아동배낭",
        "categoryName": None, "brandName": None,
        "makerName": "[MOCK] 아이테스트", "makerCntryName": "한국",
        "importerName": None, "importDiv": "제조", "certDate": "20190717",
    },
    # 표시 사용금지. 취소와 같은 무게로 다뤄야 한다.
    "XU07012345": {
        "certNum": "XU07012345", "certState": "안전인증표시 사용금지 2개월",
        "certDiv": "어린이제품 특별법 대상>안전확인 대상",
        "productName": "[MOCK] 유아용 블록 완구", "modelName": "BLK-100",
        "categoryName": None, "brandName": None,
        "makerName": "[MOCK] 안심완구", "makerCntryName": "한국",
        "importerName": None, "importDiv": "제조", "certDate": "20200101",
    },
}


def _mock_cert(key: str) -> CertRecord | None:
    row = _MOCK_ROWS.get(key)
    if row is None:
        return None
    f = _MOCK_FIELDS
    raw_state = row.get("certState")
    return CertRecord(
        cert_number=row["certNum"],
        product_name=row.get("productName"),
        model_name=row.get("modelName"),
        maker=row.get("makerName"),
        status=raw_state,
        state=classify_cert_state(raw_state, _MOCK_STATES),
        detail_url=cert_evidence_url(row["certNum"]),
        brand_name=row.get("brandName"),
        category_name=row.get("categoryName"),
        maker_country=row.get("makerCntryName"),
        importer=row.get("importerName"),
        import_div=row.get("importDiv"),
        cert_div=row.get("certDiv"),
        cert_date=row.get("certDate"),
    )


def _mock_recalls(term: str) -> list[RecallRecord]:
    if "RCL" not in (term or "").upper():
        return []
    # 콤마로 묶인 다중 모델. 통짜 비교하면 term 이 안 잡힌다.
    models = f"{term},HKAK31101S-00"
    return [
        RecallRecord(
            product_name="[MOCK] 가정용섬유제품(책가방)",
            model_name=models,
            maker="[MOCK] 제조사",
            reason="[MOCK] 프탈레이트계 가소제 기준 초과",
            announced_on="20260319",
            detail_url="https://www.safetykorea.kr/",
            scope="domestic",
            models=split_list_field(models),
            cert_numbers=["CB123A123-1234"],
            brand_name="JJ",
            recall_type="명령에따른리콜",
            action_guide="수선 및 교환, 환불",
            uid="3802",
        )
    ]
