# RAG_IMPLEMENTATION_SPEC.md

## 0. 문서 목적

이 문서는 `stock-ai-assistant` 저장소에 **발표용 RAG 기능을 실제로 구현하기 위한 최종 실행 명세서**다.

Claude Code 또는 Codex는 이 문서를 처음부터 끝까지 읽고, 아래 단계와 중단 조건을 지키며 구현한다.

이 문서의 목표는 다음 두 가지다.

1. 주식 초보자가 뉴스·공시·리포트·재무·주가를 쉽게 질문할 수 있게 한다.
2. 정확한 숫자는 검색으로 추측하지 않고, 공식 DB·시장 데이터·리포트 표에서 정확히 가져온다.

---


# 0.1 현재 데이터 상태 — 구현 시작 기준

이 상태를 구현의 출발점으로 사용한다. 존재하지 않는 데이터를 이미 Supabase에 있다고 가정하면 안 된다.

## Supabase에 이미 존재하는 데이터

- 뉴스 원문과 뉴스 사건 클러스터
- 뉴스 요약 결과
- DART 원문과 구조화 공시
- 기존 재무 데이터
- 그 밖의 현재 프로젝트 DB 데이터

정확한 테이블명과 컬럼은 Phase 0에서 실제 스키마를 다시 확인한다.

## 토스증권 주가 데이터

- 토스증권 API를 사용하기 위한 키 또는 설정은 환경에 들어가 있다.
- 아직 실제 주가 데이터 수집 작업을 실행하지 않았다.
- 현재 Supabase에는 토스증권에서 받아온 주가 이력 데이터가 저장되어 있지 않다.
- 기존 코드에 연동 흔적이 있더라도 실제 호출 가능 여부와 지원 범위는 Phase 0에서 확인한다.

따라서 주가 기능은 기존 저장 데이터를 조회하는 기능으로 가정하지 않는다.

MVP 기본 방향:

```text
현재가·기간 시세 요청
→ 토스증권 API에서 필요할 때 조회
→ 백엔드에서 계산
→ 짧은 TTL 캐시
```

장기 주가 이력 테이블은 발표용 기능에 꼭 필요한 경우에만 추가한다.  
토스증권 API가 사건 전후 과거 시세를 제공하지 않는다면 임의 구현하지 말고 지원 범위와 대안을 보고한다.

## 증권사 리포트

- 리포트 PDF 원본은 현재 로컬 파일로만 존재한다.
- 아직 Supabase Storage에 업로드하지 않았다.
- 리포트 메타데이터, 페이지, 표, 검색 청크도 아직 Supabase에 없다.
- Phase 5에서 로컬 폴더를 입력으로 받아 비공개 Storage 업로드, 파싱, DB 저장, 임베딩을 순서대로 수행한다.
- 업로드 완료 후에도 로컬 원본을 자동 삭제하지 않는다.


# 1. 구현 원칙

## 1.1 반드시 지킬 원칙

- 기존 뉴스 수집·클러스터링·DART 수집 기능을 깨지 않는다.
- 기존 테이블을 추측해 이름이나 컬럼을 변경하지 않는다.
- 신규 RAG 테이블은 `rag_` 또는 `research_` 접두사를 사용한다.
- `.env`, API 키, 서비스 역할 키를 코드·로그·테스트 결과에 출력하지 않는다.
- 마이그레이션 전 실제 Supabase 스키마를 다시 확인한다.
- 마이그레이션 전 백업 또는 복구 가능한 상태를 확인한다.
- 정확한 숫자는 LLM이 계산하거나 문서 조각에서 임의로 복사하게 두지 않는다.
- 실제값, 공식 발표값, 증권사 예상값, 뉴스 해석을 답변에서 구분한다.
- 문서 근거가 없으면 모른다고 답한다.
- 매수·매도 추천과 확정적 주가 예측을 하지 않는다.
- 현재 보고 있는 뉴스·공시·리포트가 있으면 그 문서를 우선한다.
- 구현은 한 단계씩 진행하고, 각 단계 테스트를 통과한 뒤 다음 단계로 이동한다.

## 1.2 중단 조건

다음 상황에서는 자동으로 임의 결정하지 말고 작업을 중단한 뒤 보고한다.

- Upstage 문서용·질문용 임베딩 출력 차원이 1024가 아닌 경우
- 현재 사용 가능한 Upstage 모델명이 사전 점검 결과와 다른 경우
- 기존 DB에 동일 목적의 RAG 테이블이나 검색 함수가 이미 존재하는 경우
- 기존 테이블의 실제 컬럼이 이 명세에서 예상한 데이터 역할과 맞지 않는 경우
- 전체 PDF 처리 예상 비용이 설정한 제한을 넘는 경우
- 마이그레이션 적용 후 기존 API 테스트가 실패하는 경우
- 리포트 원본의 저장 또는 외부 문서 분석 전송이 권한·약관상 불가능한 경우

---

# 2. 최종 아키텍처

이 프로젝트의 RAG는 단순 벡터 검색 하나가 아니다.

정확한 명칭은 다음과 같다.

> **문맥 우선·도구 결합형 하이브리드 RAG**

구성은 다음과 같다.

```text
사용자 질문
   ↓
현재 화면 문맥과 종목 확인
   ↓
필요 작업 결정 — 여러 작업을 동시에 선택 가능
   ├─ 재무·공시 숫자 조회
   ├─ 금융 용어 조회
   ├─ 주가·거래량 조회
   └─ 뉴스·공시·리포트 하이브리드 검색
   ↓
결과 통합
   ↓
출처 중복 제거·공식 자료 우선·현재 문서 우선
   ↓
Solar 스트리밍 답변
   ↓
문장별 인용 번호 + 출처 카드
```

## 2.1 사용하지 않는 구조

MVP에서는 다음을 사용하지 않는다.

- LangChain 전체 프레임워크
- LangGraph
- 여러 에이전트가 반복 검색하는 Agentic RAG
- 답변마다 PDF를 다시 파싱하는 방식
- 답변마다 별도 LLM 재정렬 호출
- 차트 이미지에서 정확한 숫자를 추측하는 방식

이유는 2주 일정, 3~4초 응답 목표, 10만원 이내 비용 때문이다.

## 2.2 현재 구조와 향후 확장 구조 구분

> 이 절은 **향후 계획**이다. 아래 "현재 구조"만 구현되어 있고,
> "향후 확장 구조(Tool Registry / 제한형 Agentic / MCP / A2A)"는 **아직 미구현**이다.
> Agentic·MCP·A2A를 완료된 기능처럼 서술하거나 사용하지 않는다.

### 현재 구조 (구현 완료)

- LangChain·LangGraph 없이 **직접 구현한 결정론적 하이브리드 RAG**.
- 질문 계획(§9)은 규칙 기반 라우터로, LLM 호출 없이 신호어로 필요한 작업을 결정한다.
- 필요한 조회(재무·용어·주가·하이브리드 검색)를 병렬 실행 후 결과를 통합한다.
- 반복 검색 루프·에이전트 간 협상·동적 도구 선택 LLM 호출이 없다(결정론적).

### 향후 확장 구조 (미구현, 계획)

확장은 현재 결정론적 경로를 **대체하지 않고 감싸는** 방식으로 도입한다.

1. **Extension A — 공통 읽기 전용 Tool 인터페이스 (Tool Registry)**
   - 기존 서비스(FactsService, 하이브리드 검색, 용어 조회, 향후 주가·리포트)를
     동일한 read-only Tool 시그니처로 추상화한다.
   - 라우터와 (향후) Agent가 같은 Tool 목록을 공유한다. 부작용(쓰기) 없는 조회만 노출.

2. **Extension B — 제한형 Agentic Orchestrator**
   - **복합·다단계 질문에만** 제한적으로 적용한다(단순 질문은 기존 결정론적 라우터 유지).
   - 최대 호출 횟수·시간 상한을 두고, **실패·시간 초과 시 기존 라우터로 fallback**한다.
   - Agent는 Tool Registry의 read-only Tool만 사용한다.

3. **Extension C — MCP 서버 공개**
   - 동일한 Tool을 MCP 서버로 노출해 외부(또는 다른 런타임)에서 재사용 가능하게 한다.
   - 내부 구현(직접 함수 호출)과 MCP 노출은 같은 Tool 정의를 공유한다.

4. **Extension D — A2A PoC**
   - 필요성과 일정이 확인되면 **Fact Agent**(정확 숫자·공시)와
     **Research Agent**(뉴스·리포트 설명)를 분리한 A2A(agent-to-agent) PoC를 구현한다.
   - PoC 단계로만 두고, 확정 전까지 프로덕션 경로에 넣지 않는다.

각 확장의 실행 단계는 `RAG_PHASE_EXECUTION_PLAN.md`의 Extension A~D를 따른다.

---

# 3. 확정 기술 선택

## 3.1 백엔드

- 기존 FastAPI 구조 유지
- Python 3.11 이상
- Supabase Python SDK 유지
- Upstage API는 `httpx.AsyncClient`로 직접 호출
- 스트리밍은 FastAPI `StreamingResponse`
- 검색과 DB 조회는 비동기로 병렬 실행

## 3.2 데이터베이스

- Supabase PostgreSQL
- `pgvector`
- `pg_trgm`
- 벡터: `extensions.vector(1024)`
- 벡터 거리: cosine
- 벡터 인덱스: HNSW
- 한국어 키워드 검색: `pg_trgm` 기반
- 최종 검색 결합: RRF, Reciprocal Rank Fusion

## 3.3 임베딩

사전 점검에서 확인한 값을 기본값으로 사용한다.

```env
UPSTAGE_EMBEDDING_QUERY_MODEL=solar-embedding-2-query
UPSTAGE_EMBEDDING_PASSAGE_MODEL=solar-embedding-2-passage
UPSTAGE_EMBEDDING_DIMENSION=1024
```

구현 전 다음을 실제 API로 검증한다.

- 문서 모델과 질문 모델이 모두 호출되는지
- 두 모델의 출력 길이가 모두 1024인지
- 동일 벡터 공간에서 cosine 검색이 가능한지
- 입력 길이 제한과 배치 제한

검증 실패 시 DB 마이그레이션을 진행하지 않는다.

## 3.4 생성 모델

정확한 채팅 모델명은 코드에 고정하지 않는다.

```env
UPSTAGE_CHAT_MODEL=<현재 콘솔에서 사용 가능한 스트리밍 모델>
```

구현자는 현재 계정에서 사용 가능한 모델을 확인해 환경변수로 설정한다.

필수 조건:

- 한국어 답변 품질
- 스트리밍 지원
- 시스템 지시 준수
- 제공된 인용 번호만 사용 가능
- 3~4초 목표에 맞는 응답 속도

## 3.5 PDF 처리

### 기본 경로

- 원본 PDF: 비공개 Supabase Storage
- 기본 파서: Upstage Document Parse
- OCR 필요 PDF: Upstage OCR 또는 Document Parse의 OCR 경로
- 로컬 대체 경로: PyMuPDF/PyMuPDF4LLM

### 선택 기준

먼저 대표 PDF 10개로 시험한다.

- 본문 중심
- 표 중심
- 차트 중심
- 스캔형
- 여러 증권사 형식

Upstage Document Parse를 기본으로 사용하되 다음 비용 제한을 적용한다.

```text
대표 10개 실제 비용 측정
→ 전체 244개 예상 비용 계산
→ PDF 전처리 총 예상 비용이 30,000원을 넘으면
   텍스트형 PDF는 로컬 처리
   표·OCR이 필요한 PDF만 Upstage 사용
```

모든 PDF를 사용자 질문 시점에 파싱하지 않는다. 배치로 한 번만 처리한다.

---

# 4. 저장소 현재 구조에 맞춘 구현 위치

현재 저장소는 아래 RAG 파일이 자리만 존재하는 상태다.

```text
backend/app/rag/chunking.py
backend/app/rag/indexing.py
backend/app/rag/prompting.py
backend/app/rag/retrieval.py
backend/app/api/routes/qa.py
```

이 파일을 중심으로 구현한다.

## 4.1 새로 생성할 백엔드 파일

```text
backend/app/rag/models.py
backend/app/rag/routing.py
backend/app/rag/answering.py
backend/app/rag/report_parser.py
backend/app/rag/normalization.py
backend/app/rag/upstage_client.py

backend/app/repositories/rag.py
backend/app/repositories/reports.py
backend/app/repositories/terms.py
backend/app/repositories/price_queries.py

backend/app/services/qa.py
backend/app/services/rag_ingestion.py

backend/app/schemas/qa.py
backend/app/schemas/reports.py

backend/scripts/rag_preflight.py
backend/scripts/index_news_rag.py
backend/scripts/index_dart_rag.py
backend/scripts/import_research_reports.py
backend/scripts/index_financial_terms.py
backend/scripts/evaluate_rag.py
```

## 4.2 수정할 파일

```text
backend/app/core/config.py
backend/app/api/router.py
backend/app/api/routes/qa.py
backend/app/api/routes/reports.py
backend/app/rag/chunking.py
backend/app/rag/indexing.py
backend/app/rag/prompting.py
backend/app/rag/retrieval.py
backend/pyproject.toml
backend/.env.example
```

## 4.3 프런트엔드

```text
frontend/kakao-stock-frontend/src/api/qa.ts
frontend/kakao-stock-frontend/src/types/qa.ts
frontend/kakao-stock-frontend/src/hooks/useQaStream.ts
```

기존 AI 질문 패널과 `/ask` 화면의 실제 컴포넌트 위치를 확인한 뒤 연결한다. UI를 새로 전면 재작성하지 않는다.

---

# 5. 환경변수

`backend/.env.example`에 추가한다. 실제 값은 커밋하지 않는다.

```env
# Upstage
UPSTAGE_API_KEY=
UPSTAGE_CHAT_MODEL=
UPSTAGE_EMBEDDING_QUERY_MODEL=solar-embedding-2-query
UPSTAGE_EMBEDDING_PASSAGE_MODEL=solar-embedding-2-passage
UPSTAGE_EMBEDDING_DIMENSION=1024
UPSTAGE_DOCUMENT_PARSE_MODEL=

# RAG
RAG_ENABLED=true
RAG_MAX_CONTEXT_CHUNKS=8
RAG_SEMANTIC_CANDIDATES=24
RAG_LEXICAL_CANDIDATES=24
RAG_RRF_K=50
RAG_MAX_CHUNKS_PER_DOCUMENT=2
RAG_CONTEXT_CHAR_BUDGET=12000
RAG_MAX_OUTPUT_TOKENS=700
RAG_LOG_QUERIES=true

# PDF
REPORT_LOCAL_DIR=
REPORT_STORAGE_BUCKET=research-reports-private
REPORT_PARSE_COST_LIMIT_KRW=30000
REPORT_SIGNED_URL_TTL_SECONDS=60
REPORT_PUBLIC_PREVIEW_ENABLED=false

# Price
PRICE_CACHE_TTL_SECONDS=30
```

`UPSTAGE_CHAT_MODEL`, `UPSTAGE_DOCUMENT_PARSE_MODEL`은 현재 계정에서 확인 후 설정한다. 추측한 기본값을 넣지 않는다.

---

# 6. 데이터베이스 마이그레이션

기존 마이그레이션 이후 번호를 사용한다.

```text
0012_rag_core.sql
0013_research_reports.sql
0014_rag_hybrid_search.sql
0015_rag_rls_storage.sql
```

## 6.1 확장 기능

```sql
create extension if not exists vector with schema extensions;
create extension if not exists pg_trgm with schema extensions;
```

## 6.2 `rag_documents`

검색 대상 원본의 버전과 출처를 관리한다.

필수 컬럼:

```text
id uuid primary key
source_type text
source_pk text
stock_code text null
title text
publisher text null
published_at timestamptz null
source_url text null
storage_bucket text null
storage_path text null
content_hash text
parser_name text
parser_version text
chunking_version text
embedding_model text
embedding_dimension integer
metadata jsonb
is_current boolean
created_at timestamptz
updated_at timestamptz
```

허용 `source_type`:

```text
news_event
dart_document
research_report
financial_term
```

제약:

- `stock_code`는 null 또는 6자리 숫자
- `(source_type, source_pk, content_hash)` unique
- 같은 `(source_type, source_pk)`에서 `is_current=true`는 하나만 허용
- 원본 삭제 시 검색 문서가 자동 삭제되지 않도록 직접 FK를 걸지 않거나 `on delete restrict`

## 6.3 `rag_sections`

큰 문맥 단위다.

```text
id uuid primary key
document_id uuid
section_order integer
heading_path text[]
section_type text
page_start integer null
page_end integer null
content text
content_hash text
metadata jsonb
created_at timestamptz
```

`section_type` 예:

```text
summary
narrative
table
correction_delta
figure_caption
term_definition
```

## 6.4 `rag_chunks`

실제 검색 단위다.

```text
id uuid primary key
document_id uuid
section_id uuid null
chunk_order integer
content text
search_text text
token_estimate integer
page_start integer null
page_end integer null
source_locator jsonb
value_kind text
content_hash text
embedding extensions.vector(1024)
is_active boolean
created_at timestamptz
updated_at timestamptz
```

`value_kind`:

```text
official_fact
actual_value
forecast_value
news_interpretation
broker_opinion
term_definition
```

인덱스:

```sql
create index rag_chunks_embedding_hnsw
on rag_chunks
using hnsw (embedding extensions.vector_cosine_ops);

create index rag_chunks_search_text_trgm
on rag_chunks
using gin (search_text extensions.gin_trgm_ops);

create index rag_chunks_filter_idx
on rag_chunks (stock_code, source_type, is_active);
```

`stock_code`, `source_type`를 `rag_chunks`에 중복 저장할지는 실제 성능과 쿼리 단순성을 보고 결정한다. 저장한다면 `rag_documents`와 일치하도록 인덱싱 단계에서 보장한다.

## 6.5 `research_reports`

```text
id uuid primary key
stock_code text
broker text
title text
report_date date
investment_opinion text null
target_price numeric null
target_price_currency text null
current_price numeric null
page_count integer
storage_bucket text
storage_path text
file_hash text unique
parse_status text
parser_name text
parser_version text
parse_cost numeric null
metadata jsonb
created_at timestamptz
updated_at timestamptz
```

## 6.6 `research_report_pages`

```text
id uuid primary key
report_id uuid
page_number integer
plain_text text
markdown_text text
elements jsonb
page_hash text
created_at timestamptz
unique(report_id, page_number)
```

## 6.7 `research_report_tables`

정상 추출된 표만 저장한다.

```text
id uuid primary key
report_id uuid
page_number integer
table_order integer
title text null
unit text null
headers jsonb
rows jsonb
value_kind text
source_bbox jsonb null
parse_confidence numeric null
created_at timestamptz
```

`value_kind`:

```text
actual
forecast
mixed
unknown
```

## 6.8 `rag_terms`

```text
id uuid primary key
term text unique
aliases text[]
english_name text null
official_definition text
easy_definition text null
source_page integer null
search_text text
is_active boolean
created_at timestamptz
updated_at timestamptz
```

정확 일치용 인덱스와 trigram 인덱스를 만든다.

## 6.9 `rag_ingestion_runs`

```text
id uuid primary key
source_type text
status text
started_at timestamptz
finished_at timestamptz null
processed_count integer
success_count integer
failure_count integer
estimated_cost numeric null
actual_cost numeric null
config jsonb
error_summary jsonb
```

## 6.10 `rag_query_logs`

발표 전 품질 분석에 사용한다.

```text
id uuid primary key
created_at timestamptz
question text
stock_code text null
context_source_type text null
context_source_id text null
query_plan jsonb
retrieved_chunk_ids uuid[]
answer text null
citations jsonb
latency_ms jsonb
model text
status text
error_code text null
```

개인정보가 포함되지 않는 데모 환경이라는 전제다. 서비스 공개 시에는 질문 저장 여부를 다시 검토한다.

---

# 7. 원본 PDF Storage

버킷:

```text
research-reports-private
```

정책:

- public 아님
- 브라우저가 서비스 역할 키로 직접 접근 금지
- 백엔드만 서비스 역할로 읽기
- 원본 경로는 DB에 저장
- 공개 UI에는 원본 URL을 직접 노출하지 않음
- 기본 UI는 증권사, 날짜, 문서명, 페이지, 인용문만 보여줌
- 원본 열기 기능은 `REPORT_PUBLIC_PREVIEW_ENABLED=false`가 기본
- 필요 시 짧은 만료시간의 signed URL을 백엔드가 생성

원본 PDF를 저장하는 이유:

- 페이지 출처 검증
- 재전처리
- 파서 변경 비교
- 발표 시 근거 확인
- 잘못 추출된 표 재검수

---

# 8. 데이터별 전처리

## 8.1 공통 정규화

`normalization.py`에 구현한다.

- Unicode NFKC
- 연속 공백 정리
- 줄바꿈 3개 이상 축소
- 페이지 번호·반복 머리말·반복 꼬리말 제거
- HTML entity 정리
- 숫자 쉼표는 보존
- `%`, `조원`, `억원`, `원`, `주`, 날짜 단위 보존
- 종목 코드 보존
- 영문 대소문자는 검색용 텍스트에서 소문자화
- 원본 인용용 `content`는 의미를 바꾸지 않음

검색용 `search_text`는 다음을 합친다.

```text
종목명
종목 코드
문서 제목
증권사 또는 출처
항목 제목
본문
별칭
```

## 8.2 뉴스

### 주 검색 대상

뉴스는 개별 기사보다 이미 만든 사건 단위 결과를 우선한다.

입력:

```text
summary_title
easy_explanation
factual_body
cluster_id
stock_code
대표 기사 제목·URL
사건 시각
```

### 청킹 규칙

- 기본: 사건 1개 = 청크 1개
- `summary_title + easy_explanation + factual_body`를 합침
- 1,200자 이하라면 분할하지 않음
- 1,200자를 넘으면 제목·소제목·문단 경계로 500~900자 분할
- overlap은 최대 100자
- 한 사건에서 최대 3개 청크

### 대표 기사 본문

MVP 기본 검색에는 넣지 않는다.

이유:

- 샘플에 본문 중복이 존재
- 추천 기사·댓글·내비게이션 문구가 섞여 있음
- 사건 통합 본문이 이미 더 깨끗함

대표 기사 본문은 출처 확인용으로 보존한다. 후속 개선 시 정제 후 보조 청크로 추가할 수 있다.

### 뉴스 인덱싱 조건

- 활성 클러스터
- 요약 성공
- `factual_body` 존재
- 종목 코드 존재
- 현재 버전만 활성화

## 8.3 DART

### 짧은 주요사항보고서

- 번호 항목 기준으로 분리
- 제목과 항목명을 매 청크에 반복
- 표는 `항목: 값` 구조로 직렬화
- 날짜, 수량, 금액, 거래소, 목적을 보존

### 정정공시

반드시 두 종류의 섹션을 만든다.

1. `correction_delta`
   - 정정 항목
   - 정정 사유
   - 정정 전
   - 정정 후
2. 최신 전체 내용

정정 전 문서는 `is_current=false`로 전환한다.

### 긴 사업·분기보고서

샘플 기준 45만 자 이상이므로 전체를 균일하게 자르지 않는다.

우선 인덱싱 대상:

```text
사업의 내용
주요 제품 및 서비스
원재료 및 생산설비
매출 및 수주상황
위험관리 및 파생거래
주요계약 및 연구개발
기타 참고사항
중장기 전략
요약재무정보
```

초기 제외 또는 낮은 우선순위:

```text
대표이사 확인
주소·전화·작성 책임자
반복 목차
감사보고 관련 반복
전체 재무제표의 반복 행
지배구조·임원 명단
부속 상세표 중 RAG 질문과 무관한 대량 목록
```

### 긴 문서 청킹

- 큰 항목을 `rag_sections`에 저장
- 검색용 청크는 500~900자
- 문단 경계 우선
- 100자 이하의 짧은 문단은 다음 문단과 합침
- 표는 제목·단위·열 머리글을 반복해 5~12행 단위로 나눔
- 표 전체가 구조화 재무 DB와 중복이면 검색 우선순위를 낮춤

## 8.4 증권사 리포트

### 페이지 처리

각 페이지별로:

- 일반 텍스트
- Markdown 또는 HTML
- 요소 종류
- 표
- 그림 제목
- 페이지 번호
- 원본 위치 정보

를 저장한다.

### 제거 대상

- 마지막 Compliance Notice
- 반복 증권사 로고·페이지 번호
- 반복 종목명 머리말
- 연락처
- 법적 고지문
- 의미 없는 차트 축 숫자 나열
- 빈 페이지

### 첫 페이지 핵심 정보

반드시 추출한다.

```text
종목명
종목 코드
증권사
발행일
리포트 제목
투자의견
목표주가
목표주가 변경 방향
기준 주가
핵심 요약
```

추출 방식:

1. 정규식과 위치 기반 추출
2. 실패 시 Solar 구조화 추출
3. 추출값이 실제 페이지 텍스트에 존재하는지 검증
4. 검증 실패 시 null로 저장하고 사람이 확인

### 본문 청킹

- 제목 또는 소제목 기준
- 작은 청크: 400~800자
- 큰 부모 섹션: 1,500~4,000자
- 검색은 작은 청크
- 답변 문맥은 부모 섹션 또는 앞뒤 청크까지 확장

### 표 처리

정상 추출된 표만 사용한다.

보존 정보:

```text
표 제목
페이지
단위
열 머리글
행 머리글
값
실제값/전망값
각주
```

`2025A`, `2026E`, `2026F`와 같은 표기를 사용해 실제와 전망을 분리한다.

- A: 실제
- E/F: 예상 또는 전망
- 혼합 표: `mixed`

표 질문 예:

> “키움증권은 한화오션 2026년 영업이익을 얼마로 봐?”

이 질문은 `research_report_tables`에서 정확히 조회한다.

### 차트 처리

MVP에서는 차트 숫자를 복원하지 않는다.

저장:

- 그림 제목
- 페이지
- 범례
- 축 이름
- 주변 설명
- 차트가 말하는 방향을 설명한 본문

금지:

- 선 위치를 보고 정확한 숫자 추측
- 축 눈금을 OCR한 뒤 실제 데이터인 것처럼 답변
- 차트만 근거로 수익률 계산

## 8.5 금융 용어

- 용어 하나 = 레코드 하나
- 정확한 용어·별칭 일치가 우선
- 정확 일치 실패 시 trigram 검색
- 그래도 없으면 일반 문서 검색
- 공식 정의와 쉬운 설명을 분리
- 쉬운 설명은 공식 정의를 덮어쓰지 않음

## 8.6 재무와 구조화 공시

기존 테이블을 그대로 사용한다.

- 새 테이블로 복제하지 않음
- 실제 컬럼을 조사해 저장소 어댑터 작성
- 금액·날짜·주식 수·분기 값은 SQL 직접 조회
- LLM은 조회된 숫자의 의미만 설명

## 8.7 주가

기존 토스증권 연동 경로와 `prices.py` 응답 모델을 재사용한다.

지원 질문:

- 현재가
- 전일 대비 등락률
- 특정 기간 수익률
- 사건 전후 주가 변화
- 거래량 변화

처리:

```text
질문에서 기간과 기준일 해석
→ 기존 시장 데이터 소스 조회
→ 백엔드에서 계산
→ 결과를 structured fact로 답변 문맥에 삽입
```

표현 규칙:

- “뉴스 때문에 하락했다” 금지
- “뉴스 발표 이후 하락했다” 허용
- 원인 판단은 당시 뉴스·공시 근거가 있을 때만 제한적으로 설명

---

# 9. 질문 계획

`routing.py`는 질문을 하나의 종류로 분류하지 않는다.

`QueryPlan` 예:

```python
class QueryPlan:
    stock_code: str | None
    need_financials: bool
    need_disclosure_values: bool
    need_terms: bool
    need_price: bool
    need_documents: bool
    requested_source_types: list[str]
    date_from: date | None
    date_to: date | None
    current_document_id: str | None
    actual_or_forecast: str | None
```

## 9.1 규칙 우선

추가 LLM 호출 없이 규칙으로 처리한다.

### 숫자 신호

```text
얼마
몇
매출
영업이익
순이익
목표주가
발행주식수
계약금액
전환가액
수익률
등락률
```

### 설명 신호

```text
왜
의미
중요
영향
위험
전망
평가
핵심
```

### 용어 신호

```text
뭐야
뜻
정의
무슨 말
```

### 주가 신호

```text
주가
현재가
올랐
내렸
수익률
거래량
```

혼합 질문은 여러 플래그를 동시에 true로 만든다.

## 9.2 종목 결정

우선순위:

1. UI에서 전달된 `stock_code`
2. 현재 문서의 종목 코드
3. 질문에 명시된 회사명·코드
4. 이전 대화의 종목
5. 불명확하면 확인 질문

다른 종목을 임의 선택하지 않는다.

---

# 10. 하이브리드 검색

## 10.1 의미 검색

- 질문용 임베딩 모델 사용
- cosine distance
- 기본 후보 24개
- 필터:
  - `is_active=true`
  - 종목 코드
  - 출처 종류
  - 날짜 범위
  - 실제/전망 구분
  - 현재 문서 여부

## 10.2 키워드 검색

한국어 형태소 확장을 새로 설치하지 않는다.

MVP 방식:

- `pg_trgm`
- 정확 문구 포함
- 제목 포함
- 종목 코드·회사명 포함
- 숫자·영문 약어·제품명 포함
- trigram similarity

기본 후보 24개.

## 10.3 RRF

Supabase 공식 하이브리드 검색 방식과 같은 원리로 결과 순위를 합친다.

기본:

```text
rrf_k = 50
semantic_weight = 1.0
lexical_weight = 1.0
```

임의로 cosine 점수와 trigram 점수를 직접 더하지 않는다.

## 10.4 현재 문서 우선

현재 문서가 있는 경우:

1. 현재 문서 내부에서 최대 4개 검색
2. 전체 자료에서 최대 12개 검색
3. 합친 뒤 중복 제거
4. 현재 문서의 관련 청크가 최소 1개 있으면 최종 문맥에 포함

## 10.5 중복 제거

- 문서 하나당 최대 2개 청크
- 뉴스 사건 하나당 최대 2개 청크
- 동일 `content_hash` 제거
- cosine 유사도가 매우 높은 청크는 하나만 남김
- 같은 표의 연속 조각은 필요할 때만 함께 포함

## 10.6 최종 문맥

최종 6~8개.

우선순위:

```text
현재 문서
공식 DART
구조화 숫자
증권사 리포트
뉴스 사건
금융 용어
```

질문에 따라 우선순위를 다르게 적용한다. 뉴스 질문에 무조건 DART를 끼워 넣지 않는다.

## 10.7 부모 문맥 확장

검색된 청크만 LLM에 보내지 않는다.

- `section_id`가 있으면 부모 섹션의 관련 범위를 추가
- 너무 크면 검색 청크 앞뒤 1개를 추가
- 전체 문맥은 `RAG_CONTEXT_CHAR_BUDGET` 이하
- 인용 번호는 검색된 핵심 청크 기준

---

# 11. 정확한 값 조회 우선순위

## 11.1 실제 재무 수치

```text
기존 구조화 재무 테이블
→ DART 구조화 공시
→ DART 원문 표
→ 리포트의 실제값
```

## 11.2 미래 전망

```text
특정 증권사 질문
→ 해당 리포트 표

시장 전망 질문
→ 여러 리포트 값을 출처별로 표시

회사 공식 가이던스
→ DART 또는 회사 발표
```

## 11.3 공시 값

```text
최신 정정 구조화 값
→ 최신 정정 공시 원문
→ 최초 공시
```

정정 전 값을 최신값처럼 답하면 실패다.

---

# 12. 답변 생성

## 12.1 입력 문맥

Solar에 다음을 전달한다.

```text
시스템 규칙
사용자 질문
종목과 현재 문서
정확 조회 결과
용어 조회 결과
주가 계산 결과
검색 문서 [1]~[N]
최근 대화 최대 4턴
```

## 12.2 시스템 규칙

`prompting.py`에 다음 원칙을 포함한다.

- 제공된 자료만 사용
- 실제값과 전망값을 구분
- 증권사 의견은 증권사 의견이라고 표현
- 뉴스 보도와 공식 공시를 구분
- 근거 없는 인과관계 단정 금지
- 매수·매도 추천 금지
- 어려운 용어는 짧게 설명
- 각 사실 문단 끝에 `[번호]`
- 제공되지 않은 번호 사용 금지
- 근거가 부족하면 부족하다고 말하기
- 초보자 기준으로 핵심부터 답하기

## 12.3 답변 형식

질문에 따라 유연하게 사용하되 기본 순서는 다음이다.

```text
한 줄 결론

핵심 사실
왜 중요한지
정확한 숫자 또는 전망
주의할 점

출처
```

출처 목록 자체는 프런트엔드가 별도 카드로 렌더링하므로 모델이 긴 출처 설명을 반복하지 않는다.

## 12.4 인용 검증

생성 후 코드에서 확인한다.

- 답변에 등장한 모든 `[n]`이 실제 출처 ID인지
- 없는 번호가 있으면 제거하지 말고 한 번의 짧은 교정 처리 또는 오류로 기록
- 숫자 답변에 최소 하나의 출처가 있는지
- 문서 검색을 사용했는데 인용이 하나도 없으면 실패 로그
- 인용문은 원문에 실제로 존재하는 짧은 구절이어야 함

MVP 런타임에서 별도 Groundedness LLM 호출은 하지 않는다. 평가 스크립트에서만 선택적으로 사용한다.

---

# 13. API 명세

## 13.1 동기 응답

```http
POST /api/qa/answer
```

요청:

```json
{
  "question": "2분기 영업이익이 얼마고 왜 늘었어?",
  "stockCode": "005930",
  "context": {
    "sourceType": "news_event",
    "sourceId": "6226",
    "documentId": null,
    "page": null
  },
  "conversationId": "optional",
  "history": [
    {
      "role": "user",
      "content": "..."
    }
  ]
}
```

응답:

```json
{
  "answer": ".... [1]",
  "queryPlan": {
    "needFinancials": true,
    "needDocuments": true
  },
  "sources": [
    {
      "id": 1,
      "sourceType": "dart_document",
      "title": "분기보고서",
      "publisher": "DART",
      "publishedAt": "2026-05-15T00:00:00Z",
      "page": null,
      "snippet": "....",
      "sourceUrl": null,
      "stockCode": "005930",
      "valueKind": "official_fact"
    }
  ],
  "warnings": [],
  "latencyMs": {
    "planning": 5,
    "embedding": 350,
    "retrieval": 90,
    "generation": 1900,
    "total": 2500
  }
}
```

## 13.2 스트리밍

```http
POST /api/qa/stream
Content-Type: application/json
Response: text/event-stream
```

이벤트:

```text
event: plan
data: {...}

event: sources
data: {...}

event: delta
data: {"text":"삼성전자의..."}

event: done
data: {...}

event: error
data: {...}
```

프런트엔드는 `delta`를 이어 붙이고, `sources`로 출처 카드 영역을 먼저 만든다.

## 13.3 리포트 출처

```http
GET /api/reports/{report_id}/citation?page=2
```

기본 응답은 메타데이터와 짧은 인용문이다.

signed URL은 기능이 활성화된 경우에만 별도 엔드포인트에서 생성한다.

---

# 14. 성능 목표

목표 전체 응답 시간:

```text
3~4초
```

내부 목표:

```text
계획 수립             20ms 이하
query embedding       700ms 이하
DB·검색                300ms 이하
가격 조회              500ms 이하
첫 토큰               2초 이내
전체 응답             4초 내외
```

방법:

- 숫자 조회·용어 조회·문서 검색·가격 조회를 가능한 범위에서 병렬 실행
- PDF 파싱은 런타임 금지
- query embedding TTL 캐시
- 가격 30초 캐시
- 문맥 최대 8개
- 출력 토큰 제한
- 별도 reranker LLM 호출 금지
- 네트워크 timeout 명시
- Upstage 오류 시 재시도 최대 2회

3~4초가 항상 보장되지 않으면 프런트 스트리밍으로 체감 시간을 줄인다.

---

# 15. 비용 제어

총 프로젝트 예산은 10만원 이내다.

## 15.1 비용 구분

- PDF Document Parse
- OCR
- 문서 임베딩
- 질문 임베딩
- Solar 답변 생성

## 15.2 제한

- PDF 파일 해시가 같으면 재파싱 금지
- 청크 해시가 같으면 재임베딩 금지
- 질문 캐시가 있으면 재임베딩 생략
- 개발 중 전체 리포트 재처리 금지
- 먼저 뉴스 100건, DART 20건, PDF 10개로 시험
- 예상 비용을 `rag_ingestion_runs`에 기록
- PDF 예상 비용 30,000원 초과 시 자동 중단
- 모델 오류로 반복 호출하지 않도록 재시도 제한

---

# 16. 구현 단계

## Phase 0 — 사전 검증

작업:

- 현재 브랜치와 테스트 상태 기록
- 실제 Supabase 스키마 재확인
- 현재 테이블 행 수 기록
- pgvector·pg_trgm 존재 여부 확인
- Upstage 모델 호출 시험
- 임베딩 차원 1024 확인
- 토스증권 API 키의 존재 여부를 값 노출 없이 확인
- 토스증권 API 실제 소량 호출 시험
- 현재가·기간 시세·과거 시세 지원 범위 확인
- Supabase에 주가 이력 데이터가 없음을 확인
- 로컬 리포트 폴더 위치와 파일 수 확인
- 대표 PDF 1개 Document Parse 시험

산출물:

```text
backend/artifacts/rag_preflight_report.md
```

통과 조건:

- 기존 테스트 통과
- 임베딩 차원 확인
- Supabase 쓰기 권한 확인
- 비공개 Storage 생성 가능
- PDF 파싱 결과에 페이지·본문·표가 포함

## Phase 1 — DB와 저장소 계층

작업:

- 4개 마이그레이션 작성
- 로컬 또는 스테이징에서 적용
- RLS 확인
- `repositories/rag.py`, `reports.py`, `terms.py`
- CRUD·버전 비활성화 구현

통과 조건:

- 마이그레이션 재실행 안전
- HNSW·trigram 인덱스 존재
- current 문서 partial unique 동작
- 서비스 역할 외 원본 PDF 접근 불가

## Phase 2 — 뉴스 RAG 최소 동작

작업:

- 뉴스 사건 청킹
- passage embedding
- 배치 인덱싱
- semantic 검색
- `/api/qa/answer`
- 출처 반환

범위:

- 요약 성공 뉴스 100건부터
- 이후 전체 활성 뉴스 사건

통과 조건:

- 현재 뉴스 질문에서 해당 사건이 상위 3위 안
- 동일 사건 중복이 답변 문맥을 독점하지 않음
- 답변에 실제 출처 번호 포함
- 없는 내용 생성하지 않음

## Phase 3 — 하이브리드 검색

작업:

- trigram 키워드 검색
- RRF RPC
- 필터
- 중복 제거
- 현재 문서 우선
- 부모 문맥 확장

통과 조건:

- 정확한 제품명·계약명·영문 약어 질문 개선
- 의미가 다른 표현 질문도 관련 문서를 찾음
- 검색 p95가 목표 범위

## Phase 4 — 숫자·용어·혼합 질문

작업:

- 기존 재무 테이블 어댑터
- 기존 구조화 공시 어댑터
- 금융 용어 인덱싱
- `QueryPlan`
- 혼합 실행
- 정정공시 최신 우선

통과 조건:

- “얼마고 왜?” 질문이 숫자 조회와 문서 검색을 모두 사용
- 실제값과 전망값 구분
- 용어 정확 일치
- 정정 전 숫자를 최신 숫자로 사용하지 않음

## Phase 5 — 증권사 리포트

작업:

- 로컬 리포트 폴더 탐색
- 비공개 Storage
- 로컬 PDF 업로드·중복 검사
- Document Parse
- 페이지 저장
- 첫 페이지 메타데이터
- 본문·표 청킹
- 표 전망값 조회
- 페이지 출처

통과 조건:

- 제공된 대표 리포트에서 제목·증권사·날짜·목표주가 추출
- 표의 단위와 A/E/F 구분
- 차트에서 숫자를 추측하지 않음
- 답변 출처에 정확한 페이지 표시

## Phase 6 — 주가 질문

작업:

- Supabase에 저장된 주가 이력이 없다는 전제에서 시작
- 기존 토스증권 시장 데이터 코드 재사용
- 기간 수익률 계산
- 사건 전후 계산
- 캐시
- 인과 표현 제한

통과 조건:

- 계산값을 LLM이 아닌 백엔드가 생성
- 거래일이 아닌 날짜 처리
- 데이터 부족 시 명확한 오류
- “때문에”라고 단정하지 않음

## Phase 7 — 프런트 연결

작업:

- `/ask`
- 뉴스 모달 우측 AI 패널
- 종목 페이지 질문 버튼
- 공시·리포트 질문 버튼
- 스트리밍
- 출처 카드
- 오류·재시도
- 현재 문서 context 전달

통과 조건:

- 뉴스 모달 질문 시 해당 뉴스 ID 전달
- 전역 질문 시 종목 선택 전달
- 답변 생성 중 UI 멈춤 없음
- 출처 번호 클릭 시 카드 강조
- 모바일에서도 입력 가능

## Phase 8 — 평가와 튜닝

작업:

- 최소 50개 고정 질문
- semantic 단독 vs hybrid 비교
- 검색 hit@k
- 출처 정확성
- 숫자 정확성
- 실제/전망 혼동
- 정정공시 오류
- 응답 시간
- 비용

통과 조건은 18장 기준.

## Phase 9 — 배포

- 기존 Docker·CD 흐름 유지
- 새 환경변수 배포 환경에 추가
- CI에 테스트·lint
- 마이그레이션은 배포 전 별도 단계
- 운영 API에서 서비스 역할 키가 브라우저로 노출되지 않음
- 발표 전 전체 인덱싱 완료

---

# 17. 테스트

## 17.1 단위 테스트

```text
test_news_chunking.py
test_dart_chunking.py
test_report_chunking.py
test_query_routing.py
test_hybrid_fusion.py
test_source_dedup.py
test_citation_validation.py
test_actual_forecast_labels.py
test_correction_priority.py
test_price_calculation.py
```

## 17.2 통합 테스트

```text
test_qa_news_context.py
test_qa_financial_and_reason.py
test_qa_term.py
test_qa_report_forecast.py
test_qa_correction_disclosure.py
test_qa_price_event_window.py
test_report_private_storage.py
```

## 17.3 반드시 포함할 회귀 사례

1. 대표 기사 본문의 추천 기사·댓글 텍스트가 검색되지 않아야 한다.
2. 현대차 분기보고서의 45만 자 전체가 한 청크가 되면 안 된다.
3. 정정 전 127,200과 정정 후 126,035를 혼동하지 않아야 한다.
4. 리포트의 `2026E` 값을 실제 실적으로 표현하면 안 된다.
5. SK하이닉스 제품명·ADR·종목 코드 같은 정확 단어를 키워드 검색이 찾아야 한다.
6. 현재 뉴스 모달 질문이 다른 삼성전자 뉴스로 튀지 않아야 한다.
7. 차트만 있는 페이지에서 정확한 숫자 답변을 만들면 안 된다.

---

# 18. 평가 기준

## 18.1 검색

- 기대 근거가 top 5 안에 포함: 85% 이상
- 현재 문서 질문에서 현재 문서 top 3 포함: 95% 이상
- 정확 명칭 질문에서 keyword hit: 90% 이상
- 중복 뉴스가 최종 8개 중 3개 이상 차지: 0건

## 18.2 답변

- 정확 숫자 질문 정확도: 95% 이상
- 출처가 없는 사실 단정: 5% 미만
- 실제값·전망값 혼동: 0건
- 정정 전 공시 사용: 0건
- 존재하지 않는 인용 번호: 0건
- 매수·매도 직접 추천: 0건

## 18.3 성능

- 첫 토큰 p50: 2초 이내
- 전체 p50: 4초 이내
- 전체 p95: 8초 이내
- 검색 p95: 500ms 이내

3~4초 목표를 못 맞추면 정확도를 희생하기 전에 다음 순서로 조정한다.

1. 문맥 수 축소
2. 출력 길이 축소
3. 가격·조회 병렬화
4. query cache
5. 모델 변경 검토

---

# 19. 프롬프트 예시

```text
너는 주식 초보자를 위한 정보 해설 도우미다.

규칙:
1. 아래 제공된 자료만 사용한다.
2. 회사가 공식 발표한 사실, 뉴스 보도, 증권사 전망을 구분한다.
3. 실제값과 예상값을 구분한다.
4. 숫자는 STRUCTURED FACTS의 값을 우선한다.
5. 근거가 부족하면 확인할 수 없다고 말한다.
6. 매수·매도 추천을 하지 않는다.
7. 주가 움직임과 뉴스의 인과관계를 단정하지 않는다.
8. 사실이 포함된 문단 끝에 제공된 [번호]를 붙인다.
9. 제공되지 않은 인용 번호를 만들지 않는다.
10. 초보자가 이해하기 쉽게 핵심부터 설명한다.

답변 순서:
- 한 줄 결론
- 핵심 사실
- 왜 중요한지
- 주의할 점
```

문서 조각:

```text
[1] source_type=dart_document, value_kind=official_fact, ...
[2] source_type=research_report, value_kind=forecast_value, ...
```

---

# 20. Claude Code/Codex 실행 규칙

각 Phase 시작 전:

1. 관련 기존 코드를 읽는다.
2. 변경 파일 목록을 먼저 출력한다.
3. DB 또는 API 계약이 불명확하면 코드를 추측하지 않는다.
4. 작은 테스트를 먼저 작성한다.
5. 구현 후 테스트·lint를 실행한다.
6. 실패하면 다음 Phase로 넘어가지 않는다.

각 Phase 종료 보고 형식:

```text
완료한 항목
수정한 파일
적용한 마이그레이션
실행한 테스트와 결과
실측 비용
실측 응답 시간
남은 위험
다음 Phase 진행 가능 여부
```

한 번에 전체를 무검증 구현하지 않는다.

---

# 21. 완료 정의

다음이 모두 되면 MVP RAG 완료다.

- 뉴스 모달에서 현재 사건 기준 질문 가능
- 종목 전체 질문 가능
- 재무 숫자 + 이유 혼합 질문 가능
- 공시 최신 정정값 사용
- 리포트 목표주가·전망과 근거 질문 가능
- 금융 용어 설명 가능
- 주가 기간 변화 질문 가능
- 하이브리드 검색 사용
- 모든 답변에 출처 카드
- 리포트 페이지 표시
- 실제값과 전망값 구분
- 평균 3~4초 수준 또는 스트리밍으로 즉시 반응
- 총 API 비용 10만원 이내
- 기존 뉴스·DART 기능 회귀 없음

---

# 22. 공식 참고 자료

- Supabase Docs — Hybrid Search
- pgvector 공식 저장소 — HNSW, cosine, vector dimensions
- Upstage Docs — Embeddings
- Upstage Docs — Document Parse
- Upstage Docs — OCR
- FastAPI Docs — StreamingResponse
