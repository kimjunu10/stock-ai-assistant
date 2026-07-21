# 뉴스 클러스터링 구현 GPT 평가 자료

## 1. 문서 목적

이 문서는 현재 구현된 뉴스 운영 파이프라인, 특히 `LLMAssigner` 기반 company 뉴스
클러스터링을 외부 GPT에게 검토받기 위한 설명 자료다. 구현된 사실과 아직 검증하지 않은
부분을 분리해 적었다.

이번 작업 범위는 **운영 파이프라인 연결, Supabase 영속화, 제한적인 실제 smoke test,
UI 연결**까지다. 호재/악재 분류 모델 실험과 전체 기사 백필은 범위에서 제외했다.

## 2. 목표 처리 흐름

```text
뉴스 검색·크롤링
  -> article_id 기준 중복 방지 저장
  -> 기존 classify_kind로 company / market / info 분류
  -> company
       -> 같은 stock_code, 최근 72시간 클러스터 조회
       -> BGE-M3 유사도 상위 최대 5개 후보 선택
       -> 후보가 없으면 신규 클러스터
       -> 후보가 있으면 Solar가 동일 사건 existing/new 판정
       -> existing: 기존 클러스터 배정
       -> new: 신규 클러스터 생성
       -> Solar/파싱 오류: pending_retry 영속화
  -> market / info
       -> 기존 날짜·규칙 기반 클러스터링 유지
  -> 클러스터 생성 또는 기사 추가
       -> summarize.py로 클러스터 전체 재정리
  -> Supabase 저장
  -> 기존 뉴스 스케줄러의 다음 주기에서 재실행
```

feature flag는 `USE_LLM_ASSIGN`이며 현재 기본값은 `true`다. `false`이면 company도 기존
규칙 기반 경로를 사용할 수 있다.

## 3. company 클러스터 배정 방식

### 3.1 후보 검색

- 임베딩 모델: `BAAI/bge-m3`
- 검색 범위: 동일 `stock_code`, 동일 `kind=company`, 최근 72시간
- Solar에 전달하는 후보: cosine similarity 상위 최대 5개
- 클러스터 centroid는 소속 기사 임베딩의 누적 평균으로 갱신
- 후보 정보에는 클러스터 ID, 대표 제목, 대표 설명, 기사 수 등이 포함됨

### 3.2 Solar 판정

기존 `experiments/exp_b_factual_summaries/assign_llm.py`의 `LLMAssigner` 프롬프트와
파서를 재사용한다.

Solar의 구조화 응답은 다음 두 결정을 허용한다.

- `existing`: `matched_cluster_id`에 기존 클러스터 ID가 있어야 함
- `new`: 신규 클러스터 생성

API 오류, timeout, 빈 응답, JSON 파싱 실패, 허용되지 않은 cluster ID 반환은 정상
배정으로 취급하지 않는다. 이 경우 임의의 신규 클러스터를 만들지 않고
`pending_retry`로 저장한다.

### 3.3 market/info 경로

`market`과 `info`는 LLMAssigner를 호출하지 않는다. 기존 `market_rules.py`의 날짜 및
규칙 기반 키를 유지해 이번 변경으로 기존 경로가 바뀌지 않게 했다.

## 4. 멱등성과 중복 방지

중복 방지는 두 단계다.

1. `articles.canonical_url` unique 제약으로 동일 원문 중복 수집 방지
2. `news_cluster_assignments(article_id, stock_code)` unique 제약과
   `news_article_processing.article_id` primary key로 동일 종목 배정 재실행 방지

한 기사가 여러 종목과 관련될 수 있으므로 같은 `article_id`가 서로 다른
`stock_code`의 클러스터에 각각 배정되는 것은 정상이다. 실제 smoke에서 기사 3건이
각각 두 종목에 연결되어 총 6개 클러스터가 만들어진 이유도 이것이다.

## 5. Supabase 저장 구조

### 5.1 `news_clusters`

클러스터 단위 상태와 정리 결과를 저장한다.

- `stock_code`, `kind`
- `representative_article_id`
- `first_published_at`, `last_active_at`
- `centroid`, `article_count`
- `summary_title`, `easy_explanation`, `factual_body`
- `summary_status`, `summary_error`
- `summary_retry_count`, `summary_next_retry_at`
- `summary_prompt_version`

### 5.2 `news_cluster_assignments`

기사·종목별 배정 결과와 LLMAssigner 진단 정보를 저장한다.

- `article_id`, `stock_code`, `cluster_id`
- `status`: `assigned_new`, `assigned_existing`, `pending_retry`
- `similarity`, `candidate_cluster_ids`
- `llm_called`, `assignment_reason`, `raw_response`
- `error_code`, `retry_count`, `next_retry_at`

### 5.3 `news_article_processing`

기사 단위 파이프라인 진행 상태를 저장한다.

- `status`: `processing`, `completed`, `pending_retry`
- `kind`, `retry_count`, `next_retry_at`, `last_error`
- `started_at`, `completed_at`

### 5.4 관련 migration

- `0003_news_clustering_pipeline.sql`: 위 3개 테이블, 제약조건, 인덱스, trigger
- `0004_news_easy_explanation.sql`: 초보자용 쉬운 설명 컬럼
- `0005_article_image_url.sql`: 원문 대표 이미지 컬럼

세 migration은 현재 연결된 Supabase에 적용했다.

## 6. pending_retry 처리

### 6.1 배정 오류

동일 사건 판정이 실패하면 다음 두 곳에 오류를 남긴다.

- `news_cluster_assignments`: `status=pending_retry`, `cluster_id=NULL`
- `news_article_processing`: `status=pending_retry`

`retry_count`, `next_retry_at`, 오류 메시지를 함께 저장한다. 다음 스케줄 실행 시
`next_retry_at`이 지난 기사만 다시 처리한다. 재시도 전에는 신규 클러스터를 만들지 않는다.

프로세스가 중간에 종료돼 `processing`으로 남은 행은 일정 시간이 지나면 stale로 보고
다시 선택할 수 있다.

### 6.2 클러스터 정리 오류

기사 배정 성공과 클러스터 정리 성공은 분리한다. 정리 실패 시 클러스터와 배정은
유지하고 `news_clusters.summary_status=pending_retry`로 저장한다. 다음 스케줄 시작 시
만료된 정리 재시도를 먼저 수행한다.

## 7. 클러스터 정리와 초보자 설명

클러스터가 생성되거나 기사가 추가될 때 기존 `summarize.py`를 호출해 소속 기사 전체를
다시 정리한다. 현재 prompt version은 `factual_easy_v2`다.

저장 결과:

- `summary_title`: 사건 통합 제목
- `easy_explanation`: 초보자용 2~3문장, `~해요` 문체, 용어를 문장 안에서 설명
- `factual_body`: 가능한 경우 4~7문장의 사실 중심 사건 정리

원문이 짧으면 길이를 맞추기 위해 추측하지 않도록 프롬프트에 명시했다. 호재/악재,
매수/매도 판단은 프롬프트와 UI에서 제외했다.

## 8. 조회 API와 UI 연결

- `GET /api/clusters`: 정리 성공 클러스터와 모든 원문 반환
- `POST /api/clusters/explain-selection`: 사용자가 선택한 문구를 사건 문맥과 함께 Solar에
  보내 초보자용 설명 반환

뉴스 목록, 홈, 종목 목록, 종목 상세가 mock 데이터가 아닌 이 API를 사용한다.

UI에는 다음을 표시한다.

- 클러스터 제목, AI 쉬운 설명, 사건 정리
- 쉬운 설명 접기/펼치기
- 원문 대표 이미지, 언론사, 상대 발행 시각, 원문 제목과 설명
- 여러 원문이 있으면 원문별 카드 전체 표시
- 텍스트 선택 시 오른쪽 위 AI 설명 아이콘

감성 관련 타입은 추후 연결을 위해 optional로만 남기고 현재 렌더링하지 않는다.

## 9. 실제 데이터 및 smoke 결과

2026-07-21 Supabase 실집계:

- 전체 기사: 6,234건
- 크롤링 성공 기사: 6,102건
- relevant 고유 기사: 6,192건
- relevant `(article_id, stock_code)`: 7,994쌍
- 크롤링 성공 relevant 미처리: 고유 기사 6,060건, 연결 7,827쌍
- 미처리 예상 kind: company 6,012 / market 1,048 / info 767쌍

실제 후보가 있는 company 1쌍을 제한 실행했다. BGE 후보 1개가 Solar에 전달됐고 Solar는
`new`를 반환했다. 배정 cluster 7과 `factual_easy_v2` 통합 본문이 Supabase에 성공
저장됐다. 이어 오래된 미처리 3쌍을 작은 배치로 실행해 cluster 8~10과 통합 본문을
저장했다. 실패 및 pending_retry는 0건이다. 기존 `GET /api/clusters`에서도 네 클러스터를
조회했다.

읽기 전용 BGE 시뮬레이션에서는 미처리 company 6,015쌍 중 5,950쌍이 후보를 가져 Solar
동일사건 판정을 호출할 것으로 추정됐다. 전체 백필은 실행하지 않았다.

## 10. 자동화 검증

검증한 시나리오:

- company 첫 기사 신규 클러스터 생성
- 유사 후속 기사 `existing` 배정 및 centroid/기사 수 갱신
- Solar 오류 시 `pending_retry` 저장
- 재처리 후 기존 클러스터 정상 배정
- 오류 중 임의 신규 클러스터 미생성
- market/info에서 LLMAssigner 미호출
- 완료 article ID 재처리 방지
- 클러스터 생성/기사 추가 후 정리 갱신
- 쉬운 설명 JSON 파싱과 원문 이미지 추출
- 클러스터 API의 원문·이미지 응답

현재 결과:

- backend Ruff: 통과
- backend pytest: 35개 통과
- frontend build: 통과
- frontend lint: 통과
- `git diff --check`: 통과

## 11. 주요 구현 파일

- `app/services/news_clustering.py`: 전체 orchestration
- `app/repositories/news_clusters.py`: Supabase 조회·저장·재시도
- `app/jobs/scheduler.py`: 기존 수집 주기에 클러스터링 연결
- `experiments/exp_b_factual_summaries/assign_llm.py`: 동일 사건 Solar 판정
- `experiments/exp_b_factual_summaries/summarize.py`: 클러스터 정리와 쉬운 설명
- `app/api/routes/clusters.py`: 클러스터 조회와 선택 문구 설명 API
- `frontend/.../NewsClusterCard.tsx`: 실제 뉴스 카드 UI

## 12. GPT에게 평가받고 싶은 항목

1. 동일 종목·72시간·BGE 상위 5개 후보 전략이 과병합/미병합 위험을 적절히 줄이는가?
2. centroid 누적 평균 방식이 사건이 길게 이어질 때 의미 drift를 일으킬 가능성이 큰가?
3. Solar 오류 시 신규 클러스터를 만들지 않고 retry하는 정책이 운영상 적절한가?
4. 기사 단위와 기사·종목 단위 멱등성 경계가 충분한가?
5. 배정 성공과 정리 성공의 retry 상태를 분리한 구조가 일관적인가?
6. scheduler 한 프로세스 내 순차 실행이 장애 격리와 처리량 측면에서 충분한가?
7. BGE 후보 발생률 98.9%와 예상 Solar 호출량을 낮추면서 recall을 지킬 방법은 무엇인가?
8. 쌍 단위 체크포인트·호출 상한·비용 상한이 장시간 백필 재개에 충분한가?

## 13. 아직 하지 않은 작업

- 전체 미처리 7,827쌍 백필
- 호재/악재 분류 모델 실험 및 UI 표시
- 대량 처리 성능·비용 측정
- retry 적체 모니터링 대시보드와 운영 알림

위 항목은 현재 구현 완료로 간주하면 안 된다.
