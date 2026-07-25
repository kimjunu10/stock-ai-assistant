# Phase 7 결함 분석 — "어제 …" 뉴스 질문에서 search_news 오류

- 작성일: 2026-07-26
- 상태: **원인 확정 → 수정·검증 완료(2026-07-26)**
- 증상 화면: "삼성전자 어제 악재 이었음?" → "일시적인 오류가 발생해 악재 여부를 확인할 수 없습니다."

---

## 1. 증상 (실측)

실제 운영 코드(로컬 `/api/qa`)로 8개 Tool 카테고리를 호출한 결과, **뉴스만** 실패한다.

| 질문 | 호출 Tool | 결과 |
|---|---|---|
| 삼성전자 최근 실적 | get_financial_facts | ✅ ok |
| PBR이 뭐야 | lookup_financial_term | ✅ ok |
| 삼성전자 최근 공시 | search_disclosures | ✅ ok |
| 삼성전자 목표주가 | search_research_reports | ✅ ok |
| 삼성전자 현재 주가 | get_stock_prices | ✅ ok |
| 삼성전자 **최근 호재** 뉴스 | search_news | ✅ ok |
| 삼성전자 **어제** 악재 이었음? | search_news | ❌ error |
| 삼성전자 **어제** 무슨 일 있었어? | search_news | ❌ error |
| **어제** 삼성전자 나쁜 소식 있었어? | search_news | ❌ error |

→ "뉴스 기능 전체 고장"이 아니라 **"어제/특정 시점"류 뉴스 질문에서만** 재현된다.

## 2. 근본 원인 (스택 추적으로 확정)

`sanitize_exception`이 실제 예외를 숨기고 있어(설계상 정상), 임시 로깅으로 실제 예외를 잡았다.

```
run_search_news
  └ HybridRetriever.search
      └ UpstageEmbedder.embed_query(question)
          └ POST https://api.upstage.ai/v1/embeddings
              → 400 Bad Request
              body: "'$.input' is invalid ..." (Upstage)
              inputs=['']        ← 빈 문자열을 임베딩에 보냄
```

Tool 진입 인자를 로깅한 결과(같은 임시 로깅):

```
search_news args: query=''    relative_period='yesterday'  → error   (×3, 매번 재현)
search_news args: query='삼성전자' relative_period='today'  → no_data (정상)
```

### 정리
1. Agent가 `search_news`를 호출할 때 **검색어 `query`를 빈 문자열(`''`)로 넘긴다.**
2. `HybridRetriever.search`는 이 빈 `query`를 그대로 Upstage 임베딩에 전달한다.
3. Upstage 임베딩 API는 **빈 input을 거부(400)** 한다.
4. `run_search_news`가 이 예외를 잡아 `error`를 반환 → UI에 "일시적인 오류".

## 3. "검색어가 빌 수 있나?" — 왜 비는가 (핵심)

사용자 질문 "삼성전자 어제 악재 이었음?"은 그 자체로 완전한 검색어다. 문제는 이 문장이
Tool의 여러 인자로 **분해**되어 전달된다는 점이다.

```
search_news(
    stock_code = "005930",       ← 채워짐
    query      = ""              ← 비워짐  ★결함
    relative_period = "yesterday" ← 채워짐
)
```

**왜 하필 "어제(yesterday)"일 때만 비는가:**

- Tool 시그니처: `query: str` 은 **필수 인자**다(Optional 아님).
- 그런데 docstring이 `relative_period`의 사용법만 상세히 설명하고,
  **`query`에 무엇을 넣어야 하는지는 한 줄도 설명하지 않는다.**
- 그 결과 Agent는 "어제"라는 시간 조건이 강한 질문에서
  "시간 필터(relative_period)만으로 충분하다"고 판단하고,
  필수 필드인 `query`는 형식만 만족시키려 **빈 문자열**로 채운다.
- 반대로 "최근 호재"처럼 시간 신호가 약하면 `query`에 "삼성전자"/"삼성전자 호재"를 채워 정상 동작한다.

→ 즉 **모델의 무작위 실수가 아니라, Tool 계약(설계)이 유도한 재현되는 결함**이다.
   "yesterday" 계열에서 100% 재현된다.

## 4. 왜 이 버그가 지금까지 안 잡혔나

- Phase 7 Changelog의 실제 Agent smoke는 `어제 삼성전자 호재 있었음?`으로
  `search_news status ok`를 확인했다고 기록돼 있다. 그러나 이는 **Agent가 그때 우연히
  `query`를 채웠을 때**의 결과일 수 있다. `query=''` 재현 경로는 검증되지 않았다.
- 단위 테스트는 `run_search_news`에 이미 채워진 정상 입력을 넣어 통과한다.
  **Agent가 빈 `query`를 만들어내는 경로**는 테스트가 없다.
- `HybridRetriever.search`/`embed_query`에 **빈 문자열 방어가 없다.**

## 5. 재현 절차 (요약)

```bash
curl -s -X POST http://127.0.0.1:8000/api/qa \
  -H 'Content-Type: application/json' \
  -d '{"question":"삼성전자 어제 악재 이었음?","stock_code":"005930"}'
# → execution.tool_calls = [{"name":"search_news","status":"error"}]
```

Upstage 직접 확인: `solar-embedding-2-query` 모델에 정상 문장은 200,
빈 문자열 input은 400(`'$.input' is invalid`).

## 6. 수정 방향 (후보, 미적용)

세 층 중 어디를 막을지 결정 필요. 권장은 **①+②(방어 + 계약 개선)**.

| # | 층 | 내용 | 성격 |
|---|---|---|---|
| ① | 임베딩/retriever | 빈/공백 `query`는 Upstage에 보내지 않고 안전 처리(빈 벡터 검색 skip 또는 명확한 no_data). | 근본 방어. 모든 Tool 보호. 다시는 400 안 남 |
| ② | search_news Tool 계약 | `query` docstring에 "항상 핵심 검색어(종목명·주제)를 채운다"를 명시. 빈 `query`면 시간범위 내 해당 종목 뉴스를 반환(사용자 "어제 뉴스" 의도 충족). | 계약 개선. Agent가 애초에 안 비우게 유도 |
| ③ | 뉴스 검색 자체 | 시간범위만 있고 query 없을 때 벡터검색 대신 **최신순 조회**로 분기. | 검색 시맨틱 변경(추가 설계 필요) |

### 주의(스펙 준수)
- 질문 문자열을 백엔드에서 파싱해 Tool을 강제하거나 키워드 라우터를 두지 않는다.
- 종목·질문 하드코딩 금지. `query` 기본값은 Agent가 넘긴 값(종목/문맥)만 사용한다.
- 임베딩 방어는 "빈 입력 거부"만 하고, 없는 데이터를 만들어내지 않는다(no_data 유지).

## 7. 최종 수정 (2026-07-26, 승인 후 적용)

승인된 핵심 원칙: "어제 악재 있었어?"처럼 **종목·기간·감성만 있는 뉴스 질문은
검색 주제가 없어도 정상 질문**이다. 이 경우 임베딩 검색을 강제하지 말고 조건 조회한다.

### 7.1 변경 전후 실행 흐름

**변경 전 (결함)**
```
"어제 악재?" → Agent: search_news(query='', relative_period='yesterday')
            → retriever.search → embed_query('')  ← 빈 문자열
            → Upstage 400 → search_news error → "일시적 오류"
```

**변경 후**
```
주제 없음: "어제 악재?"
  → Agent: search_news(query 생략, sentiment='negative', relative_period='yesterday')
  → run_search_news: 주제 없음 판정 → retriever.list_recent_news(임베딩 미호출)
  → news_clusters 를 종목·기간·감성으로 최신순 조회 → ok

주제 있음: "어제 HBM 뉴스?"
  → Agent: search_news(query='HBM', relative_period='yesterday')
  → run_search_news: 주제 있음 → retriever.search (semantic+lexical+RRF 유지)
```

### 7.2 변경 파일

| 파일 | 변경 |
|---|---|
| `app/ml/embeddings.py` | `_embed`: 빈/공백 input 이면 외부 HTTP 없이 `ValueError`. 임의 문장·벡터 대체 안 함. |
| `app/rag/retrieval.py` | `HybridRetriever.list_recent_news` 신규 — `news_clusters` 직접 조회(종목·기간·감성·최신순·사건단위). 임베딩 미호출. `_first_topic` 헬퍼 추가. |
| `app/agent/tools/news.py` | `SearchNewsInput.query` optional(None 허용) + `sentiment` 추가. `run_search_news`: `_has_topic()`(None·빈·공백=없음)로 경로 분리. `applied_filters.mode`(hybrid_search/recent_events)·`sentiment` 노출. |
| `app/agent/runtime.py` | `search_news` tool: `query` optional, `sentiment` 인자 추가, docstring 에 검색어 필요/불필요 케이스 명시. |

### 7.3 감성(sentiment) 데이터 근거

`rag_documents.source_pk = news_clusters.id` 로 연결되고, `news_clusters` 에
`sentiment_label`(positive/neutral/negative)이 실재한다(실측 확인). 따라서
"악재/호재" 질문에서 감성을 **DB 조건으로** 필터한다(질문 문자열 파싱·키워드 라우터 아님).
Agent 가 sentiment 인자를 판단해 넘기고, 백엔드는 그 값으로 조회만 한다.

### 7.4 스펙 준수 확인

- 질문 문자열을 백엔드에서 파싱하거나 Tool 을 강제하는 분기 없음(Agent 가 인자 선택).
- 빈 검색어에 종목명을 억지로 넣지 않음(주제 없으면 조건 조회로 분기).
- 오류를 no_data 로 숨기지 않음(임베딩 빈 입력은 명확한 ValueError, 결과 없음만 no_data).
- 다른 종목·기간 대체 없음. 기존 Agent Tool 선택 구조 변경 없음.

### 7.5 단위 테스트 (신규)

- `tests/agent/test_tool_contracts.py`: 주제 있음→hybrid_search / None·""·공백→recent_events
  (임베딩 경로 미호출), 감성 전달, 결과 없음→no_data(error 아님).
- `tests/unit/test_news_empty_query.py`: 빈/공백 임베딩 입력→외부 HTTP 0회 ValueError,
  list_recent_news 최신순·사건단위 중복 없음·타 종목 혼입 없음·빈 결과 무대체.

### 7.6 실제 Agent 반복 검증 (각 5회, 총 35회)

| 질문 | search_news 결과 |
|---|---|
| 삼성전자 어제 악재 있었어? | ok ×5 |
| 삼성전자 어제 무슨 일 있었어? | ok ×5 |
| 어제 삼성전자 나쁜 소식 있었어? | ok ×5 |
| 삼성전자 오늘 뉴스 알려줘. | ok ×5 |
| 삼성전자 어제 HBM 관련 뉴스 알려줘. | no_data ×5 (주제有→하이브리드, 해당일 HBM 없음) |
| 삼성전자 최근 호재 알려줘. | ok ×5 |
| 어제 존재하지 않는 종목 뉴스 | search_news 미호출 ×5 (지원 밖 종목, 혼입 없음) |

- **search_news error: 0/35** ✅
- 빈 검색 주제 질문에서 임베딩 호출 0(단위 테스트로 증명), Upstage 400 0건.
- no_data 와 error 구분됨(HBM 사례=no_data). 다른 종목 혼입 0.

### 7.7 회귀

- 전체 pytest: **310 passed**(297 → +13 신규). ruff check·format 통과.
- Agent 평가(dev 7 + holdout 10): required_tool_recall 1.0, forbidden 0.0,
  no_data_handled·financial_exact_match 전부 통과, nonexistent_citation 0.
  → 기존 뉴스 검색 Recall 회귀 없음.

## 8. timeout 변경(별개 결함, 분리 기록)

**이 timeout 변경은 빈 검색어 결함과 무관하다.** 빈 검색어 수정이 timeout 문제를
해결한 것이 아니다.

- `app/core/config.py`: `agent_timeout_seconds 8.0 → 45.0`.
- 원인: 8초는 다단계 모델 호출(최대 4회, 개별 모델 timeout 20초)·콜드스타트에서
  정상 응답도 timeout 시켜 빈 답변을 유발함.
- 실측 지연 근거(평가): p50 ≈ 2.4~3.8초, **p95 ≈ 6.2~6.7초**. 8초는 p95 에 근접해
  정상 응답을 자를 위험이 크고, 45초는 개별 모델 timeout(20초)×다단계를 감당할 여유가
  있다. → 45초 유지가 타당(실측 기준 별도 판단).
- 진단에 쓴 임시 디버그 로깅(runtime.py/embeddings.py/common.py)은 전부 원복했다.
