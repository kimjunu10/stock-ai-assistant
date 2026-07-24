# Phase 5.5-G · 스테이징 Agent Smoke Test 결과

- 일자: 2026-07-24
- 환경: 로컬 스테이징. 백엔드 `AGENT_ENABLED=true` (별도 포트), Agent 모델 gpt-4.1-mini.
- 방법: `/api/qa/stream`(SSE)·`/api/qa`(동기)를 실제 HTTP로 호출해 첫 응답·전체 응답·
  이벤트 순서 측정. legacy(flag off) 서버와 동일 질문 비교.
- ⚠️ **실제 웹 UI 미연결**: 프런트 `AskPage`는 백엔드 미연결 프로토타입(하드코딩 안내문).
  질의응답 UI 연결은 Phase 7 미구현이라, "웹 화면"이 아니라 **API SSE 레벨**로 smoke 했다.

## 1. SSE 진행 표시·응답 시간 (AGENT_TIMEOUT_SECONDS=15)

| 질문 유형 | 진행표시 시작 | 첫 답변(delta) | 전체 | 이벤트 순서 |
|---|---|---|---|---|
| 단순-용어(PER) | 즉시(agent_start) | 4.1s | 4.1s | agent_start→tool_start→tool_end→sources→delta→done |
| 단순-숫자 | 즉시 | 2.4s | 2.4s | 정상 |
| 단순-뉴스 | 즉시 | 2.1s | 2.1s | 정상 |
| 복합(재무+리포트) | 즉시 | 5.9s | 5.9s | tool_start/end ×2 후 done |
| 복합-부정제외 | 즉시 | 5.0s | 5.0s | 정상 |
| 복합-리포트 | 즉시 | 4.8s | 4.8s | 정상 |

- **SSE 진행 표시 정상**: agent_start·tool_start·tool_end·sources·delta·done 순서로 전달.
  사용자는 "AI가 자료 찾는 중"을 즉시(수백ms 내) 보게 된다.
- **응답 시간**: 단순 2~4s, 복합 5~6s. SPEC 목표(단순≤6s, 복합≤10s) 충족.
- **첫 답변 = 전체 시각**: 현재 delta 는 답변을 한 번에 전송(토큰 단위 스트리밍 아님).
  진행 이벤트로 대기 체감을 줄이지만, 실시간 타이핑 효과는 없음(추후 개선 여지).

## 2. timeout 설정 발견

- 기본 `AGENT_TIMEOUT_SECONDS=8` 에서 **복합-부정제외 질문이 8.76s 로 timeout** 발생.
- 평가 P95(9~10s)와 실측을 반영해 **운영 timeout 을 12~15s 로 상향 필요**(설정값 조정).
  15s 로 재기동 후 전 케이스 정상 완주 확인.

## 3. legacy vs agent 비교

| 질문 | legacy(결정론적) | agent |
|---|---|---|
| "목표주가와 증권사 전망" | 정상(목표주가·전망) | 정상(search_research_reports ×2) |
| "2025년 영업이익 얼마?" | **정답 23.53조** | ❌ **"확정 데이터 없음" 오답** |

## 4. DB 확인 — 43.60조 / 23.53조 의 정체

삼성전자 2025 영업이익 실제 행(DB):

| 값 | reprt_code | 의미 | fs_div | amount_type |
|---|---|---|---|---|
| **43.60조** (43,601,051,000,000) | 11011 | **사업보고서(연간)** | CFS(연결) | cumulative(누적) |
| **23.53조** (23,527,391,000,000) | 11014 | **3분기보고서** | CFS(연결) | cumulative(누적) |

→ "2025년 영업이익"의 올바른 답은 **연간 43.60조**. (smoke 초기의 legacy 23.53조는 사실
3분기 누적값이었음.)

## 5. 발견·수정한 결함 (smoke 가 잡음)

### 결함 A — 기간 미지정 재무 질문 오답
- "삼성전자 2025년 영업이익 알려줘"(기간 미지정) → 반복 시 "확정 수치 없음" 오답.
- 수정: `get_financial_facts` 에 일반 규칙 추가 — **business_year 있고 report_period 비면
  annual 로 해석**(`_resolve_report_period`). 손익 연간=cumulative, 재무상태표=point_in_time.
  단일 행만 반환하고, 없으면 no_data(다른 기간 대체 없음). 질문 파싱·특정 예외 없음.

### 결함 B — DuplicateToolCallMiddleware 요청 간 상태 누수 (치명)
- Agent 는 `get_agent_qa_service` 의 `lru_cache` 로 1회만 생성돼 모든 요청이 같은 middleware
  인스턴스를 공유한다. `_seen`(동일 Tool+인자 카운트)이 인스턴스 필드라 **요청 간 누적**되어,
  같은 질문을 두 번째 물으면 Tool 호출이 차단되고 "데이터 없음"으로 답했다.
- 초기 smoke·1차 검증이 처참(연간명시 0~1/4)했던 진짜 원인. (평가 스크립트는 질문이 다양·
  독립이라 안 드러남.)
- 수정: `before_agent` 훅에서 요청마다 `_seen` 초기화 → 요청 간 상태 누수 제거.

### FactsService.REPRT_LABEL 오매핑도 정정
- 5.5-F 에서 이미 공식 매핑(11011=연간 등)으로 수정 완료. 기간 라벨 정확.

## 6. 수정 후 재검증 (스테이징, 각 4회 반복)

| 케이스 | 결과 |
|---|---|
| 연도만("2025년 영업이익 알려줘") | 4/4 → 43.60조 |
| 연간 명시 | 4/4 → 43.60조 |
| 3분기 누적 | 4/4 → 23.53조 |
| 없는 기간(2099) | 4/4 → "없음"(대체 없음) |

홀드아웃 회귀: dev·holdout 재무 Exact Match 2/2·3/3 유지, 전 지표 통과. 전체 201 테스트·ruff 통과.

## 7. 운영 timeout
- 기본 8s 에서 복합 질문이 간헐 timeout → **12~15s 권장**. `.env.example` 반영.

## 8. 결론 / 운영 전환 판단
- 결함 A·B 수정으로 기간 미지정 재무 질문·반복 호출 모두 안정화(4/4). SSE·응답 시간 정상.
- **운영 flag 전환(agent_enabled=true 라이브)은 이번에도 하지 않는다** — 지시대로 smoke 결과
  보고 후 사용자 승인 뒤 진행. 현재 `agent_enabled=false` 유지.
