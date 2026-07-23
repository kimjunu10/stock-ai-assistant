# Phase 4. 숫자·용어·혼합 질문 (기준 문서)

정확한 숫자(SQL)와 설명(RAG), 금융용어 조회를 하나의 답변으로 합친다 (SPEC §9·§11·§12).
사전 데이터 조사는 `DATA_SURVEY.md` 참고.

## 1. 역할 분리 (핵심)

| 대상 | 경로 | 근거 |
|---|---|---|
| 정확한 재무 숫자 | **SQL** `FactsService.get_financials` | financials(원 단위, 연결 CFS) |
| 구조화 공시 값 | **SQL** `get_structured_values` | structured_disclosures.normalized_data |
| 정정공시 최신본 | **SQL** `get_latest_disclosures`(is_latest=true) | disclosures |
| 공시/사건 설명 | **RAG** HybridRetriever | 뉴스 사건(+원문 success/요약) |
| 금융 용어 | **rag_terms** `lookup_term`(정확→별칭→유사) | 시드 6개 |

→ 숫자는 LLM이 추측/계산하지 않고 SQL 값을 그대로 fact로 주입. 설명만 RAG.

## 2. QueryPlan (규칙 기반, SPEC §9)

`app/rag/query_plan.py` — 추가 LLM 없이 신호어로 플래그를 켠다(혼합 질문은 복수 true).
- 숫자 신호(얼마/매출/영업이익/…) → `need_financials`
- 설명 신호(왜/의미/중요/…) → `need_documents`
- 용어 신호(뭐야/뜻/정의/…) → `need_terms`
- 정정 신호(정정/바뀐/…) → `need_correction`
- 종목 결정 우선순위: UI stock_code > 현재 문서 종목 > 질문 내 6자리 코드 (임의 선택 금지)

## 3. 값 정확성 규칙 (조사 근거)

- 재무 금액은 **원 단위 정수** 보존. 표시용 조/억 변환은 `format_won`(표현 계층)에서만.
- 기간: `reprt_code`(1분기/반기/3분기/사업보고서) + `amount_type`(당기/누적/시점값) 라벨.
- 연결/별도: `fs_div`(현재 CFS=연결만). 별도재무 없음 → 답변에서 "연결 기준" 명시.
- value_kind: 실제(actual)·공식(official)·전망(forecast) 구분. 전망을 실적처럼 말하지 않음.
- 정정: `is_latest=true` 우선. 정정 전 값을 최신처럼 답하지 않음.

## 4. QA 흐름 (`app/services/rag_qa_facts.py`)

`FactsQaService.answer`:
1. QueryPlan 생성
2. 숫자 조회(SQL) + 문서 검색(RAG) + 용어 조회를 **ThreadPoolExecutor로 병렬**
3. 정확 숫자·용어를 프롬프트 [정확 숫자]/[용어] 블록으로 주입
4. Solar 1회 호출로 합성
5. 반환: `sources`(설명 출처) / `numeric_sources`(숫자 출처) **분리** + `term` + `plan`

## 5. 코드/데이터

| 역할 | 위치 |
|---|---|
| QueryPlan | `app/rag/query_plan.py` |
| SQL 어댑터(읽기 전용) | `app/services/facts.py` |
| 통합 QA | `app/services/rag_qa_facts.py` |
| 프롬프트 facts/term 블록 | `app/rag/prompting.py` |
| 용어 시드(데이터) | `scripts/seed_rag_terms.py` → rag_terms |
| 소량 검증 | `scripts/rag_phase4_trial.py` |

## 6. 제약 (조사 기반)
- 별도재무(OFS)·2023 이전 재무 없음.
- 원문 설명은 disclosures.parse_status='success' 389건만(나머지는 구조화 요약으로 보완).
- 주가/수익률은 Phase 6.
- 기존 DART·재무 테이블은 **읽기 전용**(SELECT만). 변경 없음.
