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

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

_MAP_PATH = Path(__file__).parent / "data" / "kats_field_map.yaml"

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


@dataclass(frozen=True)
class CertRecord:
    cert_number: str
    product_name: str | None
    model_name: str | None
    maker: str | None
    status: str | None
    detail_url: str | None


@dataclass(frozen=True)
class RecallRecord:
    product_name: str | None
    model_name: str | None
    maker: str | None
    reason: str | None
    announced_on: str | None
    detail_url: str | None
    scope: str  # "domestic" | "overseas"


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

    def search_recalls(self, *, product_name: str | None, model_name: str | None) -> list[RecallRecord]:
        term = (model_name or product_name or "").strip()
        if not term:
            return []
        if self._mock:
            return _mock_recalls(term)
        # 모델명이 있으면 모델명으로, 없으면 제품명으로 찾는다. conditionKey 가
        # 검색 대상 필드를 정하므로 무엇으로 찾는지 명시해야 한다 (설계서 p.9, p.15).
        logical = "model_name" if model_name else "product_name"
        out: list[RecallRecord] = []
        for op, scope in (("recall_domestic", "domestic"), ("recall_overseas", "overseas")):
            rows = self._call(op, self._query(op, logical, term))
            out.extend(self._to_recall(r, scope) for r in rows)
        return out

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
        resp.raise_for_status()
        payload = resp.json()

        # 설계서 p.19: HTTP 200 이어도 resultCode 로 실패를 알린다. 이걸 안 보면
        # 인증 실패(4000)나 IP 미등록(4001)을 "조회 결과 없음"으로 착각하고,
        # 그러면 멀쩡한 인증번호에 RED 를 띄우게 된다.
        code = str(payload.get("resultCode", "")) if isinstance(payload, dict) else ""
        if code == _CODE_NO_DATA:
            return []
        if code and code != _CODE_SUCCESS:
            raise KatsApiError(code, str(payload.get("resultMsg", "")))

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
        return CertRecord(
            cert_number=str(row.get(f["cert_number"], "")),
            product_name=row.get(f.get("product_name", "")),
            model_name=row.get(f.get("model_name", "")),
            maker=row.get(f.get("maker", "")),
            status=row.get(f.get("status", "")),
            detail_url=row.get(f.get("detail_url", "")) or _center_search_url(row.get(f["cert_number"], "")),
        )

    def _to_recall(self, row: dict, scope: str) -> RecallRecord:
        op = "recall_domestic" if scope == "domestic" else "recall_overseas"
        f = self._op(op)["fields"]
        return RecallRecord(
            product_name=row.get(f.get("product_name", "")),
            model_name=row.get(f.get("model_name", "")),
            maker=row.get(f.get("maker", "")),
            reason=row.get(f.get("reason", "")),
            announced_on=row.get(f.get("announced_on", "")),
            detail_url=row.get(f.get("detail_url", "")),
            scope=scope,
        )


def _center_search_url(cert_number: str) -> str:
    """근거 링크(R2)로 쓰는 인증정보 상세 조회 팝업.

    설계서 p.18 의 "인증번호 상세 조회 (신)" URL 이다. 인증키가 필요 없어서
    셀러가 그대로 눌러 원문을 확인할 수 있다.
    """
    return f"http://www.safetykorea.kr/search/searchPop?certNum={cert_number}"


# ---------------------------------------------------------------------------
# Fixtures for MOCK_MODE. Clearly fake so they can never be mistaken for real
# lookups: every mock record is tagged.
# ---------------------------------------------------------------------------
_MOCK_CERTS = {
    "XU07012345": CertRecord(
        cert_number="XU07012345",
        product_name="[MOCK] 유아용 블록 완구",
        model_name="BLK-100",
        maker="[MOCK] 안심완구",
        status="유효",
        detail_url=_center_search_url("XU07012345"),
    )
}


def _mock_cert(key: str) -> CertRecord | None:
    return _MOCK_CERTS.get(key)


def _mock_recalls(term: str) -> list[RecallRecord]:
    if "RCL" in term.upper():
        return [
            RecallRecord(
                product_name="[MOCK] 리콜 대상 완구",
                model_name=term,
                maker="[MOCK] 제조사",
                reason="[MOCK] 프탈레이트계 가소제 기준 초과",
                announced_on="2026-03-19",
                detail_url="https://www.safetykorea.kr/",
                scope="domestic",
            )
        ]
    return []
