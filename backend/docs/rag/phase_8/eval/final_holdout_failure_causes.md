# Phase 8 최종 홀드아웃 실패 문항 원인표

실행 시각은 `2026-07-27T13:40:57.460488+09:00`부터
`2026-07-27T13:43:02.433524+09:00`까지다. 40문항을 데이터 순서대로
각 1회 실행했고 재시도는 없었다.

## 동결 채점기의 전체 통과 조건 실패

| 문항 | 유형 | 실패 조건 | 직접 관찰 |
|---|---|---|---|
| h-fin-20 | 정확한 재무 숫자 | financial_value_mismatch | `get_financial_facts=error`, 숫자 근거 없음 |
| h-fin-21 | 정확한 재무 숫자 | exclusion_violated, financial_value_mismatch | `get_financial_facts=error`; 답변이 제외 요청한 전망을 다시 제안 |
| h-fin-22 | 정확한 재무 숫자 | financial_value_mismatch | `get_financial_facts=error`, 숫자 근거 없음 |
| h-fin-23 | 정확한 재무 숫자 | financial_value_mismatch | `get_financial_facts=error`, 숫자 근거 없음 |
| h-fin-24 | 정확한 재무 숫자 | financial_value_mismatch | `get_financial_facts=error`, 숫자 근거 없음 |
| h-fin-25 | 정확한 재무 숫자 | financial_value_mismatch | `get_financial_facts=error`, 숫자 근거 없음 |

동결 채점기의 formal failure는 6건이다. 다만 이 통과 조건은 Tool을
“호출했는가”를 확인하고 Tool의 최종 `status=error` 자체는 실패 조건에 넣지
않는다. 따라서 아래 31건의 실제 Tool 실행 실패 중 숫자 정답 조건이 있는 6건만
전체 통과 실패로 나타났다.

## 실제 제품 실행 실패

외부 API 429·timeout·명시적 일시 네트워크 오류는 없었다. 아래 오류는 허용된
재시도 조건에 해당하지 않아 재실행하지 않았으며 실제 제품 실행 실패로 분류한다.

| 문항 | 실패 Tool/종료 상태 | 출처 수 | 분류 |
|---|---|---:|---|
| h-term-12 | `lookup_financial_term=error` | 0 | 구조화 용어 조회 실패 |
| h-term-13 | `lookup_financial_term=error` | 0 | 구조화 용어 조회 실패 |
| h-term-14 | `lookup_financial_term=error` | 0 | 구조화 용어 조회 실패 |
| h-term-15 | `lookup_financial_term=error` | 0 | 구조화 용어 조회 실패 |
| h-fin-20 | `get_financial_facts=error` | 0 | 재무 조회 실패 |
| h-fin-21 | `get_financial_facts=error` | 0 | 재무 조회 실패 |
| h-fin-22 | `get_financial_facts=error` | 0 | 재무 조회 실패 |
| h-fin-23 | `get_financial_facts=error` | 0 | 재무 조회 실패 |
| h-fin-24 | `get_financial_facts=error` | 0 | 재무 조회 실패 |
| h-fin-25 | `get_financial_facts=error` | 0 | 재무 조회 실패 |
| h-news-20 | `search_news=error` | 0 | 뉴스 검색 실패 |
| h-news-21 | `search_news=error` | 0 | 뉴스 검색 실패 |
| h-news-22 | `search_news=error` | 0 | 뉴스 검색 실패 |
| h-news-23 | `search_news=error` | 0 | 뉴스 검색 실패 |
| h-news-24 | `search_news=error` 2회 | 0 | Agent 내부 반복 검색 모두 실패 |
| h-news-25 | `search_news=error` | 0 | 뉴스 검색 실패 |
| h-disc-16 | `get_disclosure_values=error` | 0 | 구조화 공시 조회 실패 |
| h-disc-17 | `get_disclosure_values=error` | 0 | 구조화 공시 조회 실패 |
| h-disc-18 | `get_disclosure_values=error` | 0 | 구조화 공시 조회 실패 |
| h-disc-19 | `get_disclosure_values=error` | 0 | 구조화 공시 조회 실패 |
| h-disc-20 | `get_disclosure_values=error` | 0 | 구조화 공시 조회 실패 |
| h-report-16 | `search_research_reports=error` | 0 | 리포트 검색 실패 |
| h-report-17 | `search_research_reports=error` | 0 | 리포트 검색 실패 |
| h-report-18 | `search_research_reports=error` | 0 | 리포트 검색 실패 |
| h-report-19 | `search_research_reports=error` | 0 | 리포트 검색 실패 |
| h-report-20 | `search_research_reports=error` | 0 | 리포트 검색 실패 |
| h-mix-16 | `get_disclosure_values=error`, `get_financial_facts=error` | 0 | 복합 조회 실패 |
| h-mix-17 | `get_financial_facts=error`, `get_disclosure_values=error` | 0 | 복합 조회 실패 |
| h-mix-18 | `get_disclosure_values=error`, `get_financial_facts=error` | 0 | 복합 조회 실패 |
| h-mix-19 | `get_financial_facts` 상태 누락, `get_disclosure_values=error` | 0 | 복합 조회 일부 실패 |
| h-mix-20 | 일부 Tool 오류 후 `step_limit`, 빈 답변 | 0 | 복합 질문 완료 실패 |

나머지 9건은 최종 Tool 오류 없이 종료됐다. 그중 `h-na-10`은 답변 불가능
문항이라 Tool·출처가 없는 것이 정상이다.

## 외부 장애

외부 장애 문항은 0건이다. Agent 재시도도 0건이며 Solar Judge는 40건 모두
성공했다.
