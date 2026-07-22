# Phase 4 사전 데이터 조사 (읽기 전용)

- 조사일: 2026-07-22
- 방식: 전부 읽기 전용 SELECT. 기존 데이터 변경 없음.
- 대상: `financials`, `structured_disclosures`, `disclosures`, `corporate_events`, `company_profiles`

## 1. 테이블 건수

| 테이블 | 건수 |
|---|---:|
| financials | 510 |
| structured_disclosures | 1,524 |
| disclosures | 4,722 |
| corporate_events | 142 |
| company_profiles | 5 |

## 2. financials (정확한 재무 숫자의 1차 소스)

### 구조
- 키: `(stock_code, bsns_year, reprt_code, fs_div, account_nm, amount_type)` 로 값 1개 유일 특정.
- `thstrm_amount`(당기), `frmtrm_amount`(전기). **단위 컬럼 없음 → 원(KRW) 단위 정수.**
  - 예: 삼성전자 매출액 133,873,444,000,000 = 약 133.9조 원.
- `fs_div`: **CFS(연결)만 존재.** 별도(OFS) 없음.
- `reprt_code`(DART 표준): 11011=1분기, 11012=반기, 11013=3분기, 11014=사업(연간)보고서.
- `amount_type`: `quarter`(당기 3개월), `cumulative`(누적), `point_in_time`(재무상태표 시점값).
  - 1분기(11011)는 당기=누적이라 `quarter` 행이 없고 `cumulative`만 있음.

### 범위
- 종목 5개(005930, 000660, 034020, 042660, 005380) × 연도 2024~2026 × 분기 4종.
- 종목당 102행, 총 510행. fs_div는 전부 1종(CFS).

### 지원 account_nm (자주 묻는 항목)
매출액, 영업이익, 당기순이익(각 80행) / 자산총계, 부채총계, 자본총계, 영업·투자·재무활동현금흐름(각 45행).

### NULL / 이상치
- `thstrm_amount` NULL 0, 0값 0. `frmtrm_amount` NULL 105(현금흐름 등 전기 미제공 항목).
- 음수 존재(적자/현금유출, 정상). min -85.4조 ~ max 633조.
- **중복 없음**: (키 6요소) 조합별 1행. (앞선 "2행"은 quarter/cumulative 서로 다른 amount_type)

## 3. disclosures (원문 공시 + 정정 이력)

### 정정/최신본 구분 필드
- `is_latest`(bool): 최신본 여부. `correction_status ∈ {original, correction, cancelled, withdrawn}`.
- 정정 체인: `original_rcept_no`(최초), `supersedes_rcept_no`(직전본).
- 분포: original 4,472 / correction 216(is_latest=t) + 4(f) / cancelled 2 / withdrawn 3.
- **최신 정정본 조회 규칙: `is_latest = true` 우선. 정정 전(is_latest=false)을 최신처럼 답하면 실패.**

### 원문(raw_text) 상태 (RAG 설명 가능 범위)
- `parse_status`: success 389(raw_text O) / pending 4,332(raw_text NULL) / unavailable 1.
- 즉 **원문 기반 RAG 설명은 success 389건만 가능.** 종목별 고루 분포(042660:115, 000660:75, 005380:73, 005930:70, 034020:56).
- `raw_text_truncated` = 0(잘린 원문 없음).

## 4. structured_disclosures (구조화 공시 값 + 요약)

- `data_group`: regular_report(정기보고서) / major_event(주요사항).
- `event_type`: dividend_matter 603, capital_change_status 415, treasury_stock_status 343,
  stock_total_status 138, treasury_stock_disposal 16, treasury_stock_acquisition 6 등.
- `normalized_data`(jsonb): 이벤트별 구조화 값. 금액은 원 단위 정수, 통화·기관명은 텍스트로 병기.
  - 예: 자기주식 처분 `disp_planned_amount_common: 322755945000`(원), `disp_unit_price_common: 285000`.
- `summary_text`: 거의 전부 존재(regular 1,499/1,499, major 25/25) → **RAG 설명 소스로 활용 가능.**
- 연결키 `rcept_no`: 1,524건 전부 존재, 그중 548건이 `disclosures.rcept_no`와 매칭.

## 5. corporate_events (일정성 이벤트)

- event_type: ir 52, earnings 40, shareholders_meeting 25, dividend 20, record_date 5.
- `amount`는 dividend 2건만 존재(대부분 일정 정보라 금액 없음). 날짜 필드 위주.

## 6. SQL(정확 값) vs RAG(설명) 역할 구분

| 질문 성격 | 경로 |
|---|---|
| "영업이익 얼마?" 등 정확 숫자 | **SQL** — financials/structured_disclosures/corporate_events에서 조회 |
| "왜 늘었어?", "이 공시가 왜 중요해?" 설명 | **RAG** — disclosures.raw_text(success) + structured.summary_text 검색 |
| "ADR이 뭐야?" 용어 | **rag_terms** 정확일치/별칭/유사 검색 (현재 0건 → 소량 시드 필요) |
| 혼합("얼마고 왜 늘었어?") | SQL 숫자 + RAG 설명 병렬 후 합성 |

## 7. 현재 데이터로 답할 수 있는/없는 질문

### 답 가능
- 5종목 2024~2026 분기별 매출·영업이익·순이익·자산/부채/자본·현금흐름 (연결 기준, 원 단위).
- 정정공시 최신본 존재 여부·정정 전후 구분(구조화/원문 success 건).
- 자기주식·배당·증자 등 구조화 이벤트 값과 요약.
- 일정성 이벤트(IR·주총·실적발표 날짜).

### 답 불가 / 제약
- **별도재무(OFS)**: 데이터 없음 → "연결 기준"만 답하고 별도는 없다고 명시.
- **원문 설명 pending 4,332건**: raw_text 없음 → 원문 인용 설명 불가(구조화 요약으로 보완).
- **2023년 이전 재무**: 없음.
- **금융용어**: rag_terms 비어있음 → 시드 넣기 전엔 용어 질문 불가.
- **주가/수익률**: Phase 6 범위(여기서 안 다룸).

## 8. 구현 시 고정 규칙 (조사 근거)
- 재무 금액은 원 단위, 표시 시 조/억 변환은 표현 계층에서만(값 자체는 원 정수 보존).
- 연결/별도는 `fs_div`로 라벨(현재 CFS=연결). 누적/당기는 `amount_type` 라벨.
- 정정공시는 `is_latest=true` 우선, 정정 전은 별도 표기.
- 특정 종목/항목/공시번호를 코드에 하드코딩하지 않음(전부 파라미터/데이터 기반).
