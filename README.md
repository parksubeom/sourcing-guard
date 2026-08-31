# sourcing-guard

**안심 소싱 돋보기** — 이커머스 셀러용 KC 인증·리콜 리스크 스크리너

**배포**: https://sourcing-guard.fly.dev (목 모드 가동 중)

> **이어서 작업하는 사람은 `docs/작업로그_2026-09-01.md` 부터 읽으세요.**
> 지금 상태와 바로 착수할 일이 거기 있습니다.
>
> 결정 사항과 그 이유, 검증된 API 사실, 남은 일정은 `00_프로젝트_핸드오프.md` 에 있습니다.

---

## 실행

**Python 3.11 이상이 필요합니다.** 코드가 런타임에 평가되는 `X | None` 표기를 쓰므로
3.10 이하에서는 import 단계에서 실패합니다.

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # MOCK_MODE=true 로 키 없이 구동됩니다
pytest -q                     # 100 passed
uvicorn sourcing_guard.main:app --reload
curl -s localhost:8000/healthz
```

`/healthz` 는 목 모드 여부, 활성/초안 룰 개수, 워치리스트 등록 건수를 돌려줍니다.
활성 룰이 0이면 정상입니다 — 아래 "설계상 눈여겨볼 지점" 참조.

## 무엇이 들어 있나

| 파일 | 역할 |
|---|---|
| `models.py` | 스키마. `Finding`은 근거 URL 없이는 **생성 자체가 불가능**하고, "안전합니다" 같은 단정 문구도 생성자에서 거부됩니다 |
| `config.py` | `.env` 로더. `MOCK_MODE` 기본값이 true 라 키 없이도 전 파이프라인이 돕니다 |
| `extractor.py` | ① Claude 추출. 프롬프트에 안전성 판단 요청이 없습니다. 키가 없으면 휴리스틱으로 대체 구동 |
| `kats_client.py` | SafetyKorea API 어댑터. 필드명을 하드코딩하지 않고 `data/kats_field_map.yaml`에서 주입 |
| `verifier.py` | ② 결정론 검증. 규칙 DB 로더 포함 |
| `scorer.py` | 위험도 연산. 순수 함수, I/O·시각·난수 없음 |
| `watchlist.py` | 리콜 워치리스트 매칭. 순수 함수, 저장소 비의존 |
| `storage.py` | 워치리스트 SQLite 저장소. `WATCHLIST_DB_PATH` 로 경로 지정 |
| `main.py` | FastAPI. `/healthz`, `/api/v1/scan`, `/api/v1/watch`(등록·조회), `/api/v1/watch/sweep` |
| `data/hazard_rules.yaml` | 자체 규칙 DB. `status: draft`는 스코어링에서 제외 |
| `scripts/probe_kats_schema.py` | API 응답 스키마 탐침 |

## 설계상 눈여겨볼 지점

**GREEN은 두 축의 적극적 증거가 모두 있어야 나옵니다.** 침묵은 증거가 아닙니다. finding이 하나도 없으면 GREEN이 아니라 UNKNOWN입니다.

**선언된 커버리지만으로는 부족합니다.** `hazard_rules.yaml`의 `coverage`에 품목군이 적혀 있어도, 그 품목군에 `verified` 룰이 하나도 없으면 커버되지 않은 것으로 처리됩니다. 그래서 지금 상태(17건 전부 draft)에서는 완구조차 UNKNOWN이 나옵니다. 의도된 동작입니다. 승격 절차는 `docs/규칙DB_검수목록.md` 참조.

**워치리스트만 오류 비대칭이 반대입니다.** 스캔은 모르면 UNKNOWN으로 물러서지만, 리콜 알림은 놓치는 쪽이 훨씬 비쌉니다. 그래서 약한 매칭도 버리지 않고 `MatchStrength`(정확/유사/약한 일치)를 붙여 내보냅니다. 다만 3자 미만 모델명("A1")은 우연 충돌이 심해 아예 매칭하지 않습니다.

**UNKNOWN일 때 점수는 0으로 강제됩니다.** "모릅니다" 옆에 78점 같은 안심시키는 숫자를 띄우지 않기 위해서입니다.

현재 목 모드 동작:

```
[인증 적합]     → UNKNOWN  (규칙 DB 미검증 상태이므로 정직하게 모름)
[인증 취소]     → RED
[표시 사용금지] → RED
[인증 미조회]   → AMBER    (SCoC 대상은 조회 DB에 없는 게 정상. CLAUDE.md R3-b)
[리콜 일치]     → RED
[품목 미분류]   → UNKNOWN
```

**RED는 정부 DB가 문제를 적어둔 경우에만 줍니다. 부재는 증거가 아닙니다** (R3-b).

## 미구현 / 알려진 불일치

- **실응답 검증만 남았습니다.** 경로·파라미터·필드명은 설계서 v2.0 원문 대조로
  전부 채웠습니다(`kats_field_map.yaml`, 항목마다 원문 페이지 주석). 인증키가 오면
  `scripts/probe_kats_schema.py` 로 실제 응답과 한 번 대조하면 됩니다.
- 프론트엔드(0%), 리콜 로컬 동기화 스케줄러(`kats_client.recalls_published_on()` 이
  준비됨), Extractor 실제 프롬프트와 골든셋, 알림 발송(v1 범위 밖).
- **배포 시 `WATCHLIST_DB_PATH` 를 영구 볼륨으로 지정해야 합니다.** 컨테이너 기본
  파일시스템에 두면 재배포마다 워치리스트가 사라져, 이 서비스가 유일하게 보증하는
  알림 약속이 조용히 깨집니다 (기획서 §6.1).

## 다음에 할 일

**`docs/작업로그_2026-09-01.md` §2 를 보세요.** 바로 착수할 것은 **규칙 DB 검수**입니다.

배포는 끝났고(https://sourcing-guard.fly.dev), 매핑도 설계서 대조로 확정됐습니다.
규칙 DB 검수가 D4~D7 구간 전체를 쓰는 진짜 작업이고, 프로젝트의 유일한 진입장벽입니다.
지금 `active_rules: 0` 이라 신호등이 갈라지지 않습니다.
