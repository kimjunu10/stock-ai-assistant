# Phase 7 결함 — 검색 Tool의 stock_code 자리에 회사명 혼입

- 작성일: 2026-07-26
- 상태: **원인 확정 → 수정·검증 완료(2026-07-26)**
- 발견 경로: 실사용자 톤 UI 시뮬레이션(20문, `/qa/stream` 그대로 재현) 중 발견.

---

## 1. 증상

문맥 종목코드(`stock_code=005930`)를 정상적으로 넘겼는데도, 다음처럼 회사 약칭 +
검색 주제가 함께 있는 질문에서 검색계 Tool 이 실패하고 Agent 가 "종목 코드를
알려달라"고 되물었다.

| 질문(stock_code=005930 전달) | 이전 결과 |
|---|---|
| "삼성 HBM 관련 최근 뉴스 알려줘" | search_news status=None → "종목 코드 알려달라" |
| "삼성 HBM 관련 공시 있어?" | search_disclosures status=None |
| "삼성 HBM 관련 증권사 리포트 있어?" | search_research_reports status=None |

- "삼성전자"(정식명)일 때는 우연히 정상, "삼성"(약칭)에서 재현.
- "하이닉스"·재무/주가 Tool 은 정상 → 특정 Tool·특정 약칭에서 유도되는 결함.

## 2. 근본 원인 (로깅으로 확정)

Tool 진입 인자를 로깅한 결과:

```
search_news stock_code='삼성'  query='HBM'  ctx_stock='005930'
```

- Agent 가 **stock_code 자리에 회사명 '삼성'** 을 넣었다(사용자가 준 문맥 코드
  `005930` 은 `runtime.context.stock_code` 에 있는데 무시).
- `SearchNewsInput.stock_code` 는 `^[0-9]{6}$` 패턴이라 '삼성' 은 **검증 실패**.
- 검증 예외 → `ToolErrorMiddleware` 가 안전 메시지로 감싸지만 ToolResult payload 가
  없어 **tool status 가 None** 으로 남고, Agent 는 "종목 코드 필요"로 되물었다.

배경: 시스템 프롬프트·Tool docstring 어디에도 **stock_code 가 6자리 숫자이며
문맥 코드를 써야 한다**는 안내가 없었다. 검색 주제(query)가 강조되면서 Agent 가
회사명을 종목 식별자로 오인했다.

## 3. 수정 (docstring 보강 + 안전 폴백, 2층)

docstring 만으로는 100% 못 막으므로 **결정론적 폴백**을 함께 넣었다.

### 3.1 안전 폴백 — `_resolve_stock_code`(app/agent/runtime.py)
```
stock_code 가 6자리 숫자가 아니면
  → runtime.context.stock_code(사용자가 UI 문맥으로 준 코드)가 6자리면 그것으로 폴백
  → 그것도 없으면 원값 유지(입력 스키마가 안전 오류로 처리)
```
- 질문 문자열을 파싱하거나 회사명→코드 매핑을 하지 않는다(키워드 라우터·하드코딩 아님).
- 검색계 3개 Tool(search_news / search_disclosures / search_research_reports)에 적용.

### 3.2 docstring 보강
세 Tool 의 docstring 에 `stock_code: 항상 6자리 숫자 코드. 문맥 종목코드를 쓰고
회사명을 넣지 말 것` 을 명시.

## 4. 검증

### 4.1 수정 후 실사용 재현
| 질문(005930 전달) | 결과 |
|---|---|
| 삼성 HBM 뉴스 | search_news **ok** |
| 삼성 HBM 공시 | search_disclosures **ok** |
| 삼성 HBM 리포트 | search_research_reports **ok** |

### 4.2 단위 테스트(tests/agent/test_agent_runtime.py)
- 유효 코드는 그대로 유지.
- 회사명·빈 문자열 → 문맥 코드로 폴백.
- 문맥도 없으면 원값 유지(회사명→코드 매핑 안 함).

### 4.3 회귀
- pytest **313 passed**(+3), ruff check·format 통과.
- 실사용 UI 시뮬레이션 20문 재실행: error 이벤트 0, 내부정보 노출 0, SSE 순서 정상.

## 5. 실사용 UI 시뮬레이션 요약(20문, `/qa/stream`)

실제 사용자 톤(구어·줄임말·오타·모호·함정)으로 UI 경로를 그대로 재현했다.

정상 동작 확인:
- 구어/줄임말: "삼전 어제 뭐 뉴스 없냐", "삼전 지금 얼마임?", "삼전 작년 영업이익" → 정상.
- 오타/약칭 용어: "per이 뭐야", "pbr 이란게 먼가요" → term 정의 정상.
- 복합: "지금 상황 핵심만 정리" → 재무+뉴스(+리포트) 다중 Tool.
- "목표주가 vs 실제 주가 비교" → reports + prices, 실제/전망 구분.
- 제외 조건: "호재만, 실적은 빼고" → 뉴스 + 제외 경고.

안전 처리(정상):
- "삼성바이오로직스 현재가" → 지원 5종목 밖 → get_stock_prices error(대체 안 함).
- "삼성전자 내일 주가 오를까?" → Tool 미호출, 예측 불가 안내(예측·인과 단정 없음).
- "대통령이랑 회담…" → 종목 뉴스로 매칭되는 사건 없으면 no_data(허위 생성 없음).

전 케이스: error 이벤트 0, 내부 추론·전체 Tool 인자·비밀값 노출 0,
SSE 순서 agent_start→tool_start→tool_end→sources→delta→done.

## 6. 미수행
운영 배포·자동 머지·Phase 8 진행 안 함.
