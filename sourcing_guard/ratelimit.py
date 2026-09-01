"""호출 상한. 투표 기간 18일을 버티기 위한 장치다 (핸드오프 §8 인프라 리스크).

두 가지를 따로 막는다. 막는 이유가 다르기 때문이다.

  IP당 분당 제한   한 사람이 스크립트로 두드리는 것을 막는다. 넘으면 429.
  일일 LLM 상한    비용을 막는다. 넘어도 서비스는 계속 돈다 - LLM 대신
                   휴리스틱으로 내리고 그 사실을 화면에 적는다.

⚠ 데모 3종은 두 제한 모두와 무관하게 동작해야 한다 (핸드오프 §9, §10).
  투표자가 첫 화면에서 버튼을 눌렀는데 429 를 보면 그대로 이탈한다. 상한은
  낯선 사람의 반복 호출을 막으려는 것이지 데모를 막으려는 것이 아니다.

상태는 프로세스 메모리에 둔다. 머신 하나에 워커 하나라 충분하고, 재시작으로
초기화되는 것이 오히려 맞다 - 어제 쓴 예산을 오늘 물려받을 이유가 없다.
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import date

# 한 사람이 화면을 쓰는 속도. 붙여넣고 결과를 읽는 데 최소 몇 초는 걸린다.
DEFAULT_PER_MINUTE = 12

# 하루 LLM 호출 상한. 골든셋 1회가 11건이고 스캔 1건이 1회다.
# 넘으면 서비스가 멈추는 것이 아니라 휴리스틱으로 내려간다.
DEFAULT_DAILY_LLM = 500


def text_fingerprint(text: str) -> str:
    """공백을 접은 뒤 해시. 데모 버튼이 보내는 문장을 알아보기 위한 것이다."""
    normalized = " ".join((text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class RateLimiter:
    """IP당 분당 제한 + 일일 LLM 예산.

    면제 지문(데모 3종)은 둘 다 통과시킨다.
    """

    def __init__(
        self,
        *,
        per_minute: int = DEFAULT_PER_MINUTE,
        daily_llm: int = DEFAULT_DAILY_LLM,
        exempt: set[str] | None = None,
    ) -> None:
        self._per_minute = per_minute
        self._daily_llm = daily_llm
        self._exempt = exempt or set()
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}
        self._llm_day: date | None = None
        self._llm_used = 0

    # -- 면제 --------------------------------------------------------------

    def is_exempt(self, fingerprint: str) -> bool:
        return fingerprint in self._exempt

    def register_exempt(self, *texts: str) -> None:
        for t in texts:
            self._exempt.add(text_fingerprint(t))

    # -- IP당 분당 ---------------------------------------------------------

    def allow_request(self, client_ip: str, *, fingerprint: str = "", now: float | None = None) -> bool:
        if self.is_exempt(fingerprint):
            return True
        t = time.monotonic() if now is None else now
        with self._lock:
            window = [h for h in self._hits.get(client_ip, ()) if t - h < 60.0]
            if len(window) >= self._per_minute:
                self._hits[client_ip] = window
                return False
            window.append(t)
            self._hits[client_ip] = window
            # 오래된 IP 를 흘려보낸다. 안 그러면 투표 기간 내내 쌓인다.
            if len(self._hits) > 4096:
                self._hits = {
                    ip: hs for ip, hs in self._hits.items() if any(t - h < 60.0 for h in hs)
                }
            return True

    def retry_after_seconds(self, client_ip: str, *, now: float | None = None) -> int:
        t = time.monotonic() if now is None else now
        with self._lock:
            window = [h for h in self._hits.get(client_ip, ()) if t - h < 60.0]
        if not window:
            return 1
        return max(1, int(60.0 - (t - min(window))) + 1)

    # -- 일일 LLM 예산 ------------------------------------------------------

    def _roll_day(self, today: date) -> None:
        if self._llm_day != today:
            self._llm_day = today
            self._llm_used = 0

    def take_llm_budget(self, *, fingerprint: str = "", today: date | None = None) -> bool:
        """LLM 을 써도 되는가. 면제 지문은 예산을 소모하지 않는다."""
        if self.is_exempt(fingerprint):
            return True
        d = today or date.today()
        with self._lock:
            self._roll_day(d)
            if self._llm_used >= self._daily_llm:
                return False
            self._llm_used += 1
            return True

    def snapshot(self, *, today: date | None = None) -> dict:
        d = today or date.today()
        with self._lock:
            self._roll_day(d)
            return {
                "per_minute": self._per_minute,
                "daily_llm_limit": self._daily_llm,
                "daily_llm_used": self._llm_used,
                "exempt_fingerprints": len(self._exempt),
                "tracked_ips": len(self._hits),
            }
