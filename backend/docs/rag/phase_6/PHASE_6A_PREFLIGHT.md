# Phase 6-A · 주가 Tool 사전 조사(Preflight)

- 일자: 2026-07-25
- 범위: **조사·설계만.** 구현·Agent Tool 등록·운영 배포는 하지 않는다.
- 브랜치: `phase/6-a-stock-price-preflight`
- 대상 질문(Phase 6 목표): 현재 주가 / 기간 수익률 / 사건 전후 수익률 / 목표주가 아닌 실제 주가 이동 / 휴장일 기준 처리.

---

## 1. 기존 주가 코드 전수 조사 결과

### 1.1 어댑터 — `app/sources/prices.py`
토스증권 Open API 동기 클라이언트. **재사용 대상이며 복제 금지.**

- `TOSS_OPEN_API_BASE_URL = "https://openapi.tossinvest.com"` (`prices.py:23`)
- `SUPPORTED_STOCK_CODES` = 5종목(005930·000660·034020·042660·005380) (`prices.py:24`) — **앱 레벨 게이트**(토스 API 자체 제약 아님, 4절 실측 참고).
- `TossApiError(RuntimeError)` `.code` 속성(`ip_not_allowed` / `auth_failed` 등) (`prices.py:27-32`).
- 클래스 `TossInvestClient`:
  - 공개 메서드: `get_stock_market_overview()`(5종목 일괄 현재가), `get_stock_market_data(stock_code, candle_count=130)`(현재가+일봉+1분봉+호가+가격제한 통합), `get_stock_info()`(종목 마스터+DART 개황).
  - 인증: `POST /oauth2/token` `grant_type=client_credentials` (`prices.py:320-368`). 토큰 인메모리 저장, `expires_at > now+60`이면 재사용, 401 시 강제 무효화 후 1회 재시도.
  - 요청 래퍼 `_request_json` (`prices.py:370-401`): 최대 2회(401 재시도 1회), `timeout=self._timeout_seconds`. **지수 백오프·명시적 rate-limit 대기 없음.**
  - 캐시: 인스턴스 내부 TTL 캐시(`market_data_cache_seconds` 기본 **15초**), 종목별 fetch lock(thundering herd 방지), `_previous_close_cache`, `_stock_info_cache`.

### 1.2 응답 모델 — `app/schemas/prices.py`
`CamelModel`(snake↔camel). `Candle`, `StockQuote`, `OrderbookLevel`, `StockMarketData`, `StockListQuote`, `StockMarketOverview`, `StockCompanyProfile`.
- `Candle`: `time:str, open/high/low/close:float, volume:int`.
- **주의**: `Candle.time`은 `str`(일봉은 `YYYY-MM-DD`, 분봉은 ISO 타임스탬프). SourceRef 붙이려면 이 문자열 기준일을 그대로 쓴다.

### 1.3 호출부 — `app/api/routes/stocks.py`
- `get_toss_client()` `@lru_cache(maxsize=1)` 싱글턴 → 프로세스당 토큰·캐시 1개 공유 (`stocks.py:32-42`).
- 엔드포인트: `GET /stocks/market-overview`, `GET /stocks/{code}/market-data`, `GET /stocks/{code}/company-profile`.
- 에러 매핑 `_market_data_error`: `ip_not_allowed`→503, 그 외→502.
- `SUPPORTED_STOCK_CODES`는 `financials.py`·`disclosures.py`·`clusters.py`에서도 상수로 재사용.

### 1.4 테스트 — `tests/unit/test_toss_prices.py`
`FakeSession` 주입식 어댑터 단위 테스트 8종(정규화·캐시 히트·전일종가 선택·IP 차단·DART 병합). **라우트/통합 테스트·Agent Tool 테스트는 없음.**

### 1.5 설정 — `app/core/config.py`
- `toss_client_id`(env `TOSS_CLIENT_ID`), `toss_client_secret`(env `TOSS_CLIENT_SECRET`)
- `toss_request_timeout_seconds=15.0`, `toss_market_data_cache_seconds=15`
- `validate_toss_market_data()` 자격증명 존재 검증. `.env.example`에 두 키 이름만(값 없음).

### 1.6 인증·실사용 경로
- 인증 방식: **OAuth2 client_credentials**(토스 WTS에서 발급한 client_id/secret). 토큰 만료 `expires_in`(실측 86399초≈24h), 60초 안전 마진으로 사전 갱신.
- 실사용 경로: 현재는 `/api/stocks/*` 프런트용 3개 라우트만. **QA/Agent 경로에는 주가 연동이 전혀 없음**(Phase 6에서 신규).

---

## 2. 토스증권 API 실측 결과 (소량 실제 호출, 비밀값 미출력)

로컬 Mac에서 `app.sources.prices` 재사용 + 저수준 GET로 검증. 자격증명은 마스킹(len/head/tail)만 출력.

| 확인 항목 | 결과 |
|---|---|
| OAuth 토큰 | `POST /oauth2/token` → 200, `expires_in=86399`(≈24h) |
| 현재가 `/api/v1/prices?symbols=` | 200. 필드 `symbol,timestamp,lastPrice,currency`. 복수 심볼 콤마 구분 |
| 일봉 `/api/v1/candles interval=1d` | 200. 필드 `timestamp,openPrice,highPrice,lowPrice,closePrice,volume,currency` |
| 분봉 `/api/v1/candles interval=1m` | 200. 당일 1분봉, ISO 타임스탬프 |
| 호가 `/api/v1/orderbook` | 200. `asks`/`bids` 각 10호가, `timestamp,currency` 포함 |
| 가격제한 `/api/v1/price-limits` | 200. `upperLimitPrice,lowerLimitPrice` |
| **캔들 count 최대** | **200** (300·500 요청 시 `400 invalid-request`, 제약 `{min:1,max:200}`) |
| **지원 주기** | **`1m`, `1d` 만** (1w·1M·5m·60m → `400`, `allowedValues:['1m','1d']`) |
| **과거 이력 깊이** | `before` 페이지네이션으로 최소 **5년+**(2021-08까지 확인). count=200당 약 10개월. 응답 newest-first, `nextBefore` 커서 제공 |
| **rate limit** | **실재.** 연속 호출 시 `429 rate-limit-exceeded`. 호출 간 ~2초 sleep으로 회피됨 |
| 잘못된 종목 `/prices` | 200 + 빈 `result:[]` (에러 아님) |
| 잘못된 종목 `/candles` | `404 stock-not-found` |
| 앱 미지원 실제 종목(373220) | `/prices` 200 정상 → 토스는 5종목 외도 지원. **5종목 제한은 앱 코드 게이트** |
| 날짜·시간 기준 | 모든 타임스탬프 `+09:00`(KST) 명시. 조회일(07-25 토)과 무관하게 데이터는 직전 거래일(07-24 금) |
| 휴장일 응답 | 별도 에러 없음. 휴장일엔 그 날짜 캔들이 **아예 없음**(빈틈). 현재가 `timestamp`는 마지막 체결일 기준 |
| 상장 전·데이터 없음 | 해당 구간 캔들이 비어서 반환(에러 아님). count보다 적게 올 수 있음 |
| timeout/재시도 | 어댑터는 timeout=15s, 401 재시도 1회. **429·5xx 백오프는 없음** → Phase 6에서 보강 필요 |
| 토큰 만료 | 24h, 60s 마진 사전 갱신. 별도 처리 불필요 |

**Phase 6 관점 핵심 제약 3가지**
1. **주기는 1d·1m 만** → "최근 한 달 수익률"은 일봉 2점(시작·종료 거래일)으로 계산. 주봉/월봉 집계 불가.
2. **캔들 200개 상한 + rate limit** → 장기 구간은 `before` 페이징 필요하고 호출 간격 제어(백오프) 필수.
3. **휴장일 = 데이터 없음(빈틈)** → 기준일이 휴장이면 "직전 거래일"로 스냅해야 하며, API가 대체값을 주지 않음(백엔드가 선택).

---

## 3. Phase 6 Tool 설계안

원칙(SPEC §7.7·§8.7, PLAN Phase 6 체크리스트 준수):
- **수익률·등락은 전부 백엔드가 계산. Agent는 산술 금지.** Tool은 계산된 structured fact + SourceRef만 반환.
- 기존 `app/sources/prices.py`·`app/schemas/prices.py` 재사용, **복제 금지**.
- 읽기 전용. `no_data`와 `error` 구분. 원문/DB 스키마 미노출. 인과 단정 금지.
- 신규 Tool 파일(예정): `app/agent/tools/prices.py`(SPEC:842 계획 경로).

### 3.1 `get_stock_prices`
현재가 또는 지정 기간의 일봉/등락을 조회한다(계산 포함).

**입력 스키마(안)**
```
GetStockPricesInput:
  stock_code: str                 # 필수. SUPPORTED_STOCK_CODES 검증
  as_of: date | None = None       # 기준일(미지정 시 최신 거래일)
  lookback: str | None = None     # "1d"|"1w"|"1m"|"3m"|"6m"|"1y" 등 정규화 키워드(자유서술 금지)
  # start/end 직접 지정 대신 정규화된 lookback 키워드만 허용 → Agent 자유 파싱 차단
```
- 기간 미지정 → 현재가(+전일 대비 등락률)만.
- lookback 지정 → 시작 거래일·종료 거래일 종가와 **기간 수익률(백엔드 계산)**.

**반환 데이터(안)**
```
StockPricesResult:
  stock_code
  as_of_trading_day: date         # 실제 사용된 거래일(휴장 스냅 반영)
  current: { price, previous_close, change, change_rate }   # 전일 대비(백엔드 계산)
  period: {                       # lookback 있을 때만
    start_trading_day, end_trading_day,
    start_close, end_close,
    return_pct                    # 백엔드 계산
  } | None
  status: "ok" | "no_data"
  sources: [SourceRef(source_type="price", publisher="토스증권 Open API",
                      published_at=거래일, locator={trading_day, interval:"1d", adjusted})]
```

### 3.2 `calculate_event_return`
특정 사건일(뉴스/공시 발표일) 전후 실제 주가 변화율을 계산한다.

**입력 스키마(안)**
```
CalculateEventReturnInput:
  stock_code: str
  event_date: date                # 사건 기준일(뉴스/공시 발표일)
  window: str = "±5d"             # 정규화 키워드("±1d"|"±5d"|"pre5_post5" 등)만 허용
  # source_id: str | None         # 연결된 뉴스/공시 source_id(있으면 근거로 첨부)
```

**반환 데이터(안)**
```
EventReturnResult:
  stock_code
  event_date
  base_trading_day: date          # event_date가 휴장이면 직전 거래일로 스냅
  pre_close: { trading_day, close }
  post_close: { trading_day, close }
  return_pct                      # 백엔드 계산(post/pre - 1)
  status: "ok" | "no_data"
  sources: [SourceRef(source_type="price", ...), (있으면) 연결 뉴스/공시 SourceRef]
  note: "발표 이후 변화(인과 아님)"   # 표현 가드
```

### 3.3 공통 규칙

**거래일 선택 규칙**
- 기준일이 거래일이면 그대로 사용.
- 휴장일/주말/공휴일이면 **직전 거래일로 스냅**(미래일로 당기지 않음). API가 휴장일 캔들을 주지 않으므로, 조회된 일봉 중 `date <= 기준일`의 최신 항목을 선택(기존 `_previous_close_from_raw_candles`와 동일한 "완료된 캔들 선택" 패턴 재사용).
- 사건 전후는 event_date 스냅 후, pre=스냅 거래일 종가, post=window 만큼 뒤의 거래일 종가.

**수익률 계산 규칙(백엔드 전담)**
- 기간 수익률 = `(end_close / start_close - 1) * 100`, 소수 2자리.
- 전일 대비 = 기존 어댑터의 비수정 전일종가 기준(`adjusted=false` 참조 캔들)을 그대로 사용.
- 기간 수익률은 **수정주가(adjusted=true)** 사용(배당·액면 반영 일관성). 두 기준을 결과에 `adjusted` 플래그로 명시.
- Agent에는 **완성된 숫자 + 단위(%) + 기간(거래일 범위)** 만 전달 → Agent가 재계산할 입력을 주지 않음.

**source metadata**
- `SourceRef(source_type="price")`, `publisher="토스증권 Open API"`, `published_at=거래일`, `locator={trading_day, interval, adjusted, window?}`.
- validator가 "숫자 존재·단위·기간" 검증 시 이 SourceRef의 값과 대조.

**30초 cache 적용 위치**
- 기존 어댑터 인스턴스 캐시는 **15초**(`toss_market_data_cache_seconds=15`) → Phase 6에서 **30초로 설정 상향**(코드 신규 캐시 추가 아님).
- 단, 어댑터 캐시는 "현재가 통합 데이터" 단위. **기간/사건 조회용 일봉 캐시는 별도 필요** → Tool 계층에서 `(stock_code, interval, before-cursor)` 키의 30초 TTL 캐시를 신규로 얇게 추가(어댑터 캐시와 중복 아님). rate limit 완화 목적.

**데이터 없음 처리**
- 해당 거래일/구간 캔들 없음 → `status="no_data"`, 다른 기간으로 **대체 금지**(SPEC:344). Agent는 "확인 불가"로 답.
- 잘못된 종목 → `/candles` 404 또는 `/prices` 빈 결과 → `no_data`(에러 아님으로 정규화).

**Agent가 직접 산술하지 못하게 하는 방법**
1. Tool 입력에 원시 시계열을 넣지 않음(기간은 정규화 키워드만).
2. Tool 반환에 **계산 완료된 최종 수치**만 포함, 개별 캔들 배열은 반환하지 않음(또는 최소 2점만).
3. system prompt: "수익률·등락은 Tool이 준 값만 인용, 직접 계산 금지".
4. validator: 답변 내 수치가 Tool 결과 값과 일치하는지 대조, 불일치 시 제거/경고(숫자 임의 수정 금지).

---

## 4. 5개 예시 질문 지원 가능 여부

| # | 질문 | 지원 | Tool·경로 | 비고 |
|---|---|---|---|---|
| 1 | 삼성전자 현재 주가 알려줘 | ✅ | `get_stock_prices`(기간 없음) | 현재가+전일대비. 실측 정상 |
| 2 | 삼성전자 최근 한 달 수익률 | ✅ | `get_stock_prices(lookback="1m")` | 일봉 2점 종가로 백엔드 계산. 월봉 없어도 무방 |
| 3 | 이 뉴스 발표 전후로 주가가 얼마나 움직였어? | ✅(조건부) | `calculate_event_return` | event_date는 뉴스 source의 발표일에서 확보. window 정규화 필요 |
| 4 | 목표주가 말고 실제 주가가 얼마나 움직였어? | ✅ | `get_stock_prices`/`calculate_event_return` | **research_reports.target_price 경로와 분리** 필수. "목표주가"는 리포트 Tool, "실제 주가"는 price Tool. 부정/대조 케이스 |
| 5 | 휴장일을 기준일로 지정하면? | ✅ | 거래일 스냅 규칙 | event_date/as_of가 휴장이면 **직전 거래일로 스냅**하고, 응답에 실제 사용 거래일 명시. API는 휴장일 캔들을 주지 않으므로 백엔드가 스냅 담당. 미래일로 당기지 않음 |

**주의**: 질문 4는 회귀 필수 케이스(GUIDE:451, EVAL:162). 목표주가(리포트)와 실제주가(price Tool)를 섞으면 실패. Tool 분리 + system prompt 가드로 방지.

---

## 5. 변경 예정 파일 (Phase 6 구현 시 — 지금은 미구현)

| 파일 | 변경 | 비고 |
|---|---|---|
| `app/agent/tools/prices.py` | **신규** | 두 Tool 정의. `TossInvestClient` 재사용 |
| `app/services/`(신규 price service) 또는 tools 내 helper | **신규** | 거래일 스냅·수익률 계산·30s 캐시. 어댑터 위 얇은 계층 |
| `app/agent/agent.py`(create_agent tools 목록) | 수정 | 두 Tool 등록. `ToolCallLimitMiddleware`·retry 적용 |
| `app/agent/validator.py` | 수정 | price 수치·단위·기간 검증, source_type="price" 처리 |
| `app/schemas/` (SourceRef/price fact) | 소폭 수정 | `source_type="price"`는 SPEC:280 이미 예약. price fact 스키마 추가 여지 |
| `app/core/config.py` | 수정 | `toss_market_data_cache_seconds` 15→30(또는 Tool 캐시 별도 설정) |
| system prompt | 수정 | "수익률 직접 계산 금지·인과 단정 금지·이후/때문에 구분" |
| **불변**: `app/sources/prices.py`, `app/schemas/prices.py`, `app/api/routes/stocks.py` | 재사용만 | 복제·수정 없이 그대로 사용 |

## 6. 테스트 계획 (Phase 6 구현 시)

- 단위: 거래일 스냅(휴장일→직전 거래일), 기간 수익률 계산, 사건 전후 수익률, no_data(잘못된 종목·빈 구간), 캐시 히트, rate-limit 백오프.
- Tool 계약: 반환에 SourceRef(source_type="price") 포함, 원시 캔들 배열 미노출, 계산값만.
- 검증 게이트: 답변 수치가 Tool 값과 일치, 불일치 시 validation_error(숫자 임의 수정 0).
- 회귀: "목표주가 말고 실제 주가"(질문4)에서 target_price 미혼입.
- Fake 세션 재사용(`test_toss_prices.py` 패턴), 실제 API는 테스트에서 호출 안 함.
- 평가셋 추가(EVAL Phase 6: 주가 조회 성공률·거래일 기준 계산·기간 수익률·인과 과도 단정률).

## 7. 예상 위험

| 위험 | 내용 | 완화 |
|---|---|---|
| **rate limit(429)** | 장기 구간 `before` 페이징 시 연속 호출로 429 실측됨 | Tool 계층 백오프+30s 캐시, count 상한 인지, 필요한 최소 구간만 조회 |
| **주기 제약(1d·1m)** | 주봉·월봉 없음 | 기간 수익률은 일봉 2점으로 계산(집계 불필요), 문제 없음 |
| **휴장일 처리 오류** | 기준일 휴장 시 잘못된 거래일 선택 위험 | "직전 거래일 스냅" 규칙 + 실제 사용 거래일 응답 명시, 단위 테스트 |
| **수정주가 vs 비수정** | 전일대비(비수정)와 기간수익률(수정) 혼용 시 불일치 | 결과에 `adjusted` 플래그 명시, 용도별 기준 고정 |
| **목표주가 혼입** | 질문4에서 리포트 target_price를 실제주가로 오인 | Tool 분리 + system prompt + 회귀 테스트 |
| **인과 단정** | "뉴스 때문에 하락" 생성 | note 가드 + system prompt("이후"만 허용) + EVAL 과도단정률 모니터 |
| **IP 허용목록** | 운영 VM IP만 토스 허용목록에 있을 수 있음 | 로컬 실측은 통과했으나, 운영 배포 시 VM IP 등록 상태 재확인(ip_not_allowed→503 기존 처리) |
| **5종목 게이트** | 앱은 5종목만, 사용자가 타 종목 질문 시 no_data | 현행 유지(범위 밖 안내), 확장은 별도 결정 |

---

## 8. 결론

- Phase 6 두 Tool(`get_stock_prices`, `calculate_event_return`)은 **기존 토스 연동을 재사용해 구현 가능**하며, 5개 예시 질문 모두 설계상 지원 가능(질문 3·4·5는 거래일 스냅·Tool 분리·인과 가드 전제).
- 실측으로 확인한 실제 제약(캔들 200 상한, 1d·1m 주기, 429 rate limit, 휴장일=빈틈, KST)을 설계에 반영함.
- **본 문서는 조사·설계까지만.** 구현·Agent Tool 등록·30초 캐시 적용·운영 배포는 **사용자 승인 후 Phase 6-B에서 진행**(PLAN:521 자동 진행 금지).
