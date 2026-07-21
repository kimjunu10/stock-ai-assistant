# LLMAssigner 운영 뉴스 파이프라인 연결 정리

## 1. 문서 목적

이 문서는 실험 단계에서 구현된 `LLMAssigner`를 실제 뉴스 수집 스케줄러에 연결한
작업을 설명한다. 다른 GPT나 개발자가 현재 작업 트리를 이어받아 코드 리뷰, Supabase
마이그레이션 적용, 실제 API smoke test를 진행할 수 있도록 구현 의도와 데이터 계약을
함께 기록한다.

이번 작업 범위는 다음과 같다.

- 뉴스 크롤링 이후 클러스터링 파이프라인 연결
- `classify_kind` 기반 company/market/info 라우팅
- company 기사에 대한 BGE-M3 후보 검색 및 Solar 동일 사건 판정
- 클러스터 생성·기사 추가 후 기존 `summarize.py` 요약 갱신
- Supabase 저장 구조와 `pending_retry` 영속화
- 기존 스케줄러 연결과 mock 기반 smoke test
- `USE_LLM_ASSIGN` feature flag 유지

호재/악재 또는 감성 분류 모델 실험은 이번 작업에 포함하지 않았고 관련 코드를
변경하지 않았다. 커밋도 생성하지 않았다.

## 2. 최종 처리 흐름

```text
기존 APScheduler 뉴스 수집 주기
  └─ Naver 뉴스 검색 및 articles/article_stocks upsert
      └─ 기사 본문 크롤링
          └─ 기존 종목 relevance 판정
              └─ 처리 대상 relevant 기사 조회
                  └─ article_id 단위 처리 상태 기록
                      └─ classify_kind(title, description)
                          ├─ company
                          │   └─ BGE-M3 title+description 임베딩
                          │       └─ 같은 stock_code, 최근 72시간 클러스터 조회
                          │           └─ cosine 후보 최대 5개 선택
                          │               ├─ 후보 없음 → 신규 클러스터
                          │               ├─ Solar existing → 기존 클러스터
                          │               ├─ Solar new → 신규 클러스터
                          │               └─ 오류/잘못된 응답 → pending_retry
                          ├─ market
                          │   └─ 기존 동일 거래일 + cosine 규칙 경로
                          └─ info
                              └─ 기존 동일 거래일 + cosine 규칙 경로
                                  └─ 배정 결과 Supabase 저장
                                      └─ 클러스터 단위 summarize.py 실행
                                          └─ 기사 처리 완료 또는 재시도 저장
```

스케줄러 연결 지점은 `app/jobs/scheduler.py`의
`run_news_collection_cycle()`이다. 기존 relevance 판정 직후
`NewsClusteringService.process_pending()`이 호출된다.

## 3. 분류 및 배정 정책

### 3.1 공통 분류

모든 기사는 기존
`experiments.exp_b_factual_summaries.market_rules.classify_kind()`로 다음 중 하나로
분류된다.

- `company`: 기업 고유 사건
- `market`: 시장 전반 시황
- `info`: 비사건형 투자 정보

분류 우선순위와 패턴은 기존 구현을 그대로 사용한다.

### 3.2 company 경로

1. 기사 제목과 description을 공백으로 연결한다.
2. 고정 revision의 `BAAI/bge-m3`로 L2 정규화된 임베딩을 생성한다.
3. Supabase에서 같은 `stock_code`와 `kind=company`이며 기사 발행 시각 기준 최근
   72시간 안에 활성화된 클러스터를 조회한다.
4. 기존 `LLMAssigner`가 centroid cosine 유사도를 계산하고 최소 유사도 0.55 이상인
   후보를 최대 5개까지 선택한다.
5. 후보가 없으면 Solar를 호출하지 않고 신규 클러스터를 만든다.
6. 후보가 있으면 최초 anchor 기사들을 Solar에 한 번 전달한다.
7. 응답이 `existing`이고 후보 목록에 실제로 존재하는 ID이면 기존 클러스터에 붙인다.
8. 응답이 `new`이면 신규 클러스터를 만든다.
9. 통신 오류, timeout, JSON 오류, 필수 필드 누락, 후보에 없는 ID 등은 모두
   `pending_retry`로 남긴다. 이 경우 클러스터를 만들거나 기사 배정을 확정하지 않는다.

### 3.3 market/info 경로

market과 info는 `LLMAssigner`나 Solar 동일 사건 판정을 호출하지 않는다.

- 같은 `stock_code`
- 같은 `kind`
- 같은 거래일
- 최근 72시간
- cosine similarity 0.74 이상

조건을 만족하는 최적 클러스터가 있으면 기존 클러스터에 추가하고, 없으면 신규
클러스터를 만든다. market/info가 company 클러스터의 연결 다리 역할을 하지 않도록
종류별로 완전히 분리한다.

## 4. USE_LLM_ASSIGN feature flag

운영 설정은 Pydantic `Settings`의 `use_llm_assign`이며 환경변수 이름은
`USE_LLM_ASSIGN`이다.

```env
USE_LLM_ASSIGN=false
NEWS_EMBEDDING_DEVICE=cpu
```

- `true`: company 후보가 있으면 Solar 동일 사건 판정 사용
- `false`: company 기사도 기존 cosine 0.74 거리 기반 배정 사용
- market/info 경로에는 영향 없음

현재 운영 기본값은 `true`이며, 즉시 롤백이 필요하면 `false`로 바꿀 수 있다. Solar 배정과 클러스터 요약에는
`UPSTAGE_API_KEY`가 사용된다.

## 5. BGE-M3 로딩 방식

`BgeM3Embedder`는 `sentence-transformers`를 함수 내부에서 지연 import한다. 모델은
`(model_name, revision, device)` 키로 프로세스 안에서 캐시하므로 스케줄 주기마다 모델을
다시 로드하지 않는다.

고정값은 기존 실험 설정을 그대로 사용한다.

- 모델: `BAAI/bge-m3`
- revision: `5617a9f61b028005a4858fdac845db406aefb181`
- 입력: `title + " " + description`
- 출력: L2 정규화된 1024차원 벡터

운영 의존성으로 `numpy`와 `sentence-transformers`를 추가했으며 `uv.lock`을
갱신했다.

## 6. Supabase 저장 구조

DDL은 `backend/migrations/0003_news_clustering_pipeline.sql`에 있다. 이 migration은
2026-07-20에 현재 설정된 Supabase에 적용했다.

### 6.1 news_clusters

클러스터 자체의 현재 상태를 저장한다.

| 주요 컬럼 | 의미 |
| --- | --- |
| `id` | 전역 클러스터 ID |
| `stock_code` | 클러스터 종목 코드 |
| `kind` | company/market/info |
| `anchor_article_id` | Solar 판정용 최초 고정 기사 |
| `representative_article_id` | UI용 대표 기사 |
| `centroid` | 정규화 임베딩 centroid 배열 |
| `article_count` | 소속 기사 수 |
| `first_published_at` | 최초 기사 발행 시각 |
| `last_active_at` | 마지막 추가 기사 발행 시각 |
| `clustering_version` | 클러스터링 버전 |
| `summary_title` | 통합 사실 제목 |
| `factual_body` | 통합 사실 본문 |
| `summary_status` | pending/success/pending_retry |
| `summary_retry_count` | 요약 재시도 횟수 |
| `summary_next_retry_at` | 다음 요약 재시도 시각 |

### 6.2 news_cluster_assignments

기사와 종목별 클러스터 배정을 저장한다. 기본키는
`(article_id, stock_code)`다. 하나의 기사가 여러 종목에 relevant일 수 있기 때문에
종목별 배정은 분리하되, 전체 기사 처리는 `article_id` 단위로 관리한다.

| 주요 컬럼 | 의미 |
| --- | --- |
| `article_id`, `stock_code` | 배정의 복합 기본키 |
| `cluster_id` | 성공 시 배정 클러스터, 재시도 시 NULL |
| `kind` | company/market/info |
| `status` | assigned_new/assigned_existing/pending_retry |
| `llm_called` | Solar 동일 사건 판정 호출 여부 |
| `candidate_count` | LLMAssigner 후보 수 |
| `assignment_reason` | 배정 근거 문자열 |
| `error_code` | transport_error/invalid_response 등 |
| `prompt_version` | 동일 사건 프롬프트 버전 |
| `retry_count` | 배정 재시도 횟수 |
| `next_retry_at` | 다음 배정 재시도 시각 |

DB check constraint로 `pending_retry`이면 `cluster_id IS NULL`과
`next_retry_at IS NOT NULL`을 강제한다. 성공 상태이면 반대로 실제 `cluster_id`가
필수다.

### 6.3 news_article_processing

`article_id` 기준 중복 처리 방지와 전체 상태를 저장한다.

| 주요 컬럼 | 의미 |
| --- | --- |
| `article_id` | 기본키이자 처리 멱등성 키 |
| `kind` | classify_kind 결과 |
| `status` | processing/completed/pending_retry |
| `retry_count` | 기사 전체 재시도 횟수 |
| `next_retry_at` | 다음 처리 시각 |
| `last_error` | 종목별 오류를 합친 마지막 오류 |
| `started_at`, `completed_at` | 처리 시작/완료 시각 |

한 기사가 여러 종목에 연결된 경우 하나의 기사 처리 안에서 종목별로 각각 배정한다.
일부 종목만 실패하면 기사 전체 상태는 `pending_retry`가 되지만, 다음 재처리에서는 이미
성공한 `(article_id, stock_code)` 배정을 건너뛰고 실패한 종목만 다시 처리한다.

## 7. pending_retry 처리 방식

### 7.1 동일 사건 배정 실패

Solar 오류가 발생하면 다음 두 위치에 상태가 남는다.

1. `news_cluster_assignments`
   - `status=pending_retry`
   - `cluster_id=NULL`
   - `error_code`, `assignment_reason`, `retry_count`, `next_retry_at` 저장
2. `news_article_processing`
   - `status=pending_retry`
   - `last_error`, `retry_count`, `next_retry_at` 저장

다음 스케줄 실행에서 `next_retry_at`이 지난 기사만 다시 선택한다. 기존
`LLMAssigner` 정책대로 실패한 article ID는 성공 처리된 것으로 간주하지 않는다.

예상치 못한 프로세스 종료로 `processing`에 남은 행도 30분이 지나면 stale로 보고 다시
선택할 수 있다.

### 7.2 요약 실패

배정 성공 여부와 요약 성공 여부는 분리한다. 요약 호출 실패 또는 JSON 검증 실패 시
클러스터는 유지하고 다음 값을 저장한다.

- `summary_status=pending_retry`
- `summary_error`
- `summary_retry_count`
- `summary_next_retry_at`

다음 스케줄 시작 시 만료된 요약 재시도 클러스터를 먼저 처리한다.

## 8. 클러스터 요약 갱신

신규 클러스터가 생성되거나 기존 클러스터에 기사가 추가될 때마다 다음 순서로 기존
`experiments.exp_b_factual_summaries.summarize.py`를 호출한다.

1. 성공 배정된 클러스터 기사 조회
2. 최대 12개 기사를 발행/배정 순서로 구성
3. `summarize.build_user_prompt()` 호출
4. `summarize.call_solar()` 호출
5. `summary_title`, `easy_explanation`, `factual_body`, prompt version과 상태 저장

현재 prompt version은 `factual_easy_v2`다. 호재/악재 등 투자 판단은 생성하지 않는다.

## 8.1 전체 백필과 중단·재개

백필의 처리량 기준은 기사 수가 아니라 `(article_id, stock_code)`다. 성공한 배정은
`news_cluster_assignments`의 복합키와 성공 상태를 기준으로 건너뛰므로 같은 명령을 다시
실행해도 남은 쌍부터 이어진다. `news_backfill_runs`에는 실행 상태, 마지막 성공 기사·종목,
처리 쌍 수, 호출 수, 토큰, 비용, 적용 상한을 저장한다.

안전장치는 실행당 batch size, 동일사건 판정/통합 본문 호출 수 상한, 실행당·일일 비용
상한, Solar 호출 간격, 진행률 로그, SIGINT 체크포인트다. `--all`은
`--approve-full-backfill`을 함께 지정해야만 동작한다.

```bash
cd backend
USE_LLM_ASSIGN=true uv run python -m scripts.backfill_news_clusters --inventory
USE_LLM_ASSIGN=true uv run python -m scripts.backfill_news_clusters \
  --execute --batch-size 25 --run-key relevant-news-v1
```

`backend/migrations/0006_news_backfill_runs.sql`은 현재 Supabase에 적용했다.

## 9. 변경 파일과 역할

| 파일 | 역할 |
| --- | --- |
| `.gitignore` | 신규 0003 migration만 Git 변경으로 노출 |
| `backend/.env.example` | USE_LLM_ASSIGN 및 임베딩 device 예시 |
| `backend/app/core/config.py` | 배치 크기, 재시도 간격, device, feature flag 설정 |
| `backend/app/jobs/scheduler.py` | 기존 뉴스 수집 주기에 클러스터 처리 연결 |
| `backend/app/repositories/news_clusters.py` | Supabase 조회/저장/재시도 저장소 |
| `backend/app/services/news_clustering.py` | 분류, 임베딩, 배정, 요약 orchestration |
| `backend/migrations/0003_news_clustering_pipeline.sql` | 신규 3개 테이블, 제약조건, 인덱스, trigger |
| `backend/tests/unit/test_news_clustering_smoke.py` | 운영 연결 mock smoke test |
| `backend/pyproject.toml` | BGE-M3 운영 의존성 추가 |
| `backend/uv.lock` | 의존성 lock 갱신 |

재사용하는 기존 구현은 다음과 같다.

- `backend/experiments/exp_b_factual_summaries/assign_llm.py`
- `backend/experiments/exp_b_factual_summaries/market_rules.py`
- `backend/experiments/exp_b_factual_summaries/summarize.py`
- `backend/experiments/exp_b_factual_summaries/config.py`

## 10. smoke test 결과

실제 Supabase나 Solar를 변경하지 않도록 repository, BGE-M3, Solar 응답을 mock한 연결
smoke test를 실행했다.

검증한 시나리오는 다음과 같다.

- company 첫 기사 신규 클러스터 생성
- 유사 company 후속 기사 Solar `existing` 배정
- 클러스터 생성 및 기사 추가 후 요약 갱신
- Solar 통신 실패 시 배정 없는 `pending_retry` 저장
- 재실행 시 기존 클러스터로 정상 복구
- pending_retry 동안 임의 신규 클러스터가 생기지 않음
- market 기사가 LLMAssigner를 호출하지 않고 규칙 경로 사용
- 완료된 article ID가 다음 실행에서 다시 처리되지 않음
- 기존 LLMAssigner 회귀 동작 유지

최종 결과(2026-07-21):

```text
Ruff: 통과
전체 backend tests: 35 passed
git diff --check: 통과
```

## 11. 실제 DB 집계와 제한 실행 결과

2026-07-21 최종 집계는 전체 기사 6,234건, 크롤링 성공 6,102건, relevant 고유 기사
6,192건, relevant 연결 7,994쌍이다. 크롤링 성공 relevant 중 미처리는 고유 기사
6,060건, `(article_id, stock_code)` 7,827쌍이다. 미처리 쌍의 예상 kind는 company
6,012, market 1,048, info 767이다.

실제 후보가 있는 company 1쌍을 선택해 Solar를 호출했다. 후보 1개에 대해 `new`가
반환돼 cluster 7을 생성했고, `factual_easy_v2` 저장까지 성공했다. 이어 발행 순서상
오래된 3쌍만 처리해 cluster 8~10을 생성했다. 이 3쌍은 후보가 없어 동일사건 Solar는
호출하지 않았고 통합 본문 3회만 호출했다. 네 쌍 모두 오류와 pending_retry는 없었다.

전체 백필은 실행하지 않았다.

## 12. 실제 뉴스 UI 연결

백엔드 `GET /api/clusters`가 요약 완료 클러스터와 소속 원문을 반환한다. 프런트의
뉴스 목록, 종목 상세 뉴스, 홈 주요 사건, 종목 목록 최근 뉴스가 이 API를 사용한다.

카드는 다음 정보를 표시한다.

- 종목과 클러스터 최신 시각
- Solar 통합 제목과 사실 본문
- 클러스터 기사 수와 언론사 목록
- 대표 이미지·언론사·상대 시각·제목·설명을 포함한 원문 카드 목록
- 뉴스 정리 복사 버튼

호재/악재 배지, 감성 점수, 감성 근거, 감성 필터는 렌더링하지 않는다. 이후 분류 모델
응답이 추가되면 optional 필드에 연결할 수 있도록 타입과 카드 조건부 렌더링만 남겼다.

후속 UI 개선으로 다음 기능을 추가했다.

- `0004_news_easy_explanation.sql`: 초보자용 `easy_explanation` 저장 컬럼
- 제목 아래 `AI 쉬운 설명`, 그 아래 긴 `사건 정리`의 2단 구성
- `AI 쉬운 설명`은 기본으로 열리고 사용자가 접거나 다시 펼칠 수 있음
- 사건 정리는 가능한 범위에서 4~7문장, 쉬운 설명은 2~3문장 `~해요` 말투
- 뉴스 텍스트를 선택하면 마지막 선택 영역의 오른쪽 위 꼭짓점에 AI 아이콘 표시
- 노란 쉬운 설명 영역에서도 구분되도록 텍스트 선택 색상을 밝은 파란색으로 통일
- 아이콘 클릭 시 `/api/clusters/explain-selection`이 선택 문구와 사건 문맥을 Solar에 전달
- 반환된 설명을 카드 안 작은 팝오버로 표시
- `0005_article_image_url.sql`: 원문 대표 이미지 저장 컬럼
- 크롤러가 `og:image`, `og:image:url`, `twitter:image` 순서로 대표 이미지를 수집
- 대표 이미지가 없거나 로드에 실패하면 언론사 사이트 파비콘을 사용
- 한 클러스터에 원문이 여러 개면 모든 원문을 각각 카드로 표시

기존 smoke 클러스터 6개는 `factual_easy_v2`로 재생성했으며, 쉬운 설명 110~241자,
사건 정리 293~651자로 DB에 저장됐다. 원문의 정보가 부족할 때는 길이를 맞추기 위해
추측하지 않도록 프롬프트에 명시했다.

실제 브라우저에서 Supabase의 6개 클러스터 렌더링, 쉬운 설명 접기/펼치기, 첫 카드
원문 카드 펼침을 검증했다. 현재 smoke 원문 3건은 대표 이미지 백필도 완료했다.

## 13. 이후 운영 단계

1. 다음 스케줄에서 유사 후보가 있는 company 기사를 처리해 Solar `existing/new`
   판정 결과를 추가 검증한다.
2. `news_cluster_assignments`, `news_article_processing`, `news_clusters.summary_status`의
   pending_retry 적체를 모니터링한다.
3. 운영 안정화 이후 호재/악재 분류 모델을 별도 작업으로 연결한다.

호재/악재 분류 실험은 위 운영 연결이 안정화된 이후 별도 작업으로 시작해야 한다.
