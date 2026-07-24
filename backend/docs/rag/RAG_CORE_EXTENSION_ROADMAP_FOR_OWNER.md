# 우리 프로젝트의 핵심 RAG 확장 방향

## 1. 결론

우리 프로젝트에는 아래 네 가지면 충분하다.

```text
현재 RAG 완성
→ 공통 Tool 인터페이스
→ 제한형 Agentic Orchestrator
→ 실행 추적·평가
```

MCP는 핵심 구현이 안정된 뒤 **선택적으로 추가**한다.

A2A는 이번 프로젝트에서 제외한다.

```text
LangChain: 도입하지 않음
A2A: 구현하지 않음
MCP: 선택적
Agentic: 복합 질문에만 적용
오케스트레이션: 직접 구현
```

---

## 2. A2A를 제외하는 이유

A2A는 서로 독립적으로 실행되는 여러 Agent가 작업을 위임하고 결과를 주고받을 때 필요하다.

예를 들면 다음과 같은 구조다.

```text
총괄 Agent
→ 재무 Agent
→ 뉴스 Agent
→ 리포트 Agent
```

하지만 현재 우리 서비스는 하나의 FastAPI 애플리케이션 안에서 뉴스, 공시, 재무, 금융용어, 리포트, 주가 기능을 처리한다.

이 기능들을 억지로 독립 Agent로 나누면 다음 문제가 생긴다.

- 배포 구조가 복잡해진다.
- Agent 간 통신 오류가 추가된다.
- 응답 시간이 길어진다.
- 실제 서비스 품질보다 기술 이름을 넣기 위한 구현이 될 수 있다.
- 일주일 안에 검증·평가하기 어렵다.

따라서 A2A는 현재 프로젝트의 핵심 문제를 해결하지 않는다.

발표에서는 다음과 같이 설명한다.

> A2A는 독립 Agent 간 작업 위임이 필요한 구조에서 의미가 있지만, 현재 서비스는 하나의 백엔드 안에서 공통 Tool을 안전하게 호출하는 구조가 더 적합하다고 판단해 적용하지 않았습니다.

---

## 3. LangChain을 도입하지 않는 이유

LangChain은 RAG 또는 Agentic의 필수 조건이 아니다.

현재 프로젝트는 이미 다음 기능을 직접 구현했다.

- 뉴스·공시·금융용어 검색
- 벡터 검색과 키워드 검색 결합
- RRF 순위 결합
- 재무 SQL 조회
- 질문 라우팅
- 출처 결합
- 증분 인덱싱

이 코드를 LangChain으로 다시 작성해도 사용자 기능이 늘어나지 않는다.

오히려 다음 위험이 있다.

- 기존 동작 회귀
- 디버깅 범위 증가
- 프레임워크 구조와 현재 코드의 중복
- 발표에서 실제 구현 내용을 설명하기 어려워짐

따라서 기존 FastAPI 기반 직접 구현을 유지한다.

발표 표현:

> LangChain 템플릿을 사용하지 않고 검색, 라우팅, 데이터 조회, 출처 결합을 직접 구현했습니다.

---

## 4. 가장 먼저 추가할 것: 공통 Tool 인터페이스

Agentic을 구현하기 전에 기존 기능을 Tool로 정리한다.

예상 Tool:

```text
get_financial_facts
search_news
search_disclosures
lookup_financial_term
search_research_reports
get_stock_price
calculate_event_return
```

각 Tool은 동일한 형식으로 동작한다.

```json
{
  "ok": true,
  "data": {},
  "sources": [],
  "warnings": [],
  "error": null
}
```

Tool의 원칙:

- 기존 Service와 Repository를 재사용한다.
- 검색 로직을 다시 만들지 않는다.
- 기본적으로 읽기 전용이다.
- 숫자에는 단위와 기간을 포함한다.
- 리포트 전망값은 실제 실적과 구분한다.
- 검색 결과에는 출처를 포함한다.
- 오류와 timeout 형식을 통일한다.

Tool 인터페이스를 먼저 만들면 다음 장점이 있다.

- 기존 라우터에서도 같은 Tool을 사용한다.
- Agentic에서도 같은 Tool을 사용한다.
- 나중에 MCP를 붙일 때도 같은 Tool을 재사용한다.
- 테스트 대상이 명확해진다.

---

## 5. 핵심 확장: 제한형 Agentic Orchestrator

모든 질문을 Agent에게 맡기지 않는다.

### 단순 질문

기존 결정론적 경로를 유지한다.

```text
“PER이 뭐야?”
→ 금융용어 Tool

“2025년 영업이익은 얼마야?”
→ 재무 SQL Tool

“최근 삼성전자 뉴스 보여줘.”
→ 뉴스 검색 Tool
```

### 복합 질문

여러 데이터가 필요한 질문만 Agentic 경로로 보낸다.

```text
“삼성전자 영업이익은 왜 감소했고
증권사들은 앞으로 어떻게 전망해?”
```

예상 실행:

```text
1. get_financial_facts
   → 실제 영업이익과 비교 기간 확인

2. search_news 또는 search_disclosures
   → 감소 원인 검색

3. search_research_reports
   → 증권사 전망 검색

4. 검증
   → 실제값과 전망값 분리
   → 핵심 주장마다 출처 연결

5. 최종 답변
```

Agentic의 핵심은 첫 단계에서 모든 호출을 미리 확정하지 않는 것이다.

```text
Tool 실행
→ 결과 확인
→ 정보가 부족하면 다음 Tool
→ 충분하면 종료
```

---

## 6. Agentic 안전장치

우리 Agent는 범용 자율 Agent가 아니라 제한형 Agent다.

```text
최대 Tool 호출: 5회
최대 실행 단계: 6회
전체 timeout: 적용
동일 Tool·동일 인자 반복: 차단
허용 목록 외 Tool: 차단
DB 쓰기·삭제: 금지
주문 실행: 금지
SQL 숫자: LLM 추론보다 우선
실제값·전망값: 분리
출처 없는 사실: 최종 답변에서 제거
Agent 실패: 기존 라우터로 fallback
```

이 제한이 있어야 금융 정보 서비스에서 예측 가능성과 정확성을 유지할 수 있다.

---

## 7. 오케스트레이션

오케스트레이션은 별도의 마지막 기술이 아니라 전체 실행을 관리하는 구조다.

현재도 일부 오케스트레이션이 있다.

```text
질문
→ QueryPlan
→ SQL·검색·용어 작업 선택
→ 결과 통합
→ 답변
```

확장 후에는 다음 역할을 추가한다.

```text
질문 복잡도 판정
→ 단순 질문은 기존 경로
→ 복합 질문은 Agentic 경로
→ Tool 실행 순서 관리
→ 반복·timeout·오류 통제
→ fallback
→ 출처 검증
→ 최종 답변
```

따라서 우리 프로젝트는 LangGraph 없이 오케스트레이션을 직접 구현한다.

---

## 8. 실행 추적과 평가

교수님이 지적한 문제를 피하려면, 기술을 사용했다는 말보다 실제 실행을 보여줘야 한다.

Agentic 요청마다 다음 정보를 기록한다.

```text
요청 ID
선택된 모드
호출한 Tool
Tool 호출 순서
Tool별 실행 시간
반환 결과 개수
오류와 timeout
종료 이유
fallback 여부
출처 검증 결과
```

모델의 내부 추론 전문은 저장하지 않는다.

평가 지표:

- 단순·복합 질문 분기 정확도
- 필수 Tool 선택률
- 불필요 Tool 호출률
- 동일 호출 반복 횟수
- 복합 질문 완료율
- 숫자 정확도
- 출처 정확도
- fallback 성공률
- 응답 시간
- 질문당 비용

Agentic을 추가한 뒤 기존 결정론적 RAG와 같은 질문으로 비교한다.

---

## 9. MCP는 선택적으로 추가

MCP는 기존 Tool을 외부 AI 클라이언트가 표준 방식으로 호출하게 하는 연결 계층이다.

```text
외부 AI 클라이언트
→ MCP 서버
→ 공통 Tool Registry
→ 기존 서비스
```

MCP를 추가해도 검색 알고리즘이 좋아지는 것은 아니다.

우리 프로젝트에서 MCP가 의미 있는 경우:

- 교수님이 표준 프로토콜 구현을 요구함
- 외부 MCP 클라이언트에서 실제 Tool 호출을 시연할 수 있음
- Agentic과 기존 Tool이 안정화됨
- 남은 일정이 충분함

MCP를 구현할 경우 최소 범위:

```text
search_news
get_financial_facts
search_research_reports
```

핵심 Tool 3개만 공개해도 충분하다.

MCP는 Agentic보다 먼저 구현하지 않는다.

---

## 10. 최종 구현 순서

```text
Phase 5
증권사 리포트 RAG 완성

Phase 6
주가 조회·수익률 계산 완성

Extension A
기존 기능을 공통 Tool로 정리

Extension B
복합 질문용 제한형 Agentic Orchestrator

Extension C
실행 trace와 Agentic 평가

선택 Extension
MCP 서버로 핵심 Tool 3개 공개
```

제외:

```text
LangChain 재작성
LangGraph 도입
A2A
다중 Agent 분산 구조
DB 쓰기 Agent
투자 주문 Agent
```

---

## 11. 최종 구조

```text
사용자 질문
   ↓
질문 복잡도 판정
   ├─ 단순 질문
   │    └─ 기존 결정론적 라우터
   │         └─ 공통 Tool
   │
   └─ 복합 질문
        └─ 제한형 Agentic Orchestrator
             └─ 공통 Tool
                  ├─ 재무
                  ├─ 뉴스
                  ├─ 공시
                  ├─ 금융용어
                  ├─ 리포트
                  └─ 주가
   ↓
숫자·실제값·전망값·출처 검증
   ↓
최종 답변
```

선택적 외부 연결:

```text
외부 MCP 클라이언트
→ MCP 서버
→ 같은 공통 Tool
```

---

## 12. 발표에서 설명할 문장

### Agentic까지 구현한 경우

> LangChain이나 LangGraph에 의존하지 않고 금융 특화 하이브리드 RAG를 직접 구현했습니다. 단순 질문은 기존 결정론적 라우팅으로 처리하고, 여러 데이터가 필요한 복합 질문에는 허용된 읽기 전용 Tool을 선택하고 결과에 따라 다음 호출을 결정하는 제한형 Agentic Orchestration을 적용했습니다.

### MCP까지 구현한 경우

> 내부 RAG와 Agentic에서 사용한 동일 Tool을 MCP 서버로 공개해 외부 AI 클라이언트에서도 표준 방식으로 호출할 수 있게 했습니다.

### A2A를 적용하지 않은 이유

> 현재 서비스는 하나의 백엔드 안에서 공통 Tool을 호출하는 구조가 더 단순하고 안정적이기 때문에, 독립 Agent 간 통신을 위한 A2A는 적용하지 않았습니다.

---

## 13. 한 문장 요약

> 기존 RAG를 LangChain으로 다시 만들거나 A2A 다중 Agent 구조로 복잡하게 바꾸지 않고, 현재 기능을 공통 Tool로 정리한 뒤 복합 질문에만 제한형 Agentic Orchestration을 적용하고, MCP는 일정과 시연 가치가 있을 때만 선택적으로 추가한다.
