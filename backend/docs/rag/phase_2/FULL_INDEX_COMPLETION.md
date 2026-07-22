# Phase 2 전체 인덱싱 완료 보고

- 완료일: 2026-07-22
- 브랜치: `rag/phase2`
- 대상: 활성 뉴스 사건 전체 (active_version `v2_event_role_20260721`)

## 최종 결과

| 항목 | 값 |
|---|---|
| 활성 사건 후보 | 2,940건 |
| **인덱싱된 문서(current)** | **2,940건** |
| **활성 청크** | **3,112개** |
| 제외 | **0건** |
| 실패(최종) | **0건** (1차 실패 1건 → 재인덱싱으로 복구) |
| 청크 없는 유령 문서 | 0건 (무결성 확인) |
| 소요 시간 | 1차 ~27분 + 복구 ~1분 |
| 추정 비용 | 임베딩 ~$0.10 (약 107만 토큰, Upstage Embed 2 참고 단가) |

## 중복 방지 / 비용 기록
- **해시 기반 중복 방지 동작 확인**: 재실행 시 기존분 skip, 재임베딩 0회(추가 비용 거의 0).
- 실행 로그는 `rag_ingestion_runs`에 기록:
  - 1차: `8ebaad32-...` status=partial (success 2939 / failure 1)
  - 복구: `80172e09-...` status=success
  - 최종 보정: cluster 4748 개별 재인덱싱(성공)
- 비용은 참고 단가 기반 추정치. 실제 청구액은 Upstage 콘솔 기준.

## 1차 실패 → 복구된 1건 (식별자 기록)
- **cluster_id: 4748** / stock: 005380(현대차)
- title: "현대차그룹, 보스턴다이내믹스 완전 자회사 편입 추진 및 계열사 로보틱스·AI 사업"
- 원인: 1차 전체 인덱싱 중 **임베딩 단계에서 일시 예외**로 실패. 문서/청크 모두 미생성(유령 데이터 없음).
- 경과: 1차 복구 재실행이 스케줄러의 신규 요약 활동과 타이밍이 겹쳐 이 건을 놓침 → **개별 재인덱싱으로 복구 완료**.
- 참고: 본문(factual_body 863자)이 정상 존재하는 사건으로, **"본문 없어 제외"가 아니었음**. 최종적으로 정상 인덱싱됨. 현재 제외 건은 0.

## 검색 검증
- **자기 사건 상위 포함(self_in_top): 5개 종목 5/5** (4개 rank 1, 현대차만 rank 8 — CSR 마이너 사건이라 같은 종목의 더 관련성 높은 사건이 상위. 정상)
- 교차 자연어 검색 정확:
  - "HBM 반도체 수요 어때?" → 삼성전자 AI메모리 / SK하이닉스 HBM / HBM4
  - "조선업 수주 상황" → 삼성중공업·HD한국조선해양·조선3사 수주 사건
- 검색 지연 97~318ms

## 기존 기능 영향
- 기존 뉴스/DART/재무 테이블·데이터 무변경 (읽기만).
- `rag_documents` / `rag_chunks`의 news_event 행만 추가.

## 증분 인덱싱 스케줄러 연결 (구현 완료)

이전에 "미연결"로 확인됐던 항목을 구현했다.

- 뉴스 사이클(`run_news_collection_cycle`)의 `summary → verify` **이후** `run_incremental_news_index`를 호출한다.
- 신규 모듈 `app/jobs/rag_index_job.py`가 담당하며, 다음을 만족한다:
  - **신규·변경만 처리**: 인덱서가 문서 `content_hash`로 기존 사건을 skip(재임베딩 0).
  - **예외 격리**: 인덱싱 실패는 함수 내부에서 모두 삼켜 뉴스 수집/클러스터링 사이클을 중단시키지 않는다(`_run_news_stage` 밖에서 직접 호출).
  - **동시 실행 방지(프로세스·인스턴스 간)**: `DATABASE_URL`이 있으면 **PostgreSQL advisory lock**(`pg_try_advisory_lock`, non-blocking)으로 여러 uvicorn 워커/컨테이너/인스턴스에서도 하나만 인덱싱한다. `DATABASE_URL`이 없는 환경(로컬/테스트)에서는 프로세스 내 `threading.Lock`으로 fallback. 이미 잡혀 있으면 `skipped_locked` 반환. (스케줄러 잡 `max_instances=1`/`coalesce=True`도 유지.)
  - **기록**: 로그(`RAG_INDEX_DONE`/`RAG_INDEX_FAILURES`/`RAG_INDEX_FATAL`) + `rag_ingestion_runs`(status/처리·성공·실패 건수/실패 cluster id/`trigger=scheduler_incremental`).
  - **기존 데이터 무수정**: 뉴스/DART 테이블은 읽기만, `rag_*`만 쓴다.
- 설정 플래그 `RAG_INDEX_ON_SCHEDULE`(기본 `true`)로 on/off. active_backfill 중에는 인덱싱도 건너뛴다.

### 실환경 검증
- 전량 인덱싱된 상태에서 잡 실행 → **2,940건 전부 skip, 인덱싱 0, 실패 0**(재실행 skip 실증).
- `rag_ingestion_runs`에 `trigger=scheduler_incremental`, status=success, processed=2940 기록 확인.

### 참고: 요약 지연 모드와의 관계
- `NEWS_SUMMARY_ENABLED=false`(비용 절감 모드)에서는 요약 안 된 신규 사건이 인덱싱 대상 조건(summary_status='success')에서 자연히 빠진다.
- 즉 요약을 켜거나 `scripts/summarize_v2.py`로 채운 뒤에야 그 사건들이 다음 사이클에서 인덱싱된다. 이는 의도된 순서다.

## 동시 실행 방지 — 배포 환경 분석 및 advisory lock 도입 (최종 확인)

### 왜 threading.Lock 으로 부족한가
- 스케줄러는 API 프로세스 lifespan 안에서 in-process(`AsyncIOScheduler`)로 뜬다(`app/main.py`).
- 현재 `Dockerfile`은 `uvicorn app.main:app`을 `--workers` 없이 실행 → **현재 구성상** 1 워커·1 컨테이너.
- 그러나 이는 **구성 관행이지 코드 보장이 아니다**:
  - `uvicorn --workers N`/gunicorn을 붙이면 워커마다 lifespan → 스케줄러 N개.
  - `docker compose --scale`/멀티 인스턴스 배포 시 컨테이너마다 스케줄러.
  - `threading.Lock`은 프로세스 내부 한정 → 위 경우 중복 인덱싱 가능.
- 결론: **단일 실행이 보장되지 않는다** → DB 기반 잠금으로 변경.

### 도입: PostgreSQL advisory lock
- `app/db/advisory_lock.py`: `pg_try_advisory_lock(key)` non-blocking, 세션 레벨(전용 psycopg 커넥션 유지, 블록 종료 시 `pg_advisory_unlock`).
- 키: `NEWS_RAG_INDEX_LOCK_KEY`(고정 64-bit).
- `DATABASE_URL` 있으면 advisory lock, 없으면 `threading.Lock` fallback.
- `psycopg[binary]`를 런타임 의존성으로 추가(pyproject/uv.lock 갱신).

### 실환경 검증
- advisory lock 상호배제: 1차 획득 True → 같은 키 2차 시도 **False** → 해제 후 재획득 True.
- advisory lock 경로로 인덱싱 잡 실행: processed 2953 / **indexed 53(신규분만)** / skipped 2900 / 실패 0 → **증분 동작 실증**.

## 테스트
- `tests/unit/test_rag_index_job.py`: 자동 반영 / 재실행 skip / 실패 격리 / partial 실패기록 / threadlock 방지 / **advisory lock 획득 실행 / advisory lock busy skip** (7)
- `tests/unit/test_advisory_lock.py`: URL 없음 False / 획득·해제 / busy 시 unlock 안 함 / 연결오류 False (4)
- `tests/unit/test_scheduler_rag_wiring.py`: 사이클이 인덱싱을 호출함 / 플래그로 끌 수 있음 (2)
- 전체 **87 passed**, 회귀 없음.

## .DS_Store 정리 (최종 확인)
- 추적 중인 `.DS_Store`: **없음**(git ls-files 확인).
- 루트 `.gitignore`에 `.DS_Store`/`**/.DS_Store` 규칙 존재.
- 단, `backend/.gitignore`의 `!docs/rag/**` 화이트리스트가 `backend/docs/rag/.DS_Store`를 다시 포함시켜 노출됐던 문제를 발견 → `backend/.gitignore`에 `.DS_Store`/`**/.DS_Store` 재무시 규칙 추가로 해결(현재 `git status`에 안 뜸).

## 기타
- Phase 3(하이브리드 검색)는 진행하지 않음 — 대기.
