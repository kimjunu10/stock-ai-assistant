# 뉴스 클러스터링 운영 파이프라인 및 전체 백필 결과 보고서

## 1. 보고서 개요

- 작성 기준일: 2026-07-21 (KST)
- 대상 환경: 실제 Supabase 운영 데이터
- 백필 run key: `full-news-backfill-v2-20260721`
- feature flag: `USE_LLM_ASSIGN=true`
- 운영 스케줄: 30분 주기
- 작업 범위: 뉴스 클러스터 배정, 통합 본문 생성, 재시도·재개 구조, 운영 스케줄 연결
- 제외 범위: KR-FinBERT-SC, 호재/악재 분류, 감성 UI

본 작업은 과거 기사 전체 백필에서 동일 클러스터의 통합 본문을 기사 추가 때마다 반복
생성하던 문제를 제거하고, 배정과 최종 통합 본문 생성을 두 단계로 분리하는 것을 목표로
진행했다. 소스 변경과 실제 데이터 처리는 수행했으며 커밋은 하지 않았다.

## 2. 최종 상태 요약

2026-07-21 마지막 확인 시점의 실제 DB 집계는 다음과 같다.

| 항목 | 결과 |
|---|---:|
| 전체 articles | 6,252건 |
| 크롤링 성공 articles | 6,120건 |
| relevant 전체 고유 기사 | 6,210건 |
| relevant 전체 연결 | 8,022 pair |
| 현재 배정 대상 고유 기사 | 6,082건 |
| 현재 배정 대상 `(article_id, stock_code)` | 7,865 pair |
| 처리 가능한 미배정 고유 기사 | 0건 |
| 처리 가능한 미배정 pair | 0건 |
| 통합 본문 `pending_retry` | 12개 클러스터 |

백필 종료 직후 신규 기사 3 pair가 추가됐으나 같은 run key로 재개해 모두 배정했다.

- 기존 클러스터 배정: 2 pair
- 신규 클러스터 생성: 1 pair
- 배정 오류: 0 pair
- 해당 재개 실행의 통합 본문 성공: 9개 클러스터
- 해당 재개 실행의 통합 본문 실패: 3개 클러스터

따라서 현재 **클러스터 배정은 100% 완료**됐으며, 남은 12개는 배정 실패가 아니라 Solar
일시 오류 등으로 통합 본문 생성 재시도를 기다리는 클러스터다.

## 3. 전체 처리 구조

```text
30분 뉴스 스케줄 시작
  -> 뉴스 검색 및 크롤링
  -> relevance 분류
  -> 미처리 relevant (article_id, stock_code) 선택
  -> 기존 classify_kind로 company / market / info 분류
  -> company
       -> 동일 stock_code, 최근 72시간 클러스터 조회
       -> BGE-M3로 유사 후보 최대 5개 검색
       -> 후보 존재: Solar로 existing/new 판정
       -> existing: 기존 cluster_id에 배정
       -> new 또는 후보 없음: 신규 클러스터 생성
       -> 오류: pending_retry 저장
  -> market/info
       -> 기존 날짜·유사도 규칙 경로로 배정 또는 생성
  -> 변경된 클러스터의 centroid/article_count/활성 시각 갱신
  -> factual_easy_v3_readable 통합 본문 생성 또는 갱신
  -> Supabase 저장
```

## 4. 자동 클러스터 생성·배정 여부

자동 생성과 자동 배정은 모두 구현되어 있다.

### 4.1 자동 실행 조건

- `NEWS_SCHEDULER_ENABLED=true`
- 스케줄 간격 30분
- `USE_LLM_ASSIGN=true`
- 백필이 실행 중이 아닐 것

현재 로드된 설정값은 scheduler 활성화, 30분 간격, batch size 50,
`USE_LLM_ASSIGN=true`다.

### 4.2 신규 company 기사

1. 아직 성공 배정되지 않은 relevant pair를 자동 선택한다.
2. 동일 종목의 최근 72시간 클러스터를 조회한다.
3. BGE-M3 centroid 유사도로 Solar에 전달할 후보를 최대 5개 선택한다.
4. Solar가 `existing`을 반환하면 지정된 기존 클러스터에 배정한다.
5. Solar가 `new`를 반환하거나 후보가 없으면 신규 클러스터를 생성한다.
6. 기존 클러스터에 추가하면 다음 값을 갱신한다.
   - `centroid`
   - `article_count`
   - `last_active_at`
   - `representative_article_id`
7. 변경된 클러스터의 통합 본문을 다시 생성한다.

### 4.3 market/info 기사

Solar 동일 사건 판정을 호출하지 않고 기존 날짜·유사도 규칙 경로를 유지한다. 규칙에
맞는 기존 클러스터가 있으면 배정하고, 없으면 신규 클러스터를 자동 생성한다.

### 4.4 오류 격리

한 기사 또는 한 클러스터의 오류가 전체 30분 작업을 중단하지 않는다. 실패 pair는
`pending_retry`로 저장하고 다음 대상 처리를 계속한다. `next_retry_at`이 지난 항목은 다음
주기에서 다시 선택된다.

## 5. 백필 최적화

### 5.1 수정 전 문제

기존 방식은 각 `(article_id, stock_code)`를 배정할 때마다 그 클러스터의
`factual_easy_v2` 통합 본문을 다시 생성했다. 같은 사건에 기사 10개가 순서대로 들어오면
통합 본문도 최대 10번 생성되어 전체 백필의 Solar 호출량이 약 13,000회 이상으로
예상됐다.

### 5.2 수정 후 2단계 방식

#### A. 클러스터 배정 단계

- 모든 미처리 pair를 발행 시각순으로 배정한다.
- 같은 stock_code 안에서는 반드시 순서를 지킨다.
- 서로 다른 stock_code는 최대 4개 worker로 제한 병렬 처리한다.
- 이 단계에서는 통합 본문을 생성하지 않는다.
- 변경된 `cluster_id`만 dirty cluster 테이블에 중복 없이 기록한다.

#### B. 최종 통합 본문 생성 단계

- 배정 단계가 끝난 뒤 dirty unique cluster만 선택한다.
- 한 클러스터에 기사가 여러 건 추가돼도 최종 상태에서 한 번만 생성한다.
- `summary_title`, `easy_explanation`, `factual_body`를 저장한다.
- 성공하면 `summary_status=success`, 실패하면 `summary_status=pending_retry`로 저장한다.

이 구조로 동일 사건 판정 호출은 유지하면서, 기사 추가마다 발생하던 중간 통합 본문
호출을 제거했다.

## 6. 멱등성, 동시 처리 방지 및 중단·재개

### 6.1 성공 pair 중복 방지

- `news_cluster_assignments(article_id, stock_code)`의 성공 상태를 확인한다.
- `news_backfill_pair_claims(article_id, stock_code)`를 DB claim으로 사용한다.
- 이미 완료된 pair는 재실행해도 Solar를 다시 호출하지 않는다.
- 여러 worker가 같은 pair를 동시에 처리할 수 없다.

### 6.2 dirty cluster 중복 방지

`news_backfill_dirty_clusters`는 `(run_key, cluster_id)`를 primary key로 사용한다. 같은
클러스터가 여러 번 변경돼도 요약 대상은 한 행만 유지된다.

### 6.3 안전한 재개

- 동일한 run key로 재실행하면 완료 pair와 성공 summary를 건너뛴다.
- 오래된 `processing` claim은 stale 처리 후 다시 claim할 수 있다.
- assignment 성공 직후 프로세스가 종료되어 dirty 기록이 누락된 경우 repair RPC가
  성공 claim에서 dirty cluster를 복원한다.
- Ctrl+C, 네트워크 단절, 프로세스 종료 후 같은 명령으로 이어서 실행할 수 있다.

재개 명령:

```bash
cd backend
USE_LLM_ASSIGN=true uv run python -m scripts.run_full_news_backfill \
  --run-key full-news-backfill-v2-20260721 \
  --workers 4 \
  --preflight-pairs 0 \
  --execute
```

## 7. API rate limit 및 장애 안전장치

- 시작 worker 수: 4개
- Solar 오류 증가 시 worker를 자동 축소
- 정상 호출이 누적되면 worker 수를 단계적으로 복구
- exponential backoff 재시도
- 연속 20회 API 실패 또는 충분한 표본에서 전체 오류율 10% 초과 시 안전 중단
- assignment 논리 상한: 실제 남은 company pair 수
- summary 논리 상한: dirty unique cluster 수
- 한 작업 실패 후 다음 pair 또는 cluster 계속 처리

마지막 재개 실행에서는 통합 본문 호출 중 일시 오류가 3회 발생해 worker가 4개에서
1개까지 자동 축소됐다. 프로세스는 중단되지 않았고 9건은 성공, 3건은
`pending_retry`로 저장된 뒤 정상 종료했다.

## 8. Supabase 저장 구조

### 8.1 `news_clusters`

- 클러스터 종목·종류와 대표 기사
- `centroid`, `article_count`
- `first_published_at`, `last_active_at`
- `summary_title`, `easy_explanation`, `factual_body`
- summary 성공·재시도 상태 및 오류

### 8.2 `news_cluster_assignments`

- pair별 배정 cluster ID
- `assigned_new`, `assigned_existing`, `pending_retry`
- 후보 수, LLM 호출 여부, 판정 이유와 오류

### 8.3 `news_backfill_pair_claims`

- 백필 worker의 pair claim
- `processing`, `completed`, `pending_retry`
- 실행 run key와 오류

### 8.4 `news_backfill_dirty_clusters`

- 백필 중 변경된 unique cluster 목록
- `dirty`, `processing`, `success`, `pending_retry`
- retry count, 다음 재시각, 마지막 오류

### 8.5 `news_backfill_runs`

- run key별 실행 상태와 체크포인트
- 진행량, 호출량, 토큰 사용량, 비용 추적값
- 백필 실행 여부를 운영 스케줄러가 확인하는 기준

## 9. 백필 실행 결과 및 호출량

- 실제 최종 배정 대상: 7,865 pair
- 처리 가능한 미배정: 0 pair
- 최종 재개 실행까지 포함한 동일 사건 판정 호출 수: 로그 재구성 기준 약 5,798회
- 통합 본문 호출 수: dirty unique cluster 및 재시도 포함 약 2,700회
- 최적화 전 예상 총 호출: 약 13,777회
- 최적화 후 실제 총 호출: 약 8,500회
- 감소량: 약 5,200회, 약 38%

여러 차례 네트워크 단절과 프로세스 재시작이 있어 초기 중단 구간의 토큰 사용량이 run
체크포인트에 모두 합산되지 않았다. DB에 확정 기록된 추적 비용은 VAT 제외
`$1.597251`이며, 누락된 초기 assignment 호출의 표본 평균을 합산한 전체 추정 비용은
약 `$2.0`이다. 비용은 확정 청구서가 아니라 애플리케이션 토큰 집계 기반 추정값이다.

## 10. 운영 경로와 백필의 관계

- 백필 실행 중에도 새 기사의 수집·크롤링·relevance 저장은 계속할 수 있다.
- 최근 실행 중인 백필 상태가 있으면 30분 스케줄러의 클러스터링 단계만 건너뛴다.
- 백필이 완료 또는 중단 상태가 되면 운영 클러스터링이 자동으로 다시 활성화된다.
- 이후 들어온 미처리 기사는 다음 주기에 자동으로 배정된다.
- 운영 경로는 백필의 지연 요약 방식을 사용하지 않는다. 신규 기사 배정 직후 변경된 해당
  클러스터의 통합 본문을 갱신한다.

## 11. UI 및 후속 검증

- `/api/clusters?limit=50`: 200 응답 확인
- 실제 브라우저에서 93개 원문 클러스터 확인
- AI 쉬운 설명: 기본 닫힘 확인
- 사건 정리: 3문단 및 문단별 핵심 문장 볼드 확인
- 원문 목록: 기본 닫힘, 펼쳤을 때 3개 표시, 더보기 시 5개씩 증가 확인
- footer: 전체 언론사 문자열 대신 `기사 93건 · 언론사 67곳`으로 축약
- `factual_easy_v3_readable` 실제 Solar smoke: JSON 파싱 성공, 3문단, 볼드 3개 확인
- 대표 cluster 69: v3 저장 및 브라우저 재조회 확인
- backend Ruff/format: 통과
- backend pytest: 37개 통과
- frontend lint/build: 통과

현재 처리 가능한 미배정 pair는 0건이며 자동 신규 클러스터 생성·기존 클러스터 배정
경로는 활성화된 상태다. 통합 본문 `pending_retry` 12개 클러스터는 다음 재시도 대상이다.

종목 시세 오류는 Toss OAuth 응답을 직접 확인한 결과 현재 핫스팟 외부 IP가 허용 목록에
없어 발생한 403이다. 애플리케이션은 이제 이 원인을 구체적으로 표시한다. 실제 시세 복구를
위해서는 Toss증권 WTS의 설정 > Open API에서 현재 서버 IP를 등록하거나 기존 허용
네트워크를 사용해야 한다.

## 12. GPT 검토 요청 항목

1. 동일 종목·72시간·BGE-M3 상위 5개 후보 정책이 과병합과 미병합을 적절히 제어하는가?
2. Solar의 `existing/new` 이진 판단과 현재 프롬프트가 동일 사건 판정에 충분한가?
3. centroid 누적 평균이 장기 사건에서 의미 drift를 만들 가능성과 개선 방법은 무엇인가?
4. pair claim과 dirty unique cluster의 멱등성 경계가 운영 장애에 충분한가?
5. 백필 2단계 요약 방식과 운영 즉시 요약 방식의 분리가 적절한가?
6. 12개 summary retry의 적체를 감시하기 위해 필요한 지표와 알림 기준은 무엇인가?
7. 현재 정확도를 유지하면서 assignment Solar 호출량을 더 낮출 방법은 무엇인가?
