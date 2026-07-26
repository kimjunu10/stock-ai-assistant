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
| 5.5 | 단일 Agentic RAG 전환 | [ ] | [ ] |
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

## 5.5-A. 의존성과 모델 preflight

- [ ] 새 브랜치 생성
- [ ] LangChain v1·LangGraph v1 호환 버전 조사
- [ ] `langchain-upstage` 현재 호환 버전 조사
- [ ] 작은 별도 환경에서 설치
- [ ] 기존 테스트 실행
- [ ] `ChatUpstage.bind_tools()` 단일 Tool call 검증
- [ ] Tool result 후 추가 Tool call 검증
- [ ] 2개 Tool 연속 호출 검증
- [ ] Tool call streaming 검증
- [ ] 한국어 부정·제외 질문 검증
- [ ] `create_agent` 호환 검증
- [ ] 정확한 버전을 `uv.lock`에 고정
- [ ] 비밀키 미출력
- [ ] preflight 결과 문서화

### 중단 조건

- 현재 Agent 모델이 Tool Calling을 안정적으로 지원하지 않음
- 스트리밍 Tool call이 현재 SSE 계약과 연결 불가
- 패키지 도입으로 기존 테스트 대량 회귀
- 모델 비용·지연이 프로젝트 한도를 크게 초과

중단 시 임의 parser Agent를 만들지 않는다. `AGENT_CHAT_MODEL` 후보를 보고한다.

### 산출물

```text
backend/docs/rag/phase_5_5/AGENT_PREFLIGHT.md
backend/scripts/agent_preflight.py
```

---

## 5.5-B. Tool 계약

- [ ] 공통 `ToolResult` 구현
- [ ] 공통 `SourceRef` 구현
- [ ] `QaRuntimeContext` 구현
- [ ] Tool error sanitize
- [ ] Tool 결과 크기 제한
- [ ] 읽기 전용 확인

### Tools

- [ ] `get_financial_facts`
- [ ] `lookup_financial_term`
- [ ] `search_news`
- [ ] `search_disclosures`
- [ ] `get_disclosure_values`
- [ ] `search_research_reports`

### 검증

- [ ] 기존 Service 재사용
- [ ] Agent가 SQL 문자열을 전달할 수 없음
- [ ] `get_financial_facts` 기간·amount_type 엄격 검증
- [ ] 다른 기간 fallback 없음
- [ ] latest disclosure 기본값
- [ ] partial report 제외
- [ ] 모든 결과에 source metadata

### 산출물

```text
backend/app/agent/context.py
backend/app/agent/tools/
backend/tests/agent/test_tool_*.py
```

---

## 5.5-C. Agent 구현

- [ ] `ChatUpstage` 또는 검증된 Agent model 초기화
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
