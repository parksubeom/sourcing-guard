# Fly.io 배포 절차

## ✅ 배포 완료 (2026-08-31)

**https://sourcing-guard.fly.dev** — 목 모드로 가동 중. 9/2 목표 이틀 앞당김.

| 항목 | 값 |
|---|---|
| 앱 | `sourcing-guard` (org: personal) |
| 리전 | `nrt` (도쿄) |
| 머신 | `185175db33d968`, 헬스체크 1/1 passing |
| 볼륨 | `sg_data` 3GB (`vol_vwnxgn7l9dkgxymv`) |
| 이미지 | 54MB |
| IP | shared ipv4 `66.241.124.15` / dedicated ipv6 |

검증한 것:
- `/healthz` 200, 0.2초
- `/api/v1/scan` → 미조회 인증번호에 RED + 근거 링크 3건
- `/api/v1/watch` 등록 → **머신 재시작 후에도 유지**(볼륨 영속성 실증)

**아직 안 한 것**: 인증키 미수령이라 실연동 검증 불가. IP 등록도 대기.

---

**목표: 목 모드 그대로 공개 URL 확보** (기획서 §10, 9/2 마감)

인증키가 없어도 배포한다. `MOCK_MODE=true` 로 전 파이프라인이 돌고,
키가 오면 `fly secrets set` 한 줄로 실연동으로 바뀐다.
마지막 날 배포는 해커톤 실패의 전형이라 순서를 뒤집지 않는다.

---

## 사전 준비 (사람이 해야 함)

1. https://fly.io 가입 + 결제 수단 등록
   무료 티어로는 안 된다 — 슬립이 있으면 투표 기간 18일 무중단이 깨진다.
   전용 IPv4 $2 + shared-cpu-1x 512MB, 월 $5~7 수준.
2. flyctl 설치
   ```powershell
   powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
   ```
3. `fly auth login`

---

## 배포

```bash
# 1) 앱 생성. 배포는 아직 하지 않는다.
fly launch --no-deploy --name sourcing-guard --region nrt
#    → fly.toml 의 app 이름이 실제 생성된 이름과 다르면 맞춘다.
#    → 이미 fly.toml 이 있으므로 덮어쓰겠냐고 물으면 "아니오".

# 2) 볼륨 생성. 워치리스트 + 리콜 동기화 DB 양쪽이 들어간다.
fly volumes create sg_data --region nrt --size 3

# 3) 배포
fly deploy

# 4) 확인
fly status
curl -s https://<앱이름>.fly.dev/healthz
```

`/healthz` 가 이렇게 나오면 성공이다.

```json
{"ok":true,"mock_mode":true,"active_rules":0,"draft_rules":2,"watched_items":0}
```

`active_rules: 0` 은 정상이다. 규칙 DB 가 전부 draft 라서 그렇고,
그래서 지금은 완구도 UNKNOWN 이 나온다 (의도된 동작).

---

## 시크릿 (인증키 도착 후)

이미지나 저장소에 키를 넣지 않는다. `fly secrets` 만 쓴다.

```bash
fly secrets set KATS_SERVICE_KEY=xxxxx     # 이것만으로 실연동 시작
fly secrets set ANTHROPIC_API_KEY=sk-...   # Extractor 실제 구동
fly secrets set MOCK_MODE=false
```

`fly secrets set` 은 자동으로 재배포한다.

**IP 등록**: SafetyKorea 는 등록된 IP 에서만 응답한다(결과코드 4001).
Fly 의 나가는 IP 를 확인해 제품안전정보센터에 등록 신청한다.

```bash
fly ips list          # 인바운드
fly machine list      # 머신 확인
```

egress IP 가 필요하면 전용 IPv4 를 할당한다.

```bash
fly ips allocate-v4
```

D(로컬 동기화)로 가면 **서빙 시점의 IP 의존은 없어진다.** 동기화 잡만
등록된 IP 에서 돌리면 되고, 공개 트래픽은 로컬 DB 만 읽는다.
다만 인증키 의존은 그대로 남는다.

---

## 설정에서 결정한 것과 이유

| 항목 | 값 | 이유 |
|---|---|---|
| `auto_stop_machines` | **false** | 슬립되면 깨어나는 데 30초~1분. 투표자는 그냥 닫는다 (기획서 §8: 3초 이내) |
| `min_machines_running` | 1 | 항상 1대는 떠 있어야 무중단 |
| 볼륨 크기 | 3GB | 워치리스트 + 리콜 동기화 DB 양쪽. 리콜 전량은 수십 MB 수준이라 여유 있음 |
| 헬스체크 | `/healthz` | 이 응답은 `watched_items` 를 세느라 SQLite 를 실제로 읽는다. **볼륨이 안 붙으면 헬스체크가 실패한다** — 배포 사고를 조용히 넘기지 않는다 |
| 워커 | 1개 | SQLite 를 여러 프로세스가 쓰면 잠금 경합. 늘려야 하면 Postgres 로 먼저 옮긴다 |
| 리전 | `nrt`(도쿄) | 한국에서 가장 가깝다. `icn`(서울)은 지역에 따라 미제공일 수 있어 실패 시 nrt |
| 메모리 | 512MB | FastAPI + SQLite 에 충분. anthropic SDK 포함해도 여유 |
| 이미지 유저 | 비루트(uid 1000) | `/data` 소유권을 넘겨야 SQLite 쓰기가 된다 |

---

## 주의

**`WATCHLIST_DB_PATH` 는 반드시 `/data` 아래여야 한다.** 컨테이너 기본
파일시스템에 두면 재배포마다 워치리스트가 사라진다. 그러면 셀러는 감시받고
있다고 믿는 채로 감시되지 않고, 이미 알린 리콜을 매일 다시 통보받는다.
이 서비스가 유일하게 보증하는 것이 알림이라 조용히 깨지면 안 된다 (기획서 §6.1).

`fly.toml` 의 `[env]` 에 이미 박아뒀으니 건드리지 말 것.

---

## 배포 후

- `fly logs` 로 기동 확인
- 9/20~10/7 무중단이 요구조건이므로 헬스체크 알림을 걸어둔다
- 화면에 캐시 기준일을 표시한다 (D 작업 이후)
