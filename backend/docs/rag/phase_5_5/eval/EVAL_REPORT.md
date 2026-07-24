# Phase 5.5-F · Agent 평가 보고서

- 일자: 2026-07-24
- 방식: devset.json 12개 질문을 **실제 Agent(create_agent + solar-pro3 + 실제 DB)** 로 실행,
  Tool trace 로 지표 계산. read-only.
- 산출물: `scripts/evaluate_agent.py`, `eval/devset.json`, `eval/eval_result.json`, 이 보고서.

## 1. 하드코딩 감사 (질문별·종목별 Tool 선택 강제 없음)

Agent 경로(`app/agent/**`, `app/services/agent_qa.py`) 전수 grep 감사:

| 항목 | 결과 |
|---|---|
| 질문 문자열 직접 비교(`question ==`, `in question`) | **없음** |
| 특정 종목코드(005930 등) 분기 | **없음** |
| 특정 회사명(삼성전자 등) 분기 | **없음** |
| Tool 강제 선택(need_*, force_tool, classifier) | **없음** (주석의 "classifier 없음" 문구만) |
| 프롬프트 질문별/종목별 few-shot 라우팅 고정 | **없음** ("고정하지 않는다" 명시) |
| Tool 내부 종목 하드코딩 | **없음** |

→ Tool 선택은 코드가 아니라 **모델이 런타임에 판단**한다.

## 2. 모델이 직접 Tool 을 선택했음을 Tool trace 로 증명

질문별 실제 `tool_calls`(Agent 실행 trace):

```
term-1        → lookup_financial_term
fin-annual-1  → get_financial_facts, search_news        (legacy 규칙: get_financial_facts 만)
fin-q3-cum-1  → get_financial_facts
news-1        → search_news
disclosure-1  → search_disclosures, get_disclosure_values
mixed-1       → get_financial_facts, search_research_reports, search_news, get_disclosure_values
exclude-2     → search_news
exclude-3     → search_disclosures, get_disclosure_values
compare-1     → get_financial_facts ×4
no-data-1     → get_financial_facts
```

증명 논거:
- 질문마다 **서로 다른 Tool 조합**을 스스로 구성(mixed-1은 4종, compare-1은 재무 반복).
- **legacy QueryPlan 규칙 경로와 불일치**(예: mixed-1 legacy=리포트만 vs agent=4종;
  exclude-1 legacy=재무 vs agent=검색 시도). 코드 강제였다면 규칙과 같아야 하는데 다르다.
- 동일 코드·동일 프롬프트에서 질문 의미에 따라 다른 선택 → 모델 판단 결과.

## 3. 지표 (timeout 35s 재평가 기준)

| 지표 | 결과 | 승인 기준 | 판정 |
|---|---|---|---|
| Required Tool Recall | 0.833 (10/12) | ≥ 0.95 | ❌ |
| Forbidden Tool Violation | 8.3% (1/12) | ≤ 3% | ❌ |
| 부정·제외 치명 위반 | 0 (금지 Tool 실호출 아님*) | 0 | ✅ |
| no_data 처리 | 1/1 | — | ✅ |
| 동일 호출 반복 | 1건 | 0 | ❌ |
| 지연 P50 | 8.5초 | — | — |
| 지연 P95 | 106초 | 복합 ≤10초 | ❌ |

*forbidden violation 1건(fin-annual-1)은 순수 재무 질문에 search_news 를 추가 호출한 것으로,
금지 주제를 답변에 넣은 치명 위반은 아니나 불필요 호출로 집계.

## 4. 발견된 결함 (평가가 드러낸 것)

1. **timeout 이 Tool 내부 LLM 왕복을 중단하지 못함** — `AgentQaService` 의
   `ThreadPoolExecutor.result(timeout)` 은 실행 중 스레드를 강제 종료할 수 없어,
   Tool loop 안의 모델 왕복이 계속 돌아 report-1 106초·exclude-1 609초로 폭주.
   → 8초 기본 timeout 에서는 검색 포함 질문이 완주 못 하고 tools=[] 로 보임(1차 평가 6건).
2. **불필요 Tool 호출** — fin-annual-1 이 순수 재무 질문에 search_news 추가 호출.
   시스템 프롬프트에 "사실 조회만 요구되면 검색 Tool 을 부르지 말 것" 강화 필요.
3. **동일 재무 Tool 반복(compare-1 4회)** — DuplicateToolCallMiddleware 가 인자가 조금씩
   다르면(연도/유형) 우회됨. 비교 질문은 정상적 다회 호출이나, 과다 호출은 프롬프트·
   ToolCallLimit 로 억제 필요.
4. **모델 왕복 지연 큼** — solar-pro3 Tool Calling 왕복이 케이스당 수 초~수십 초.
   복합 P95 10초 목표는 현재 모델·구성으로 미달.

## 5. 결론

- **모델의 자율 Tool 선택·하드코딩 부재는 증명됨.** no_data 정직 처리도 통과.
- **그러나 승인 기준(§5.5-F) 미달**: Required Recall 0.83(<0.95), Forbidden 8.3%(>3%),
  반복 1건, 복합 P95 106초(≫10초). 특히 timeout 미작동은 실동작 결함.
- 따라서 **5.5-G(라이브 전환) 불가**. `agent_enabled=false` 유지가 타당(라이브는 결정론적 경로).

## 6. 개선 우선순위 (다음 작업, 이번 범위 아님)

1. timeout 을 실제로 강제하는 실행 구조(예: LangGraph 자체 재귀/스텝 제한 + per-tool 시간
   상한), 또는 스트리밍 기반 조기 종료.
2. 시스템 프롬프트: 순수 사실 질문에서 검색 Tool 미호출, 복합 질문 Tool 과다 억제.
3. 모델 왕복 지연 최적화(모델 파라미터·병렬 Tool·후보 수) 후 재평가.
4. devset 확장(현재 12개 → 유형별 홀드아웃 포함), Tool Argument Accuracy·Citation Precision·
   숫자 Exact Match 세부 채점 추가.
