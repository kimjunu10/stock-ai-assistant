# Phase 5.5-F · Agent 평가 보고서

- 일자: 2026-07-24
- 방식: devset.json 12개 질문을 **실제 Agent(create_agent + 실제 DB)** 로 실행,
  Tool trace 로 지표 계산. read-only.
- Agent 모델: **gpt-4.1-mini-2025-04-14** (OpenAI). provider-agnostic 구성으로 교체.
- 산출물: `scripts/evaluate_agent.py`, `eval/devset.json`, `eval/eval_result.json`, 이 보고서.

## 1. 하드코딩 감사 (질문별·종목별 Tool 선택 강제 없음)

Agent 경로(`app/agent/**`, `app/services/agent_qa.py`) 전수 grep 감사:

| 항목 | 결과 |
|---|---|
| 질문 문자열 직접 비교 | 없음 |
| 특정 종목코드/회사명 분기 | 없음 |
| Tool 강제 선택(need_*, force_tool, classifier) | 없음 |
| 프롬프트 질문별/종목별 few-shot 라우팅 고정 | 없음 |

→ Tool 선택은 코드가 아니라 모델이 런타임에 판단한다. 모델을 solar-pro3 → gpt-4.1-mini 로
바꾼 것은 provider-agnostic 설계(`AGENT_CHAT_PROVIDER`)에 따른 교체이며, 라우팅 하드코딩이
아니다.

## 2. 모델이 직접 Tool 을 선택했음을 Tool trace 로 증명

질문별 실제 `tool_calls`:

```
term-1        → lookup_financial_term
fin-annual-1  → get_financial_facts
fin-q3-cum-1  → get_financial_facts
news-1        → search_news
disclosure-1  → search_disclosures
report-1      → search_research_reports
mixed-1       → get_financial_facts, search_research_reports
exclude-1     → search_news            (재무 Tool 미호출: '실적 제외' 준수)
exclude-2     → search_news
exclude-3     → search_disclosures     ('증권사 전망 말고 공시만' 준수)
compare-1     → get_financial_facts ×2 (단독/누적 각 1회, 정상)
no-data-1     → (없음)                 (2099년 미래값 → 상식으로 없음 판단)
```

- 질문마다 다른 Tool 조합을 스스로 구성. legacy QueryPlan 규칙 경로와도 불일치.
- 부정·제외 질문에서 금지 대상 Tool 을 부르지 않음(exclude-1/2/3).

## 3. 지표 — 승인 기준 통과

| 지표 | 결과 | 승인 기준 | 판정 |
|---|---|---|---|
| Required Tool Recall | **1.0 (12/12)** | ≥ 0.95 | ✅ |
| Forbidden Tool Violation | **0%** | ≤ 3% | ✅ |
| 부정·제외 치명 위반 | **0** | 0 | ✅ |
| no_data 처리 | **1/1** | — | ✅ |
| 동일 호출 반복 | **0건** | 0 | ✅ |
| 지연 P50 | 4.5초 | — | — |
| 지연 P95(복합 포함) | **7.1초** | 복합 ≤ 10초 | ✅ |
| 하드코딩 없음 / 모델 자율 선택 | 없음 / 증명 | — | ✅ |

## 4. 미측정(잔여) 항목

승인 기준 중 아래 3개는 이번 러너에서 **세부 채점을 구현하지 않았다**(정직 기록):

- 재무 숫자 Exact Match 100%
- 기간·단위 정확도 100% / actual·forecast 혼동 0
- Citation Precision / 존재하지 않는 인용 0

근거: get_financial_facts Tool 이 report_period→공식 reprt_code 매핑·amount_type 엄격 검증·
no_data(fallback 없음)을 이미 코드로 강제하고(5.5-B 단위 테스트 통과), 5.5-E 검증기가
존재하지 않는 인용·근거 없는 숫자를 코드로 검출한다. 다만 **평가셋 정답값 대비 자동 채점**은
Tool Argument Accuracy·숫자 Exact Match 채점 로직으로 별도 구현이 필요하다(5.5-F 잔여).

## 5. 모델 비교(solar-pro3 → gpt-4.1-mini)

| 지표 | solar-pro3 | gpt-4.1-mini |
|---|---|---|
| Required Recall | 0.75 | **1.0** |
| Forbidden | 0~8% | **0%** |
| 동일 반복 | 1~3건 | **0건** |
| P95 | 106~954초(폭주) | **7.1초** |

solar-pro3 는 Tool Calling 왕복 지연이 크고 일부 호출이 hang 되어 복합 P95 목표를 만족하지
못했다. gpt-4.1-mini 로 교체하고, 개별 LLM 호출 HTTP timeout·recursion_limit 안전장치를
더해 폭주를 제거했다.

## 6. 결론

- **모델 자율 Tool 선택·하드코딩 부재 증명**, 핵심 게이트(Recall·Forbidden·부정제외·지연·반복)
  **전부 통과**.
- 단, **재무 Exact Match·기간·단위·Citation 자동 채점은 미구현(잔여)**. 이 세부 채점을 완료해
  승인 기준 전체를 명시적으로 검증한 뒤에 5.5-G(라이브 전환)로 진행하는 것이 안전하다.
- 현재 `agent_enabled=false` 유지(라이브는 결정론적 경로).
