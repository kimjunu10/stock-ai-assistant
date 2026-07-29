# Moa AI

Moa AI는 국내 주식 정보를 한곳에서 살펴보고, 어려운 금융 정보를 자연어로 질문할 수
있는 AI 투자 정보 서비스입니다. 뉴스, 공시, 재무 정보, 증권사 리포트와 주가 데이터를
종목별로 모아 초보 투자자도 이해하기 쉽게 보여주는 것을 목표로 합니다.

> Moa AI가 제공하는 내용은 투자 참고용 정보이며, 특정 종목의 매수·매도를 권유하지
> 않습니다. 최종 투자 판단과 책임은 사용자에게 있습니다.

## 주요 기능

- **종목 정보**: 국내 주요 종목의 주가 차트와 핵심 정보를 제공합니다.
- **뉴스 브리핑**: 관련 기사를 주제별로 묶고 호재·악재·중립 관점으로 요약합니다.
- **공시·재무 정보**: 기업 공시와 주요 재무 지표를 종목 화면에서 확인할 수 있습니다.
- **증권사 리포트**: 종목별 리포트와 투자의견, 목표주가 등 주요 정보를 제공합니다.
- **AI 질의응답**: 뉴스, 주가, 공시, 재무 정보와 리포트를 근거로 질문에 답하고 참고한
  출처를 함께 보여줍니다.

## 기술 구성

| 영역 | 주요 기술 |
| --- | --- |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Backend | Python, FastAPI, LangChain, LangGraph |
| Data & AI | Supabase, OpenAI, Upstage, Sentence Transformers |
| Infra | Docker, GitHub Actions |

## 프로젝트 구조

```text
stock-ai-assistant/
├── backend/                       # API, 데이터 처리, AI/RAG
├── frontend/kakao-stock-frontend/ # React 웹 애플리케이션
├── deploy/                        # 운영 배포 설정
└── .github/workflows/             # CI/CD
```

세부 내용은 [백엔드 문서](backend/README.md)와
[프론트엔드 문서](frontend/kakao-stock-frontend/README.md)를 참고해 주세요.

## 로컬 실행

### 사전 준비

- Python 3.11 이상
- [uv](https://docs.astral.sh/uv/)
- Node.js와 npm
- 사용하는 외부 서비스의 API 키

### 1. 백엔드

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run uvicorn app.main:app --reload
```

필요한 환경변수는 `backend/.env.example`을 기준으로 설정합니다. 로컬 API 문서는
`http://localhost:8000/docs`에서 확인할 수 있습니다.

### 2. 프론트엔드

새 터미널에서 다음 명령을 실행합니다.

```bash
cd frontend/kakao-stock-frontend
npm install
npm run dev
```

기본 접속 주소는 `http://localhost:5173`입니다. 개발 환경에서는 프론트엔드가
`http://127.0.0.1:8000`의 백엔드 API를 사용합니다.

## 테스트

```bash
# Backend
cd backend
uv run ruff check .
uv run pytest

# Frontend
cd frontend/kakao-stock-frontend
npm run lint
npm run test
npm run build
```

변경 사항은 브랜치에서 작업하고, 관련 테스트를 통과한 뒤 Pull Request로 반영합니다.
