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

## 4. 세부 자동 채점 (개발셋 + 홀드아웃)

재무 정답값은 DB(FactsService)에서 동적 조회해 채점(하드코딩 아님). 홀드아웃은 개발셋과
겹치지 않는 종목·기간·표현.

| 지표 | 개발셋(12) | 홀드아웃(10) | 기준 | 판정 |
|---|---|---|---|---|
| Required Tool Recall | 1.0 | 1.0 | ≥0.95 | ✅ |
| Forbidden Violation | 0% | 0% | ≤3% | ✅ |
| 동일 호출 반복 | 0 | 0 | 0 | ✅ |
| no_data 처리 | 1/1 | 1/1 | — | ✅ |
| **재무 Exact Match** | **2/2** | **3/3** | 100% | ✅ |
| **기간 정확도** | **2/2** | **3/3** | 100% | ✅ |
| **actual/forecast** | **2/2** | **3/3** | 혼동 0 | ✅ |
| **존재하지 않는 인용** | **0** | **0** | 0 | ✅ |
| 지연 P95 | 9.2초 | 8.9초 | 복합 ≤10초 | ✅ |
| 질문당 비용 | $0.0019 | $0.0017 | — | — |

**홀드아웃에서도 동일 통과** → 평가셋에 맞춘 하드코딩이 아니라 일반 규칙 개선임을 확인.

### 이번 라운드 개선(일반 규칙, 특정 질문·종목 하드코딩 없음)

1. `FactsService.REPRT_LABEL` 공식 매핑 수정(11013=1분기 … 11011=연간). 기간 라벨 정확화.
2. 시스템 프롬프트에 재무 인자 매핑 규칙(예: "3분기 누적"→report_period=q3, amount_type=cumulative)
   + "no_data 면 다른 기간으로 대체하지 않는다" 명시.
3. get_financial_facts 결과에 `value_display`(조/억 표기) 제공 → 모델의 큰 숫자 자릿수
   변환 실수 제거(43.6조를 4.36조로 답하던 오류 해소).

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

- **모델 자율 Tool 선택·하드코딩 부재 증명**. 승인 기준 **전 지표 통과**(개발셋·홀드아웃):
  Recall 1.0, Forbidden 0%, 반복 0, no_data 처리, **재무 Exact Match·기간·actual·인용 전부**,
  복합 P95 ≤10초. 질문당 비용 ~$0.002.
- 세부 자동 채점(재무 Exact Match·기간·단위·actual/forecast·인용·비용)까지 구현·통과.
- 5.5-G(라이브 전환) 진입 조건 충족. 단, 라이브 전환은 별도 승인 절차(5.5-G 체크리스트:
  스테이징 flag on·UI smoke·legacy 비교·운영 flag 전환)를 따른다.
- 현재 `agent_enabled=false` 유지(라이브는 결정론적 경로).
