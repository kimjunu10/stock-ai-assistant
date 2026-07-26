# RAG 답변 출력 구조 — UI 재작업용 참고 문서

이 문서는 **UI를 새로 짜는 사람(Codex 등)이 백엔드 내부 로직을 몰라도 되도록**,
`/api/qa`·`/api/qa/stream`이 실제로 반환하는 응답의 정확한 JSON 구조만 정리한
것이다. Agent가 어떤 프롬프트로 어떤 Tool을 고르는지, RAG 검색이 어떻게
동작하는지는 UI와 무관하므로 다루지 않는다.

- 백엔드: `backend/app/api/routes/qa.py`, `backend/app/schemas/qa.py`
- 기존 프론트 구현(참고용, 그대로 유지할 필요 없음): `frontend/kakao-stock-frontend/src/{types/qa.ts, api/qa.ts, hooks/useRagConversation.ts, components/Rag*.tsx}`

---

## 1. 엔드포인트 2개

| 엔드포인트 | 방식 | 용도 |
|---|---|---|
| `POST /api/qa` | 동기, 단일 JSON 응답 | 스트리밍이 필요 없을 때 |
| `POST /api/qa/stream` | SSE (`text/event-stream`) | 실제 서비스 UI가 쓰는 경로 |

**중요한 사실**: 서버는 Agent 실행을 전부 동기로 완료한 뒤 그 결과를 SSE
이벤트로 "재생"한다. 실시간 토큰 스트리밍이 아니다. `tool_start`/`tool_end`도
실시간이 아니라 완료 후 한꺼번에 순서대로 방출된다. `delta` 이벤트도 토큰 단위가
아니라 **완성된 답변 전체 텍스트가 한 번에** 온다. UI를 짤 때 "타이핑 애니메이션"을
넣고 싶다면 프론트에서 텍스트를 받은 뒤 인위적으로 나눠 보여줘야 한다 — 서버가
그렇게 주지 않는다.

Agent가 비활성화된 환경이면 두 엔드포인트 모두 **HTTP 503**
(`{"detail": "QA 서비스가 현재 비활성화되어 있습니다(Agent 미구성)."}`)을 반환한다.

---

## 2. 요청 바디 (`QaRequest`, 두 엔드포인트 공통)

```ts
interface QaRequest {
  question: string                    // 필수, 1~2000자
  stock_code?: string                 // 6자리 숫자, 예: "005930"
  context_source_id?: string          // 현재 보고 있는 문서/사건의 id
  context_source_type?: string        // 위 문서의 종류
  event_context?: EventContext[]      // 아래 참고, 최대 10개
  selected_event_id?: string
  document_id?: string
  report_page?: number                // 1 이상
  conversation_id?: string            // 최대 128자
  history?: object[]                  // 현재 서버가 사용하지 않음(보내도 무시됨)
  stream?: boolean                    // 기본 true (다만 실제로 어느 엔드포인트를
                                       // 치느냐로 스트리밍 여부가 정해짐)
}

interface EventContext {
  event_id: string           // 직전 응답의 sources[].source_id 를 그대로
  stock_code?: string
  published_at?: string      // ISO
  title?: string
  source_type?: string
  user_selected: boolean     // 사용자가 카드를 직접 클릭해서 골랐는지
}
```

`EventContext`는 "이 뉴스 이후 주가가 어떻게 됐어?" 같은 후속 질문에서 어떤
사건을 가리키는지 서버에 명시적으로 알려주는 값이다. **답변 텍스트를 파싱해서
채우면 안 된다** — 직전 응답의 `sources`(또는 `news_cards`/`event_timeline`
visualization의 아이템)를 그대로 담아 보내야 한다. 사용자가 카드를 여러 개 중
하나 직접 클릭했다면 `user_selected: true`로 표시한다.

---

## 3. SSE 이벤트 순서 (`/api/qa/stream`)

```
agent_start
  → (tool_start → tool_end)*      ← Tool 호출 개수만큼 반복
  → sources
  → error                          ← 실패 시 여기서 스트림 종료(아래 이벤트 없음)
     또는
  → delta → done                   ← 성공 시
```

각 이벤트는 `event: <name>\ndata: <json>\n\n` 형식.

| 이벤트 | data 구조 | 비고 |
|---|---|---|
| `agent_start` | `{ question: string }` | 요청 접수 직후 즉시 |
| `tool_start` | `{ name: string }` | Tool 이름만(예: `"search_news"`) |
| `tool_end` | `{ name: string, status: string \| null }` | `tool_start`와 순서대로 1:1 대응 |
| `sources` | `{ sources: Source[], visualizations: Visualization[], warnings: string[] }` | §4, §5 참고. **답변 텍스트보다 먼저 도착** — 카드/그래프를 답변보다 먼저 그리거나 동시에 그릴 수 있음 |
| `delta` | `{ text: string }` | 완성된 답변 전체 문자열(토큰 단위 아님, 보통 1회만 옴) |
| `done` | `{ stop_reason: string, model_calls: number, tool_calls: string[], visualizations: Visualization[], warnings: string[] }` | 스트림 종료 신호 |
| `error` | `{ message: string, stop_reason: string }` | 실패 시 마지막 이벤트 |

UI 설계 팁: `sources` 이벤트가 `delta`보다 먼저 오므로, "자료를 찾는 중 → 카드/그래프
먼저 표시 → 답변 텍스트 표시" 순서로 자연스럽게 단계적 로딩을 연출할 수 있다.

### stop_reason 값
`"completed"`(정상) / `"timeout"`(응답 시간 초과) / `"step_limit"`(조회 단계 한도
초과) / `"error"`(내부 오류) / `"runner_error"`(평가 전용, 서비스 응답에는 안 나옴).

---

## 4. 동기 응답 (`/api/qa`, `QaResponse`)

```ts
interface QaResponse {
  answer: string
  sources: Source[]
  broker_opinions: BrokerOpinion[]
  visualizations: Visualization[]
  warnings: string[]
  execution: AgentExecution | null

  // 아래 필드는 응답 스키마에는 존재하지만 Agent 경로에서 항상 빈 값이다.
  // UI에서 사용하지 말 것(레거시, 곧 제거될 수 있음).
  numeric_sources: []
  report_sources: []
  term: null
  official_information: []
  invalid_citations: []
  latency_ms: {}
}

interface AgentExecution {
  agent: true
  tool_calls: { name: string; status: string | null; result_count: number | null }[]
  model_calls: number
  stop_reason: string | null
  validation_errors: string[]   // 화면에 그대로 노출하지 않는 내부 검증 로그
  source_ids: string[]
}
```

스트리밍 경로의 `sources`+`delta`+`done` 이벤트를 하나로 합친 것이 이 응답이라고
보면 된다. `execution`이 SSE의 `done` 이벤트에 대응한다.

---

## 5. `sources` 배열 — 출처 카드 공통 구조

```ts
interface Source {
  source_id: string | null
  source_type:
    | "news_event" | "research_report" | "financial"
    | "term" | "structured_disclosure" | "dart_document" | "price"
  title: string | null
  publisher: string | null
  url: string | null
  stock_code: string | null
  published_at: string | null   // ISO, 종류에 따라 null 가능
  page: number | null
  value_kind: string | null      // "actual" | "forecast" 등
  locator: Record<string, unknown>   // 종류별로 완전히 다름, 아래 표 참고
  citation: number    // 항상 0 (미사용 필드)
  chunk_id: string | null  // 항상 null (미사용 필드)
}
```

`sources`는 이번 답변에 실제로 쓰인 근거 전체를 `source_id` 기준 중복 제거한
목록이다. **"확인한 출처" 섹션 하나로 몰아서 보여줘도 되고, source_type별로
섹션을 나눠도 된다** — 실제 서비스는 후자(뉴스/리포트/공시/용어를 구분 표시).

### 5-1. `news_event`

```json
{
  "source_id": "71fdddab-6551-42ed-aa8b-1bea84849b7b",
  "source_type": "news_event",
  "title": "이재용-올트먼, 오픈AI 본사에서 AI·반도체 협력 논의",
  "publisher": null,
  "published_at": "2026-07-26T07:16:00+00:00",
  "url": null,
  "locator": { "source_pk": "7201", "document_id": "7557c820-6d1b-4777-94e5-fb91a067e9d5" }
}
```
- `publisher`/`url`이 `null`인 경우가 흔하다(원문 언론사 크롤링이 안 된 케이스) — UI는 이 경우 링크를 숨기거나 "원문 미제공" 처리.
- `locator.source_pk`는 뉴스 "사건 클러스터" id(여러 기사를 하나로 묶은 사건 단위).

### 5-2. `research_report`

```json
{
  "source_id": "301b74ab-df0b-45fa-bd31-c7cb9d61e6a7",
  "source_type": "research_report",
  "title": "시선을 약간만 아래로",
  "publisher": "미래에셋증권",
  "published_at": "2026-07-14",
  "page": 8,
  "locator": {
    "report_id": "18f336cf-2f29-44fb-a626-b56ed9088db7",
    "page_number": 9,
    "pdf_page": 8,
    "source_page": null,
    "target_price_source_page": 1,
    "evidence": "...리포트 원문 발췌(최대 500자)...",
    "investment_opinion": "매수",
    "target_price": 4200000
  }
}
```
- PDF 원문 다운로드가 필요하면 `locator.report_id`와 화면 문맥의 종목코드로
  `GET /api/stocks/{stockCode}/reports/{reportId}/download` 를 호출(기존 프론트
  구현 참고: `RagSources.tsx`).
- `locator.evidence`가 있으면 인용 원문이므로 "근거 보기" 같은 접이식 UI로 노출하기 좋다.
- `locator.target_price`는 서버가 이미 "명시적으로 stated된 값"만 골라 넣은 것 —
  프론트가 리포트 본문에서 숫자를 다시 파싱할 필요 없음.

### 5-3. `financial` (DART 정식 재무제표 값)

```json
{
  "title": "영업이익 · 2025 연간 · 연결",
  "value_kind": "actual",
  "locator": { "source_type": "...", "source_key": "..." }
}
```
`publisher`/`url`/`page`는 항상 `null`.

### 5-4. `structured_disclosure` (공시 핵심값)

```json
{
  "title": "dividend_matter",
  "published_at": null,
  "locator": { "rcept_no": "20260716000582", "event_type": "dividend_matter" }
}
```
**주의**: `title`이 영문 이벤트 코드 그대로 온다(한글 라벨 아님). UI에서
`event_type`을 한글로 매핑하는 테이블을 직접 만들어야 한다(예:
`dividend_matter` → "배당 결정"). `published_at`이 `null`인 경우도 있다.

### 5-5. `dart_document` (공시 원문 문서)

```json
{
  "title": "임원ㆍ주요주주특정증권등소유상황보고서",
  "published_at": "2026-07-16T00:00:00+00:00",
  "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260716000582",
  "locator": { "rcept_no": "20260716000582" }
}
```
`url`이 DART 공식 뷰어 링크로 바로 채워져 있어 그대로 새 탭 링크로 쓰면 된다.

### 5-6. `term` (금융용어 정의)

```json
{
  "source_id": "term:공매도",
  "title": "공매도",
  "publisher": "한국은행",
  "locator": { "source_title": "경제금융용어 800선", "source_page": 29 }
}
```

### 5-7. `price` (주가 조회 근거)

```json
{
  "source_id": "price:005930:2026-07-24",
  "title": "005930 주가 · 2026-07-24",
  "publisher": "토스증권 Open API",
  "value_kind": "actual",
  "locator": { "stock_code": "005930", "interval": "1d", "provider": "toss", "as_of": "..." }
}
```

---

## 6. `visualizations` 배열 — 구조화 카드/그래프

```ts
interface Visualization {
  type: VisualizationType
  title: string          // 서버가 이미 한글 제목을 채워줌(그대로 써도 됨)
  data: Record<string, unknown>   // 타입별로 완전히 다름, 아래 참고
  source_ids: string[]   // 이 카드의 근거가 되는 sources[].source_id 목록
}
```

한 답변에 여러 개의 visualization이 동시에 올 수 있다(예: 뉴스카드 + 주가그래프).
`source_ids`로 어떤 `sources` 항목과 연결되는지 알 수 있으므로, 카드를 클릭하면
관련 출처를 하이라이트하는 식의 UI도 가능하다.

### `news_cards`
```json
{
  "type": "news_cards",
  "title": "최근 뉴스",
  "data": {
    "items": [
      {
        "source_id": "...", "title": "...", "snippet": "...(요약)",
        "published_at": "2026-07-26T07:16:00+00:00",
        "publisher": null, "url": null, "stock_code": "005930",
        "sentiment": "positive" | "neutral" | "negative" | null
      }
    ],
    "date_from": "2026-07-24" | null,
    "date_to": "2026-07-27" | null
  }
}
```
`sentiment`은 값이 있을 때만 배지를 그리면 된다(구식 데이터는 `null`).

### `price_line` (일봉 데이터 2건 이상 있을 때)
```json
{
  "type": "price_line",
  "title": "실제 주가 흐름",
  "data": {
    "points": [
      { "trading_day": "2026-07-24", "close": 91000, "open": 90000, "high": 92000, "low": 89500, "volume": 12345678, "currency": "KRW" }
    ],
    "quote": { "stock_code": "005930", "price": 91000, "previous_close": 90000, "change": 1000, "change_rate": 1.11, "currency": "KRW", "as_of": "...", "trading_day": "2026-07-24" },
    "period": null
  }
}
```
`points`는 최대 60거래일, 오래된 순.

### `price_snapshot` (일봉 데이터가 없거나 1건뿐일 때 — 현재가만)
```json
{
  "type": "price_snapshot",
  "title": "실제 주가",
  "data": {
    "quote": { "stock_code": "005930", "price": 91000, "previous_close": 90000, "change": 1000, "change_rate": 1.11, "currency": "KRW", "as_of": "...", "trading_day": "2026-07-24" },
    "period": {
      "stock_code": "005930", "start_trading_day": "2026-06-24", "end_trading_day": "2026-07-24",
      "start_close": 80000, "end_close": 91000, "change": 11000, "return_pct": 13.75,
      "currency": "KRW", "adjusted": true
    }
  }
}
```
`quote`, `period` 둘 다 상황에 따라 `null`일 수 있다(질문이 "현재가"만 물었으면 `period`는 null, "한 달 수익률"만 물었으면 `quote`는 null인 식).

### `event_return` (특정 사건 발표 전후 수익률)
```json
{
  "type": "event_return",
  "title": "발표 전후 주가 변화",
  "data": {
    "stock_code": "005930", "event_date": "2026-07-20",
    "baseline_trading_day": "2026-07-17", "baseline_close": 85000,
    "horizons": [
      { "horizon_days": 1, "trading_day": "2026-07-21", "close": 87000, "change": 2000, "return_pct": 2.35 },
      { "horizon_days": 3, "trading_day": "2026-07-23", "close": 89000, "change": 4000, "return_pct": 4.7 },
      { "horizon_days": 5, "trading_day": "2026-07-25", "close": 91000, "change": 6000, "return_pct": 7.06 }
    ],
    "currency": "KRW", "adjusted": true
  }
}
```
`horizons`는 발표 후 확정된 거래일만큼만 채워진다(최대 1/3/5거래일 시점 3개,
아직 3거래일이 지나지 않았으면 그만큼만 옴 — 없으면 이 visualization 자체가
생성되지 않고 답변이 "데이터가 아직 없다"는 텍스트로 대체됨. §8 참고).

### `financial_series` (DART 재무 수치 나열)
```json
{
  "type": "financial_series",
  "title": "DART 공식 재무정보",
  "data": { "items": [ { "label": "...", "value_won": 0, "value_display": "...", "unit": "원", "period": "...", "basis": "연결", "value_kind": "actual" } ] }
}
```

### `disclosure_metrics` (공시 핵심 수치)
```json
{
  "type": "disclosure_metrics",
  "title": "공시 핵심 정보",
  "data": { "items": [ { "rcept_no": "...", "event_type": "dividend_matter", "announced_at": "...", "summary": "...", "normalized_data": { "contract_amount": 0, "contract_counterparty": "...", "...": "..." } } ] }
}
```
`normalized_data`의 키는 `event_type`에 따라 달라진다(계약 관련이면
`contract_amount`/`contract_counterparty`/`contract_start_date`/`contract_end_date`,
배당이면 다른 키). 이 문서에서 모든 키를 다 나열하진 않으니, 실제 렌더링 시
`Object.entries(normalized_data)`로 순회하며 알려진 키만 한글 라벨로 매핑하고
모르는 키는 그대로(또는 숨김) 처리하는 방어적 구현을 권장한다.

### `event_timeline` (뉴스+공시가 함께 나올 때만 생성됨)
```json
{
  "type": "event_timeline",
  "title": "관련 사건 타임라인",
  "data": {
    "events": [
      { "kind": "news", "title": "...", "at": "2026-07-24T09:00:00+00:00", "source_id": "...", "publisher": "...", "url": "..." },
      { "kind": "disclosure", "title": "...", "at": "2026-07-23T00:00:00+00:00", "source_id": "20260716000582", "publisher": "DART" }
    ]
  }
}
```
최신순 정렬, 최대 12건. `kind`가 `"news"` 또는 `"disclosure"`뿐이므로 아이콘/색상
분기가 단순하다.

### `term_definition`
```json
{ "type": "term_definition", "title": "금융용어", "data": { "term": "공매도", "english_name": "...", "official_definition": "...", "easy_definition": "..." } }
```

### `broker_targets` (증권사 목표주가 목록 — `report_opinions`와 별도)
```json
{ "type": "broker_targets", "title": "증권사 목표주가", "data": { "items": [ { "broker": "...", "target_price": 4200000, "investment_opinion": "매수", "...": "..." } ] } }
```
이 배열은 dedup이 안 된 원본 목록이라 아래 `broker_opinions`(§7)와 건수가 다를
수 있다. **증권사 의견 카드 UI는 `broker_opinions`를 우선 쓰고, `broker_targets`는
보조 데이터로만 참고하는 걸 권장**(서버가 이미 중복 제거·최신 1건만 골라둔 쪽이
`broker_opinions`이기 때문).

---

## 7. `broker_opinions` — 증권사 의견 카드 (동기 응답 전용 필드명, SSE에선 `sources`/`done` 이벤트 안에 안 오고 `visualizations`의 `broker_targets`로만 흘러온다는 점 주의)

```ts
interface BrokerOpinion {
  broker: string | null
  report_date: string | null
  title: string | null
  investment_opinion: string | null
  target_price: number          // stated인 것만 카드화되므로 항상 값 있음
  target_price_currency: string | null
  target_price_status: "stated"  // 항상 "stated"
  summary: string | null         // 핵심 전망 요약(snippet)
  source_id: string | null       // sources 배열과 매칭 가능
  source_page: number | null
  is_stale: boolean
}
```
서버가 이미 "목표주가가 명시적으로 stated된 것만, 증권사별 최신 발행일 1건만"
걸러서 준다 — 프론트가 추가로 dedup할 필요 없다. `is_stale: true`면 "다소 오래된
의견일 수 있음" 같은 보조 표시를 고려.

**참고**: 이 필드는 `QaResponse`(동기 `/api/qa`)에만 있는 이름이다. SSE
스트리밍 경로에서는 이 데이터가 `visualizations` 배열의 `broker_targets` 타입으로
대신 전달된다(§6 마지막 항목). 즉 SSE로 UI를 짤 거라면 증권사 의견 카드는
`broker_targets` visualization을 써야 한다.

---

## 8. 특수 상황 (에러 · 답변 불가 · 안전장치)

- **Agent 비활성화**: HTTP 503, 고정 안내문.
- **타임아웃**: `stop_reason: "timeout"`. SSE는 `error` 이벤트로 종료. UI 권장 문구:
  "답변 시간이 초과됐어요, 다시 시도해 주세요" 류.
- **조회 단계 초과**: `stop_reason: "step_limit"`.
- **일반 오류**: `stop_reason: "error"`, 메시지에 내부 예외 타입명만 노출(스택트레이스 없음).
- **근거 없이 답할 수 없는 사건 질문**(예: "이 뉴스 발표 후 주가 어떻게 됐어?"인데
  아직 확정 거래일 데이터가 없거나 사건이 특정되지 않음): 이 경우 `answer` 텍스트
  자체가 정형화된 안내 문구로 오고, 관련 `event_return` visualization은 아예
  생성되지 않는다. 즉 "카드는 없는데 텍스트로 상황을 설명"하는 답변이 정상
  케이스로 존재한다 — UI가 "visualization이 없으면 빈 화면"이 되지 않도록
  `answer` 텍스트만으로도 충분히 읽히게 레이아웃을 짜야 한다.
- **근거 없는 문장 자동 제거**: 서버가 답변 문장 일부를 검증 실패로 제거하고
  안내 문구를 붙이는 경우가 있다(예: "일부 증권사의 구조화된 목표주가를 확인할 수
  없어 해당 수치는 제외했습니다."). 이건 `answer` 텍스트에 이미 포함돼 오므로
  UI가 별도 처리할 필요는 없다 — 그대로 표시하면 된다.
- **`warnings` 배열**: 답변과 별개로 "일부 조회가 실패했지만 나머지로 답변함" 같은
  보조 안내 문자열 목록. 토스트/배너 등 부가 영역에 표시하는 용도로 쓰면 된다
  (없으면 빈 배열).

---

## 9. UI 설계 시 참고할 최소 상태 모델

SSE 기준으로 프론트가 가져야 할 상태는 최소 다음과 같다(기존 구현 예시,
그대로 따를 필요는 없음 — 구조 이해용):

```ts
type Phase = 'idle' | 'connecting' | 'running' | 'streaming' | 'completed' | 'error' | 'aborted'

interface Message {
  role: 'user' | 'assistant'
  text: string
  sources: Source[]
  visualizations: Visualization[]
  warnings: string[]
}
```

이벤트별 전이:
- `agent_start` → `running` (진행 표시: "자료를 찾는 중")
- `tool_start`/`tool_end` → 여전히 `running` (실시간 아니므로 세밀한 진행률로 쓰지 말 것 — "근거 확인 중" 정도의 뭉뚱그린 표시가 적절)
- `sources` → `sources`/`visualizations`/`warnings`를 메시지에 채움(답변 텍스트보다 먼저 옴)
- `delta` → `streaming`, 답변 텍스트 설정
- `done` → `completed`
- `error` → `error`, `stop_reason`에 따라 사용자 메시지 분기

---

## 10. 실제 예시 데이터가 더 필요하면

`backend/docs/rag/phase_8/eval/baseline_dev_records_final.json`의 `records[].sources`가
실제 프로덕션과 동일한 `Source` 스키마의 대량 실측 예시다(용어/뉴스/리포트/공시
등 케이스별로 다양). 단 이 파일은 평가 파이프라인 로그라 `visualizations`,
`broker_opinions`, `execution` 같은 API 응답 전용 필드는 들어있지 않다 — `sources`
구조 참고용으로만 쓰면 된다.
