# Phase 10 뉴스 검색 평가 감사

## 범위

- 기준: `main@dd1313e2165926823797632008d6840e1c1def22` (PR #74 포함)
- 입력: Phase 9 동일 홀드아웃 회귀의 저장된 raw record와 Tool trace
- 감사 중 제품 코드 수정·Agent 실행: 없음
- 최초 블라인드 또는 일반화 평가가 아니라 기존 결과의 읽기 전용 감사

## Automatic formal-condition pass의 실제 구성

최종 boolean은
`backend/scripts/phase8_final_evaluation_after_prompt.py::case_passed`
(85–113행)에서 계산한다. 문서 검색 지표는 별도로
`backend/app/eval/grader.py::aggregate`(1003–1024행)에서 집계된다.

| 항목 | 최종 formal boolean 포함 | 코드 근거 |
|---|---|---|
| required Tool 호출 | 예 | `case_passed` 91–92행 |
| Tool 인자 정확도 | 예 | 95–96행 |
| Tool status | 아니오 | 함수 전체에 status 판정 없음 |
| 뉴스 canonical Gold cluster 적중 | 아니오 | 뉴스 Gold는 `grade_case` 676–680행에서 개별 Gold hit 채점을 건너뛰고 별도 retrieval 지표로 이동 |
| 뉴스 strict Recall@K | 아니오 | `aggregate` 1006행의 별도 집계 |
| 뉴스 event-equivalent Recall@K | 아니오 | `aggregate` 1017–1019행의 별도 집계 |
| citation coverage | 아니오 | `aggregate` 991–995행의 별도 집계 |
| Solar Judge | 일부 파생 항목만 | Judge 성공·grounded 자체는 미포함. Judge가 채운 exclusion·overclaim·unanswerable 결과는 97–104행에서 사용 |
| 숫자 정확도 | 예 | financial exact와 number matched, 105–108행 |
| 단위 정확도 | 독립 조건 아님 | aggregate에는 기록되지만 `financial_grade.unit_ok` 자체는 formal 조건이 아님 |
| 기간 정확도 | 예 | period/trading day, 109–112행 |

따라서:

- 뉴스 Gold cluster를 찾지 못해도 formal pass가 가능하다.
- 뉴스 Recall miss 자체는 formal fail을 발생시키지 않는다.
- Solar Judge는 반환된 다른 출처에 답변이 grounded됐다고 판단할 수 있다. 다만
  Judge가 retrieval miss를 formal pass로 “뒤집는” 것이 아니라 retrieval 자체가
  formal 조건에 없기 때문에 pass가 유지된다.
- 39/40(97.5%)은 automatic formal-condition pass rate이며 RAG 정확도가 아니다.
  뉴스 canonical-cluster Recall@K는 별도 2/6(33.33%)이다.

## 뉴스 6문항 저장 trace 감사

실행 기준일은 2026-07-27이다. 모든 문항에 사용자 기간 표현이 없었지만 Agent는
모두 `relative_period=recent`를 넣었다. recent는
`resolve_relative_date_range()`에 의해 2026-07-25부터 2026-07-27까지다.
홀드아웃 event-equivalent 추가 승인은 없으므로 strict와 event-equivalent hit가 같다.

| 문항 | 질문 | canonical Gold | 실제 query / relative_period | 반환 cluster 순서 | Gold 순위 | strict / event hit | 최종 답변 출처 cluster | Solar / formal | 원인 |
|---|---|---:|---|---|---:|---|---|---|---|
| h-news-20 | 현대차 정의선 회장 건은 어떤 내용이야? | 7131 | `정의선 회장` / `recent` | 7131, 7219, 7143, 7280, 7074 | 1 | hit / hit | 동일 5개 | success·grounded / pass | 적중. 불필요한 recent가 있었지만 Gold가 반환됨 |
| h-news-21 | 삼성전자 삼성 AI 글래스 관련해서 무슨 일 있었어? | 7181 | `삼성 AI 글래스` / `recent` | 7181, 7182, 7195, 7012, 7002 | 1 | hit / hit | 동일 5개 | success·grounded / pass | 적중 |
| h-news-22 | 한화오션 美 하원 세출위 뉴스 어떻게 된 거야? | 6889 | `美 하원 세출위` / `recent` | 7193, 7314, 7222, 7193, 7306 | 없음 | miss / miss | 동일 순서 | success·grounded / pass | **질문에 없는 relative_period 추가로 정답 제외**. Gold 2026-07-23은 시작일 7월 25일보다 이전 |
| h-news-23 | SK하이닉스 이재명 대통령 이슈 설명해줘 | 7108 | `이재명 대통령` / `recent` | 6982, 7165, 7198, 7135, 7101 | 없음 | miss / miss | 동일 5개 | success·grounded / pass | **질문에 없는 relative_period 추가로 정답 제외**. Gold 2026-07-24는 시작일 이전 |
| h-news-24 | 현대차 기아 관련 소식 알려줘 | 7014 | `기아` / `recent`, 이후 `현대차` / `recent` | 7050, 7266, 7176, 7213, 7186, 7177, 7173, 7166 | 없음 | miss / miss | 동일 8개 | success·grounded / pass | **질문에 없는 relative_period 추가로 정답 제외**. Gold 2026-07-24는 시작일 이전 |
| h-news-25 | 삼성전자 브로드컴 건은 어떤 내용이야? | 7149 | `브로드컴` / `recent` | 7151, 7145, 7136, 7163, 7002 | 없음 | miss / miss | 동일 5개 | success·grounded / pass | **기타**. Gold 날짜 2026-07-25는 recent 범위 안이며 종목·query도 맞다. 저장 trace는 최종 상위 5개만 보존해 후보 생성과 hybrid ranking 중 어느 단계에서 빠졌는지 구분 불가. 7151을 동일 사건으로 승인한 데이터도 없음 |

## 수정 진행 결정

일반 제품 문제는 3건에서 같은 방식으로 재현됐다.

1. 질문에 기간 표현이 없다.
2. Agent가 사건 식별어만 보고 `recent`를 추가한다.
3. Tool wrapper가 이를 그대로 날짜 범위로 변환한다.
4. 검색 가능한 과거 사건이 필터 단계에서 제외된다.

질문별 ID·cluster·제목·날짜 없이 “사용자가 직접 표현한 기간만 적용”하는
일반 규칙으로 수정할 수 있으므로 제품 최소 수정 조건을 충족한다.

h-news-25는 원인 계층을 증명할 데이터가 없으므로 candidate/ranking을 수정하지 않는다.
