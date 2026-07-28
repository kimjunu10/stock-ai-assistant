# Failure analysis

## Holdout formal failures

### `h-fin-23`

- 질문: `한화오션(042660) 2025년 3분기 당기순이익 알려줘`
- 실행: `get_financial_facts`, `quarter`, 정상 `ok`
- 답변 근거: `042660/2025/11014/CFS/당기순이익/quarter`
- 실패 원인: Gold는 `cumulative`를 요구한다. 동일 문장 구조의 `h-fin-20`은
  `quarter`를 요구하므로 평가 의미가 일관되지 않다.
- 성격: 제품 규칙과 Gold 불일치. 숫자 환각이나 타 종목 오염은 아니다.

### `h-news-23`

- 질문: `SK하이닉스 이재명 대통령 이슈 설명해줘`
- 결과: semantic 다중 종목 판정으로 Tool 실행 전 차단
- 원인: semantic classifier가 뉴스 속 인물을 별도 회사 후보로 축약했고, 후단 필터가
  원 질문의 인물 역할을 복원하지 못했다.
- 성격: 실제 제품 결함. 선택 종목 안전장치의 false positive.

### `h-news-24`

- 질문: `현대차 기아 관련 소식 알려줘`
- 결과: 실제 두 지원 회사를 명시해 Tool 실행 전 차단
- 원인: 단일 종목 화면 안전 정책과 기존 Gold의 검색 요구가 충돌한다.
- 성격: 의도된 안전 차단이지만 회귀 기준상 실패.

## Devset formal failures

- `term-07`: 모델이 일반지식으로 답해 필수 용어 Tool을 생략했다.
- `fin-05`: Tool은 누적 반기값을 반환했으나 Gold 값과 불일치했다. DB/Gold 수치 감사가 필요하다.
- `news-08`: 답변 내용은 검색 근거와 맞았으나 formal overclaim 판정. Solar는 통과했다.
- `news-11`: 뉴스 질문에서 사실 확인용 재무 Tool을 추가 호출해 forbidden Tool 실패.
- `news-14`: 한화오션과 HJ중공업을 함께 명시해 단일종목 안전장치가 차단했다.
- `mix-06`: “왜 줄었나”에 뉴스가 필요했지만 재무+리포트만 호출했다.
- `mix-08`: 최근 실적 이슈에 뉴스가 필요했지만 리포트+재무만 호출했다.
- `mix-09`, `mix-10`: 검색 리포트의 비구조화 과거 목표주가를 모델이 언급해 validator가
  제거했다. 최종 답변은 안전하지만 필수 Tool/argument formal 조건 일부가 맞지 않았다.

## High-risk manual audit

- Tool `error`: 0
- Tool `null`: 0
- `step_limit`: 0
- 타 종목 source/숫자 오염: 0
- 존재하지 않는 citation: 0
- 미지원·다중 종목의 Tool 실행: 0
- `h-na-09`: 삼성전자와 애플 비교를 Tool 0회로 차단. Phase 10의 타 회사 재무 Tool
  실행/null 재발 없음.
- 현재가/종가: targeted에서 `price_kind=current`, `market_status`, `as_of`를 반환했고
  오늘 확정 종가가 없을 때 장후 현재가와 명확히 구분했다.
- 차트: 1개월/1년/기간 없는 일반 흐름 모두 질문 기간 또는 기본 1개월과 일치했다.
- 뉴스 링크: cluster ID가 있는 source는 `/news?cluster=<id>` 내부 링크였다.
- 컨텍스트 뉴스: 선택 기사 1건만 source로 사용하고 요약 1문장+불릿으로 답했다.
- 컨텍스트 리포트: 읽기 쉬운 불릿 답변은 정상이나, 평가 전 발견된 primary source의
  stated 목표주가 evidence 누락을 수정했다.

## Solar Judge false positives

Solar는 devset 120/120, holdout 40/40을 모두 grounded로 통과시켰다. 그러나 formal 실패는
각각 9건, 3건이며, devset에는 validator가 근거 없는 리포트 숫자를 제거한 사례와
overclaim 사례도 있다. 따라서 최소 12건은 “Solar 통과만으로 성공 판정할 수 없는” 사례다.
특히 `h-news-23/24`의 Tool 미실행과 `h-fin-23`의 기간 유형 불일치를 Solar가 모두 통과시켰다.

## Targeted API iterations

- iteration1: 10/15. 채점기가 `어제 종가`처럼 올바른 구분도 단어 존재만으로 실패시킨
  오탐 3건과 실제 뉴스 인과 문장 잔존 2건을 분리했다.
- iteration2: 15/15. 채점기 오탐 수정 및 뉴스 인과 문장 제거 후 working tree 검증.
- iteration3: 최종 commit에서 14/15. 실행이 자정 직후(2026-07-29 00:00 KST) 시작되어
  “오늘 뉴스”가 새 날짜 기준 `no_data`였다. 재시도하지 않았다. 나머지 14건은 통과했다.

## Remaining root causes

1. semantic 회사 분류가 인물·발행기관의 역할 정보를 잃을 수 있다.
2. 한 화면 한 종목 정책과 다중 회사 뉴스 Gold가 충돌한다.
3. 분기/누적 Gold가 같은 자연어에 대해 일관되지 않다.
4. 리포트 source의 top-level page 직렬화가 locator 정보를 승격하지 않는다.
5. LLM Tool 선택은 여전히 일반지식 답변 또는 복합 질문의 한 Tool 생략이 가능하다.
6. 뉴스·리포트 본문의 숫자는 구조화 숫자 근거와 별도라 validator 사후 제거가 발생한다.
