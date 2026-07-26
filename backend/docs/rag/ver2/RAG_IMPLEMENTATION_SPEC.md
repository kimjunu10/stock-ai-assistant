# RAG_IMPLEMENTATION_SPEC.md

## 0. 문서 목적

이 문서는 `stock-ai-assistant`의 최종 RAG 구현 명세다.

기존 Phase 0~5 구현을 유지하면서, 키워드 기반 `QueryPlan`을 제거하고 표준 LangChain Agent 실행 구조로 전환한다.

최종 목표:

1. 사용자의 자연어 질문에서 포함·제외·부정·기간·출처 제한을 이해한다.
2. 정확한 숫자는 검증된 SQL Tool로만 조회한다.
3. 뉴스·공시·증권사 리포트는 기존 하이브리드 검색을 재사용한다.
4. 한 Agent가 필요한 Tool을 선택하고 결과를 확인하며 답한다.
5. 특정 질문·기업·평가 사례를 위한 라우팅 하드코딩을 사용하지 않는다.

---

# 1. 현재 구현 상태

## 완료

```text
Phase 0 사전 검증
Phase 1 RAG DB·Storage·Repository
Phase 2 뉴스 RAG
Phase 3 semantic + lexical + RRF 하이브리드 검색
Phase 4 재무 SQL·금융용어·혼합 QA
Phase 5 증권사 리포트 적재·검색·QA 연결
```

현재 데이터:

```text
뉴스 사건 RAG 청크
DART 원문·구조화 공시
재무 financials
금융용어 rag_terms
증권사 리포트 244개
리포트 페이지 1,877
리포트 표 1,937
활성 리포트 검색 청크 4,350
```

## 교체 대상

```text
app/rag/query_plan.py
키워드 기반 need_* 판정
FactsQaService의 QueryPlan 실행 분기
```

## 유지 대상

```text
FactsService
HybridRetriever
ResearchReportService
뉴스·DART·리포트 Repository
인덱싱·청킹·RRF
출처 변환
FastAPI·SSE
```

---

# 2. 최종 아키텍처

정확한 명칭:

> **Single-Agent Tool-Calling Agentic Hybrid RAG**

```text
POST /qa 또는 /qa/stream
        ↓
Agent Runtime Context
- stock_code
- current source_type/source_id
- current report page
- conversation_id
        ↓
LangChain create_agent
        ↓
Agent model
        ↓
Tool call 0..N
├─ get_financial_facts
├─ lookup_financial_term
├─ search_news
├─ search_disclosures
├─ get_disclosure_values
├─ search_research_reports
├─ get_stock_prices             Phase 6
└─ calculate_event_return       Phase 6
        ↓
기존 Service·Repository
        ↓
Tool 결과 관찰
        ↓
추가 Tool 필요 여부 판단
        ↓
최종 답변
        ↓
숫자·인용·출처 validator
        ↓
API 응답
```

---

# 3. 기술 선택

## 3.1 Agent

```text
LangChain v1 `langchain.agents.create_agent`
```

이유:

- LangChain v1의 표준 Agent 인터페이스
- LangGraph runtime 기반
- Tool loop를 직접 구현하지 않음
- middleware 조합 가능
- 스트리밍과 상태 지원
- Tool이 적은 단일 Agent에 적합

## 3.2 LangGraph

직접 `StateGraph`를 작성하지 않는다.

`create_agent`가 내부적으로 생성하는 LangGraph graph를 사용한다.

직접 Graph API를 쓰는 조건:

```text
create_agent로 표현할 수 없는 승인·장시간 작업·복잡한 병렬 상태가
실제 요구사항으로 확인된 경우
```

현재 범위에는 해당하지 않는다.

## 3.3 Upstage

공식 LangChain integration을 사용한다.

```python
from langchain_upstage import ChatUpstage
```

단, Agent 전환 전 현재 모델의 Tool Calling을 실제 검증한다.

검증 항목:

- 단일 Tool call
- 연속 Tool call
- 병렬 Tool call 지원 여부
- Tool result 후 추가 Tool call
- Tool call streaming
- 한국어 제외 조건
- LangChain `create_agent` 호환

통과하지 않으면 별도 `AGENT_CHAT_MODEL`을 사용한다. 생성 모델과 Agent 모델을 환경변수로 분리한다.

```env
AGENT_CHAT_PROVIDER=upstage
AGENT_CHAT_MODEL=
ANSWER_CHAT_MODEL=
```

모델 공급자를 코드에 고정하지 않는다.

## 3.4 패키지

주요 버전 계열:

```text
langchain 1.x
langgraph 1.x
langchain-upstage
langsmith
```

정확한 버전은 Phase 5.5 preflight에서 호환성 테스트 후 `uv.lock`에 고정한다. 범위가 넓은 무제한 버전을 운영에 사용하지 않는다.

---

# 4. 하드코딩 정책

## 4.1 금지

```text
if question == "..."
if "영업이익" in question: need_financials = True
회사명별 라우팅 분기
평가 질문별 예외
특정 문서 ID 강제
미분류 → 뉴스 기본 검색
단순/복합 키워드 분류
```

## 4.2 허용·필수

```text
Tool JSON Schema
DART 공식 코드
재무 기간 의미
단위 변환
정정 최신본
actual/forecast
읽기 전용 권한
호출 제한
timeout
검색 전역 설정
```

## 4.3 별칭

회사명·종목코드·금융용어 별칭은 코드 조건문이 아니라 마스터 데이터로 관리한다.

예:

```text
삼성전자 ↔ 005930
순이익 ↔ 당기순이익
```

---

# 5. Runtime Context

UI와 API에서 이미 알고 있는 정보를 모델이 다시 추측하지 않도록 context로 전달한다.

```python
from dataclasses import dataclass

@dataclass
class QaRuntimeContext:
    stock_code: str | None
    source_type: str | None
    source_id: str | None
    document_id: str | None
    report_page: int | None
    conversation_id: str | None
```

원칙:

1. UI `stock_code`가 있으면 Tool 기본 종목으로 사용한다.
2. 질문에서 사용자가 다른 종목을 명시하면 Agent가 해당 종목을 선택할 수 있다.
3. 현재 문서 context를 검색 Tool에 자동 주입할 수 있다.
4. context는 ToolRuntime을 통해 Tool이 접근한다.
5. 모델이 임의 종목을 고르면 안 된다.

---

# 6. Tool 공통 계약

## 6.1 결과

```python
class ToolResult(BaseModel):
    status: Literal["ok", "no_data", "error"]
    data: dict | list
    sources: list[SourceRef]
    warnings: list[str] = []
```

## 6.2 SourceRef

```python
class SourceRef(BaseModel):
    source_id: str
    source_type: Literal[
        "financial",
        "term",
        "news_event",
        "dart_document",
        "structured_disclosure",
        "research_report",
        "price",
    ]
    title: str
    publisher: str | None
    published_at: datetime | date | None
    page: int | None
    url: str | None
    value_kind: str | None
    locator: dict
```

## 6.3 Tool 원칙

- 읽기 전용
- raw exception 미노출
- 결과에 출처 포함
- 숫자에 기간·단위 포함
- `no_data`와 `error` 구분
- 1회 응답 크기 제한
- Tool 내부에서 LLM 답변 생성 금지
- 기존 Service 재사용
- Agent에게 DB schema 노출 금지

---

# 7. Tool 상세

## 7.1 get_financial_facts

```python
class FinancialFactsInput(BaseModel):
    stock_code: str
    account_name: Literal[
        "매출액",
        "영업이익",
        "당기순이익",
        "자산총계",
        "부채총계",
        "자본총계",
        "영업활동현금흐름",
        "투자활동현금흐름",
        "재무활동현금흐름",
    ]
    business_year: int | None = None
    report_period: Literal["q1", "half", "q3", "annual"] | None = None
    amount_type: Literal["quarter", "cumulative", "point_in_time"] | None = None
    fs_div: Literal["CFS", "OFS"] = "CFS"
```

Tool 내부 검증:

```text
annual 손익 → cumulative
q1 손익 → quarter와 cumulative가 동일 기간일 수 있음
half 손익 → quarter 또는 cumulative를 질문 의도대로 선택
q3 손익 → quarter 또는 cumulative를 질문 의도대로 선택
자산·부채·자본 → point_in_time
정확한 행이 없으면 no_data
다른 기간으로 fallback 금지
CFS/OFS 혼합 금지
```

DART 코드:

```text
11013 = q1
11012 = half
11014 = q3
11011 = annual
```

## 7.2 lookup_financial_term

```python
class FinancialTermInput(BaseModel):
    term: str
```

정확 일치 → 별칭 → trigram 순서로 조회한다.

## 7.3 search_news

```python
class SearchNewsInput(BaseModel):
    stock_code: str
    query: str
    date_from: date | None = None
    date_to: date | None = None
    sentiment: Literal["positive", "neutral", "negative"] | None = None
    include_topics: list[str] = []
    exclude_topics: list[str] = []
    current_event_id: str | None = None
    limit: int = Field(default=8, ge=1, le=12)
```

동작:

1. metadata 필터
2. semantic + lexical 후보
3. RRF
4. 중복 제거
5. 현재 사건 우선
6. Tool 인자의 포함·제외 조건을 결과 요약에 명시
7. Agent가 결과를 검토하고 조건 불충족 시 최대 한 번 검색 수정

검색 엔진이 부정 표현을 완벽히 이해한다고 가정하지 않는다. Agent가 Tool 결과를 보고 최종 근거 선택에서 제외 조건을 적용한다.

## 7.4 search_disclosures

```python
class SearchDisclosuresInput(BaseModel):
    stock_code: str
    query: str
    disclosure_types: list[str] = []
    date_from: date | None = None
    date_to: date | None = None
    latest_only: bool = True
    limit: int = Field(default=8, ge=1, le=12)
```

기본 `latest_only=true`.

## 7.5 get_disclosure_values

정확한 공시 금액·날짜·수량은 구조화 DB에서 조회한다.

자유 SQL을 허용하지 않는다.

## 7.6 search_research_reports

```python
class SearchResearchReportsInput(BaseModel):
    stock_code: str
    query: str
    broker: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    actual_or_forecast: Literal["actual", "forecast"] | None = None
    current_report_id: str | None = None
    current_page: int | None = None
    limit: int = Field(default=8, ge=1, le=12)
```

반환:

- 제목
- 증권사
- 발행일
- 투자의견
- 목표주가
- page
- source_page
- value_kind
- snippet

partial 리포트는 제외한다.

## 7.7 Phase 6 Tool

```text
get_stock_prices
calculate_event_return
```

수익률은 백엔드가 계산한다. Agent가 산술하지 않는다.

---

# 8. Agent 생성

개념 코드:

```python
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
    ModelRetryMiddleware,
    ToolErrorMiddleware,
)

agent = create_agent(
    model=agent_model,
    tools=[
        get_financial_facts,
        lookup_financial_term,
        search_news,
        search_disclosures,
        get_disclosure_values,
        search_research_reports,
    ],
    system_prompt=FINANCIAL_AGENT_SYSTEM_PROMPT,
    context_schema=QaRuntimeContext,
    middleware=[
        ModelCallLimitMiddleware(
            run_limit=4,
            exit_behavior="end",
        ),
        ToolCallLimitMiddleware(
            run_limit=5,
            exit_behavior="continue",
        ),
        ToolRetryMiddleware(
            max_retries=1,
            tools=["search_news", "search_disclosures", "search_research_reports"],
        ),
        ModelRetryMiddleware(
            max_retries=1,
        ),
        ToolErrorMiddleware(
            on_error=sanitize_tool_error,
        ),
    ],
)
```

실제 middleware 순서는 preflight에서 공식 동작을 확인하고 고정한다. Tool retry는 네트워크·일시 오류에만 적용한다. `no_data`는 재시도 오류가 아니다.

---

# 9. 시스템 프롬프트 원칙

```text
너는 주식 초보자를 위한 금융 정보 Agent다.

- 사용자의 문장 전체 의미를 해석한다.
- 단어가 등장했다는 이유만으로 Tool을 호출하지 않는다.
- “제외”, “말고”, “아닌”, “빼고”의 범위를 지킨다.
- 기업 데이터와 현재 사실을 답할 때는 반드시 적절한 Tool을 사용한다.
- 정확한 숫자는 Tool 결과만 사용한다.
- 기간·단위·연결/별도·실제/전망을 보존한다.
- 뉴스·공시·리포트를 구분한다.
- 검색 결과가 조건을 충족하지 않으면 한 번까지 검색을 수정할 수 있다.
- 근거가 없으면 없다고 답한다.
- 매수·매도 추천을 하지 않는다.
- 주가 움직임의 인과를 단정하지 않는다.
- 제공된 source_id만 인용한다.
```

금지:

```text
특정 질문 예시를 대량 few-shot으로 넣어 라우팅을 고정
기업별 프롬프트 분기
Tool 호출 순서를 질문 유형별로 강제
```

소수의 형식 예시는 허용하지만 런타임 로직을 대신하게 만들지 않는다.

---

# 10. 검색

기존 `HybridRetriever` 유지:

```text
semantic candidates 24
lexical candidates 24
RRF
metadata filter
document/event limit
content_hash dedup
parent context expansion
final context 6~8
```

출처별 Retriever를 Tool 내부에서 호출한다.

```text
news
dart
research_report
```

하나의 범용 `search_everything` Tool로 합치지 않는다. Tool 이름과 설명이 명확해야 Agent가 출처 제한을 지킬 수 있다.

---

# 11. Reranker 정책

기본 라이브 경로는 현재 RRF다.

Cross-encoder reranker는 평가 후 선택한다.

후보:

```text
BAAI/bge-reranker-v2-m3
```

도입 게이트:

```text
홀드아웃 MRR/Recall 개선
Citation Precision 유지
검색 P95 +300ms 이내
메모리·배포 비용 허용
```

도입 시:

```text
RRF top 24
→ reranker
→ final 8
```

특정 질문 유형에만 임의로 켜지 않는다. source type별 전역 설정은 가능하다.

---

# 12. 최종 답변과 검증

## 12.1 Agent 최종 답변

Agent가 Tool loop 종료 후 답변을 생성한다. 별도 planner LLM과 별도 synthesis LLM을 두지 않는다.

## 12.2 코드 검증

다음은 모델에 맡기지 않는다.

- source_id 존재 여부
- 존재하지 않는 `[n]`
- 숫자가 Tool 결과에 존재하는지
- 단위·기간 메타데이터
- actual/forecast 라벨
- 최신 정정 여부
- Tool call limit

검증 실패:

```text
숫자 주장 제거 또는 응답 실패 처리
근거 부족 경고
trace 기록
```

숫자를 임의 수정하지 않는다.

## 12.3 Groundedness

런타임에 추가 LLM judge를 기본 강제하지 않는다. 먼저 코드 검증과 offline 평가를 사용한다.

Upstage Groundedness Check는 Phase 8 평가와 샘플 검수에 사용한다. 라이브 활성화는 지연·비용 개선이 확인될 때만 한다.

---

# 13. API

기존 엔드포인트 유지:

```text
POST /qa
POST /qa/stream
```

요청:

```json
{
  "question": "최근 호재 알려줘. 실적 관련은 제외해.",
  "stockCode": "005930",
  "context": {
    "sourceType": null,
    "sourceId": null,
    "documentId": null,
    "page": null
  },
  "conversationId": "optional",
  "history": []
}
```

응답 확장:

```json
{
  "answer": "...",
  "sources": [],
  "numericSources": [],
  "reportSources": [],
  "warnings": [],
  "execution": {
    "agent": true,
    "toolCalls": [
      {
        "name": "search_news",
        "status": "ok",
        "latencyMs": 520,
        "resultCount": 8
      }
    ],
    "modelCalls": 2,
    "stopReason": "completed"
  },
  "latencyMs": {}
}
```

`queryPlan` 필드는 한 릴리스 동안 deprecated optional 필드로 유지하고 이후 제거한다.

SSE:

```text
event: agent_start
event: tool_start
event: tool_end
event: sources
event: delta
event: done
event: error
```

모델의 내부 chain-of-thought는 전송하지 않는다.

---

# 14. 대화 상태

초기 전환은 기존 요청의 `history`를 사용할 수 있다.

운영 대화 상태가 필요하면 LangGraph checkpointer를 사용한다.

권장:

```text
langgraph-checkpoint-postgres
conversationId → thread_id
```

비공개 리포트 전체 원문을 state에 누적하지 않는다. Tool 결과는 필요한 메타데이터와 짧은 근거만 보존한다.

---

# 15. Trace와 관찰성

기존 `rag_query_logs` 확장:

```text
request_id
thread_id
question
runtime_context
model_calls
tool_calls
tool_args
tool_status
tool_latency
result_count
source_ids
stop_reason
validation_errors
total_latency
estimated_cost
```

금지:

- 비밀키
- raw DB connection
- 모델 내부 추론 전문
- 전체 비공개 PDF 본문

LangSmith는 개발·스테이징에서 선택적으로 사용한다.

---

# 16. 오류 처리

```text
Tool no_data
→ Agent가 근거 부족을 설명

Tool validation error
→ Agent가 인자를 한 번 수정 가능

Tool transient error
→ middleware 1회 재시도

모델 API transient error
→ middleware 1회 재시도

호출 제한 도달
→ 추가 호출 중단, 확보한 근거 범위에서 답하거나 실패

전체 timeout
→ 명확한 일시 오류 응답
```

legacy QueryPlan fallback은 사용하지 않는다.

---

# 17. 보안

- Tool은 read-only credential 사용
- 서비스 역할 키를 모델에 전달하지 않음
- Agent에게 SQL 실행 Tool 미제공
- Storage 원본 URL 미노출
- signed URL은 기존 정책 유지
- Tool error에서 내부 exception 메시지 제거
- 입력·출력 크기 제한
- 주문·계좌·쓰기 기능 없음

---

# 18. 환경변수

```env
# Agent
AGENT_ENABLED=false
AGENT_CHAT_PROVIDER=upstage
AGENT_CHAT_MODEL=
AGENT_MAX_MODEL_CALLS=4
AGENT_MAX_TOOL_CALLS=5
AGENT_TIMEOUT_SECONDS=8
AGENT_MAX_SAME_TOOL_ARGS=1

# Retrieval
RAG_MAX_CONTEXT_CHUNKS=8
RAG_SEMANTIC_CANDIDATES=24
RAG_LEXICAL_CANDIDATES=24
RAG_RRF_K=50

# Reranker
RAG_RERANKER_ENABLED=false
RAG_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RAG_RERANKER_CANDIDATES=24
RAG_RERANKER_TOP_K=8

# Trace
LANGSMITH_TRACING=false
LANGSMITH_PROJECT=stock-ai-assistant-agentic-rag
```

전환은 `AGENT_ENABLED` feature flag로 제어한다. 평가 통과 전 운영 기본값은 false다.

---

# 19. 구현 파일

신규 또는 주요 파일:

```text
backend/app/agent/context.py
backend/app/agent/prompts.py
backend/app/agent/runtime.py
backend/app/agent/middleware.py
backend/app/agent/tools/common.py
backend/app/agent/tools/financials.py
backend/app/agent/tools/terms.py
backend/app/agent/tools/news.py
backend/app/agent/tools/disclosures.py
backend/app/agent/tools/reports.py
backend/app/agent/tools/prices.py
backend/app/services/agent_qa.py
backend/tests/agent/
backend/scripts/agent_preflight.py
backend/scripts/evaluate_agent.py
```

수정:

```text
backend/app/api/routes/qa.py
backend/app/schemas/qa.py
backend/app/core/config.py
backend/pyproject.toml
backend/.env.example
```

legacy:

```text
backend/app/rag/query_plan.py
backend/app/services/rag_qa_facts.py
```

평가 통과까지 보존하되 라이브 전환 후 deprecated 표시한다.

---

# 20. 테스트

## 단위

```text
test_tool_schemas.py
test_financial_tool_contract.py
test_news_tool_filters.py
test_disclosure_latest_only.py
test_report_tool_sources.py
test_tool_result_contract.py
test_citation_validator.py
test_numeric_claim_validator.py
test_agent_limits.py
test_tool_error_sanitization.py
```

## 통합

```text
test_agent_term_single_tool.py
test_agent_financial_single_tool.py
test_agent_news_exclusion.py
test_agent_source_restriction.py
test_agent_financial_news_report.py
test_agent_no_data.py
test_agent_current_context.py
test_agent_stream_events.py
```

LLM Tool 선택은 고정 mock만으로 완료 처리하지 않는다. 실제 Agent 모델을 사용한 offline evaluation을 별도로 실행한다.

---

# 21. Phase 5.5 완료 조건

```text
Tool Calling preflight 통과
모든 Tool read-only
legacy QueryPlan 라이브 미사용
부정·제외 평가 통과
재무 Exact Match 100%
실제/전망 혼동 0
존재하지 않는 인용 0
동일 호출 반복 0
호출 limit 준수
SSE 정상
기존 뉴스·DART·리포트 회귀 없음
```

---

# 22. 제외 기술

```text
직접 만든 custom StateGraph
다중 Agent
Supervisor
A2A
자유 SQL Agent
GraphRAG
Self-RAG
CRAG 명목 구현
Deep Agents
MCP 선행 구현
```

MCP는 Agent와 Tool이 안정화된 후 외부 재사용 요구가 있을 때만 같은 Tool을 노출한다.

---

# 23. 참고 자료

- LangChain overview: https://docs.langchain.com/oss/python/langchain/overview
- LangChain Agents: https://docs.langchain.com/oss/python/langchain/agents
- LangChain Tools: https://docs.langchain.com/oss/python/langchain/tools
- LangChain middleware: https://docs.langchain.com/oss/python/langchain/middleware/built-in
- LangGraph Agentic RAG: https://docs.langchain.com/oss/python/langgraph/agentic-rag
- LangGraph workflows and agents: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- LangChain Upstage integration: https://docs.langchain.com/oss/python/integrations/providers/upstage
- ReAct: https://arxiv.org/abs/2210.03629
- RAG: https://arxiv.org/abs/2005.11401
- RRF: https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf
- BGE-M3: https://arxiv.org/abs/2402.03216
