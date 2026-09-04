# 안심 소싱 돋보기 — 매칭 엔진 뼈대

```bash
pip install -r requirements.txt
cp .env.example .env          # MOCK_MODE=true 로 키 없이 구동됩니다
pytest -q                     # 9 passed
uvicorn sourcing_guard.main:app --reload
curl -s localhost:8000/healthz
```

## 무엇이 들어 있나

| 파일 | 역할 |
|---|---|
| `models.py` | 스키마. `Finding`은 근거 URL 없이는 **생성 자체가 불가능**하고, "안전합니다" 같은 단정 문구도 생성자에서 거부됩니다 |
| `extractor.py` | ① Claude 추출. 프롬프트에 안전성 판단 요청이 없습니다. 키가 없으면 휴리스틱으로 대체 구동 |
| `kats_client.py` | 국표원 API 어댑터. 필드명을 하드코딩하지 않고 `data/kats_field_map.yaml`에서 주입 |
| `verifier.py` | ② 결정론 검증. 규칙 DB 로더 포함 |
| `scorer.py` | 위험도 연산. 순수 함수, I/O·시각·난수 없음 |
| `data/hazard_rules.yaml` | 자체 규칙 DB. `status: draft`는 스코어링에서 제외 |
| `watchlist.py` | 리콜 워치리스트 매칭. 순수 함수, 저장소 비의존 |
| `scripts/probe_kats_schema.py` | API 응답 스키마 탐침 |

## 설계상 눈여겨볼 지점

**GREEN은 두 축의 적극적 증거가 모두 있어야 나옵니다.** 침묵은 증거가 아닙니다. finding이 하나도 없으면 GREEN이 아니라 UNKNOWN입니다.

**선언된 커버리지만으로는 부족합니다.** `hazard_rules.yaml`의 `coverage`에 품목군이 적혀 있어도, 그 품목군에 `verified` 룰이 하나도 없으면 커버되지 않은 것으로 처리됩니다. 그래서 지금 상태(전부 draft)에서는 완구조차 UNKNOWN이 나옵니다. 의도된 동작입니다.

**워치리스트만 오류 비대칭이 반대입니다.** 스캔은 모르면 UNKNOWN으로 물러서지만, 리콜 알림은 놓치는 쪽이 훨씬 비쌉니다. 그래서 약한 매칭도 버리지 않고 `MatchStrength`(정확/유사/약한 일치)를 붙여 내보냅니다. 다만 3자 미만 모델명("A1")은 우연 충돌이 심해 아예 매칭하지 않습니다.

**UNKNOWN일 때 점수는 0으로 강제됩니다.** "모릅니다" 옆에 78점 같은 안심시키는 숫자를 띄우지 않기 위해서입니다.

현재 목 모드 동작:

```
[인증 조회됨]   → UNKNOWN  (규칙 DB 미검증 상태이므로 정직하게 모름)
[인증 미조회]   → RED
[리콜 일치]     → RED
[품목 미분류]   → UNKNOWN
```

## 다음에 할 일 (순서대로)

**1. 서비스키 발급 — 오늘 가능**
공공데이터포털 15116894에서 활용신청합니다. 개발단계는 자동승인이라 즉시 발급됩니다. 운영단계 전환 시에는 심의승인이 필요하니 데모 배포 전에 여유를 두세요.

**2. 인터페이스 설계서 확보**
이 데이터셋은 API 유형이 LINK라서 상세 규격이 safetykorea.kr의 Open API 설계서(HWP)에 있습니다. `https://www.safetykorea.kr/release/openapi`에서 받습니다.

**3. 스키마 탐침 후 매핑 확정**
```bash
python scripts/probe_kats_schema.py \
  --base-url <설계서의 호스트> --path <오퍼레이션 경로> \
  --key $KATS_SERVICE_KEY --extra type=json --extra numOfRows=3
```
출력된 후보를 설계서와 대조해 `kats_field_map.yaml`의 `TODO(unverified)`를 채우고 `verified: true`로 바꿉니다. **탐침의 매핑 제안은 이름 유사도일 뿐이니 그대로 믿지 마세요.**

**4. 규칙 DB 검수 — 여기가 진짜 작업**
`hazard_rules.yaml`의 두 draft 룰을 부속서 원문과 대조해 승격시킵니다. 이 단계가 끝나야 완구 품목이 GREEN/AMBER로 갈라지기 시작합니다. D4~D7 구간 전체를 여기에 쓸 각오를 하세요. 프로젝트의 유일한 진입장벽입니다.

**5. 크롬 확장**
`chrome.scripting.executeScript`로 `document.body.innerText`를 뽑아 `/api/v1/scan`에 POST합니다. 서버 크롤러는 만들지 않습니다.
