#!/usr/bin/env python3
"""HWP 5.0 → 텍스트 추출.

국가기술표준원 고시·부속서는 HWP로만 배포되는 경우가 많습니다. HWP 5.0 은
OLE 복합문서이고 본문은 zlib 로 압축된 레코드 스트림이라, 한글 프로그램 없이
읽을 수 있습니다.

    pip install olefile
    python scripts/hwp2txt.py 어린이제품_공통안전기준.hwp -o docs/공통안전기준.txt

주의: 이 스크립트는 문단 텍스트만 뽑습니다. 표 구조와 페이지 번호는 보존되지
않으므로, hazard_rules.yaml 의 기준치를 여기서 바로 확정하지 마세요.
추출 결과는 어디를 볼지 찾는 용도이고, 최종 대조는 원문 뷰어로 해야 합니다
(CLAUDE.md R5, §5).
"""

from __future__ import annotations

import argparse

import struct
import sys
import zlib

try:
    import olefile
except ImportError:
    sys.exit("olefile 이 필요합니다:  pip install olefile")

HWPTAG_PARA_TEXT = 67


def extract(path: str) -> str:
    ole = olefile.OleFileIO(path)
    streams = {"/".join(s) for s in ole.listdir()}

    if "FileHeader" not in streams:
        raise SystemExit(f"{path}: HWP 5.0 형식이 아닙니다.")

    header = ole.openstream("FileHeader").read()
    compressed = bool(header[36] & 0x01)

    sections = sorted(s for s in streams if s.startswith("BodyText/Section"))
    if not sections:
        raise SystemExit(f"{path}: BodyText 스트림이 없습니다.")

    out: list[str] = []
    for name in sections:
        data = ole.openstream(name).read()
        if compressed:
            data = zlib.decompress(data, -15)
        out.extend(_paragraphs(data))
    return "\n".join(out)


def _decode_para(raw: bytes) -> str:
    """Decode one PARA_TEXT payload, skipping embedded control records.

    HWP stores control characters in the same UTF-16 stream as text. Codes
    1-3, 11-12, 14-18 (extended) and 4-9, 19-20 (inline) each occupy **8 code
    units**, not one. Stripping only the leading unit leaves the remaining 7
    behind, which decode as random CJK glyphs -- the '捤獥汤捯' noise.
    """
    units = [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw) - 1, 2)]
    eight_wide = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20}

    out: list[str] = []
    i, n = 0, len(units)
    while i < n:
        c = units[i]
        if c in eight_wide:
            i += 8
            continue
        if c < 32:              # single-unit control (line break, para end, ...)
            i += 1
            continue
        out.append(chr(c))
        i += 1
    return "".join(out).strip()


def _paragraphs(data: bytes) -> list[str]:
    """Walk the record stream and pull HWPTAG_PARA_TEXT payloads."""
    out: list[str] = []
    i, n = 0, len(data)
    while i + 4 <= n:
        (hdr,) = struct.unpack("<I", data[i : i + 4])
        tag = hdr & 0x3FF
        size = (hdr >> 20) & 0xFFF
        i += 4
        if size == 0xFFF:                       # extended size record
            if i + 4 > n:
                break
            (size,) = struct.unpack("<I", data[i : i + 4])
            i += 4
        if tag == HWPTAG_PARA_TEXT:
            text = _decode_para(data[i : i + size])
            if text:
                out.append(text)
        i += size
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="HWP 5.0 텍스트 추출")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out", help="출력 파일 (생략 시 표준출력)")
    a = ap.parse_args()

    chunks = []
    for f in a.files:
        chunks.append(f"===== {f} =====")
        chunks.append(extract(f))

    text = "\n".join(chunks)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"{len(text):,}자 → {a.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
