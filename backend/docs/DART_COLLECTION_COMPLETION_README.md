# DART 증분 보완 실행 README

이 작업은 기존 정상 데이터를 삭제하거나 처음부터 다시 만들지 않는다. Supabase의 보유 상태를 확인해 원문 누락·잘림·중요 공시와 최신 구조화 데이터만 보완한다. RAG 임베딩과 청킹은 실행하지 않는다.

## 환경변수

```dotenv
DART_API_KEY=...
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
DATABASE_URL=...
DART_RAW_DOCUMENT_DIR=data/dart/raw_documents
```

`DART_RAW_DOCUMENT_DIR`은 절대경로 또는 `backend/` 기준 상대경로를 사용할 수 있다. DB의 `raw_document_path`에는 이 루트 아래 상대경로만 저장된다.

## Migration

```bash
cd backend
/Library/PostgreSQL/17/bin/psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f migrations/0010_dart_source_completion.sql
/Library/PostgreSQL/17/bin/psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f migrations/0011_dart_document_unavailable_status.sql
```

기존 컬럼이나 행을 삭제하지 않는 비파괴 migration이다.

## Dry-run

```bash
cd backend
uv run python -m scripts.complete_dart_collection --dry-run
```

외부 DART 호출과 DB 변경 없이 종목별 원문 선택 건수, 예상 주요사항·정기보고서 호출 수를 출력한다.

## 실제 증분 보완

```bash
cd backend
uv run python -m scripts.complete_dart_collection \
  --run-key dart-rag-source-20260721 \
  --failure-log dart_collection_failures.jsonl
```

중단 후 같은 명령을 다시 실행하면 정상 보존 원문과 같은 run-key에서 완료된 구조화 API 요청은 건너뛴다.

## 특정 종목만 실행

```bash
uv run python -m scripts.complete_dart_collection \
  --run-key dart-rag-source-20260721-samsung \
  --only 005930
```

## 멱등성 검증

전체 실행 직후 같은 run-key로 동일 명령을 다시 실행한다. 출력의 `row_delta`와 Supabase 유일키 중복 집계를 확인한다.

## 원문 선택 정책

수집 대상:

- 잘린 원문
- 사업·반기·분기·주요사항보고서
- 잠정실적, 단일판매·공급계약, 배당
- 증자·감자, CB·BW·EB
- 자기주식 취득·처분
- 합병·분할, 자산·영업 양수도
- 주주총회, IR, 기준일·주주명부 폐쇄
- 정정공시

기본 제외:

- 임원·주요주주 특정증권 소유상황보고서
- 주식 등의 대량보유상황보고서
- 위 중요 패턴에 해당하지 않는 메타데이터성 공시

제외된 공시도 `disclosures` 목록·접수번호·DART 링크는 유지한다.

## 완료 결과 확인

- 보완 전: `docs/DART_DATA_INVENTORY_BEFORE.md`
- 대상 선정: `docs/DART_DATA_GAP_PLAN.md`
- 보완 후 및 API별 결과: `docs/DART_DATA_INVENTORY_AFTER.md`
- 실행 중 실패 이력과 해결 상태: `dart_collection_failures.jsonl`

원본 ZIP은 기본적으로 `data/dart/raw_documents/{stock_code}/{rcept_no}.zip`에 저장된다. RAG 청킹 전에는 DB에서 `parse_status=success`, `is_latest=true`를 우선하고 `unavailable`·저우선순위 `pending` 행을 제외한다.
