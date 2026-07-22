# RAG Phase 0 사전 검증 리포트

- 검증일: 2026-07-22
- 브랜치: `rag/phase0` (base: `main` @ 7ac894c)
- 방식: 읽기 전용 조사 + 소량 실호출. DB 변경/Storage 변경은 전부 롤백·삭제.
- 비밀키는 값 미노출(키 이름만 확인).

## 1. 저장소 / 실행 상태

| 항목 | 결과 |
|---|---|
| 현재 브랜치 | `rag/phase0` (신규) |
| 기존 테스트 | `pytest` **58 passed** (0.73s) |
| FastAPI 진입점 | `app.main:app`, 라우터 `/api` 마운트 |
| 등록 라우트 | stocks, clusters, disclosures, financials, reports, qa |
| QA/reports 라우트 | **엔드포인트 없음(placeholder)** |
| RAG 코드 | `app/rag/*.py`, `app/ml/embeddings.py`, `generation.py` 모두 **docstring placeholder** |

## 2. Supabase DB

출처: `rag_precheck_bundle/database_status.md` (읽기전용) + 본 검증 롤백 테스트.

| 항목 | 결과 |
|---|---|
| pgvector 설치 여부 | **미설치** |
| pg_trgm 설치 여부 | **미설치** |
| `CREATE EXTENSION vector` 권한 | **가능** (트랜잭션 롤백 확인) |
| `CREATE EXTENSION pg_trgm` 권한 | **가능** (롤백 확인) |
| `CREATE TABLE`(public) 권한 | **가능** (probe 생성→drop→롤백) |
| DB 롤 | `postgres` / super=false, createrole=true, createdb=true |
| RAG 신규 테이블 | `chunks/reports/research_reports/terms/qa_logs/prices` 등 **전부 없음** |
| 기존 데이터 | articles 10,470 / news_clusters 6,828 / disclosures 4,722 / structured_disclosures 1,524 / financials 510 등 존재 |
| news_clusters.centroid | `double precision[]`, 전 행 길이 1024, null 0 (pgvector 아님) |
| 벡터/검색 인덱스·함수 | 없음 |

## 3. Storage

| 항목 | 결과 |
|---|---|
| 기존 버킷 | 0개 |
| 비공개 버킷 생성 권한 | **가능** (probe 버킷 private 생성→삭제 확인) |
| RLS | 18개 public 테이블에 enable(not forced), storage/public 정책 0개 |

## 4. Upstage 임베딩 (실호출)

| 항목 | 결과 |
|---|---|
| query 모델 | `solar-embedding-2-query` → **1024 dim** |
| passage 모델 | `solar-embedding-2-passage` → **1024 dim** |
| 차원 일치 | **일치 (1024)** |

- 구 alias `embedding-query/passage`(4096)는 2026-08-31 종료 예정 → **사용 안 함**.
- SPEC(`RAG_IMPLEMENTATION_SPEC.md`)은 이미 `vector(1024)` 기준이라 실제와 정합. (번들 gaps 문서의 4096 언급은 구버전 기준 참고용.)

## 5. Solar Chat (실호출)

| 항목 | 결과 |
|---|---|
| 사용 모델 | `solar-pro3-260323` (뉴스 파이프라인과 동일 계열) |
| 스트리밍 | **지원** (SSE 청크 15개 수신 확인) |
| 계정 카탈로그 | solar-mini/pro2/pro3 계열 + 260323 pin 사용 가능 |

## 6. PDF 파싱

- 리포트 폴더: `/Users/kimjunwoo/report`, 종목별 5폴더, **총 244개** (SPEC 244와 일치).
  - 두산에너빌리티 26 / 삼성전자 86 / 한화오션 28 / 현대차 39 / SK하이닉스 65
- 파일명 규칙 `date_company_broker_title.pdf` → import 스크립트 기대와 일치.
- 파서: 현재 로컬 `pdftotext -layout` (poppler 26.04.0 설치됨). PDF 전용 파이썬 의존성은 미설치.
- 대표 PDF(미래에셋 두산에너빌리티, 최대 용량) 검증:

| 항목 | 결과 |
|---|---|
| 페이지 구분(form-feed) | 유지됨(12) → 페이지별 저장 가능 |
| 메타 키워드 | 투자의견/목표주가/기준주가/Buy 추출됨 |
| 표 단위 표기 | 십억원/억원/%/배/원 보존됨 |
| 본문 순서·표 셀 정합 | **불안정** (세로형/그래픽 조판에서 글자·셀 순서 흐트러짐) |

→ 텍스트/메타/단위는 로컬 파서로 확보 가능하나, **본문 재구성과 표 행·열 정확 복원은 로컬 파서만으로 부족**. Phase 5에서 표·복잡 레이아웃 PDF에 Upstage Document Parse 등 보강 필요.

## 7. 토스증권 API

| 항목 | 결과 |
|---|---|
| 연동 코드 | `app/sources/prices.py` `TossInvestClient` (구현 완료, 재사용 가능) |
| 키 존재 | `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET` 존재(값 미노출) |
| 소량 실호출(005930) | 성공: 현재가 O, 일봉 5, 분봉 120 |
| 지원 범위 | 현재가·전일종가, 일봉/분봉 캔들(2~200), 호가, 가격제한 |
| 지원 종목 | 005930,000660,034020,042660,005380 (5종) |
| Supabase 주가 이력 | **없음** (prices 테이블 부재 확인) |

## 8. 최소 통과 조건 판정

| 조건 | 판정 |
|---|---|
| 임베딩 모델·차원 확인 | ✅ 1024 (query/passage) |
| DB 마이그레이션 실행 가능 | ✅ extension+table 생성 권한 확인 |
| 기존 기능 기본 실행 | ✅ 58 tests pass |
| PDF 페이지·본문 연결 | ⚠️ 페이지 연결 OK, 표/본문 정합은 Phase 5 파서 보강 필요 |
| 치명적 충돌 없음 | ✅ 없음 |

**결론: Phase 1 진행 가능.**
