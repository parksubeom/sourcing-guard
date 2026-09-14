"""식약처 수집기 — **HTTP 200 을 성공으로 읽지 않는지** 잠근다.

⚠⚠ 이 검사가 있는 이유는 실측이다 (2026-09-14 17:15 KST · 실호출 1회):

      HTTP 200 · total_count='0'
      RESULT={'CODE': 'ERROR-503',
              'MSG': '09시~19시에는 서비스가 제한됩니다. 이용에 참고바랍니다.'}

  상태 코드만 보면 "받았다" 가 되고 **빈 목록이 정상처럼 흐른다.** `resultCode`
  를 안 봐서 kats·rra 양쪽에서 이미 겪은 자리다 (CLAUDE.md §6). 우리가 이해하지
  못한 응답은 성공이 아니다 (R3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from sync_mfds_recalls import MfdsError, body, collect, fetch  # noqa: E402

#: 실제로 받은 응답 그대로. 지어낸 모양이 아니다.
_TIME_LIMITED = {
    "I0490": {
        "total_count": "0",
        "RESULT": {"MSG": "09시~19시에는 서비스가 제한됩니다. 이용에 참고바랍니다.",
                   "CODE": "ERROR-503"},
    }
}


class _Resp:
    def __init__(self, doc): self._doc = doc
    def raise_for_status(self): return None
    def json(self): return self._doc


class _Client:
    """페이지마다 미리 정한 응답을 돌려준다. 네트워크 없음."""
    def __init__(self, *docs): self.docs = list(docs); self.urls: list[str] = []
    def get(self, url):
        self.urls.append(url)
        return _Resp(self.docs.pop(0) if self.docs else self.docs)


def _ok(rows, total, code="INFO-000"):
    return {"I0490": {"total_count": str(total), "RESULT": {"CODE": code, "MSG": "정상"},
                      "row": rows}}


def test_a_time_limited_reply_is_not_a_success():
    """⚠⚠ **실측 응답.** 200 이고 CODE 가 ERROR-503 이면 멈춘다."""
    with pytest.raises(MfdsError) as e:
        body(_TIME_LIMITED)
    assert "ERROR-503" in str(e.value)
    assert "09시~19시" in str(e.value), "왜 멈췄는지 사람이 읽을 수 있어야 한다"


def test_an_unknown_code_is_not_a_success():
    """모르는 코드는 성공이 아니다 (R3). 통과시키면 빈 목록이 정상이 된다."""
    with pytest.raises(MfdsError):
        body({"I0490": {"total_count": "0", "RESULT": {"CODE": "INFO-200", "MSG": "?"}}})


def test_a_missing_block_is_not_a_success():
    with pytest.raises(MfdsError):
        body({"어떤다른것": {}})


def test_an_error_reply_never_becomes_an_empty_collection():
    """⚠ 가장 비싼 실패 모양 - 오류를 '0건 수집' 으로 흘리는 것."""
    with pytest.raises(MfdsError):
        collect("KEY", page=3, client=_Client(_TIME_LIMITED))


def test_pages_until_the_total_is_reached():
    rows_a = [{"PRDTNM": f"제품{i}"} for i in range(3)]
    rows_b = [{"PRDTNM": "제품3"}]
    c = _Client(_ok(rows_a, 4), _ok(rows_b, 4))
    rows, total, calls = collect("KEY", page=3, client=c)
    assert [r["PRDTNM"] for r in rows] == ["제품0", "제품1", "제품2", "제품3"]
    assert total == 4 and calls == 2
    assert c.urls[0].endswith("/json/1/3") and c.urls[1].endswith("/json/4/6")


def test_an_empty_page_stops_the_loop():
    """총건수가 거짓말해도 무한히 돌지 않는다."""
    c = _Client(_ok([], 999))
    rows, total, calls = collect("KEY", page=5, client=c)
    assert rows == [] and calls == 1


def test_a_single_row_object_is_accepted_as_one_row():
    """행이 하나면 list 가 아니라 dict 로 올 수 있다 (law.go.kr 에서 겪었다)."""
    c = _Client(_ok({"PRDTNM": "하나"}, 1))
    rows, _, _ = collect("KEY", page=5, client=c)
    assert rows == [{"PRDTNM": "하나"}]


def test_the_key_is_in_the_path_so_the_url_carries_it():
    """⚠ 키가 **경로**에 있다는 사실을 검사로 남긴다 - 마스킹이 필요한 이유다."""
    c = _Client(_ok([], 0))
    collect("SECRET-KEY-VALUE", page=2, client=c)
    assert "/api/SECRET-KEY-VALUE/I0490/" in c.urls[0]

    from sourcing_guard.masking import mask_url, register_secret

    register_secret("SECRET-KEY-VALUE")
    assert "SECRET-KEY-VALUE" not in mask_url(c.urls[0])


def test_the_host_check_runs_before_the_call():
    """허용 호스트 검사를 거치지 않고 나가지 않는다 (R4)."""
    import sync_mfds_recalls as mod

    called: list[str] = []
    original = mod.ensure_allowed
    mod.ensure_allowed = lambda u: called.append(u)
    try:
        fetch("K", 1, 2, client=_Client(_ok([], 0)))
    finally:
        mod.ensure_allowed = original
    assert called and called[0].startswith("http://openapi.foodsafetykorea.go.kr/")
