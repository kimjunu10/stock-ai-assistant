# Post-PR79 RAG final regression report

## 판정

**종료 불가**

기준 `origin/main`과 실제 테스트 revision은 모두 `7fb0ba758e14c570e2f85ccf08c6cf847a0c01f3`(PR #88 merge)이다. 제품 코드·프롬프트·Tool·Retriever·Gold·채점기는 수정하지 않았다.

## 결과 구분

| 결과 종류 | 결과 | 의미 |
|---|---:|---|
| 기존 devset 120문항 재사용 회귀 | **108/120 formal (90.0%)** | 최신 코드 전체 회귀. 일반화 성능 아님 |
| 기존 holdout 40문항 동일 재사용 회귀 | **37/40 formal (92.5%)** | `post_pr79_same_holdout_regression`. 일반화 성능 아님 |
| 신규 targeted API 검증 | **7/15 계약 통과** | PR #76~88 기능 계약·안전성 검증. frozen 160과 합산 금지 |

세 결과를 하나의 정확도나 종합 점수로 합치지 않았다.

## 기본 테스트와 preflight

- Backend: Ruff check/format 통과, pytest **620 passed**.
- Frontend: lint 통과, Vitest **38 passed**, production build 통과.
- Frozen dataset validator **24/24 PASS**, holdout preflight **40/40 PASS**.
- dev 120 + holdout 40 모두 파일 순서대로 정확히 1회 실행, 재시도 0, 선택 재실행 0, 외부 장애 0.

## targeted API

통과: 선택 종목 암묵 재무, 동일 회사 명시, 다른 지원 종목 차단, 미지원 Apple 차단, 두 종목 차단, 어제 종가, `/qa`와 `/qa/stream` parity.

실패: 현재가 market status, 오늘 종가 current/close 혼동, 전일 대비 market status, 1개월·1년 market status, 기간 없는 흐름의 2점 차트, 뉴스 상충·인과 및 validation error. 내부 cluster 링크 자체는 통과했다.

`/qa`와 SSE는 최종 종목·숫자·출처·차트가 일치했다. 그러나 두 surface가 같은 결함도 공유하므로 parity 통과가 가격 의미 정확성을 보장하지는 않는다.

## devset 120 재사용 회귀

- Formal **108/120**, 환경 제외 0.
- Tool status `ok 123 / no_data 6 / error 0 / null 3`; step_limit 0.
- 사용자에게 보인 응답 120/120(정책 차단 응답 4건 포함).
- 뉴스 Recall **13/19**, Hit@1 **.4211**, MRR **.5123**.
- 리포트 Recall **9/15**, Hit@1 **.4667**, MRR **.5167**.
- 숫자 **.8947**, 단위 **.9474**, 기간 **1.0**, citation coverage **.9464**.
- 비용 **$0.727814**.

## 동일 holdout 40 재사용 회귀

- Formal **37/40**: `h-fin-20`, `h-news-23`, `h-news-24`.
- Tool status `ok 42 / no_data 0 / error 0 / null 1`; step_limit 0.
- Tool-bearing 문항 성공 **35/36**. 사용자에게 보인 응답 **40/40**(정책 차단 응답 3건 포함).
- 뉴스 canonical Recall/Hit@1/MRR **3/6 / .5 / .5**.
- 리포트 Recall/Hit@1/MRR **4/5 / .6 / .6667**.
- structured lookup **.8**; 숫자/단위/기간 **.8333 / 1 / 1**.
- citation coverage/precision **.9474 / 1**; 존재하지 않는 출처 0; 종목 오염 0.
- 비교 가능한 aggregate P50/P95 **3658/6242ms**; 비용 **$0.230742**.

## Phase 10 대비

뉴스는 2/6→3/6으로 개선됐지만 formal 39/40→37/40, 리포트 5/5→4/5, structured .9333→.8, citation coverage 1→.9474로 하락했다. 원인은 과잉 종목 차단, 구조화 공시 Tool 미선택, 증권사 제약 누락으로 각각 설명된다.

## 발표 사용 지침

- 반드시 “기존 문항 재사용 회귀” 또는 “targeted API 검증”이라고 표기한다.
- 발표 가능한 별도 수치: `dev 108/120 formal`, `same holdout 37/40 formal`, `targeted 7/15`.
- 이를 합쳐 `152/175` 같은 종합 정확도로 발표하면 안 된다.
- 현재는 종료 불가이므로 성공 지표만 떼어 “RAG 정확도”로 표현하지 않는다.

## 실제 실행된 시연 질문

안전하게 보여줄 수 있는 흐름:

1. `삼성전자 어제 종가 알려줘` — 확정 전일 종가 응답 통과.
2. 삼성전자 선택 상태에서 `SK하이닉스 올해 실적 알려줘` — mismatch 차단, Tool 0회.
3. `삼성전자와 SK하이닉스 실적을 비교해줘` — multi-stock 차단, Tool 0회.
4. `올해 영업이익 알려줘` — 선택 종목을 유지하고 데이터 없음 상태를 다른 기간으로 대체하지 않음.

현재가·오늘 종가·일반 주가 흐름·오늘 뉴스 질문은 결함이 해결되기 전 시연에서 제외한다.
