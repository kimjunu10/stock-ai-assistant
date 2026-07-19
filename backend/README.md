# Stock Assistant Backend

`SPEC.md`에 정의된 증권 AI 투자 어시스턴트의 FastAPI 백엔드 뼈대입니다.
현재는 디렉터리와 모듈의 책임만 나눠 놓았으며, 수집·분류·RAG·DB 처리 로직은 구현하지 않았습니다.

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

실제 기능 구현 시 API → 서비스 → 저장소/외부 소스 순으로 의존하도록 구성합니다.
