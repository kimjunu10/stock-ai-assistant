# Phase 6 · 주가 Tool 완료 기록

- 일자: 2026-07-25
- 브랜치: `phase/6-stock-price-tools`
- 범위: 구현·통합·평가까지 한 브랜치에서 연속 수행. **운영 배포·머지는 하지 않음**(최종 PR만).
- 상태: 구현·테스트·실제 API smoke·평가 완료. 사용자 승인 후 배포 대기.

---

## 1. 개요

기존 토스증권 연동(`app/sources/prices.py` `TossInvestClient`)을 재사용해, 단일 Agent 에
읽기 전용 주가 Tool 2개를 추가했다(6→8). 수익률·등락은 **백엔드 한 곳(`StockPriceService`)
에서만 계산**하고, Agent 는 산술하지 않는다. 실제 주가와 증권사 목표주가를 Tool 로 분리했다.

## 2. Tool 입력·출력 계약

### get_stock_prices — 실제 주가(현재가·전일대비·기간 가격)
입력:
| 필드 | 타입 | 설명 |
|---|---|---|
| stock_code | str(6자리) | 필수. 지원 5종목 |
| lookback | str? | "1w"·"2w"·"1m"·"3m"·"6m"·"1y" (정규화 키만) |
| start_date / end_date | str?(YYYY-MM-DD) | 명시 구간 |
| include_daily | bool | 일봉 요약 포함(기본 False) |

출력(ToolResult):
- `data.quote`: price·previous_close·change·change_rate_pct·currency·trading_day·as_of·unit("원")
- `data.period`(lookback/구간 시): start/end_trading_day·start/end_close·change·return_pct·adjusted·unit
- `sources`: SourceRef(source_type="price", publisher="토스증권 Open API", published_at=거래일,
  value_kind="actual", locator={stock_code, interval:"1d", provider:"toss", as_of, …})
- 없으면 `status="no_data"`(대체 금지).

### calculate_event_return — 사건/기간 전후 실제 수익률
입력:
| 필드 | 타입 | 설명 |
|---|---|---|
| stock_code | str(6자리) | 필수 |
| event_date | str?(YYYY-MM-DD) | 사건(뉴스·공시 발표일) 기준 |
| window | str | "1d"·"3d"·"5d"·"10d" (기본 "5d") |
| lookback | str? | event_date 없을 때 기간 수익률 |

출력: `data`에 start/end_trading_day·start/end_close·change·return_pct·currency·adjusted·unit·note
("발표 전후"/"최근 …" — 인과 아님). `sources`: price SourceRef 2건(시작·종료 거래일).

**계산 위치**: `return_pct = (end_close/start_close - 1) * 100`(소수 2자리)는 `StockPriceService`
한 곳에서만. Tool·Agent 는 값을 그대로 인용한다.

## 3. 거래일 처리 규칙

- 기준일이 거래일이면 그대로 사용.
- 휴장일/주말/공휴일이면 **목적에 따라 명시적 스냅**:
  - 기간 시작일: 사용할 수 있는 **첫 거래일**(start 이상, `_snap_on_or_after`).
  - 기간 종료일: 사용할 수 있는 **마지막 거래일**(end 이하, `_snap_on_or_before`).
  - 사건 base: 사건일 당일 또는 **직전 거래일**(발표 시점 가격). 상장 이전 등으로 없으면 직후.
- 선택된 실제 거래일을 결과(start/end_trading_day)에 표시한다.
- 토스는 휴장일 캔들을 주지 않으므로(빈틈), 백엔드가 조회된 일봉 중 조건에 맞는 거래일을 고른다.
- 데이터가 부족하면 `no_data`(다른 날짜·종목 대체 금지).

## 4. 캐시·429 정책

- **30초 메모리 캐시**: `StockPriceService` 계층에서 일봉·현재가를 `(stock_code, earliest,
  adjusted)`/`quote:{code}` 키로 TTL 캐시(`stock_price_cache_seconds=30`). 어댑터의 15초
  통합 캐시와 별개(중복 아님, rate limit 완화 목적).
- **동시 중복 방지**: 캐시 키별 fetch lock(같은 요청 동시 폭주 차단).
- **429 제한 재시도**: `rate_limited` code 에만 제한 재시도(`stock_price_rate_limit_retries=2`)
  + 선형 백오프(`stock_price_rate_limit_backoff_seconds=1.5`, i+1 배). 무제한 재시도 금지.
  그 외 오류는 즉시 전파.
- **200개 경계/페이징**: 토스 일봉 1회 최대 200. 긴 구간은 `nextBefore` 커서로만 확장하되
  `stock_price_max_candle_pages=4`(≈800 거래일)로 상한. 과도한 API 호출 방지.

## 5. 실제 API 검증(소량 smoke, 비밀값 미출력)

정상 2종목(005930·000660):
| 항목 | 결과 |
|---|---|
| 현재가·전일대비 | 정상(005930 252,500원 등, 거래일·as_of 표시) |
| 최근 한 달 수익률(백엔드 계산) | 정상(거래일 스냅 후 시작·종료 종가로 계산) |
| 휴장일 포함 구간 | end=토요일 요청 → 실제 사용 거래일 07-24(금)로 직전 스냅 ✅ |
| 잘못된 종목(999999) | StockPriceError(지원 안 함) 안전 처리 |
| 200 경계/페이징 | 300일 요청→198 거래일(주말 제외), 페이징 정상 |
| 캐시 재호출 | 동일 구간 즉시(캐시 히트) |
| 429 방지 | 백오프·캐시로 연속 호출 최소화 → 발생 없음 |

토스 API 실측 제약(Phase 6-A): 캔들 count 최대 200, 주기 `1d`·`1m` 만, KST(+09:00),
휴장일=빈틈, before 페이징 5년+.

## 6. 평가 결과

주가 평가셋 5종(`docs/rag/phase_5_5/eval/devset.json`, 실제 Agent 실행):
| id | 질문 | 호출 Tool | 결과 |
|---|---|---|---|
| price-current-1 | 현재 주가 | get_stock_prices | ✅ |
| price-return-1 | 최근 한 달 수익률 | get_stock_prices | ✅ (-25.63%, 백엔드 계산) |
| price-not-target-1 | 목표주가 말고 실제 주가 | get_stock_prices | ✅ (리포트 Tool 미호출) |
| price-compare-1 | 목표주가와 실제 주가 비교 | search_research_reports + get_stock_prices | ✅ (값 구분) |
| price-event-1 | 발표일 전후 수익률 | calculate_event_return | ✅ (+24.43%, 인과 아님) |

**확인 기준**: 필요한 주가 Tool 호출 ✅ / 금지된 리포트 Tool 미호출 ✅ / Agent 직접 산술 0 ✅
/ 실제·목표주가 혼동 0 ✅ / no_data 추측 0 ✅ / 인과 단정 0 ✅.
- 회귀(재무-연간·부정제외·리포트·답변불가) 4/4 유지(프롬프트 변경 무해).
- 전체 pytest 288 통과, ruff check·format 통과.
- 단위/통합 테스트: 서비스 16 + Tool 11 + Agent 통합 6 + validator 4.

**참고**: price-compare 에서 검증기가 근거 없는 증권사명 환각 문장을 제거(안전장치 정상 작동).

## 7. 남은 위험

| 위험 | 내용 | 완화 |
|---|---|---|
| rate limit(429) | 장기 구간 페이징 시 연속 호출 | 30s 캐시·백오프·페이지 상한. 발생 시 제한 재시도 |
| 다단계 사건 질문 | "최근 실적 발표 전후"처럼 발표일 미상이면 뉴스·공시로 먼저 찾다 tool 한도 근접 | 발표일이 주어지면 정상. 미상 시 되묻거나 근거 부족 안내 |
| 목표주가 혼입 | 비교 질문에서 증권사명 환각 | validator 가 근거 없는 증권사·목표주가 문장 제거 |
| 5종목 게이트 | 앱 지원 5종목 외 질문 | StockPriceError→안전 처리(범위 밖 안내) |
| IP 허용목록 | 운영 VM IP 가 토스 허용목록에 있어야 함 | 로컬 실측 통과. 배포 시 VM IP 등록 확인(ip_not_allowed→기존 처리) |
| 수정/비수정 혼용 | 전일대비(비수정) vs 기간수익률(수정) | 결과에 adjusted 플래그 명시, 용도별 기준 고정 |

## 8. 운영 배포 절차(승인 후)

1. PR 머지 → CI/CD 로 이미지 `...backend:<sha>` 빌드·배포.
2. 운영 `.env` 에 `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET` 존재 확인(주가 Tool 필수).
   없으면 주가 Tool 은 안전 error 를 반환하고 나머지 QA 는 정상.
3. 운영 VM IP 가 토스 Open API 허용목록에 등록돼 있는지 확인.
4. `AGENT_ENABLED=true` 유지(Phase 5.5 에서 이미 활성). 재시작 후 /docs·agent=true 확인.
5. 운영 smoke: "현재 주가"·"최근 한 달 수익률"·"목표주가 말고 실제 주가"로 주가 Tool 호출 확인.

### 배포 시 필요한 환경변수
- `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET`(기존, 주가 Tool 필수)
- (선택) `STOCK_PRICE_CACHE_SECONDS`(기본 30), `STOCK_PRICE_RATE_LIMIT_RETRIES`(2),
  `STOCK_PRICE_RATE_LIMIT_BACKOFF_SECONDS`(1.5), `STOCK_PRICE_MAX_CANDLE_PAGES`(4)
- 기존 `OPENAI_API_KEY`·`AGENT_ENABLED` 유지.

## 9. Rollback

- `AGENT_ENABLED=false` 는 QA 503(legacy 복귀 아님). 장애 시 flag 를 끄지 말고 **이전 정상
  revision 이미지로 롤백**(`export BACKEND_IMAGE=...:<prev-sha>; docker compose up -d backend`).
- 주가 Tool 만 문제면, 토스 자격증명을 제거하면 주가 Tool 이 안전 error 를 반환하고 나머지
  QA(재무·뉴스·공시·리포트)는 정상 유지된다(부분 degrade). 단, 정식 복구는 이미지 롤백.

## 10. 변경 파일

**신규**
- `app/services/stock_prices.py` — StockPriceService(조회·계산·캐시·429·페이징·거래일 스냅)
- `app/agent/tools/prices.py` — get_stock_prices·calculate_event_return Tool
- `tests/unit/test_stock_price_service.py`(16) · `tests/unit/test_price_tools.py`(11)
- `tests/agent/test_price_agent_integration.py`(6)
- `docs/rag/phase_6/PHASE_6A_PREFLIGHT.md`(사전 조사) · 본 문서

**수정**
- `app/sources/prices.py` — read-only raw fetch 3종 추가(인증·토큰 재사용), 429/404 code
- `app/agent/runtime.py` — Tool 2개 등록(6→8), context.services.prices 배선
- `app/agent/context.py` — ToolServices.prices 추가
- `app/agent/prompts.py` — 실제/목표 구분·산술 금지·인과 금지·문맥 종목 규칙
- `app/agent/validator.py` — price 근거 수집·숫자 검증
- `app/services/agent_qa.py` — StockPriceService 구성·주입
- `app/core/config.py` — stock_price_* 설정
- `scripts/evaluate_agent.py` — prices 주입·required_tools_any 채점
- `docs/rag/phase_5_5/eval/devset.json` — 주가 케이스 5

**불변(재사용만)**: 기존 `TossInvestClient` 인증/토큰/응답 모델, `app/api/routes/stocks.py`.
