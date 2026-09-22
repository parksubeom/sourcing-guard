"""인증 조회 캐시 시드.

재배포하면 `CertCache` 가 0 이 된다. 국표원이 죽어 있는 동안 배포하면 데모의
인증 축이 전부 "조회 실패" 로 뜬다. 시드는 그 구멍을 막는다.

⚠⚠ 이 파일이 지키는 것은 **"데모가 산다"** 가 아니라 **"거짓으로 살지
  않는다"** 이다. 시드를 fresh 로 얹으면 화면이 하루 묵은 레코드를 두고
  "조회되었습니다" 라고 말한다 - 조회하지 않았는데 조회했다고 하는 것이고,
  이 저장소가 가장 비싸다고 적어 둔 방향이다 (CLAUDE.md §6).

  그래서 양쪽을 다 잰다:
    시드가 있고 국표원이 죽었다  → 답하되 **"조회분으로 표시"** 를 단다
    시드가 없고 국표원이 죽었다  → 조회 실패로 간다 (조용한 초록불 없음)
    시드가 있고 국표원이 살았다  → **실조회가 이긴다** (시드가 눌러앉지 않는다)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from sourcing_guard.cert_seed import SEED_PATH, apply_to, load_entries
from sourcing_guard.demos import DEMOS
from sourcing_guard.kats_client import (
    CERT_NUMBER_RE,
    CertRecord,
    CertState,
    KatsApiError,
    KatsClient,
    normalize_kc,
)


# ── 실제로 배포되는 시드 파일 ────────────────────────────────────────
_KNOWN_SKIP = "키와 담긴 번호가 다르다"


def test_the_shipped_seed_is_only_dropped_for_a_reason_we_know():
    """걸러진 줄이 있으면 그 번호는 시드가 없는 것과 같다. 조용히 줄면 안 된다.

    ⚠⚠ 전에는 `skipped == 0` 이었다. 2026-09-22 에 **실제로 0 이 아니게 됐고,
      그때 이 검사가 옳았다** - 시드가 깨끗하지 않았다. 9/19 에 옛 코드
      (`rows[0]`)로 만들어 **셀러가 적은 번호를 키로 하고 다른 인증의 레코드를
      담은 줄**이 5건 섞여 있었다.

      그런 줄은 캐시에서 조회가 끝나게 만들어 `_pick_exact` 를 건너뛰고,
      「적합」이면 **거짓 GREEN** 이 된다. 적재에서 거르는 것이 안전망이다.

    ⚠ 그래서 조건을 `== 0` 에서 **「모르는 이유로는 안 걸러진다」**로 옮겼다.
      수를 박지 않는다 - 시드를 다시 만들면(`scripts/build_cert_seed.py`,
      `_pick_exact` 를 거친다) 0 이 되고, 그때도 이 검사는 그대로 통과한다.
      새로운 **종류**의 오염이 생기면 걸린다.
    """
    entries, stats = load_entries()
    assert entries, "시드 파일이 비어 있다 - 재배포하면 데모의 인증 축이 죽는다"
    unknown = [r for r in stats.reasons if _KNOWN_SKIP not in r]
    assert not unknown, f"모르는 이유로 걸러진 줄: {unknown}"


def test_every_seeded_number_looks_like_a_cert_number():
    entries, _ = load_entries()
    for e in entries:
        assert CERT_NUMBER_RE.fullmatch(e.cert_number), e.cert_number


def test_every_seeded_time_is_a_past_iso_instant():
    """미래 시각이면 화면이 아직 오지 않은 날짜로 '조회분' 을 말한다."""
    now = datetime.now(timezone.utc)
    entries, _ = load_entries()
    for e in entries:
        when = datetime.fromisoformat(e.fetched_at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        assert when <= now, f"{e.cert_number} 의 조회 시각이 미래다: {e.fetched_at}"


def test_the_seed_covers_every_number_the_demos_mention():
    """⚠ 데모 버튼이 곧 첫 화면이다. 데모 번호가 시드에 없으면 재배포가 그 버튼을 죽인다.

    데모 문구를 바꿔 새 번호를 넣으면 이 검사가 먼저 깨진다. 그때
    `scripts/build_cert_seed.py` 를 다시 돌린다.
    """
    entries, _ = load_entries()
    seeded = {e.cert_number for e in entries}
    for demo in DEMOS:
        for m in CERT_NUMBER_RE.finditer(demo["text"]):
            key = normalize_kc(m.group(0))
            assert key in seeded, (
                f"데모 '{demo['title']}' 의 {key} 가 시드에 없다 - "
                "scripts/build_cert_seed.py 를 다시 돌릴 것"
            )


def test_the_seed_file_carries_no_contact_information():
    """국표원 등록 원부라 개인정보는 없다. 그래도 새 필드가 들어오면 여기서 걸린다."""
    raw = SEED_PATH.read_text(encoding="utf-8")
    import re

    assert not re.search(r"\b0\d{1,2}-\d{3,4}-\d{4}\b", raw), "전화번호 모양이 있다"
    assert not re.search(r"\b\d{3}-\d{2}-\d{5}\b", raw), "사업자번호 모양이 있다"
    assert "@" not in raw, "이메일 모양이 있다"


# ── 얹는 동작 ────────────────────────────────────────────────────────
class _DeadKats(KatsClient):
    """국표원이 죽은 상태. 실조회는 전부 실패한다."""

    def __init__(self) -> None:
        super().__init__(None, "K", mock=False)
        self.calls = 0

    def lookup_certification(self, kc_number: str) -> CertRecord | None:
        self.calls += 1
        raise KatsApiError("network", "timed out")


class _LiveKats(KatsClient):
    """국표원이 살아 있는 상태. 실조회가 새 값을 준다."""

    def __init__(self) -> None:
        super().__init__(None, "K", mock=False)
        self.calls = 0

    def lookup_certification(self, kc_number: str) -> CertRecord | None:
        self.calls += 1
        return CertRecord(
            cert_number=normalize_kc(kc_number), product_name="완구",
            model_name=None, maker=None, status="안전인증취소",
            state=CertState.REVOKED, detail_url=None,
        )


def _seed_file(tmp_path, *, number="CB061R2170-3018", when=None, record=True):
    when = when or (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(
        timespec="seconds")
    payload = {
        "entries": [{
            "cert_number": number,
            "fetched_at": when,
            "record": {
                "cert_number": number, "product_name": "완구", "model_name": None,
                "maker": None, "status": "적합", "state": "ok", "detail_url": None,
            } if record else None,
        }]
    }
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_seeded_entries_land_in_the_cache(tmp_path):
    client = _DeadKats()
    stats = apply_to(client, _seed_file(tmp_path))
    assert stats.loaded == 1 and stats.applied == 1
    assert len(client._cert_cache) == 1


def test_a_dead_lookup_answers_from_the_seed_but_says_it_is_not_fresh(tmp_path):
    """⚠ 이것이 시드의 목적이다. 그리고 **조용히** 답하면 안 된다."""
    client = _DeadKats()
    apply_to(client, _seed_file(tmp_path))

    result = client.lookup_certification_cached("CB061R2170-3018")

    assert result.record is not None and result.record.status == "적합"
    assert result.stale is True, "시드를 최신 조회인 것처럼 내보냈다"
    assert result.fetched_at, "언제 조회한 것인지 없이 답했다"
    assert client.calls == 1, "시드가 fresh 로 들어가 실조회를 건너뛰었다"


def test_without_a_seed_a_dead_lookup_fails_loudly(tmp_path):
    """**반대 방향.** 시드가 없으면 조회 실패여야 한다 - 조용한 None 은 다른 뜻이다."""
    client = _DeadKats()
    with pytest.raises(KatsApiError):
        client.lookup_certification_cached("CB061R2170-3018")


def test_a_live_lookup_wins_over_the_seed(tmp_path):
    """시드는 만료 상태로 들어간다. 국표원이 살아나면 **그날로** 밀려나야 한다.

    fresh 로 넣었다면 취소된 인증이 24시간 동안 '적합' 으로 보인다.
    """
    client = _LiveKats()
    apply_to(client, _seed_file(tmp_path))

    result = client.lookup_certification_cached("CB061R2170-3018")

    assert client.calls == 1, "시드가 fresh 라 실조회를 안 했다"
    assert result.stale is False
    assert result.record.status == "안전인증취소", "낡은 시드가 이겼다"


def test_a_live_value_is_never_overwritten_by_the_seed(tmp_path):
    """이미 조회해 둔 값이 파일보다 새롭다."""
    client = _LiveKats()
    client.lookup_certification_cached("CB061R2170-3018")   # 실조회로 캐시를 채운다
    apply_to(client, _seed_file(tmp_path))

    assert client._cert_cache.get("CB061R2170-3018") is not None, "시드가 덮었다"


# ── 깨진 시드 ────────────────────────────────────────────────────────
def test_a_future_timestamp_is_dropped_not_trusted(tmp_path):
    when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec="seconds")
    entries, stats = load_entries(_seed_file(tmp_path, when=when))
    assert entries == []
    assert stats.skipped == 1


def test_a_placeholder_number_is_dropped(tmp_path):
    entries, stats = load_entries(_seed_file(tmp_path, number="비대상"))
    assert entries == []
    assert stats.skipped == 1


def test_an_unknown_state_is_dropped_rather_than_rounded_to_unknown(tmp_path):
    """R3. 모르는 상태값을 UNKNOWN 으로 반올림하면 화면이 아는 척을 한다."""
    p = tmp_path / "seed.json"
    p.write_text(json.dumps({"entries": [{
        "cert_number": "CB061R2170-3018",
        "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "record": {"cert_number": "CB061R2170-3018", "state": "무슨상태"},
    }]}, ensure_ascii=False), encoding="utf-8")

    entries, stats = load_entries(p)
    assert entries == []
    assert stats.skipped == 1


def test_a_missing_file_is_not_an_error(tmp_path):
    entries, stats = load_entries(tmp_path / "없는파일.json")
    assert entries == [] and stats.skipped == 0


def test_a_broken_file_does_not_raise(tmp_path):
    p = tmp_path / "seed.json"
    p.write_text("{ 이건 json 이 아니다", encoding="utf-8")
    entries, stats = load_entries(p)
    assert entries == []
    assert stats.reasons, "왜 못 읽었는지 남기지 않았다"


# ── 앱이 실제로 얹는가 ───────────────────────────────────────────────
def test_the_app_seeds_the_cache_on_startup():
    """⚠ 2026-09-14 에 `register_settings_secrets()` 가 프로덕션에서 한 번도 안
    불린 적이 있다. 시작 훅에 넣었다는 것과 불린다는 것은 다르다.
    """
    from fastapi.testclient import TestClient

    from sourcing_guard.main import app

    with TestClient(app) as client:
        body = client.get("/healthz").json()

    assert "cert_seed" in body, "/healthz 가 시드 상태를 말하지 않는다"
    assert body["cert_seed"]["loaded"] > 0, "시작 시 시드를 얹지 않았다"
    # ⚠ `skipped == 0` 이 아니다. 부분일치 시드(2026-09-22 · 5건)는 **걸러지는
    #   것이 맞다** - 자세한 이유는 `test_the_shipped_seed_is_only_dropped_…`.
    #   여기서는 **모르는 이유로 걸러지지 않는가**만 본다.
    unknown = [r for r in body["cert_seed"]["reasons"] if "키와 담긴 번호가 다르다" not in r]
    assert not unknown, unknown


def test_seeding_twice_in_one_process_reports_it_as_already_loaded():
    """⚠ `loaded` 와 `applied` 를 가르는 이유.

    같은 프로세스에서 두 번째 시작은 **새로 넣은 것이 0** 이다. 하나로 뭉치면
    "시드가 비었다" 와 "이미 얹혀 있다" 가 같은 0 으로 보인다 - 실제로 이
    파일의 시작 검사가 전체 실행에서만 깨져서 알았다.
    """
    from sourcing_guard.kats_client import KatsClient

    client = KatsClient(None, "K", mock=False)
    first = apply_to(client)
    second = apply_to(client)

    assert first.applied > 0 and second.applied == 0
    assert second.loaded == first.loaded, "파일에서 읽은 수는 같아야 한다"


def test_a_seed_row_whose_record_is_a_different_number_is_rejected(tmp_path):
    """**키와 담긴 번호가 다르면 싣지 않는다.**

    국표원 조회는 접두 부분일치로 답한다. 2026-09-22 이전 코드가 `rows[0]` 을
    썼기 때문에 그 전에 만든 시드에는 셀러가 적은 번호를 키로 하고 **다른
    인증의 레코드**를 담은 줄이 섞여 있다 - 실측으로 29건 중 5건이었다.

    그런 줄을 캐시에 얹으면 조회가 캐시에서 끝나 `_pick_exact` 가 **불리지
    않는다.** 셀러가 적은 번호로 남의 인증 상태가 나가고, 그것이 「적합」이면
    거짓 GREEN 이다. 같은 날 실측으로 -9001(기간만료) vs -9001r(적합) 이 확인됐다.

    주의(중요): 거른 줄은 캐시 미스가 되어 **실조회**로 간다. 정부 API 가
      죽어 있으면 "조회 실패" 가 되고, 그게 거짓 GREEN 보다 낫다 (R3).
    """
    import json
    from pathlib import Path

    from sourcing_guard.cert_seed import load_entries

    def row(key: str, got: str, status: str = "적합") -> dict:
        return {
            "cert_number": key,
            "fetched_at": "2026-09-19T14:02:56+00:00",
            "record": {"cert_number": got, "product_name": "완구",
                       "model_name": "M", "maker": "-", "status": status,
                       "state": "ok",
                       "detail_url": f"http://www.safetykorea.kr/search/searchPop?certNum={got}"},
        }

    p = Path(tmp_path) / "seed.json"
    p.write_text(json.dumps({"entries": [
        row("CB061R2170-3018", "CB061R2170-3018"),          # 같다 - 실린다
        row("CB064R2424-9001", "CB064R2424-9001R"),         # 접미 - 걸러진다
        row("HU073506-24001", "HU073506-24001A"),           # 접미 - 걸러진다
        row("CB113H018-2012", "cb113h018-2012"),            # 대소문자만 - 실린다
    ]}, ensure_ascii=False), encoding="utf-8")

    entries, stats = load_entries(p)
    kept = {e.cert_number for e in entries}
    assert kept == {"CB061R2170-3018", "CB113H018-2012"}, kept
    assert stats.loaded == 2 and stats.skipped == 2, (stats.loaded, stats.skipped)
    assert all("키와 담긴 번호가 다르다" in r for r in stats.reasons), stats.reasons


def test_the_shipped_seed_has_no_partial_match_rows_left_after_filtering():
    """리포에 든 시드에 그 줄이 몇 개인지 **세서** 적는다.

    2026-09-22 기준 29건 중 5건이 걸러진다(9/19 에 옛 코드로 만든 것). 시드를
    다시 만들면 `_pick_exact` 를 거치므로 0 이 된다 - 그때 이 검사는 여전히
    통과한다(거를 것이 없을 뿐). 0 을 보고 통과하는 것이 아니라 **걸러진 뒤
    남은 것에 어긋난 줄이 없다**를 잠근다.
    """
    from pathlib import Path

    from sourcing_guard.cert_seed import load_entries
    from sourcing_guard.kats_client import normalize_kc

    entries, stats = load_entries(Path("sourcing_guard/data/cert_seed.json"))
    assert entries, "시드가 통째로 비었다 - 그러면 이 검사는 침묵이다"
    for e in entries:
        got = normalize_kc(str(e.record.cert_number or ""))
        assert got == e.cert_number, f"{e.cert_number} 에 {got} 가 실렸다"
    # ⚠ 수를 박지 않는다. 파일에 든 줄 수에서 끌어온다 - 시드를 다시 만들면
    #   건수가 달라지고, 박아 두면 결함이 아닌 이유로 깨진다.
    raw = json.loads(Path("sourcing_guard/data/cert_seed.json").read_text(encoding="utf-8"))
    assert stats.loaded + stats.skipped == len(raw["entries"]), (
        stats.loaded, stats.skipped, len(raw["entries"]))
