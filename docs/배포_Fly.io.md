# Fly.io 배포 절차

## ⚠⚠ 규칙 — 화면에 닿는 커밋은 **그날 배포한다**

2026-09-11 에 배포본이 **09-08 자**였다. 그 사이 고친 것이 배포되지 않아,
투표 링크가 가리키는 코드에 이것들이 **전부 없었다**:

    스캔 500 방지 (4-p)             정부 API 가 흔들리면 투표자가 에러 화면을 본다
    잘못된 초록불 방지 (4-q 결함 3)   전파인증 **점검 페이지**를 "확인됨" 으로 보여준다
    SQLite 손상 격리                 DB 가 깨지면 앱이 부팅조차 못 한다
    gov_lookup · results · watch_sweep · scan meta   관측이 전부 없다

**배포본이 전파인증 점검 페이지를 "확인됨" 으로 보여주는 코드였다.** 비대상
부착 0 을 지켜 온 제품에서 잘못된 초록불은 존재 이유를 뒤집는다.

그래서 규칙은 하나다:

> **셀러 화면의 판단을 바꾸는 커밋은 그날 배포한다.**
> 문서·측정 스크립트·검사만 바꾼 커밋은 모아서 배포해도 된다.

판단을 바꾸는 것의 예: `verifier`·`scorer`·`extractor`·어댑터·`models` 의
`FindingKind`·화면 문구. 확신이 안 서면 배포하는 쪽으로 판단한다.

### 배포 명령 — 커밋 해시를 반드시 박는다

```
fly deploy \
  --build-arg GIT_SHA=$(git rev-parse --short=9 HEAD) \
  --build-arg BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
```

⚠ 빌드 인자를 빼면 `/healthz.build.commit` 이 `null` 이고, 그러면 **필드 유무로
배포 버전을 역추적**하게 된다. 2026-09-11 에 실제로 그래야 했다.

### 배포 뒤 확인 넷

```
curl -s https://sourcing-guard.fly.dev/healthz | jq '.build, .kats, .storage, .extraction.order'
```

1. `build.commit` 이 **방금 푸시한 해시**인가
2. 실스캔 1건이 **200** 인가 · `meta.gov_lookup` 이 있는가
3. `storage.quarantined_from` 이 `null` 인가 (값이 있으면 워치 데이터를 잃었다)
4. `extraction.order` — `["gpt","claude"]` 는 **Claude 잔액 0 동안의 임시값**이다.
   충전되면 fly secret `EXTRACTOR_ORDER` 와 `.env` 를 **함께** 지운다 (R7).

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
- `/api/v1/scan` → 미조회 인증번호에 근거 링크 3건
  (당시 신호는 RED. `48e7787` 이후 미조회는 AMBER 다 — CLAUDE.md R3-b)
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

# 3) 배포 — **빌드 인자를 반드시 준다.** 안 주면 /healthz 의 build.commit 이
#    null 이 되고, 랜딩 5절의 커밋 표시가 "-" 가 된다.
fly deploy \
  --build-arg GIT_SHA=$(git rev-parse --short=9 HEAD) \
  --build-arg BUILT_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# 4) 확인
fly status
curl -s https://<앱이름>.fly.dev/healthz
```

⚠⚠ **2026-09-12 에 이 자리의 맨 `fly deploy` 때문에 두 번 배포했다.** 위 §정기
  배포에는 인자가 적혀 있었는데 이 설치 절에는 없어서, 기억으로 친 쪽이 인자
  없는 형태였다. `build.commit: null` 을 보고 다시 쳤다.

  **같은 명령을 두 곳에 적으면 한쪽이 낡는다** (§6). 여기를 고쳤지만, 다음에
  또 갈리면 `scripts/` 로 옮기는 것을 검토할 것.

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
fly secrets set ANTHROPIC_API_KEY=sk-...   # 추출기 1순위 (CLAUDE.md R7)
fly secrets set GPT_API_KEY=sk-...         # 추출기 2순위. 둘 다 죽으면 휴리스틱
fly secrets set GPT_MODEL=gpt-5.4-mini
fly secrets set MOCK_MODE=false
```

`fly secrets set` 은 자동으로 재배포한다.

⚠ **키를 커맨드라인에 두면 프로세스 목록과 셸 히스토리에 남는다.** 여러 개를
한 번에 넣을 때는 stdin 을 쓴다:

```bash
fly secrets import < secrets.env   # KEY=value 한 줄씩. 넣은 뒤 파일을 지운다
```

#### `EXTRACTOR_ORDER` — 장애 우회용 secret

코드 기본값은 `claude,gpt` 다 (`config.py`). **Claude 잔액이 0 인 동안만**
secret 으로 순서를 뒤집는다:

```bash
fly secrets set EXTRACTOR_ORDER=gpt,claude   # 잔액 0 인 동안만
fly secrets unset EXTRACTOR_ORDER            # 충전하면 지운다 → 기본값으로
```

지우지 않으면 GPT 가 영구 1순위가 되고 **발표 숫자의 기준 추출기가 조용히
바뀐다.** 지금 어느 경로로 도는지는 `/healthz` 의 `extraction` 에서 본다 —
응답 모양으로 추론하지 말 것 (2026-09-08 에 그 실수를 했다).

#### `DOMEGGOOK_API_KEY` — **아직 올리지 않는다**

도매꾹은 키 발급 시 **호출 IP 를 등록받는다.** 지금 등록된 것은 개발 PC 의
공인 IP 이고, Fly 의 나가는 IP 는 머신마다·재시작마다 달라진다. 그래서
배포본은 도매꾹을 부르지 않고, 호출은 `scripts/` 안에서만 한다
(`main.py` 는 `domeggook_client` 를 import 하지 않는다).

**고정 egress IP 를 확정한 뒤** secret 을 올린다:

```bash
fly ips allocate-egress -a sourcing-guard -r nrt   # IPv4+IPv6 한 쌍
fly ips list                                       # 할당 확인
```

Fly 공식 가격표 원문:

> Static Egress IPs: $0.005 per hour (~$3.60/month)
> When you allocate a static egress IP, you'll get both an IPv4 and IPv6
> address for this single price.

(참고: dedicated IPv4 는 "$2/mo". 출처 <https://fly.io/docs/about/pricing/>)

⚠ 할당한 IP 를 도매꾹에 **등록 신청**해야 한다. 복수 IP 등록이 되는지는
  미확인이다(참조.md §7) - 개발 PC IP 를 유지하면서 Fly IP 를 더할 수
  있는지 확인하고 나서 올린다.

⚠ `fly machine egress-ip` 는 deprecated 다. `fly ips allocate-egress`
  (앱 스코프)를 쓴다.

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
