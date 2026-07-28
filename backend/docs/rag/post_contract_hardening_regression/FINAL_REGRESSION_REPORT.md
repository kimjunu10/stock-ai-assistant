# RAG contract hardening final regression

## 판정

**종료 불가.**

기존 160문항 재사용 회귀와 신규 targeted API 검증을 분리해 실행했다. 가격·차트·내부
뉴스 링크·일반/SSE 일치·컨텍스트 챗 가독성은 개선됐지만, 종목 안전장치 false positive,
정책과 Gold 충돌, 리포트 page 계약 회귀가 남아 종료 기준을 충족하지 못한다.

## 기준 revision

- 최신 기준 `origin/main`: `7fb0ba758e14c570e2f85ccf08c6cf847a0c01f3`
- 실제 테스트 revision: `7e74180484fa2642183e0e01e08e047bc1e0b304`
- 브랜치: `codex/rag-contract-hardening`
- 기존 데이터 질문·Gold·순서·분할: 변경 없음

## 코드 수정

사용자의 수정 요청에 따라 평가 전에 제품 코드를 수정했다. 질문별 답을 하드코딩하거나
고정 출력 틀을 만들지 않았다.

- 컨텍스트 뉴스/리포트: 상투적 `쉽게 말해` 도입 제거, 긴 단일 문단의 적응형 요약+불릿
- 가격: `price_kind`, `market_status`, `as_of`, 현재가/확정 종가 구분
- 차트: 기간 없는 일반 흐름만 기본 1개월
- 뉴스: 근거 없는 직접 인과 문장 제거, 상충 방향 합성 방지
- 종목 문맥: 인물/증권사 역할 필터와 Tool 실행 전 차단
- 재무/공시/리포트: 계정 별칭, 분기 유형, 구조화 공시 유형, 증권사 필터 정규화
- 컨텍스트 리포트의 stated 목표주가를 validator evidence로 전달

## 기본 테스트

- backend Ruff format/check: PASS
- backend unit/integration/Agent: **633 passed**, warning 1건(Starlette deprecation)
- frontend: **39 passed**
- frontend lint: PASS
- frontend production build: PASS
- 평가 데이터 정적 검사: 18/18 PASS
- DB/Gold preflight: PASS (뉴스 6/6, 리포트 14/14, 재무 6/6, 공시 5/5)

## 신규 targeted API 검증

이 결과는 기존 160문항과 섞지 않은 별도 targeted API 검증이다.

- 최종 commit iteration3: **14/15**
- 일반 `/qa`와 `/qa/stream` 가격·source·시각화 일치: PASS
- 종목 불일치/미지원/다중 종목 Tool 0회 차단: PASS
- 현재가·오늘/어제 종가 구분: PASS
- 1개월/1년/기본 1개월 차트: PASS
- 뉴스 내부 cluster 링크: PASS
- 실패 1건: 자정 직후 새 날짜의 “오늘 뉴스”가 `no_data`; 원칙에 따라 재시도하지 않음
- 참고: 같은 코드 변경 집합의 자정 전 iteration2는 15/15였지만 최종 지표로 합산하지 않음

## 기존 devset 120문항 재사용 회귀

이 수치는 일반화 정확도가 아니라 기존 문항 재사용 회귀다.

- formal-condition pass: **111/120 (92.5%)**
- 실제 Tool 실행 성공: **113/113**
- Tool status: `ok` 130, `no_data` 3, `error` 0, `null` 0
- 최종 답변 완료: 118/120 (`news-14`, 미지원 `na-02`는 안전 차단)
- `step_limit`: 0
- 뉴스 canonical Recall/Hit@1/MRR: 13/19, 0.4211, 0.5123
- 리포트 Recall/Hit@1/MRR: 15/15, 1.0, 1.0
- 숫자 exact / 단위 / 기간: 0.9474 / 1.0 / 1.0
- citation coverage / precision: 0.9821 / 1.0
- 타 종목 오염 / 존재하지 않는 citation: 0 / 0
- P50/P95: 4452/16831 ms
- 비용: $0.733005

## 기존 holdout 40문항 동일 문항 회귀

이 수치는 일반화 정확도가 아니라 기존 Phase 8 홀드아웃 동일 문항 회귀다.

- formal-condition pass: **37/40 (92.5%)**
- 실제 Tool 실행 성공: **36/36**
- Tool status: `ok` 41, `error` 0, `null` 0
- 최종 답변 완료: 37/40
- `step_limit`: 0
- 뉴스 canonical Recall/Hit@1/MRR: 3/6, 0.5, 0.5
- 리포트 Recall/Hit@1/MRR: 5/5, 1.0, 1.0
- structured row hit: 0.9333
- 숫자 exact / 단위 / 기간: 0.8333 / 1.0 / 1.0
- citation coverage / precision: 0.9474 / 1.0
- 타 종목 오염 / 존재하지 않는 citation: 0 / 0
- P50/P95: 3590/8924 ms
- 비용: $0.224659

## Phase 8·9·10 대비

- formal: 34/40 → 39/40 → 39/40 → **37/40**
- 뉴스 canonical: 0/6 → 2/6 → 2/6 → **3/6**
- 리포트 Recall: 0/5 → 5/5 → 5/5 → **5/5**
- `error/null/step_limit`: 이번 실행 **0/0/0**
- Phase 10 실제 실패 2건의 `h-na-09` 타 회사 Tool 실행/null은 재발하지 않았다.
- formal 하락 원인은 `h-fin-23` Gold 의미 불일치와 `h-news-23/24` 안전 차단이다.
- 리포트 page accuracy는 Phase 10 4/14에서 0/14로 하락해 설명 가능한 계약 회귀다.

## 치명적 정확성·안전성

- 타 회사 수치·출처 혼입: 발견 없음
- 현재가를 확정 종가로 표현: targeted 최종 답변에서 발견 없음
- 실제 quote와 답변 숫자 불일치: 발견 없음
- 질문과 차트 기간 불일치: 발견 없음
- cluster ID 외부 링크: 발견 없음
- 출처 조작/존재하지 않는 citation: 발견 없음
- 남은 종료 방해 문제:
  - 인물을 회사로 오인하는 안전장치 false positive (`h-news-23`)
  - 다중 회사 뉴스 정책과 Gold 충돌 (`h-news-24`)
  - 동일한 “3분기” 표현의 누적/단독 Gold 불일치 (`h-fin-20` 대 `h-fin-23`)
  - 리포트 page top-level 계약 0/14
  - targeted 최종 실행의 날짜 전환 `no_data`

## Solar Judge

Solar는 devset 120/120, holdout 40/40을 모두 통과시켰지만 formal은 111/120,
37/40이었다. 최소 12개 formal 실패를 통과시켰으므로 false positive가 있다.
Solar 통과만으로 성공이나 RAG 정확도를 발표하면 안 된다.
