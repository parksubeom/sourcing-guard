# 새 PC 로 옮길 때 가져갈 것 — 2026-09-03 작성 · **2026-09-12 갱신**

이 저장소를 다른 PC(회사 등)에서 이어서 작업할 때, **git 에 없어서 손으로
옮겨야 하는 것**만 모았다. 실제로 `git status --ignored` 와
`git apply --check` 로 훑어 확인한 목록이고, 여기 없는 것은 전부 클론으로
따라온다.

⚠ **2026-09-12 에 실제로 한 번 이전했고, 그때 걸린 것을 §5 에 적었다.** 문서가
  예상한 것과 실제로 걸린 것이 달랐다 - §5 를 먼저 읽는 편이 빠르다.

---

## 0. 30초 요약

| # | 무엇 | 크기 | 안 가져가면 |
|---|---|---|---|
| 1 | `.env` 의 **비밀값 5개** | 텍스트 | 목 모드로만 돈다. 실제 인증 조회·리콜 조회·LLM 추출이 안 된다 |
| 2 | `data/watchlist.db` | 33,419,264 바이트 (33.4MB) | 리콜 대조가 0건이 된다. 다시 만들 수는 있으나 **아래 §2-2 의 이유로 권하지 않는다** |
| 3 | **Fly 재로그인** (파일 복사 아님) | — | 배포를 못 한다 |

**아무것도 안 가져가도 `pytest -q` 는 통과한다** (2026-09-12 기준 **1,386 passed**).
목 모드가 기본값이라 키 없이 전 파이프라인이 돈다. 코드만 볼 거라면 §1 만 하면 된다.

⚠ **윈도우에서 작업한다면 §0-C 를 먼저 본다.** 2026-09-12 이전에서 실제로
  걸린 것이 전부 거기 있다.

---

## 0-B. ⚠ 이미 클론이 있다면 — 2026-09-09 rewrite 때문에 pull 이 깨진다

**새로 클론하는 경우는 이 절을 건너뛴다.** 2026-09-09 이전에 클론해 둔 사본이
있으면 다음 `git pull` 이 실패한다.

그날 author·committer 이메일만 바꾸는 히스토리 rewrite 를 했고 **커밋 해시가
전부 바뀌었다.** 파일 내용은 한 글자도 안 바뀌었다(트리 해시 동일).

⚠⚠ **2026-09-12 이전에서 실제로 이랬다.** 로컬이 **rewrite 전 09-04 커밋**에 서 있었고
`origin/main` 과 **공통 조상이 아예 없었다**(disjoint history · 서로 다른 루트).
`git status` 는 `ahead 111, behind 208` 로 보였지만 그중 "ahead 111" 은 앞서
있다는 뜻이 아니라 **히스토리가 갈라져 있다는 뜻**이다.

```bash
git fetch --all --prune
# 버리기 전에 반드시 확인 — 로컬 작업이 정말 원격에 있는가
git merge-base --is-ancestor HEAD origin/backup/pre-rewrite-2026-09-09 && echo "로컬 작업 보존됨"
git rev-list --left-right --count HEAD...origin/backup/pre-rewrite-2026-09-09   # 왼쪽이 0 이어야 안전
git status --porcelain -uall     # 비어 있어야 안전
git stash list

git reset --hard origin/main
```

⚠ `git reset --hard` 는 **커밋하지 않은 변경을 버린다.** 위 세 줄로 먼저 확인한다.
왼쪽 수가 0 이 아니면 로컬에만 있는 커밋이 있다는 뜻이니 `cherry-pick` 으로
새 `main` 위에 다시 얹는다.

⚠ `git pull` 을 먼저 시도하면 "divergent branches" 로 멈추거나 옛 히스토리와
새 히스토리가 **양쪽 다 들어간 머지 커밋**이 생긴다 - `pull` 이 아니라 `reset --hard` 다.

옛 해시를 되짚어야 하면 `docs/해시_대응표_rewrite_2026-09-09.md` 와
원격 `backup/pre-rewrite-2026-09-09`(태그 `pre-rewrite-2026-09-09`)를 본다
(**영구 보존 ref** · CLAUDE.md §6).

---

## 0-C. ⚠ 윈도우에서 작업한다면 — 2026-09-12 신설

개발 PC 는 Windows 10 · Python 3.12.10 이다. 아래는 **클론 직후 한 번씩** 한다.

```bash
git config core.autocrlf false     # ⚠ 기본값 true 면 줄끝이 CRLF 로 바뀐다
git config core.longpaths true     # 한글 경로 + 깊은 tests/fixtures 에서 걸린다
```

⚠ **`core.autocrlf` 는 이 저장소에서 특히 위험하다.** 소스 텍스트를 그대로 읽어
검사하는 것이 여럿이다(`tests/srccheck.py`·`test_finding_kind_tables.py`·
화면 중복 검사). 줄끝이 바뀌면 **코드는 멀쩡한데 검사만 깨져** 원인을 엉뚱한
곳에서 찾게 된다.

**콘솔 인코딩** — 파이썬을 부를 때 UTF-8 을 강제한다.

```bash
PYTHONUTF8=1 python -m pytest -q
```

안 하면 한글 출력이 깨진 문자로 나온다. 실패 메시지가 한글이라 **무엇이 틀렸는지
못 읽는다.** 영구로 두려면 사용자 환경변수에 `PYTHONUTF8=1`.

**셸** — `fly deploy` 와 `docs/배포_Fly.io.md` 의 명령은 **Git for Windows 의
Git Bash** 에서 그대로 돈다(`$(...)`·`date -u`). PowerShell 을 쓸 거면 §2-3 의
PowerShell 판을 쓴다. PowerShell 5.1 에는 `&&`·`||` 가 없다.

**커밋 이메일** — `user.email` 은 GitHub noreply 여야 한다. 2026-09-09 rewrite 가
바로 이것 때문이었다. 다시 실수하면 히스토리를 또 갈아야 한다.

```bash
git config user.email "104641096+parksubeom@users.noreply.github.com"
```

**구현 에이전트 모델은 Opus 5 다.** 2026-09-11 에 Fable 5.1 로 바꿨다가 안전
분류기 오탐으로 되돌렸다(작업로그 2026-09-12 §0). 경계 시험·개인정보 마스킹·
호스트 게이트 작업이 그 분류기가 보는 모양과 겹친다. **제출(9/20) 뒤에 다시 본다.**

---

## 1. 저장소만으로 되는 것

```bash
git clone https://github.com/parksubeom/sourcing-guard.git
cd sourcing-guard
python -m venv .venv
source .venv/Scripts/activate      # PowerShell 이면 .venv\Scripts\activate
pip install -r requirements.txt
PYTHONUTF8=1 pytest -q             # 1,386 passed 나오면 정상
```

- **Python 3.11 이상 필수.** 런타임에 평가되는 `X | None` 표기를 써서 3.10
  이하는 import 부터 실패한다. 개발 PC 는 **3.12.10**.
- `.env` 는 없어도 된다. `MOCK_MODE` 기본값이 true 다.
- 프론트는 빌드 단계가 없다. `uvicorn sourcing_guard.main:app --reload` 로
  띄우면 바로 화면이 나온다.

> **주의 — 목 모드에서 데모 3종은 전부 회색불(UNKNOWN)이다.** 목
> `KatsClient` 가 아는 인증번호가 데모가 쓰는 번호와 다르다. 신호등이
> 초록·빨강으로 갈리는 건 실연동(§2-1)에서만이다. 목 모드 회색불은 고장이 아니다.

---

## 2. 가져가야 할 것

### 2-1. `.env` — 키 12개 중 **비밀 5개**

`.env.example` 은 **커밋돼 있다.** 뼈대와 주석은 클론으로 따라오니, 그것을
`.env` 로 복사한 뒤 비밀 5개를 채우면 된다.

| 키 | 길이(개발 PC) | 없으면 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 108자 | Claude 경로가 빠진다 |
| `GPT_API_KEY` | — | **기준 추출기가 빠진다** (아래 ⚠⚠) |
| `KATS_SERVICE_KEY` | 36자 | KC 인증 조회·리콜 동기화가 안 된다 |
| `SYNC_TOKEN` | 32자 | `POST /api/v1/sync` 수동 트리거가 403 |
| `DOMEGGOOK_API_KEY` | — | 표본 수집 스크립트가 안 돈다. **배포본은 안 쓴다** |

⚠⚠ **기준 추출기는 GPT 다 (2026-09-11 · R7 개정).** 기본 순서가 `gpt,claude` 이고
**발표 숫자도 GPT 기준**이다. `GPT_API_KEY` 가 없으면 로컬이 Claude 로 돌아
**기획서·랜딩 ④ 의 숫자를 로컬에서 재현할 수 없다.** Claude 원자료는 대조군으로
남겨 두되 지우지 않는다.

⚠ `EXTRACTOR_ORDER` 는 **비워 두는 것이 정상**이다(기본 `gpt,claude`). 순서를
바꿔 시험할 때만 채우고, 그때 재는 숫자는 어느 추출기 것인지 함께 적는다.

⚠ `DOMEGGOOK_API_KEY` 는 **호출 IP 가 등록된 키**다. PC 를 옮기면 공인 IP 가
바뀌어 401/403 이 난다 - **도매꾹에 새 IP 등록을 먼저 신청해야 한다.** 쿼터는
분당 180회 · 하루 15,000회. 도매꾹 호출은 `scripts/` 안에서만 한다.

비밀이 아닌 나머지 7개는 값을 그대로 적어둔다 — 개발 PC 기준:

```
MOCK_MODE=false
EXTRACTOR_MODEL=claude-sonnet-5
GPT_MODEL=gpt-5.4-mini
EXTRACTOR_ORDER=            (빈 값이 정상. 기본 gpt,claude)
KATS_BASE_URL=              (빈 값이 정상. 시험용 오버라이드 전용)
WATCHLIST_DB_PATH=data/watchlist.db
SYNC_ENABLED=true
```

**SafetyKorea 는 IP 등록이 필요 없다.** 인증키 회신에 **"IP 제한은 없습니다"** 가
명시됐다 (`00_프로젝트_핸드오프.md` §7). 회사 IP 에서도 실연동이 된다.
**IP 를 등록해야 하는 것은 도매꾹뿐이다.**

**옮기는 방법**: USB 나 비밀번호 관리자를 쓸 것. 메신저·이메일로 보내면 키가
그쪽 서버에 남는다 (CLAUDE.md §6).

### 2-2. `data/watchlist.db`

2026-09-12 개발 PC 실측:

```
recalls            37,329      국내 4,244 + 국외 33,085
rf_noncompliant     2,749      부적합 방송통신기자재
watch_items             0
sync_state              4      initial_load_at / last_sync_at 등
```

`.gitignore` 의 `/data/` 로 빠져 있다. 파일 하나만 통째로 복사하면 된다.

**다시 만들 수 있는데도 복사를 권하는 이유**: 초기 전량 적재가
`conditionValue=%` 와일드카드 조회인데, 이건 **설계서에 명시된 사용법이
아니다.** 신청서 안내문에 *"개발 명세서 포맷을 어길 시 별도 통보 없이 인증이
취소될 수 있다"* 고 되어 있어서, **초기 적재 1회에만 쓰고 반복 호출에는
쓰지 않기로** 정해둔 호출이다. 새 PC 에서 또 돌리면 그 1회를 한 번 더 쓰는 셈이다.

복사한 뒤 일일 증분 동기화(월 단위 접두 조회)는 그대로 이어진다.

### 2-3. Fly 로그인 — 파일을 복사하지 말고 다시 로그인할 것

토큰이 `~/.fly/config.yml` 에 있어 PC 를 넘어가지 않는다. 그 파일에는
`access_token`·`metrics_token`·`wire_guard_state` 가 들어 있으므로 **복사해서
옮기지 말고** 새 PC 에서 다시 로그인한다.

```powershell
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
fly auth login
fly status --app sourcing-guard
```

**배포에는 `.env` 가 필요 없다.** 앱 시크릿은 이미 Fly 서버에 올라가 있다.
`.env` 는 로컬 실행 전용이다.

**배포 명령** (절차 전문은 `docs/배포_Fly.io.md`). Git Bash 에서는 그 문서의
명령을 그대로 쓴다. PowerShell 이면:

```powershell
fly deploy `
  --build-arg GIT_SHA=$(git rev-parse --short=9 HEAD) `
  --build-arg BUILT_AT=$([DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"))
```

⚠ PowerShell 에는 `date -u` 가 없다. 위 `[DateTime]::UtcNow` 판은 2026-09-12 에
실제로 돌려 확인했다(`2026-09-12T05:34:40Z`).

⚠ `fly deploy` 는 **foreground 로** 돌린다. 배경으로 띄우면 세션이 끝날 때 빌드가
죽고, 그 사이 배포본이 옛 코드로 남는다 (2026-09-12 작업로그 §2 회귀).

---

## 3. 안 가져가도 되는 것

| 무엇 | 왜 |
|---|---|
| `.venv/` · `__pycache__/` · `.pytest_cache/` | 재생성된다. 오히려 옮기면 경로가 깨진다 |
| 조사용 HTML 덤프 | 재현 명령이 `docs/공개API_조사_2026-09-02.md` §4 에 있다 |
| HS부호 XLSX (11,327건) | 같은 문서 §1 에 로그인 없이 받는 2단계 경로가 있다 |
| 관세청 세관장확인 인증키 | 1회성이고 `.env` 에도 없다. 필요하면 data.go.kr 에서 재발급 |
| 어린이제품 공통안전기준 PDF·리콜 TSV 덤프 | `docs/` 에 커밋돼 있다 |

---

## 4. 옮긴 뒤 확인 — 이 순서로 하면 뭐가 빠졌는지 바로 드러난다

```bash
PYTHONUTF8=1 pytest -q
# -> 1386 passed.  실패하면 코드가 아니라 Python 버전(3.11+)과 §0-C 를 먼저 볼 것

python -c "import sqlite3;print(sqlite3.connect('data/watchlist.db').execute('select count(*) from recalls').fetchone())"
# -> (37329,).  0 이나 파일 없음이면 2-2 를 안 옮긴 것

uvicorn sourcing_guard.main:app --reload
curl http://127.0.0.1:8000/healthz
```

`/healthz` 기대값 (2026-09-12 개발 PC 실측):

| 필드 | 기대값 | 어긋나면 |
|---|---|---|
| `mock_mode` | `false` | `.env` 의 `MOCK_MODE` 또는 키를 안 옮긴 것 |
| `active_rules` | `21` | 규칙 DB 승격 상태가 다르다 |
| `sync.recalls` | 국내 `4244` · 국외 `33085` | 2-2 를 안 옮겼거나 동기화가 더 돌았다 |
| `sync.rf_noncompliant.count` | `2749` | 위와 같다 |
| `extraction.order` | `['gpt','claude']` | R7 개정 전 상태다 |
| `extraction.gpt_key` | `true` | **`GPT_API_KEY` 를 안 옮긴 것** (§2-1 ⚠⚠) |
| `storage.quarantined_from` | `null` | 값이 있으면 **워치 데이터를 잃었다** |

```bash
fly status --app sourcing-guard
# -> 로그인 안 됐으면 여기서 걸린다
```

---

## 5. 이번 이전에서 실제로 걸린 것 — 2026-09-12 실측

문서가 예상한 것(키·DB·Fly 로그인)은 **하나도 안 걸렸다.** 걸린 것은 전부
**윈도우에서 처음 드러난 코드 결함** 둘이었다.

| # | 증상 | 원인 | 결과 |
|---|---|---|---|
| 1 | `test_outage_resilience` **2건 실패** | 손상 DB 격리가 커넥션을 연 채로 rename → `PermissionError WinError 32` | **수정** `65c5988`. `_open()` 이 실패 시 스스로 닫는다 |
| 2 | `test_report_miss` **2건 플래키**(8회 중 6회 실패) | 공유 커넥션에 락이 없어 `with self._conn:` 이 겹침 | **수정** `dcafe9b`. `RLock` |

⚠ **1 번은 윈도우에서만 보인다.** POSIX 는 열린 파일의 rename 이 되므로 리눅스
배포본은 영향이 없었다. 원래 검사가 "격리가 됐는가" 만 봐서 이 경로가 비어
있었다 - 지금은 **"실패한 `_open` 이 커넥션을 남기지 않는다"** 는 불변식으로
바꿔 양쪽 OS 에서 돈다.

⚠⚠ **2 번은 윈도우 전용이 아니었다.** 리눅스에서도 난다. 그리고 **오류보다
무음 손실이 많았다** - 8스레드 × 200 쓰기에서:

```
리눅스 c80b03c   저장 1,047 · 오류 152 · 무음 손실 약 400
윈도우 65c5988   저장   214 · 오류   7 · 무음 손실 1,386
RLock 적용 후    저장 1,600 · 오류   0
```

예외 수만 세는 검사였다면 못 잡았다. **검사의 기대값을 건수로 쓴 이유가 이것이다.**

**두 수정 뒤 `1,386 passed` 연속 2회** (4:35 · 5:00), `test_report_miss.py` 단독
연속 10회 전부 초록. 그 파일은 손대지 않았다(타임아웃 조정·flaky 마킹 없음).

검사 수 이력: 09-04 로컬 트리 **1,380**(1,378 passed + 격리 2 failed)
→ 격리 검사 +3, 동시성 검사 +3 → **1,386**.

---

## 6. 이어서 할 일

`docs/미완_목록.md` 와 `docs/인수인계_2026-09-11.md` §2 큐가 정본이다.
옮긴 직후에 걸리는 것만 추리면:

1. **`GPT_API_KEY` 확보** — 없으면 발표 숫자를 로컬에서 재현할 수 없다 (§2-1)
2. **도매꾹 IP 재등록** — `[M]`·`[M-5]` 표본 수집이 그 전엔 안 돈다
3. **부속서 1·6·11 원문 수록** — 사용자 수령 대기. 회색불을 깨는 유일한 길

---

## 7. 이 목록을 다시 만드는 법

이 문서가 낡았다고 의심되면 개발 PC 에서:

```bash
git status --ignored --short | grep '^!!'    # git 밖에 있는 것 전부
git status --short                            # 미추적 파일
PYTHONUTF8=1 pytest -q | tail -1              # 검사 수
python -c "import pathlib;ks=[l.split('=',1)[0] for l in pathlib.Path('.env.example').read_text(encoding='utf-8').splitlines() if l.strip() and not l.startswith('#') and '=' in l];s=[k for k in ks if any(x in k.upper() for x in ('KEY','TOKEN','SECRET'))];print(f'키 {len(ks)}개 · 비밀 {len(s)}개 -> {s}')"
```
