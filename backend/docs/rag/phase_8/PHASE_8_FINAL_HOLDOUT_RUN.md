# Phase 8 최종 홀드아웃 평가

## 결론

최종 홀드아웃 실행 절차는 완료됐지만 제품 성능 관점에서 Phase 8을 완료로
선언할 수 없다.

- 동결 채점기 전체 조건 통과: **34/40 (85.00%)**
- 외부 장애 제외 통과: **34/40 (85.00%)**
- 동결 채점기 formal failure: **6건**
- 실제 제품 실행 실패: **31건**
- 외부 장애: **0건**
- Agent 재시도: **0건**

31건은 최종 Tool trace에 `status=error`, 상태 누락, 또는 `step_limit`이
직접 남은 문항이다. 동결된 전체 통과 조건은 Tool 호출 여부를 보지만 Tool
성공 상태를 직접 실패 조건으로 사용하지 않아 31건 중 숫자 정답이 실패한
6건만 formal failure로 나타났다. 따라서 85%를 실제 응답 성공률로 해석하면 안 된다.

## 동결 및 실행 원칙

- 기준 커밋: `8c3a55c1606880fbf70664c0cfd1a3212381dc6b`
- 브랜치: `phase/8-final-holdout-run`
- 개발셋 120문항 실행: 없음
- 홀드아웃: 데이터 순서대로 40문항, 최초 1회
- 성공 문항 재실행: 없음
- 허용 외부 장애 재시도: 0회
- 결과 확인 후 제품 코드·프롬프트·Tool·Retriever·평가 코드·Gold 변경: 없음

## Preflight

실행 직전 `2026-07-27T13:28:21.577094+09:00`에 1회 실행해 PASS했다.

| 검사 | 결과 |
|---|---|
| 홀드아웃 형식·split | 40/40 PASS |
| 재무 Gold | 6/6 존재 |
| 공시 Gold | 5/5 존재 |
| 용어 Gold | 4/4 존재 |
| 뉴스 canonical Gold | 6/6 현행 document/chunk 해석 |
| 리포트 Gold | 14/14 청크·페이지 확인 |
| 상대 기간 | 오류 0, 명시적 상대 기간 없음 40 |
| event-equivalent 형식 | PASS |

뉴스의 resolved document/chunk ID는
`eval/final_holdout_run_preflight.json`에 감사값으로만 보존했다.

## 실행 결과

- Agent 실행 시작: `2026-07-27T13:40:57.460488+09:00`
- Agent 실행 종료: `2026-07-27T13:43:02.433524+09:00`
- Agent 실행 구간: 124.973초
- 최초 시도: 40
- 재시도: 0
- 총 Agent 시도: 40
- Solar Judge: 성공 40, fallback 0
- grounded=false: 0건(참고 전용)

## 최종 지표

| 영역 | 지표 | 결과 |
|---|---|---:|
| 전체 | 전체 40문항 통과 | 34/40, 85.00% |
| 전체 | 외부 장애 제외 통과 | 34/40, 85.00% |
| 제품 | formal failure | 6 |
| 제품 | 실제 Tool/완료 실패 | 31 |
| 외부 | 외부 장애 | 0 |
| Agent | 필수 Tool 호출률 | 100.00% |
| Agent | Tool 인자 정확도 | 100.00% |
| Agent | 복합 Tool 호출 완료율 | 100.00% |
| Agent | 복합 최종 답변 완료 | 4/5, 80.00% |
| 숫자 | 숫자 정확도 | 0/6, 0.00% |
| 숫자 | 단위 정확도 | 5/6, 83.33% |
| 숫자 | 기간 정확도 | 6/6, 100.00% |
| 숫자 | 실제값·전망값 혼동 | 0 |
| 출처 | 근거 없는 숫자 | 0 |
| 출처 | 존재하지 않는 출처 | 0 |
| 출처 | 답변 출처 coverage | 18.92% |
| 출처 | 타 종목 혼입 | 0 |
| 답변 | 제외 조건 위반 | 1 |
| 검색 | 뉴스 strict Recall@K / Hit@1 / MRR | 0 / 0 / 0 |
| 검색 | 뉴스 event-equivalent Recall@K / Hit@1 / MRR | 0 / 0 / 0 |
| 검색 | 리포트 Recall@K / Hit@1 / MRR | 0 / 0 / 0 |
| 검색 | 리포트 페이지 정확도 | 0/14, 0.00% |
| 조회 | 구조화 조회 성공률 | 0.00% |
| Judge | Solar 성공 / fallback | 40 / 0 |
| 지연 | P50 / P95 | 2,396ms / 7,370ms |
| 비용 | 총비용 / 문항당 | $0.229838 / $0.005746 |

grounded는 위 통과 조건에 포함하지 않았다.

## 검색 결과

뉴스 strict 평가는 canonical `news_clusters.id`를 사용했다. resolved
document/chunk UUID는 적중 판정에 사용하지 않았다.

- 뉴스 strict: 0/6
- 뉴스 event-equivalent: 0/6
- 리포트: 0/5
- 리포트 페이지: 0/14
- 구조화 조회: 0%

뉴스 6건 모두 `search_news=error`였으며 출처가 반환되지 않았다. 동결 채점기는
4건을 실행 시 Agent가 선택한 `relative_period=recent` 범위 밖 Gold로,
2건을 retriever failure로 분리했다. preflight는 질문이나 기대 Tool 인자에
상대 기간이 없는 문항을 정상적으로 통과시켰으며, 실행 시 Agent가 자율적으로
`recent`를 선택한 결과는 원시 trace에 그대로 보존했다.

## 실패 분석

formal failure 6건은 모두 재무 숫자 문항이다.

- `h-fin-20`~`h-fin-25`: 재무 Tool 오류로 정답 숫자 미제공
- `h-fin-21`: 숫자 실패에 더해 제외 요청한 전망을 다시 제안해 제외 조건 위반

운영상 실제 실패는 총 31건이다.

| 유형 | 실패/전체 | 주 원인 |
|---|---:|---|
| 금융용어 | 4/4 | `lookup_financial_term=error` |
| 정확한 재무 숫자 | 6/6 | `get_financial_facts=error` |
| 뉴스 사건·영향 | 6/6 | `search_news=error` |
| 공시 설명·구조화 값 | 5/5 | `get_disclosure_values=error` |
| 증권사 리포트 | 5/5 | `search_research_reports=error` |
| 복수 기능 혼합 | 5/5 | 일부/전체 Tool 오류, 1건 `step_limit` |

외부 API 장애 식별자가 없어 이 31건은 외부 장애에서 제외했다. 답변 품질이나
검색 실패를 이유로 선택 재실행하지 않았다.

## 개발셋 대비

- 외부 장애 제외 통과율: 97.44% → 85.00%, **-12.44%p**
- 뉴스 strict Recall@K: 63.16% → 0%
- 리포트 Recall@K: 86.67% → 0%
- 구조화 조회: 77.78% → 0%
- 숫자 정확도: 94.74% → 0%

Tool 선택·인자 정확도는 오히려 높았지만 실제 Tool 실행과 근거 반환이
무너졌다. 따라서 결과 차이는 단순한 모델 응답 과적합만으로 설명할 수 없고,
홀드아웃 실행 시점의 제품 Tool 경로 실패가 지배적이다. 개발셋 97.44%를
홀드아웃 결과로 표현하지 않는다.

## Phase 8 상태

- 최종 평가 프로토콜: **완료**
- 홀드아웃 실행·감사 기록: **완료**
- 제품 성능 완료 판정: **미완료**

낮은 결과를 확인한 뒤 코드·프롬프트·Gold·채점기를 변경하지 않았고, 남은
문제는 이 보고서의 한계와 실제 제품 실패로 동결 기록한다.

## 산출물

- `eval/final_holdout_run_preflight.json`
- `eval/final_holdout_raw_records.json`
- `eval/final_holdout_tool_traces.json`
- `eval/final_holdout_metrics.json`
- `eval/final_holdout_failures.json`
- `eval/final_holdout_failure_causes.md`
- `eval/final_holdout_external_failures.json`
- `eval/final_holdout_judge_cache.json`
- `eval/final_holdout_dev_comparison.md`
- `PHASE_8_FINAL_HOLDOUT_PRESENTATION.md`
