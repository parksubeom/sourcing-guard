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
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import httpx
import yaml

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
    def search_by_model(self, model: str, *, limit: int = 10) -> list[str]:
        """모델명으로 검색해 내부키 목록을 돌려준다.

        부분문자열 매칭이다 (model_no=100 이 10건). 호출측이 반환값을 반드시
        재대조해야 하며, 짧은 모델명은 watchlist 식별력 규칙으로 걸러야 한다.

        목록에는 인증번호가 없어 18자리 내부키만 나온다. 실제 번호는
        detail(내부키) 로 팝업을 한 번 더 열어야 한다.
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
            query = _euc_kr_query({op["params"]["model"]: term, "category": "C"})
            resp = self._client.get(f"{url}?{query}")
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
        """내부키로 팝업을 열어 실제 인증번호를 얻는다.

        팝업은 UTF-8 이다. 검색 목록(EUC-KR)과 다르므로 갈라 처리한다.
        """
        if self._mock or not internal_key:
            return None
        op = _PUBLIC["operations"]["detail_popup"]
        url = f"{_PUBLIC['base_url'].rstrip('/')}/{op['path']}"
        try:
            resp = self._client.get(url, params={op["param"]: internal_key})
            resp.raise_for_status()
            body = resp.content.decode(op.get("encoding", "utf-8"), "replace")
        except httpx.HTTPError as exc:
            raise RraApiError("network", type(exc).__name__) from exc

        found = RF_NUMBER_RE.search(_strip_tags(body))
        return RfCertRecord(cert_number=found.group(0)) if found else None


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
