# 우리 프로젝트의 최종 RAG 확장 방향

> 문서 상태: 최종 설계안  
> 기준 시점: Phase 5 완료 후  
> 대상 프로젝트: `stock-ai-assistant`

---

## 1. 최종 결론

이 프로젝트는 다음 구조로 구현한다.

> **LangChain `create_agent` 기반 단일 Tool-Calling Agentic Hybrid RAG**  
> **실행 런타임은 LangGraph를 사용하고, 기존 금융 조회·검색 코드는 읽기 전용 Tool로 재사용한다.**

핵심 흐름:

```text
사용자 질문 + 현재 화면 문맥
        ↓
단일 LangChain Agent
        ↓
LLM이 질문 전체 의미를 해석
        ↓
필요한 Tool을 0개·1개·여러 개 선택
        ↓
Tool 결과를 확인하고 필요하면 추가 Tool 호출
        ↓
숫자·기간·실제값/전망값·출처 검증
        ↓
근거가 있는 최종 답변
```

모든 질문은 같은 Agent에 들어간다.

- 별도의 키워드 기반 질문 분류기를 두지 않는다.
- 단순 질문과 복합 질문을 사전에 하드코딩으로 나누지 않는다.
- Agent가 Tool 하나로 충분하다고 판단하면 한 번 호출하고 끝낸다.
- 여러 자료가 필요하면 결과를 보면서 추가 Tool을 호출한다.
- Tool 호출이 필요 없는 인사·UI 도움말은 바로 답한다.

---

## 2. 기존 설계에서 폐기하는 부분

기존 `QueryPlan`은 질문 안의 단어 존재 여부로 다음 값을 켰다.

```text
need_financials
need_news
need_reports
need_terms
need_price
```

이 방식은 다음 질문을 안정적으로 처리하지 못한다.

```text
최근 뉴스에서 삼성전자 호재 있어?
영업이익 같은 실적 관련 내용은 제외해.
```

단어만 보면 `뉴스`, `호재`, `영업이익`이 모두 발견되므로 재무 Tool까지 잘못 실행할 수 있다.  
사용자는 영업이익을 **요청한 것이 아니라 제외한 것**이다.

따라서 다음을 메인 경로에서 제거한다.

```text
키워드·신호어 기반 Tool 선택
완성 문장별 예외 처리
기업별 라우팅 예외
미분류 질문을 뉴스 검색으로 보내는 기본값
단순/복합 질문을 규칙으로 사전 분류하는 로직
```

기존 `QueryPlan`은 회귀 비교용 legacy 코드로만 잠시 보존한 뒤, 새 Agent 평가가 통과하면 라이브 경로에서 제거한다. Agent 실패 시에도 기존 QueryPlan으로 되돌아가지 않는다. 잘못된 경로로 답하는 것보다 근거 부족이나 일시 오류를 명시하는 것이 안전하다.

---

## 3. 왜 이 방식이 표준적인가

이번 설계는 새로운 사설 프레임워크를 만드는 방식이 아니다.

### 3.1 LangChain `create_agent`

LangChain v1의 표준 Agent 생성 인터페이스다.

- 모델
- Tool 목록
- 시스템 지시
- middleware
- 상태와 스트리밍

을 조합해 Agent를 만든다.

`create_agent`는 내부적으로 LangGraph 런타임을 사용한다. 직접 `StateGraph`를 설계하지 않아도 Tool 호출, 결과 관찰, 추가 호출, 종료 흐름을 제공한다.

### 3.2 ReAct / Tool-Calling Agent

Agent가 다음 과정을 반복한다.

```text
질문 이해
→ Tool 호출
→ 결과 관찰
→ 추가 Tool이 필요한지 판단
→ 충분하면 최종 답변
```

이는 ReAct 계열의 일반적인 Agent 실행 패턴이다. 우리 프로젝트는 모델의 내부 추론 전문을 저장하거나 사용자에게 노출하지 않고, Tool 호출과 결과만 trace로 기록한다.

### 3.3 Agentic RAG

뉴스·공시·리포트 검색 Tool을 Agent가 필요할 때 호출하므로 Agentic RAG다.

- 재무 SQL Tool만 호출: Agentic structured-data QA
- 금융용어 Tool만 호출: Agentic lookup QA
- 뉴스·공시·리포트 검색 Tool 호출: Agentic RAG
- SQL과 검색 Tool을 함께 호출: Agentic Hybrid RAG

시스템 전체 명칭은 다음으로 통일한다.

> **금융 데이터 Tool을 사용하는 단일 Agent 기반 Agentic Hybrid RAG**

---

## 4. LangChain과 LangGraph 사용 범위

### 사용한다

```text
langchain.agents.create_agent
langchain Tool 인터페이스
Pydantic Tool 입력 스키마
LangChain middleware
LangGraph 기반 상태·Tool loop·스트리밍
LangGraph checkpointer(대화 상태가 필요할 때)
```

### 직접 만들지 않는다

```text
커스텀 Agent loop
커스텀 planner/replanner
키워드 intent router
직접 만든 조건부 StateGraph
다중 Agent supervisor
Agent 간 A2A
자유 SQL Agent
```

### 기존 구현은 유지한다

```text
FastAPI
Supabase PostgreSQL
pgvector
pg_trgm
RRF
HybridRetriever
FactsService
리포트 파서·페이지·표·청크
뉴스 사건 클러스터
금융용어 DB
출처 및 페이지 메타데이터
SSE API
```

LangChain으로 기존 검색기와 Repository를 다시 작성하지 않는다. 기존 Service를 얇은 Tool로 감싼다.

---

## 5. Tool 목록

현재 Tool은 6개로 시작한다.

```text
get_financial_facts
lookup_financial_term
search_news
search_disclosures
get_disclosure_values
search_research_reports
```

Phase 6에서 다음을 추가한다.

```text
get_stock_prices
calculate_event_return
```

Tool 수가 10개 이하이므로 별도의 Tool Selector Agent나 Tool 검색 middleware는 사용하지 않는다. Tool 설명과 입력 스키마를 정확히 작성해 주 Agent가 직접 선택하게 한다.

각 Tool은 읽기 전용이며 다음 공통 형식으로 반환한다.

```json
{
  "status": "ok | no_data | error",
  "data": {},
  "sources": [],
  "warnings": []
}
```

Agent가 직접 SQL을 생성하지 않는다.

```text
Agent
→ 검증된 Tool 인자
→ 기존 Service
→ 제한된 SQL 또는 검색
```

---

## 6. 질문 예시

### 금융용어

```text
질문: PER이 뭐야?

Agent
→ lookup_financial_term(term="PER")
→ 답변
```

### 정확한 재무 숫자

```text
질문: 삼성전자 2025년 영업이익은 얼마야?

Agent
→ get_financial_facts(
     stock_code="005930",
     account_name="영업이익",
     business_year=2025,
     report_period="annual",
     amount_type="cumulative",
     fs_div="CFS"
   )
→ 답변
```

연간·분기·누적·연결·별도 선택은 Tool 내부의 금융 규칙으로 검증한다. Agent가 DB 행을 임의 선택하지 않는다.

### 제외 조건이 있는 뉴스 질문

```text
질문:
최근 뉴스에서 삼성전자 호재 있어?
영업이익 같은 실적 관련 내용은 제외해.

Agent
→ search_news(
     stock_code="005930",
     query="최근 호재",
     sentiment="positive",
     exclude_topics=["영업이익", "실적"]
   )
→ 검색 결과 확인
→ 제외 조건에 맞지 않는 근거는 답변에서 사용하지 않음
→ 필요하면 검색어를 바꿔 한 번 추가 검색
→ 답변
```

`영업이익`이라는 단어가 있다는 이유로 재무 Tool을 호출하지 않는다. 문장 전체 의미와 Tool 인자 설명을 바탕으로 모델이 판단한다.

### 복합 질문

```text
질문:
삼성전자 영업이익이 왜 줄었고
증권사들은 앞으로 어떻게 전망해?

Agent
→ get_financial_facts
→ search_news 또는 search_disclosures
→ search_research_reports
→ 실제값과 전망값을 분리
→ 답변
```

---

## 7. 하드코딩 정책

### 금지되는 하드코딩

```text
특정 질문 문장과 완전 일치
질문 속 특정 단어만으로 Tool 선택
삼성전자·현대차 등 회사별 예외
평가 실패 질문을 위한 if 문
특정 기사·리포트 ID 강제
미분류 질문의 고정 뉴스 fallback
```

### 반드시 코드로 고정해야 하는 금융 규칙

다음은 하드코딩 문제가 아니라 데이터 계약과 도메인 불변식이다.

```text
DART reprt_code 공식 매핑
annual / quarter / cumulative / point_in_time 의미
CFS / OFS 구분
실제값 / 전망값 구분
정정공시 최신본 우선
원 / 억 / 조 단위 변환
Tool 호출 횟수와 timeout
읽기 전용 권한
```

자연어를 특정 경로로 보내는 규칙과, 데이터의 정확성을 지키는 규칙을 구분한다.

### 설정값

다음은 환경변수 또는 설정 파일로 관리한다.

```text
최대 Tool 호출 수
최대 모델 호출 수
검색 후보 수
최종 문맥 수
timeout
RRF 상수
reranker 활성화 여부
```

특정 질문을 통과시키기 위해 설정값을 바꾸지 않는다. 개발셋에서 조정하고 홀드아웃으로 확인한다.

---

## 8. 검색 방식

기존 하이브리드 검색을 유지한다.

```text
semantic retrieval
+
lexical retrieval
+
RRF
+
metadata filter
+
중복 제거
+
부모 문맥 확장
```

이 구조는 뉴스·공시·리포트별 검색 Tool 내부에 그대로 남는다.

### Reranker

Cross-encoder reranker는 표준적인 2단계 검색 기법이지만 무조건 추가하지 않는다.

```text
현재 HybridRetriever
vs
HybridRetriever + bge-reranker-v2-m3
```

를 홀드아웃에서 비교한 뒤 다음 조건을 모두 만족할 때만 활성화한다.

- Recall@8 또는 MRR이 의미 있게 개선
- Citation Precision이 악화되지 않음
- 검색 P95 증가가 허용 범위 이내
- 배포 메모리와 비용 한도 이내

이 결정 게이트 자체를 최종 설계에 포함한다. 이름을 넣기 위해 무거운 모델을 강제하지 않는다.

---

## 9. 안전장치

LangChain의 prebuilt middleware를 사용한다.

```text
ModelCallLimitMiddleware
ToolCallLimitMiddleware
ToolRetryMiddleware
ModelRetryMiddleware
ToolErrorMiddleware
```

초기 제한:

```text
모델 호출: 질문당 최대 4회
Tool 호출: 질문당 최대 5회
동일 Tool + 동일 인자 반복: 금지
외부 API Tool 재시도: 최대 1회
전체 timeout: 8초
읽기 전용 Tool만 허용
```

다음은 사용하지 않는다.

```text
무제한 ReAct loop
DB 쓰기 Tool
주문 실행 Tool
파일 시스템 Tool
코드 실행 Tool
웹 검색 Tool
다중 Agent
```

---

## 10. Phase 5 이후 구현 순서

```text
Phase 5 승인·머지
        ↓
Phase 5.5 Agentic RAG 전환
  1. LangChain/Upstage Tool Calling 호환성 검증
  2. 기존 Service를 typed Tool로 래핑
  3. create_agent 기반 단일 Agent 구현
  4. prebuilt middleware 적용
  5. /qa·/qa/stream을 Agent 경로로 전환
  6. legacy QueryPlan 라이브 사용 중단
  7. Tool trace·출처·숫자 validator 연결
  8. 개발셋·홀드아웃 평가
        ↓
Phase 6 주가 Tool 추가
        ↓
Phase 7 프런트 연결
        ↓
Phase 8 전체 평가·튜닝
        ↓
Phase 9 배포
```

---

## 11. 사용하지 않는 RAG 이름

### GraphRAG

기업·제품·공급망 관계를 그래프로 탐색하는 기능이 핵심이 아니므로 현재 적용하지 않는다.

### Self-RAG

별도 reflection token 학습을 요구하는 연구 방식이므로 적용하지 않는다.

### CRAG

검색 품질 판정기와 별도 수정 검색 파이프라인을 강제하지 않는다. Agent가 검색 결과를 보고 제한된 범위에서 재검색할 수 있으므로, 초기 구현을 CRAG라고 부르지 않는다.

### Multi-Agent RAG

단일 Agent와 6~8개 Tool로 충분하므로 적용하지 않는다.

---

## 12. 발표용 설명

> 기존에는 질문 안의 키워드를 기준으로 SQL과 검색 경로를 선택했지만, 부정·제외 조건을 잘못 해석할 수 있어 해당 라우터를 제거했습니다. 최종 구조는 LangChain의 표준 `create_agent`와 LangGraph 런타임을 사용한 단일 Tool-Calling Agent입니다. Agent가 질문 전체 의미를 이해해 재무 SQL, 금융용어, 뉴스, 공시, 증권사 리포트 Tool을 선택하고, 결과를 확인한 뒤 필요한 경우에만 추가 Tool을 호출합니다. 기존 하이브리드 검색과 금융 데이터 검증 코드는 읽기 전용 Tool로 재사용하며, 특정 질문이나 기업을 위한 라우팅 하드코딩은 사용하지 않습니다.

---

## 13. 참고 기준

- LangChain Agents: https://docs.langchain.com/oss/python/langchain/agents
- LangChain Tools: https://docs.langchain.com/oss/python/langchain/tools
- LangChain prebuilt middleware: https://docs.langchain.com/oss/python/langchain/middleware/built-in
- LangGraph Agentic RAG: https://docs.langchain.com/oss/python/langgraph/agentic-rag
- LangGraph workflows and agents: https://docs.langchain.com/oss/python/langgraph/workflows-agents
- ReAct paper: https://arxiv.org/abs/2210.03629
- RAG paper: https://arxiv.org/abs/2005.11401
- RRF paper: https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf
- BGE-M3 paper: https://arxiv.org/abs/2402.03216
- Upstage LangChain integration: https://docs.langchain.com/oss/python/integrations/providers/upstage

---

## 14. 한 문장 요약

> **키워드 QueryPlan을 제거하고, LangChain `create_agent`가 기존 금융 SQL·뉴스·공시·리포트 검색 Tool을 직접 선택하는 단일 Agentic Hybrid RAG로 전환한다.**
