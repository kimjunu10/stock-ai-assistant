# RAG_PHASE_EXECUTION_PLAN.md

## 0. 이 문서의 역할

이 문서는 `RAG_IMPLEMENTATION_SPEC.md`를 실제 개발 순서로 실행하기 위한 **진행 체크리스트**다.

Claude Code 또는 Codex는 아래 규칙을 따른다.

- 한 번에 전체 RAG를 구현하지 않는다.
- 현재 Phase 안에서는 필요한 코드 변경을 유연하게 수행한다.
- 사소한 구현 선택 때문에 작업을 멈추지 않는다.
- 기획서와 달라지는 부분은 숨기지 말고 기록한다.
- 각 Phase가 끝나면 이 문서의 체크박스와 진행 기록을 직접 갱신한다.
- 다음 Phase로 자동 진행하지 않고 결과를 보고한 뒤 기다린다.

관련 문서:

```text
docs/rag/RAG_IMPLEMENTATION_SPEC.md
docs/rag/RAG_GUIDE_FOR_OWNER.md
docs/rag/RAG_PHASE_EXECUTION_PLAN.md
```

---


# 0.1 현재 데이터 위치

Claude Code는 아래 상태를 사실로 보고 시작한다.

| 데이터 | 현재 위치 | 현재 상태 | 구현 중 해야 할 일 |
|---|---|---|---|
| 뉴스·클러스터·요약 | Supabase | 저장되어 있음 | 기존 데이터를 읽어 RAG 인덱싱 |
| DART 원문·구조화 공시 | Supabase | 저장되어 있음 | 기존 데이터를 읽어 RAG 인덱싱 |
| 기존 재무 데이터 | Supabase | 저장되어 있음 | 정확한 숫자 조회에 재사용 |
| 토스증권 API 설정 | 로컬/배포 환경변수 | 키 또는 설정은 있으나 실제 수집 안 함 | Phase 0에서 소량 호출 검증 |
| 토스증권 주가 이력 | 없음 | Supabase에 저장되어 있지 않음 | Phase 6에서 필요 시 조회·계산·캐시 |
| 증권사 리포트 PDF | 로컬 폴더 | 원본만 존재 | Phase 5에서 비공개 Storage 업로드 |
| 리포트 페이지·표·청크 | 없음 | 아직 생성되지 않음 | Phase 5에서 파싱·저장·임베딩 |

주의:

- 주가 데이터를 이미 DB에 저장한 것으로 가정하지 않는다.
- 리포트가 이미 Supabase에 있다고 가정하지 않는다.
- 로컬 PDF 경로를 코드에 하드코딩하지 않는다.
- 리포트 업로드 후 로컬 원본을 자동 삭제하지 않는다.


# 1. 개발 운영 원칙

## 1.1 반드시 지켜야 하는 고정 원칙

아래는 개발 중 임의로 바꾸면 안 된다.

- 정확한 재무·공시 숫자는 LLM이 추측하거나 계산하지 않는다.
- 실제값과 증권사 전망값을 구분한다.
- 정정공시는 최신 정정 내용을 우선한다.
- 뉴스·공시·리포트 출처를 답변과 함께 제공한다.
- 리포트 원본 PDF는 비공개로 저장한다.
- 차트 모양만 보고 정확한 숫자를 추측하지 않는다.
- 기존 뉴스 수집·클러스터링·DART 기능을 깨지 않는다.
- API 키와 비밀정보를 출력하거나 커밋하지 않는다.
- DB를 파괴적으로 변경하기 전에 백업·롤백 방법을 확인한다.
- 임베딩 모델 세대와 차원이 다른 벡터를 같은 인덱스에 섞지 않는다.

## 1.2 개발하면서 바꿀 수 있는 부분

아래는 실제 코드와 실험 결과에 따라 변경할 수 있다.

- 파일과 함수 이름
- 클래스 분리 방법
- Repository와 Service의 세부 구조
- 청크 길이와 overlap
- 검색 후보 개수
- 최종 문맥 개수
- RRF 상수
- 캐시 방식과 만료시간
- PDF 파서 조합
- 일부 DB 컬럼의 이름과 타입
- API 응답의 부가 필드
- 프런트 컴포넌트 구조
- 테스트 구현 방식
- 답변 프롬프트의 세부 문장

단, 기획서와 달라진 경우 반드시 이 문서의 **변경 기록**에 남긴다.

## 1.3 작업을 멈춰야 하는 경우

아래만 즉시 중단하고 사용자에게 확인한다.

- 임베딩 차원이 예상과 달라 현재 DB 설계를 사용할 수 없음
- 기존 데이터가 삭제되거나 손상될 가능성이 있음
- 기존 테이블과 신규 마이그레이션이 충돌함
- 전체 PDF 처리 예상 비용이 프로젝트 한도를 크게 초과함
- 외부 API 또는 라이선스 문제로 원본을 처리할 수 없음
- 실제값과 전망값을 안정적으로 구분할 수 없음
- 출처를 원문과 연결할 수 없음
- 기존 핵심 기능이 회귀 테스트에서 깨짐
- 보안키가 프런트엔드나 저장소에 노출될 위험이 있음

그 외의 작은 문제는 합리적인 방법으로 해결하고 Phase 종료 보고서에 기록한다.

---

# 2. 상태 표시 방법

각 항목은 다음 표시를 사용한다.

```text
[ ] 시작 전
[~] 진행 중
[x] 완료
[!] 변경 또는 주의 필요
[-] 이번 MVP에서 제외
```

Claude Code는 작업하면서 직접 체크박스를 수정한다.

---

# 3. 전체 진행 현황

| Phase | 내용 | 상태 | 승인 |
|---|---|---:|---:|
| 0 | 사전 검증 | [x] | [x] |
| 1 | DB·Storage·기본 Repository | [x] | [x] |
| 2 | 뉴스 기반 최소 RAG | [x] | [x] |
| 3 | 하이브리드 검색 | [x] | [x] |
| 4 | 숫자·용어·혼합 질문 (결정론적 QA 라이브 경로 완료) | [x] | [x] |
| 5 | 증권사 리포트 | [x] 적재+검색+QA 연결 완료 | [ ] |
| 6 | 주가 질문 | [ ] | [ ] |
| 7 | 프런트엔드 연결 | [ ] | [ ] |
| 8 | 평가·튜닝 | [ ] | [ ] |
| 9 | 배포·발표 준비 | [ ] | [ ] |
| Ext A | 공통 read-only Tool 인터페이스 (향후) | [ ] | [ ] |
| Ext B | 제한형 Agentic Orchestrator (향후) | [ ] | [ ] |
| Ext C | MCP 서버 공개 (선택, Tool·Agentic 안정화 후) | [ ] | [ ] |
| Ext D | ~~A2A PoC~~ (이번 프로젝트 범위 제외) | 제외 | — |

> Ext A~B는 Phase 6 이후의 **향후 확장**이며 미구현이다. Agentic·MCP는 아직 완료 기능이 아니다.
> **Ext C(MCP)**는 Tool·Agentic 안정화 이후 일정·시연 가치가 있을 때만 선택적으로 추가한다.
> **Ext D(A2A)**는 이번 프로젝트 범위에서 **제외**하며, 적용하지 않은 이유만 설계 판단으로 기록한다.
> Phase 4 의 결정론적 QA(숫자·용어·혼합)는 2026-07-24 통합으로 **실제 QA API 라이브 경로**가 되었다.

---

# Phase 0. 사전 검증

## 목표

실제 코드·DB·API 환경이 구현 명세와 맞는지 빠르게 확인한다.

이 단계에서는 대량 인덱싱이나 본격 기능 구현을 하지 않는다.

## 작업 체크리스트

- [x] 현재 브랜치와 저장소 상태 확인
- [x] 기존 테스트 실행 결과 기록  (58 passed)
- [x] 현재 FastAPI 진입점 확인  (app.main:app)
- [x] 기존 RAG 관련 파일의 구현 상태 확인  (전부 placeholder)
- [x] 실제 Supabase 테이블·함수·인덱스 확인
- [x] `pgvector` 사용 가능 여부 확인  (미설치, CREATE 권한 O)
- [x] `pg_trgm` 사용 가능 여부 확인  (미설치, CREATE 권한 O)
- [x] Supabase 마이그레이션 권한 확인  (CREATE TABLE 롤백 검증)
- [x] 비공개 Storage 생성 권한 확인  (probe 버킷 생성→삭제)
- [x] Upstage query embedding 실제 호출  (1024)
- [x] Upstage passage embedding 실제 호출  (1024)
- [x] 두 임베딩 출력 차원 확인  (1024 일치)
- [x] 현재 사용할 수 있는 Solar 채팅 모델 확인  (solar-pro3-260323)
- [x] Solar 스트리밍 지원 여부 확인  (지원)
- [x] 대표 PDF 1개 파싱
- [x] 페이지 구분 유지 여부 확인  (form-feed 유지)
- [!] 본문 추출 품질 확인  (한국어 조판 순서 불안정 → Phase5 보강)
- [!] 표 제목·단위·행·열 유지 여부 확인  (단위 O, 행·열 정합 부족 → Phase5)
- [x] 기존 토스증권 연동 코드 위치와 재사용 가능 여부 확인  (app/sources/prices.py)
- [x] 토스증권 키 존재 여부를 값 노출 없이 확인
- [x] 토스증권 API 소량 실제 호출  (005930)
- [x] 현재가·기간 시세·과거 시세 지원 범위 확인  (현재가/일봉/분봉/호가)
- [x] Supabase에 토스 주가 이력이 없음을 확인
- [x] 로컬 리포트 폴더 경로와 PDF 파일 수 확인  (/Users/kimjunwoo/report, 244)
- [x] Supabase에 리포트 원본·페이지·표가 아직 없음을 확인
- [x] 예상 변경 파일 목록 작성  (완료 보고서)
- [x] 예상 비용과 주요 위험 작성  (완료 보고서)

## 유연하게 판단할 부분

- 대표 PDF는 가장 복잡한 파일 한 개를 우선 사용해도 된다.
- PDF 파서 모델명과 호출 방식은 현재 공식 API에 맞게 조정할 수 있다.
- 테스트가 없는 영역은 최소 smoke test로 대체할 수 있다.
- 스키마 조사 결과 명세와 실제 이름이 다르면 실제 코드를 기준으로 한다.

## 최소 통과 조건

- 임베딩 모델과 차원이 확인됨
- DB 마이그레이션 실행이 가능함
- 기존 기능이 기본적으로 실행됨
- PDF에서 페이지와 본문을 연결할 수 있음
- 치명적인 충돌이 없음

## 산출물

```text
backend/docs/rag/phase_0/rag_preflight_report.md
backend/docs/rag/phase_0/PHASE_0_COMPLETION.md
backend/docs/rag/phase_0/precheck_bundle/   (기존 조사 자료 보관)
```
(주: SPEC의 backend/artifacts 경로 대신, 지시에 따라 phase_0 폴더에 저장)

## Phase 종료 기록

```text
상태: 완료
완료일: 2026-07-22
확인한 임베딩 모델: solar-embedding-2-query / solar-embedding-2-passage
확인한 차원: 1024 (query=passage)
사용할 Chat 모델: solar-pro3-260323 (스트리밍 지원)
PDF 파서: 로컬 pdftotext -layout(1차), 표·복잡 PDF는 Phase5에서 Upstage Document Parse 보강
Phase 1 진행 가능 여부: 가능
주요 변경 필요 사항: 임베딩 1024 확정(4096 alias 미사용), 표 복원은 Phase5 파서 보강
```

---

# Phase 1. DB·Storage·기본 Repository

## 목표

RAG 데이터를 안전하게 저장하고 검색할 기반을 만든다.

## 작업 체크리스트

- [x] 마이그레이션 파일 작성  (0012~0015)
- [x] `rag_documents` 생성
- [x] `rag_sections` 생성
- [x] `rag_chunks` 생성  (embedding vector(1024))
- [x] `research_reports` 생성
- [x] `research_report_pages` 생성
- [x] `research_report_tables` 생성
- [x] `rag_terms` 생성
- [x] `rag_ingestion_runs` 생성
- [x] `rag_query_logs` 생성
- [x] `rag_chunks`에 `stock_code` 중복 저장
- [x] `rag_chunks`에 `source_type` 중복 저장
- [x] `rag_chunks`에 `published_at` 중복 저장
- [x] `rag_chunks`에 `value_kind` 중복 저장
- [x] `rag_chunks`에 `is_active` 저장
- [x] 벡터 인덱스 생성  (HNSW cosine)
- [x] 키워드 검색 인덱스 생성  (trgm GIN)
- [x] 자주 사용하는 필터 인덱스 생성  (filter/published/document)
- [x] 비공개 리포트 Storage 생성  (research-reports-private, public=false)
- [x] Storage 접근 정책 확인  (service_role 전용, 정책 0개=익명 차단)
- [x] Repository 구현  (app/repositories/rag.py)
- [x] 문서 버전 비활성화 로직 구현  (실DB 검증)
- [x] 마이그레이션 재실행 안전성 확인  (멱등)
- [x] 롤백 방법 작성  (migrations/rollback/, --rollback)
- [x] 기존 DB 기능 회귀 확인  (58 passed)

## 유연하게 판단할 부분

- 실제 스키마와 코드 스타일에 맞게 테이블·컬럼명을 조금 바꿀 수 있다.
- `rag_sections`를 초기에는 최소 컬럼으로 구현하고 이후 확장할 수 있다.
- query log는 개인정보 위험이 있으면 저장 범위를 축소할 수 있다.
- Repository 파일 분리는 기존 프로젝트 패턴을 우선한다.

## 최소 통과 조건

- 문서·청크·리포트·용어를 저장할 수 있음
- 의미 검색과 키워드 검색용 인덱스가 생성됨
- 원본 PDF가 public으로 노출되지 않음
- 기존 데이터가 변경되지 않음
- 롤백 방법이 존재함

## 산출물

```text
backend/docs/rag/phase_1/PHASE_1_DB_STORAGE.md   (기준 문서)
backend/docs/rag/phase_1/PHASE_1_COMPLETION.md   (완료 보고서)
migrations/0012~0015 + migrations/rollback/*
scripts/apply_rag_migrations.py, scripts/create_rag_storage.py
app/repositories/rag.py
```

## Phase 종료 기록

```text
상태: 완료
완료일: 2026-07-22
생성한 마이그레이션: 0012_rag_core, 0013_research_reports, 0014_rag_hybrid_search, 0015_rag_rls_storage
실제 적용된 테이블: rag_documents, rag_sections, rag_chunks, research_reports,
  research_report_pages, research_report_tables, rag_terms, rag_ingestion_runs, rag_query_logs (9개)
기획서와 달라진 스키마: uuid=gen_random_uuid, rag_chunks denorm 컬럼 확장,
  RLS enable만(정책 없음), Storage 버킷은 API로 생성
롤백 방법: scripts/apply_rag_migrations.py --rollback
남은 위험: denorm 정합성은 Phase2 인덱싱 책임, RLS 정책은 공개 API 시 재검토
```

---

# Phase 2. 뉴스 기반 최소 RAG

## 목표

뉴스 사건 데이터만으로 질문→검색→답변→출처 흐름을 완성한다.

## 작업 체크리스트

- [x] 뉴스 사건 원본 조회 구현
- [x] 뉴스 텍스트 정규화 구현
- [x] 뉴스 사건 청킹 구현
- [x] 대표 기사 전체 본문은 기본 검색에서 제외
- [x] 문서용 passage embedding 구현
- [x] 해시 기반 중복 임베딩 방지  (재실행 100건 skip 확인)
- [x] 뉴스 100건 시험 인덱싱  (indexed 100 / chunks 109 / 실패 0)
- [x] 의미 검색 구현  (rag_search_semantic RPC)
- [x] 현재 뉴스 문맥 우선 검색
- [x] QA 요청 모델 구현
- [x] QA 응답 모델 구현
- [x] Solar 답변 생성 구현
- [x] 스트리밍 구현  (SSE)
- [x] 출처 배열 반환
- [x] 인용 번호 검증  (invalid 0)
- [x] 뉴스 질문 smoke test  (self_in_top_rate 1.0)
- [x] 응답 시간 측정  (검색~0.13s, 생성~3.9s)
- [x] API 비용 측정  (시험 규모 소량)
- [x] 시험 통과 후 전체 활성 뉴스 인덱싱  (2,940 docs / 3,112 chunks, 실패 0, 재실행 복구, 제외 0)
- [x] 신규 사건 증분 인덱싱을 스케줄러(summary/verify 후)에 자동 연결
- [x] 증분 인덱싱: content_hash skip / 예외 격리 / rag_ingestion_runs 기록
- [x] 동시실행 방지: PostgreSQL advisory lock(프로세스·인스턴스 간) + threading.Lock fallback
- [x] 자동 반영·재실행 skip·실패 격리·advisory lock 테스트 추가  (87 passed)
- [x] .DS_Store Git 추적 제거 확인 + backend/.gitignore 재무시 규칙 추가

## 기본 답변 형식

```markdown
## 한 줄 결론

## 쉽게 설명하면

## 자세히 보면

## 핵심 숫자

## 주의할 점
```

규칙:

- 쉬운 설명과 자세한 설명은 같은 근거와 한 번의 모델 호출에서 생성한다.
- 쉬운 설명은 2~4문장 정도로 작성한다.
- 자세한 설명은 근거와 숫자의 성격을 포함한다.
- 관련 숫자가 없는 질문이면 `핵심 숫자`는 생략할 수 있다.
- 주의할 내용이 없으면 `주의할 점`은 짧게 처리하거나 생략할 수 있다.
- 출처 목록은 별도의 `sources` 배열로 반환한다.

## 유연하게 판단할 부분

- 답변 제목은 UI에 맞게 조금 변경할 수 있다.
- 단순 용어 질문처럼 짧은 질문은 일부 구역을 생략할 수 있다.
- 청크 길이와 검색 개수는 실제 결과를 보고 조정할 수 있다.
- 스트리밍 형식은 기존 프런트 구조에 맞출 수 있다.

## 최소 통과 조건

- 현재 뉴스 질문에서 해당 사건이 상위 검색 결과에 포함됨
- 답변에 출처가 표시됨
- 존재하지 않는 인용 번호를 만들지 않음
- 관련 없는 대표 기사 추천 문구가 검색되지 않음
- 사용자가 첫 응답을 빠르게 볼 수 있음

## 산출물

```text
backend/docs/rag/phase_2/PHASE_2_NEWS_RAG.md   (기준 문서)
backend/docs/rag/phase_2/PHASE_2_COMPLETION.md (완료 보고서)
backend/docs/rag/phase_2/trial_100_result.json (100건 시험 결과)
app/rag/{normalization,chunking,indexing,retrieval,prompting}.py
app/ml/{embeddings,generation}.py, app/services/rag_qa.py, app/schemas/qa.py
app/api/routes/qa.py, migrations/0016_rag_search_semantic.sql
scripts/rag_phase2_trial.py, tests/unit/test_rag_phase2.py
```

## Phase 종료 기록

```text
상태: 완료 (100건 검증 + 전체 인덱싱)
완료일: 2026-07-22
시험 인덱싱 건수: 100 (청크 109)
최종 인덱싱 건수: 2,940 docs / 3,112 chunks (활성 2,940 전부, 실패 0, 제외 0)
평균 응답 시간: 검색 ~0.1s + 생성 ~3.9s
첫 토큰 시간: SSE 스트리밍 즉시
비용: 전체 임베딩 ~$0.10 추정(약 107만 토큰). 재실행은 해시 skip으로 0
답변 포맷 변경 사항: 없음(계획서 형식 유지)
남은 문제:
  1) 신규 사건 증분 인덱싱 스케줄러 연결 — 구현 완료 (app/jobs/rag_index_job.py,
     summary/verify 후 자동 호출, content_hash skip, 예외격리, 락, rag_ingestion_runs 기록)
  2) 하이브리드는 Phase 3 (대기)
  (1차 실패 1건=cluster 4748, 임베딩 일시예외 → 개별 재인덱싱 복구, 최종 제외 0)
```

---

# Phase 3. 하이브리드 검색

## 목표

의미 검색과 정확한 키워드 검색을 결합한다.

## 작업 체크리스트

- [x] query embedding 구현
- [x] 의미 검색 후보 조회
- [x] `pg_trgm` 키워드 검색 구현  (word_similarity + ILIKE)
- [x] 제목·본문·종목코드 검색 지원
- [x] 영문 약어·제품명·공시 표현 검색 확인  (HBM/CEO/005930/숫자)
- [x] RRF 순위 결합 구현  (RPC rag_search_hybrid, rrf_k=50)
- [x] 종목 필터
- [x] 날짜 필터
- [x] 출처 종류 필터
- [x] 실제값·전망값 필터  (value_kind 필터, 뉴스엔 미적용이나 RPC 지원)
- [x] 현재 문서 우선 처리  (현재문서 4 + 전체 12)
- [x] 같은 문서 청크 제한  (최대 2)
- [x] 같은 뉴스 사건 중복 제거  (사건당 최대 2)
- [x] 동일 내용 해시 중복 제거  (content_hash)
- [x] 부모 문맥 확장  (앞뒤 청크 배경)
- [x] 문맥 길이 제한  (char budget 12000)
- [x] 의미 검색 단독과 하이브리드 비교  (recall/MRR, scripts/rag_phase3_eval.py)
- [x] 검색 시간 측정  (semantic ~134ms / hybrid ~635ms)

## 유연하게 판단할 부분

- 후보 개수 24는 고정값이 아니다.
- RRF 상수 50은 실험 후 변경할 수 있다.
- 문서당 최대 청크 2개도 질문 유형에 따라 조정할 수 있다.
- 부모 문맥을 section 전체로 가져올지 앞뒤 청크만 가져올지 결과를 보고 선택한다.
- 한국어 키워드 검색이 부족하면 범위가 작은 보완 방식을 제안할 수 있다.

## 최소 통과 조건

- 정확 명칭 질문이 의미 검색 단독보다 나아짐
- 쉬운 표현 질문도 기존 수준 이상 유지
- 중복 자료가 최종 문맥을 독점하지 않음
- 현재 문서 질문이 다른 문서로 과도하게 튀지 않음

## 산출물

```text
backend/docs/rag/phase_3/PHASE_3_HYBRID_SEARCH.md  (기준 문서)
backend/docs/rag/phase_3/PHASE_3_COMPLETION.md      (완료 보고서)
backend/docs/rag/phase_3/eval_result.json + holdout_result.json (비교 평가/홀드아웃)
migrations/0017_rag_hybrid_rrf.sql + 0018_rag_hybrid_lexical_exact_first.sql (+rollback)
app/rag/retrieval.py(HybridRetriever), app/rag/fusion.py
scripts/rag_phase3_eval.py, tests/unit/test_hybrid_fusion.py, test_source_dedup.py
```

## Phase 종료 기록

```text
상태: 완료
완료일: 2026-07-22
semantic 후보 수: 24
lexical 후보 수: 24
RRF 설정: rrf_k=50, semantic_weight=lexical_weight=1.0
최종 문맥 수: 8 (문서·사건당 최대 2)
개선된 질문 사례: 정확명칭 recall@8 최신 0.25→0.92 / 홀드아웃 0.65→0.94 (숫자·RFI·CEO 등 회수)
악화된 질문 사례: SDV(1→5), ASML EUV(1→2) — top-8 유지(recall 손실 없음)
기획서와 달라진 점: 키워드=word_similarity+ILIKE, lexical 정확일치 우선, 부모문맥=앞뒤 청크, fusion.py, 평가토큰 일반화(종목명 제외+DF임계)
하드코딩 여부: 없음. 홀드아웃(offset 200)에서 재현 확인 → 과적합 아님
```

---

# Phase 4. 숫자·용어·혼합 질문

## 목표

정확한 숫자와 설명을 서로 다른 데이터 경로에서 가져와 하나의 답변으로 합친다.

## 작업 체크리스트

- [x] QueryPlan 구현  (app/rag/query_plan.py, 규칙 기반)
- [x] 한 질문에서 복수 작업 선택 지원  (혼합 시 복수 플래그)
- [x] 기존 재무 테이블 어댑터 구현  (facts.py, 읽기 전용)
- [x] 기존 구조화 공시 어댑터 구현  (get_structured_values)
- [x] 최신 정정공시 우선 처리  (is_latest=true, 정정 페어)
- [x] 금융 용어 파싱 또는 import  (한국은행 800선 789개 적재 + 시드 6, 총 795)
- [x] 용어 정확 일치
- [x] 용어 별칭 일치  (순이익→당기순이익 확인)
- [x] 용어 유사 검색  (search_text 부분일치)
- [x] 숫자 조회와 문서 검색 병렬 실행  (ThreadPoolExecutor)
- [x] 실제값·공식값·전망값 라벨 적용  (value_kind)
- [x] 숫자 단위 보존  (원 단위 정수, 표시만 조/억 변환)
- [x] 숫자 출처와 설명 출처 분리  (numeric_sources vs sources)
- [x] 혼합 질문 테스트
- [x] 근거 부족 응답 테스트  (없는 회사 → 확인 불가)

## 필수 시험 질문

- [x] "영업이익이 얼마야?"  (57.23조원, 실제 실적/연결)
- [x] "영업이익이 얼마고 왜 늘었어?"  (숫자 SQL + 설명 RAG 병렬)
- [x] "ADR이 뭐야?"  (term=ADR 시드 조회)
- [x] "정정 전과 정정 후 뭐가 바뀌었어?"  (최신 정정본 기준)
- [x] "이 공시가 왜 중요해?"  (관련 공시 설명, 출처 8)

## 유연하게 판단할 부분

- 첫 버전의 QueryPlan은 규칙 기반으로 구현해도 된다.
- 규칙이 복잡해지면 작은 LLM 분류를 추가 제안할 수 있다.
- 모든 재무 항목을 한 번에 지원하지 않고 자주 묻는 항목부터 구현할 수 있다.
- 용어 별칭은 평가 중 발견되는 항목을 추가할 수 있다.

## 최소 통과 조건

- 정확한 숫자를 문서 검색 결과에서 임의 선택하지 않음
- 혼합 질문이 숫자 조회와 설명 검색을 모두 사용함
- 전망값을 실제값처럼 표현하지 않음
- 정정 전 값을 최신값처럼 답하지 않음

## 산출물

```text
backend/docs/rag/phase_4/DATA_SURVEY.md          (사전 데이터 조사)
backend/docs/rag/phase_4/PHASE_4_NUMERIC_TERMS.md (기준 문서)
backend/docs/rag/phase_4/PHASE_4_COMPLETION.md    (완료 보고서)
backend/docs/rag/phase_4/trial_result.json        (필수 질문 검증)
app/rag/query_plan.py, app/services/facts.py, app/services/rag_qa_facts.py
app/rag/prompting.py(facts/term 블록), scripts/seed_rag_terms.py, scripts/rag_phase4_trial.py
tests/unit/test_query_plan.py, test_facts_format.py
```

## Phase 종료 기록

```text
상태: 완료
완료일: 2026-07-22
지원하는 숫자 항목: 매출액·영업이익·당기순이익·자산/부채/자본총계·영업/투자/재무활동현금흐름 (연결, 원 단위)
지원하는 공시 유형: 정기보고서·주요사항(구조화 값+요약), 정정공시 최신본, 일정성 이벤트
등록된 용어 수: 795 (한국은행 경제금융용어 800선 789 canonical entry + 시드 6)
용어 적재: 0019 컬럼확장 + load_bok_terms.py, 789 임베딩(solar-embedding-2, ~$0.016), 재실행 skip
혼합 질문 결과: 숫자 SQL + 설명 RAG 병렬 사용, 인용 오류 0, 필수 질문 5개 통과
기획서와 달라진 점: PyMuPDF 좌표+목차 기반 파서, related_terms 컬럼 추가, 조사 접미사 제거, account 신호어 매핑
남은 지원 범위: 별도재무·2023 이전·주가(Phase6) 미지원, 단독 숫자질문 기간 표기 튜닝
기존 데이터: DART·재무·공시 전부 읽기 전용(SELECT, 무변경). 신규 쓰기는 rag_terms(795)뿐
```

### 변경 기록 — 결정론적 QA 라이브 경로 (Phase 5 선결 작업, 2026-07-24)

```text
발견: Phase 4 의 QueryPlan/FactsQaService(숫자·용어·혼합 결정론적 경로)는
      구현·테스트만 되고 실제 QA API(qa.py)에는 미연결이었다.
      라이브 /qa 는 RagQaService(뉴스 하이브리드 검색 전용)만 서빙하고 있었다.
조치: qa.py 단일 진입점을 FactsQaService 로 전환(진입점 하나 유지).
      QueryPlan 판정으로 순수 뉴스→기존 검색 재사용, 숫자→SQL, 용어→lookup,
      혼합→결합. FactsQaService.stream() 추가(생성만 스트리밍).
      QaResponse 에 numeric_sources·term 선택 필드 추가(기존 필드 유지, 비파괴).
      RagQaService 는 삭제하지 않고 유지(validate_citations 및 참조 보존).
검증: 전체 136 테스트 통과(신규 통합 7개 포함), ruff·format 통과.
결과: 결정론적 QA 라이브 경로 완료. Agentic·Tool Registry·MCP·A2A 는 미구현(범위 밖).

후속 수정(2026-07-24): QueryPlan need_documents 규칙을 의도 신호 기반으로 정정.
  이전에는 need_financials 이면 문서 검색을 항상 켜서 순수 숫자 질문도 뉴스 검색을
  유발했다. 이제 설명/정정 신호가 있거나(켬), 사실 신호(숫자/용어)가 없는 자연어
  질문일 때만 문서 검색을 켠다. 순수 숫자→SQL만, 순수 용어→용어만(뉴스 검색·임베딩
  호출 없음). 질문 문장 하드코딩 없이 신호 조합으로만 판정. 전체 143 테스트 통과.
한국은행 자료 이용범위: 공개·상용 출시 전 확인 필요(개방 라이선스 미명시), 원본 PDF는 Git 제외
```

---

# Phase 5. 증권사 리포트

## 목표

리포트의 본문과 표를 검색하고 정확한 페이지 출처를 제공한다.

## 작업 체크리스트

- [ ] 로컬 리포트 입력 폴더를 환경변수 또는 CLI 인자로 받기
- [ ] 로컬 PDF 파일 목록과 대상 종목 확인
- [ ] PDF 파일 해시 계산
- [ ] 비공개 Storage 업로드
- [ ] 중복 업로드 방지
- [ ] 대표 PDF 10개 파싱
- [ ] 페이지별 텍스트 저장
- [ ] 페이지별 구조 요소 저장
- [ ] 반복 머리말·꼬리말 제거
- [ ] Compliance Notice 제외
- [ ] 첫 페이지 핵심 메타데이터 추출
- [ ] 투자의견 추출
- [ ] 목표주가 추출
- [ ] 기준주가 추출
- [ ] 본문 소제목 구조 복원
- [ ] 본문 청킹
- [ ] 표 제목 추출
- [ ] 표 단위 추출
- [ ] 표 행·열 저장
- [ ] A/E/F 실제·전망 구분
- [ ] 표 조회 Repository 구현
- [ ] 페이지 출처 연결
- [ ] 차트 숫자 추측 방지
- [ ] 실패 PDF 목록 저장
- [ ] 실제 처리 비용 측정
- [ ] 전체 예상 비용 계산
- [ ] 대표 10개 결과 보고
- [ ] 승인 후 전체 PDF 처리

## 유연하게 판단할 부분

- 텍스트형 PDF는 로컬 파서로 처리할 수 있다.
- 표·OCR이 필요한 PDF만 Upstage를 사용할 수 있다.
- 목표주가 추출 실패는 null로 저장하고 검수 대상으로 보낼 수 있다.
- 표 복원이 불안정하면 본문 검색만 활성화할 수 있다.
- 모든 차트를 MVP에 넣을 필요는 없다.
- PDF 244개 전체 처리보다 발표 대상 종목의 최신 문서를 우선할 수 있다.

## 최소 통과 조건

- 리포트 제목·증권사·날짜·페이지를 연결할 수 있음
- 실제값과 전망값을 구분할 수 있음
- 표의 단위를 잃지 않음
- 파싱이 불확실한 숫자를 확정값처럼 답하지 않음
- 비용이 프로젝트 한도 안에 있음

## Phase 종료 기록

```text
상태: 적재 완료(QA 연결·리포트 검색 연결은 미진행 — 지시에 따름)
완료일: 2026-07-24
시험 PDF 수: 14(2단계 대표) + 6(파서 회귀)
전체 처리 PDF 수: 244 (success 243 / partial 1 / failed 0, 오류 0)
사용한 파서: app/rag/report_parser.py(PyMuPDF 좌표+find_tables, 로컬 파서. OCR 미사용)
적재 결과: research_reports 244, pages 1877, tables 1937,
  rag_documents(report) 244, rag_chunks(report) 4351
표 value_kind(DB): unknown 547 / forecast 254 / mixed 187 / actual 12
투자의견 추출: 1p 규칙 추출(목표주가 numeric 추출은 후속 검수 대상)
OCR 대상 수: 0 (partial 1건은 스캔형이나 OCR 미적용, 발표/검색 제외 후보)
실제 임베딩 비용: ~$0.22 (본문 청크 4351, solar-embedding-2-passage)
재실행 skip: content_hash 동일 시 재임베딩 0 (3건 재실행 검증)
사람이 확인할 항목: 목표주가 numeric 파싱, 키움류 표 소수점 토큰(값 손실 0),
  partial 1건 발표 제외 여부
```

### 변경 기록 — 파서 규칙 확정 + 적재 (2026-07-24)

```text
키움 병합셀 재정렬(_resplit_merged)·소수점/콤마 정규화(normalize_cell) 일반 규칙 추가.
원문 대조는 콤마·공백 무시 비교로 정정. 값 손실 0 확인(재정렬이 값 보존).
A/E/F 토큰 단위 value_kind 합계 = aef_value_total 일치 확인(정의상 일치).
표 단위 value_kind 는 DB CHECK(actual/forecast/mixed/unknown)에 맞춰 매핑
  (열별 estimate/guidance 세부는 metadata·col 분류로 보존, 표 단위는 mixed/forecast 로 집계).
파서 app/rag/report_parser.py 로 재사용화. 적재 scripts/load_research_reports.py
  (Storage 업로드 + reports/pages/tables + 본문 임베딩, file_hash 멱등·재시작·재실행 skip).
QA 연결·Agentic·MCP 미진행(지시).
```

### 검증 기록 — QA 연결 전 확인 (2026-07-24)

```text
1) partial 리포트 1건: reports/pages/tables 에는 저장하되 본문 임베딩·검색에서 제외.
   최초 적재 시 차트 축 텍스트 조각 1청크가 임베딩됐던 것을 발견 → 해당 문서/청크를
   is_active=false·is_current=false 로 비활성화(활성 report 청크 4351→4350).
   재발 방지: 적재 스크립트가 parse_status='success' 인 리포트만 본문 임베딩하도록 수정.
2) report rag_chunks NULL embedding = 0.
3) Storage 객체 = 244 (research-reports-private, 모든 stock_code 폴더 합).
4) research_report_tables 총 count = 1937. "1000" 은 PostgREST 기본 조회 limit 때문에
   select() 가 1000행만 반환한 것(데이터 차이 아님). range 로 전량 집계 시
   unknown 1112 / forecast 469 / mixed 344 / actual 12 = 합 1937 로 일치.

A/E/F 6063 과 표 단위 value_kind 집계의 기준 차이:
- aef_value_total(6063) = 본문+표 텍스트에서 A/E/F '토큰 출현 횟수'(2025A·2026E·2027F …
  개별 등장 수). 한 표의 한 열에 같은 A/E/F 가 여러 행에서 반복 출현하므로 수가 크다.
- research_report_tables.value_kind(합 1937) = '표 1개당 1건'의 표 단위 분류
  (열들의 kind 를 actual/forecast/mixed/unknown 으로 요약). 집계 대상 단위가 다르다
  (토큰 vs 표). 따라서 두 수는 정의상 일치할 수 없으며 비교 대상이 아니다.
- 토큰 단위 value_kind 합(actual/estimate/forecast) 은 aef_value_total 과 일치함을
  파서 회귀(phase5_verify_parser.py)에서 별도 확인.
```

### 완료 기록 — 검색·QA 연결 (2026-07-24)

```text
search_research_reports(app/services/research_reports.py): HybridRetriever 재사용
  (source_type=research_report). RPC 가 is_active·is_current 강제 → partial·NULL emb 제외.
  stock_code·발행일 필터(RPC), 증권사 필터(후처리). 제목·증권사·발행일·투자의견·
  page_number·pdf_page·source_page·표 value_kind 반환. 전망값을 실적으로 표현 안 함.
검색 품질: 5개 유형(정확명칭·자연어·전망·목표주가·실적원인) Recall@8=100%(25/25),
  타종목 혼입 0, 출처페이지 유효 40/40.
QA 연결: QueryPlan need_reports 추가(report intent 독립 판정). FactsQaService 병렬
  조회에 리포트 추가. QaResponse.report_sources 비파괴 확장. 세 의도(financial/news/
  report) 독립 판정으로 과호출 제거('목표주가' 만으로 SQL·뉴스 자동 안 켜짐).
QA 응답 계약: 비파괴(선택 필드만 추가). Agentic·Tool Registry·MCP 미진행.
```

---

# Phase 6. 주가 질문

## 목표

기존 시장 데이터 연동을 이용해 현재가와 사건 전후 가격 변화를 정확히 계산한다.

## 작업 체크리스트

- [ ] Supabase에 기존 주가 이력이 없다는 전제 확인
- [ ] 기존 토스증권 연동 코드 확인
- [ ] 토스증권 API 실제 지원 범위 확인
- [ ] 현재가 조회
- [ ] 전일 대비 계산
- [ ] 특정 기간 수익률 계산
- [ ] 사건 전후 1거래일 계산
- [ ] 사건 전후 3거래일 계산
- [ ] 사건 전후 5거래일 계산
- [ ] 거래량 변화 계산
- [ ] 휴장일 처리
- [ ] 데이터 누락 처리
- [ ] 가격 캐시
- [ ] 계산값 structured fact로 전달
- [ ] 인과관계 단정 방지
- [ ] API 응답 시간 측정

## 유연하게 판단할 부분

- 기존 API가 기간 시세를 제공하지 않으면 지원 범위를 줄일 수 있다.
- 1·3·5거래일 중 실제 발표 UI에 필요한 구간부터 구현할 수 있다.
- 가격 데이터 소스의 제약은 종료 보고서에 명시한다.
- 주가 질문을 별도 API로 분리할 수 있다.

## 최소 통과 조건

- 수익률은 백엔드 코드가 계산함
- 거래일 기준으로 계산함
- 데이터가 없으면 추측하지 않음
- 뉴스와 주가의 인과관계를 확정적으로 말하지 않음

## Phase 종료 기록

```text
상태:
완료일:
지원하는 가격 질문:
사용 데이터 소스:
평균 조회 시간:
캐시:
제약 사항:
```

---

# Extension A~C. Tool·Agentic·MCP 확장 (향후 계획) / A2A 제외

> **주의**: Extension A~C는 Phase 5(리포트 RAG)와 Phase 6(주가)이 완료된 뒤 진행하는
> **향후 계획**이다. 아직 미구현이며, 현재 시스템은 LangChain·LangGraph 없이 직접 구현한
> **결정론적 하이브리드 RAG**다. Extension은 기존 결정론적 경로를 대체하지 않고 감싸며,
> 단순 질문은 계속 기존 라우터로 처리한다. 기존 Phase 0~7 번호는 그대로 유지한다.
> **A2A(Extension D)는 이번 프로젝트 범위에서 제외한다** — 아래 "Extension D" 절에 사유만 기록한다.

## Extension A. 공통 읽기 전용 Tool 인터페이스

### 목표
기존 서비스(FactsService, 하이브리드 검색, 용어 조회, Phase 5 리포트, Phase 6 주가)를
동일한 read-only Tool 시그니처로 추상화해 라우터와 (향후) Agent가 공유하게 한다.

### 작업 체크리스트
- [ ] Tool 인터페이스(입력 스키마·출력 스키마·부작용 없음) 정의
- [ ] 기존 서비스들을 Tool Registry에 등록(쓰기 없는 조회만 노출)
- [ ] 기존 결정론적 라우터가 Registry를 통해 동일 Tool 호출하도록 전환
- [ ] Tool 호출 로깅(선택 Tool·지연·결과 크기)
- [ ] 회귀: 기존 답변 품질·지연 변화 없음 확인

### 최소 통과 조건
- 모든 Tool이 읽기 전용
- 기존 라우터 동작·결과가 이전과 동일(회귀 없음)

## Extension B. 제한형 Agentic Orchestrator

### 목표
복합·다단계 질문에만 제한적으로 Agent를 적용하고, 단순 질문은 기존 라우터를 유지한다.

### 작업 체크리스트
- [ ] 복합 질문 판별 기준 정의(다단계·비교·다중 종목 등)
- [ ] Agent는 Extension A의 read-only Tool만 사용
- [ ] 최대 Tool 호출 횟수 상한
- [ ] 실행 시간 상한
- [ ] 실패·시간 초과 시 기존 결정론적 라우터로 fallback
- [ ] 단순 질문은 Agent를 거치지 않음(라우터 직결)
- [ ] Agent 경로 on/off 플래그
- [ ] 반복·불필요 호출 방지 로깅

### 최소 통과 조건
- 단순 질문은 기존 라우터로만 처리됨
- Agent 실패·초과 시 fallback으로 답변 보장
- 플래그로 즉시 비활성화 가능

## Extension C. MCP 서버 공개 (선택)

### 목표
Extension A의 동일 Tool을 MCP 서버로 노출해 외부·다른 런타임에서 재사용 가능하게 한다.
**Tool·Agentic이 안정화되고 일정·시연 가치가 확인될 때만** 선택적으로 진행한다.
Agentic보다 먼저 구현하지 않는다.

### 작업 체크리스트
- [ ] MCP 서버로 노출할 핵심 Tool 3개 확정(예: search_news·get_financial_facts·search_research_reports, read-only만)
- [ ] 내부 함수 호출과 MCP 노출이 같은 Tool 정의를 공유
- [ ] 인증·접근 범위 정의
- [ ] MCP on/off 및 장애 시 내부 경로 유지 확인

### 최소 통과 조건
- MCP가 꺼져도 내부 RAG는 정상 동작
- 노출 Tool이 전부 읽기 전용

## Extension D. A2A — 이번 프로젝트 범위에서 제외

**구현하지 않는다.** 구현 계획에도 넣지 않으며, 적용하지 않은 이유만 설계 판단으로 기록한다.

### 제외 사유
- 현재 서비스는 하나의 FastAPI 애플리케이션 안에서 뉴스·공시·재무·용어·리포트·주가를
  처리한다. 이를 억지로 독립 Agent로 나누면 배포 복잡도·Agent 간 통신 오류·응답 지연이
  늘고, 실제 서비스 품질보다 기술 이름을 넣기 위한 구현이 된다.
- 하나의 백엔드 안에서 공통 read-only Tool을 안전하게 호출하는 구조(Ext A~B)가 더 단순하고
  안정적이며, 짧은 일정 안에서 검증·평가하기에도 적합하다.
- 따라서 독립 Agent 간 작업 위임을 위한 A2A는 현재 프로젝트의 핵심 문제를 해결하지 않는다.

### 발표 표현
> A2A는 독립 Agent 간 작업 위임이 필요한 구조에서 의미가 있지만, 현재 서비스는 하나의
> 백엔드 안에서 공통 Tool을 안전하게 호출하는 구조가 더 적합하다고 판단해 적용하지 않았습니다.

## Extension 종료 기록

```text
Extension A 상태:
Extension B 상태:
Extension C 상태(선택):
Extension D(A2A) 상태: 제외(범위 밖). 사유는 위 "Extension D" 절에 기록.
비고(미진행 결정 포함):
```

---

# Phase 7. 프런트엔드 연결

## 목표

현재 UI 안에서 RAG를 자연스럽게 사용할 수 있게 한다.

## 작업 체크리스트

- [ ] QA API 클라이언트
- [ ] SSE 스트리밍 훅
- [ ] 뉴스 모달 AI 패널 연결
- [ ] 뉴스 `sourceId` 전달
- [ ] 종목 코드 전달
- [ ] 공시 질문 연결
- [ ] 리포트 질문 연결
- [ ] 리포트 페이지 context 전달
- [ ] 전역 질문 화면 연결
- [ ] Markdown 답변 렌더링
- [ ] 쉬운 설명 영역 표시
- [ ] 자세한 설명 영역 표시
- [ ] 핵심 숫자 표시
- [ ] 주의할 점 표시
- [ ] 출처 카드 표시
- [ ] 출처 번호 클릭 상호작용
- [ ] 로딩 상태
- [ ] 스트리밍 중단 처리
- [ ] 오류와 재시도
- [ ] 모바일 화면 확인
- [ ] 기존 UI 회귀 확인

## 유연하게 판단할 부분

- 쉬운 설명과 자세한 설명을 탭으로 보여줄 수 있다.
- 한 화면에 연속으로 보여줄 수도 있다.
- 핵심 숫자는 카드 UI로 분리할 수 있다.
- 출처는 아래 목록 또는 우측 패널로 표시할 수 있다.
- 기존 디자인 시스템을 우선한다.

## 최소 통과 조건

- 현재 문서 context가 백엔드로 전달됨
- 답변이 스트리밍됨
- 쉬운 설명과 자세한 설명을 사용자가 구분할 수 있음
- 출처를 확인할 수 있음
- 기존 화면을 크게 망가뜨리지 않음

## Phase 종료 기록

```text
상태:
완료일:
연결한 화면:
답변 표시 방식:
출처 표시 방식:
모바일 결과:
기획서와 달라진 UI:
남은 UX 문제:
```

---

# Phase 8. 평가·튜닝

## 목표

완벽한 연구 평가가 아니라, 발표에서 신뢰할 수 있는 수준인지 확인한다.

## 작업 체크리스트

- [ ] 평가 질문 50개 작성
- [ ] 숫자 질문 포함
- [ ] 용어 질문 포함
- [ ] 뉴스 문맥 질문 포함
- [ ] 공시 질문 포함
- [ ] 리포트 질문 포함
- [ ] 혼합 질문 포함
- [ ] 근거가 없는 질문 포함
- [ ] 의미 검색 단독 결과 기록
- [ ] 하이브리드 결과 기록
- [ ] 검색 top 5 근거 포함 여부
- [ ] 숫자 정확성
- [ ] 실제·전망 혼동
- [ ] 정정공시 최신값
- [ ] 인용 번호 검증
- [ ] 응답 시간
- [ ] 비용
- [ ] 치명적 오류 수정
- [ ] 발표용 대표 질문 선정

## 유연하게 판단할 부분

- 모든 기준을 수치 100%로 맞출 필요는 없다.
- 발표용 프로젝트이므로 치명적 오류를 우선 수정한다.
- 검색 결과가 조금 다르더라도 답변 근거가 정확하면 허용할 수 있다.
- 평가 질문은 실제 UI 사용 사례에 맞춰 바꿀 수 있다.
- 재정렬 모델은 개선 효과가 명확할 때만 추가한다.

## 반드시 0건이어야 하는 오류

- 정정 전 값을 최신값으로 답함
- 증권사 예상값을 확정 실적으로 표현함
- 존재하지 않는 출처 번호 사용
- 차트에서 없는 숫자를 만들어냄
- 매수·매도 직접 추천
- 비공개 키 또는 원본 파일 노출

## Phase 종료 기록

```text
상태:
완료일:
평가 질문 수:
검색 결과:
숫자 정확도:
치명적 오류:
평균 응답 시간:
누적 예상 비용:
발표 가능 여부:
남은 한계:
```

---

# Phase 9. 배포·발표 준비

## 목표

발표 환경에서 안정적으로 동작하게 한다.

## 작업 체크리스트

- [ ] 최종 환경변수 목록 확인
- [ ] 비밀키 Git 미포함 확인
- [ ] 배포 환경에 Upstage 키 설정
- [ ] 배포 환경에 Supabase 키 설정
- [ ] 시장 데이터 키 확인
- [ ] 마이그레이션 적용 상태 확인
- [ ] 전체 인덱싱 완료 확인
- [ ] 실패 문서 목록 확인
- [ ] Docker 빌드
- [ ] 백엔드 배포
- [ ] 프런트 배포
- [ ] CORS 확인
- [ ] 스트리밍 프록시 확인
- [ ] 실제 배포 URL smoke test
- [ ] 발표용 질문 10개 리허설
- [ ] 장애 시 대체 화면 또는 녹화 준비
- [ ] 최종 비용 확인
- [ ] 알려진 한계 문서화

## 유연하게 판단할 부분

- 발표 안정성을 위해 일부 기능을 숨길 수 있다.
- 처리 실패한 오래된 리포트는 발표 대상에서 제외할 수 있다.
- 성능이 느린 고급 질문은 베타 표시할 수 있다.
- 실제 배포에서 스트리밍 문제가 있으면 일반 응답 방식으로 임시 전환할 수 있다.

## 최소 통과 조건

- 발표용 핵심 질문이 정상 작동
- 비밀정보가 노출되지 않음
- 출처가 표시됨
- 치명적인 숫자 오류가 없음
- 장애 대응 방법이 있음

## Phase 종료 기록

```text
상태:
완료일:
배포 주소:
최종 지원 기능:
제외한 기능:
발표용 질문:
알려진 한계:
장애 대응:
```

---

# 4. 변경 기록

기획서와 구현이 달라질 때 아래 표를 추가한다.

| 날짜 | Phase | 원래 계획 | 실제 구현 | 변경 이유 | 영향 | 사용자 결정 필요 |
|---|---|---|---|---|---|---|
| 2026-07-22 | 0 | 임베딩 4096(구 alias) | solar-embedding-2 1024 | 구 alias 2026-08-31 종료 | 인덱스 차원 1024 확정, BGE-M3와 혼용 금지 | 아니오 |
| 2026-07-22 | 0 | 산출물 backend/artifacts/ | backend/docs/rag/phase_0/ | 사용자 지시 | 경로만 변경 | 아니오 |
| 2026-07-22 | 5(선반영) | 로컬 파서로 표/본문 복원 | 로컬 pdftotext는 페이지/단위만, 표·본문은 Upstage 보강 예정 | 한국어 조판 순서 불안정 | Phase5 파서 조합 확정 필요 | 아니오 |
| 2026-07-22 | 1 | uuid=extensions.uuid_generate_v4() | gen_random_uuid() | 스키마접두어 불필요·이식성 | 기능 동일 | 아니오 |
| 2026-07-22 | 1 | rag_chunks denorm은 선택 | stock_code/source_type/published_at/value_kind 저장 | 계획서 체크리스트·필터 성능 | 인덱싱이 정합성 유지 | 아니오 |
| 2026-07-22 | 1 | RLS 정책 부여 | enable만(정책 없음, 기존 관례) | service_role 우회 아키텍처 | 익명 차단, 공개 API 시 재검토 | 아니오 |
| 2026-07-22 | 1 | Storage를 SQL로 | create_rag_storage.py(API) | 버킷은 DDL 대상 아님 | 0015는 RLS만 | 아니오 |
| 2026-07-22 | 2 | (검색 방식 미명시) | 의미검색 RPC rag_search_semantic 추가(0016) | PostgREST로 pgvector 연산 곤란 | Phase3 하이브리드 기반 | 아니오 |
| 2026-07-22 | 2 | 문서 중복 판단 | content_hash=청크 결합 해시 | 사건 내용 변경 시만 재임베딩 | 비용 절감 | 아니오 |
| 2026-07-22 | (운영) | 클러스터링 시 즉시 요약 | NEWS_SUMMARY_ENABLED=false 기본, 요약 지연+날짜별 수동 요약(summarize_v2.py) | 서비스 미운영 중 요약 LLM 비용 절감 | 스케줄러 요약 호출 0, 나중에 원하는 날짜부터 요약 | 예(사용자 요청) |
| 2026-07-22 | 2 | RAG 인덱싱 수동 실행 | 스케줄러 summary/verify 후 증분 인덱싱 자동 연결(app/jobs/rag_index_job.py) | 신규 사건 자동 반영 | content_hash skip·예외격리·락·ingestion_runs 기록 | 예(사용자 요청) |
| 2026-07-22 | 2 | 동시실행 방지=threading.Lock | PostgreSQL advisory lock(psycopg 런타임 추가) + threading fallback | 배포 시 단일 프로세스 미보장(멀티워커/인스턴스 가능) | 프로세스·인스턴스 간 중복 인덱싱 방지 | 예(사용자 요청) |
| 2026-07-22 | 3 | 키워드=전체 similarity(%) | word_similarity(<%) + ILIKE 부분일치 | 긴 문서·짧은 쿼리에서 %가 threshold 미달로 매칭 0 | 정확명칭/약어 회수 개선 | 아니오 |
| 2026-07-22 | 3 | 부모문맥=section 범위 | 뉴스엔 section 없어 앞뒤 청크(±1)로 확장 | 뉴스 사건 구조상 | 배경 문맥 추가, 인용은 핵심 청크 기준 | 아니오 |
| 2026-07-22 | 3 | lexical=word_similarity 단일 | 정확 부분일치(ILIKE) 우선 → word_similarity 2단계 | 완전일치가 근사유사와 뒤섞여 밀림 | 정확명칭 recall 대폭↑(전체 공통 규칙, 하드코딩 없음) | 아니오 |
| 2026-07-22 | 3 | (개선을 0017 파일 수정) | 0018 신규 마이그레이션에서 CREATE OR REPLACE로 분리 | 0017이 DB에 이미 적용된 이력 보존 | 이력 무수정, 롤백 시 0017로 복원 | 아니오 |
| 2026-07-22 | 3 | 평가 정확명칭=제목 토큰 | 종목명 조각 제외 + 코퍼스 DF 임계로 변별력 토큰만 | 초빈도 조각(SK/AI)은 정확명칭 아님 | 공정 평가, 홀드아웃 재현 | 아니오 |
| 2026-07-22 | 4 | 금융용어 외부 사전 import | 소량 시드 6개(rag_terms 데이터) | 소량 검증 우선, 사전 파일 부재 | 추후 한국은행 사전 등 확장 | 아니오 |
| 2026-07-22 | 4 | (용어 후보 추출 미정) | 한국어 조사 접미사 제거 규칙 | 'ADR이'처럼 조사가 붙음 | 일반 규칙(특정 용어 하드코딩 아님) | 아니오 |
| 2026-07-22 | 4 | 용어 시드 6개만 | 한국은행 800선 789개 전체 적재(0019 컬럼확장) | 사용자 승인 후 전체 적재 | rag_terms 795, 임베딩 789 | 예(사용자 요청) |
| 2026-07-22 | 4 | 파서 미정 | PyMuPDF 좌표+폰트+목차 기반 파서 | 2단 컬럼·수식·그래프 정확 파싱 | scripts/parse_bok_terms.py, 원본 PDF Git 제외 | 아니오 |

## 변경 판단 기준

### 사용자 확인 없이 변경 가능

- 파일 구조 정리
- 함수·클래스 이름 변경
- 테스트 방식 변경
- 작은 성능 최적화
- 후보 개수·캐시 시간 조정
- 실제 코드 스타일에 맞춘 타입 변경
- UI 내부 컴포넌트 분리

### 반드시 사용자 확인

- 지원 데이터 종류 삭제
- 하이브리드 검색을 다른 방식으로 대체
- 실제값·전망값 구분 정책 변경
- 리포트 원본 공개 범위 변경
- 외부 유료 서비스 추가
- 예상 비용이 크게 증가
- 답변 포맷 대폭 변경
- 기존 DB 테이블 변경 또는 삭제
- 발표 핵심 기능 제외

---

# 5. Phase 종료 보고 템플릿

Claude Code는 매 Phase 종료 시 아래 형식으로 보고한다.

```markdown
# Phase N 완료 보고

## 완료한 작업
- ...

## 수정한 파일
- ...

## DB 변경
- ...

## 테스트 결과
- ...

## 실제 응답 시간과 비용
- ...

## 기획서와 달라진 점
- 변경 없음
또는
- 원래:
- 실제:
- 이유:
- 영향:

## 아직 남은 문제
- ...

## 사용자 확인이 필요한 것
- 없음
또는
- ...

## 다음 Phase 진행 가능 여부
- 가능 / 조건부 가능 / 불가능
```

---

# 6. Claude Code에 처음 전달할 명령

```text
docs/rag/RAG_IMPLEMENTATION_SPEC.md,
docs/rag/RAG_GUIDE_FOR_OWNER.md,
docs/rag/RAG_PHASE_EXECUTION_PLAN.md를 전체 읽어라.

RAG_PHASE_EXECUTION_PLAN.md를 실제 진행 체크리스트로 사용하고,
작업하면서 체크박스와 Phase 종료 기록을 직접 갱신해라.

현재는 Phase 0만 진행해라.

사소한 구현 선택은 합리적으로 판단해서 진행하고
작업을 불필요하게 멈추지 마라.

단, 고정 원칙을 바꾸거나 데이터 손상·비용 초과·보안 위험이
발생할 가능성이 있으면 중단하고 보고해라.

기획서와 다른 방식으로 구현한 부분은 숨기지 말고
변경 기록에 원래 계획, 실제 구현, 이유, 영향을 작성해라.

Phase 0이 끝나면 다음 Phase로 자동 진행하지 말고
완료 보고를 남긴 뒤 기다려라.

비밀키와 .env 값은 출력하거나 커밋하지 마라.
```

---

# 7. 이후 Phase 시작 명령

Phase 0을 승인한 뒤에는 짧게 명령하면 된다.

```text
RAG_PHASE_EXECUTION_PLAN.md의 Phase 1을 진행해라.
해당 Phase의 체크박스와 종료 기록을 갱신하고,
완료 보고 후 다음 Phase로 넘어가지 말고 기다려라.
```

Phase 번호만 바꿔 반복한다.

---

# 8. 핵심 운영 방식

이 문서는 Claude Code를 지나치게 묶기 위한 문서가 아니다.

목적은 다음 세 가지다.

1. 어디까지 했는지 잊지 않게 하기
2. 중요한 원칙이 개발 중 사라지지 않게 하기
3. 실제 코드 때문에 계획이 바뀌었을 때 이유를 남기기

따라서 작은 구현 차이는 자유롭게 허용하고, 다음만 확실히 관리한다.

```text
정확한 숫자
실제값과 전망값 구분
최신 정정공시
출처
비공개 원본
비용
보안
기존 기능 보호
```
