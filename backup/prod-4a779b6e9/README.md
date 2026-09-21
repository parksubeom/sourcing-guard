# 프로덕션 `4a779b6e9` 자산 사본 — **영구 보존. 지우지 마라**

2026-09-21 에 라이브(`https://sourcing-guard.fly.dev`)에서 **그대로** 받았다.

## 왜 있나

프로덕션 `4a779b6e9` 의 **커밋이 저장소 어디에도 없다.** 윈도우 PC 에서 푸시
없이 배포됐고 그 트리를 아직 못 찾았다. 새로 배포하면 **거기로 못 돌아간다** —
이 폴더가 그때의 유일한 사본이다.

    프로덕션   4a779b6e9 · 2026-09-20T23:37:54Z 빌드
    origin/main 이 사본을 만들 때 352da25
    git cat-file -t 4a779b6e9  →  **없음**

## 무엇이 들어 있나 — 17개

    pages/            HTML 8장 (랜딩·scan·batch·watch·guide·samples·misses·unknown)
    static/           참조된 자산 9개 (app.css · mascot.svg · favicon.svg ·
                      owner.js · guide.js · samples.js · misses.js · unknown.js ·
                      data/안전성조사_보도자료.json)
    healthz.json      받을 때의 /healthz 전문

목록은 HTML 8장을 훑어 `/static/...` 참조를 전부 모은 것이고, 받기 전에
`assert len(...) == 17` 로 세었다 (§6).

⚠ `/static/og.png` 는 **없다.** 저장소(63e090f)에만 있고 프로덕션에 배포된
  적이 없다 — 라이브는 404 다.

## ⚠⚠ 이것은 소스가 아니다 — **서버가 런타임에 넣은 것이 섞여 있다**

`pages/` 의 HTML 을 그대로 소스로 되돌리면 안 된다:

    ?v=4a779b6e9                                    `_page()` 가 박은 캐시버스터
    <span class="asof" title=…>2026-09-17 기준</span>  `_fill_as_of` 가 채운 것
                                                     소스는 `<span class="asof" data-asof></span>`
    주석 제거                                         `srccheck.markup_only` 가 지운 것

그리고 `<title>` 은 **저장소 쪽이 새것**이다 (63e090f — `/scan` 이
`상품 검사 · 안심 소싱 돋보기`). 여기 것으로 덮으면 되돌아간다.

## 잃은 것 — 여기서 복원되지 않는다

라이브에서 못 보는 것은 담기지 않았다:

    프로덕션 트리에만 있던 **검사 파일 · 주석 · 파이썬 변경**

⚠ 파이썬은 **안 갈렸다**(총괄 실측 — 라이브 `POST /api/v1/scan` 출력이 저장소의
  `scorer.py`·`models.py` 와 한 글자도 다르지 않다). 그래서 남는 위험은
  **검사와 주석**뿐이다.

윈도우 트리를 나중에 찾으면 이 브랜치 옆에 올려 비교한다.
