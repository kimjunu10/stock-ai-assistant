# Failure analysis

## 종료를 막는 문제

| 범위 | 사례 | 문제 | 근본 원인 | 해결 가능성 |
|---|---|---|---|---|
| targeted API | `today-close` | `price_kind=current`인 218,000원을 오늘 종가라고 표현 | prompt에는 금지 규칙이 있지만 응답 후 current/close 의미 검증이 없고 payload에 market status가 없음 | 가능: 세션 상태를 Tool 계약에 추가하고 의미 validator에서 강제 |
| targeted API | 모든 가격 질의 | 기준 시각은 locator에 있으나 시장 상태가 없음 | `PriceQuote`·source·visualization 스키마에 market status 필드가 없음 | 가능: 공급자 세션 상태를 단일 계약으로 전파 |
| targeted API | `one-month-flow` | quote는 전일 종가 254,000/-14.17%, 일봉은 255,000/-14.51% | `_daily_payload`가 candle 인접값으로 다시 계산해 quote의 basePrice와 분기 | 가능: 마지막 일봉의 비교 기준을 quote.previous_close로 통일 |
| targeted API | `unspecified-flow` | 일반 흐름 질문에 2점 차트만 반환 | prompt가 기간 미지정 시 임의 기간 금지를 명시하고 Tool의 `lookback=None`도 2점 계약이라 요구된 기본 기간과 충돌 | 가능: 제품 정책을 정한 뒤 prompt+Tool 기본값을 함께 변경 |
| targeted API | 뉴스 2건 | 상승과 급락을 한 답에 함께 쓰고 원인 단정도 남음 | 상충 cluster를 조정하는 단계가 없고 causal sanitizer는 경고문만 앞에 붙여 원문을 보존 | 가능: 상충 탐지/시각 정규화 후 위험 문장을 제거 또는 재생성 |
| frozen holdout | `h-news-23` | 대통령 이름을 다중 회사로 오인해 뉴스 Tool 미실행 | 의미 분류기의 company 대상 정의가 인물·기관 관계 문장에서 불안정 | 가능: 분류 스키마/결정 규칙과 결정 trace를 강화 |
| frozen dev | `report-11`, `report-15` | 증권사명을 다른 종목으로 오인해 차단 | 분해형 Unicode 증권사명이 semantic classifier에서 회사 대상으로 분류됨 | 가능: Unicode NFC 정규화와 broker/entity role 분리 |
| frozen holdout | `h-disc-18`, `h-disc-20` | 유효한 자기주식 공시를 없다고 답함 | 구조화 질문이 `search_disclosures`로 라우팅되어 최신 무관 공시가 상위 노출 | 가능: 사건 유형이 식별되면 구조화 Tool을 결정적으로 선택 |
| frozen holdout | `h-report-18` | 하나증권 요청인데 다른 증권사 리포트만 답함 | Tool 계약에 publisher filter가 없고 모델 query에서도 증권사명이 누락 | 가능: publisher를 구조화 인자로 전달하고 Unicode 정규화 |
| frozen dev/holdout | `fin-04`, `fin-10`, `h-fin-20` | quarter/cumulative 또는 CFS/OFS 선택 오류 | 규칙은 prompt에 있으나 모델이 Tool 인자를 위반해도 사전 검증이 차단하지 않음 | 가능: 기간·재무제표 기준을 deterministic resolver로 이동 |

## 고위험 수동 감사

- 모든 formal 실패 15건(dev 12, holdout 3), 모든 null 4건, 모든 blocked 7건, holdout 뉴스 6건, 현재 화면 문맥 10건, 가격 관련 holdout 4건을 raw record와 Tool trace로 확인했다.
- 타 회사 source/card/숫자 오염은 발견되지 않았다. `h-na-09`는 Agent Tool 0회로 차단되어 Phase 10의 Apple 수치 혼입이 재발하지 않았다.
- `h-mix-20`은 첫 financial Tool 인자 `순이익`이 스키마 오류로 null이었고 동일 요청 안에서 `당기순이익`으로 교정됐다. 최종 숫자는 근거와 일치하지만 null 상태 자체는 운영 결함이다.
- `news-08` formal overclaim은 실제 투자 과장 문제가 아니라 뉴스의 상품 조건인 “잔존가치를 보장”을 범용 키워드 채점기가 오탐한 것이다.
- 내부 뉴스 링크는 cluster ID가 있는 모든 targeted source/card에서 `/news?cluster=<id>`로 올바르게 생성됐다.

## Solar Judge

- Solar 호출은 dev 120/120, holdout 40/40 성공했고 fallback은 0이다.
- 과거 `h-na-09` 종목 오염을 통과시킨 유형의 false positive는 재발하지 않았다.
- 다만 Solar의 선언된 범위는 숫자·필수 Tool·Gold ID를 판정하지 않는다. 따라서 `h-fin-20`, `h-news-23`, `h-news-24`도 grounded=true였다. Solar 40/40을 전체 성공률로 해석하면 3건의 false positive가 된다.
- dev의 `news-08`은 Solar가 grounded=true로 보고 범용 overclaim 키워드의 오탐을 드러냈다.

## 판정

**종료 불가.** targeted API에서 current/close 의미, market status, 가격 기준값 일관성, 일반 차트 기간, 뉴스 상충·인과 문제가 확인됐다. 최신 holdout formal도 Phase 10의 39/40에서 37/40으로 하락했다.
