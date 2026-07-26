# Phase 7 UI 데이터 계약

- 작성일: 2026-07-26
- 원칙: Agent 라우팅/Tool 선택/검색은 변경하지 않고, 이미 실행된 ToolResult의 검증된
  `data`와 `sources`만 공개 UI view model로 변환한다.

## 1. 변경 이유

기존 Agent는 내부적으로 ToolResult를 수집했지만 API route가 `sources=[]`를 반환하고
구조화 `data`를 버렸다. 자연어 답변을 프런트에서 다시 파싱하지 않고 카드와 차트를
만들려면 최소 typed payload가 필요하다.

## 2. 요청

실제 FastAPI 계약은 snake_case다.

```json
{
  "question": "이 리포트에서 목표주가를 내린 이유가 뭐야?",
  "stock_code": "005930",
  "context_source_type": "research_report",
  "context_source_id": "report-7",
  "document_id": "document-7",
  "report_page": 3,
  "conversation_id": "optional",
  "history": [],
  "stream": true
}
```

- `stock_code`: 현재 종목 화면/선택 종목
- `context_source_type`: `news_event | dart_document | structured_disclosure |
  research_report | null`
- `context_source_id`: 현재 뉴스 사건/공시/리포트 식별자
- `document_id`, `report_page`: 현재 문서/페이지가 실제로 있을 때만
- `history`: 스키마 호환을 위해 받지만 현재 서버 대화 상태에는 사용하지 않음
- `conversation_id`: RuntimeContext로 전달하지만 checkpointer는 아직 없음

## 3. 공개 Source

기존 `SourceRef`에서 다음 필드만 복사한다.

```json
{
  "source_id": "price:005930:2026-07-24",
  "source_type": "price",
  "title": "005930 주가 · 2026-07-24",
  "publisher": "토스증권 Open API",
  "published_at": "2026-07-24",
  "page": null,
  "url": null,
  "value_kind": "actual",
  "locator": {"provider": "toss"}
}
```

허용 source type:

- `financial`
- `term`
- `news_event`
- `dart_document`
- `structured_disclosure`
- `research_report`
- `price`

프런트는 실제 `url`이 `http/https`일 때만 링크를 제공한다. URL이 없으면 임의 주소를
만들지 않는다. private Storage 경로나 raw Tool exception은 포함하지 않는다.

## 4. Visualization

```json
{
  "type": "price_snapshot",
  "title": "실제 주가",
  "data": {},
  "source_ids": ["price:005930:2026-07-24"]
}
```

허용 enum(실제 생성 여부 표기, 2026-07-26 마무리 기준):

- `news_cards`(생성): 검증된 뉴스 목록, 조회 기간, 원문 링크. item에 `sentiment`
  (호재/악재/중립, 사건 조회 경로에서만), `stock_code` 포함(있을 때만 배지 렌더).
- `price_snapshot`(생성): 단일 현재가/기간 요약 카드
- `price_line`(생성): 실제 거래일 점. UI 전용 `daily_full`(최대 60거래일) 우선, 없으면
  요약 `daily`(6점). 프런트는 값을 재계산하지 않는다.
- `event_return`(생성): 발표 전/후 거래일·가격·백엔드 계산 수익률
- `broker_targets`(생성): `target_price_status=stated`인 증권사 목표주가
- `financial_series`(생성): DART 공식 재무값
- `disclosure_metrics`(생성): 구조화 공시 핵심 값
- `event_timeline`(생성): 뉴스+공시가 함께 조회된 경우에만 발표시각 최신순 병합
- `term_definition`(생성): 금융용어 정의
- `financial_comparison`(**미생성 — 데이터 부족**): 실제/전망 실적 병렬 비교. 리포트
  Tool이 추정 실적을 구조화된 값으로 반환하지 않아 현재 생성 경로 없음. 필요한 계약은
  §"미지원 시각화" 참조. type은 스키마 enum에만 남겨 두되 payload는 만들지 않는다.

### event_timeline payload

```json
{
  "type": "event_timeline",
  "title": "관련 사건 타임라인",
  "data": {
    "events": [
      {"kind": "news|disclosure", "title": "...", "at": "2026-07-25T09:00:00+09:00",
       "source_id": "...", "publisher": "...", "url": "https://... (뉴스만, 있을 때)"}
    ]
  },
  "source_ids": ["..."]
}
```

같은 답변에서 뉴스와 공시가 **둘 다** ok일 때만 만든다(단일 종류면 각자 카드). 확정된
사건만 쓰고 발표시각 최신순으로 정렬한다(최대 12건). 새 조회·값 재계산은 없다.

### 미지원 시각화와 필요한 백엔드 계약

`financial_comparison`(실제 vs 전망 실적 비교)은 데이터가 없어 지원하지 않는다.
실제 실적은 DART `financials`로 있으나, 증권사 리포트 Tool은 목표주가만 구조화하고
추정 매출·영업이익·EPS 등 전망 재무수치를 구조화된 값으로 반환하지 않는다
(`table_value_kinds`는 값이 아닌 카운트). 지원하려면 리포트 파서가 추정 실적 표를
항목·기간·값(`forecast_financials`)으로 구조화해 반환하는 백엔드 계약이 필요하다.
그 전까지는 지원한다고 표시하지 않고, 빈/환각 차트를 만들지 않는다.

### 출처 이동(리포트·공시)

- 공시(`dart_document`): `rcept_no`가 있으면 DART 공식 공개 뷰어 URL을 `url`에 실어
  새 탭 이동. 비공개 경로·signed URL은 만들지 않는다.
- 리포트(`research_report`): 원문 URL이 없으므로 `locator.evidence`(검증된 근거 문장),
  `locator.target_price`(stated만), `locator.investment_opinion`을 실어 클릭 시 인라인
  근거 보기를 제공한다(내부 근거 보기).

규칙:

1. `status=ok`이고 SourceRef가 한 건 이상일 때만 만든다.
2. `source_ids`가 비면 프런트도 다시 거부한다.
3. 자연어 답변/질문을 파싱하지 않는다.
4. 가격/수익률/재무/목표주가를 프런트에서 재계산하거나 보정하지 않는다.
5. 차트 좌표 정규화는 표시 처리일 뿐 값 계산이 아니다.
6. 알 수 없는 type은 안전하게 무시한다.
7. `no_data`와 `error`는 빈 차트를 만들지 않고 경고/오류 UX로 보낸다.

### `news_cards` 예시

```json
{
  "type": "news_cards",
  "title": "최근 뉴스",
  "data": {
    "date_from": "2026-07-24",
    "date_to": "2026-07-26",
    "items": [
      {
        "source_id": "news-1",
        "title": "기사 제목",
        "snippet": "검증된 검색 결과의 요약",
        "publisher": "언론사",
        "published_at": "2026-07-25T09:00:00+09:00",
        "url": "https://example.com/article"
      }
    ]
  },
  "source_ids": ["news-1"]
}
```

`최근` 뉴스의 기본 계약은 KST 요청일 기준 오늘부터 2일 전까지다. 기간 내 결과가
없을 때는 더 오래된 뉴스를 카드에 섞지 않는다. 프런트는 URL을 다시 `http/https`로
검증하며, 뉴스 카드에 포함된 Source는 하단 출처 카드에서 중복 표시하지 않는다.

## 5. SSE

```text
agent_start
→ (tool_start → tool_end)*
→ sources {sources, visualizations, warnings}
→ delta {text}
→ done {stop_reason, model_calls, tool_calls, visualizations, warnings}
```

- Tool 진행 이벤트는 name/status만 공개한다.
- Tool 전체 인자, 원시 payload, 내부 추론, 시스템 프롬프트는 공개하지 않는다.
- 현재 서버는 동기 Agent `invoke` 완료 후 이벤트를 순서대로 내보낸다. 따라서 계약은
  SSE지만 Tool 실행 중간/모델 토큰 단위의 진정한 실시간 전송은 아니다.
- 프런트는 fetch stream + AbortController로 연결하며 CRLF/multi-line data를 처리한다.

## 6. 호환성

`QaResponse.sources`, `visualizations`, `warnings`는 optional/default empty 확장이다.
기존 응답 필드는 유지한다. Agent Tool 선택, 프롬프트, 검색 알고리즘, DB schema는
최초 UI 연결 시 변경하지 않았다. 이후 서버 KST 시간 컨텍스트와 재무 Tool의 최신
보고기간 선택 계약을 추가했으며 API 응답 스키마는 그대로 유지한다. 상세 변경 이력은
`PHASE_7_CHANGELOG.md`에 기록한다.
