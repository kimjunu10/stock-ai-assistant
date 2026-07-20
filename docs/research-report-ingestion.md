# 리서치 리포트 적재 설계

현재 로컬 리포트는 244개, PDF 원본 약 300MB, 총 1,877페이지다. 페이지별 원문은
약 670만 자이며 37개는 추출량이 500바이트 미만인 이미지형 PDF다.

## 저장 경계

- 비공개 Supabase Storage: 원본 PDF
- `research_reports`: 종목, 증권사, 제목, 날짜, 해시, 스토리지 경로, 추출 상태
- `research_report_pages`: 페이지별 원문
- 현재 단계에서는 청크와 임베딩을 만들지 않는다.

이 구조는 원본을 Postgres의 `bytea`나 base64로 넣지 않으므로 DB 백업과 쿼리를
불필요하게 무겁게 만들지 않는다. 나중의 RAG 인덱서는 페이지 원문을 입력으로 삼아
버전이 있는 별도 청크/벡터 테이블 또는 외부 벡터 스토어를 만들면 된다.

## 실행 순서

1. `backend/scripts/research_reports_schema.sql`을 DB에 적용한다.
2. `python scripts/import_research_reports.py /Users/kimjunwoo/report`로 dry-run한다.
3. 결과와 저작권/접근 정책을 확인한다.
4. 같은 명령에 `--apply`를 붙여 업로드한다. SHA-256 중복은 건너뛴다.
5. `needs_ocr`만 별도 OCR 작업으로 보강한다.

Storage 버킷은 public이 아니며, 사용자에게 원문을 보여줄 때는 백엔드가 짧은 만료의
signed URL을 발급해야 한다. 증권사 리포트의 외부 재배포 권한은 업로드 전에 별도로
확인한다.
