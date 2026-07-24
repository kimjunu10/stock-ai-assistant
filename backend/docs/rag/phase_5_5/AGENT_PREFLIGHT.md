# Phase 5.5-A · LangChain create_agent + ChatUpstage Tool Calling Preflight 결과

- 일자: 2026-07-24
- 브랜치: `phase/5.5-a-agent-preflight`
- 목적: Phase 5.5 Agentic 전환 전, 현재 Upstage 모델이 LangChain `create_agent`
  Tool Calling을 실제로 지원하는지 격리 환경에서 검증(코드·DB 라이브 경로 미변경).
- 산출물: 이 문서 + `scripts/agent_preflight.py` + `phase_5_5/preflight_result.json`

## 1. 실행 방식 (프로젝트 lockfile 미오염)

프로젝트 `.venv`/`uv.lock`을 건드리지 않고 `uv run --no-project --with ...`로 격리 설치·실행:

```bash
cd backend
uv run --no-project \
  --with 'langchain==1.3.14' \
  --with 'langgraph>=1.2.5,<1.3.0' \
  --with 'langchain-upstage==0.7.7' \
  --with 'python-dotenv' \
  python scripts/agent_preflight.py
```

실제 DB·서비스는 호출하지 않고 더미 read-only Tool 2종으로 모델의 Tool 선택 능력만 검증.
비밀키는 출력·기록하지 않음.

## 2. 호환 버전 조사 결과

| 패키지 | 검증 버전 | 제약 |
|---|---|---|
| langchain | 1.3.14 | core `>=1.4.9,<2.0.0`, langgraph `>=1.2.5,<1.3.0` |
| langchain-core | 1.5.1 | — |
| langgraph | 1.2.9 | — |
| langchain-upstage | 0.7.7 | **core `>=1.2.5,<2.0.0` → v1 계열 지원 확인** |

- `langchain-upstage`는 아직 0.x(v1 태그 없음)지만 **langchain-core 1.x를 요구·지원**하므로
  langchain v1 `create_agent`와 함께 사용 가능.
- 파이썬 요구: 세 패키지 모두 `>=3.10` (프로젝트 3.13 충족).

## 3. 검증 항목 결과 (모델 `solar-pro3-260323`)

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| init | ChatUpstage 초기화 | ✅ | model=solar-pro3-260323 |
| 1 | bind_tools 단일 Tool call | ✅ | "영업이익 알려줘" → `get_financial_facts` 1건만 |
| 5 | 한국어 부정·제외 | ✅ | "호재 있어? 영업이익 실적은 제외" → `search_news`만, 재무 Tool 미호출 |
| 6 | create_agent 멀티툴 | ✅ | 복합 질문 → tool_msgs=2 (재무+뉴스) |
| 2·3 | Tool result 후 추가/연속 호출 | ✅ | fin=True, news=True 둘 다 호출 |
| 4 | Tool call streaming | ✅ | chunks=33, tool_call_chunks 감지됨 |

**6/6 통과.** 상세는 `preflight_result.json` 참조.

특기: 항목 5(부정·제외)에서 Agent가 `search_news(exclude_topics=[...])`를 스스로 구성하고
재무 Tool을 호출하지 않았다. 이는 기존 키워드 QueryPlan이 "영업이익" 단어만으로 재무 조회를
켜던 문제(문서 §변경기록)를 Agent가 실제로 해결함을 보여준다.

## 4. 중단 조건 점검 (문서 5.5-A)

| 중단 조건 | 해당 여부 |
|---|---|
| 모델이 Tool Calling 미지원 | 아니오 (전 항목 통과) |
| 스트리밍 Tool call이 SSE 계약과 연결 불가 | 아니오 (tool_call_chunks 스트리밍 확인, SSE 매핑 가능) |
| 패키지 도입으로 기존 테스트 대량 회귀 | 미측정 — 격리 설치라 프로젝트 테스트 영향 없음. 실제 도입(5.5-B~) 시 재확인 |
| 모델 비용·지연 한도 초과 | 미측정 — 5.5-F 평가에서 P95·비용 측정 예정 |

→ **중단 조건 없음.** 임의 parser Agent 불필요.

## 5. uv.lock 고정 제안 (아직 미적용)

Phase 5.5-B 이후 실제 도입 시 아래 버전을 `pyproject.toml`/`uv.lock`에 고정 제안:

```toml
langchain = "==1.3.14"
langgraph = ">=1.2.5,<1.3.0"   # 1.2.9 검증
langchain-upstage = "==0.7.7"
# langchain-core 는 langchain 이 1.5.1 로 자동 해결
```

- 무제한 범위(`langchain>=1`) 사용 금지.
- `AGENT_CHAT_MODEL` 환경변수로 Agent 모델을 분리 관리(provider-agnostic). 현재는
  `solar-pro3-260323`이 통과했으므로 별도 모델 불필요.
- **이번 단계에서는 lockfile·pyproject·의존성을 변경하지 않았다**(preflight는 격리 실행).

## 6. 결론

`solar-pro3-260323` + LangChain v1 `create_agent` + `langchain-upstage 0.7.7` 조합이
단일 Tool call·연속 호출·스트리밍·한국어 부정/제외까지 전부 통과했다.
**Phase 5.5-B(Tool 계약 구현)로 진행 가능**하나, 지시에 따라 여기서 멈추고 대기한다.
