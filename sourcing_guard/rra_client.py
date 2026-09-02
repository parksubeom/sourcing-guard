"""방송통신기자재 적합성평가(전파인증) 조회 어댑터.

KC 안전인증(전안법)과 **완전히 별개 제도**다. KC 마크가 있어도 전파인증이
없으면 위반이고, 무선 기능이 있는 공산품 대부분이 대상이라 셀러가 가장 자주
놓친다. KC 조회와 나란히 두는 축이지, KC 를 대체하는 것이 아니다.

두 경로가 **폴백 관계가 아니라 다른 질문에 답한다** (실측):

    페이지에 인증번호가 있음  -> emsit Open API   "이 번호가 유효한가"
    인증번호가 없음 (대부분)  -> RRA 공개 검색     "이 모델에 인증이 있나"

emsit 은 mtlCefNo 하나만 받는다. 모델명·상호로는 0001(조회내역없음)이 온다.
구매대행 상품은 대부분 번호가 없으므로 실사용 주력은 RRA 쪽이다.

CLAUDE.md R3-b 가 여기서도 그대로 걸린다. 자기적합확인 대상은 R- 번호가 아예
없고 별도 레지스트리에 자체 관리번호로 공개된다 - 전안법 SCoC 와 같은 구조다.
적합성평가 DB 미조회를 RED 로 두면 같은 오탐이 재발한다. RED 자격이 있는 것은
부적합 기자재 현황(A_d_list) 하나뿐이다.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx
import yaml

from .watchlist import normalize_model

_log = logging.getLogger(__name__)

_MAP_PATH = Path(__file__).parent / "data" / "rra_field_map.yaml"
_CFG: dict[str, Any] = yaml.safe_load(_MAP_PATH.read_text(encoding="utf-8")) or {}

_OPEN_API = _CFG.get("open_api", {})
_PUBLIC = _CFG.get("public_search", {})
_URLS = _CFG.get("public_urls", {})

# 신형 R-{C|R|I}-{식별부호}-{모델} 과 구형 KCC- 를 둘 다 받는다. 구형 번호도
# 현재 DB 에 실재하고 조회된다 (실측: KCC-REM-MJT-MJT, 2012년 접수건).
RF_NUMBER_RE = re.compile(r"(?i)\b(?:R-[CRI]-[A-Za-z0-9_]+-[A-Za-z0-9._-]+|KCC-[A-Za-z0-9-]+)\b")

# 요청 파라미터 누락. 우리 잘못이라 셀러에게 "다시 시도" 를 권하면 안 된다.
OPERATOR_FAULT_CODES = {"0098"}


# 모델명 검색 비용 - 실측 (2026-09-02, 반복 측정)
#
#   검색, 결과 있음   category 빈값  12.0초   99KB
#                    category=C      7.3초   (결과 없는 경우였다)
#                    category=R     22.5초
#   검색, 결과 0건                    1.3초   98KB
#   팝업                             0.1초    3.5KB   ← 사실상 공짜
#
# ⚠ 비용은 전부 검색에 있다. 팝업이 비쌀 것이라 보고 POPUP_LIMIT 을 조였는데
#   실측은 반대였다 - 팝업은 0.1초고 검색이 12초다.
#
# ⚠ 타임아웃을 8초로 뒀더니 "결과가 있는 질의만" 타임아웃됐다. 0건은 1.3초라
#   통과하고 1건 이상이면 12초라 실패하니, 인증이 있는 상품일수록 조회에
#   실패하는 최악의 편향이 된다. 실측보다 넉넉하게 잡는다.
SEARCH_TIMEOUT_SECONDS = 15.0
SEARCH_RESULT_LIMIT = 10   # 목록 1페이지가 10건이다
POPUP_LIMIT = 3            # 0.1초라 비용은 거의 없다. 재대조 대상 상한이다
MODEL_CACHE_TTL_SECONDS = 24 * 60 * 60


def is_searchable_model(model: str | None) -> bool:
    """이 모델명으로 RRA 를 검색해도 되는가.

    목록이 부분문자열 매칭이라 식별력이 낮은 문자열은 수천 페이지를 문다.
    실측 (2026-09-02, category 비움, model_no 축):

        모델명      글자  길이   총 페이지
        100          0    3     6,491     ← 숫자만
        1000         0    4     1,747
        A1           1    2     1,579
        AB           2    2       906
        Q1           1    2       250
        ABC          3    3        41
        M-1000       1    5        66     ← 길이 5인데 글자가 하나
        GP-500       2    5         3
        TS183        2    5         1
        A05418       1    6         1     ← 글자 하나여도 길면 괜찮다
        SM-R900      3    6         1
        WU922MS      4    7         1
        DECKTS183    6    9         1

    갈라지는 선이 "길이 5 이상 + 글자 1개 이상 + (글자 2개 이상 또는 길이 6
    이상)" 에서 정확히 맞는다. 숫자만인 문자열은 길이와 무관하게 뺀다.

    ⚠ watchlist 의 식별력 규칙(④)보다 엄격하다. 거기서는 강등이라는 중간
      단계가 있어 '100' 도 참고로 남길 수 있지만, 여기서는 질의 자체가
      6,491페이지를 물어 아예 던지면 안 된다.
    """
    key = normalize_model(model)
    n = len(key)
    if n < 5:
        return False
    alpha = sum(1 for c in key if c.isalpha())
    if alpha == 0:
        return False
    return alpha >= 2 or n >= 6


def models_match(ours: str | None, record: "RfCertRecord") -> bool:
    """검색 결과가 정말 이 상품인가.

    목록이 부분문자열 매칭이라 재대조 없이 쓰면 남의 인증을 이 상품 것으로
    말하게 된다 - "인증이 있다" 는 안심시키는 방향이라 가장 비싼 오류다.

    기본모델과 파생모델을 모두 본다. 셀러가 적은 것이 파생모델일 수 있다
    (실측: R-R-LGE-WU922M2604 의 파생 "WU922MC WU922MN WU922MW WU922MB").

    포함 매칭은 쓰지 않는다. 정확 일치에서 빠지면 미조회(AMBER)로 가는데,
    그건 확인을 권하는 방향이라 안전한 실패다.
    """
    key = normalize_model(ours)
    if not key:
        return False
    return any(normalize_model(m) == key for m in record.all_models)


class ModelSearchCache:
    """모델명 -> 조회 결과 TTL 캐시. kats_client.CertCache 와 같은 방식이다.

    검색 한 번이 요청 4회(목록 1 + 팝업 3)까지 가므로 캐시가 없으면 같은
    상품을 여러 셀러가 볼 때마다 RRA 를 그만큼 두드린다.
    """

    def __init__(self, ttl_seconds: int = MODEL_CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, str, list]] = {}

    def get(self, key: str) -> tuple[str, list] | None:
        with self._lock:
            hit = self._entries.get(key)
        if hit is None:
            return None
        stored_at, fetched_at, records = hit
        if (time.monotonic() - stored_at) > self._ttl:
            return None
        return fetched_at, records

    def put(self, key: str, records: list, fetched_at: str) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic(), fetched_at, list(records))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


class RraApiError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        self.code, self.message = str(code), message
        super().__init__(f"[{code}] {message}" if message else f"[{code}]")


class RfCertState(str, Enum):
    VERIFIED = "verified"      # 0000 - 유효한 적합성평가가 있다
    NOT_FOUND = "not_found"    # 0001 - 없다. 단 자기적합확인 여지 (R3-b)
    UNKNOWN = "unknown"        # 조회 자체를 못 했다


@dataclass(frozen=True)
class RfCertRecord:
    cert_number: str
    company: str | None = None
    equipment: str | None = None
    base_model: str | None = None
    derived_models: tuple[str, ...] = ()
    maker: str | None = None
    country: str | None = None
    cert_date: str | None = None
    state: RfCertState = RfCertState.VERIFIED

    @property
    def all_models(self) -> tuple[str, ...]:
        """기본 + 파생. 셀러 상품이 파생모델이어도 잡히게 한다."""
        out = [m for m in (self.base_model, *self.derived_models) if m]
        return tuple(dict.fromkeys(out))


def is_rf_number(value: str) -> bool:
    """전파인증 번호 형식인가.

    emsit 의 0001 은 "번호가 없다" 와 "애초에 번호가 아니다" 를 구분하지 못한다.
    형식 검증을 통과한 값만 던져야 0001 을 "미조회" 로 읽을 수 있다.
    """
    return bool(RF_NUMBER_RE.fullmatch((value or "").strip()))


def extract_rf_numbers(text: str) -> list[str]:
    """본문에서 전파인증 번호를 뽑는다. KC 번호(CB...)와 형식이 달라 섞이지 않는다."""
    return list(dict.fromkeys(m.group(0) for m in RF_NUMBER_RE.finditer(text or "")))


def split_derived_models(raw: str | None) -> list[str]:
    """파생모델 문자열을 개별 모델로 나눈다.

    구분자가 콤마가 아니라 **공백**이다 (실측 36건, 콤마·슬래시·세미콜론 0건):

        R-R-LGE-WU922M2604  파생 "WU922MC WU922MN WU922MW WU922MB"

    단순 공백 split 은 쓰지 않는다. 기본모델에 공백이 든 것이 실재하고
    (HDO3.0 Rev2), 문자열만으로 하나인지 둘인지 단정할 수 없다. 리콜 certNum 을
    구분자 분할에서 토큰 추출로 바꿨던 것과 같은 상황이다.
    """
    if not raw:
        return []
    tokens = [t for t in re.split(r"[\s,/;]+", str(raw)) if t]
    # 2자 미만 조각은 우연 충돌이 심해 버린다 (watchlist 식별력 규칙과 같은 취지).
    return list(dict.fromkeys(t for t in tokens if len(t) >= 2))


class RraClient:
    """전파인증 조회. 어댑터 계층 안에서만 외부 호출을 한다 (CLAUDE.md 6장)."""

    def __init__(self, *, mock: bool = False, timeout: float = 20.0) -> None:
        self._mock = mock
        self._model_cache = ModelSearchCache()
        # RRA 공개 검색은 응답이 100KB 대이고 느리다. emsit(XML 0.5KB)보다
        # 넉넉히 잡지 않으면 연속 호출에서 타임아웃이 난다 (실측).
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                # RRA 공개 검색의 게이트는 Referer 헤더의 '존재' 하나다. 값은
                # 검증하지 않지만, 우리 출처를 밝히는 편이 정직하다.
                "Referer": _URLS.get("search", "https://www.rra.go.kr/"),
                "User-Agent": "sourcing-guard/1.0 (+https://sourcing-guard.fly.dev)",
            },
        )

    # -- 번호가 있을 때: emsit ----------------------------------------------
    def lookup_number(self, cert_number: str) -> RfCertRecord | None:
        """인증번호로 조회한다. 형식이 아니면 던지지 않는다.

        명세: 인증번호는 '-' 유무와 상관없이 조회 가능.
        """
        number = (cert_number or "").strip()
        if not is_rf_number(number):
            return None
        if self._mock:
            return _MOCK.get(number.upper()) or _MOCK.get(number)

        op = _OPEN_API["operations"]["auth_info"]
        url = f"{_OPEN_API['base_url'].rstrip('/')}/{op['path']}"
        try:
            resp = self._client.get(url, params={op["param"]: number})
            resp.raise_for_status()
            body = resp.text
        except httpx.HTTPError as exc:
            # emsit 은 레이트 초과 시 XML 이 아니라 400 HTML 을 돌려준다(미문서화).
            # 파싱 실패를 조용히 흘리면 미조회가 GREEN 으로 반올림된다.
            raise RraApiError("network", type(exc).__name__) from exc
        return _parse_auth_info(body, number)

    # -- 번호가 없을 때: RRA 공개 검색 --------------------------------------
    def search_by_model(self, model: str, *, limit: int = SEARCH_RESULT_LIMIT) -> list[str]:
        """모델명으로 검색해 내부키 목록을 돌려준다.

        부분문자열 매칭이다. 호출측이 반환값을 반드시 재대조해야 하며
        (models_match), 짧은 모델명은 is_searchable_model 로 먼저 걸러야 한다.

        목록에는 인증번호가 없어 18자리 내부키만 나온다. 실제 번호는
        detail(내부키) 로 팝업을 한 번 더 열어야 한다.

        ⚠ category 는 빈 값으로 '존재' 해야 한다. 실측:

            category=C&model_no=WU922MS   0건   ← 적합등록(R-R-)을 통째로 놓친다
            category=R&model_no=WU922MS   1건
            category= &model_no=WU922MS   1건   ← 채택
            (category 파라미터 자체를 빼면)  0건

          소비자 무선기기 주류가 적합등록이라 C 로 고정하면 주력 경로가
          조용히 0건이 된다.
        """
        term = (model or "").strip()
        if not term or self._mock:
            return []

        op = _PUBLIC["operations"]["search"]
        url = f"{_PUBLIC['base_url'].rstrip('/')}/{op['path']}"
        try:
            # 한글 질의는 EUC-KR 퍼센트 인코딩이어야 한다. 폼이
            # accept-charset=euc-kr 이고, UTF-8 로 보내면 에러가 아니라 0건이
            # 돌아온다 (firm=삼성전자: UTF-8 0건 / EUC-KR 10건).
            query = _euc_kr_query({op["params"]["model"]: term, "category": ""})
            resp = self._client.get(f"{url}?{query}", timeout=SEARCH_TIMEOUT_SECONDS)
            resp.raise_for_status()
            # 검색 목록은 EUC-KR. 팝업은 UTF-8 - 페이지마다 다르다.
            body = resp.content.decode(_PUBLIC.get("encoding", "euc-kr"), "replace")
        except httpx.HTTPError as exc:
            raise RraApiError("network", type(exc).__name__) from exc

        if _PUBLIC.get("no_result_marker", "없습니다") in _strip_tags(body):
            return []
        keys = re.findall(r"A_b_popup\.do\?app_no=([0-9]{10,20})", body)
        return list(dict.fromkeys(keys))[:limit]

    def detail(self, internal_key: str) -> RfCertRecord | None:
        """내부키로 팝업을 열어 레코드를 만든다.

        팝업은 UTF-8 이다. 검색 목록(EUC-KR)과 다르므로 갈라 처리한다.
        모델명·파생모델명까지 읽는다 - 재대조(models_match)에 둘 다 필요하다.
        """
        if self._mock or not internal_key:
            return None
        op = _PUBLIC["operations"]["detail_popup"]
        url = f"{_PUBLIC['base_url'].rstrip('/')}/{op['path']}"
        try:
            resp = self._client.get(
                url, params={op["param"]: internal_key}, timeout=SEARCH_TIMEOUT_SECONDS
            )
            resp.raise_for_status()
            body = resp.content.decode(op.get("encoding", "utf-8"), "replace")
        except httpx.HTTPError as exc:
            raise RraApiError("network", type(exc).__name__) from exc
        return _parse_popup(body)

    def search_certs_by_model(self, model: str) -> list[RfCertRecord]:
        """모델명 -> (검색 -> 팝업) -> 재대조까지 끝낸 레코드 목록.

        번호가 없는 상품(구매대행 대부분)의 유일한 조회 경로다. emsit 은
        mtlCefNo 만 받으므로 여기서는 쓸 수 없다.

        비용이 크다 - 목록 1회 + 팝업 N회이고 RRA 응답은 100KB에 2초쯤 걸린다.
        그래서 세 겹으로 조인다:
          ① is_searchable_model 로 폭발하는 질의를 아예 안 던진다
          ② 팝업은 POPUP_LIMIT 건까지만 연다
          ③ 모델명 기준 TTL 캐시 (인증 조회 캐시와 같은 방식)
        """
        key = normalize_model(model)
        if not key or not is_searchable_model(model):
            return []
        if self._mock:
            return [r for r in _MOCK.values() if models_match(model, r)]

        cached = self._model_cache.get(key)
        if cached is not None:
            return list(cached[1])

        records: list[RfCertRecord] = []
        for internal_key in self.search_by_model(model)[:POPUP_LIMIT]:
            record = self.detail(internal_key)
            # 부분일치로 온 무관한 건을 여기서 떨어뜨린다. 목록이 부분문자열
            # 매칭이라 재대조 없이 쓰면 남의 인증을 이 상품 것으로 말하게 된다.
            if record is not None and models_match(model, record):
                records.append(record)

        self._model_cache.put(
            key, records, datetime.now(timezone.utc).isoformat(timespec="seconds")
        )
        return records


    # -- 부적합 현황 --------------------------------------------------------
    def fetch_noncompliant(self, *, max_pages: int = 300) -> list[dict]:
        """부적합 방송통신기자재 현황을 전량 수집한다.

        전파인증 축에서 **RED 자격이 있는 유일한 소스**다. 부적합사유·행정처분이
        명시되어 "정부 DB 가 적극적으로 문제를 적어둔" 조건을 만족한다 (R3-b).

        실측: 2,748건 / 275페이지 / 10건씩. 페이징은 cpage 만 먹고 page·pageNo·
        pageIndex 는 조용히 무시된다.

        인증번호 칸에 두 제도가 섞여 있다 - R-R-msg-DECKTS183(적합성평가)과
        PLCL-YK-006·CCMS-Q1(자기적합확인 관리번호). 목록 하나로 둘 다 대조된다.
        """
        if self._mock:
            return list(_MOCK_NONCOMPLIANT)

        cfg = _CFG.get("noncompliant", {})
        url = f"{cfg['base_url'].rstrip('/')}/{cfg['path']}"
        paging = cfg.get("paging", {})
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            params = {**paging.get("extra", {}), paging.get("param", "cpage"): str(page)}
            try:
                resp = self._client.get(url, params=params)
                resp.raise_for_status()
                body = resp.content.decode(cfg.get("encoding", "euc-kr"), "replace")
            except httpx.HTTPError as exc:
                raise RraApiError("network", type(exc).__name__) from exc

            rows = _parse_noncompliant_page(body)
            if not rows:
                break  # 빈 페이지 = 끝
            out.extend(rows)
        return out


def _parse_noncompliant_page(html: str) -> list[dict]:
    """목록 페이지의 표를 파싱한다.

    컬럼: 번호 / 상호 / 인증번호 / 모델명 / 처분일자 / 조치결과.
    매칭에 필요한 축이 목록에 다 있어 상세 2,748건을 열 필요가 없다.
    """
    out: list[dict] = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"(?is)<[^>]+>", "", c)).strip()
            for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        ]
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        out.append({
            "seq": cells[0],
            # 목록에 HTML 주석 잔재(-->)가 섞여 나온다. 실측 확인.
            "company": cells[1].replace("-->", "").strip() or None,
            "cert_number": cells[2] or None,
            "model": cells[3] or None,
            "acted_on": cells[4] or None,
        })
    return out


def _parse_popup(html: str) -> "RfCertRecord | None":
    """팝업(UTF-8)에서 레코드를 만든다.

    항목: 상호 / 기기명칭 / 모델명 / 파생모델명 / 인증번호 / 제조자 / 제조국가 /
    인증연월일. 목록에는 인증번호가 없어 이 팝업이 유일한 출처다.
    """
    fields: dict[str, str] = {}
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html):
        cells = [
            re.sub(r"\s+", " ", re.sub(r"(?is)<[^>]+>", " ", c)).strip()
            for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row)
        ]
        cells = [c for c in cells if c]
        for i in range(0, len(cells) - 1, 2):
            fields.setdefault(cells[i], cells[i + 1])

    number = fields.get("인증번호") or ""
    if not number:
        found = RF_NUMBER_RE.search(_strip_tags(html))
        number = found.group(0) if found else ""
    if not number:
        return None
    return RfCertRecord(
        cert_number=number,
        company=fields.get("상호") or None,
        equipment=fields.get("기기명칭") or None,
        base_model=fields.get("모델명") or None,
        derived_models=tuple(split_derived_models(fields.get("파생모델명"))),
        maker=fields.get("제조자") or None,
        country=fields.get("제조국가") or None,
        cert_date=fields.get("인증연월일") or None,
    )


def _euc_kr_query(params: dict[str, str]) -> str:
    from urllib.parse import quote

    return "&".join(f"{k}={quote(str(v), encoding='euc-kr')}" for k, v in params.items())


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"(?is)<[^>]+>", " ", html))


def _parse_auth_info(body: str, asked: str) -> RfCertRecord | None:
    """emsit XML 응답을 레코드로. 파싱 실패는 예외로 올린다.

    400 HTML(레이트 초과)을 조용히 "없음" 으로 흘리면 미조회가 GREEN 으로
    반올림된다. 못 읽은 것과 없는 것은 다르다 (R3).
    """
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise RraApiError("parse", "XML 이 아닌 응답 - 레이트 초과 가능") from exc

    def text(tag: str) -> str | None:
        el = root.find(tag)
        return el.text.strip() if el is not None and el.text else None

    code = text("resultCode") or ""
    if code == "0001":
        return None
    if code and code != "0000":
        raise RraApiError(code, text("resultMsg") or "")

    f = _OPEN_API["fields"]
    # 파생모델이 없으면 태그가 통째로 빠진다(빈 태그가 아님). 파서가 이걸
    # 파싱 실패로 읽으면 안 된다.
    return RfCertRecord(
        cert_number=text(f["cert_number"]) or asked,
        company=text(f["company"]),
        equipment=text(f["equipment"]),
        base_model=text(f["base_model"]),
        derived_models=tuple(split_derived_models(text(f["derived_models"]))),
        maker=text(f["maker"]),
        country=text(f["country"]),
        cert_date=text(f["cert_date"]),
    )


def rf_evidence_url(cert_number: str | None = None) -> str:
    """근거 링크(R2). 인증키가 필요 없는 공개 검색 페이지."""
    return _URLS.get("search", "https://www.rra.go.kr/ko/license/A_c_search.do")


_MOCK_NONCOMPLIANT = [
    {"seq": "2748", "company": "[MOCK] 주식회사 퓨어엘코스",
     "cert_number": "PLCL-YK-006", "model": "YK-006", "acted_on": "2026-08-31"},
    {"seq": "2747", "company": "[MOCK] 주식회사 코어커머스",
     "cert_number": "CCMS-Q1", "model": "Q1", "acted_on": "2026-08-31"},
]


_MOCK = {
    "R-C-GRM-A05418": RfCertRecord(
        cert_number="R-C-GRm-A05418",
        company="[MOCK] Garmin Corporation.",
        equipment="특정소출력 무선기기(무선데이터통신시스템용 무선기기)",
        base_model="A05418",
        maker="[MOCK] Garmin Corporation.",
        country="대만",
        cert_date="2026-08-10",
    ),
    "KCC-REM-MJT-MJT": RfCertRecord(
        cert_number="KCC-REM-MJT-MJT",
        company="[MOCK] (주)명정보기술",
        equipment="SSD",
        base_model="MITS3016GN1-S",
        derived_models=("MITS3002GN1-S", "MITS3004GN1-S"),
        maker="[MOCK] (주)명정보기술",
        country="한국",
        cert_date="2012-05-07",
    ),
}
