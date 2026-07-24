# RAG 평가 계획

> 평가 대상: 단일 Tool-Calling Agentic Hybrid RAG  
> 기준 구조: LangChain `create_agent` + LangGraph runtime + 기존 금융 Tool  
> 목적: 검색 품질뿐 아니라 Tool 선택, 인자, 숫자, 출처, 제외 조건을 분리 평가한다.

---

## 1. 평가 목적

최종 시스템은 단순 검색기가 아니라 다음을 모두 수행한다.

```text
자연어 이해
→ Tool 선택
→ Tool 인자 생성
→ SQL 또는 검색
→ 필요 시 추가 Tool 호출
→ 근거 기반 답변
```

따라서 하나의 “RAG 정확도”로 평가하지 않는다.

1. Agent Tool 선택
2. Tool 인자 정확성
3. 검색 성능
4. 숫자·기간·단위 정확성
5. 답변 근거성
6. 출처 정확성
7. 부정·제외 조건 준수
8. 답변 불가능 질문 처리
9. 지연시간·비용·안정성

---

## 2. 평가 원칙

### 2.1 개발셋과 홀드아웃 분리

```text
개발셋
→ Tool 설명, 프롬프트, 검색 설정, 문맥 수 조정에 사용

홀드아웃
→ 최종 평가에서만 사용
```

홀드아웃 결과를 보고 수정하면 해당 질문은 개발셋으로 이동하고, 새로운 홀드아웃을 만든다.

### 2.2 런타임 하드코딩 금지

금지:

- 평가 질문 문장과 일치하는 조건문
- 특정 종목·기업·리포트 예외
- 실패 질문별 Tool 강제
- 평가 문서 ID 강제
- 질문 속 단어만으로 Tool 선택

허용:

- Tool 입력 JSON Schema
- 금융 공식 코드와 기간 규칙
- 데이터 정규화
- 종목 별칭 마스터 데이터
- 일반적인 검색 필터
- 개발셋에서 선택한 전역 설정값

평가 데이터에 정답 Tool과 정답 인자를 기록하는 것은 런타임 하드코딩이 아니다. 평가용 정답표일 뿐이다.

### 2.3 기존 QueryPlan과 비교

전환 기간에 동일 질문으로 비교한다.

```text
legacy keyword QueryPlan
vs
single tool-calling Agent
```

비교 결과는 새 Agent가 다음 항목에서 우수한지 확인하는 용도다.

- 부정·제외 조건
- 동의어와 자연스러운 표현
- 복수 Tool 질문
- 불필요 Tool 호출
- 근거 부족 처리

새 Agent가 기준을 통과하면 legacy QueryPlan은 라이브 경로에서 제거한다.

---

## 3. 평가 데이터

최종 160개를 목표로 한다.

| 유형 | 질문 수 |
|---|---:|
| 금융용어 | 15 |
| 정확한 재무 숫자 | 25 |
| 뉴스 사건·영향 | 25 |
| 공시 설명·구조화 값 | 20 |
| 증권사 리포트 | 20 |
| 복수 Tool 혼합 질문 | 20 |
| 부정·제외·대조 조건 | 15 |
| 현재 화면 문맥 질문 | 10 |
| 답변 불가능·모호 질문 | 10 |
| **합계** | **160** |

각 질문은 다음 구조로 저장한다.

```yaml
question: "최근 뉴스에서 삼성전자 호재 있어? 실적 관련은 제외해."
context:
  stock_code: "005930"
  source_type: null
  source_id: null

expected_tools:
  required:
    - search_news
  forbidden:
    - get_financial_facts
    - search_research_reports

expected_arguments:
  search_news:
    stock_code: "005930"
    sentiment: "positive"
    exclude_topics_contains:
      - "실적"

gold_document_ids:
  - "..."

expected_facts:
  - "..."

expected_numbers: []

is_answerable: true
```

Tool 인자의 자연어 배열은 완전 문자열 일치 대신 의미 기준으로 판정한다. 예를 들어 `실적`, `기업 실적`, `earnings`는 동일 제외 의도로 인정할 수 있다.

---

## 4. 필수 회귀 질문

```text
PER이 뭐야?

삼성전자 2025년 영업이익은 얼마야?

삼성전자 2025년 3분기 누적 영업이익은 얼마야?

최근 뉴스에서 삼성전자 호재 있어?
영업이익 같은 실적 관련 내용은 제외해.

실적 얘기는 빼고 최근 악재만 알려줘.

목표주가 말고 실제 주가가 왜 떨어졌어?

증권사 전망 말고 회사가 직접 공시한 내용만 알려줘.

2025년 3분기 누적 영업이익과
3분기 단독 영업이익을 비교해줘.

영업이익이 왜 감소했고 증권사 전망은 어때?

이 리포트에서 목표주가를 내린 이유가 뭐야?

이 뉴스와 관련된 공식 공시가 있어?

자료에 없는 내년 매출을 확정값으로 알려줘.
```

---

## 5. Agent 평가

### 5.1 Required Tool Recall

정답에 필요한 Tool 중 실제 호출한 비율이다.

```text
호출한 필수 Tool 수 / 필요한 Tool 수
```

목표:

```text
전체 ≥ 95%
정확한 숫자 질문 = 100%
```

### 5.2 Forbidden Tool Violation

호출하면 안 되는 Tool을 호출한 비율이다.

예:

```text
“실적 관련 제외” 질문에서 get_financial_facts 호출
```

목표:

```text
전체 ≤ 3%
부정·제외 질문 = 0%
```

### 5.3 Tool Argument Accuracy

다음을 분리 평가한다.

- stock_code
- 기간
- report_period
- amount_type
- CFS/OFS
- sentiment
- source 제한
- include_topics
- exclude_topics
- actual/forecast

목표:

```text
금융 기간·amount_type = 100%
나머지 필수 인자 ≥ 95%
```

### 5.4 Tool Sequence Success

복합 질문에서 필요한 Tool을 호출하고 최종 답변까지 완료한 비율이다.

목표:

```text
≥ 90%
```

### 5.5 불필요 반복

```text
동일 Tool + 동일 인자 반복 호출 수
```

목표:

```text
0건
```

### 5.6 호출 예산 준수

```text
Tool 호출 ≤ 5
모델 호출 ≤ 4
전체 timeout 내 종료
```

초과:

```text
0건
```

---

## 6. 검색 성능

뉴스·공시·리포트를 분리한다.

### 6.1 Recall@K

- Recall@5
- Recall@8

### 6.2 Hit@1

정답 근거가 1위인지 확인한다.

### 6.3 MRR

정답 근거가 상위에 배치되는 정도를 평가한다.

### 6.4 중복 독점률

동일 문서·사건의 유사 청크가 최종 문맥을 과도하게 차지하는지 확인한다.

목표:

```text
동일 문서/사건 ≤ 최종 문맥의 25%
```

### 6.5 현재 문서 우선

현재 뉴스·공시·리포트 문맥이 전달된 질문에서 해당 문서가 상위에 포함되는지 평가한다.

목표:

```text
Top 3 포함 ≥ 95%
```

---

## 7. Reranker 도입 평가

두 구성을 동일 홀드아웃에서 비교한다.

```text
A. 현재 semantic + lexical + RRF
B. A + cross-encoder reranker
```

reranker 활성화 조건:

- Recall@8 또는 MRR 개선
- Citation Precision 유지 또는 개선
- 검색 P95 증가가 300ms 이내
- 배포 메모리 한도 충족
- 전체 응답 P95 목표 충족

조건을 충족하지 않으면 현재 RRF 검색을 유지한다.

모델 후보를 특정 질문에 맞춰 선택하지 않는다. 다국어 cross-encoder 후보는 별도 소규모 실험 후 확정한다.

---

## 8. 숫자·기간·단위 평가

정확한 재무와 구조화 공시는 Exact Match로 평가한다.

모두 맞아야 성공이다.

```text
숫자
단위
통화
사업연도
보고기간
quarter/cumulative/point_in_time
CFS/OFS
실제값/전망값
정정 최신 여부
```

목표:

```text
재무 숫자 Exact Match = 100%
기간 정확도 = 100%
단위 정확도 = 100%
실제값/전망값 혼동 = 0건
```

정확한 행이 없을 때 다른 기간을 대신 반환하면 실패다.

---

## 9. 부정·제외 조건 평가

다음 유형을 별도 집계한다.

```text
A 말고 B
A는 제외
A 관련 내용은 빼고
실제값만
전망은 제외
뉴스만
공시만
증권사 의견 말고 회사 발표만
```

평가 항목:

1. 금지 Tool을 호출하지 않았는가
2. 금지 주제를 답변에 포함하지 않았는가
3. 허용된 근거만 사용했는가
4. 제외 조건 때문에 근거가 부족하면 솔직히 말했는가

목표:

```text
제외 조건 준수율 ≥ 95%
치명적 위반 = 0건
```

---

## 10. 답변 품질

### 10.1 사실 충실도

답변의 검증 가능한 주장 중 Tool 결과가 뒷받침하는 비율이다.

목표:

```text
≥ 95%
```

### 10.2 핵심정보 포함률

사전에 작성한 `expected_facts`가 답변에 포함된 비율이다.

### 10.3 직접성

질문에 직접 답했는지 평가한다.

### 10.4 과도한 인과 단정

다음 표현을 실패로 기록한다.

```text
이 뉴스 때문에 주가가 올랐다
목표주가가 올라 실제 주가도 오를 것이다
실적이 반드시 좋아진다
```

관찰과 인과를 구분한다.

---

## 11. 출처 평가

### Citation Precision

제시한 출처 중 실제 주장을 뒷받침하는 비율이다.

### Citation Coverage

출처가 필요한 주장 중 실제 출처가 연결된 비율이다.

### 메타데이터 정확성

- 제목
- 언론사·증권사
- 날짜
- 공시 접수번호
- PDF 페이지
- actual/forecast 라벨

목표:

```text
존재하지 않는 인용 = 0건
잘못된 PDF 페이지 = 0건
비활성 문서 인용 = 0건
```

---

## 12. 답변 불가능 질문

평가:

- Tool 결과가 없음을 인식했는가
- 다른 기간·기업·문서로 대체하지 않았는가
- 숫자를 생성하지 않았는가
- 필요한 경우 확인 질문을 했는가

목표:

```text
근거 없는 숫자 생성 = 0건
관련 없는 근거 사용 = 0건
```

---

## 13. 성능과 비용

### 지연시간

P50/P95:

- Agent 첫 모델 호출
- Tool별 지연
- 검색
- 첫 답변 토큰
- 전체 응답

초기 목표:

| 지표 | 목표 |
|---|---:|
| 검색 P95 | 1초 이하 |
| 첫 답변 토큰 P95 | 3초 이하 |
| 전체 단순 질문 P95 | 6초 이하 |
| 전체 복합 질문 P95 | 10초 이하 |

Agentic 구조에서는 모든 질문을 3~4초에 끝내겠다는 비현실적인 단일 목표를 사용하지 않는다. 단순 질문과 복합 질문을 분리한다.

### 비용

- 질문당 모델 호출 수
- Tool 호출 수
- query embedding 비용
- 최종 생성 비용
- 재검색 발생률
- reranker 비용 또는 GPU 자원

---

## 14. 자동·사람 평가

### 자동 평가

- Tool 이름
- Tool 인자
- 호출 횟수
- Recall@K
- MRR
- 숫자 Exact Match
- Citation ID 무결성
- 지연시간
- 비용

### 사람 평가

- 초보자 이해 가능성
- 제외 조건 준수
- 설명 충분성
- 근거와 표현의 적합성
- 투자 추천처럼 보이는지

최소 2명이 독립 평가한다.

---

## 15. LangSmith 사용

개발·스테이징에서는 LangSmith tracing과 offline evaluation을 권장한다.

기록:

```text
질문
Tool 호출 이름
Tool 인자
Tool 결과 크기
모델 호출 수
최종 답변
지연시간
종료 사유
```

주의:

- API 키와 DB 비밀정보를 보내지 않는다.
- 비공개 리포트 전체 원문을 trace에 남기지 않는다.
- 짧은 검색 근거와 메타데이터만 남긴다.
- 외부 전송 정책이 승인되지 않으면 기존 `rag_query_logs`로 동일 지표를 저장한다.

LangSmith 사용 여부는 런타임 아키텍처를 바꾸지 않는다.

---

## 16. 전환 승인 기준

새 Agent를 라이브 `/qa`에 적용하려면 다음을 모두 만족해야 한다.

```text
필수 Tool Recall ≥ 95%
금지 Tool 위반 ≤ 3%
부정·제외 치명적 위반 0건
재무 숫자 Exact Match 100%
기간·단위 정확도 100%
실제값/전망값 혼동 0건
존재하지 않는 인용 0건
동일 호출 반복 0건
단순 질문 P95 ≤ 6초
복합 질문 P95 ≤ 10초
```

기준 미달 시 특정 질문 예외를 추가하지 않는다.

수정 우선순위:

```text
Tool 설명·스키마
→ Tool 내부 데이터 계약
→ 검색 데이터·메타데이터
→ 시스템 프롬프트
→ 모델 호환성
```

---

## 16.5 Phase별 평가 연결 (기존 문서 보존 + 확보 실측)

> 이 절은 Agentic 전환 전 각 Phase 평가 항목과 이미 확보한 실측 결과를 보존한 것이다.
> Phase 5.5 이후에는 위 §5(Agent 평가) 지표를 함께 적용한다.

### Phase 3 (하이브리드 검색) — 확보 실측

| 평가 | 결과 |
|---|---:|
| 뉴스 고유명칭 Recall@8 | 0.92 |
| 별도 홀드아웃 Recall@8 | 0.94 |
| 뉴스 자연어 Recall@8 | 0.975 이상 |

주의: 위 수치는 전체 RAG 정확도가 아니라 **뉴스 검색 성능**이다.
(Phase 3 개선 전 정확명칭 recall@8 0.25 → 0.92, 홀드아웃 0.65 → 0.94.)

### Phase 4 (재무·용어·혼합)
- DART 검색·공시 최신본 선택·재무 Exact Match·단위·기간·금융용어 정의 정확도.

### Phase 5 (증권사 리포트) — 확보 실측
- 검색 품질: 5개 유형(정확명칭·자연어·전망·목표주가·실적원인) Recall@8 = 100%(25/25),
  타종목 혼입 0, 출처페이지 유효 40/40.
- 리포트 페이지 인용·표 숫자 추출·실제값/전망값 구분·목표주가/투자의견 추출.

### Phase 6 (주가)
- 주가 조회 성공률·거래일 기준 계산·기간 수익률·인과 과도 단정률.

### Phase 8 (전체)
- 160개 홀드아웃 종합, 치명적 오류 분석·수정.

---

## 17. 참고 자료

- LangSmith evaluation concepts: https://docs.langchain.com/langsmith/evaluation-concepts
- LangSmith RAG evaluation: https://docs.langchain.com/langsmith/evaluate-rag-tutorial
- LangChain Agent docs: https://docs.langchain.com/oss/python/langchain/agents
- LangGraph Agentic RAG: https://docs.langchain.com/oss/python/langgraph/agentic-rag
- RAG paper: https://arxiv.org/abs/2005.11401
- ReAct paper: https://arxiv.org/abs/2210.03629
