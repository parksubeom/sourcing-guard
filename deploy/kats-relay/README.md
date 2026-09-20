# 국표원 조회 경유지 (`sgkatsrelay`)

## 왜 있나

**도쿄(nrt)에서만** `www.safetykorea.kr` 로 TCP 연결이 안 된다. 같은 이미지·같은
명령으로 fly 세 리전에서 쟀다 (각 2회 · 2026-09-20 14:06~14:08 UTC):

| 리전 | 스킴 | code | 응답 IP | connect | curl exit |
|---|---|---|---|---|---|
| sin | http | 404 | 152.99.46.37 | 1.247s | 0 |
| sin | https | 404 | 152.99.46.37 | 0.242s | 0 |
| nrt | http/https | 000 | — | — | 28 (타임아웃) |
| syd | http/https | 000 | — | — | 6 (호스트 이름 못 풂) |

404 는 파라미터 없는 경로라 정상이다 — 보는 것은 **연결됐는가**다.

⚠ syd 는 판별에서 뺀다. DNS 실패는 "국외라 막혔다" 가 아니라 다른 종류의
실패다. 잰 범위는 **fly 세 리전 · 각 2회 · 한 시점**이고, 결론은 "국외 전반"
이 아니라 **도쿄만**이다.

⚠⚠ **같은 날 두 번 쟀고 syd 가 갈렸다.** 커밋 `3a9767c` 의 회차(23:09 KST)는
`syd http=200 connect=2.022` 였고 위 회차(23:06~23:08 KST)는 DNS 실패였다.
어느 쪽도 지우지 않는다 — 한 시점씩 잰 것이다. sin 의 코드가 200 과 404 로
갈린 것은 경로가 다르기 때문이다(`/` 는 200 · `/openapi/api` 는 404).
**두 회차가 일치하는 것은 nrt** 이고, 이 경유지가 선 자리가 거기다.

## 왜 리전을 안 옮기고 경유지인가

볼륨은 리전을 못 넘는다. 옮기면 워치 항목과 투표자 지연을 건드린다. 경유지만
세워도 조회는 똑같이 산다 (총괄 판정 2026-09-20).

    본체     nrt 그대로     볼륨 · 워치 · 지연 안 건드림
    조회     sin 경유      `KATS_BASE_URL` secret 한 줄
    되돌리기  secret unset  매핑 기본값(safetykorea 직결)로 돌아간다

## 무엇을 하지 않나

- **저장하지 않는다** — 볼륨 없음, 캐시 없음
- **키를 갖지 않는다** — 헤더 `AuthKey` 를 그대로 넘길 뿐이다
- **접근 로그를 남기지 않는다** — `log { output discard }`
- **공개 IP 가 없다** — fly 사설망(6PN)에서 같은 조직만 닿는다
- **범용 프록시가 아니다** — `/openapi/api/*` 밖은 404

## 배포

```sh
cd deploy/kats-relay
fly apps create sgkatsrelay --org personal     # 처음 한 번
fly deploy
fly ips list -a sgkatsrelay                    # 비어 있어야 한다
```

본체에서 켜기:

```sh
fly secrets set KATS_BASE_URL="http://sgkatsrelay.internal:8080/openapi/api" -a sourcing-guard
```

끄기:

```sh
fly secrets unset KATS_BASE_URL -a sourcing-guard
```

⚠ 호스트를 바꾸면 `CLAUDE.md` R4 표와 `sourcing_guard/allowed_hosts.py` 를
**표부터** 고친다. 어긋나면 `tests/test_allowed_hosts.py` 가 깨진다.
