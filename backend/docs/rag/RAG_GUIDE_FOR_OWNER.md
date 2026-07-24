# RAG_GUIDE_FOR_OWNER.md

> 대상: 프로젝트 소유자가 최종 RAG 구조와 구현 순서를 이해하기 위한 문서  
> 현재 기준: Phase 5 완료, Agentic 전환 전

---

## 1. 최종적으로 만드는 기능

사용자는 자연스럽게 질문한다.

```text
PER이 뭐야?

2025년 영업이익 얼마야?

최근 호재 알려줘.
실적 관련 내용은 빼고.

영업이익이 왜 감소했고
증권사 전망은 어때?
```

시스템은 질문에 들어간 단어만 세지 않는다.

LLM Agent가 문장 전체 의미를 이해하고 다음 기능 중 필요한 것만 사용한다.

```text
금융용어 조회
재무 SQL 조회
뉴스 검색
공시 검색
구조화 공시값 조회
증권사 리포트 검색
주가 조회
사건 전후 수익률 계산
```

---

## 2. 정확한 이름

> **단일 Tool-Calling Agent 기반 Agentic Hybrid RAG**

쉽게 표현하면:

> AI가 질문을 이해하고, 필요한 자료 조회 기능을 직접 골라 사용한 뒤, 찾은 근거로 답하는 구조다.

---

## 3. 기존 방식과 차이

### 기존 키워드 QueryPlan

```text
영업이익 단어 있음
→ 재무 조회

뉴스 단어 있음
→ 뉴스 검색
```

문제:

```text
“영업이익 같은 실적 관련 내용은 제외해”
```

에서도 영업이익이 발견되므로 재무 조회를 켤 수 있다.

### 새 Agent

```text
영업이익 = 요청 대상이 아니라 제외 대상
최근 뉴스 + 호재만 필요
```

로 해석한다.

실행:

```text
search_news
sentiment=positive
exclude_topics=["영업이익", "실적"]
```

---

## 4. LangChain과 LangGraph가 하는 일

### LangChain

Agent와 Tool을 표준 형식으로 연결한다.

```text
모델
Tool
시스템 프롬프트
middleware
구조화된 Tool 인자
```

### LangGraph

Agent가 다음 과정을 실행하는 런타임이다.

```text
모델 판단
→ Tool 호출
→ 결과 확인
→ 추가 Tool 판단
→ 종료
```

직접 복잡한 그래프를 만들지 않는다. LangChain v1의 표준 `create_agent`를 사용하면 내부적으로 LangGraph가 실행을 관리한다.

---

## 5. 단순 질문도 Agent가 처리하는가

그렇다. 모든 질문은 같은 Agent로 들어간다.

### 단순 질문

```text
PER이 뭐야?
```

Agent:

```text
lookup_financial_term 한 번
→ 종료
```

### 정확한 숫자

```text
2025년 영업이익 얼마야?
```

Agent:

```text
get_financial_facts 한 번
→ 종료
```

### 복합 질문

```text
영업이익이 왜 줄었고 증권사 전망은 어때?
```

Agent:

```text
get_financial_facts
→ search_news 또는 search_disclosures
→ search_research_reports
→ 답변
```

단순·복합 질문을 먼저 규칙으로 분류하지 않는다. Agent가 실제 Tool 호출 수로 자연스럽게 구분한다.

---

## 6. 어떤 부분이 RAG인가

### RAG

```text
search_news
search_disclosures
search_research_reports
```

문서를 검색해 LLM 문맥에 넣는다.

### RAG가 아닌 정확 조회

```text
get_financial_facts
lookup_financial_term
get_disclosure_values
get_stock_prices
calculate_event_return
```

정확한 구조화 데이터를 조회하거나 백엔드가 계산한다.

전체 서비스는 이 둘을 함께 쓰므로 Agentic Hybrid RAG다.

---

## 7. 기존 Phase 5까지 만든 것은 버리지 않는다

유지:

```text
뉴스 사건 클러스터
감성 분류와 중요도
뉴스 하이브리드 검색
DART 원문·구조화 데이터
재무 DB
한국은행 금융용어
증권사 리포트 244개
리포트 페이지·표·검색 청크
pgvector + pg_trgm + RRF
출처·페이지 정보
```

교체:

```text
키워드 QueryPlan
need_news / need_financials / need_reports 신호어 판정
```

추가:

```text
typed Tool
LangChain create_agent
LangGraph runtime
middleware
Tool trace
Agent 평가
```

---

## 8. 하드코딩 여부

### 사용하지 않음

```text
“삼성전자 목표주가 알려줘” 문장 일치
“영업이익” 단어가 있으면 무조건 재무 Tool
특정 회사 질문 예외
평가 실패 사례별 if 문
```

### 반드시 코드에 있어야 함

```text
11013=1분기
11012=반기
11014=3분기
11011=연간

quarter / cumulative / point_in_time
CFS / OFS
actual / forecast
원 / 억 / 조
최신 정정본
```

이것은 자연어 라우팅 하드코딩이 아니라 금융 데이터 정확성을 위한 공식 규칙이다.

---

## 9. 검색 방식

뉴스·공시·리포트는 현재 하이브리드 검색을 유지한다.

```text
의미 검색
+
키워드 검색
+
RRF
+
필터
+
중복 제거
+
부모 문맥 확장
```

Agent는 어느 검색 Tool을 사용할지 결정한다. 검색 Tool 내부 알고리즘은 기존 구현을 재사용한다.

---

## 10. 답변이 만들어지는 예

질문:

```text
삼성전자 2025년 영업이익이 얼마고,
왜 달라졌으며 증권사들은 앞으로 어떻게 봐?
```

실행:

```text
1. get_financial_facts
   → 2025년 공식 연간 영업이익

2. search_news / search_disclosures
   → 변화 배경

3. search_research_reports
   → 증권사 전망

4. Agent 최종 답변
   → 공식 실제값과 증권사 전망 분리
   → 출처 표시
```

Agent가 재무 행을 직접 고르지는 않는다. `get_financial_facts`가 기간과 amount_type을 검증해 정확한 행만 반환한다.

---

## 11. Agent가 마음대로 행동하지 못하게 하는 방법

```text
읽기 전용 Tool만 제공
Tool 최대 5회
모델 최대 4회
전체 timeout
동일 호출 반복 차단
DB 쓰기 금지
자유 SQL 금지
웹 검색 금지
주문 실행 금지
```

LangChain의 표준 middleware를 사용해 호출 수와 재시도를 제한한다.

---

## 12. 왜 다중 Agent를 쓰지 않는가

현재 기능은 하나의 Agent가 6~8개 Tool을 호출하면 충분하다.

다중 Agent를 사용하면:

- 응답이 느려짐
- Agent 간 전달 오류
- 디버깅 어려움
- 비용 증가
- 발표 설명 복잡

이 생긴다.

따라서 다음은 제외한다.

```text
재무 Agent
뉴스 Agent
리포트 Agent
Supervisor Agent
A2A
```

---

## 13. 왜 CRAG·Self-RAG·GraphRAG를 쓰지 않는가

### CRAG

별도 검색 평가기와 수정 검색 경로를 추가하는 방식이다. 첫 구현에는 필요하지 않다. Agent가 검색 결과를 보고 최대 한 번 다시 검색할 수 있다.

### Self-RAG

모델 자체를 reflection token 방식으로 학습하는 연구 구조다. 현재 API 모델에 그대로 적용할 수 없다.

### GraphRAG

기업·제품·공급망 관계를 그래프로 탐색할 때 유용하다. 현재 핵심 기능은 종목별 뉴스·공시·실적·리포트 QA이므로 우선순위가 아니다.

---

## 14. 구현 순서

### 지금

```text
Phase 5 PR 승인·머지
```

### 다음: Phase 5.5

```text
1. 현재 Solar 모델의 Tool Calling 호환성 확인
2. LangChain v1 / LangGraph v1 버전 고정
3. 기존 Service를 Tool로 래핑
4. create_agent 구현
5. 호출 제한 middleware 적용
6. /qa·/qa/stream 전환
7. Tool trace와 출처 검증
8. 실제 질문 평가
9. legacy QueryPlan 라이브 제거
```

### 이후

```text
Phase 6 주가 Tool
Phase 7 프런트 연결
Phase 8 전체 평가
Phase 9 배포
```

---

## 15. 모델 호환성 확인 (5.5-A preflight 완료)

Agent 모델은 반드시 다음을 실제 API로 통과해야 한다.

```text
Tool Calling
여러 Tool 연속 호출
Tool 결과를 보고 추가 호출
스트리밍 Tool Call
한국어 부정·제외 조건
```

**결과(2026-07-24)**: 현재 Solar 모델(`solar-pro3-260323`)이 위 항목을 통과했다.
단, Upstage 전용 패키지(`langchain-upstage`)는 tokenizers 버전이 프로젝트 `transformers`와
충돌하므로 사용하지 않고, **OpenAI 호환 API로 `langchain-openai`의 `ChatOpenAI`에 Upstage
base_url 을 지정**해 사용한다. (기능·모델은 동일, 패키지만 교체.)

```env
AGENT_CHAT_PROVIDER=upstage
AGENT_CHAT_MODEL=solar-pro3-260323
UPSTAGE_BASE_URL=https://api.upstage.ai/v1
ANSWER_CHAT_MODEL=
```

이는 설계 변경이 아니다. Agent 모델 교체가 가능하도록 처음부터 provider-agnostic하게 만드는 것이다.
자세한 preflight 결과는 `docs/rag/phase_5_5/AGENT_PREFLIGHT.md` 참조.

---

## 16. 네가 직접 확인해야 하는 질문

```text
최근 뉴스에서 삼성전자 호재 있어?
영업이익 같은 실적 관련은 제외해.

실적 말고 공급계약 관련 악재만 알려줘.

증권사 전망 말고 회사가 직접 발표한 내용만 알려줘.

2025년 3분기 누적 영업이익과
3분기 단독 영업이익을 구분해줘.

목표주가가 아니라 실제 주가가 얼마나 움직였어?

이 뉴스와 관련된 공식 공시를 찾아줘.

자료에 없으면 없다고 말해.
```

확인:

- 제외한 Tool을 호출하지 않았는가
- 제외한 내용을 답변에 넣지 않았는가
- 숫자 기간이 맞는가
- 실제값과 전망값을 구분했는가
- 출처가 실제 근거인가

---

## 17. 발표 문장

> 저희는 질문 안의 키워드로 검색 경로를 고정하지 않았습니다. LangChain의 표준 Tool-Calling Agent를 사용해 질문 전체 의미와 포함·제외 조건을 해석하고, 재무 SQL·금융용어·뉴스·공시·증권사 리포트 중 필요한 Tool을 선택하도록 했습니다. Agent 실행은 LangGraph 런타임이 관리하며, 기존 하이브리드 검색과 금융 데이터 검증 코드는 읽기 전용 Tool로 재사용했습니다.

---

## 부록 A. 비용 관리 (기존 문서 보존)

> 이 절은 Agentic 전환 전 기존 GUIDE에서 보존한 운영 기준이다. Phase 5.5 이후에도
> Tool 호출 수·모델 호출 수가 늘 수 있으므로 예산 실측이 계속 필요하다.

총예산:

```text
100,000원 이하
```

권장 배분:

```text
PDF 파싱·OCR     최대 30,000원
문서 임베딩       최대 20,000원
개발·평가 질문    최대 30,000원
발표 여유분        최소 20,000원
```

실제 가격이 다를 수 있으므로 Claude/Codex가 API 사용량을 실측해 보고해야 한다.

확인할 것:

- 하루 사용액
- PDF 한 개 평균 비용
- 전체 예상 비용
- 같은 파일을 중복 처리하고 있지 않은지
- (Agentic) 질문당 모델 호출 수·Tool 호출 수·재검색 발생률

실측 기록(Phase별):

```text
Phase 2 뉴스 전체 임베딩 ~$0.10 (약 107만 토큰)
Phase 4 금융용어 789개 임베딩 ~$0.016
Phase 5 리포트 본문 청크 4,351 임베딩 ~$0.22
```

## 부록 B. 화면에서 추천하는 질문 기능 (기존 문서 보존)

> UI 각 화면에서 사용자가 바로 누를 수 있는 예시 질문. Agent 전환 후에도 동일하게
> 하나의 QA Agent로 전달된다.

- 뉴스 모달: 이 사건이 왜 중요해? / 관련 공식 공시가 있어? / 이 종목 최근 악재만 알려줘.
- 리포트: 이 리포트 목표주가와 근거는? / 증권사 전망 말고 회사 발표만 알려줘.
- 공시: 이 공시 핵심 숫자만 알려줘 / 정정 전과 후 뭐가 바뀌었어?
- 종목 페이지: 2025년 영업이익 얼마야? / 최근 호재만 알려줘, 실적은 빼고.
- 용어 팝오버: 이 용어가 무슨 뜻이야?

---

## 18. 참고 자료

- LangChain Agents: https://docs.langchain.com/oss/python/langchain/agents
- LangChain Tools: https://docs.langchain.com/oss/python/langchain/tools
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph Agentic RAG: https://docs.langchain.com/oss/python/langgraph/agentic-rag
- Upstage integration: https://docs.langchain.com/oss/python/integrations/providers/upstage
