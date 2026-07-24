# RAG_PHASE_EXECUTION_PLAN.md

## 0. 문서 역할

이 문서는 최종 Agentic Hybrid RAG 구현 체크리스트다.

고정 원칙:

- 키워드 기반 Tool 라우팅을 새로 추가하지 않는다.
- 특정 질문·기업·평가 사례를 런타임 코드에 하드코딩하지 않는다.
- LangChain `create_agent`와 prebuilt middleware를 우선한다.
- 직접 custom StateGraph를 만들지 않는다.
- 기존 검색·SQL Service를 Tool로 재사용한다.
- 각 Phase 완료 후 자동으로 다음 단계로 진행하지 않는다.

---

# 1. 전체 진행 현황

| Phase | 내용 | 상태 | 승인 |
|---|---|---:|---:|
| 0 | 사전 검증 | [x] | [x] |
| 1 | DB·Storage·Repository | [x] | [x] |
| 2 | 뉴스 RAG | [x] | [x] |
| 3 | 하이브리드 검색 | [x] | [x] |
| 4 | 재무·용어·혼합 QA | [x] 구현 완료, 정확성 보강 필요 | [x] |
| 5 | 증권사 리포트 | [x] 적재·검색·QA 연결 완료 | [ ] |
| 5.5 | 단일 Agentic RAG 전환 | [ ] (A·B 완료, C~G 대기) | [ ] |
| 6 | 주가 Tool | [ ] | [ ] |
| 7 | 프런트 연결 | [ ] | [ ] |
| 8 | 전체 평가·튜닝 | [ ] | [ ] |
| 9 | 배포·발표 | [ ] | [ ] |
| 선택 | MCP 노출 | [-] 기본 제외 | — |
| 제외 | A2A·다중 Agent | [-] 제외 | — |

---

# 2. 고정 설계 결정

## 채택

```text
LangChain v1 create_agent
LangGraph runtime
단일 Agent
typed read-only Tools
기존 HybridRetriever
기존 FactsService
prebuilt middleware
Tool trace
```

## 폐기

```text
키워드 QueryPlan을 메인 라우터로 사용
단순/복합 규칙 분류
legacy QueryPlan fallback
특정 질문 예외
```

## 제외

```text
custom StateGraph
다중 Agent
Supervisor
A2A
자유 SQL
GraphRAG
Self-RAG
CRAG 명목 구현
Deep Agents
```

---

# Phase 5. 현재 완료 상태

## 완료 내용

```text
244 research_reports
1,877 pages
1,937 tables
활성 리포트 청크 4,350
partial 리포트 검색 제외
search_research_reports
QA report_sources 연결
페이지 출처
```

## Phase 5 승인 전 확인

- [ ] PR CI 통과
- [ ] 변경 범위가 Phase 5에 한정
- [ ] 비관련 `vercel.json` 미포함
- [ ] 전체 테스트·ruff 통과
- [ ] Phase 5 문서와 실제 DB count 일치
- [ ] 머지

---

# Phase 5.5. 단일 Agentic RAG 전환

## 목표

키워드 QueryPlan을 라이브 경로에서 제거하고, 모든 질문을 LangChain 표준 Tool-Calling Agent가 처리하도록 전환한다.

---

## 5.5-A. 의존성과 모델 preflight  ✅ 완료 (2026-07-24)

- [x] 새 브랜치 생성 (`phase/5.5-a-agent-preflight`)
- [x] LangChain v1·LangGraph v1 호환 버전 조사 (1.3.14 / 1.2.9)
- [x] Upstage integration 호환 조사 — **langchain-upstage 대신 langchain-openai 채택**
- [x] 작은 별도 환경에서 설치 (uv --no-project 격리) + 정식 .venv 설치
- [x] 기존 테스트 실행 (pytest 156 passed, ruff clean — 회귀 없음)
- [x] `bind_tools()` 단일 Tool call 검증
- [x] Tool result 후 추가 Tool call 검증
- [x] 2개 Tool 연속 호출 검증 (복합 질문 표현에 따라 편차 → 5.5-C 프롬프트 보강)
- [x] Tool call streaming 검증 (tool_call_chunks 감지)
- [x] 한국어 부정·제외 질문 검증 (재무 Tool 미호출 확인)
- [x] `create_agent` 호환 검증
- [x] 정확한 버전을 `uv.lock`에 고정
- [x] 비밀키 미출력
- [x] preflight 결과 문서화 (`AGENT_PREFLIGHT.md`)

### ⚠️ 5.5-A 발견: langchain-upstage → langchain-openai 대체

`langchain-upstage 0.7.7`이 `tokenizers<0.21`을 강제해 프로젝트 `transformers>=5`
(tokenizers 0.22)와 uv lock 해결 불가 충돌. Upstage 는 OpenAI 호환 API 이므로
`langchain-openai`의 `ChatOpenAI(base_url=Upstage)`로 대체(설계 변경 아님, provider 분리 유지).

### 중단 조건

- 현재 Agent 모델이 Tool Calling을 안정적으로 지원하지 않음
- 스트리밍 Tool call이 현재 SSE 계약과 연결 불가
- 패키지 도입으로 기존 테스트 대량 회귀
- 모델 비용·지연이 프로젝트 한도를 크게 초과

→ **해당 없음.** 임의 parser Agent 불필요.

### 산출물

```text
backend/docs/rag/phase_5_5/AGENT_PREFLIGHT.md      (완료)
backend/docs/rag/phase_5_5/preflight_result.json  (완료)
backend/scripts/agent_preflight.py                (완료)
```

### 5.5-A 종료 기록

```text
상태: 완료
완료일: 2026-07-24
고정 버전: langchain 1.3.14 / langchain-core 1.5.1 / langgraph 1.2.9 / langchain-openai 1.4.1
Agent 모델: solar-pro3-260323 (ChatOpenAI + Upstage base_url)
Tool Calling: 단일·부정제외·streaming·create_agent 통과. 멀티툴은 프롬프트 보강 대상.
기존 테스트: 156 passed (회귀 없음)
langchain-upstage: 미채택(tokenizers<0.21 충돌) → langchain-openai 대체
```

---

## 5.5-B. Tool 계약  ✅ 완료 (2026-07-24)

- [x] 공통 `ToolResult` 구현 (`app/agent/tools/common.py`)
- [x] 공통 `SourceRef` 구현
- [x] `QaRuntimeContext` 구현 (`app/agent/context.py`)
- [x] Tool error sanitize (`sanitize_exception` — 내부 예외 비노출)
- [x] Tool 결과 크기 제한 (`clamp_text`/`clamp_items`, MAX_RESULT_ITEMS/MAX_TEXT_CHARS)
- [x] 읽기 전용 확인 (전 Tool 이 기존 read-only Service 만 호출, 쓰기 없음)

### Tools

- [x] `get_financial_facts` (`tools/financials.py`)
- [x] `lookup_financial_term` (`tools/terms.py`)
- [x] `search_news` (`tools/news.py`)
- [x] `search_disclosures` (`tools/disclosures.py`)
- [x] `get_disclosure_values` (`tools/disclosures.py`)
- [x] `search_research_reports` (`tools/reports.py`)

### 검증

- [x] 기존 Service 재사용 (FactsService·HybridRetriever·ResearchReportSearch)
- [x] Agent가 SQL 문자열을 전달할 수 없음 (입력 스키마에 sql/query-SQL 필드 없음, Literal 계정)
- [x] `get_financial_facts` 기간·amount_type 엄격 검증 (report_period→공식 reprt_code 매핑)
- [x] 다른 기간 fallback 없음 (미일치 시 no_data)
- [x] latest disclosure 기본값 (`SearchDisclosuresInput.latest_only=True`)
- [x] partial report 제외 (검색 계층이 active/current 강제)
- [x] 모든 결과에 source metadata (`SourceRef`)

> 참고: DART reprt_code 매핑은 Tool 계층에서 공식값(11013=q1 … 11011=annual)을 사용한다.
> (기존 `FactsService.REPRT_LABEL` 오매핑과 무관하게 Tool 이 올바른 코드로 조회.)
> Agent 등록(create_agent)·LLM 실호출은 5.5-C 이후. 이 단계는 Tool 계약·구현·단위검증만.

### 산출물

```text
backend/app/agent/context.py                    (완료)
backend/app/agent/tools/common.py               (완료)
backend/app/agent/tools/{financials,terms,news,disclosures,reports}.py  (완료)
backend/tests/agent/test_tool_contracts.py      (완료, 14 테스트 통과)
```

전체 테스트 170 passed(기존 156 + 5.5-B 14), ruff·format 통과.

---

## 5.5-C. Agent 구현

- [ ] Agent model 초기화 (ChatOpenAI + Upstage base_url; 5.5-A 확정)
- [ ] `create_agent` 사용
- [ ] 시스템 프롬프트 작성
- [ ] Tool 목록 연결
- [ ] Runtime Context 연결
- [ ] `ModelCallLimitMiddleware`
- [ ] `ToolCallLimitMiddleware`
- [ ] `ToolRetryMiddleware`
- [ ] `ModelRetryMiddleware`
- [ ] `ToolErrorMiddleware`
- [ ] 동일 Tool·동일 인자 반복 검사
- [ ] 전체 timeout
- [ ] 내부 추론 전문 비로그
- [ ] Agent feature flag

초기 제한:

```text
모델 최대 4회
Tool 최대 5회
동일 Tool+인자 최대 1회
외부 Tool 재시도 1회
전체 8초
```

### 금지

- [ ] custom planner node를 만들지 않음
- [ ] keyword router를 만들지 않음
- [ ] simple/complex classifier를 만들지 않음
- [ ] custom StateGraph를 만들지 않음
- [ ] legacy QueryPlan fallback을 만들지 않음

### 산출물

```text
backend/app/agent/runtime.py
backend/app/agent/prompts.py
backend/app/agent/middleware.py
backend/app/services/agent_qa.py
```

---

## 5.5-D. API 연결

- [ ] `/qa` Agent 경로
- [ ] `/qa/stream` Agent 경로
- [ ] 기존 요청 계약 유지
- [ ] `execution.toolCalls` 응답 추가
- [ ] `queryPlan` deprecated optional
- [ ] SSE `tool_start`
- [ ] SSE `tool_end`
- [ ] SSE `sources`
- [ ] SSE `delta`
- [ ] SSE `done`
- [ ] 오류 응답
- [ ] feature flag로 legacy/agent A-B 실행
- [ ] 운영 전 기본 flag false

### 산출물

```text
backend/app/api/routes/qa.py
backend/app/schemas/qa.py
```

---

## 5.5-E. 검증기와 trace

- [ ] source_id 유효성
- [ ] 숫자 Tool 결과 포함 여부
- [ ] 단위·기간 검증
- [ ] actual/forecast 검증
- [ ] latest correction 검증
- [ ] Tool call count 기록
- [ ] model call count 기록
- [ ] Tool latency
- [ ] stop reason
- [ ] validation errors
- [ ] 비밀정보·전체 PDF 미로그

### 선택

- [ ] LangSmith 개발 tracing 검토
- [ ] 데이터 외부 전송 정책 확인
- [ ] 미승인 시 `rag_query_logs`만 사용

---

## 5.5-F. 평가

- [ ] 개발셋 작성
- [ ] 홀드아웃 작성
- [ ] 금융용어
- [ ] 재무 연간·분기·누적
- [ ] 뉴스
- [ ] 공시
- [ ] 리포트
- [ ] 복합 질문
- [ ] 부정·제외
- [ ] 현재 문맥
- [ ] no_data
- [ ] legacy QueryPlan 비교
- [ ] Tool Recall
- [ ] forbidden Tool violation
- [ ] Tool arg accuracy
- [ ] 숫자 Exact Match
- [ ] Citation Precision
- [ ] 지연·비용
- [ ] 동일 호출 반복

### 반드시 포함

```text
최근 뉴스에서 삼성전자 호재 있어?
영업이익 같은 실적 관련은 제외해.

실적 얘기는 빼고 최근 악재만 알려줘.

목표주가 말고 실제 주가가 왜 떨어졌어?

증권사 전망 말고 회사가 직접 공시한 내용만 알려줘.

2025년 3분기 누적 영업이익과
3분기 단독 영업이익을 비교해줘.
```

### 승인 기준

```text
필수 Tool Recall ≥ 95%
금지 Tool 위반 ≤ 3%
부정·제외 치명적 위반 0
재무 Exact Match 100%
기간·단위 100%
actual/forecast 혼동 0
존재하지 않는 인용 0
동일 호출 반복 0
단순 P95 ≤ 6초
복합 P95 ≤ 10초
```

---

## 5.5-G. 라이브 전환

- [ ] 승인 기준 통과
- [ ] `AGENT_ENABLED=true` 스테이징
- [ ] 실제 UI smoke test
- [ ] legacy와 결과 비교
- [ ] 운영 flag 전환
- [ ] QueryPlan 라이브 호출 제거
- [ ] QueryPlan deprecated 표시
- [ ] 문서 갱신
- [ ] 완료 보고
- [ ] 다음 Phase 자동 진행 금지

---

## Phase 5.5 종료 기록

```text
상태:
완료일:
Agent 모델:
LangChain 버전:
LangGraph 버전:
Tool 수:
Tool 선택 평가:
금융 Exact Match:
부정·제외 평가:
단순 P95:
복합 P95:
질문당 평균 비용:
legacy QueryPlan 라이브 제거 여부:
남은 위험:
Phase 6 진행 가능 여부:
```

---

# Phase 6. 주가 Tool

## 목표

주가 조회와 사건 전후 수익률을 Agent가 사용할 수 있는 읽기 전용 Tool로 추가한다.

- [ ] 토스증권 API 실제 범위 재확인
- [ ] `get_stock_prices`
- [ ] `calculate_event_return`
- [ ] 거래일 처리
- [ ] 휴장일
- [ ] 데이터 누락
- [ ] 30초 cache
- [ ] 백엔드 계산
- [ ] source metadata
- [ ] Agent Tool 등록
- [ ] 호출 limit
- [ ] 인과 단정 금지
- [ ] 평가셋 추가

통과:

```text
계산 Exact Match 100%
Agent가 산술로 대체 0
데이터 없음 추측 0
```

---

# Phase 7. 프런트 연결

- [ ] Agent SSE 이벤트
- [ ] Tool 실행 상태 표시
- [ ] 뉴스 현재 문맥
- [ ] 공시 현재 문맥
- [ ] 리포트 현재 문맥·페이지
- [ ] 종목 코드
- [ ] 출처 카드
- [ ] numeric source
- [ ] report source
- [ ] 오류
- [ ] 중단
- [ ] 모바일
- [ ] 내부 추론 미표시

표시 예:

```text
재무 데이터 확인 중
최근 뉴스 검색 중
증권사 리포트 확인 중
```

Tool 인자 전체나 내부 reasoning은 사용자에게 보여주지 않는다.

---

# Phase 8. 전체 평가·튜닝

- [ ] 160개 평가셋
- [ ] 홀드아웃
- [ ] Agent trajectory
- [ ] 검색
- [ ] 숫자
- [ ] 출처
- [ ] 제외 조건
- [ ] 답변 불가능
- [ ] 지연
- [ ] 비용
- [ ] reranker A/B
- [ ] 사람 평가 2인
- [ ] 치명적 오류 수정
- [ ] 특정 질문 하드코딩 점검
- [ ] 발표 질문 선정

---

# Phase 9. 배포

- [ ] lockfile
- [ ] Docker 의존성
- [ ] 메모리
- [ ] 환경변수
- [ ] feature flag
- [ ] migration
- [ ] trace 정책
- [ ] CI
- [ ] 배포 smoke
- [ ] SSE proxy
- [ ] 비용
- [ ] rollback
- [ ] 발표 리허설

rollback:

```text
AGENT_ENABLED=false
```

이 플래그는 장애 대응용이다. legacy QueryPlan을 장기 운영 fallback으로 유지한다는 뜻이 아니다. 비활성화 시 QA를 안전한 제한 응답 또는 검증된 단일 조회 API로 전환한다.

---

# 선택: MCP

기본 제외한다.

다음 조건이 모두 만족될 때만 진행한다.

- Agent와 Tool 안정화
- 외부 클라이언트 재사용 요구
- 인증 범위 확정
- 일정 여유

노출 후보:

```text
get_financial_facts
search_news
search_research_reports
```

내부 Agent보다 먼저 구현하지 않는다.

---

# 부록 P0-5. Phase 0~5 상세 실행 기록 (보존)

> 아래는 Agentic 전환(Phase 5.5) 이전, Phase 0~5 실제 구현·검증·적재·비용의 상세 기록이다.
> 위 §1 진행 현황표의 완료 근거이며, 삭제·축약하지 않고 원문 보존한다.
> 참고: Phase 4~5의 '결정론적 QueryPlan/FactsQaService 라이브 경로'는 Phase 5.5에서
> LangChain 단일 Agent로 대체될 예정이다(당시 시점의 완료 기록으로 읽을 것).

---

# Phase 0. 사전 검증

## 목표

실제 코드·DB·API 환경이 구현 명세와 맞는지 빠르게 확인한다.

이 단계에서는 대량 인덱싱이나 본격 기능 구현을 하지 않는다.

## 작업 체크리스트

- [x] 현재 브랜치와 저장소 상태 확인
- [x] 기존 테스트 실행 결과 기록  (58 passed)
- [x] 현재 FastAPI 진입점 확인  (app.main:app)
- [x] 기존 RAG 관련 파일의 구현 상태 확인  (전부 placeholder)
- [x] 실제 Supabase 테이블·함수·인덱스 확인
- [x] `pgvector` 사용 가능 여부 확인  (미설치, CREATE 권한 O)
- [x] `pg_trgm` 사용 가능 여부 확인  (미설치, CREATE 권한 O)
- [x] Supabase 마이그레이션 권한 확인  (CREATE TABLE 롤백 검증)
- [x] 비공개 Storage 생성 권한 확인  (probe 버킷 생성→삭제)
- [x] Upstage query embedding 실제 호출  (1024)
- [x] Upstage passage embedding 실제 호출  (1024)
- [x] 두 임베딩 출력 차원 확인  (1024 일치)
- [x] 현재 사용할 수 있는 Solar 채팅 모델 확인  (solar-pro3-260323)
- [x] Solar 스트리밍 지원 여부 확인  (지원)
- [x] 대표 PDF 1개 파싱
- [x] 페이지 구분 유지 여부 확인  (form-feed 유지)
- [!] 본문 추출 품질 확인  (한국어 조판 순서 불안정 → Phase5 보강)
- [!] 표 제목·단위·행·열 유지 여부 확인  (단위 O, 행·열 정합 부족 → Phase5)
- [x] 기존 토스증권 연동 코드 위치와 재사용 가능 여부 확인  (app/sources/prices.py)
- [x] 토스증권 키 존재 여부를 값 노출 없이 확인
- [x] 토스증권 API 소량 실제 호출  (005930)
- [x] 현재가·기간 시세·과거 시세 지원 범위 확인  (현재가/일봉/분봉/호가)
- [x] Supabase에 토스 주가 이력이 없음을 확인
- [x] 로컬 리포트 폴더 경로와 PDF 파일 수 확인  (/Users/kimjunwoo/report, 244)
- [x] Supabase에 리포트 원본·페이지·표가 아직 없음을 확인
- [x] 예상 변경 파일 목록 작성  (완료 보고서)
- [x] 예상 비용과 주요 위험 작성  (완료 보고서)

## 유연하게 판단할 부분

- 대표 PDF는 가장 복잡한 파일 한 개를 우선 사용해도 된다.
- PDF 파서 모델명과 호출 방식은 현재 공식 API에 맞게 조정할 수 있다.
- 테스트가 없는 영역은 최소 smoke test로 대체할 수 있다.
- 스키마 조사 결과 명세와 실제 이름이 다르면 실제 코드를 기준으로 한다.

## 최소 통과 조건

- 임베딩 모델과 차원이 확인됨
- DB 마이그레이션 실행이 가능함
- 기존 기능이 기본적으로 실행됨
- PDF에서 페이지와 본문을 연결할 수 있음
- 치명적인 충돌이 없음

## 산출물

```text
backend/docs/rag/phase_0/rag_preflight_report.md
backend/docs/rag/phase_0/PHASE_0_COMPLETION.md
backend/docs/rag/phase_0/precheck_bundle/   (기존 조사 자료 보관)
```
(주: SPEC의 backend/artifacts 경로 대신, 지시에 따라 phase_0 폴더에 저장)

## Phase 종료 기록

```text
상태: 완료
완료일: 2026-07-22
확인한 임베딩 모델: solar-embedding-2-query / solar-embedding-2-passage
확인한 차원: 1024 (query=passage)
사용할 Chat 모델: solar-pro3-260323 (스트리밍 지원)
PDF 파서: 로컬 pdftotext -layout(1차), 표·복잡 PDF는 Phase5에서 Upstage Document Parse 보강
Phase 1 진행 가능 여부: 가능
주요 변경 필요 사항: 임베딩 1024 확정(4096 alias 미사용), 표 복원은 Phase5 파서 보강
```

---

# Phase 1. DB·Storage·기본 Repository

## 목표

RAG 데이터를 안전하게 저장하고 검색할 기반을 만든다.

## 작업 체크리스트

- [x] 마이그레이션 파일 작성  (0012~0015)
- [x] `rag_documents` 생성
- [x] `rag_sections` 생성
- [x] `rag_chunks` 생성  (embedding vector(1024))
- [x] `research_reports` 생성
- [x] `research_report_pages` 생성
- [x] `research_report_tables` 생성
- [x] `rag_terms` 생성
- [x] `rag_ingestion_runs` 생성
- [x] `rag_query_logs` 생성
- [x] `rag_chunks`에 `stock_code` 중복 저장
- [x] `rag_chunks`에 `source_type` 중복 저장
- [x] `rag_chunks`에 `published_at` 중복 저장
- [x] `rag_chunks`에 `value_kind` 중복 저장
- [x] `rag_chunks`에 `is_active` 저장
- [x] 벡터 인덱스 생성  (HNSW cosine)
- [x] 키워드 검색 인덱스 생성  (trgm GIN)
- [x] 자주 사용하는 필터 인덱스 생성  (filter/published/document)
- [x] 비공개 리포트 Storage 생성  (research-reports-private, public=false)
- [x] Storage 접근 정책 확인  (service_role 전용, 정책 0개=익명 차단)
- [x] Repository 구현  (app/repositories/rag.py)
- [x] 문서 버전 비활성화 로직 구현  (실DB 검증)
- [x] 마이그레이션 재실행 안전성 확인  (멱등)
- [x] 롤백 방법 작성  (migrations/rollback/, --rollback)
- [x] 기존 DB 기능 회귀 확인  (58 passed)

## 유연하게 판단할 부분

- 실제 스키마와 코드 스타일에 맞게 테이블·컬럼명을 조금 바꿀 수 있다.
- `rag_sections`를 초기에는 최소 컬럼으로 구현하고 이후 확장할 수 있다.
- query log는 개인정보 위험이 있으면 저장 범위를 축소할 수 있다.
- Repository 파일 분리는 기존 프로젝트 패턴을 우선한다.

## 최소 통과 조건

- 문서·청크·리포트·용어를 저장할 수 있음
- 의미 검색과 키워드 검색용 인덱스가 생성됨
- 원본 PDF가 public으로 노출되지 않음
- 기존 데이터가 변경되지 않음
- 롤백 방법이 존재함

## 산출물

```text
backend/docs/rag/phase_1/PHASE_1_DB_STORAGE.md   (기준 문서)
backend/docs/rag/phase_1/PHASE_1_COMPLETION.md   (완료 보고서)
migrations/0012~0015 + migrations/rollback/*
scripts/apply_rag_migrations.py, scripts/create_rag_storage.py
app/repositories/rag.py
```

## Phase 종료 기록

```text
상태: 완료
완료일: 2026-07-22
생성한 마이그레이션: 0012_rag_core, 0013_research_reports, 0014_rag_hybrid_search, 0015_rag_rls_storage
실제 적용된 테이블: rag_documents, rag_sections, rag_chunks, research_reports,
  research_report_pages, research_report_tables, rag_terms, rag_ingestion_runs, rag_query_logs (9개)
기획서와 달라진 스키마: uuid=gen_random_uuid, rag_chunks denorm 컬럼 확장,
  RLS enable만(정책 없음), Storage 버킷은 API로 생성
롤백 방법: scripts/apply_rag_migrations.py --rollback
남은 위험: denorm 정합성은 Phase2 인덱싱 책임, RLS 정책은 공개 API 시 재검토
```

---

# Phase 2. 뉴스 기반 최소 RAG

## 목표

뉴스 사건 데이터만으로 질문→검색→답변→출처 흐름을 완성한다.

## 작업 체크리스트

- [x] 뉴스 사건 원본 조회 구현
- [x] 뉴스 텍스트 정규화 구현
- [x] 뉴스 사건 청킹 구현
- [x] 대표 기사 전체 본문은 기본 검색에서 제외
- [x] 문서용 passage embedding 구현
- [x] 해시 기반 중복 임베딩 방지  (재실행 100건 skip 확인)
- [x] 뉴스 100건 시험 인덱싱  (indexed 100 / chunks 109 / 실패 0)
- [x] 의미 검색 구현  (rag_search_semantic RPC)
- [x] 현재 뉴스 문맥 우선 검색
- [x] QA 요청 모델 구현
- [x] QA 응답 모델 구현
- [x] Solar 답변 생성 구현
- [x] 스트리밍 구현  (SSE)
- [x] 출처 배열 반환
- [x] 인용 번호 검증  (invalid 0)
- [x] 뉴스 질문 smoke test  (self_in_top_rate 1.0)
- [x] 응답 시간 측정  (검색~0.13s, 생성~3.9s)
- [x] API 비용 측정  (시험 규모 소량)
- [x] 시험 통과 후 전체 활성 뉴스 인덱싱  (2,940 docs / 3,112 chunks, 실패 0, 재실행 복구, 제외 0)
- [x] 신규 사건 증분 인덱싱을 스케줄러(summary/verify 후)에 자동 연결
- [x] 증분 인덱싱: content_hash skip / 예외 격리 / rag_ingestion_runs 기록
- [x] 동시실행 방지: PostgreSQL advisory lock(프로세스·인스턴스 간) + threading.Lock fallback
- [x] 자동 반영·재실행 skip·실패 격리·advisory lock 테스트 추가  (87 passed)
- [x] .DS_Store Git 추적 제거 확인 + backend/.gitignore 재무시 규칙 추가

## 기본 답변 형식

```markdown
## 한 줄 결론

## 쉽게 설명하면

## 자세히 보면

## 핵심 숫자

## 주의할 점
```

규칙:

- 쉬운 설명과 자세한 설명은 같은 근거와 한 번의 모델 호출에서 생성한다.
- 쉬운 설명은 2~4문장 정도로 작성한다.
- 자세한 설명은 근거와 숫자의 성격을 포함한다.
- 관련 숫자가 없는 질문이면 `핵심 숫자`는 생략할 수 있다.
- 주의할 내용이 없으면 `주의할 점`은 짧게 처리하거나 생략할 수 있다.
- 출처 목록은 별도의 `sources` 배열로 반환한다.

## 유연하게 판단할 부분

- 답변 제목은 UI에 맞게 조금 변경할 수 있다.
- 단순 용어 질문처럼 짧은 질문은 일부 구역을 생략할 수 있다.
- 청크 길이와 검색 개수는 실제 결과를 보고 조정할 수 있다.
- 스트리밍 형식은 기존 프런트 구조에 맞출 수 있다.

## 최소 통과 조건

- 현재 뉴스 질문에서 해당 사건이 상위 검색 결과에 포함됨
- 답변에 출처가 표시됨
- 존재하지 않는 인용 번호를 만들지 않음
- 관련 없는 대표 기사 추천 문구가 검색되지 않음
- 사용자가 첫 응답을 빠르게 볼 수 있음

## 산출물

```text
backend/docs/rag/phase_2/PHASE_2_NEWS_RAG.md   (기준 문서)
backend/docs/rag/phase_2/PHASE_2_COMPLETION.md (완료 보고서)
backend/docs/rag/phase_2/trial_100_result.json (100건 시험 결과)
app/rag/{normalization,chunking,indexing,retrieval,prompting}.py
app/ml/{embeddings,generation}.py, app/services/rag_qa.py, app/schemas/qa.py
app/api/routes/qa.py, migrations/0016_rag_search_semantic.sql
scripts/rag_phase2_trial.py, tests/unit/test_rag_phase2.py
```

## Phase 종료 기록

```text
상태: 완료 (100건 검증 + 전체 인덱싱)
완료일: 2026-07-22
시험 인덱싱 건수: 100 (청크 109)
최종 인덱싱 건수: 2,940 docs / 3,112 chunks (활성 2,940 전부, 실패 0, 제외 0)
평균 응답 시간: 검색 ~0.1s + 생성 ~3.9s
첫 토큰 시간: SSE 스트리밍 즉시
비용: 전체 임베딩 ~$0.10 추정(약 107만 토큰). 재실행은 해시 skip으로 0
답변 포맷 변경 사항: 없음(계획서 형식 유지)
남은 문제:
  1) 신규 사건 증분 인덱싱 스케줄러 연결 — 구현 완료 (app/jobs/rag_index_job.py,
     summary/verify 후 자동 호출, content_hash skip, 예외격리, 락, rag_ingestion_runs 기록)
  2) 하이브리드는 Phase 3 (대기)
  (1차 실패 1건=cluster 4748, 임베딩 일시예외 → 개별 재인덱싱 복구, 최종 제외 0)
```

---

# Phase 3. 하이브리드 검색

## 목표

의미 검색과 정확한 키워드 검색을 결합한다.

## 작업 체크리스트

- [x] query embedding 구현
- [x] 의미 검색 후보 조회
- [x] `pg_trgm` 키워드 검색 구현  (word_similarity + ILIKE)
- [x] 제목·본문·종목코드 검색 지원
- [x] 영문 약어·제품명·공시 표현 검색 확인  (HBM/CEO/005930/숫자)
- [x] RRF 순위 결합 구현  (RPC rag_search_hybrid, rrf_k=50)
- [x] 종목 필터
- [x] 날짜 필터
- [x] 출처 종류 필터
- [x] 실제값·전망값 필터  (value_kind 필터, 뉴스엔 미적용이나 RPC 지원)
- [x] 현재 문서 우선 처리  (현재문서 4 + 전체 12)
- [x] 같은 문서 청크 제한  (최대 2)
- [x] 같은 뉴스 사건 중복 제거  (사건당 최대 2)
- [x] 동일 내용 해시 중복 제거  (content_hash)
- [x] 부모 문맥 확장  (앞뒤 청크 배경)
- [x] 문맥 길이 제한  (char budget 12000)
- [x] 의미 검색 단독과 하이브리드 비교  (recall/MRR, scripts/rag_phase3_eval.py)
- [x] 검색 시간 측정  (semantic ~134ms / hybrid ~635ms)

## 유연하게 판단할 부분

- 후보 개수 24는 고정값이 아니다.
- RRF 상수 50은 실험 후 변경할 수 있다.
- 문서당 최대 청크 2개도 질문 유형에 따라 조정할 수 있다.
- 부모 문맥을 section 전체로 가져올지 앞뒤 청크만 가져올지 결과를 보고 선택한다.
- 한국어 키워드 검색이 부족하면 범위가 작은 보완 방식을 제안할 수 있다.

## 최소 통과 조건

- 정확 명칭 질문이 의미 검색 단독보다 나아짐
- 쉬운 표현 질문도 기존 수준 이상 유지
- 중복 자료가 최종 문맥을 독점하지 않음
- 현재 문서 질문이 다른 문서로 과도하게 튀지 않음

## 산출물

```text
backend/docs/rag/phase_3/PHASE_3_HYBRID_SEARCH.md  (기준 문서)
backend/docs/rag/phase_3/PHASE_3_COMPLETION.md      (완료 보고서)
backend/docs/rag/phase_3/eval_result.json + holdout_result.json (비교 평가/홀드아웃)
migrations/0017_rag_hybrid_rrf.sql + 0018_rag_hybrid_lexical_exact_first.sql (+rollback)
app/rag/retrieval.py(HybridRetriever), app/rag/fusion.py
scripts/rag_phase3_eval.py, tests/unit/test_hybrid_fusion.py, test_source_dedup.py
```

## Phase 종료 기록

```text
상태: 완료
완료일: 2026-07-22
semantic 후보 수: 24
lexical 후보 수: 24
RRF 설정: rrf_k=50, semantic_weight=lexical_weight=1.0
최종 문맥 수: 8 (문서·사건당 최대 2)
개선된 질문 사례: 정확명칭 recall@8 최신 0.25→0.92 / 홀드아웃 0.65→0.94 (숫자·RFI·CEO 등 회수)
악화된 질문 사례: SDV(1→5), ASML EUV(1→2) — top-8 유지(recall 손실 없음)
기획서와 달라진 점: 키워드=word_similarity+ILIKE, lexical 정확일치 우선, 부모문맥=앞뒤 청크, fusion.py, 평가토큰 일반화(종목명 제외+DF임계)
하드코딩 여부: 없음. 홀드아웃(offset 200)에서 재현 확인 → 과적합 아님
```

---

# Phase 4. 숫자·용어·혼합 질문

## 목표

정확한 숫자와 설명을 서로 다른 데이터 경로에서 가져와 하나의 답변으로 합친다.

## 작업 체크리스트

- [x] QueryPlan 구현  (app/rag/query_plan.py, 규칙 기반)
- [x] 한 질문에서 복수 작업 선택 지원  (혼합 시 복수 플래그)
- [x] 기존 재무 테이블 어댑터 구현  (facts.py, 읽기 전용)
- [x] 기존 구조화 공시 어댑터 구현  (get_structured_values)
- [x] 최신 정정공시 우선 처리  (is_latest=true, 정정 페어)
- [x] 금융 용어 파싱 또는 import  (한국은행 800선 789개 적재 + 시드 6, 총 795)
- [x] 용어 정확 일치
- [x] 용어 별칭 일치  (순이익→당기순이익 확인)
- [x] 용어 유사 검색  (search_text 부분일치)
- [x] 숫자 조회와 문서 검색 병렬 실행  (ThreadPoolExecutor)
- [x] 실제값·공식값·전망값 라벨 적용  (value_kind)
- [x] 숫자 단위 보존  (원 단위 정수, 표시만 조/억 변환)
- [x] 숫자 출처와 설명 출처 분리  (numeric_sources vs sources)
- [x] 혼합 질문 테스트
- [x] 근거 부족 응답 테스트  (없는 회사 → 확인 불가)

## 필수 시험 질문

- [x] "영업이익이 얼마야?"  (57.23조원, 실제 실적/연결)
- [x] "영업이익이 얼마고 왜 늘었어?"  (숫자 SQL + 설명 RAG 병렬)
- [x] "ADR이 뭐야?"  (term=ADR 시드 조회)
- [x] "정정 전과 정정 후 뭐가 바뀌었어?"  (최신 정정본 기준)
- [x] "이 공시가 왜 중요해?"  (관련 공시 설명, 출처 8)

## 유연하게 판단할 부분

- 첫 버전의 QueryPlan은 규칙 기반으로 구현해도 된다.
- 규칙이 복잡해지면 작은 LLM 분류를 추가 제안할 수 있다.
- 모든 재무 항목을 한 번에 지원하지 않고 자주 묻는 항목부터 구현할 수 있다.
- 용어 별칭은 평가 중 발견되는 항목을 추가할 수 있다.

## 최소 통과 조건

- 정확한 숫자를 문서 검색 결과에서 임의 선택하지 않음
- 혼합 질문이 숫자 조회와 설명 검색을 모두 사용함
- 전망값을 실제값처럼 표현하지 않음
- 정정 전 값을 최신값처럼 답하지 않음

## 산출물

```text
backend/docs/rag/phase_4/DATA_SURVEY.md          (사전 데이터 조사)
backend/docs/rag/phase_4/PHASE_4_NUMERIC_TERMS.md (기준 문서)
backend/docs/rag/phase_4/PHASE_4_COMPLETION.md    (완료 보고서)
backend/docs/rag/phase_4/trial_result.json        (필수 질문 검증)
app/rag/query_plan.py, app/services/facts.py, app/services/rag_qa_facts.py
app/rag/prompting.py(facts/term 블록), scripts/seed_rag_terms.py, scripts/rag_phase4_trial.py
tests/unit/test_query_plan.py, test_facts_format.py
```

## Phase 종료 기록

```text
상태: 완료
완료일: 2026-07-22
지원하는 숫자 항목: 매출액·영업이익·당기순이익·자산/부채/자본총계·영업/투자/재무활동현금흐름 (연결, 원 단위)
지원하는 공시 유형: 정기보고서·주요사항(구조화 값+요약), 정정공시 최신본, 일정성 이벤트
등록된 용어 수: 795 (한국은행 경제금융용어 800선 789 canonical entry + 시드 6)
용어 적재: 0019 컬럼확장 + load_bok_terms.py, 789 임베딩(solar-embedding-2, ~$0.016), 재실행 skip
혼합 질문 결과: 숫자 SQL + 설명 RAG 병렬 사용, 인용 오류 0, 필수 질문 5개 통과
기획서와 달라진 점: PyMuPDF 좌표+목차 기반 파서, related_terms 컬럼 추가, 조사 접미사 제거, account 신호어 매핑
남은 지원 범위: 별도재무·2023 이전·주가(Phase6) 미지원, 단독 숫자질문 기간 표기 튜닝
기존 데이터: DART·재무·공시 전부 읽기 전용(SELECT, 무변경). 신규 쓰기는 rag_terms(795)뿐
```

### 변경 기록 — 결정론적 QA 라이브 경로 (Phase 5 선결 작업, 2026-07-24)

```text
발견: Phase 4 의 QueryPlan/FactsQaService(숫자·용어·혼합 결정론적 경로)는
      구현·테스트만 되고 실제 QA API(qa.py)에는 미연결이었다.
      라이브 /qa 는 RagQaService(뉴스 하이브리드 검색 전용)만 서빙하고 있었다.
조치: qa.py 단일 진입점을 FactsQaService 로 전환(진입점 하나 유지).
      QueryPlan 판정으로 순수 뉴스→기존 검색 재사용, 숫자→SQL, 용어→lookup,
      혼합→결합. FactsQaService.stream() 추가(생성만 스트리밍).
      QaResponse 에 numeric_sources·term 선택 필드 추가(기존 필드 유지, 비파괴).
      RagQaService 는 삭제하지 않고 유지(validate_citations 및 참조 보존).
검증: 전체 136 테스트 통과(신규 통합 7개 포함), ruff·format 통과.
결과: 결정론적 QA 라이브 경로 완료. Agentic·Tool Registry·MCP·A2A 는 미구현(범위 밖).

후속 수정(2026-07-24): QueryPlan need_documents 규칙을 의도 신호 기반으로 정정.
  이전에는 need_financials 이면 문서 검색을 항상 켜서 순수 숫자 질문도 뉴스 검색을
  유발했다. 이제 설명/정정 신호가 있거나(켬), 사실 신호(숫자/용어)가 없는 자연어
  질문일 때만 문서 검색을 켠다. 순수 숫자→SQL만, 순수 용어→용어만(뉴스 검색·임베딩
  호출 없음). 질문 문장 하드코딩 없이 신호 조합으로만 판정. 전체 143 테스트 통과.
한국은행 자료 이용범위: 공개·상용 출시 전 확인 필요(개방 라이선스 미명시), 원본 PDF는 Git 제외
```

---

# Phase 5. 증권사 리포트

## 목표

리포트의 본문과 표를 검색하고 정확한 페이지 출처를 제공한다.

## 작업 체크리스트

- [ ] 로컬 리포트 입력 폴더를 환경변수 또는 CLI 인자로 받기
- [ ] 로컬 PDF 파일 목록과 대상 종목 확인
- [ ] PDF 파일 해시 계산
- [ ] 비공개 Storage 업로드
- [ ] 중복 업로드 방지
- [ ] 대표 PDF 10개 파싱
- [ ] 페이지별 텍스트 저장
- [ ] 페이지별 구조 요소 저장
- [ ] 반복 머리말·꼬리말 제거
- [ ] Compliance Notice 제외
- [ ] 첫 페이지 핵심 메타데이터 추출
- [ ] 투자의견 추출
- [ ] 목표주가 추출
- [ ] 기준주가 추출
- [ ] 본문 소제목 구조 복원
- [ ] 본문 청킹
- [ ] 표 제목 추출
- [ ] 표 단위 추출
- [ ] 표 행·열 저장
- [ ] A/E/F 실제·전망 구분
- [ ] 표 조회 Repository 구현
- [ ] 페이지 출처 연결
- [ ] 차트 숫자 추측 방지
- [ ] 실패 PDF 목록 저장
- [ ] 실제 처리 비용 측정
- [ ] 전체 예상 비용 계산
- [ ] 대표 10개 결과 보고
- [ ] 승인 후 전체 PDF 처리

## 유연하게 판단할 부분

- 텍스트형 PDF는 로컬 파서로 처리할 수 있다.
- 표·OCR이 필요한 PDF만 Upstage를 사용할 수 있다.
- 목표주가 추출 실패는 null로 저장하고 검수 대상으로 보낼 수 있다.
- 표 복원이 불안정하면 본문 검색만 활성화할 수 있다.
- 모든 차트를 MVP에 넣을 필요는 없다.
- PDF 244개 전체 처리보다 발표 대상 종목의 최신 문서를 우선할 수 있다.

## 최소 통과 조건

- 리포트 제목·증권사·날짜·페이지를 연결할 수 있음
- 실제값과 전망값을 구분할 수 있음
- 표의 단위를 잃지 않음
- 파싱이 불확실한 숫자를 확정값처럼 답하지 않음
- 비용이 프로젝트 한도 안에 있음

## Phase 종료 기록

```text
상태: 적재 완료(QA 연결·리포트 검색 연결은 미진행 — 지시에 따름)
완료일: 2026-07-24
시험 PDF 수: 14(2단계 대표) + 6(파서 회귀)
전체 처리 PDF 수: 244 (success 243 / partial 1 / failed 0, 오류 0)
사용한 파서: app/rag/report_parser.py(PyMuPDF 좌표+find_tables, 로컬 파서. OCR 미사용)
적재 결과: research_reports 244, pages 1877, tables 1937,
  rag_documents(report) 244, rag_chunks(report) 4351
표 value_kind(DB): unknown 547 / forecast 254 / mixed 187 / actual 12
투자의견 추출: 1p 규칙 추출(목표주가 numeric 추출은 후속 검수 대상)
OCR 대상 수: 0 (partial 1건은 스캔형이나 OCR 미적용, 발표/검색 제외 후보)
실제 임베딩 비용: ~$0.22 (본문 청크 4351, solar-embedding-2-passage)
재실행 skip: content_hash 동일 시 재임베딩 0 (3건 재실행 검증)
사람이 확인할 항목: 목표주가 numeric 파싱, 키움류 표 소수점 토큰(값 손실 0),
  partial 1건 발표 제외 여부
```

### 변경 기록 — 파서 규칙 확정 + 적재 (2026-07-24)

```text
키움 병합셀 재정렬(_resplit_merged)·소수점/콤마 정규화(normalize_cell) 일반 규칙 추가.
원문 대조는 콤마·공백 무시 비교로 정정. 값 손실 0 확인(재정렬이 값 보존).
A/E/F 토큰 단위 value_kind 합계 = aef_value_total 일치 확인(정의상 일치).
표 단위 value_kind 는 DB CHECK(actual/forecast/mixed/unknown)에 맞춰 매핑
  (열별 estimate/guidance 세부는 metadata·col 분류로 보존, 표 단위는 mixed/forecast 로 집계).
파서 app/rag/report_parser.py 로 재사용화. 적재 scripts/load_research_reports.py
  (Storage 업로드 + reports/pages/tables + 본문 임베딩, file_hash 멱등·재시작·재실행 skip).
QA 연결·Agentic·MCP 미진행(지시).
```

### 검증 기록 — QA 연결 전 확인 (2026-07-24)

```text
1) partial 리포트 1건: reports/pages/tables 에는 저장하되 본문 임베딩·검색에서 제외.
   최초 적재 시 차트 축 텍스트 조각 1청크가 임베딩됐던 것을 발견 → 해당 문서/청크를
   is_active=false·is_current=false 로 비활성화(활성 report 청크 4351→4350).
   재발 방지: 적재 스크립트가 parse_status='success' 인 리포트만 본문 임베딩하도록 수정.
2) report rag_chunks NULL embedding = 0.
3) Storage 객체 = 244 (research-reports-private, 모든 stock_code 폴더 합).
4) research_report_tables 총 count = 1937. "1000" 은 PostgREST 기본 조회 limit 때문에
   select() 가 1000행만 반환한 것(데이터 차이 아님). range 로 전량 집계 시
   unknown 1112 / forecast 469 / mixed 344 / actual 12 = 합 1937 로 일치.

A/E/F 6063 과 표 단위 value_kind 집계의 기준 차이:
- aef_value_total(6063) = 본문+표 텍스트에서 A/E/F '토큰 출현 횟수'(2025A·2026E·2027F …
  개별 등장 수). 한 표의 한 열에 같은 A/E/F 가 여러 행에서 반복 출현하므로 수가 크다.
- research_report_tables.value_kind(합 1937) = '표 1개당 1건'의 표 단위 분류
  (열들의 kind 를 actual/forecast/mixed/unknown 으로 요약). 집계 대상 단위가 다르다
  (토큰 vs 표). 따라서 두 수는 정의상 일치할 수 없으며 비교 대상이 아니다.
- 토큰 단위 value_kind 합(actual/estimate/forecast) 은 aef_value_total 과 일치함을
  파서 회귀(phase5_verify_parser.py)에서 별도 확인.
```

### 완료 기록 — 검색·QA 연결 (2026-07-24)

```text
search_research_reports(app/services/research_reports.py): HybridRetriever 재사용
  (source_type=research_report). RPC 가 is_active·is_current 강제 → partial·NULL emb 제외.
  stock_code·발행일 필터(RPC), 증권사 필터(후처리). 제목·증권사·발행일·투자의견·
  page_number·pdf_page·source_page·표 value_kind 반환. 전망값을 실적으로 표현 안 함.
검색 품질: 5개 유형(정확명칭·자연어·전망·목표주가·실적원인) Recall@8=100%(25/25),
  타종목 혼입 0, 출처페이지 유효 40/40.
QA 연결: QueryPlan need_reports 추가(report intent 독립 판정). FactsQaService 병렬
  조회에 리포트 추가. QaResponse.report_sources 비파괴 확장. 세 의도(financial/news/
  report) 독립 판정으로 과호출 제거('목표주가' 만으로 SQL·뉴스 자동 안 켜짐).
QA 응답 계약: 비파괴(선택 필드만 추가). Agentic·Tool Registry·MCP 미진행.
```

---


---

# 변경 기록

| 날짜 | 변경 | 이유 | 영향 |
|---|---|---|---|
| 2026-07-24 | 키워드 QueryPlan을 메인 라우터에서 제거하기로 결정 | 부정·제외 범위를 단어 규칙으로 처리할 수 없음 | Phase 5.5 추가 |
| 2026-07-24 | LangChain v1 `create_agent` 채택 | 표준 Agent harness, custom 최소화 | LangGraph runtime 사용 |
| 2026-07-24 | custom StateGraph 제외 | 현재 Tool 수와 작업에 불필요 | 유지보수 범위 축소 |
| 2026-07-24 | 모든 질문을 단일 Agent로 처리 | simple/complex 분류 하드코딩 제거 | Tool 0..N 동적 호출 |
| 2026-07-24 | legacy QueryPlan fallback 제외 | 잘못된 경로로 조용히 오답 생성 가능 | 명시적 오류/근거 부족 우선 |
| 2026-07-24 | CRAG·Self-RAG 명목 구현 제외 | 연구 구조를 억지로 복제하지 않음 | bounded Agent retry만 사용 |
| 2026-07-24 | reranker 평가 게이트 도입 | 무조건 추가 시 지연·메모리 위험 | 홀드아웃 개선 시만 활성화 |

---

## 부록: 기존(Extension 계획 시기) 변경 기록

기획서와 구현이 달라질 때 아래 표를 추가한다.

| 날짜 | Phase | 원래 계획 | 실제 구현 | 변경 이유 | 영향 | 사용자 결정 필요 |
|---|---|---|---|---|---|---|
| 2026-07-22 | 0 | 임베딩 4096(구 alias) | solar-embedding-2 1024 | 구 alias 2026-08-31 종료 | 인덱스 차원 1024 확정, BGE-M3와 혼용 금지 | 아니오 |
| 2026-07-22 | 0 | 산출물 backend/artifacts/ | backend/docs/rag/phase_0/ | 사용자 지시 | 경로만 변경 | 아니오 |
| 2026-07-22 | 5(선반영) | 로컬 파서로 표/본문 복원 | 로컬 pdftotext는 페이지/단위만, 표·본문은 Upstage 보강 예정 | 한국어 조판 순서 불안정 | Phase5 파서 조합 확정 필요 | 아니오 |
| 2026-07-22 | 1 | uuid=extensions.uuid_generate_v4() | gen_random_uuid() | 스키마접두어 불필요·이식성 | 기능 동일 | 아니오 |
| 2026-07-22 | 1 | rag_chunks denorm은 선택 | stock_code/source_type/published_at/value_kind 저장 | 계획서 체크리스트·필터 성능 | 인덱싱이 정합성 유지 | 아니오 |
| 2026-07-22 | 1 | RLS 정책 부여 | enable만(정책 없음, 기존 관례) | service_role 우회 아키텍처 | 익명 차단, 공개 API 시 재검토 | 아니오 |
| 2026-07-22 | 1 | Storage를 SQL로 | create_rag_storage.py(API) | 버킷은 DDL 대상 아님 | 0015는 RLS만 | 아니오 |
| 2026-07-22 | 2 | (검색 방식 미명시) | 의미검색 RPC rag_search_semantic 추가(0016) | PostgREST로 pgvector 연산 곤란 | Phase3 하이브리드 기반 | 아니오 |
| 2026-07-22 | 2 | 문서 중복 판단 | content_hash=청크 결합 해시 | 사건 내용 변경 시만 재임베딩 | 비용 절감 | 아니오 |
| 2026-07-22 | (운영) | 클러스터링 시 즉시 요약 | NEWS_SUMMARY_ENABLED=false 기본, 요약 지연+날짜별 수동 요약(summarize_v2.py) | 서비스 미운영 중 요약 LLM 비용 절감 | 스케줄러 요약 호출 0, 나중에 원하는 날짜부터 요약 | 예(사용자 요청) |
| 2026-07-22 | 2 | RAG 인덱싱 수동 실행 | 스케줄러 summary/verify 후 증분 인덱싱 자동 연결(app/jobs/rag_index_job.py) | 신규 사건 자동 반영 | content_hash skip·예외격리·락·ingestion_runs 기록 | 예(사용자 요청) |
| 2026-07-22 | 2 | 동시실행 방지=threading.Lock | PostgreSQL advisory lock(psycopg 런타임 추가) + threading fallback | 배포 시 단일 프로세스 미보장(멀티워커/인스턴스 가능) | 프로세스·인스턴스 간 중복 인덱싱 방지 | 예(사용자 요청) |
| 2026-07-22 | 3 | 키워드=전체 similarity(%) | word_similarity(<%) + ILIKE 부분일치 | 긴 문서·짧은 쿼리에서 %가 threshold 미달로 매칭 0 | 정확명칭/약어 회수 개선 | 아니오 |
| 2026-07-22 | 3 | 부모문맥=section 범위 | 뉴스엔 section 없어 앞뒤 청크(±1)로 확장 | 뉴스 사건 구조상 | 배경 문맥 추가, 인용은 핵심 청크 기준 | 아니오 |
| 2026-07-22 | 3 | lexical=word_similarity 단일 | 정확 부분일치(ILIKE) 우선 → word_similarity 2단계 | 완전일치가 근사유사와 뒤섞여 밀림 | 정확명칭 recall 대폭↑(전체 공통 규칙, 하드코딩 없음) | 아니오 |
| 2026-07-22 | 3 | (개선을 0017 파일 수정) | 0018 신규 마이그레이션에서 CREATE OR REPLACE로 분리 | 0017이 DB에 이미 적용된 이력 보존 | 이력 무수정, 롤백 시 0017로 복원 | 아니오 |
| 2026-07-22 | 3 | 평가 정확명칭=제목 토큰 | 종목명 조각 제외 + 코퍼스 DF 임계로 변별력 토큰만 | 초빈도 조각(SK/AI)은 정확명칭 아님 | 공정 평가, 홀드아웃 재현 | 아니오 |
| 2026-07-22 | 4 | 금융용어 외부 사전 import | 소량 시드 6개(rag_terms 데이터) | 소량 검증 우선, 사전 파일 부재 | 추후 한국은행 사전 등 확장 | 아니오 |
| 2026-07-22 | 4 | (용어 후보 추출 미정) | 한국어 조사 접미사 제거 규칙 | 'ADR이'처럼 조사가 붙음 | 일반 규칙(특정 용어 하드코딩 아님) | 아니오 |
| 2026-07-22 | 4 | 용어 시드 6개만 | 한국은행 800선 789개 전체 적재(0019 컬럼확장) | 사용자 승인 후 전체 적재 | rag_terms 795, 임베딩 789 | 예(사용자 요청) |
| 2026-07-22 | 4 | 파서 미정 | PyMuPDF 좌표+폰트+목차 기반 파서 | 2단 컬럼·수식·그래프 정확 파싱 | scripts/parse_bok_terms.py, 원본 PDF Git 제외 | 아니오 |

## 변경 판단 기준

### 사용자 확인 없이 변경 가능

- 파일 구조 정리
- 함수·클래스 이름 변경
- 테스트 방식 변경
- 작은 성능 최적화
- 후보 개수·캐시 시간 조정
- 실제 코드 스타일에 맞춘 타입 변경
- UI 내부 컴포넌트 분리

### 반드시 사용자 확인

- 지원 데이터 종류 삭제
- 하이브리드 검색을 다른 방식으로 대체
- 실제값·전망값 구분 정책 변경
- 리포트 원본 공개 범위 변경
- 외부 유료 서비스 추가
- 예상 비용이 크게 증가
- 답변 포맷 대폭 변경
- 기존 DB 테이블 변경 또는 삭제
- 발표 핵심 기능 제외

---


---

# Claude Code에 줄 Phase 5.5 시작 명령

```text
docs/rag/RAG_IMPLEMENTATION_SPEC.md,
docs/rag/RAG_GUIDE_FOR_OWNER.md,
docs/rag/RAG_EVALUATION_PLAN.md,
docs/rag/RAG_PHASE_EXECUTION_PLAN.md를 전체 읽어라.

현재는 Phase 5.5-A 의존성과 모델 preflight만 수행해라.

중요:
- 기존 키워드 QueryPlan에 규칙을 추가하지 마라.
- 특정 질문·기업·평가 사례 하드코딩 금지.
- custom StateGraph를 만들지 마라.
- LangChain v1 create_agent와 공식 Upstage integration 호환성을 먼저 검증해라.
- 실제 Tool Calling, 연속 Tool 호출, 스트리밍, 한국어 부정·제외 표현을 시험해라.
- 비밀키를 출력하지 마라.
- 코드·DB 라이브 경로는 아직 변경하지 마라.
- 정확한 패키지 버전을 uv.lock에 고정할 제안과 결과를 보고해라.
- 완료 후 다음 단계로 넘어가지 말고 기다려라.
```
