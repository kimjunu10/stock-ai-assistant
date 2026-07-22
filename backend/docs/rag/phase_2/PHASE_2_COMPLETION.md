# Phase 2 완료 보고 (100건 검증)

- 완료일: 2026-07-22
- 브랜치: `rag/phase2`
- 범위: 뉴스 사건 **100건 시험 인덱싱 + 검색·답변 흐름 검증**까지. 전체 인덱싱과 Phase 3는 진행하지 않음(대기).

## 완료한 작업
- 뉴스 사건 원본 조회(활성 clustering_version + 요약성공 + factual_body + 종목)
- 텍스트 정규화(NFKC/공백/엔티티, 숫자·단위·종목코드 보존)
- 뉴스 사건 청킹(1200자 규칙, 500~900자 분할, overlap≤100, 사건당 최대 3청크)
- 대표 기사 원문 제외(사건 통합 본문만 인덱싱)
- passage 임베딩(Upstage Embed 2, 1024차원, 배치100)
- 해시 기반 중복 임베딩 방지
- 뉴스 100건 시험 인덱싱
- 의미 검색(pgvector cosine RPC) + 현재 문맥 우선
- QA 요청/응답 모델, Solar 답변 생성, SSE 스트리밍
- 출처 배열 반환 + 인용 번호 검증
- 뉴스 질문 smoke test, 응답시간·비용 측정

## 수정/추가한 파일
- 신규 구현: `app/rag/normalization.py`, `chunking.py`, `indexing.py`, `retrieval.py`, `prompting.py`
- 신규 구현: `app/ml/embeddings.py`, `app/ml/generation.py`
- 신규: `app/services/rag_qa.py`, `app/schemas/qa.py`
- 구현: `app/api/routes/qa.py` (기존 placeholder → 엔드포인트)
- 마이그레이션: `migrations/0016_rag_search_semantic.sql` (+ rollback)
- 설정: `app/core/config.py` RAG 키 추가
- 스크립트: `scripts/rag_phase2_trial.py`
- 테스트: `tests/unit/test_rag_phase2.py` (신규 12개)
- 산출물: `docs/rag/phase_2/` (본 보고서, 기준 문서, `trial_100_result.json`)

## DB 변경
- 신규 RPC 함수 `rag_search_semantic` 1개 추가(0016).
- 데이터: `rag_documents` news_event 100건 + `rag_chunks` 109건 **신규 삽입**(기존 테이블/데이터 무변경).
- 기존 뉴스/DART/재무 데이터는 읽기만 함.

## 테스트 결과
- pytest: **70 passed** (기존 58 + 신규 12, 회귀 없음)
- 100건 시험 인덱싱: processed 100 / indexed 100 / chunks 109 / **failures 0** / 24.6s
- 재실행(멱등): **skipped_unchanged 100**, 임베딩 0회(비용 0), 2.3s → 해시 중복방지 정상
- 검색 smoke(6질문): **self_in_top_rate = 1.0**(모두 rank 1), 출처 각 8개, **invalid_citations 0**
- 인과 단정 표현("때문에 상승/하락") 없음
- API: `POST /api/qa` 200(출처8, 인용오류0), `POST /api/qa/stream` SSE 정상(sources→token×442→done)

## 실제 응답 시간과 비용
- 검색: ~130ms
- 답변 생성(Solar): 평균 ~3.9초 (2.9~5.5초)
- 임베딩: 100사건/109청크 ≈ 24.6초(배치), 재실행 시 0회
- 비용: query 임베딩 6건 + passage 109건 + Solar 답변 6건 수준. 소량. (전체 2,940건 인덱싱 시 규모는 Phase 2 승인 후 별도 측정)

## 최소 통과 조건 판정
| 조건 | 판정 |
|---|---|
| 현재 뉴스 질문이 상위 검색에 포함 | ✅ rank 1 (100%) |
| 답변에 출처 표시 | ✅ sources 배열 |
| 존재하지 않는 인용 번호 없음 | ✅ invalid 0 |
| 관련 없는 대표 기사 추천 문구 미검색 | ✅ 대표 원문 미인덱싱 |
| 첫 응답을 빠르게 | ✅ SSE 토큰 스트리밍 |

## 기획서와 달라진 점
1. **의미 검색 RPC(0016) 추가**: PostgREST로 pgvector 연산이 어려워 SQL 함수로 노출.
   - 영향: Phase 3 하이브리드의 기반. 사용자 확인 불필요.
2. **문서 content_hash = 청크 결합 해시**로 정의(중복 방지 단위).
   - 영향: 사건 내용 변경 시에만 재임베딩.
3. **검색 top_k=8, 후보 24** 기본값(계획서 "결과 보고 조정" 여지 범위).
4. Phase 2는 의미 검색만. 키워드+RRF는 Phase 3(계획서 명시 범위).

## 아직 남은 문제 / 유의
- **전체 활성 뉴스(2,940건) 인덱싱은 미실행** — 승인 후 진행 예정.
- `context_source_id`는 뉴스 사건 id(source_pk) 기준. 프런트 연동은 Phase 7.
- 답변 형식 세부 문장은 UI 확정 시 조정 가능.

## 사용자 확인이 필요한 것
- 없음 (데이터 손상·비용 초과·보안 위험·회귀 없음)
- 다만 **전체 인덱싱 진행 여부는 승인 대기** (지시대로 자동 진행하지 않음)

## 다음 단계
- 이 100건 결과 승인 시:
  1) 전체 활성 뉴스 인덱싱(Phase 2 마무리) 또는
  2) Phase 3(하이브리드 검색) 진행
- 어느 쪽이든 **자동 진행하지 않고 대기**.

---

## Phase 종료 기록 (계획서 반영용)
```text
상태: 100건 검증 완료 (전체 인덱싱 대기)
완료일: 2026-07-22
시험 인덱싱 건수: 100 (청크 109)
최종 인덱싱 건수: 미실행(전체 2,940건은 승인 후)
평균 응답 시간: 검색 ~0.13s + 생성 ~3.9s
첫 토큰 시간: SSE 스트리밍 즉시(생성 시작과 함께)
비용: 시험 규모 소량(임베딩 109청크 + query/answer 6건)
답변 포맷 변경 사항: 계획서 형식 그대로(한 줄 결론/쉽게/자세히/핵심 숫자/주의)
남은 문제: 전체 인덱싱 미실행, 하이브리드는 Phase 3
```
