# Phase 7 후속 변경 기록

Phase 7 구현 이후 발견된 결함과 수정·검증 결과를 계속 누적한다. 질문 문구나 종목별
하드코딩, 키워드 라우터는 추가하지 않는다. Agent가 의미를 해석해 Tool을 선택하고,
Tool은 시간·정렬·숫자 같은 결정론적 정확성을 보장한다.

## 2026-07-26 — Phase 7 마무리(통합 점검·부족 기능 보완)

브랜치 `phase/7-finalization`. main(#44/#45 머지·운영 배포 완료) 기준으로 감사 후
데이터가 이미 있는 부족 기능을 보완했다. 값·날짜 재계산이나 답변 파싱은 하지 않고,
확정된 ToolResult 값만 UI view로 변환한다.

### 뉴스 compact 카드 보강(§4)
- news Tool item에 `sentiment`(호재/악재/중립)와 `stock_code`를 추가. 감성은 사건
  조회 경로에서 `news_clusters.sentiment_label`로 채워지고(하이브리드 검색 경로는 None),
  UI는 값이 있을 때만 배지를 그린다. Tool·Agent는 감성을 새로 판정하지 않는다.
- 프런트 `NewsCards`에 감성 배지·종목 코드 배지 추가(기존 카드 variant 확장, 복제 아님).

### 사건 타임라인(§6, event_timeline)
- 같은 답변에서 뉴스와 공시가 **둘 다** 조회됐을 때만, 확정된 사건(제목·발표시각)을
  발표시각 최신순으로 병합해 `event_timeline`을 생성. 단일 종류면 각자 카드로 충분.
- `_build_ui_payload`에 cross-tool 병합 단계 추가(`_event_timeline`). 새 조회 없음.
- 프런트 `EventTimeline` 렌더러 추가.

### 실적 vs 전망 비교(§6, financial_comparison) — 미지원(사유 기록)
- **데이터 부족으로 구현하지 않았다.** 실제 실적은 DART(`financials`)로 있으나,
  증권사 리포트 Tool은 **목표주가만 구조화**하고 추정 매출·영업이익·EPS 등 전망
  재무수치를 구조화된 값으로 반환하지 않는다(`table_value_kinds`는 값이 아닌 카운트).
- 필요한 백엔드 계약: 리포트 파서가 추정 실적 표를 항목·기간·값으로 구조화해
  `forecast_financials` 형태로 반환해야 실제/전망 병렬 비교 payload를 만들 수 있다.
  값이 없는 상태에서 지원한다고 표시하지 않는다(빈/환각 차트 금지).

### 리포트·공시 출처 이동(§5)
- **공시**: `rcept_no`가 있으면 DART 공식 공개 뷰어 URL
  (`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=...`)을 SourceRef.url에 실어 새 탭
  이동. 비공개 저장소 경로·signed URL·존재하지 않는 주소는 만들지 않는다.
- **리포트**: 원문 URL이 없으므로 우선순위 4(내부 근거 보기)를 구현. SourceRef.locator에
  검증된 근거 문장(`evidence`)·목표주가(stated만)·투자의견을 실어, 프런트에서 클릭 시
  인라인으로 근거 페이지·목표주가(전망값 표기)·근거 문장을 펼친다.

### 한 달 주가 그래프 점 수(§7)
- get_stock_prices가 UI 전용 `daily_full`(실제 거래일별 종가, 최대 60거래일)을 별도로
  반환. 모델용 요약 `daily`(앞3+뒤3)는 그대로 유지해 답변 문맥을 키우지 않는다.
  UI 선그래프는 `daily_full` 우선, 없으면 `daily`. 프런트는 값을 재계산하지 않는다.
  200개 API 상한·캐시는 StockPriceService가 그대로 처리. Tool docstring에 흐름·추이
  질문 시 include_daily 안내 추가(키워드 라우터 아님).

### 스트리밍 진행 상태의 실제성(§8)
- 조사: LangChain create_agent는 `.stream()`/`astream_events()`로 실제 tool 이벤트
  스트리밍이 가능하나, 현재 동기 `invoke` 구조를 진짜 실시간 스트리밍으로 바꾸는 것은
  이번 마무리 범위에서 리스크가 크다(단일 Agent·표준 실행 유지, 직접 StateGraph 금지).
- 결정(§170-173 대안): 백엔드가 invoke 완료 후 도구 이벤트를 한꺼번에 내보내므로,
  **작업 중에는 일반 진행 라벨("근거 자료 확인 중")만 표시**하고 도구별 라벨을 순서대로
  재생하지 않는다(허위 진행 상태 제거). 내부 추론·전체 도구 인자는 노출하지 않는다.
  실제 실시간 스트리밍은 후속 과제로 남긴다.

### 검증
- 백엔드 pytest 316 passed(+3), ruff check·format 통과, Agent 평가 recall 1.0/forbidden 0.0.
- 프런트 tsc·oxlint·vitest 13(+4) 통과, vite production build 통과.
- Agent 경유 실제 API: 뉴스+공시→event_timeline 생성, 공시→DART url, 리포트→근거보기
  evidence, 주가→daily_full 22거래일 확인. price_line은 daily_full 우선 사용 확인.

## 2026-07-26 — 최근 뉴스 계약·뉴스 카드·긴 답변 스크롤

### 최근의 기준

- 기간 없는 `최근/요즘/최신` 뉴스 질문은 Agent가
  `search_news(relative_period="recent")`를 선택한다.
- `recent`는 서버의 KST 요청일을 기준으로 **오늘부터 2일 전까지** 양 끝을 포함한다.
  예를 들어 2026-07-26 요청은 `2026-07-24 ~ 2026-07-26`이다.
- 날짜 계산은 모델이 하지 않고 `time_context.resolve_relative_date_range`가 담당한다.
- 해당 범위에 뉴스가 없으면 7일·30일 전 자료로 자동 확장하지 않는다.
- 질문 문구나 기업별 분기, 종목별 하드코딩은 추가하지 않았다.

### 뉴스·답변 UI

- `search_news` ToolResult에 각 뉴스의 `source_id`와 검증된 원문 `url`을 함께 담는다.
- 공개 visualization에 `news_cards`를 추가했다.
- 뉴스 카드는 조회 기간, 기사 수, 언론사 수, 제목, 요약, 발행일, 원문 링크를 표시한다.
- 같은 뉴스 출처를 하단 가로 출처 카드로 다시 복제하지 않는다.
- 자연어의 번호 목록과 불릿을 HTML로 해석하지 않고 안전한 React 텍스트 목록으로
  렌더링한다. 기사 내용을 답변 줄글로 반복하지 않도록 Agent 응답 원칙도 간결화했다.
- 주가 시계열, 수익률, DART 재무, 구조화 공시, 증권사 목표주가는 기존처럼 Tool이
  확정한 값만 각각 차트·지표 카드·표형 UI로 표시한다.

### 스크롤

- `100vh` 대신 모바일 주소창을 반영하는 `100dvh`를 사용한다.
- 채팅 부모의 모든 grid 단계에 `min-height: 0`과 overflow 경계를 명시했다.
- 메시지 끝 sentinel로 답변·카드 렌더 후 내부 대화 영역을 끝까지 이동한다.
- 모바일에서는 하단 고정 내비게이션과 safe-area만큼 대화 영역 아래 여백을 둔다.

### 검증

- Backend Tool/UI payload 테스트: 26 passed
- Backend Agent 전체 테스트: 70 passed (`AGENT_ENABLED=false` 격리 기준)
- Frontend 전체 Vitest: 4 files, 9 tests passed
- Frontend oxlint: PASS
- Frontend TypeScript + Vite production build: PASS
- 실제 Agent: 2026-07-26 요청에서 `2026-07-24 ~ 2026-07-26`, 뉴스 5건 확인
- 브라우저 1280×720: 페이지 가로 overflow 0, 내부 대화 끝 sentinel 도달
- 브라우저 390×844: 페이지 가로 overflow 0, 단일 열 뉴스 카드, 내부 스크롤
  `scrollTop == maxScrollTop` 확인

## 2026-07-25 — 초보자용 재무 요약·컨센서스 조사

네이버 증권 Financial Summary와 투자의견 컨센서스의 데이터 구성, 접근 방식,
FnGuide 라이선스, 현재 DART·리포트 데이터의 대체 가능성을 조사했다. 구현과 DB 변경은
하지 않았다.

결론:

- 네이버/WiseReport 내부 HTML·AJAX 운영 스크래핑은 채택하지 않음
- OpenDART 공식 주요 재무지표는 종목 UI와 RAG에 바로 확장 가능
- 현재 리포트로 제한적 목표주가 요약은 가능하지만 `시장 컨센서스`로 부르지 않음
- FnGuide식 추정실적·전체 컨센서스는 정식 API와 외부 노출 계약이 필요

상세: `PHASE_7_BEGINNER_FINANCIAL_CONSENSUS_RESEARCH.md`

## 2026-07-25 — 시간 기준·DART 최신 실적·가독성

### 발견한 문제

1. `어제 삼성전자 호재` 질문에서 Agent가 어제를 `2024-04-25`로 잘못 해석했다.
   기존 RuntimeContext와 시스템 프롬프트에는 서버 현재 일시·시간대가 없었다.
2. `최근 삼성전자 실적` 질문에서 `2025년/2024년 3분기`를 최신값처럼 답했다.
3. 답변의 재무 카드와 출처 카드가 8~10px 중심이라 실제 화면에서 읽기 어려웠다.

### DART 데이터 확인

실제 `financials` 테이블의 삼성전자(`005930`) 매출액을 확인했다.

- 2026년 1분기 `11013`, CFS, 누적/당기 행 존재
- 2025년 사업보고서와 1·2·3분기 행 존재
- 기존 화면의 2025년 3분기 239.77조원, 2024년 3분기 225.08조원도 DB에 존재

따라서 2026년 데이터 미수집이 아니라 Agent가 오래된 보고기간을 선택한 결함이었다.
사용자가 제시한 외부 표의 `(E)`는 전망치이므로 DART 공식 확정 실적과 섞지 않는다.

### 시간 처리

- 요청 시작 시 `Asia/Seoul` 기준 timezone-aware 현재 일시를 한 번 계산한다.
- `QaRuntimeContext`에 `current_datetime`, `current_date`, `timezone`을 넣는다.
- LangChain `dynamic_prompt`로 모든 모델 호출에 같은 런타임 시간 기준을 주입한다.
- 뉴스 Tool에 일반화된 `relative_period` typed 인자를 추가했다.
- Agent는 상대 기간의 의미를 선택하고, 백엔드는 KST 기준 ISO 범위를 계산한다.
- 지원 범위: `recent`, `today`, `yesterday`, `last_7_days`, `last_30_days`,
  `this_week`, `this_month`.
- 사용자 질문 문자열을 백엔드에서 파싱하거나 Tool을 강제하는 분기는 없다.

### DART 최신 실적 처리

- 재무 Tool에 `period_mode=latest|exact|history` 계약을 추가했다.
- 기간 미지정 최신 조회는 모델이 후보 중 하나를 고르지 않고 Tool이 최신 공식
  보고기간 하나만 반환한다.
- DART `reprt_code`의 숫자 크기를 시간 순서로 사용하지 않고 공식 순서
  `1분기 → 반기 → 3분기 → 사업보고서`로 정렬한다.
- 광범위한 실적 조회에서 항목을 생략하면 Tool 한 번으로 매출액·영업이익·당기순이익을
  조회한다. 이는 질문 키워드 분기가 아니라 입력 생략 시 적용되는 Tool 기본 계약이다.
- 정확한 기간이나 항목이 지정되면 해당 typed 인자를 그대로 사용한다.

### UI 가독성

- 자연어 답변: 14px → 16px
- 재무/주가 카드 제목·배지·보조정보: 8~12px → 11~14px
- 주요 값: 16px → 18px
- 출처 카드 라벨·제목·메타·실제값 배지: 8~10px → 11~13px
- 출처 카드 최소 폭: 190px → 230px
- 경고 문구: 9px → 12px

### 실제 Agent smoke

`어제 삼성전자 호재 있었음?`

- `search_news` 1회, status `ok`
- 서버 기준 어제: `2026-07-24`
- 반환 뉴스의 `published_at`: `2026-07-24`
- 최종 답변도 `어제(2026년 7월 24일)`로 표시

`최근 삼성전자 실적`

- `get_financial_facts` 1회, status `ok`
- 최신 공식 기간: `2026년 1분기보고서 누적`, 연결
- 매출액·영업이익·당기순이익 3개를 같은 보고기간으로 반환
- 2025년/2024년 3분기를 최신값으로 섞지 않음

### 검증

- Agent 관련 테스트: 36 passed
- Backend 전체 테스트: 297 passed
- Backend Ruff: PASS
- Frontend Vitest: 3 files, 7 tests PASS
- Frontend TypeScript + Vite production build: PASS
- Frontend oxlint: PASS
- 실제 브라우저 데스크톱 렌더: 답변 16px, 지표 라벨 12px, 값 18px,
  보조정보 11px, 출처 제목 13px 확인
- 390×844 모바일 렌더: viewport/body/scroll width 모두 390px, 가로 overflow 0,
  재무 카드 단일 열, console warning/error 0

## fix/phase-7-exit-gate — 사건 후속 질문 기간 오류 근본 수정

운영에서 "그 뉴스 이후 주가가 어떻게 됐어?"가 사건 발표일이 아닌 최근 1개월 수익률로
답하던 결함을 수정했다. 상세 원인·계약은 `PHASE_7_BUG_EVENT_REFERENCE.md`,
검증 결과는 `PHASE_7_EXIT_GATE.md` 참조.

### 백엔드 계약 변경

- `calculate_event_return`(파괴적): `event_date` 필수화, `lookback` 인자 제거.
  발표일은 서버 확정 문맥에서만 오며 Agent가 넘긴 날짜는 무시한다. 사건 미확정·복수
  사건이면 계산을 거부하고 후보를 반환한다. 결과는 발표 전 마지막 확정 거래일 기준
  발표 후 1·3·5거래일 종가·수익률(확정된 지평만).
- `StockPriceService.get_event_window_return` 추가(수익률 계산 단일 지점 유지).
  발표 후 확정 거래일이 없으면 `has_post_data=False`로 데이터 부족을 그대로 표현한다.
- `QaRequest.event_context` / `selected_event_id` 추가(비파괴적). 사건 식별자·발표일·
  종목·사용자 선택 여부를 구조화해 전달한다. 서버 대화 상태는 만들지 않는다.
- `app/agent/event_reference.py` 신규: 사용자 선택 우선 → 서로 다른 사건 1개면 자동
  연결(같은 사건 기사 여러 건은 클러스터 하나) → 그 외 명확화.
- `QaRuntimeContext`에 확정 사건 필드 추가, 시스템 프롬프트에 사건 문맥·기간 선택 규칙 주입.
- `validate_event_grounding` 추가: "이 뉴스 이후" 주장에 사건 근거(식별자·발표일·거래일·
  계산 결과)를 요구하고, 없으면 숫자를 고치지 않고 안전 답변으로 전환한다.

### 함께 수정한 검증기 오탐 3건

날짜 표기(`2026-07-25`), 종목코드(`999999`), 뉴스 기사 인용 수치가 "근거 없는 재무 숫자"로
오탐되던 문제. 각각 회귀 테스트로 고정했다.

### 검증

- 백엔드 pytest 372 passed / 1 failed(`test_feature_flag_off_returns_none` — 로컬 `.env`
  의존, `main`에서도 동일 실패), ruff check·format 통과
- API 종료 게이트: `/qa` 20 시나리오, `/qa/stream` 17건 전부 통과. 사건 후속 반복 15회 편차 0
- 필수 기능 호출률 100%, 금지 기능 호출 0%, 기간 대체 0건, 임의 사건 선택 0건
