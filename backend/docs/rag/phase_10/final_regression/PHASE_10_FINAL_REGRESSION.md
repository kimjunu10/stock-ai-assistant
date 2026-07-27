# Phase 10 제품 수정 후 동일 홀드아웃 최종 회귀 테스트

## 성격과 동결

이 결과는 최초 블라인드 홀드아웃도, 일반화 성능도 아니다. Phase 8과 Phase 9에
사용한 동일 40문항을 Phase 10 제품 수정 배포 후 재사용한 최종 회귀 검증이다.
기존 85%와 97.5% 결과를 수정하거나 덮어쓰지 않았다.

- production revision: `ae049871418b7ed2102f38fa0fca629f348657b2`
- production CI/CD: PASS
- production 뉴스 smoke: PASS (`ok=4`, `no_data=1`, `error=0`, `null=0`)
- 최종 preflight: PASS
- 실행: 데이터 순서대로 40문항, 최초 시도 40회
- 외부 장애 재시도: 0회
- 개발셋 120문항: 실행하지 않음
- 결과 확인 후 제품·프롬프트·Tool·Retriever·Gold·채점기 수정: 없음

## 서로 다른 네 지표

| 명칭 | 결과 | 의미 |
|---|---:|---|
| automatic formal-condition pass rate | 39/40 (97.50%) | 동결 `case_passed()` 조건 |
| news canonical-cluster Recall@K | 2/6 (33.33%) | canonical `news_clusters.id` top-K 적중 |
| actual Tool execution success | 37/39 (94.87%) | Tool 사용 문항 중 모든 status가 ok/no_data |
| final answer completion rate | 40/40 (100.00%) | completed + 비어 있지 않은 답변 |

formal 조건에는 뉴스 canonical 적중, strict/event-equivalent Recall, Tool status,
citation coverage, Solar grounded 자체가 들어가지 않는다. 따라서 뉴스 miss여도
formal pass가 가능하며 97.5%를 “RAG 정확도”라고 부를 수 없다.

## 최종 지표

| 영역 | 지표 | 결과 |
|---|---|---:|
| Agent | 필수 Tool 호출률 | 100.00% |
| Agent | Tool 인자 정확도 | 100.00% |
| Agent | 복합 질문 완료율 | 100.00% |
| Tool | status ok / no_data / error / null | 47 / 0 / 0 / 3 |
| Tool | step_limit | 0 |
| 숫자 | 숫자 / 단위 / 기간 정확도 | 83.33% / 100.00% / 100.00% |
| 숫자 | 실제값·전망값 혼동 | 0 |
| 출처 | coverage / precision | 100.00% / 100.00% |
| 출처 | 존재하지 않는 출처 / 근거 없는 숫자 | 0 / 0 |
| 출처 | 타 종목 출처 혼입 / 제외조건 위반 | 0 / 0 |
| 뉴스 strict | Recall@K / Hit@1 / MRR | 33.33% / 33.33% / 0.3333 |
| 뉴스 event-equivalent | Recall@K / Hit@1 / MRR | 33.33% / 33.33% / 0.3333 |
| 리포트 | Recall@K / Hit@1 / MRR | 100.00% / 60.00% / 0.7667 |
| 리포트 | 페이지 정확도 | 4/14 (28.57%) |
| 조회 | 구조화 조회 성공률 | 93.33% |
| Judge | Solar 성공 / fallback | 40 / 0 |
| 운영 | P50 / P95 | 4496ms / 8086ms |
| 비용 | 총 / 문항당 | $0.272251 / $0.006806 |

## 뉴스 6문항

| 문항 | 실제 query | 실제 적용 기간 | 반환 cluster 순서 | Gold rank | strict/equivalent |
|---|---|---|---|---:|---|
| h-news-20 | `정의선 회장` | `None` | 4528, 4534, 4525, 4518, 4499 | - | miss/miss |
| h-news-21 | `삼성 AI 글래스` | `None` | 7181, 6223, 3708, 3473, 5550 | 1 | hit/hit |
| h-news-22 | `美 하원 세출위` | `None` | 6889, 4972, 7037, 6940, 5763 | 1 | hit/hit |
| h-news-23 | `이재명 대통령` | `None` | 6281, 6279, 5599, 4143, 5601 | - | miss/miss |
| h-news-24 | `기아` + `현대차` | `None` | 4251, 4193, 7034, 7324, 4277, 4553, 4585, 6853, 6957, 6852 | - | miss/miss |
| h-news-25 | `브로드컴` | `None` | 7136, 7107, 7163, 7151, 7004 | - | miss/miss |


기간 없는 사건 질문에 임의 `recent`를 넣던 제품 결함은 제거됐다. 여섯 질문 모두
모델 Tool 인자와 실제 적용 기간이 `None`이었고 h-news-22는 canonical 6889를
rank 1로 회복했다. 그러나 h-news-20이 다른 사건으로 밀렸고 h-news-23의 query는
너무 넓었다. h-news-24·25는 관련 별도 cluster가 반환됐지만 사전 승인된
event-equivalent가 없어 strict와 equivalent 모두 miss다. 결과적으로 뉴스 Recall은
Phase 9와 같은 2/6이며, 뉴스 검색 문제가 전체적으로 개선됐다고 선언할 수 없다.

## 실제 실패와 종료 판정

- formal failure: h-fin-20 1건
- actual Tool/완료 실패: h-mix-20, h-na-09 2건
- 외부 장애: 0건
- `status=null`: 3건, `TOOL_RUNTIME_ERROR` 및 예외 계층 기록 없음
- h-na-09는 삼성전자 값만 근거로 애플 값까지 동일하다고 만든 실제 답변 실패다.
  Solar Judge의 false positive 때문에 formal pass가 됐다.

최종 상태: **치명적인 production 장애가 남아 종료 불가**.

이 판정은 추가 튜닝을 제안하거나 동일 홀드아웃을 다시 쓰겠다는 뜻이 아니다.
사용자 규칙대로 이 결과 이후 제품·Gold·채점기를 수정하지 않고, 동일 홀드아웃을
다시 사용한 튜닝이나 평가도 하지 않는다. Phase 10 실행 작업은 여기서 종료한다.
