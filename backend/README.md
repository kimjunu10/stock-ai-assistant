# Stock Assistant Backend

증권 AI 투자 어시스턴트의 FastAPI 백엔드입니다. 네이버 뉴스 수집·본문 크롤링,
종목 관련성/기사 역할 분류, BGE-M3와 Solar를 이용한 사건 클러스터링, 사건 요약,
클러스터 제목 기반 감성분류, Supabase 저장과 조회 API가 구현되어 있습니다.

현재 뉴스 처리 기준은 다음 문서를 기준으로 합니다.

- [뉴스 처리·클러스터링](docs/NEWS_PIPELINE.md)
- [뉴스 클러스터 감성분류](docs/NEWS_CLUSTER_SENTIMENT.md)

## 디렉터리 구조

```text
backend/
├── app/
│   ├── api/          # HTTP API 라우터
│   ├── core/         # 환경설정 등 애플리케이션 공통 설정
│   ├── db/           # Supabase 연결 경계
│   ├── repositories/ # 테이블별 데이터 접근 계층
│   ├── schemas/      # 요청·응답 Pydantic 스키마
│   ├── services/     # 유스케이스와 업무 흐름
│   ├── sources/      # 네이버·DART 등 외부 데이터 수집기
│   ├── ml/           # 임베딩·클러스터링·감성분류·문장 생성
│   ├── rag/          # 청킹·인덱싱·검색·프롬프트
│   ├── jobs/         # APScheduler 배치 작업
│   └── main.py       # FastAPI 진입점
├── migrations/       # Supabase/PostgreSQL 스키마 변경 파일
└── tests/            # 단위·통합 테스트
```

## 실행 준비

```bash
cp .env.example .env
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

API → 서비스 → 저장소/외부 소스 순으로 의존하도록 구성합니다.
