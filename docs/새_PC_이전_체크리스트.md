# 새 PC 로 옮길 때 가져갈 것 — 2026-09-03

이 저장소를 다른 PC(회사 등)에서 이어서 작업할 때, **git 에 없어서 손으로
옮겨야 하는 것**만 모았다. 실제로 `git status --ignored` 와
`git apply --check` 로 훑어 확인한 목록이고, 여기 없는 것은 전부 클론으로
따라온다.

---

## 0. 30초 요약

| # | 무엇 | 크기 | 안 가져가면 |
|---|---|---|---|
| 1 | `.env` 의 **비밀값 3개** | 텍스트 | 목 모드로만 돈다. 실제 인증 조회·리콜 조회·LLM 추출이 안 된다 |
| 2 | `data/watchlist.db` | 33,370,112 바이트 (33.4MB) | 리콜 대조가 0건이 된다. 다시 만들 수는 있으나 **아래 §2 의 이유로 권하지 않는다** |
| 3 | **Fly 재로그인** (파일 복사 아님) | — | 배포를 못 한다 |

**아무것도 안 가져가도 `pytest -q` 는 577 passed 로 통과한다.** 목 모드가
기본값이라 키 없이 전 파이프라인이 돈다. 코드만 볼 거라면 §1 만 하면 된다.

---

## 1. 저장소만으로 되는 것

```powershell
git clone https://github.com/parksubeom/sourcing-guard.git
cd sourcing-guard
python -m venv .venv
.venv\Scripts\activate          # Python 3.11+ 필수 (개발 PC 는 3.12.10)
pip install -r requirements.txt
pytest -q                        # 577 passed 나오면 정상
```

- **Python 3.11 이상 필수.** 런타임에 평가되는 `X | None` 표기를 써서 3.10
  이하는 import 부터 실패한다.
- `.env` 는 없어도 된다. `MOCK_MODE` 기본값이 true 다.
- 프론트는 빌드 단계가 없다. `uvicorn sourcing_guard.main:app --reload` 로
  띄우면 바로 화면이 나온다.

> **주의 — 목 모드에서 데모 3종은 전부 회색불(UNKNOWN)이다.** 목
> `KatsClient` 가 아는 인증번호는 `JU071047-12002C`·`CB123A123-1234`·
> `XU07012345` 셋뿐이고 데모가 쓰는 `CB061R2170-3018`·`CB067R317-5002` 는
> 거기 없다. 신호등이 초록·빨강으로 갈리는 건 실연동(§2-1)에서만이다.
> 목 모드에서 회색불이 나오는 것은 고장이 아니다.

---

## 2. 가져가야 할 것

### 2-1. `.env` 의 비밀값 3개

`.env.example` 은 **커밋돼 있다.** 뼈대와 주석은 클론으로 따라오니, 그것을
`.env` 로 복사한 뒤 값 3개만 채우면 된다.

| 키 | 값 | 없으면 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 108자 | LLM 추출이 휴리스틱으로 대체된다 (동작은 하되 정확도가 떨어진다) |
| `KATS_SERVICE_KEY` | 36자 | KC 인증 조회·리콜 동기화가 안 된다 |
| `SYNC_TOKEN` | 32자 | `POST /api/v1/sync` 수동 트리거가 403 |

비밀이 아닌 나머지는 값을 그대로 적어둔다 — 개발 PC 기준:

```
MOCK_MODE=false
EXTRACTOR_MODEL=claude-sonnet-5
KATS_BASE_URL=            (빈 값으로 두는 게 정상. 시험용 오버라이드 전용)
WATCHLIST_DB_PATH=data/watchlist.db
SYNC_ENABLED=true
```

**IP 등록은 신경 쓰지 않아도 된다.** SafetyKorea 는 원래 서비스 ID 가 등록
IP 에 묶여 미등록 IP 에서 `4001 Invalid IP` 가 나는데, 인증키 회신에
**"IP 제한은 없습니다"** 가 명시됐다 (`00_프로젝트_핸드오프.md` §7). 회사
IP 에서도 실연동이 된다.

**옮기는 방법**: USB 나 비밀번호 관리자를 쓸 것. 메신저·이메일로 보내면 키가
그쪽 서버에 남는다 (CLAUDE.md §6).

### 2-2. `data/watchlist.db`

```
recalls            37,313      국내 4,243 + 국외 33,070
rf_noncompliant     2,749      부적합 방송통신기자재
watch_items             0
sync_state              4      initial_load_at / last_sync_at 등
```

`.gitignore` 의 `/data/` 로 빠져 있다. 파일 하나만 통째로 복사하면 된다.

**다시 만들 수 있는데도 복사를 권하는 이유**: 초기 전량 적재가
`conditionValue=%` 와일드카드 조회인데, 이건 **설계서에 명시된 사용법이
아니다.** 신청서 안내문에 *"개발 명세서 포맷을 어길 시 별도 통보 없이 인증이
취소될 수 있다"* 고 되어 있어서, **초기 적재 1회에만 쓰고 반복 호출에는
쓰지 않기로** 정해둔 호출이다 (`00_프로젝트_핸드오프.md` §7). 새 PC 에서 또
돌리면 그 1회를 한 번 더 쓰는 셈이다.

복사한 뒤 일일 증분 동기화(월 단위 접두 조회)는 그대로 이어진다.

### 2-3. Fly 로그인 — 파일을 복사하지 말고 다시 로그인할 것

토큰이 `~/.fly/config.yml` 에 있어 PC 를 넘어가지 않는다. 그 파일에는
`access_token`·`metrics_token`·`wire_guard_state` 가 들어 있으므로 **복사해서
옮기지 말고** 새 PC 에서 다시 로그인한다.

```powershell
# flyctl 설치 (Windows)
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
fly auth login
fly status --app sourcing-guard
```

**배포에는 `.env` 가 필요 없다.** 앱 시크릿은 이미 Fly 서버에 올라가 있다
(`fly secrets list --app sourcing-guard` → `KATS_SERVICE_KEY` ·`SYNC_TOKEN` ·
`ANTHROPIC_API_KEY` ·`EXTRACTOR_MODEL` 모두 `Deployed`). `.env` 는 로컬 실행
전용이다.

배포 절차는 `docs/배포_Fly.io.md`.

---

## 3. 안 가져가도 되는 것

| 무엇 | 왜 |
|---|---|
| `.venv/` · `__pycache__/` · `.pytest_cache/` | 재생성된다. 오히려 옮기면 경로가 깨진다 |
| `~/Downloads/sourcing-guard-*.patch` | **`sourcing-guard-readme.patch` 하나만 빼고 전부 적용 완료** (`git apply --check` 로 확인). 그 하나는 §4 참조 |
| 조사용 HTML 덤프 (스크래치패드 17개) | 재현 명령이 `docs/공개API_조사_2026-09-02.md` §4 에 있다 |
| HS부호 XLSX (11,327건) | 같은 문서 §1 에 로그인 없이 받는 2단계 경로가 있다 |
| 관세청 세관장확인 인증키 | 1회성으로 받은 것이고 `.env` 에도 넣지 않았다. 필요하면 data.go.kr 에서 재발급 (자동승인) |
| 어린이제품 공통안전기준 PDF·리콜 TSV 덤프 | `docs/` 에 커밋돼 있다 |

---

## 4. 옮긴 뒤 확인 — 이 순서로 하면 뭐가 빠졌는지 바로 드러난다

```powershell
pytest -q
# -> 577 passed.  실패하면 코드가 아니라 Python 버전(3.11+)을 먼저 볼 것

python -c "import sqlite3;print(sqlite3.connect('data/watchlist.db').execute('select count(*) from recalls').fetchone())"
# -> (37313,).  0 이나 파일 없음이면 2-2 를 안 옮긴 것

uvicorn sourcing_guard.main:app --reload
curl http://127.0.0.1:8000/healthz
# -> mock_mode:false / active_rules:17 / recalls 4243·33070 / rf_noncompliant 2748~2749
#    mock_mode:true 로 나오면 .env 의 MOCK_MODE 또는 키 3개를 안 옮긴 것

fly status --app sourcing-guard
# -> 로그인 안 됐으면 여기서 걸린다
```

---

## 5. 이어서 할 일 (2026-09-03 기준)

자세한 것은 `docs/작업로그_2026-09-03.md`. 옮긴 직후에 걸리는 것만 추리면:

1. **배포** — 프로덕션이 9/2 빌드다. 오늘 코드 2건(`edbafdd` 사유별 UNKNOWN
   헤드라인, `7bacf68` 부속서 단서 문구)이 안 올라가 있다.
2. **`sourcing-guard-readme.patch` 적용** — `~/Downloads` 에 있고 미적용이다.
   9/1 작성이라 두 곳이 낡았으니 그대로 넣지 말 것: `479 passed` (지금 577),
   그리고 전파인증 축(9/2 추가)이 빠져 있다.
3. **부속서 1·6·11 원문 수록** — 사용자 수령 대기. 이게 유일한 병목이다.

---

## 6. 이 목록을 다시 만드는 법

이 문서가 낡았다고 의심되면 개발 PC 에서:

```bash
git status --ignored --short | grep '^!!'    # git 밖에 있는 것 전부
git status --short                            # 미추적 파일
for f in ~/Downloads/sourcing-guard-*.patch; do
  git apply --check --reverse "$f" 2>/dev/null && echo "적용됨 $f" \
    || { git apply --check "$f" 2>/dev/null && echo "미적용 $f" || echo "부분/변형 $f"; }
done
```

`부분/변형` 은 적용된 뒤 그 파일이 더 수정됐다는 뜻이라 정상이다.
`미적용` 만 확인하면 된다.
