# Phase 5.5-A · LangChain create_agent + Upstage Tool Calling Preflight 결과

- 일자: 2026-07-24
- 브랜치: `phase/5.5-a-agent-preflight`
- 목적: Phase 5.5 Agentic 전환 전, 현재 Upstage 모델이 LangChain `create_agent`
  Tool Calling을 실제로 지원하는지 검증하고 의존성을 고정한다.
- 산출물: 이 문서 + `scripts/agent_preflight.py` + `phase_5_5/preflight_result.json`
  + `pyproject.toml`/`uv.lock` 버전 고정.

## 1. 최종 패키지 구성 (프로젝트 .venv 정식 설치·고정)

| 패키지 | 고정 버전 | pyproject 제약 |
|---|---|---|
| langchain | 1.3.14 | `>=1.3.14,<1.4` |
| langchain-core | 1.5.1 | (langchain 이 해결) |
| langgraph | 1.2.9 | `>=1.2.5,<1.3` |
| langchain-openai | 1.4.1 | `>=1.4,<2` |

기존 의존성(transformers 5.14.1 / tokenizers 0.22.2 / sentence-transformers 등)과 **공존 확인**.

## 2. ⚠️ langchain-upstage 대신 langchain-openai 사용 (충돌 회피)

- 초기 계획은 `langchain-upstage 0.7.7`이었으나, 이 패키지가 **`tokenizers<0.21`을 강제**한다.
  프로젝트의 `transformers>=5`는 `tokenizers 0.22`를 요구 → **uv lock 해결 불가 충돌**.
  (preflight 격리 환경에서는 transformers 부재로 드러나지 않았고, 실제 프로젝트 lock에서 확인됨.)
- Upstage 는 **OpenAI 호환 API**이므로 `langchain-openai`의
  `ChatOpenAI(base_url="https://api.upstage.ai/v1")`로 동일하게 사용한다.
  `langchain-openai`는 tokenizers/transformers 의존이 없어 충돌이 사라진다.
- 결론: **`langchain-upstage`는 도입하지 않는다.** 모델 provider 는 여전히 환경변수로 분리한다.

```env
AGENT_CHAT_PROVIDER=upstage        # OpenAI 호환 엔드포인트
AGENT_CHAT_MODEL=solar-pro3-260323
UPSTAGE_BASE_URL=https://api.upstage.ai/v1
```

## 3. 검증 항목 결과 (모델 `solar-pro3-260323`, langchain-openai 경유)

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| init | Chat 모델 초기화 | ✅ | ChatOpenAI(base_url=Upstage) |
| 1 | bind_tools 단일 Tool call | ✅ | "영업이익" → `get_financial_facts` 1건 |
| 5 | 한국어 부정·제외 | ✅ | "호재? 실적은 제외" → `search_news`만, 재무 미호출 |
| 6 | create_agent 멀티툴 | ✅ | Tool loop 정상 작동, tool 메시지 관찰 |
| 2·3 | 추가/연속 Tool 호출 | ✅(조건부) | 복합 질문 3회 중 2회 fin+news 동시, 1회 fin만 |
| 4 | Tool call streaming | ✅ | chunks=33, tool_call_chunks 감지 |

**핵심 성과(항목 5)**: Agent 가 `search_news`만 호출하고 재무 Tool 을 호출하지 않았다.
기존 키워드 QueryPlan 이 "영업이익" 단어만으로 재무 조회를 켜던 문제를 모델이 실제로 해결.

**항목 2·3 재현성**: 복합 질문에서 여러 Tool 호출은 **질문 표현에 따라 편차**가 있다.
"두 가지를 해줘" 처럼 명시적 복합 요청은 안정적으로 둘 다 호출하나, 짧은 결합 질문은
재무만 호출하고 끝나기도 한다. 이는 모델 능력 부재가 아니라 **시스템 프롬프트 튜닝 대상**이다
(5.5-C에서 "복합 질문은 필요한 Tool 을 모두 호출" 지침으로 보강).

## 4. 중단 조건 점검 (문서 5.5-A)

| 중단 조건 | 해당 여부 |
|---|---|
| 모델이 Tool Calling 미지원 | 아니오 (단일·부정제외·스트리밍·멀티툴 전부 동작) |
| 스트리밍 Tool call이 SSE 계약과 연결 불가 | 아니오 (tool_call_chunks 스트리밍 확인) |
| 패키지 도입으로 기존 테스트 대량 회귀 | **아니오** (langchain 설치 후 기존 테스트 156개 통과, ruff clean) |
| 모델 비용·지연 한도 초과 | 미측정 — 5.5-F 평가에서 P95·비용 측정 |

→ **중단 조건 없음.** 임의 parser Agent 불필요.

## 5. 기존 테스트 회귀 확인

- langchain(1.3.14)·langgraph(1.2.9)·langchain-openai(1.4.1) 정식 설치 후
  `pytest -q` → **156 passed**, `ruff check` → All checks passed.
- 격리 환경(`uv run --with`)에서도 동일하게 156 통과 확인.

## 6. uv.lock 고정 (적용 완료)

`pyproject.toml`에 위 3개 의존성을 추가하고 `uv lock` + `uv sync --extra dev`로
`.venv`에 설치·고정했다. 무제한 버전 범위는 사용하지 않았다.

## 7. 결론

- `solar-pro3-260323` + LangChain v1 `create_agent` + `langchain-openai(base_url=Upstage)`
  조합이 단일 call·부정/제외·스트리밍·멀티툴(조건부)까지 통과.
- `langchain-upstage`는 tokenizers 충돌로 제외, `langchain-openai`로 대체(설계 변경 아님, provider-agnostic 유지).
- 멀티툴 안정성은 5.5-C 시스템 프롬프트로 보강 예정.
- **Phase 5.5-B(Tool 계약 구현)로 진행 가능**하나, 지시에 따라 여기서 멈추고 대기한다.
