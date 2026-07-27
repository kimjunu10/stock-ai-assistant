# Phase 9 · Tool runtime reliability root-cause

## 범위

- 기준: `main@000619a` (Phase 8 최종 홀드아웃 PR #72 포함)
- 브랜치: `phase/9-tool-runtime-root-cause`
- 홀드아웃 40문항 재실행: **없음**
- 개발셋 120문항 재실행: **없음**
- 제품 프롬프트·Agent 선택 정책·Gold·Retriever 랭킹·채점기 변경: **없음**
- 과거 `final_holdout_*` 산출물·85% 지표 변경: **없음**

분석에는 저장된 다음 파일만 사용했다.

- `phase_8/eval/final_holdout_raw_records.json`
- `phase_8/eval/final_holdout_tool_traces.json`
- `phase_8/eval/final_holdout_failure_causes.md`
- `phase_8/PHASE_8_FINAL_HOLDOUT_RUN.md`

## 확인된 근본 원인

### 1. `status=null`: Pydantic 입력 검증 예외가 비표준 평문으로 변환됨

`h-mix-19`는 `account_names=["배당금", "영업이익"]`, `h-mix-20`의 첫
재무 호출은 `account_names=["매출액", "영업이익", "순이익"]`을 전달했다.
`FinancialFactsInput.AccountName`의 허용값은 `당기순이익`이며 `배당금`과
`순이익`은 허용되지 않는다.

확인된 예외:

- 클래스: `pydantic_core.ValidationError` (`ValidationError`)
- 메시지 요약: `account_names.0 Input should be ...`, `literal_error`
- 입력값: `배당금` 또는 `순이익`

예외는 Tool 본문 전에 발생했고 `ToolErrorMiddleware`의 기존 callback이
`status` 없는 평문을 반환했다. 평가 recorder는 JSON의 `status`만 읽으므로
두 호출이 `null`로 남았다.

수정:

- 모든 wrapper 예외를 표준 `ToolResult` JSON
  (`status=error`, 빈 data/sources, 안전한 warning)으로 반환
- validation error는 “Tool 스키마의 enum·필수 형식을 확인”하라는 명시적
  입력 오류로 구분
- 오류를 `no_data`로 위장하지 않음

### 2. `h-mix-20 step_limit`: 실패 호출이 Tool 예산을 소진

저장 trace의 호출 순서는 다음과 같다.

1. `get_financial_facts` — `순이익` validation, status 누락
2. `search_news` — status=error
3. 동일 `search_news` — duplicate guard가 0ms에 status=error 반환
4. 수정된 `get_financial_facts(당기순이익)` — status=ok
5. `get_disclosure_values` — status=ok

5회 Tool 호출 한도를 모두 사용한 뒤 최종 답변 단계에 도달하지 못했다.
`AgentQaService`에서 `GraphRecursionError`만 `step_limit`으로 변환하므로,
저장된 `step_limit`은 이 호출 예산 소진 경로와 일치한다.

Agent 정책이나 호출 한도는 이번 작업에서 바꾸지 않았다. 대신 최초 validation
실패가 명시적인 error status로 남게 했고, h-mix-20과 같은 정상화된 직접 순차
호출(재무→뉴스→공시)이 모두 한 번에 `ok`가 되는지 smoke에 고정했다.

### 3. 36개 `status=error`의 내부 예외는 과거 산출물에서 복원 불가

과거 Tool 구현은 서비스 예외를 잡아 클래스명만 포함한 안전 warning으로 바꿨고,
평가 recorder는 warning·예외를 저장하지 않았다. 최종 답변도 내부 정보를 제거했다.
따라서 36개 error의 실제 예외 클래스·메시지·stack은 저장 산출물에 존재하지 않는다.

같은 입력을 현재 코드와 동일 환경에서 Agent 없이 호출한 결과:

- main thread: 첫 호출·두 번째 호출 모두 성공
- 요청별 새 worker thread: 모두 성공
- 하나의 worker thread 재사용: 모두 성공
- 같은 Tool 반복: 모두 성공
- 서로 다른 Tool 순차 호출: 모두 성공

따라서 Supabase client 생성/재사용, thread 경계, 기본/optional 인자, 현재 DB
데이터를 원인으로 확정할 증거는 없으며 이 경로를 추측 수정하지 않았다. 홀드아웃
실행 시점에만 발생한 DB/네트워크 계층의 일시 실패 가능성은 남지만, 과거 예외가
소실돼 정확한 종류를 단정할 수 없다.

## 왜 개발셋에서 크게 드러나지 않았는가

개발셋 기록에도 status 누락은 이미 있었다.

- `mix-02`, `mix-03`, `mix-05`: `순이익` validation으로 status=null
- `excl-07`: status=null
- 전체 Tool 상태: ok 123, no_data 4, null 4, error 1

동결 채점기는 Tool 이름 호출 여부를 주로 사용하고 status 자체를 전체 통과 조건으로
삼지 않아 이 문제가 97.44% 지표에서 전면화되지 않았다. 이번 PR은 금지사항에 따라
채점기를 변경하지 않는다.

홀드아웃은 ok 11, null 2, error 36으로 실행 시점의 Tool error가 집중됐다.
동일 호출이 지금은 모두 성공하므로 개발셋·홀드아웃 차이를 입력 데이터나
Supabase client 구조 하나로 설명할 수 없다. 향후 동일 오류가 발생하면 이번에 추가한
구조화 내부 로그로 정확한 예외를 확보할 수 있다.

## 오류 관측성

`TOOL_RUNTIME_ERROR` 내부 로그에 다음을 남긴다.

- Tool 이름
- 재귀적으로 마스킹하고 길이를 제한한 인자
- 예외 클래스
- 비밀값을 마스킹한 예외 메시지
- 메시지 값을 제외한 stack frame
- 실패 계층
- request/correlation ID

요청 ID는 `AgentQaService`에서 `QaRuntimeContext`로 전달되고 관측 middleware가
각 Tool 실행의 ContextVar에 연결한다. 각 Tool의 서비스 예외 catch 지점은
실패 계층을 명시한다. 사용자·모델에는 기존처럼 내부 stack·DB 메시지·비밀값을
노출하지 않는다.

## 실제 DB/API targeted smoke

실행 시각: `2026-07-27T14:18:48.935139+09:00`

| Tool | 기본 1/2회 | 선택 인자 1/2회 | 결과 |
|---|---|---|---|
| lookup_financial_term | ok / ok | 대체 용어 ok / ok | PASS |
| get_financial_facts | ok / ok | 정확 기간·계정 ok / ok | PASS |
| search_news | ok / ok | query 포함 ok / ok | PASS |
| get_disclosure_values | ok / ok | event_types 포함 ok / ok | PASS |
| search_research_reports | ok / ok | broker·time_context 포함 ok / ok | PASS |
| get_stock_prices | ok / ok | lookback 포함 ok / ok | PASS |

추가 계약:

- 재무→뉴스→공시 복합 순차 호출: ok / ok / ok
- 존재하지 않는 용어: `no_data`
- 잘못된 `순이익` enum: 명시적 `error`
- Agent 실행: false

상세 원시는 `tool_runtime_smoke.json`에 보존했다.

## 배포 전 명령

```bash
cd backend
set -a
source .env
set +a
.venv/bin/python scripts/phase9_tool_runtime_smoke.py
```

정상 호출 하나라도 `status=error`이거나 첫 호출과 반복 호출 상태가 다르거나,
복합 순차 호출이 실패하면 exit code 1이다. Toss 자격증명이 없어 정상 대조군을
확인할 수 없으면 exit code 2다.

## 테스트

- 백엔드 Ruff: 전체 통과, 257 files formatted
- mock 기반 unit/agent 회귀: 531 passed, warning 1
- 실제 DB/Toss targeted smoke: PASS
- 전체 Agent 평가: 실행하지 않음

mock 테스트는 마스킹, 예외 클래스·메시지·계층·request ID·stack 로그,
validation의 표준 error status, recorder status 인식을 검증한다.

## 변경 파일

- `app/agent/tools/common.py`: 안전한 로그 문맥·마스킹·예외 로거
- `app/agent/middleware.py`: 관측 middleware와 표준 Tool error JSON
- `app/agent/context.py`, `app/services/agent_qa.py`: request ID 전달
- `app/agent/runtime.py`: 관측 middleware 연결
- `app/agent/tools/{terms,financials,news,disclosures,reports,prices}.py`:
  서비스 catch 지점별 실패 계층 로그
- `scripts/phase9_tool_runtime_smoke.py`: 배포 전 실제 read-only smoke
- `tests/unit/test_tool_runtime_reliability.py` 및 관련 회귀 테스트

## 남은 문제

- 과거 홀드아웃의 36개 error는 실제 예외가 저장되지 않아 정확한 DB/API 예외
  종류를 사후 확정할 수 없다.
- 이번 실제 재현에서는 같은 입력이 모두 성공했으므로 근거 없는 DB client 교체,
  connection pool 재구성, retry 확대를 적용하지 않았다.
- Agent 호출 예산과 채점기의 status 반영 여부는 이번 PR 범위 밖이며 변경하지 않았다.
- 홀드아웃 85%와 기존 원시 기록·지표는 그대로 보존했다.
