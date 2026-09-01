"""상세 스펙표 이미지를 만든다. 이미지 입력 경로를 실제로 눌러보기 위한 것이다.

기획서 §2 에서 "상세표가 이미지뿐인 페이지"를 입력 경로로 열어뒀다. 그 경로가
라이브에서 도는지 확인하려면 진짜 이미지가 필요하다. 스크린샷을 매번 손으로
만들지 않기 위해 표를 그려서 PNG 로 저장한다.

⚠ 인증번호는 넣지 않는다. 추출기가 이미지에서 인증번호를 읽지 않도록 막아뒀고
  (0/O 오독이 정상 인증을 "미조회"로 만든다), 그 규약을 이미지로 시험한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"

ROWS = [
    ("제품명", "말랑 블록 완구 세트 120피스"),
    ("모델명", "MB-120S"),
    ("제조국", "중국"),
    ("수입원", "가나다무역"),
    ("재질", "ABS, TPE"),
    ("사용연령", "3세 이상"),
    ("구성", "블록 120개, 보관함 1개"),
    ("크기", "블록 1개 약 3.2cm"),
]


def build(path: Path) -> None:
    w, row_h, pad = 760, 56, 28
    h = pad * 2 + row_h * (len(ROWS) + 1)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    head = ImageFont.truetype(FONT, 26, index=2)
    body = ImageFont.truetype(FONT, 22, index=0)

    y = pad
    d.rectangle([pad, y, w - pad, y + row_h], fill="#eef2f7")
    d.text((pad + 18, y + 14), "상품 상세 정보", font=head, fill="#111827")
    y += row_h

    for i, (k, v) in enumerate(ROWS):
        if i % 2:
            d.rectangle([pad, y, w - pad, y + row_h], fill="#fafbfc")
        d.line([pad, y, w - pad, y], fill="#d7dce3")
        d.text((pad + 18, y + 16), k, font=body, fill="#4b5563")
        d.text((pad + 210, y + 16), v, font=body, fill="#111827")
        y += row_h

    d.rectangle([pad, pad, w - pad, y], outline="#c8cfd8", width=1)
    d.line([pad + 195, pad + row_h, pad + 195, y], fill="#d7dce3")
    img.save(path, "PNG")


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/spec.png")
    build(out)
    print(f"{out}  {out.stat().st_size:,} bytes")
