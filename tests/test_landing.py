"""[G-1] 랜딩 `/` 와 도구 `/scan` 의 분리 — 구조만. 디자인은 시피님이 새로 한다.

설계 문서 `docs/랜딩페이지_설계.md` §1·§2·§3·§4 를 잠근다.

⚠⚠ 설계 §4 가 "화면 중복 검사(24자)에 걸린다" 고 적어 뒀는데 **그 검사는 존재하지
  않았다.** 문서가 코드보다 앞선 네 번째 사례다(§6). 여기서 실제로 만든다 -
  보이는 텍스트를 24자 창으로 밀어 두 화면이 같은 문장을 반복하지 않는지 본다.
  같은 안내문이 두 화면에 있으면 투표자는 스크롤을 두 번 읽고, 심사위원은 한
  화면이 다른 화면의 복사본이라고 읽는다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sourcing_guard import main as app_module

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "sourcing_guard" / "static"
_LANDING = (_STATIC / "landing.html").read_text(encoding="utf-8")
_SCAN = (_STATIC / "index.html").read_text(encoding="utf-8")


def _visible(html: str) -> str:
    """스크립트·주석·헤더(네비)·태그를 빼고 **본문 카피**만. 공백은 하나로.

    ⚠ 헤더/네비는 모든 페이지가 공유하는 크롬이라 뺀다. 처음엔 안 뺐다가
      "소개 상품 검사 대량 검사 감시 목록" 이 24자 겹침으로 잡혔다 - 그건
      중복이 아니라 일관성이다. 이 검사가 보려는 것은 **설명 문장의 반복**이다.
    """
    s = re.sub(r"<script\b[\s\S]*?</script>", " ", html, flags=re.I)
    s = re.sub(r"<header\b[\s\S]*?</header>", " ", s, flags=re.I)
    s = re.sub(r"<nav\b[\s\S]*?</nav>", " ", s, flags=re.I)
    s = re.sub(r"<!--[\s\S]*?-->", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(s.split())


# ── 라우트 (설계 §1) ───────────────────────────────────────────────
def test_root_is_the_landing_and_scan_is_the_tool():
    from sourcing_guard.main import app

    with TestClient(app) as c:
        root = c.get("/").text
        scan = c.get("/scan").text
    # ⚠ **주석을 걷어내고 본다.** 무엇을 왜 옮겼는지 적으려면 옛 문구를
    #   인용해야 하고, 그러면 이 가드가 **자기 감사 기록에 걸린다** - 이
    #   저장소에서 열네 번째다. 화면에 그려지는 것만 센다.
    root_body = re.sub(r"<!--[\s\S]*?-->", " ", root)
    scan_body = re.sub(r"<!--[\s\S]*?-->", " ", scan)
    # v2 문구 (design/landing-v2.html). 랜딩은 소개, /scan 이 도구다.
    assert "내 상품 검사하기" in root_body and 'id="pt"' not in root_body
    assert 'id="pt"' in scan_body and "내 상품 검사하기" not in scan_body


def test_every_page_links_the_tool_at_scan_not_root():
    """`/` 가 도구에서 소개로 바뀌었다. 옛 링크가 남으면 소개로 튄다."""
    for name in ("index.html", "batch.html", "watch.html", "landing.html", "guide.html"):
        src = (_STATIC / name).read_text(encoding="utf-8")
        assert 'href="/scan"' in src, f"{name} 에 /scan 링크가 없다"
        # "/" 는 소개 링크로만 남는다 - 도구 문구를 달고 있으면 옛 링크다.
        for m in re.finditer(r'<a href="/"[^>]*>([^<]*)</a>', src):
            assert "검사" not in m.group(1), f'{name}: href="/" 가 아직 도구를 가리키는 문구다: {m.group(1)!r}'


# ── 24자 중복 검사 (설계 §4 · 이 검사는 여기서 처음 생겼다) ────────
_SHARED_BY_DESIGN = (
    "본 결과는 공개된 정부 데이터에 기반한 참고 정보이며, 법적 판단이나 안전 인증을 대체하지 않습니다.",
    "출처 · 국가기술표준원 제품안전정보센터 공개 API, 어린이제품 공통안전기준(산업통상자원부고시 제2022-220호)",
    "안심 소싱 돋보기",
    "이 상품, 팔아도 되는지 확인합니다",   # 히어로 제목 - 설계 §2 가 두 화면 같게 뒀다
    # ⚠ **일부러 같게 뒀다** (총괄 명령 ②-d · 2026-09-14). 랜딩 히어로가
    #   "상세페이지를 붙여넣으세요 / KC 인증 · 리콜 · 유해물질 기준을 정부
    #   원문으로 확인합니다" 로 약속하고, /scan 이 그 약속을 실행하는 화면이다.
    #   누르고 넘어온 셀러가 같은 말을 다시 보는 것이 맞다.
    "상세페이지를 붙여넣으세요.",
    "KC 인증 · 리콜 · 유해물질 기준을 정부 원문으로 확인합니다.",
)


def test_landing_and_scan_do_not_repeat_the_same_sentences():
    a, b = _visible(_LANDING), _visible(_SCAN)
    for shared in _SHARED_BY_DESIGN:
        a = a.replace(shared, " "); b = b.replace(shared, " ")
    a = " ".join(a.split()); b = " ".join(b.split())
    dup = sorted({a[i:i + 24] for i in range(len(a) - 23) if a[i:i + 24] in b})
    assert not dup, "랜딩과 /scan 이 같은 문장을 반복합니다 (24자 창):\n  " + "\n  ".join(dup[:8])


# ── 데모 버튼 (설계 §2) ────────────────────────────────────────────
def test_landing_demo_buttons_come_from_the_server_and_go_to_scan():
    from sourcing_guard.demos import DEMO_TEXTS

    assert "/api/v1/demos" in _LANDING
    assert "/scan?demo=" in _LANDING
    for text in DEMO_TEXTS:
        assert text not in _LANDING, "데모 문구가 랜딩에 하드코딩됐다"


def test_scan_runs_the_demo_from_the_query_and_labels_it():
    """투표자 클릭 1번에 결과 - `/scan?demo=<tone>` 을 읽어 자동 검사한다."""
    assert 'get("demo")' in _SCAN and "URLSearchParams" in _SCAN
    assert 'id="demo-note"' in _SCAN                 # "이 예시는 …" 한 줄
    assert "예시 문구를 검사한 것" in _SCAN
    # 사용자가 입력란을 손대면 예시 표시는 사라져야 한다.
    assert re.search(r'\$\("demo-note"\)\.hidden\s*=\s*true', _SCAN)


# ── 숫자 넷 (design/README §10-2) ────────────────────────────────
def test_the_landing_asks_the_server_for_the_baseline_figures():
    """70.4% · 135건 · 0건을 **마크업에 적지 않는다.**

    ⚠⚠ 전에는 HTML 에 숫자를 적어 두고 이 검사가 `audit_tally.BASELINE` 과
      대조했다. 그것은 같은 숫자를 **두 곳에 적는** 것이라 §6 이 막는 모양
      그대로였다 - 기준선을 옮기면 화면이 낡는다. 이제 서버가 낸다.
    """
    from fastapi.testclient import TestClient as _TC

    sys.path.insert(0, str(_ROOT / "scripts"))
    from audit_tally import BASELINE, BASELINE_EXTRACTOR

    b = BASELINE[BASELINE_EXTRACTOR]
    got = _TC(app_module.app).get("/healthz").json()["baseline"]
    assert got["ok"] == b["ok"]
    assert got["denominator"] == b["denominator"]
    assert got["off_target"] == b["off_target"]
    assert got["ok_rate"] == round(b["ok"] / b["denominator"] * 100, 1)
    assert got["extractor"] == BASELINE_EXTRACTOR
    # 상한은 내지 않는다 - 검수 전 숫자를 검수된 숫자처럼 읽게 만든 전례가 있다.
    assert "ok_upper" not in got


def test_the_numbers_dropped_in_v2_are_really_gone():
    """랜딩에서 뺀 숫자들 (design/README §10-2).

    ⚠ 빼기로 한 것을 빼지 않으면 "숫자가 너무 많다" 는 비평이 그대로 남는다.
    """
    v = _visible(_LANDING)
    for gone in ("71%", "24%", "20.0%", "83.7%", "94개", "88%", "83%", "80%", "70%",
                 "2026-08-06", "verified", "draft"):
        assert gone not in v, f"v2 에서 빼기로 한 숫자가 남아 있다: {gone}"
    # 절 번호도 지웠다.
    for num in "⓪①②③④⑤⑥":
        assert num not in v, f"절 번호 {num} 가 남아 있다"


def test_the_phrases_dropped_in_v2_are_really_gone():
    """지운 말투 (design/README §10-3). "AI 같은 말투는 집어치워" - 시피님."""
    v = _visible(_LANDING)
    for gone in ("조사 결과가 먼저 말합니다", "확인해 보자고 만들었습니다",
                 "이건 결함이 아니라 전제입니다", "안 한 것과 없는 것은 다르다",
                 "정직한 숫자"):
        assert gone not in v, f"지우기로 한 문구가 남아 있다: {gone}"


def test_data_figures_are_not_hardcoded():
    """리콜 수·공표일도 그 자리에서 그린다."""
    v = _visible(_LANDING)
    for stale in ("4,244", "4,245", "33,085", "33,105", "37,350"):
        assert stale not in v, f"리콜 수가 하드코딩됐다: {stale}"
    assert 'fetch("/healthz")' in _LANDING
    for key in ("recalls", "as_of", "ok_rate", "denominator", "off_target"):
        assert f'data-h="{key}"' in _LANDING, key
    # 값이 안 오면 "-" 로 남는다 - 지어내지 않는다.
    assert '"-"' in _LANDING


# ── 2절 - 무엇을 안 하나 (설계 §3-②) ─────────────────────────────
def test_the_landing_says_what_it_does_not_do():
    v = _visible(_LANDING)
    assert "판정은 하지 않습니다" in v
    assert "초록불은 보증이 아닙니다" in v
    # R2 를 말한다. v2 에서 자리가 둘로 갈렸다 - 세 칸은 정부 원문으로 링크하고,
    # 예시 카드 아래가 "모든 줄에 원문 링크가 붙습니다" 를 말한다(스크립트가 그린다).
    assert v.count("원문 ·") >= 3, "세 칸에 정부 원문 링크가 없다"
    assert "모든 줄에 원문 링크가 붙습니다" in _LANDING
    # 무엇을 확인하지 않는지 그대로 적는다 (v2 문구).
    for item in ("인증번호 도용", "실제 함유량", "앞으로의 리콜",
                 "상표권 · 원산지", "식약처 소관 품목"):
        assert item in v, item
    for banned in ("안전합니다", "합법입니다", "판매 가능합니다", "문제없습니다", "걸리지 않습니다."):
        assert banned not in v, banned


# ── 디자인 무관 (G-1 조건) ────────────────────────────────────────
def test_landing_keeps_its_styles_in_app_css_and_its_mark_empty():
    """인라인 스타일·인라인 색을 두지 않는다. 마크 자리는 아직 빈 span 이다.

    ⚠⚠ **2026-09-13 에 이름과 전제가 바뀌었다.** 전에는
      `test_landing_has_no_logo_color_or_favicon_and_an_empty_mark` 였고
      `rel="icon"` 과 `favicon.svg` 를 **금지**했다. 사유가
      "디자인은 시피님이 새로 한다" 였는데 **디자인 시스템 v0.1 이 도착했고**
      총괄이 적용을 지시했다 - 전제가 만료됐다.

      금지가 아니라 **요구**가 된 것은 `tests/test_design_tokens.py` 가 맡는다
      (네 화면이 같은 파비콘·폰트를 쓴다). 같은 단정을 두 곳에 적지 않는다.

    ⚠⚠ **2026-09-13 에 마크를 뒤집었다.** 위에서 "단계 4~5 에서 채운다" 고
      적었고 그대로 됐다 - 빈 span 이던 자리에 마스코트 32px 이 들어갔다.
      (2026-09-18 에 `#mungchi-calm` → `#ansimi-GREEN` 으로 갈았다.)
      빈 span 이 자리만 차지하고 있어 **워드마크가 본문보다 오른쪽으로 밀려
      보였다**(헤더-본문 좌측선 불일치). 그림이 들어가면서 정렬이 맞았다.
    """
    # ⚠ **실제 태그만 본다.** 주석이 "페이지 전용 스타일 태그를 두지 않는다"
    #   라고 적으면 그 문구에 걸린다 - 이 저장소에서 열 번째 자기 함정이다.
    assert not re.search(r"<style[\s>]", _LANDING), "페이지 전용 스타일이 생겼다"
    assert "logo.svg" not in _LANDING
    # 마크는 마스코트 스프라이트를 참조한다. aria-hidden 이어야 한다 -
    # 뜻을 나르지 않는 그림이다.
    m = re.search(r'<svg class="mark"[^>]*>', _LANDING)
    assert m, "헤더 마크가 없다"
    assert "aria-hidden" in m.group(0), "마크에 aria-hidden 이 없다"
    assert 'href="/static/mascot.svg#ansimi-GREEN"' in _LANDING
    assert '<span class="mark"' not in _LANDING, "빈 span 이 남아 있다"
    # 인라인 색상 지정이 없다 - app.css 토큰만.
    assert not re.search(r'style="[^"]*(color|background)', _LANDING)
    assert "/static/app.css" in _LANDING
