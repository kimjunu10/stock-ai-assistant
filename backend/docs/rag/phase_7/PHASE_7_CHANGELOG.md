# Phase 7 후속 변경 기록

Phase 7 구현 이후 발견된 결함과 수정·검증 결과를 계속 누적한다. 질문 문구나 종목별
하드코딩, 키워드 라우터는 추가하지 않는다. Agent가 의미를 해석해 Tool을 선택하고,
Tool은 시간·정렬·숫자 같은 결정론적 정확성을 보장한다.

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
- 지원 범위: `today`, `yesterday`, `last_7_days`, `last_30_days`,
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
