# Phase 8 평가 지표 집계 로직 감사

브랜치: `phase/8-metric-audit` (base: PR #62 머지 후 main)

이번 라운드는 평가 metric aggregator만 감사·수정했다. Agent·Tool·Retriever·
프롬프트·Validator·devset·gold label은 전혀 수정하지 않았고, 개발셋 120문항을
다시 실행하거나 LLM·DB를 호출하지 않았다. `docs/rag/phase_8/eval/
baseline_dev_records_final.json`(PR #62 final-dev 실행이 저장한 원시 결과)만
읽어 재채점했다.

## 1. 공식 검색 집계가 잘못된 원인

PR #62가 발견한 불일치(뉴스 공식 0/0/0 vs 재계산 0.2381/0/0.1184)를 원시
데이터로 추적한 결과, **두 개의 독립된 결함**이 겹쳐 있었다.

### 원인 A — 완전 적중 케이스가 recall 분모·분자에서 통째로 제외됨

`_doc_miss_is_not_retriever_fault(case, record, grade)`는 원래 "정답 문서를
찾았는데 검증기가 답변을 지웠다"거나 "같은 정답 문서의 다른 청크를
반환했다"는 두 경우만 걸러 "이건 Retriever 실패가 아니다"라고 표시하기
위한 함수였다. 그런데 예전 `aggregate()`는

```python
if doc_gold and not _doc_miss_is_not_retriever_fault(case, rec, g):
    retr.recall_total += len(doc_gold)
    ...
```

처럼 이 함수가 **True**를 반환하면(=Retriever 탓이 아니다) `recall_total`/
`recall_hit` 자체를 **아예 세지 않았다.** 문제는 이 함수가 "이미 청크
단위로 완전 적중(`gold_source_hits`)한 케이스"인지 전혀 구분하지 않고,
단지 "같은 부모 문서를 가리키는 출처가 하나라도 있으면" True를 반환한다는
점이다. 그 결과 완전 적중 케이스(청크 ID까지 정확히 일치)까지 recall
분모·분자에서 통째로 빠져 recall이 실제보다 크게 낮게(0.0) 보고됐다.

### 원인 B — Hit@1/MRR이 실제 검색 순위가 아니라 정렬된 청크 ID로 계산됨

더 심각한 문제를 추가로 발견했다: 예전 코드는 `first = rec.retrieved_ids[0]`
로 1위 문서를 판정했는데, `RunRecord.retrieved_ids`는 `AgentQaResult.
source_ids`(=`sorted(evidence.source_ids)`)에서 온 값이라 **청크 ID를
알파벳순으로 정렬한 집합**이다. 실제 검색 랭킹 순서가 전혀 아니다. 반면
`record.sources`는 Tool이 반환한 순서를 그대로 보존한다(실제 검색 순위).
`news-01`로 직접 대조한 결과:

```
retrieved_ids (알파벳순): [172180f6-..., 71fdddab-..., b3ceff7e-..., b71e589e-..., ca573220-...]
sources 순서(실제 검색 순위): [71fdddab-..., 172180f6-..., b71e589e-..., ca573220-..., b3ceff7e-...]
```

gold(`71fdddab-...`)는 실제 검색 순위 1위인데 `retrieved_ids[0]`로는
2위(`172180f6-...`)를 보게 된다. 즉 Hit@1/MRR이 원천적으로 무작위에
가까운 순서로 계산되고 있었다.

### 근본 수정

`app/eval/grader.py`에 문서 ID 기준 헬퍼를 새로 만들었다:

- `_gold_document_id(gs)` — 라벨 `note`의 `news_clusters.id=`/
  `research_reports.id=`를 파싱해 **부모 문서 ID**를 뽑는다(devset 자체는
  청크 단위 `source_id`만 정식 필드로 갖고 있어 이 파싱이 유일한 문서
  단위 정답 소스다. devset은 수정하지 않았다 — 읽기만 한다).
- `_source_document_id(source)` — 실제 출처 1건에서 부모 문서 ID를 뽑는다.
  news는 `locator.source_pk`, report는 `locator.report_id`가 각각
  `news_clusters.id`/`research_reports.id`와 동일 값임을 실제 데이터로
  확인하고 사용했다.
- `document_ranking(record)` — `record.sources`(실제 검색 순위 보존)를
  부모 문서 ID로 변환하고, 같은 문서의 중복 청크는 첫 등장 순위만 남겨
  1건으로 축약한다. **`retrieved_ids`(정렬된 집합)는 순위 계산에 쓰지
  않는다.**
- `document_recall_stats(cases, records, grades, doc_type)` — 뉴스/리포트를
  `doc_type`으로 완전히 분리해 각자의 분모로 Recall@K/Hit@1/MRR을 계산한다.
  gold 문서가 있는 문항만 분모에 포함하고, "완전 적중"은 항상 적중으로
  집계한다(과거처럼 문서-단위 예외 판정 함수의 반환값 때문에 적중 케이스가
  통째로 빠지는 일이 없다).
- `report_page_accuracy(cases, records)` — 문서 검색 지표와 분리해 리포트
  근거 페이지 정확도만 별도 계산.

## 2. 변경 파일

```
app/eval/grader.py                — 문서 ID 기준 헬퍼 추가(_gold_document_id,
                                     _source_document_id, document_ranking,
                                     document_recall_stats, report_page_accuracy),
                                     _doc_miss_is_not_retriever_fault 를 문서 ID
                                     비교로 재작성, aggregate() 의 문서 검색
                                     집계 로직 교체, 미사용 _reciprocal_rank 제거
app/eval/metrics.py               — RetrievalMetrics 를 news_stats/report_stats/
                                     page_stats 주입 구조로 변경(document_retrieval
                                     단일 dict → news_retrieval/report_retrieval 분리)
tests/unit/test_eval_foundation.py — 기존 검색 테스트 4건을 새 스키마(news_
                                     retrieval/report_retrieval, note 필드,
                                     locator.source_pk/report_id)에 맞게 갱신
tests/unit/test_metric_audit.py   — 신규, §4 요구 8개 케이스
scripts/phase8_metric_audit.py    — 신규, 저장된 final-dev 결과 재채점 스크립트
                                     (LLM·DB 미호출)
docs/rag/phase_8/eval/metric_audit_final.json — 감사 산출물
```

Agent(`app/agent/`)·Tool(`app/agent/tools/`)·Retriever(`app/rag/`)·
프롬프트(`app/agent/prompts.py`)·Validator(`app/agent/validator.py`)는
`git status`로 변경 없음을 확인했다. devset.json·holdout.json도 `git diff`로
변경 없음을 확인했다.

## 3. 뉴스 평가 대상 문항 수

**19문항** (devset의 "뉴스 사건·영향" 유형 전부 — gold_sources에
`news_clusters.id`가 파싱되는 케이스 19건, 구조화 조회 문항은 애초에
포함되지 않음).

## 4. 뉴스 Recall@K / Hit@1 / MRR과 분자·분모

| 지표 | 분자 | 분모 | 값 |
|---|---|---|---|
| Recall@K | 10 | 19 | 0.5263 |
| Hit@1 | 9 | 19 | 0.4737 |
| MRR | Σ(1/rank)=9.5 | 19 | 0.5 |

**수식**: 문항별로 `document_ranking(record)`(부모 문서 ID, 중복 제거, 실제
검색 순위)를 구하고, gold 문서 ID가 그 목록에 있으면 Recall 적중(분자
+1), 1위에 있으면 Hit@1 적중(분자 +1), 있으면 `1/순위`를 MRR 합산에
더한다. 분모는 세 지표 모두 "뉴스 gold 문서가 있는 문항 수"로 동일하게
고정한다(19).

미적중 9건: news-04, news-09, news-10, news-11, news-13, news-14, news-15,
news-18, news-19. 이 중 news-04/09/13/14/15/19(6건)는 round2~final-dev에서
이미 반복 확인된 순수 의미 검색 순위 한계, news-10/18(2건)은 사건명을
정확히 검색했는데도 미검색(순수 검색 순위 한계로 판단), news-11(1건)은
검색 실패가 아니라 애초에 `search_news`를 호출하지 않고 `get_financial_
facts`만 호출한 Tool 선택 오류(§8 필수 Tool 누락과 동일 근본원인, 중복
집계 아님 — 이 문항은 뉴스 검색 자체를 시도하지 않았으므로 recall 분모에는
포함되지만 분자를 얻을 기회 자체가 없었다).

## 5. 리포트 평가 대상 문항 수

**15문항** (devset의 "증권사 리포트" 유형 전부).

## 6. 리포트 Recall@K / Hit@1 / MRR과 분자·분모

| 지표 | 분자 | 분모 | 값 |
|---|---|---|---|
| Recall@K | 14 | 15 | 0.9333 |
| Hit@1 | 14 | 15 | 0.9333 |
| MRR | Σ(1/rank)=14.0 | 15 | 0.9333 |

미적중 1건: report-06(대신증권 SK하이닉스 리포트 전망 — round2에서 이미
"8배 후보 확대에도 못 찾음"으로 확정된 순수 의미 검색 한계). 나머지 14건은
모두 1위 적중(가장 관측된 case: report-05/07/08/09/10/12/13/14 — 이전
라운드에서 청크 ID 불일치 때문에 "검색 실패"로 잘못 보이던 케이스들이
문서 ID 기준으로는 전부 1위 정확 적중임을 확인했다). 이는 PR #61의 broker
우선 메타 조회 수정이 실제로는 매우 효과적이었다는 뜻이며, 예전 청크
단위 집계가 이 효과를 완전히 가려왔다는 것을 보여준다.

## 7. 리포트 페이지 정확도

문서 검색 지표와 분리해 계산: **12/48 = 0.25** (`report_page_accuracy()`).
분모(48)는 리포트 문서 검색 분모(15)보다 크다 — 한 리포트 문항이 목표주가
근거로 여러 페이지를 gold로 지정하는 경우가 있어(예: report-01은 페이지
[9] 외 추가 근거 페이지들), gold page 라벨 개수 기준으로 센다.

## 8. 필수 Tool 호출률의 분자·분모와 최종 값

**독립 재계산(저장된 raw record에서 처음부터 다시 계산, 공식 aggregate()
코드와 무관하게 수기 검증)**:

- 분모(`required_total`): 각 문항의 `required_tools` 개수 합 + (`required_
  tools_any`가 있는 문항마다 +1) = **127**
- 분자(`required_hit`): 필수 Tool이 실제로 호출된 개수 = **125**
- 계산값: 125/127 = **0.9843**

공식 `aggregate()["agent"]["required_tool_recall"]`도 동일하게 **0.9843**을
반환함을 확인했다 — **PR #62의 값과 정확히 일치한다.** 이 지표는 이번
감사에서 재설계하지 않았다(문제가 없었음을 확인만 함).

## 9. 필수 Tool 누락 질문 ID

| 문항 ID | 누락된 Tool | 원인 |
|---|---|---|
| term-07 | lookup_financial_term | "상장지수펀드 쉽게 설명해줘" — 모델이 Tool 없이 자체 지식으로 답변 |
| news-11 | search_news | "SK하이닉스 2분기 영업이익 64조원 관련해서 무슨 일 있었어?" — 뉴스 질문인데 `get_financial_facts`(금지 Tool)만 호출 |

## 10. devset·gold·제품 코드 변경 여부

**변경 없음.** `git diff --stat docs/rag/phase_8/eval/devset.json docs/rag/
phase_8/eval/holdout.json` 결과 없음(diff 없음). `app/agent/`, `app/rag/`,
`app/agent/validator.py` 등 제품 코드는 `git status`로 전혀 수정되지
않았음을 확인했다. 수정한 파일은 `app/eval/grader.py`와 `app/eval/
metrics.py`(평가 metric aggregator)뿐이며, 이는 prompt.md §3이 명시적으로
허용한 범위다.

## 11. LLM·DB 재실행 여부

**재실행하지 않음.** `scripts/phase8_metric_audit.py`는 `docs/rag/phase_8/
eval/baseline_dev_records_final.json`(PR #62가 이미 저장해 둔 원시 실행
결과)만 읽고, `grade_case(case, record, facts=None)`로 호출해 DB 조회
(`FactsService`)조차 인스턴스화하지 않는다. `get_supabase_client`, Agent
`invoke`, 임의의 LLM/HTTP 호출이 스크립트에 전혀 없음을 grep으로 확인했다.
120문항 개발셋도, 홀드아웃 40문항도 이번 라운드에서 실행하지 않았다.

## 12. 테스트 결과

`pytest tests/unit` 전체: **386 passed**(전체 Agent 재실행 없이 metric
관련 테스트와 기존 빠른 단위 테스트만 실행, prompt.md §4 지시대로).

신규 8개 테스트(`test_metric_audit.py`)가 각각 다음을 검증한다:
1. gold 문서가 1위인 경우(recall/hit@1/mrr 모두 1.0)
2. gold 문서가 K 이내 후순위인 경우(recall=1.0, hit@1=0.0, mrr=0.5)
3. gold 문서가 없는 경우(모두 0.0, missed_case_ids에 기록)
4. 같은 부모 문서의 청크가 중복 반환된 경우(1건으로 축약, 순서 유지)
5. Validator가 답변을 삭제했지만 검색은 성공한 경우(적중으로 집계)
6. 뉴스와 리포트가 섞인 경우(각자 다른 분모로 분리 집계)
7. 구조화 질문이 retrieval 분모에서 제외되는 경우(n_eval=0, None)
8. 필수 Tool이 모두 호출된 경우와 하나 누락된 경우(정확한 분자·분모 구분)

기존 검색 관련 테스트 4건(`test_eval_foundation.py`)도 새 스키마(`news_
retrieval`/`report_retrieval`, gold_sources의 `note` 필드, sources의
`locator.source_pk`/`report_id`)에 맞춰 갱신해 통과를 확인했다.

`ruff check`/`ruff format --check` 모두 통과.

## 13. 홀드아웃 실행 준비 여부

**준비됨.** 이번 감사로 문서 검색 지표(뉴스/리포트 Recall@K, Hit@1, MRR)가
청크 단위 우연이 아니라 문서 단위 정확한 값으로 계산되도록 고쳐졌고,
공식 필수 Tool 호출률(0.9843)도 독립 재계산으로 정확함이 확인됐다. 홀드아웃
40문항을 실행할 때는 이 수정된 `aggregate()`를 그대로 재사용하면 되며,
별도 계산 방식 변경 없이 일관된 지표를 얻을 수 있다.

**홀드아웃에서 사용할 최종 지표 계산 방식**:
- 문서 검색: `document_recall_stats(cases, records, grades, "news_event"
  | "research_report")` — 뉴스/리포트 완전 분리, 부모 문서 ID 기준,
  gold 있는 문항만 분모, Validator/other_stock 판정과 독립적으로 완전
  적중은 항상 적중 처리.
  - Recall@K = `count(gold_doc in document_ranking(record)) / n_eval`
  - Hit@1 = `count(document_ranking(record)[0] == gold_doc) / n_eval`
  - MRR = `sum(1/rank if hit else 0) / n_eval`
- 리포트 페이지 정확도: `report_page_accuracy(cases, records)` — 문서
  검색과 별도 분모(gold page 라벨 개수 기준).
- 구조화 조회: 기존 `lookup_hit`/`lookup_total`(청크·행 단위 정확 일치)
  그대로 유지 — 이번 감사 대상 아님, 결함 없음.
- 필수 Tool 호출률: 기존 `agent.required_hit`/`required_total` 로직 그대로
  유지 — 독립 검증 결과 이상 없음.

## PR

https://github.com/kimjunu10/stock-ai-assistant/pull/63
