# Phase 7 프런트엔드 사전 조사

- 조사일: 2026-07-25
- 기준 브랜치: `phase/7-agent-rag-ui`
- 기준 코드: `origin/main` (`1df5d049`)

## 1. 문서와 실제 상태

요구 문서가 적은 `docs/rag/**`는 저장소 루트가 아니라 실제로
`backend/docs/rag/**`에 있다. 기준 설계 문서는 이 경로의 추적 중인 네 문서다.
Phase 6 실행 계획의 체크박스는 갱신되지 않았지만
`phase_6/PHASE_6_COMPLETION.md`와 운영 검증 브랜치 기록, 실제 `main` 코드에는
주가 Tool 2종이 구현돼 있다. 이번 작업은 오래된 체크박스 대신 실제 코드와 최신 완료
기록을 기준으로 한다.

현재 `/api/qa/stream`은 SSE 이벤트 순서는 지원하지만 실제 LangGraph 토큰 스트림이
아니라 Agent 실행이 끝난 뒤 Tool 상태와 답변 전체를 `delta` 한 건으로 내보낸다.
또한 Agent가 수집한 Tool의 구조화 `data`와 `sources`를 API 계층에서 버리고 있어
Phase 7 카드·차트를 안전하게 만들 데이터가 부족하다. Agent 라우팅을 바꾸지 않고
검증된 ToolResult를 optional UI payload로 변환하는 최소 백엔드 확장이 필요하다.

## 2. 프런트 스택

| 항목 | 조사 결과 |
|---|---|
| 프레임워크 | React 19 + TypeScript 6 |
| 빌드 | Vite 8 |
| 스타일 | Tailwind CSS 4의 `@apply` 기반 단일 `App.css`, Pretendard |
| 라우팅 | 라우터 패키지 없이 `history.pushState`와 pathname 분기 |
| 상태 | React 지역 상태와 커스텀 fetch hook, 전역 상태 라이브러리 없음 |
| API | 기능별 `src/api/*.ts`, `VITE_API_BASE_URL`, 개발 `/api` 프록시 |
| 차트 | `lightweight-charts` 5.2, 기존 `PriceChart` |
| Markdown | 안전한 Markdown 렌더러 없음 |
| 테스트 | 프런트 테스트 러너/스크립트 없음. lint와 production build만 존재 |
| 테마 | CSS custom properties 기반 light/dark |
| 모바일 | 820px/560px 미디어쿼리, 패널은 하단 드로어로 전환 |

## 3. 라우팅과 화면

- `/`: 홈 브리핑과 뉴스 사건 상세 모달. 뉴스에서 `onAsk` 진입점이 존재한다.
- `/stocks`: 종목 목록. 직접 질문 진입점은 없다.
- `/stocks/:stockCode`: 주가 차트, 뉴스 사건, DART 재무, 공시, 리포트 영역.
- `/news`: 뉴스 목록과 뉴스 상세 모달.
- `/ask`: 전역 AI 질문 페이지. 현재 하드코딩된 프로토타입 답변만 표시한다.
- 별도 공시 상세/리포트 상세 라우트는 없다. 공시는 DART viewer URL을 열 수 있고,
  리포트는 화면 데이터가 아직 비어 있다.

따라서 현재 제품 구조에서는 기존 `AssistantPanel`을 공통 문맥 패널로 유지하고,
`AskPage`와 동일한 RAG 대화 코어를 공유하는 방식이 가장 자연스럽다. 이 방식이면 홈,
종목 상세, 뉴스 상세, 공시 목록, 리포트 목록의 모든 `onAsk`가 한 계약을 사용한다.

## 4. 기존 재사용 대상

- `AssistantPanel`: 우측 패널/모바일 하단 드로어 레이아웃
- `NewsClusterCard`: 뉴스 사건 카드. RAG 응답에는 같은 정보 구조의 compact source
  스타일을 사용한다.
- `PriceChart`: 종목 상세의 실제 시세 차트. RAG의 소형 시계열은 같은
  `lightweight-charts`를 직접 중복 초기화하지 않고 접근 가능한 SVG 기반 compact
  renderer로 제한한다.
- `DisclosureList`, `ReportList`: 현재 문맥을 여는 공시/리포트 행
- `LoadingDots`, `Icon`, `StockAvatar`, `SentimentBadge`
- 날짜/금액 표기는 기존 `Intl.NumberFormat` 사용 방식을 따른다.

## 5. 현재 QA 계약

요청 모델은 현재 snake_case다.

```json
{
  "question": "...",
  "stock_code": "005930",
  "context_source_id": "...",
  "context_source_type": "news_event",
  "stream": true
}
```

실제 서비스 내부 `AgentQaService.answer`는 `document_id`, `report_page`,
`conversation_id`까지 이미 받을 수 있지만 API 스키마와 라우트가 전달하지 않는다.
`history`와 서버 대화 지속은 아직 지원하지 않으므로 UI에서 가짜 지속 상태를 만들지
않고, 현재 탭에서 보이는 질문/답변만 표시한다.

현재 SSE:

```text
agent_start → (tool_start → tool_end)* → sources → delta → done
```

`tool_start/end`에는 이름과 상태만 있어 원시 인자나 내부 추론은 노출되지 않는다.

## 6. 변경 예정

### 프런트

- `src/api/qa.ts`: fetch 기반 SSE parser, AbortController 호환 요청
- `src/types/qa.ts`: UI 상태, 출처, 허용 visualization union
- `src/hooks/useRagConversation.ts`: idle/connecting/running/streaming/completed/error/aborted
- `src/components/RagConversation.tsx`: 공통 대화, 진행 상태, 재시도, 중단, 출처
- `src/components/RagVisualizations.tsx`: typed payload 전용 카드/차트
- `AssistantPanel.tsx`, `AskPage.tsx`, `App.tsx`, `types/index.ts`: 공통 코어와 문맥 연결
- `App.css`, `index.css`: 기존 카카오 톤 유지 + 볼륨감 있는 clay shadow/pressed state
- 프런트 테스트 설정과 SSE/parser/renderer/문맥 단위 테스트

### 백엔드

- `app/schemas/qa.py`: optional 문맥 필드, `UiSource`, `Visualization` 추가
- `app/services/agent_qa.py`: 검증된 ToolResult에서 공개 UI payload 생성
- `app/api/routes/qa.py`: sources/done SSE에 typed payload 포함, 문맥 전달 보완
- 관련 Agent/API 계약 테스트

## 7. 디자인 방향

새 디자인 시스템은 만들지 않는다. 기존 노랑 브랜드, 라운딩, surface/subtle 토큰을
유지하되 AI composer, context badge, 숫자 카드, source card에 양방향 soft shadow와
얕은 inset highlight를 적용한다. 버튼 active 상태는 눌린 clay 질감으로 표현하며,
다크 모드에서는 밝은 테두리와 검은 그림자 강도를 낮춰 같은 깊이만 보존한다.

## 8. 확인된 한계

- 현재 별도 공시/리포트 상세 페이지가 없어 source 클릭은 실제 DART URL, 실제 응답 URL,
  또는 현재 종목 페이지의 기존 anchor로만 연결할 수 있다.
- 뉴스 Tool source_id는 현재 chunk id이고 UI 뉴스 사건 id와 항상 같다고 보장되지 않는다.
  URL/locator가 실제로 있을 때만 링크를 제공한다.
- Phase 6의 `daily`는 모델 컨텍스트 절약을 위해 최대 6점이다. 따라서 긴 주가 선은
  제공된 점만 표시하며 프런트가 보간하거나 새 수치를 계산하지 않는다.
- 서버 Agent가 동기 `invoke`를 사용하므로 첫 Tool 진행 표시가 요청 중 실시간으로 오지
  않는다. API 계약 순서는 유지되지만 진정한 모델 토큰 단위 스트리밍은 후속 런타임
  개선 없이는 불가능하다.
