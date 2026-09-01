#!/usr/bin/env python3
"""국표원 API 응답 스키마 탐침기.

필드명을 추측해 코드에 박는 대신, 실제 응답을 한 번 받아서 구조를 출력하고
kats_field_map.yaml 에 넣을 후보를 제안합니다. (CLAUDE.md R5)

인증키는 헤더 `AuthKey` 로 보냅니다. 쿼리 파라미터가 아닙니다 (설계서 v2.0).
호스트가 평문 HTTP 라는 점에 유의하세요.

    python scripts/probe_kats_schema.py \
        --base-url http://<설계서에 적힌 호스트> \
        --path <설계서에 적힌 오퍼레이션 경로> \
        --key $KATS_SERVICE_KEY \
        --extra type=json --extra numOfRows=3
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

# 응답 필드명 후보 → 논리 필드명. 실제 스키마 확인 시 사람이 판단할 근거로만 씁니다.
RESULT_CODES = {
    "2000": "Success",
    "2004": "No Data",
    "4000": "Invalid Auth Key",
    "4001": "Invalid IP",
    "4005": "Invalid Parameter",
    "5000": "Internal Server Error",
}

HINTS = {
    "cert_number": ["cert", "인증번호", "certnum", "certno"],
    "product_name": ["prdt", "제품명", "productname", "goods"],
    "model_name": ["model", "모델"],
    "maker": ["maker", "manuf", "제조", "수입", "company", "업체"],
    "reason": ["reason", "사유", "위해", "hazard"],
    "announced_on": ["date", "일자", "공표", "dt"],
}


def walk(node, path=""):
    """리스트가 담긴 경로를 찾아 rows_path 후보를 반환."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list) and node:
        yield path, node


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--key", required=True)
    p.add_argument(
        "--auth-header",
        default="AuthKey",
        help="설계서 v2.0: 인증키는 헤더로 보내며 이름이 대소문자를 구분합니다.",
    )
    p.add_argument("--extra", action="append", default=[], help="k=v")
    a = p.parse_args()

    params: dict[str, str] = {}
    for kv in a.extra:
        k, _, v = kv.partition("=")
        params[k] = v

    url = f"{a.base_url.rstrip('/')}/{a.path.lstrip('/')}"
    r = httpx.get(url, params=params, headers={a.auth_header: a.key}, timeout=15.0)
    print(f"HTTP {r.status_code}  {r.headers.get('content-type')}\n", file=sys.stderr)

    if "json" not in (r.headers.get("content-type") or ""):
        print("JSON 이 아닙니다. 응답 앞부분:\n", r.text[:1500])
        print("\n→ type=json 파라미터가 필요하거나 XML 전용 오퍼레이션일 수 있습니다.")
        return 1

    data = r.json()

    # resultCode 필드만 본다. 본문 전체에서 코드 문자열을 찾으면 안 된다 —
    # "CB065R2397-4001" 처럼 -4001 로 끝나는 인증번호가 실제로 흔해서,
    # 성공한 응답(2000)에 Invalid IP 경고가 뜬다. 실제로 겪었다.
    code = str(data.get("resultCode") or "")
    if code and code != "2000":
        print(
            f"\n※ 결과코드 {code} ({RESULT_CODES.get(code, '알 수 없음')})."
            + ("\n  서비스 ID 가 등록 IP 에 묶여 있습니다. 출발 IP 를 확인하세요 (핸드오프 §4)."
               if code == "4001" else ""),
            file=sys.stderr,
        )
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    print("\n" + "=" * 60)

    for path, rows in walk(data):
        if not isinstance(rows[0], dict):
            continue
        keys = list(rows[0].keys())
        print(f"\nrows_path 후보: {path.split('.')}")
        print(f"필드 {len(keys)}개: {keys}")
        print("\n매핑 제안 (반드시 설계서와 대조하세요):")
        for logical, hints in HINTS.items():
            hit = [k for k in keys if any(h in k.lower() for h in hints)]
            if hit:
                print(f"  {logical:14s} → {hit}")
    print("\n※ 제안은 이름 유사도일 뿐입니다. 확정 전 인터페이스 설계서로 검증하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
