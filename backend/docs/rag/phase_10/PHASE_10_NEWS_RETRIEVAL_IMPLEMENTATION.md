# Phase 10 뉴스 기간 필터 최소 수정

## 확인된 제품 원인

Agent가 기간 표현이 없는 특정 사건 질문에 `relative_period=recent`를 추가했고,
Tool 경계가 이를 검증 없이 2일 범위로 변환했다. Phase 9 저장 trace의 뉴스
미적중 중 h-news-22·23·24가 이 경로로 Gold 범위에서 제외됐다.

## 수정

- 요청 원문을 `QaRuntimeContext.user_question`으로 Tool 경계에 전달한다.
- 일반 한국어 시간 표현을 `RelativePeriod`로 해석하는 순수 함수를 추가한다.
- 실제 Agent 요청에서는 모델이 만든 기간보다 사용자 원문의 명시적 기간을 우선한다.
  - 기간 표현 없음: `relative_period=None`
  - 최근·요즘·최신: `recent`
  - 오늘·어제·이번 주·이번 달·최근 7일·최근 30일: 대응 범위
  - 지난달: 이전 달의 달력 시작일부터 마지막 날까지
- 직접 Tool 호출처럼 질문 원문이 없는 호출은 기존 requested 인자를 그대로 보존한다.
- Tool 설명과 시스템 프롬프트에 “사건 식별어를 최근으로 해석하지 않는다”는
  일반 규칙만 보강했다.

Retriever 후보 생성, hybrid ranking, top_k, Gold, 채점기, 평가 데이터는 변경하지 않았다.

## 하드코딩 부재

제품 코드는 시간 표현만 검사한다. 다음을 참조하지 않는다.

- 홀드아웃 case ID
- news cluster/document/chunk ID
- 회사명·종목코드 목록
- 뉴스 제목·사건명·인물명·제품명
- 특정 날짜

테스트의 사건 예시도 홀드아웃 뉴스와 무관한 가상 표현을 사용한다.

## 검증

- 기간 없는 사건 질문 → `relative_period=None`
- 최근 뉴스 → `recent`
- 지난달 뉴스 → 이전 달 달력 범위
- 특정 사건명만 있는 질문 → recent 제거
- 명시한 기간 → 제거되지 않음
- 종목코드·query → 변경 없이 전달
- 질문 원문 없는 직접 Tool 호출 → 기존 API 계약 유지
- Backend Ruff 및 format: PASS
- 전체 unit/agent 회귀: **545 passed, warning 1**

Retriever는 수정하지 않았으므로 후보·ranking 테스트나 top_k 변경은 적용하지 않았다.
