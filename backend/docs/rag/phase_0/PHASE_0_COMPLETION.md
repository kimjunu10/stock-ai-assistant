# Phase 0 완료 보고

## 완료한 작업
- 브랜치 `rag/phase0` 생성, 저장소 상태 확인
- 기존 테스트 실행: **58 passed**
- FastAPI 진입점(`app.main:app`)·라우트·RAG placeholder 상태 확인
- Supabase 테이블/인덱스/함수 현황 확인 (RAG 신규 테이블 전부 없음)
- pgvector·pg_trgm 미설치 확인 + `CREATE EXTENSION` 권한 롤백 검증(가능)
- `CREATE TABLE`(public) 권한 롤백 검증(가능)
- 비공개 Storage 버킷 생성/삭제 권한 검증(가능, 버킷 0개)
- Upstage 임베딩 query/passage 실호출 → **둘 다 1024 dim**
- Solar `solar-pro3-260323` 스트리밍 실호출 확인
- 대표 리포트 PDF 1개 파싱(페이지 구분·메타·표 단위 확인)
- 토스증권 코드 위치 확인 + 005930 소량 실호출(현재가/일봉/분봉)
- 로컬 리포트 폴더 `/Users/kimjunwoo/report` 244개 PDF 확인
- Supabase에 주가 이력·리포트 없음 확인
- 산출물 및 사전조사 번들을 `backend/docs/rag/phase_0/`에 저장

## 수정한 파일
- 신규: `backend/docs/rag/phase_0/rag_preflight_report.md`
- 신규: `backend/docs/rag/phase_0/PHASE_0_COMPLETION.md`
- 신규: `backend/docs/rag/phase_0/precheck_bundle/*` (기존 조사 자료 보관)
- 애플리케이션 코드 변경 없음. (검증 스크립트는 세션 scratchpad에만 존재)

## DB 변경
- **없음.** 모든 권한 검증은 트랜잭션 ROLLBACK, Storage probe 버킷은 즉시 삭제.

## 테스트 결과
- `pytest`: 58 passed (0.73s)
- Upstage 임베딩: query 1024 / passage 1024 (일치)
- Solar 스트리밍: SSE 청크 수신 OK
- 토스 005930: 현재가 O, 일봉 5, 분봉 120

## 실제 응답/비용
- 검증용 소량 호출만 수행(임베딩 2건, 채팅 1건, 토스 1종목). 비용 무시 수준.
- 본격 인덱싱 비용 산정은 Phase 2/5에서 수행 예정.

## 기획서와 달라진 점
- 원래: (번들 gaps 문서) Upstage 임베딩 4096차원 참조
- 실제: 현행 공식 모델 `solar-embedding-2-*` **1024차원** 사용. SPEC 본문은 이미 `vector(1024)`라 정합.
- 이유: 구 alias(4096)는 2026-08-31 종료 예정.
- 영향: 인덱스 차원 1024로 확정. 뉴스 클러스터 centroid(BGE-M3 1024)와 **차원은 같지만 모델 세대가 다르므로 같은 인덱스에 혼용 금지**(고정 원칙 준수).

- 원래: PDF는 로컬 파서로 페이지·본문·표 연결
- 실제: 로컬 `pdftotext -layout`는 페이지/메타/단위는 확보하나 한국어 리포트 본문 순서·표 셀 복원이 불안정
- 이유: 세로형/그래픽 조판
- 영향: Phase 5에서 표·복잡 PDF에 Upstage Document Parse 등 보강 필요(SPEC의 "유연 판단" 범위 내)

## 아직 남은 문제
- RAG용 테이블/인덱스/Storage 전무 → Phase 1에서 생성 필요
- 로컬 PDF 경로가 저장소 밖(`/Users/kimjunwoo/report`) → 하드코딩 금지, Phase 5에서 env/CLI 인자로 처리
- 표 복원 파서 조합은 Phase 5에서 확정

## 사용자 확인이 필요한 것
- 없음 (치명적 충돌·데이터 손상·비용 초과·보안 위험 없음)

## 다음 Phase 진행 가능 여부
- **가능** — Phase 1(DB·Storage·Repository) 진행 가능

---

## Phase 종료 기록 (계획서 반영용)
```text
상태: 완료
완료일: 2026-07-22
확인한 임베딩 모델: solar-embedding-2-query / solar-embedding-2-passage
확인한 차원: 1024 (query=passage)
사용할 Chat 모델: solar-pro3-260323 (스트리밍 지원)
PDF 파서: 로컬 pdftotext -layout(1차) + Phase5에서 Upstage Document Parse 보강 예정
Phase 1 진행 가능 여부: 가능
주요 변경 필요 사항: 임베딩 1024 확정(4096 alias 미사용), 표 복원은 Phase5 파서 보강
```
