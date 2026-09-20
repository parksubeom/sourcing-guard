# 안심 소싱 돋보기 — UI 디자인 가이드

## 1. 디자인 방향

**제품 성격**
- 소싱 전 상품의 안전성·인증·리콜·유해물질 정보를 빠르게 확인하는 서비스
- 사용자가 법규나 검사 결과를 어려워하지 않도록 **안심감 + 명확한 판단 + 근거 확인**을 중심으로 설계

**핵심 UX 원칙**
1. 결과를 먼저 보여준다.
2. `정상 / 주의 / 위험 / 일부 확인`의 의미를 색과 문구로 동시에 전달한다.
3. 모든 판단에는 확인 가능한 근거를 연결한다.
4. CTA는 한 화면에서 하나의 주 행동에 집중한다.
5. 정보량은 많아도 시각적 계층은 단순하게 유지한다.

---

## 2. Visual Direction

### 키워드
`Soft SaaS` · `Trustworthy` · `Friendly` · `Evidence-first` · `Korean Public Service`

### 전체 인상
- 기존 MVP의 베이지 배경 + 얇은 테두리 중심 구조를 유지하되, 카드/섹션의 위계를 강화
- 흰색 카드와 아주 옅은 라벤더 배경을 조합
- 보라색을 브랜드/행동 색상으로 사용
- 안전 관련 상태는 보조 색상으로 구분
- 그림자와 라운드는 과하지 않게 사용

### 권장 컬러

| Token | Color | 용도 |
|---|---|---|
| `brand-600` | `#7C3AED` | Primary CTA, 활성 메뉴 |
| `brand-500` | `#8B5CF6` | 강조, 링크 |
| `brand-50` | `#F5F3FF` | 브랜드 배경 |
| `success-600` | `#16845B` | 정상 |
| `success-50` | `#EAF8F1` | 정상 배경 |
| `warning-600` | `#D97706` | 주의 |
| `warning-50` | `#FFF4DF` | 주의 배경 |
| `danger-600` | `#DC3E4D` | 위험 |
| `danger-50` | `#FFF0F1` | 위험 배경 |
| `neutral-900` | `#20243A` | 주요 텍스트 |
| `neutral-700` | `#4B5568` | 본문 |
| `neutral-500` | `#7A8496` | 보조 텍스트 |
| `neutral-200` | `#E5E7EB` | 테두리 |
| `surface` | `#FFFFFF` | 카드 |
| `page` | `#FAF8FF` | 페이지 배경 |

---

## 3. Typography

### 권장 폰트

```css
font-family:
  "Pretendard",
  "Noto Sans KR",
  system-ui,
  sans-serif;
```

### 타입 스케일

| 이름 | Size | Weight | 용도 |
|---|---:|---:|---|
| Display | 48px | 600 | 메인 히어로 |
| H1 | 36px | 600 | 페이지 제목 |
| H2 | 24px | 600 | 섹션 제목 |
| H3 | 18px | 600 | 카드 제목 |
| Body L | 16px | 400 | 설명 |
| Body | 14px | 400 | 기본 본문 |
| Caption | 12px | 400 | 보조 정보 |
| Label | 12px | 600 | Badge |

---

## 4. Global Layout

### Header

- 높이: `64px`
- 최대 콘텐츠 폭: `1280px`
- 좌측: 로고 + 서비스명
- 우측: 주요 메뉴
  - 소개
  - 상품 검사
  - 대량 검사
  - 감시 목록
  - 카테고리 가이드
- 현재 메뉴는 브랜드 컬러 underline으로 표시
- 우측 끝에는 기준일/데이터 갱신일 표시

```text
[안심 소싱 돋보기]      소개  상품 검사  대량 검사  감시 목록  카테고리 가이드     2026.09.19 기준
```

### Container

```css
max-width: 1280px;
margin: 0 auto;
padding: 0 32px;
```

Desktop 기준:
- 1280px 이상: 32px padding
- 1024~1279px: 24px
- 모바일: 16px

---

# 5. 상품 검사 페이지

## Hero

### 기존 MVP 문제
- 제목/설명/입력 영역이 같은 시각적 레벨
- 무엇을 입력해야 하는지 한눈에 들어오지 않음
- 예시 카드가 실제 입력 기능과 분리되어 보임

### 개선안

상단에 명확한 메시지:

> **상세페이지를 붙여넣으세요.**

Sub copy:

> KC 인증 · 리콜 · 유해물질 기준을 정부 원문으로 확인합니다.

그 아래에 `예시로 바로 확인하기`를 제공한다.

### 예시 카드

3개 상태를 가로 배치:

- 정상
- 주의
- 위험

각 카드는 **상태 → 상황 → 한 줄 설명 → 예시 데이터** 순서.

---

## 실제 검사 입력 영역

카드 형태의 하나의 입력 모듈로 구성한다.

### 입력 순서

1. 상세페이지 텍스트
2. 상품 이미지
3. 안내/주의사항
4. 검사 시작 CTA

### Textarea

Placeholder:

> 여기에 상세페이지 텍스트, 이미지 설명, 상품명 등을 붙여넣어주세요.

권장:
- 최소 높이: `180px`
- 최대 입력 글자 수 표시
- 우측 하단 counter

### Image Upload

Dashed border dropzone:

> 상품 상세페이지 이미지를 붙여넣거나 업로드하세요.

보조:

> PNG · JPG · WEBP · GIF / 최대 4장

### 안내 Callout

보라색 계열의 subtle callout 사용.

> 이미지의 KC 마크에서 인증번호를 읽습니다. 일부 브랜드·제품은 인증번호가 없을 수 있습니다.

---

## Primary CTA

```text
[ ✦ 검사 시작하기 ]
```

- 높이: 48px
- radius: 10px
- brand-600
- font-weight: 600
- hover 시 brand-500

Secondary:

```text
[ 지우기 ]
```

---

# 6. 검사 결과 페이지

## 결과 Hero

결과 페이지의 가장 중요한 정보는 상단에서 즉시 이해되어야 한다.

### 구조

```text
[검사 완료]

이 상품,
안전한가요?

입력하신 상세페이지를 분석한 결과입니다.

[ 정상 ]   주요 항목이 모두 정상으로 확인되었습니다.
```

오른쪽에는 상품 요약 카드.

### 상품 요약 카드

```text
[상품 이미지]

상품명
브랜드 / 제조사
모델명
제조국

✓ 주요 항목이 모두 정상으로 확인되었습니다.
```

---

# 7. 검사 항목별 결과

3열 카드:

```text
┌─────────────┐
│ ✓ KC 인증    │
│              │
│ 적합         │
│ KC 인증번호가 │
│ 유효합니다.   │
└─────────────┘

┌─────────────┐
│ ↗ 리콜       │
│              │
│ 없음         │
│ 리콜 대상     │
│ 상품이 아닙니다│
└─────────────┘

┌─────────────┐
│ ! 유해물질    │
│              │
│ 적합         │
│ 기준을        │
│ 통과했습니다. │
└─────────────┘
```

카드마다 색을 과하게 쓰지 않고:
- 아이콘
- 상태 텍스트
- 작은 accent
정도로만 상태를 표현한다.

---

# 8. 상세 결과 / 근거

## 핵심 원칙

사용자는 결과보다 **왜 그런 결과가 나왔는지**를 확인하고 싶어 한다.

따라서:

```text
검사 결과
↓
판단 이유
↓
원문 근거
↓
공식 출처
```

순서로 보여준다.

### 근거 카드

```text
[● 정상]

인증번호 'CB061R2170-3018'이 조회되었습니다.

등록 제품명: 완구

국가기술표준원 안전인증정보 조회

────────────────────

[근거 전체 보기]
```

### 링크 스타일

- 일반 링크: `brand-600`
- 공식 출처: underline
- 링크 주변에 외부 이동 아이콘 사용 가능

---

# 9. 상태 디자인

## 정상

Badge:

```text
● 정상
```

- green background
- green text
- positive icon

메시지:

> 주요 확인 항목이 모두 정상으로 확인되었습니다.

---

## 주의

Badge:

```text
● 주의
```

메시지:

> 일부 항목에서 추가 확인이 필요합니다.

주의는 **위험과 동일하게 보이면 안 된다.**

---

## 위험

Badge:

```text
● 위험
```

메시지:

> 인증·리콜·유해물질 등 중요한 확인 항목에서 문제가 발견되었습니다.

위험 상태에서는 결과 카드 상단에 눈에 띄는 warning area를 추가한다.

---

## 일부 확인

Badge:

```text
● 일부 확인
```

사용자가 `문제가 있다`고 오해하지 않도록:

> 공개된 정보만으로 일부 항목을 확인할 수 없습니다.

라고 설명한다.

---

# 10. 검사 목록 / 체험 표본

## 기존 문제

기존 카드에는 텍스트가 너무 많이 들어가 있어:
- 상태
- 상품명
- 설명
- 근거
- 링크
- 재검사
가 한 덩어리처럼 보인다.

## 개선 구조

```text
[정상]                         [식약처] [1건 검사]

상품명
짧은 상품 설명

┌─────────────────────────┐
│ ✓ 검사 결과 · 정상       │
│ 주요 항목이 정상입니다.   │
└─────────────────────────┘

검사 근거 3건                    ˅

─────────────────────────

[ ↻ 지금 다시 검사 ]

마지막 검사 · 2026.09.19
```

### 카드 권장 크기

- 3-column desktop
- gap: 16px
- min-height: 380px
- padding: 24px
- radius: 14px

---

# 11. 대량 검사 페이지

대량 검사는 일반 검사와 다르게 **작업 진행률**이 핵심이다.

### 상단

```text
대량 검사

여러 상품의 안전 정보를 한 번에 확인하세요.

[ 파일 업로드 ]
```

### 진행 상태

```text
검사 중 · 72%

████████████████░░░░

완료 72개
검사 중 8개
대기 20개
```

### 결과 요약

```text
전체 100개

정상       77
주의       14
위험        3
일부 확인   6
```

---

# 12. 홈 / 소개 페이지

## Hero

좌측:
- 짧은 eyebrow
- 큰 headline
- 설명
- Primary CTA
- 예시 상태 카드

우측:
- 실제 검사 결과를 축약한 결과 카드
- 안심이 캐릭터

### Headline

> **이 상품,  
> 사업해도 될까?**

Sub:

> 상세페이지를 붙여넣으세요.  
> KC 인증 · 리콜 · 유해물질 기준을 정부 원문으로 확인합니다.

CTA:

> **내 상품 검사하기**

---

# 13. 캐릭터 사용 규칙

안심이 캐릭터는 장식보다 **상태 안내 역할**을 한다.

### 사용 위치
- 홈 Hero
- 검사 완료
- 빈 상태
- 로딩 상태
- 확인 필요 상태

### 크기

| 위치 | 권장 크기 |
|---|---:|
| Hero | 96~140px |
| Result card | 48~72px |
| Empty state | 72~96px |
| Mobile | 48~72px |

### 금지
- 모든 카드에 캐릭터 반복
- 결과와 무관한 감정 표현
- 캐릭터가 텍스트보다 크게 보이는 구성

---

# 14. Spacing System

8px 기반.

```text
4   = micro
8   = xs
12  = sm
16  = md
24  = lg
32  = xl
48  = 2xl
64  = 3xl
80  = section
```

컴포넌트 내부는 주로 `16 / 24`,
섹션 사이에는 `48 / 64`를 사용한다.

---

# 15. Radius

```css
--radius-sm: 8px;
--radius-md: 10px;
--radius-lg: 14px;
--radius-xl: 20px;
--radius-pill: 999px;
```

- Button: 10px
- Card: 14px
- Hero panel: 20px
- Badge: pill

---

# 16. Shadow

강한 그림자 대신 아주 약한 elevation.

```css
box-shadow:
  0 1px 2px rgba(30, 25, 50, 0.04),
  0 8px 24px rgba(30, 25, 50, 0.05);
```

MVP처럼 모든 카드에 동일한 border만 두지 말고,
**배경색 + border + 약한 shadow**를 조합한다.

---

# 17. Responsive

## Desktop ≥ 1024px

- Header horizontal
- Hero 2-column
- Result 3-column
- Sample cards 3-column

## Tablet 768–1023px

- Hero 1-column 또는 60/40
- Result 2-column
- padding 24px

## Mobile < 768px

- Header 메뉴 축소
- Hero 1-column
- 모든 결과 카드 1-column
- CTA full width
- 검사 근거 accordion 기본 접힘
- 긴 설명은 2~3줄까지만 노출

---

# 18. Interaction

### Hover

Card:
- border color → brand-200
- shadow 약간 증가

Button:
- background darken
- 100~150ms

### Accordion

검사 근거:
- 기본: collapsed
- 클릭 시 150~200ms ease
- chevron rotation

### Loading

검사 중에는 단순 spinner보다 단계형 상태를 사용한다.

```text
상세페이지 분석 중
       ↓
KC 인증 확인 중
       ↓
리콜 정보 확인 중
       ↓
유해물질 기준 확인 중
       ↓
결과 정리 중
```

---

# 19. Accessibility

- 상태를 색상만으로 표현하지 않는다.
- 모든 상태는 `아이콘 + 색상 + 텍스트` 조합.
- 본문 대비율 WCAG AA 이상.
- 버튼 focus state 제공.
- 키보드로 accordion 접근 가능.
- 링크는 색상 외 underline 또는 아이콘으로 구분.
- 이미지에는 의미에 맞는 alt text 제공.

---

# 20. 최종 컴포넌트 구조

```text
App
├── Header
│   ├── Logo
│   ├── Navigation
│   └── DataDate
│
├── Hero
│   ├── Eyebrow
│   ├── Heading
│   ├── Description
│   ├── PrimaryCTA
│   └── Mascot / ResultPreview
│
├── StatusExamples
│   └── StatusCard × 3
│
├── InspectionInput
│   ├── Textarea
│   ├── ImageDropzone
│   ├── InfoCallout
│   └── ActionButtons
│
├── ResultSummary
│   ├── ResultHero
│   ├── ProductSummary
│   └── CheckStatus × 3
│
├── EvidenceSection
│   └── EvidenceCard
│       ├── Result
│       ├── Reason
│       ├── Source
│       └── Link
│
└── Footer
```

---

# 21. 핵심 개선 포인트 요약

### Before
- MVP 느낌의 단순 border 카드
- 정보가 모두 같은 무게
- 결과와 근거가 섞여 있음
- CTA가 눈에 잘 띄지 않음
- 상태별 차이가 약함

### After
- **결과 → 판단 이유 → 공식 근거**의 명확한 계층
- Soft SaaS 스타일
- 보라색 브랜드 CTA
- 정상/주의/위험/일부 확인의 명확한 상태 시스템
- 카드 내부 정보량을 줄이고 핵심만 먼저 노출
- 근거는 accordion으로 필요할 때 확장
- 홈/검사/결과/목록 전체에서 동일한 디자인 시스템 적용

## 핵심 문장

> **안심 소싱 돋보기는 '예쁜 검사 UI'보다 '왜 이 결과가 나왔는지 바로 이해되는 UI'를 우선한다.**
