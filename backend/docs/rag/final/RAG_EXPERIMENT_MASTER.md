# RAG·Agent 실험 통합 기록 (기술 근거용)

작성일: 2026-07-27
조사 기준 commit: `3b9918d818bedba732e3ec0fbf1b81db868b5c39` (origin/main, PR #79 머지 커밋)
작성 범위: 문서 작성만. Agent·개발셋·홀드아웃·외부 API 재실행 없음. 제품 코드·프롬프트·Retriever·Gold·채점기 무수정.

---

## 1. 조사 기준과 근거 위치

### 1.1 조사 방법

최신 `origin/main`을 기준으로 저장소 전체를 조사했다. 우선순위는 요약 Markdown → metrics JSON → 평가 코드 → Git/PR 기록이었고, raw Agent 기록과 Tool trace는 수치가 충돌하거나 원인 확인이 필요한 경우에만 읽었다.

### 1.2 실험 자료가 실제로 위치한 디렉터리

**Phase 8 아래에 모든 자료가 있지 않았다.** 실험 자료는 다음과 같이 흩어져 있다.

| 디렉터리 | 담긴 실험 |
|---|---|
| `backend/docs/rag/phase_2/` | 뉴스 색인(trial 100건, 전체 색인) |
| `backend/docs/rag/phase_3/` | **뉴스 Retriever 단독 비교 실험**(hybrid search) |
| `backend/docs/rag/phase_4/` | BOK 경제금융용어 800선 적재·검증 |
| `backend/docs/rag/phase_5/` | **리포트 Retriever 단독 실험**(inventory·dry-run 3단계) |
| `backend/docs/rag/phase_5_5/` | Agent 전환 preflight, 스테이징 smoke, 초기 27문항 평가셋 |
| `backend/docs/rag/phase_6/` | **주가 Tool 초기 계약 테스트** |
| `backend/docs/rag/phase_7/` | 프런트엔드 UI 데이터 계약 |
| `backend/docs/rag/phase_8/` | 160문항 평가셋 구축, 개발셋 baseline 4라운드, 지표 감사, 뉴스 감사, 최초 홀드아웃 |
| `backend/docs/rag/phase_9/` | Tool runtime 근본원인 + 동일 홀드아웃 회귀 |
| `backend/docs/rag/phase_10/` | 뉴스 기간 정책 감사·최소 수정 + **동일 40문항 최종 회귀 산출물** |
| `backend/docs/rag/STOCK_CONTEXT_SAFETY_GUARD.md` | PR #76 종목 문맥 오염 방지 |
| `backend/app/eval/` | 평가 패키지(스키마·지표·채점기·judge·recorder·runner) |
| `backend/scripts/phase8_*.py`, `phase9_*.py` | 실행기·분석기·감사 스크립트 |

### 1.3 검증의 종류를 구분한다

이 문서는 다음 5가지를 **서로 다른 종류의 검증**으로 취급한다. 섞어서 인용하면 안 된다.

| 종류 | 무엇을 재는가 | 해당 실험 |
|---|---|---|
| **검색기 단독 실험** | Retriever 랭킹만. Agent·LLM 없음 | Phase 3(뉴스), Phase 5(리포트) |
| **Agent 전체 평가** | Tool 선택·인자·답변·출처까지 end-to-end | Phase 8 개발셋 4라운드, Phase 8 최초 홀드아웃 |
| **동일 문항 회귀** | 수정 전후 같은 문항 비교. 일반화 성능 아님 | Phase 9·Phase 10 홀드아웃 회귀 |
| **production smoke** | 운영 환경에서 소수 시나리오 계약 확인 | Phase 5.5-G, Phase 6, Phase 9 tool smoke, PR #76·77 |
| **브라우저 수동 테스트** | 화면 동작 확인 | PR #78, #79 |

---

## 2. 전체 실험 타임라인

| # | 시기 | 실험 | 종류 | 핵심 결과 | PR |
|---|---|---|---|---|---|
| 1 | Phase 2 | 뉴스 색인 | 데이터 구축 | trial 100건 → 전체 색인 | — |
| 2 | Phase 3 | 뉴스 Retriever 단독 비교 | 검색기 단독 | hybrid 채택 | — |
| 3 | Phase 4 | BOK 용어 800선 적재 | 데이터 구축 | 용어 사전 확보 | — |
| 4 | Phase 5 | 리포트 Retriever 단독 | 검색기 단독 | 파서·색인 검증 | — |
| 5 | 2026-07-24 | 스테이징 Agent smoke | production smoke | 치명 결함 2건 발견·수정 | — |
| 6 | 2026-07-25 | 운영 라이브 전환 + legacy 제거 | production smoke | 운영 smoke 8/8 | #38 |
| 7 | 2026-07-25 | **주가 Tool 초기 계약 테스트** | 계약 + smoke | 주가 5케이스 전부 통과 | #41 |
| 8 | 2026-07-26 | **160문항 평가셋 구축** | 데이터 구축 | 정적 검증 19/19, dry-run 9문항 | #52 |
| 9 | 2026-07-26 | **라벨 검토 65건 확정** | 데이터 구축 | 검증 24/24, 미확정 0건 | #54 |
| 10 | 2026-07-26 | **개발셋 최초 baseline(round1)** | Agent 전체 | 무결점 42/120, 뉴스 Recall 0.333 | #55 |
| 11 | 2026-07-26 | 1차 교정 → round2 | Agent 전체 | 인자정확도 0.873→0.953 | #57·#58 |
| 12 | 2026-07-26 | 2차 교정 → round3 | Agent 전체 | 필수Tool·인자 1.0 | #59·#60 |
| 13 | 2026-07-26 | 3차(최종) 교정 → final-dev | Agent 전체 | **지표 집계 결함 발견** | #61·#62 |
| 14 | 2026-07-26 | **지표 집계 감사** | 평가코드 감사 | 리포트 Recall 실제 0.9333 | #63 |
| 15 | 2026-07-26 | 뉴스 실패 9건 원인 감사 | 평가코드 감사 | 날짜필터·중복클러스터가 주원인 | #64 |
| 16 | 2026-07-26 | 뉴스 최소 교정 | 제품 수정 | news-11 Tool 선택 수정 | #65 |
| 17 | 2026-07-26 | LLM judge 전환 + 답변 프롬프트 | 제품 수정 | 키워드 오탐 제거 | #66 |
| 18 | 2026-07-26 | **개발셋 최종 평가** | Agent 전체 | **통과율 97.44%**, 코드 동결 | #67 |
| 19 | 2026-07-27 | 뉴스 Gold canonical 전환 | 평가데이터 수정 | chunk UUID → cluster id | #71 |
| 20 | 2026-07-27 | **Phase 8 최초 블라인드 홀드아웃** | Agent 전체 | **formal 85.00%**, 실제 실패 31건 | #72 |
| 21 | 2026-07-27 | Phase 9 Tool runtime 근본원인 | 제품 수정 | validation 예외 → 표준 error | #73 |
| 22 | 2026-07-27 | **Phase 9 동일 문항 회귀** | 동일문항 회귀 | **formal 97.50%**, 뉴스 Recall 33.33% | #74 |
| 23 | 2026-07-27 | Phase 10 뉴스 기간 감사 + 수정 | 감사 + 제품 수정 | 사용자 명시 기간만 적용 | #75 |
| 24 | 2026-07-27 | **Phase 10 동일 문항 최종 회귀** | 동일문항 회귀 | **formal 97.50%, 뉴스 Recall 33.33%, 고위험 종목 무결성 결함 확인** | 원시 산출물 보존 PR #80 |
| 25 | 2026-07-27 | PR #76 종목 문맥 오염 방지 | 제품 수정 + smoke | 테스트 576 통과 | #76 |
| 26 | 2026-07-27 | 제품 QA(안내 렌더링·UI·주가·뉴스링크) | 브라우저 수동 | — | #77·#78·#79 |

---

## 3. 평가 데이터셋과 Gold 구축

근거: `backend/docs/rag/phase_8/PHASE_8_STEP1_EVALUATION_FOUNDATION.md`, `PHASE_8_LABEL_REVIEW.md`, `backend/scripts/phase8_build_dataset.py`, `backend/docs/rag/phase_8/eval/devset.json`·`holdout.json`

### 3.1 160문항 유형별 구성 (실제 JSON 재확인 값)

| 유형 | 개발셋 | 홀드아웃 | 합계 |
|---|---:|---:|---:|
| 금융용어 | 11 | 4 | 15 |
| 정확한 재무 숫자 | 19 | 6 | 25 |
| 뉴스 사건·영향 | 19 | 6 | 25 |
| 공시 설명·구조화 값 | 15 | 5 | 20 |
| 증권사 리포트 | 15 | 5 | 20 |
| 복수 기능 혼합 | 15 | 5 | 20 |
| 부정·제외·대조 | 11 | 4 | 15 |
| 현재 화면 문맥 | 7 | 3 | 10 |
| 답변 불가능·모호 | 8 | 2 | 10 |
| **합계** | **120** | **40** | **160** |

### 3.2 대상 종목

5개 종목이다. 실제 `stock_code` 분포(개발셋 / 홀드아웃):

| 종목 | 코드 | 개발셋 | 홀드아웃 |
|---|---|---:|---:|
| 삼성전자 | 005930 | 28 | 8 |
| SK하이닉스 | 000660 | 23 | 6 |
| 현대차 | 005380 | 20 | 6 |
| 한화오션 | 042660 | 16 | 9 |
| 두산에너빌리티 | 034020 | 13 | 4 |
| 종목 무관(용어 등) | null | 20 | 7 |

### 3.3 120/40 분할 방식과 이유

- 유형별 비율을 유지하며 **각 유형의 뒤 25%를 홀드아웃**으로 분리했다. 난수를 쓰지 않아 재현 가능하다.
- 홀드아웃 id는 `h-` 접두사로 구분한다.
- 이유: 개발셋으로 문제를 찾아 고치고, 홀드아웃은 **최종 평가 전까지 열지 않아** 튜닝 오염을 막는다.
- 검증기가 개발·홀드아웃 간 id 중복 0건, 질문 문자열 중복 0건을 확인했다.

### 3.4 질문과 Gold가 어떻게 생성됐는가

**RAG가 생성한 답변을 정답으로 쓰지 않았다.** 전부 DB 원본에서 유도했다.

| 유형 | Gold 출처 테이블 | 확정 방식 |
|---|---|---|
| 금융용어 | `rag_terms` | 표제어 실재 확인(`is_active=true`), `term:{표제어}` |
| 재무 | `financials` | **값을 라벨에 적지 않는다.** 기준 행만 지정하고 채점 시 DB 재조회 |
| 공시 | `structured_disclosures` | 실제 접수번호(`rcept_no`) |
| 뉴스 | `news_clusters` | 실제 사건(id·날짜·감성·기사 수) |
| 리포트 | `research_reports` | 실제 리포트(증권사·발행일·목표주가 `stated`) |

### 3.5 각 Gold가 참조한 DB 데이터와 식별자 (실제 라벨 예시)

`devset.json`에서 직접 인용:

- `fin-01` — `label_basis`: `financials 실제 행(thstrm_amount=43601051000000)`, `gold_sources[0].source_id`: `005930/2025/11011/CFS/영업이익/cumulative`
- `news-01` — `label_basis`: `news_clusters.id=7201 실재(요약 success, 기사 7건, 2026-07-26, 감성 positive). rag_documents.id=7557c820-…(is_current) 연결 확인, 활성 청크 1건을 정답 식별자로 확정. 종목 000660 일치.`
- `report-01` — `label_basis`: `research_reports.id=18f336cf-… 실재: 미래에셋증권 2026-07-14, 목표주가 4,200,000원(stated) … 목표주가는 전망값이며 실제 거래가가 아니다.`

### 3.6 재무 숫자는 직접 입력됐는가, DB 행을 참조했는가

**DB 행을 참조한다.** `expected_financial`에 `stock_code/account_name/business_year/report_period/amount_type/fs_div/value_kind`만 지정하고, 채점 시 `FactsService`로 기준 행을 다시 읽어 대조한다.

이유는 원문에 명시돼 있다 — *"사람이 옮겨 적을 때의 오타가 그대로 정답이 되기 때문이다."* (`PHASE_8_STEP1_EVALUATION_FOUNDATION.md` §4)

### 3.7 뉴스 canonical cluster 지정 방식

초기에는 Gold가 **RAG chunk UUID**였다. 같은 사건이 재색인되면 UUID가 바뀌어 Gold가 비현행이 되는 문제가 있었다(`h-news-23`은 cluster 7108이 유지되는 동안 chunk UUID가 `518f…`·`575e…` → `8fa2…` → `5683…`으로 변경).

PR #71에서 canonical 식별자를 `news_clusters.id`로 전환했다.

```json
{ "source_type": "news_event", "source_id": null, "canonical_id": "news_clusters.id=7108" }
```

- canonical 정답은 `news_clusters.id` 하나다.
- preflight가 그 cluster의 `is_current=true` document와 `is_active=true` chunk를 읽기 전용으로 해석한다.
- **다른 cluster는 자동 정답으로 인정하지 않는다.**
- strict Recall@K/Hit@1/MRR은 검색 결과의 cluster 순서와 canonical cluster를 비교한다. chunk UUID는 strict 적중 판정에 쓰지 않는다.

근거: `PHASE_8_STABLE_NEWS_GOLD.md`

### 3.8 event-equivalent 처리 방식

같은 사건이 여러 cluster로 쪼개진 경우를 위한 **보조 라벨**이다. `devset.json`/`holdout.json`의 `gold_sources`는 바꾸지 않고, 별도 파일 `eval/event_equivalent_approvals.json`에만 담는다.

승인된 것(개발셋 3건):

| case | strict Gold | 승인된 동등 cluster | 근거 |
|---|---|---|---|
| news-10 | 6974 | 7222, 7167 | 한화오션+레이도스 동일 계약 보도 |
| news-13 | 7182 | 7195 | 삼성전자 구글 협업 스마트안경 동일 사건 |
| news-18 | 6944 | 7193 | "마스가"·"1500억달러"·"한미 조선협력센터" 동일 식별어 |

**명시적 비승인 1건**: news-19(7117 "재산분할금 9440억 확정" vs 5611 "파기환송심 선고") — *"'선고'와 '확정'은 사건의 진행 단계가 다르므로 '회사명만 같다는 이유로 병합'을 피하기 위해 동일 사건으로 승인하지 않는다."*

**홀드아웃에는 event-equivalent 승인이 0건이다.** 그래서 Phase 8·9 홀드아웃에서 strict와 event-equivalent 수치가 항상 같다.

**코드상 event-equivalent의 정확한 성격** (`grader.py:367-412`, `:863-891`)

- **알고리즘적 사건 동등성 판정은 존재하지 않는다.** 임베딩 유사도·제목 매칭·날짜 창이 전혀 없다. **순수하게 사람이 작성한 ID 허용목록**이다.
- 분모는 strict와 **동일**하고(`:390-392`), 적중 판정만 넓힌다: `accepted_ids = {gold_doc, *approvals[case.id]}`, `hit = bool(accepted_ids & set(ranking))`(`:394-395`).
- 승인이 바꾸는 것은 `news_retrieval_event_equivalent` / `report_retrieval_event_equivalent` **뿐이다.** strict `news_retrieval`, `news_product_failure`(`:443`에서 strict로 재계산), `case_passed`는 **바뀌지 않는다.**
- 파일이 없으면 `{}`를 반환해(`:875-876`) event-equivalent가 strict와 동일해진다.
- **로더는 `case_id`와 `approved_equivalent_cluster_ids`만 읽는다**(`:881`, `:889`). 파일의 `strict_gold_cluster_id`·`basis`·`approved_by`·`explicitly_not_approved`는 **코드가 검증하지 않는다.** docstring도 이를 명시한다 — *"이 함수는 매핑의 출처를 검증하지 않으므로 호출부가 책임진다"*(`:379-381`). 즉 승인 근거의 보장은 **문서적 규율이지 코드적 강제가 아니다.**
- `per_type_metrics`(`phase8_final_evaluation_after_prompt.py:116-125`)는 승인 파일 경로를 넘기지 않으므로 **유형별 event-equivalent 수치는 strict와 같다.**

### 3.9 `needs_manual_review`와 `confirmed`의 의미

- `needs_manual_review` — 원본 근거를 확실히 확인할 수 없어 **임의로 채우지 않고 남겨둔** 상태. 최초 65건(뉴스 25 + 리포트 20 + 복합 20).
- `confirmed` — DB 원본 대조로 확정된 상태.

PR #54에서 65건 전부를 검토해 `confirmed`로 확정했고, 현재 `devset.json`+`holdout.json` 160문항의 `review_status`는 **전부 `confirmed`**(실제 JSON 재확인).

단, 복합 질문 20건은 *"정답 식별자 없음"을 명시한 상태로* 확정된 것이다. 하위 질문마다 정답 문서가 달라 단일 식별자를 만들 수 없기 때문이며, 이 20건은 검색 Recall 분모에서 제외되고 필수 Tool·입력 조건·출처 종류로만 채점된다.

### 3.10 독립적인 사람 라벨링이 수행됐는가 — **아니다**

이 결론은 세 가지 직접 증거에 기반한다.

**증거 1 — 사람 평가 CSV는 양식만 있고 비어 있다.**
`eval/human_review_rater1.csv`(35행)와 `human_review_rater2.csv`를 열어 확인한 결과, `case_id`·`질문`·`답변`·`제시된 출처`·`정답 근거`는 채워져 있으나 **7개 평가 점수 칼럼과 `치명적 오류`·`메모`가 전부 공란**이다. 예: `term-01` 행의 점수 칼럼이 모두 빈 값이다.

**증거 2 — 원문이 "양식만 생성"이라고 기록한다.**
`PHASE_8_STEP1_EVALUATION_FOUNDATION.md` §10: *"사람 평가 실제 수행(양식만 생성)"*을 **아직 실행하지 않은 항목**으로 분류했다.

**증거 3 — event-equivalent 승인자가 Agent 보조 검토다.**
`event_equivalent_approvals.json`의 `approved_by` 필드: **`"agent-assisted manual review (Phase 8 news final correction round)"`**

따라서:

- **"사람 라벨링 데이터셋"이라고 표현할 수 없다.**
- **"전문가가 검수한 Gold"라고 표현할 수 없다.**
- 정확한 표현은 **"DB 원본에서 결정적으로 유도하고, Claude Code/Codex가 원본 대조로 검토·확정한 Gold"**다.
- Gold 자체는 검증 가능하다 — `phase8_validate_dataset.py`가 24항목을 통과시키고, 실재하지 않는 uuid를 넣으면 실제로 실패를 잡는다(PR #54에서 고의 주입 테스트 확인).

---

## 4. 실제 채점 방식

근거: `backend/app/eval/grader.py`, `metrics.py`, `llm_judge.py`, `backend/scripts/phase8_final_evaluation_after_prompt.py`

### 4.1 automatic formal-condition pass의 실제 구성 (직접 코드 확인)

최종 통과 boolean은 `backend/scripts/phase8_final_evaluation_after_prompt.py::case_passed`(85–113행)에서 계산한다. **조건은 정확히 11개다.**

```python
def case_passed(case, grade) -> tuple[bool, list[str]]:
    fails = []
    if not grade.passed_required_tools:            fails.append("required_tool_missing")
    if grade.forbidden_violated:                   fails.append("forbidden_tool_called")
    if grade.arg_results and not all(...):         fails.append("tool_arg_mismatch")
    if grade.exclusion_violations:                 fails.append("exclusion_violated")
    if grade.other_stock_sources:                  fails.append("other_stock_source")
    if grade.overclaim:                            fails.append("overclaim")
    if grade.unanswerable_handled is False:        fails.append("false_answer_on_unanswerable")
    if grade.financial_grade and not exact:        fails.append("financial_value_mismatch")
    if any(not n.get("matched") ...):              fails.append("number_mismatch")
    if grade.period_ok is False:                   fails.append("period_mismatch")
    if grade.trading_day_ok is False:              fails.append("trading_day_mismatch")
    return (not fails), fails
```

**formal pass 조건에 들어가는 것 / 안 들어가는 것**

| 항목 | formal boolean 포함 | 근거 |
|---|---|---|
| 필수 Tool 호출 | **예** | `case_passed` 91–92행 |
| 금지 Tool 미호출 | **예** | 93–94행 |
| Tool 인자 정확도 | **예** | 95–96행 |
| 제외 조건 준수 | 예 (judge 판정 사용) | 97–98행 |
| 타 종목 미혼입 | 예 | 99–100행 |
| 과도한 단정 없음 | 예 | 101–102행 |
| 답변 불가 정상 처리 | 예 (judge 판정 사용) | 103–104행 |
| 재무값·숫자 정확도 | **예** | 105–108행 |
| 기간·거래일 정확도 | **예** | 109–112행 |
| **Tool status(ok/error/null)** | **아니오** | 함수 전체에 status 판정이 없다 |
| **뉴스 canonical Gold cluster 적중** | **아니오** | `grade_case` 676–680행에서 개별 Gold hit 채점을 건너뛰고 별도 retrieval 지표로 이동 |
| **뉴스 strict Recall@K** | **아니오** | `aggregate` 1006행의 별도 집계 |
| **뉴스 event-equivalent Recall@K** | **아니오** | `aggregate` 1017–1019행 |
| **citation coverage** | **아니오** | `aggregate` 991–995행 |
| **Solar Judge grounded** | **아니오** | 참고 지표. judge가 채운 exclusion·overclaim·unanswerable만 사용 |
| 단위 정확도 | 독립 조건 아님 | aggregate에는 기록되지만 `unit_ok` 자체는 formal 조건이 아님 |

근거: `backend/docs/rag/phase_10/PHASE_10_NEWS_RETRIEVAL_AUDIT.md`(코드 라인 감사) + 본 조사의 `case_passed` 직접 확인

### 4.2 검색 지표 (Recall@K / Hit@1 / MRR)

PR #63 감사 이후 확정된 계산 방식(`grader.py:299-364` `document_recall_stats`):

- `document_ranking(record)`(`grader.py:94-110`) — `record.sources`(**Tool이 반환한 실제 검색 순위 보존**)를 부모 문서 ID로 변환하고, 같은 문서의 중복 청크는 첫 등장 순위만 남긴다. docstring이 `record.retrieved_ids`를 쓰면 안 되는 이유(정렬된 집합이라 Hit@1/MRR이 알파벳 잡음이 된다)를 명시한다.
- 뉴스/리포트 분리는 **ID 이름공간 접두사**로 한다. `_normalize_doc_id`(`:43-50`)가 `news:<int>` 또는 `report:<uuid>`를 만들고, `:324`가 `gold_doc.startswith(f"{kind}:")`를 요구한다. `aggregate`가 두 번 호출한다(`:1006`, `:1007`) — **두 지표는 분모를 공유하지 않는다.**
- 분모(`n_eval`, `:334`) = **라벨에서 해당 종류의 Gold 부모 문서 ID가 나오는 문항 수.** 정답 식별자가 없는 복합 질문 20건, 구조화 조회 문항은 자동 제외된다.
- `Recall@K = count(gold_doc in ranking) / n_eval` (`:329`, `:357`)
- `Hit@1 = count(rank == 1) / n_eval` (`:339-340`, `:358`)
- `MRR = Σ(1/rank) / n_eval` (`:338`, `:359`)

**반드시 알아야 할 4가지 정확한 사실** (코드 직접 확인)

1. **`recall_at_k`에 실제 K가 없다.** `:329`의 `hit = gold_doc in ranking`은 반환된 **전체** 목록을 검사한다. 실효 K는 Agent가 실제로 반환한 문서 수다(`search_news`·`search_research_reports` 기본 `limit=5`, 최대 12, 호출 여러 번이면 누적). **지표 이름이 실제보다 정밀함을 함의한다.** 정확한 서술은 "반환된 전체 출처에 대한 Recall(K = Agent가 실제로 노출한 고유 부모 문서 수, 검색 1회당 보통 ≤5)"이다.
2. **문항당 Gold 문서는 1개만 채점된다.** `_gold_document_id_for_case`(`:143-149`)가 **첫 번째** 매치에서 반환한다. Gold가 여럿인 문항은 하나로만 채점되며, 이 때문에 **Recall@K ≡ Hit@K**가 된다.
3. **관용(forgiveness) 로직은 적용되지 않는다.** `_doc_miss_is_not_retriever_fault`(`:113-140`)는 "검증기가 답변을 지웠다"·"같은 문서의 다른 청크"를 용서하려고 만들어졌지만 **`document_recall_stats`가 호출하지 않는다**(호출처는 분석 스크립트뿐). `:330-333`은 문자 그대로 `pass`인 no-op이다. 따라서 보고된 strict Recall은 **관용 없는 순수 문서 ID 일치**다. 주석(`:308-309`)이 서술하는 관용은 *분석 스크립트*의 것이므로, strict Recall을 "검증기 실패 보정됨"으로 서술하면 안 된다.
4. **strict와 event-equivalent가 타종목 혼입을 다르게 취급한다.** strict(`:329`)는 무시하고, event-equivalent(`:396-402`)는 혼입 시 적중을 취소한다. 따라서 **event-equivalent Recall이 strict의 상위집합이라는 보장이 없다.**

**리포트 페이지 정확도**(`:460-479`)는 분모가 다르다 — Gold 소스 중 `page`가 있는 항목 수(문항당 여러 건 가능). 게다가 페이지가 **올바른 리포트 문서에 속하는지 요구하지 않는다**(`:474-477`).

**미적중 분류**(`:341-349`) — `gold_out_of_relative_range`(`:182-207`)가 실제 발행된 `relative_period` 인자를 운영 함수 `resolve_relative_date_range`로 다시 해석해 `stale_gold` / `retriever_failure`로 나눈다. **strict 수치 자체는 이 분류로 보정되지 않는다**(`:343-345` 주석).

### 4.3 구조화 조회(structured_lookup)와 문서 Recall의 차이

- 문서 Recall — 뉴스·리포트처럼 **의미 검색으로 문서를 찾는** 경로.
- `structured_lookup.row_hit_rate` — 재무·공시·용어처럼 **DB 행/키를 정확히 지정해 읽는** 경로. 청크·행 단위 정확 일치.

두 지표는 분모가 다르므로 섞어 인용할 수 없다.

### 4.4 Solar Judge

`backend/app/eval/llm_judge.py`

- 모델: `solar-pro3-260323` (`EVAL_JUDGE_MODEL`), 엔드포인트 `https://api.upstage.ai/v1`
- temperature=0, JSON 스키마 강제, 결과 캐시(동일 입력 재호출 안 함)
- 판정 필드는 **3개뿐**: `handled_correctly`, `grounded`, `exclusion_respected` (+`reason`)
- `overclaim`은 judge가 아니라 코드 채점이다.
- 실패 시 기존 키워드 채점으로 폴백한다.

**도입 이유**: 원래 자연어 판정이 한국어 키워드 부분 문자열 검사였다. `"확인할 수 없습니다"`는 통과하지만 뜻이 같은 `"아직 공시되지 않았습니다"`는 실패했다. 코드 주석이 위험을 명시한다 — *"그러면 제품 프롬프트를 채점기 키워드에 맞춰 쓰게 되는 역방향 압력이 생긴다(평가지표를 속이는 것)."*

**구조적 한계 (매우 중요)**: judge 입력에는 **출처의 제목·종류·날짜만** 들어가고 본문·수치는 들어가지 않는다. 프롬프트가 명시적으로 지시한다 — *"답변의 숫자가 근거 목록에 안 보인다는 이유로 false를 주면 안 된다."* 따라서 `grounded=true`는 **"숫자가 근거와 일치한다"는 뜻이 아니다.** 이것이 `grounded`를 통과 조건에서 제외한 이유다.

### 4.5 재무 숫자 채점

- 기대값을 라벨에 적지 않는다. `resolve_expected_financial`(`grader.py:582-607`)이 **운영 Tool 진입점** `run_get_financial_facts` → `FactsService.get_financials`를 호출해 DB 기준 행을 읽는다.
- **주의**: Gold가 Agent와 **같은 코드 경로**로 생성되므로, `run_get_financial_facts`에 결함이 있으면 Gold와 답변이 함께 움직인다. 이 경로의 독립성은 보장되지 않는다.
- 복수 해석 허용: `[expected_financial, *acceptable_financials]`를 모두 채점해 `exact=True`인 첫 항목을 채택한다(`:715-728`).

**숫자 관용도가 매우 넓다** (`metrics.py:56-75` `number_matches`)

`43,601,051,000,000` vs 답변 `"43조 6,010억원"`의 실제 판정 경로:
1. 한글 단위 합산 → `43*1e12 + 6010*1e8 = 43,601,000,000,000`
2. 정확 비교(`:63`) **실패** (51,000,000 차이, tolerance 기본 0.0)
3. `scale=1e8`: `round(값/1e8)=436011` vs `436010.0` → 차 1.0 ≥ 0.5 **실패**
4. `scale=1e12`: `round(값/1e12)=44` vs `43.601` → 차 **0.399 < 0.5 → 통과**(`:71`)

즉 이 케이스를 살린 것은 **조 단위 반올림**이며, 실질 허용 폭이 **1조 이상 값에 대해 ±0.5조(±5,000억원)**다. 따라서 `"43조"`, `"44조"`, `"43조 9,000억"`도 같은 Gold에 통과한다. **`number_exact_match`는 큰 금액에 대해 exact가 아니다.**

추가 주의: `normalize_number_text`(`metrics.py:30-53`)가 한글 단위 합산값 외에 **맨숫자도 전부** 후보에 넣으므로(`43.0`, `6010.0`), 날짜·인용 표시의 숫자까지 후보가 되어 오탐(false positive)이 가능하다.

**`unit_ok`는 사실상 상수 참이다.** `grader.py:623`: `(gold.get("unit") or "원") in answer or "조" in answer or "억" in answer`. DB unit은 항상 `"원"`이므로 "원"·"조"·"억" 중 하나만 있으면 통과한다.

**`period_ok`가 두 정의를 공유한다.** `grader.py:741`은 `all`을, `_grade_financial_answer`(`:615`)는 `any`를 쓰는데 둘이 같은 `period_accuracy` 비율로 합산된다. 게다가 `:736-740`이 토큰을 "질문 또는 답변에 이미 나타난 것"으로 필터링하므로, 요구 기간어가 양쪽에 다 없으면 `None`(실패 아님)이다. 즉 `period_accuracy`는 **"필요한 기간을 말했는가"가 아니라 "틀린 기간을 말했는가"**에 가깝다.

- 자연어는 완전 일치를 강요하지 않고 핵심어 70% 이상 등장으로 판정한다.

### 4.5-B 그 밖에 formal pass에 들어가지 않는 것 (코드 확인)

`case_passed`는 `(case, grade)`만 받고 **`RunRecord`를 보지 않는다.** 이 한 가지 사실이 아래 제외를 대부분 설명한다.

- `grade.unnecessary_tools`(`:668-669`) — 계산되지만 통과 조건 아님
- `grade.fact_hits`/`fact_total`(핵심 사실 포함률) — 통과 조건 아님
- `grade.gold_source_hits`(용어·재무·공시의 정확 행 Gold) — **통과 조건 아님.** `structured_lookup.row_hit_rate`는 집계 전용이다
- `overclaim`은 **judge 판정이 아니다.** `has_overclaim(record.answer)`(`:771`)로 judge 분기 **밖**에서 계산되는 키워드 부분문자열 검사다(`metrics.py:263-272`의 8개 패턴). `"보장"`이 맨 부분문자열이라 "예금자보장"·"보장성보험" 같은 정당한 문장도 걸린다
- `arg_results`에 **탈출구 2개**가 있다 — ① `required_tools_any`의 대체 Tool이 호출됐으면 해당 키를 기록하지 않음(`:553-554`) ② `args`가 `None`인 호출이 하나라도 있으면 인자 채점 전체를 건너뜀(`:557-559`, recorder 미부착 시)

### 4.5-C 통과율 분모 계산의 미묘한 점

`phase8_final_evaluation_after_prompt.py:216-228`. 환경 실패로 분류된 문항은 분모에서 빠진다(`n_eligible = len(ran_cases) - len(env_ids)`). 그런데 `:220`에서 **환경 실패인데 `case_passed`를 통과한 문항은 `continue`되어 분자·분모 어디에도 안 들어가면서 이미 분모에서 차감된 상태**다. 즉 환경 플래그가 붙고 통과한 문항은 조용히 양쪽에서 사라진다.

`is_environment_failure`(`:71-82`)에서 Tool status가 쓰이는 유일한 곳인데, 조건이 `bad and not rec.answer.strip()`이다 — 즉 **Tool이 `error`를 반환해도 모델이 텍스트를 만들어냈으면 환경 실패로도 잡히지 않는다.**

### 4.5-D 키워드 폴백의 위험한 기본값

judge 실패 시 폴백에서, `_handled_as_unanswerable`(`grader.py:846-860`)은 `stop_reason in ("timeout","step_limit","error","runner_error")`이면 **자동 통과**시킨다(`:854-855`). 즉 **타임아웃된 실행이 "답변 불가를 올바르게 처리했다"로 채점된다.** 환경 실패 제외 규칙과 겹치면 이 문항은 조건 7 자동 통과 + 분모 제외가 동시에 일어날 수 있다.

또한 judge의 `grounded`는 응답에서 누락되면 **기본값 `True`**로 기록된다(`llm_judge.py:238`).

### 4.6 지연·비용

- 비용 단가: 입력 `$0.40` / 출력 `$1.60` per 1M tokens (Phase 5.5 `evaluate_agent.py`에서 승계)
- P50/P95는 문항별 총 지연시간의 백분위

### 4.7 null과 0.0의 구분

**분모가 0인 지표는 `0.0`이 아니라 `null`로 낸다.** "못 잰 것"과 "0점인 것"을 구분하기 위한 설계다. 예: 홀드아웃 금융용어 유형은 뉴스 Gold가 없어 `news_retrieval.recall_at_k = null`이다.

---

## 5. 실험별 문제·수치·수정·개선 과정

각 실험을 요구된 12개 열로 정리한다.

### 실험 1 — 뉴스 Retriever 단독 비교 실험 (Phase 3) ★ 유일한 진짜 A/B

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 3 |
| 당시 문제 | Phase 2가 **의미 검색 단독**(`rag_search_semantic`, pgvector 코사인)으로만 출고됐다. 정확 명칭·약어·종목코드·숫자 질의를 임베딩만으로는 회수하지 못했다 |
| 실험 목적 | Retriever 랭킹 방식 선택 (**Agent·LLM 없이 검색기만**) |
| 사용 데이터 | DB에서 자동 생성. `rag_documents`(`source_type='news_event'`, `is_current=true`)를 `published_at DESC`로 정렬해 샘플링. **개발 40건(offset 0) / 홀드아웃 40건(offset 200)으로 분리** |
| 질의 생성 방식 | 사건당 2종 — ① `nl_title`(사건 `title` 원문, 사건당 1개 → 40개) ② `exact_token`(변별력 토큰 최대 2개, 조건 미달 시 생성 안 함 → 12/17개). 토큰 규칙: 영문 ≥3자 또는 숫자 ≥4자, 종목명 부분문자열 제외, 코퍼스 DF 비율 >5% 제외 |
| Gold 정의 | **자기 회수(self-retrieval)** — 질의를 만든 원본 사건이 top-8에 있는가. 단일 Gold이므로 `recall@8`은 실질적으로 Hit@8(Success@8)이다 |
| 비교 조건 | **2개 arm만.** A=`SemanticRetriever`(`rag_search_semantic`) vs B=`HybridRetriever`(`rag_search_hybrid`, 의미+렉시컬+RRF). 양쪽 공통: `top_k=8`, 의미 후보 24, 렉시컬 후보 24, `rrf_k=50`, 가중치 1.0:1.0, 문서당 최대 2청크 |
| **BM25 없음** | 한국어 형태소 분석기 미설치로 `pg_trgm`(`word_similarity`+`ILIKE`)을 렉시컬 arm으로 사용. **저장소에 BM25 arm은 존재하지 않는다** |
| **reranker 없음** | `RAG_RERANKER_ENABLED=false`, 실행 계획의 `- [ ] reranker A/B`가 미체크. **한 번도 실행되지 않았다** |

**개발 결과** (`phase_3/eval_result.json` 직접 검증)

| 질의 유형 | 지표 | 의미검색 단독 | 하이브리드 |
|---|---|---:|---:|
| nl_title (n=40) | recall@8 | 0.975 | 0.975 |
| nl_title (n=40) | MRR | 0.938 | **0.963** |
| exact_token (n=12) | recall@8 | **0.25** | **0.917** |
| exact_token (n=12) | MRR | 0.181 | **0.449** |
| — | 평균 지연 | **119ms** | **607ms** |
| — | 개선/악화 문항 | — | 11 / 2 |

**홀드아웃 결과** (`phase_3/holdout_result.json`, offset 200으로 개발셋과 분리)

| 질의 유형 | 지표 | 의미검색 단독 | 하이브리드 |
|---|---|---:|---:|
| nl_title (n=40) | recall@8 | 0.975 | **1.0** |
| nl_title (n=40) | MRR | 0.956 | **0.988** |
| exact_token (n=17) | recall@8 | **0.647** | **0.941** |
| exact_token (n=17) | MRR | 0.48 | **0.651** |
| — | 평균 지연 | 179ms | 797ms |
| — | 개선/악화 문항 | — | 11 / 2 |

| 항목 | 내용 |
|---|---|
| 발견한 원인 (실험 중) | 1차 하이브리드는 정확명칭 recall@8이 **0.50**에 그쳤다. 원인 2개 — ① **평가 방법론 결함**: 질의의 절반이 "SK"·"AI"·"ETF" 같은 조각이라 정확명칭이 아니었다 ② **Retriever 결함**: 렉시컬 랭킹이 `word_similarity`만 써서 정확 부분일치가 유사 사건들에 밀려 후보에서 탈락했다 |
| 수정 내용 | **Fix A(Retriever)**: `migrations/0018_rag_hybrid_lexical_exact_first.sql` — 렉시컬 랭킹을 2단계로(정확 부분일치 ILIKE 우선 → word_similarity). 0017을 수정하지 않고 `CREATE OR REPLACE`로 이력 보존 **Fix B(평가 방법론)**: 종목명 제외 + DF ≤5% + 최소 3자 규칙 |
| 수정 후 결과 | 정확명칭 recall@8 **0.50 → 0.917**. 홀드아웃에서 같은 패턴 재현(개선 11/악화 2가 양쪽 동일) |
| 결과의 정확한 의미 | **검색기 단독 성능이다. Agent 전체 정확도가 아니다.** Gold가 자기 회수 단일 정답이므로 `recall@8`은 Hit@8과 같다 |
| 결론 | 하이브리드를 운영 뉴스 Retriever로 채택. 지연 5배 증가를 알려진 비용으로 수용(배치 최적화는 미실시). pytest 95 passed |
| 남은 한계 | ① 이 평가셋은 Phase 8의 160문항과 **완전히 다른 별개 데이터**다 ② exact_token n=12·17로 표본이 매우 작고 신뢰구간이 없다 ③ nDCG·Hit@1·Precision@K 미측정 ④ RRF 가중치·`rrf_k`·`top_k` 스윕 미실시(1.0:1.0, 50, 8 단일 조건) ⑤ 초기 0.50의 원시 산출물이 없다(두 JSON 모두 수정 후) |
| 근거 파일 | `phase_3/PHASE_3_HYBRID_SEARCH.md`, `PHASE_3_COMPLETION.md`, `eval_result.json`, `holdout_result.json`, `scripts/rag_phase3_eval.py`(top_k :126, Gold :102-104, 지표 :114-118, 토큰 규칙 :31-56), `app/rag/retrieval.py`(Semantic :88-123, Hybrid :126-215), `migrations/0018_*.sql` |

### 실험 2 — 리포트 Retriever 단독 실험 (Phase 5)

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 5 |
| 당시 문제 | 증권사 리포트 244건을 적재했으나 "QA 연결·리포트 검색 연결은 미진행" 상태였다. 파싱·색인 품질도 미검증이었다 |
| 실험 목적 | ① 리포트 파서·색인 검증(3단계 dry-run) ② `search_research_reports`의 종목 정확성·타종목 미혼입·출처 페이지 확인 |
| 사용 데이터 | 실제 리포트 PDF 244건. 검색 질의는 5종목 × 5유형 템플릿 = **25개** 자동 생성 |
| **비교 조건** | **비교 대상이 없다. 단일 조건이다.** 하이브리드만 구성했고 의미검색 단독 arm·BM25 arm·reranker·가중치 스윕이 **전부 없다.** 따라서 **A/B 실험이 아니다** |
| Gold 정의 | **종목 단위**(문서 단위 아님) — top-8 중 하나라도 `stock_code`가 일치하면 적중. 같은 종목의 **엉뚱한 리포트**를 가져와도 적중으로 계산된다 |
| 주요 결과 수치 | **Recall@8 = 100% (25/25)**, 타종목 혼입 **0**, 출처 페이지 유효 **40/40** |
| 파싱 결과 | STEP1: PDF 244건, 파일명 파싱 244/244, 텍스트 추출 243/244. STEP3: 243 성공/1 부분/0 실패, 1,877페이지, 54,595 블록, 1,936 테이블, 6,063 A/E/F 값, **원문 숫자 일치 25,109/26,304 = 95.46%**, source_page 검출 **53.7%**(131/244, 나머지는 pdf_page 폴백) |
| 최종 적재 | research_reports 244, rag_documents 244, **rag_chunks 4,351 → 활성 4,350**. 임베딩 비용 약 $0.22 |
| 발견한 원인 | 페이지 컬럼(`page_start`/`page_end`)이 채워지지 않음 — 페이지 정보는 `source_locator` JSON에만 존재 |
| 수정 내용 | 색인 파이프라인 정비, 페이지는 `source_locator.page_number` 사용. `search_research_reports`를 QA에 연결 |
| 결과의 정확한 의미 | **파서·색인 검증 + 종목 단위 기능 확인이다. 검색 랭킹 품질 측정이 아니다.** Gold가 종목 단위이므로 100%가 "정확한 리포트를 찾았다"를 뜻하지 않는다 |
| 남은 한계 | ① **결과 JSON이 없다.** 스크립트가 stdout에만 출력했고 산출물이 커밋되지 않았다 — 유형별 분해 수치는 확인되지 않음 ② MRR·nDCG·Hit@1·Precision 미측정 ③ 이 수치는 커밋 `ca30504` 시점 코드 기준이며 현재 `research_reports.py`는 `fetch_k = base_k * 4` 등으로 변경됨 ④ "40/40"의 분모는 질의 수(25)도 top-8 총합(200)도 아닌 **동일종목 적중 건수**로, 질의당 비율이 아니다 ⑤ `page_start`/`page_end` 컬럼은 4,350건 중 0건이 채워져 있다. `target_price_source_chunk_id`도 비어 있다 |
| 근거 파일 | `phase_5/PHASE_5_STEP1~3_*.md`(파싱), `RAG_PHASE_EXECUTION_PLAN.md:1480-1481` + 커밋 `ca30504`(검색 수치 — **유일한 기록**), `scripts/phase5_eval_report_search.py`(TOP_K :24, Gold :55-57), `PHASE_8_LABEL_REVIEW.md` §7 |

### 실험 2-B — 참고: 뉴스 색인(Phase 2)과 용어 적재(Phase 4)

둘 다 **A/B 실험이 아니다.** 색인·적재 검증이다.

| 항목 | Phase 2 뉴스 색인 | Phase 4 BOK 용어 |
|---|---|---|
| 대상 | 활성 사건 2,940건 | 한국은행 『2026 경제금융용어 800선』 428p |
| 임베딩 | `solar-embedding-2-passage/query`, 1024차원 | 동일 |
| 결과 | 현행 문서 2,940 / 활성 청크 **3,112**, 실패 1건→복구 후 0, 약 **$0.1037**(약 107만 토큰) | canonical 항목 **789**개 적재, 실패 0, 약 **$0.0163**. 기존 시드 6개 보존 → 총 **795** |
| 검색 확인 | trial 100건: `self_in_top_rate` **1.0**(6질의 전부 1위), 잘못된 인용 0. 전체 색인 후 5종목 **5/5**, 지연 97~318ms | 6종 기능 확인(정확·약어·영문명·슬래시·자연어×2) **6/6 통과** |
| 정확한 의미 | **자기 회수 스모크다. 검색 품질 A/B가 아니다** | **기능 확인이다. Recall/MRR 측정이 아니다** |
| 근거 | `phase_2/trial_100_result.json`, `full_index_result.json` | `phase_4/bok_load_verification.md`, `bok_dryrun_full.json`(789건) |

### 실험 3 — 주가 Tool 초기 계약 테스트 (Phase 6)

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 6, 2026-07-25 |
| 당시 문제 | 실제 주가와 증권사 목표주가가 혼동될 위험, Agent가 직접 산술을 하면 검증 불가 |
| 실험 목적 | 읽기 전용 주가 Tool 2개의 입출력 계약 확정·검증 |
| 사용 데이터 | 실제 토스증권 Open API + 주가 케이스 5건(`phase_5_5/eval/devset.json`) |
| 비교 조건 | 정상 2종목·휴장일 경계·없는 종목·200개 페이징 경계·캐시 재호출 |
| 주요 결과 수치 | 주가 5케이스 **전부 통과**. 회귀 4/4 유지. pytest **288 통과**. 운영 smoke 10문 전부 `agent=true`·`completed` |
| 발견한 원인 | (계약 설계) 수익률을 Agent가 계산하면 검증 불가 |
| 수정 내용 | `return_pct = (end_close/start_close - 1) * 100`을 `StockPriceService` **한 곳에서만** 계산. 거래일 스냅 규칙 명시. 30초 캐시·429 제한 재시도·페이지 상한 4 |
| 수정 후 결과 | 계산 Exact Match 확인 — 1m -25.63%(339,500→252,500), event +24.43%(219,000→272,500), +28.31%(222,500→285,500). Agent 직접 산술 0건 |
| 결과의 정확한 의미 | **Tool 계약·계산 정확성 검증이다. 주가 데이터 자체의 정확성 검증 완료가 아니다.** |
| 남은 한계 | 429 rate limit, 발표일 미상인 다단계 사건 질문, 목표주가 혼입(validator가 제거), 5종목 게이트, IP 허용목록 의존. 없는 종목(999999) 답변에 검증기 오탐 1건 |
| 근거 파일 | `phase_6/PHASE_6_COMPLETION.md`, PR #41 |

### 실험 4 — 160문항 평가 데이터셋 구축 (PR #52)

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 8 1단계, 2026-07-26 |
| 당시 문제 | 기존 평가셋이 27문항뿐이어서 유형별 성능을 판단할 수 없었다 |
| 실험 목적 | 160문항 정식 스키마 + 정답 라벨 + 평가 실행기·채점기 구축 |
| 사용 데이터 | DB 원본(`rag_terms`·`financials`·`structured_disclosures`·`news_clusters`·`research_reports`) |
| 비교 조건 | 정적 검증 19항목 + dry-run 9문항(실행기 검증용) |
| 주요 결과 수치 | 정적 검증 **19/19 통과**. dry-run 9문항: 필수Tool 1.0 / 인자 1.0 / Recall@K 0.67 / P50 3.5s / $0.0047 per query. 단위테스트 **36개 통과** |
| 발견한 원인 | dry-run이 **평가 코드 결함 3건**을 잡았다 (제품 무관) |
| 수정 내용 | ① 제외 조건 오탐(`"실적 관련 내용은 제외했습니다"`를 위반으로 셈) → 문장 단위 부정 판정 ② `expected_financial`이 채점기에 미연결 → `FactsService` 재조회 연결 ③ 라벨 식별자 형식 오류(`/누적` → `/cumulative`) |
| 수정 후 결과 | ③ 수정으로 검색 Recall 0.33 → 0.67 |
| 결과의 정확한 의미 | **실행기가 동작한다는 검증이다. 9문항이므로 성능 수치가 아니다.** |
| 남은 한계 | `term-01`에서 검증기 오탐 1건 관찰(용어 설명의 예시 숫자를 재무 수치로 오인) — 수정하지 않고 기록만 남김 |
| 근거 파일 | `PHASE_8_STEP1_EVALUATION_FOUNDATION.md`, PR #52 |

### 실험 5 — 120/40 분리와 라벨 검토 (PR #52·#54)

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 8, 2026-07-26 |
| 당시 문제 | 원본 근거를 확정할 수 없는 라벨 65건이 남아 검색 Recall을 계산할 수 없었다 |
| 실험 목적 | `needs_manual_review` 65건을 DB 원본 대조로 확정 |
| 사용 데이터 | `news_clusters`, `research_reports`, `rag_documents`, `rag_chunks` |
| 비교 조건 | **RAG 답변 미사용, 검색 미실행.** DB에서 결정적으로 유도되는 식별자만 확정 |
| 주요 결과 수치 | 65건 검토 → **65건 확정, 미확정 0건**. 뉴스 28청크·리포트 62청크 생성. 검증 **24/24 통과**. 단위테스트 15개 통과 |
| 발견한 원인 | 복합 질문 20건은 하위 질문마다 정답 문서가 달라 단일 식별자 생성 불가 |
| 수정 내용 | 뉴스는 사건의 활성 청크 **전부**를 정답 후보로 남김(1건만 고르면 임의 선택). 리포트는 목표주가 숫자가 본문에 실재하는 청크만. 복합은 식별자 없음을 명시 |
| 수정 후 결과 | 검색 Recall 분모 = 뉴스 25 + 리포트 20 + 재무/공시/용어 60 |
| 결과의 정확한 의미 | **DB 대조 검토다. 독립적인 사람 라벨링이 아니다** (§3.10) |
| 남은 한계 | 운영 코드 문제 3건 기록만 함 — 리포트 페이지 컬럼 전부 NULL, `target_price_source_chunk_id` 비어 있음, 목표주가 근거 청크가 없는 리포트 존재(하나증권 360,000 / 미래에셋 70,000) |
| 근거 파일 | `PHASE_8_LABEL_REVIEW.md`, PR #54 |

### 실험 6 — 평가 실행기 dry-run

실험 4에 포함(위 표 참조). dry-run 9문항은 각 주요 유형 1개씩 **개발셋에서만** 선정했고, SSE 계약(`agent_start → tool_start/tool_end ×2 → sources → delta → done`)을 확인했다.

### 실험 7 — 개발셋 최초 baseline (round1, PR #55)

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 8, 2026-07-26 |
| 당시 문제 | 제품의 실제 성능을 유형별로 측정한 적이 없었다 |
| 실험 목적 | 개발셋 120문항 1회 실행 + 실패 분석. **운영 코드 무수정** |
| 사용 데이터 | `devset.json` 120문항. 홀드아웃은 파일을 열지도 않음 |
| 비교 조건 | 단일 실행. 외부 API 오류 0건이라 전부 제품 동작 결과 |
| 주요 결과 수치 | 524초 / $0.546. **무결점 42/120**, 실패 78/120. 필수Tool 0.945 / 인자정확도 0.873 / 복합완료 0.833 / **뉴스+리포트 통합 Recall@K 0.333** / Hit@1 0.304 / MRR 0.375 / 숫자EM 0.737 / 단위 0.789 / 기간 0.711 / coverage 0.856. 제외조건 위반 4건, 근거없는 숫자 5건 |
| 발견한 원인 | 유형별로 **공시 Recall 0.067**, 리포트 Recall 0.125가 극단적으로 낮음. 인자 정확도가 공시에서 0.600 |
| 수정 내용 | (이 라운드는 측정만) |
| 수정 후 결과 | → 실험 8로 이어짐 |
| 결과의 정확한 의미 | **개발셋 수치다. 튜닝에 사용한 데이터이므로 일반화 성능이 아니다.** |
| 남은 한계 | 이 시점 Recall 정의는 뉴스·리포트를 합쳐 청크 단위로 계산한 구(舊) 정의다 — 이후 라운드와 직접 비교 불가 |
| 근거 파일 | `PHASE_8_DEV_BASELINE.md`, `eval/baseline_dev_metrics_round1.json`, PR #55 |

### 실험 8 — 개발셋 문제 수정 후 결과 (round2·3·final-dev, PR #57~#62)

3차례 교정과 재실행을 거쳤다.

| 라운드 | 교정 내용 | PR |
|---|---|---|
| round2 | **1차 교정** — 검증기 오탐, Tool 입력 계약, 평가기 수정 | #57 → #58 |
| round3 | **2차 교정** — 뉴스 검색 종료일 경계 결함 수정 | #59 → #60 |
| final-dev | **3차 교정** — 공시 정렬 tie-break(`rcept_no` 2차 정렬), 리포트 검색 결함, 평가기 부정 표현 오탐 | #61 → #62 |

**개발셋 라운드별 지표 비교** (metrics JSON 직접 확인)

| 지표 | round1 | round2 | round3 | final-dev |
|---|---:|---:|---:|---:|
| n | 120 | 120 | 120 | 120 |
| 무결점 문항 | 42* | 85 | 96 | 89 |
| 고유 실패 문항 | 78* | 35 | 24 | 31 |
| 필수 Tool 호출률 | 0.9449 | 0.9528 | **1.0** | 0.9843 |
| Tool 인자 정확도 | 0.8733 | 0.9533 | **1.0** | 0.9866 |
| 복합 질문 완료율 | 0.8333 | 0.8333 | **1.0** | **1.0** |
| 숫자 Exact Match | 0.7368 | 0.9474 | **1.0** | **1.0** |
| 단위 정확도 | 0.7895 | 0.9474 | **1.0** | **1.0** |
| 기간 정확도 | 0.7105 | **1.0** | **1.0** | **1.0** |
| 구조화 조회 row_hit | — | 0.9556 | 0.9778 | 0.8222 |
| citation coverage | 0.8559 | 0.982 | 0.9554 | 0.9464 |
| 근거 없는 숫자 | 5 | 3 | 3 | 5 |
| 제외 조건 위반 | 4 | 2 | 4 | 2 |
| 존재하지 않는 출처 | 0 | 0 | 0 | 0 |
| 타 종목 혼입 | 0 | 0 | 0 | 0 |
| P50 / P95 (ms) | 3741 / 9123 | 3402 / 7849 | 4101 / 7772 | 3766 / 8038 |
| 문항당 비용 | $0.004554 | $0.005019 | $0.005337 | $0.005426 |
| 문서검색 Recall@K(공식) | 0.3333 | 0.0† | 0.0† | 0.0† |

\* round1 문서는 무결점 42/실패 78로 기록하고, `PHASE_8_FINAL_DEV_EVALUATION.md` §4 비교표는 round1을 73/47로 적었다. **문서 간 불일치**이며 §10에서 다룬다.
† **집계 결함**. §5 실험 9 참조.

**round3 → final-dev에서 무결점이 96→89로 악화된 이유** (코드 회귀 아님):
① 시간 경과로 실제 DB의 구조화 공시 데이터가 갱신되어(2026년 신규 배당·자본변동 공시) round3 시점의 최신 Gold가 더 이상 최신이 아니게 된 케이스 6건, ② round3엔 없던 신규 실패 패턴(news-11 Tool 오선택, news-10/18 검색 순위) 추가.

**결과의 정확한 의미**: 개발셋은 문제를 찾아 고치는 데 사용한 데이터다. **이 수치는 일반화 성능이 아니다.**

### 실험 9 — 지표 집계 결함 발견과 수정 (PR #62 발견 → #63 수정)

이 실험은 **평가 코드 자체의 결함**을 잡은 것으로, 수치 해석에 결정적이다.

| 항목 | 내용 |
|---|---|
| 당시 문제 | 공식 `aggregate()`의 문서검색 Recall이 round2부터 계속 **0.0**으로 나왔다 |
| 실험 목적 | 저장된 원시 결과만 읽어 재채점(LLM·DB 미호출) |
| 사용 데이터 | `baseline_dev_records_final.json` (PR #62가 저장한 원시 실행 결과) |
| 발견한 원인 A | `_doc_miss_is_not_retriever_fault()`가 True를 반환하면 `recall_total`/`recall_hit`을 **아예 세지 않았다.** 이 함수는 "이미 완전 적중한 케이스"인지 구분하지 않아, **완전 적중 케이스까지 분모·분자에서 통째로 빠졌다** |
| 발견한 원인 B | Hit@1/MRR이 실제 검색 순위가 아니라 **알파벳순 정렬된 청크 ID**로 계산됐다. `retrieved_ids`는 `sorted(evidence.source_ids)`였다. `news-01` 대조 결과 Gold는 실제 1위인데 `retrieved_ids[0]`로는 2위를 보고 있었다 |
| 수정 내용 | 문서 ID 기준 헬퍼 신설 — `_gold_document_id`, `_source_document_id`, `document_ranking`(실제 순위 보존, 중복 청크 축약), `document_recall_stats`(뉴스/리포트 완전 분리), `report_page_accuracy` 별도 계산 |
| 수정 후 결과 (개발셋 재채점) | **뉴스** Recall@K 10/19=**0.5263**, Hit@1 9/19=0.4737, MRR 9.5/19=0.5 / **리포트** Recall@K 14/15=**0.9333**, Hit@1 14/15=0.9333, MRR 14/15=0.9333 / 리포트 페이지 12/48=0.25 |
| 결과의 정확한 의미 | **PR #61의 broker 우선 메타 조회 수정이 실제로는 매우 효과적이었고, 청크 단위 집계가 그 효과를 완전히 가려왔다.** 리포트 미적중은 report-06 단 1건 |
| 검증 | 필수 Tool 호출률은 독립 수기 재계산(분자 125 / 분모 127 = 0.9843)이 공식값과 **정확히 일치** — 이 지표는 결함이 없었음을 확인 |
| 남은 한계 | round1의 Recall 0.3333은 결함이 없던 구 정의이고 round2~final-dev의 0.0은 결함값이다. **정의가 다른 지표를 직접 비교할 수 없다** |
| 근거 파일 | `PHASE_8_METRIC_AUDIT.md`, `PHASE_8_FINAL_DEV_EVALUATION.md` §3-A, `eval/metric_audit_final.json`, PR #63 |

### 실험 10 — 뉴스 검색 실패 9건 원인 감사 (PR #64)

| 항목 | 내용 |
|---|---|
| 당시 문제 | 개발셋 뉴스 19문항 중 9건이 Gold를 찾지 못했다. 원인이 Retriever 랭킹인지 데이터인지 불명확했다 |
| 실험 목적 | 9건(news-04·09·10·11·13·14·15·18·19)의 근본 원인 분리 |
| 사용 데이터 | 저장된 검색어·필터로 `rag_search_hybrid` RPC 읽기 전용 재현(후보 풀 200개로 확대). 대화형 LLM 미호출 |
| 주요 결과 수치 | 원인 계층별 분리 결과 아래 |
| 발견한 원인 | **① 날짜 필터 제외 2건** (news-04·09): Gold `published_at=2026-07-22`인데 `recent`(3일)가 07-25~07-27이라 후보 풀 200개에 **아예 나타나지 않음** ② **동일 사건 중복 클러스터 3건** (news-10·13·18): 같은 사건이 별도 cluster로 색인돼 서로 순위를 잠식 ③ **순수 의미 검색 한계 3건** (news-13·15·19): 검색어가 지나치게 일반적("SK" semantic rank 46/200, "최태원" 82/200) ④ **Tool 선택 오류 1건** (news-11): `search_news`를 아예 호출하지 않고 금지 Tool `get_financial_facts`만 호출 ⑤ **최신순 배치 문제 1건** (news-14): query 없이 `list_recent_news` 경로, Gold가 top5 밖 |
| 중복 클러스터의 공통 원인 | 클러스터링 파이프라인 `_find_candidates()`가 `ACTIVE_WINDOW_HOURS=24`를 넘는 후보를 **유사도 계산 전에 무조건 배제**. news-10(약 48시간), news-18(약 40시간)이 이 창을 벗어나 판정 기회조차 못 받고 새 클러스터가 생성됨 |
| 수정 내용 (PR #65) | ① `prompts.py` 공통 정책 문구 수정 — 사건·배경·이슈 표현이 있으면 문장에 수치가 있어도 `search_news` 호출 ② `ACTIVE_WINDOW_HOURS` 24 → 48 (유사도 기준 `COSINE_THRESHOLD=0.74`·`LLM_ASSIGN_AUTO_MERGE_MIN_SIM=0.85`는 **완화하지 않음** — 후보 누락만 방지) ③ event-equivalent 보조 라벨 3건 승인, news-19는 명시적 비승인 |
| 수정 후 결과 | news-11 재실행 → `tool_sequence=['search_news']` (금지 Tool 미호출). `fin-01` 회귀 없음 확인 |
| 결과의 정확한 의미 | **뉴스 검색 실패의 다수는 Retriever 랭킹 품질이 아니라 날짜 필터·데이터 중복·Gold 비현행 문제였다.** |
| 남은 한계 | news-13(약 2.7시간 차이)은 시간창 안인데도 새 클러스터가 생김 — 유사도/LLM 판정 자체의 문제로 추정되나 "유사도 기준 과도한 완화" 금지에 해당해 손대지 않음. news-10/18은 재현 참조일(07-26 vs 07-27)에 따라 결과가 달라져 원인 계층을 확정하지 못함 |
| 근거 파일 | `PHASE_8_NEWS_RETRIEVAL_AUDIT.md`, `PHASE_8_NEWS_FINAL_CORRECTION.md`, `eval/news_retrieval_audit.json`, PR #64·#65 |

### 실험 11 — LLM judge 전환 (PR #66) + 개발셋 최종 평가 (PR #67)

| 항목 | 내용 |
|---|---|
| 당시 문제 | 자연어 채점이 한국어 키워드 부분 문자열 검사여서, 뜻이 같은 표현을 표현 차이만으로 실패 처리했다(`disc-13`·`na-05` 오탐) |
| 실험 목적 | 자연어 의미 판정만 Solar judge로 이관 + 초보자용 답변 프롬프트 리팩터링 후 최종 평가 |
| 사용 데이터 | 개발셋 120문항 1회. 홀드아웃 미실행·미열람 |
| 주요 결과 수치 | 512초 / **$0.77832**. **통과율 114/117 = 97.44%**(외부장애 제외) / 114/120 = 95.00%(포함). Solar judge 성공 **120건, 폴백 0건** |
| 제품 실패 3건 | `term-07`(required_tool_missing — 기존 실패), `fin-10`(financial_value_mismatch), `news-08`(overclaim) |
| 외부 장애 3건 | `report-12`·`report-13`·`mix-01` — OpenAI `gpt-4.1-mini` **RateLimitError(429)**. 통과율 분모에서 제외 |
| 외부장애 제외 시 Agent 지표 | 필수Tool **0.9919** / 인자정확도 **0.9932** / 복합완료 **1.0** / 금지Tool **0.0** |
| 검색 지표 | 뉴스 strict Recall@K 0.5263 → **0.6316**, Hit@1 → 0.5263, MRR → 0.5632, event-equivalent → 0.7368 / 리포트 Recall@K 0.9333 → 0.8667(미스 2건 중 report-12는 외부장애이므로 실질 미스는 report-06 1건 — **리포트 검색 회귀 없음**) |
| 안전성 | 제외조건 위반 2→**0**, 답변불가 오답 1→**0**, overclaim 2→**1**, 존재하지 않는 출처 **0**, 타 종목 혼입 **0** |
| 확인된 회귀 | **A** `fin-10` — "단독"을 `fs_div=OFS`로 오해석(신규 프롬프트 3/3 재현). 단 **구 프롬프트도 3회 중 1회 OFS** → 새 버그가 아니라 기존 불안정성의 발현 빈도 증가. **B** `news-03`·`news-17` — `relative_period` 미지정(신규 4/4, 구 프롬프트 4/4 지정) = **재현 가능한 신규 회귀**. **C** `ctx-04` 종목명 미언급(경미) |
| 회귀 아님(기존 결함) | `ctx-03`·`ctx-06` — 종목코드는 맞게 쓰면서 **회사명을 지어냄**. 원인: `_stock_context_block()`이 프롬프트에 종목코드만 싣고 회사명을 주지 않음 |
| 실행 후 수정 | 평가 스크립트의 환경 실패 분류 결함만 고쳐 **저장된 기록만 재채점**(Agent 재실행 없음). 제품 코드·프롬프트·gold·devset 무변경 |
| 결과의 정확한 의미 | **개발셋 통과율이다. 홀드아웃 결과가 아니며 일반화 성능이 아니다.** 원문도 명시: *"개발셋 97.44%를 홀드아웃 결과로 표현하지 않는다."* |
| 판단 | 새로운 공통 치명적 버그 없음 → **코드 동결 가능**, 홀드아웃 진행 가능 |
| 근거 파일 | `PHASE_8_FINAL_EVALUATION_AFTER_PROMPT.md`, `eval/final_after_prompt_metrics.json`, PR #66·#67 |

### 실험 12 — 뉴스 Gold canonical 전환 (PR #71)

| 항목 | 내용 |
|---|---|
| 당시 문제 | Gold가 chunk UUID여서 재색인마다 비현행이 되어 preflight가 실패했다 |
| 수정 내용 | canonical 식별자를 `news_clusters.id`로 전환(§3.7) |
| 주요 결과 수치 | preflight **PASS**, 뉴스 canonical Gold 해석 **6/6**. 홀드아웃 Agent 실행 **0/40** |
| 결과의 정확한 의미 | **평가 데이터 안정화다. 제품 성능 변화가 아니다.** 제품 Agent·Tool·Retriever·프롬프트·뉴스 DB 무변경 |
| 근거 파일 | `PHASE_8_STABLE_NEWS_GOLD.md`, PR #71 |

### 실험 13 — Phase 8 최초 블라인드 홀드아웃 (PR #72) ★

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 8 최종, 2026-07-27 13:40~13:43 |
| 당시 문제 | 개발셋 97.44%가 일반화되는지 확인되지 않았다 |
| 실험 목적 | **최초 1회** 블라인드 홀드아웃 평가 |
| 사용 데이터 | `holdout.json` 40문항. 기준 커밋 `8c3a55c`. 개발셋 미실행 |
| 실행 통제 | 데이터 순서대로 40문항, 최초 1회. **성공 문항 재실행 0회, 외부 장애 재시도 0회.** 결과 확인 후 코드·프롬프트·Gold·채점기 무변경 |
| Preflight | 실행 직전 1회 PASS — 재무 6/6, 공시 5/5, 용어 4/4, 뉴스 canonical 6/6, 리포트 14/14 |
| 주요 결과 수치 | 124.97초 / $0.229838. **formal 통과 34/40 = 85.00%** / 외부 장애 **0건** / **실제 제품 실행 실패 31건** |
| 세부 지표 | 필수Tool **100%** / 인자정확도 **100%** / 복합Tool완료 100% / 복합 최종답변완료 4/5 / 숫자정확도 **0/6 = 0%** / 단위 5/6 / 기간 6/6 / coverage **18.92%** / 뉴스 strict Recall **0/6 = 0%** / 리포트 Recall **0/5 = 0%** / 리포트 페이지 0/14 / 구조화 조회 **0%** / P50 2,396ms P95 7,370ms |
| formal 실패 6건 | **전부 재무 숫자 문항** `h-fin-20`~`h-fin-25` — 재무 Tool 오류로 정답 숫자 미제공. `h-fin-21`은 제외 요청한 전망을 재제안해 제외조건 위반 추가 |
| 발견한 원인 | Tool trace에 `status=error` 36건, 상태 누락 2건, `step_limit` 1건. 유형별 실패: 용어 4/4, 재무 6/6, 뉴스 6/6, 공시 5/5, 리포트 5/5, 복합 5/5 — **거의 모든 Tool 경로가 실행 시점에 무너졌다** |
| 결과의 정확한 의미 | **85%를 "실제 응답 성공률"로 해석하면 안 된다.** 원문 명시: 동결 통과 조건은 Tool 호출 여부를 보지만 **Tool 성공 상태를 직접 실패 조건으로 쓰지 않아**, 31건 중 숫자 정답이 실패한 6건만 formal failure로 나타났다 |
| 개발셋 대비 | 통과율 97.44% → 85.00%(**-12.44%p**), 뉴스 Recall 63.16% → 0%, 리포트 86.67% → 0%, 구조화 77.78% → 0%, 숫자 94.74% → 0% |
| 원문 해석 | *"Tool 선택·인자 정확도는 오히려 높았지만 실제 Tool 실행과 근거 반환이 무너졌다. 결과 차이는 단순한 모델 응답 과적합만으로 설명할 수 없고, 홀드아웃 실행 시점의 제품 Tool 경로 실패가 지배적이다."* |
| Phase 8 상태 | 최종 평가 프로토콜 완료 / 홀드아웃 실행·감사 기록 완료 / **제품 성능 완료 판정 미완료** |
| 근거 파일 | `PHASE_8_FINAL_HOLDOUT_RUN.md`, `eval/final_holdout_metrics.json`, PR #72 |

### 실험 14 — Phase 9 Tool runtime 근본원인과 관측성 (PR #73)

| 항목 | 내용 |
|---|---|
| 당시 문제 | 홀드아웃에서 `status=error` 36건 + `status=null` 2건 + `step_limit` 1건이 발생했으나 예외 정보가 없었다 |
| 실험 목적 | 저장된 산출물만으로 근본원인 규명 + 관측성 추가. **홀드아웃·개발셋 재실행 없음** |
| 사용 데이터 | `final_holdout_raw_records.json`, `final_holdout_tool_traces.json` 등 저장 파일만 |
| 발견한 원인 ① | **`status=null`의 정체**: `h-mix-19`가 `account_names=["배당금","영업이익"]`, `h-mix-20`이 `["매출액","영업이익","순이익"]`을 전달. `FinancialFactsInput.AccountName` 허용값은 `당기순이익`이라 `pydantic_core.ValidationError`(`literal_error`) 발생. 예외가 Tool 본문 **전에** 터져 `ToolErrorMiddleware`가 `status` 없는 평문을 반환 → recorder가 `null`로 기록 |
| 발견한 원인 ② | **`step_limit`의 정체**: `h-mix-20`이 실패 호출로 5회 Tool 예산을 소진(validation 실패 → search_news error → duplicate guard error → 정상 호출 2건)한 뒤 최종 답변 단계에 도달하지 못함 |
| 발견한 원인 ③ | **36개 error는 사후 확정 불가**: 과거 Tool 구현이 예외를 클래스명만 담은 안전 warning으로 바꾸고 recorder가 저장하지 않아, 실제 예외·메시지·stack이 산출물에 **존재하지 않는다.** 같은 입력을 현재 코드로 재현하니 main thread·새 worker·worker 재사용·반복·순차 호출 **전부 성공** |
| 수정 내용 | 모든 wrapper 예외를 표준 `ToolResult` JSON(`status=error`, 빈 data/sources, 안전 warning)으로 반환. validation error를 명시적 입력 오류로 구분. 오류를 `no_data`로 위장하지 않음. `TOOL_RUNTIME_ERROR` 내부 로그에 Tool명·마스킹된 인자·예외 클래스·마스킹된 메시지·stack frame·실패 계층·correlation ID 기록 |
| 개발셋에서 왜 안 드러났는가 | 개발셋에도 status 누락이 이미 있었다(`mix-02`·`mix-03`·`mix-05`·`excl-07`, 전체 ok 123/no_data 4/null 4/error 1). **동결 채점기가 Tool 이름 호출 여부를 주로 보고 status를 전체 통과 조건으로 삼지 않아 97.44% 지표에서 전면화되지 않았다** |
| 검증 | 실제 DB/API targeted smoke — Tool 6종 × (기본 2회 + 선택 인자 2회) 전부 PASS. 복합 순차 호출 ok/ok/ok. 없는 용어 `no_data`. 잘못된 `순이익` enum → 명시적 `error`. Ruff 통과, mock 회귀 **531 passed** |
| 남은 한계 | 36개 error의 실제 예외 종류는 사후 확정 불가. 근거 없는 DB client 교체·connection pool 재구성·retry 확대는 적용하지 않음 |
| 근거 파일 | `phase_9/PHASE_9_TOOL_RUNTIME_ROOT_CAUSE.md`, `phase_9/tool_runtime_smoke.json`, PR #73 |

### 실험 15 — Phase 9 동일 문항 홀드아웃 회귀 (PR #74) ★

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 9, 2026-07-27 14:48~14:51 |
| 당시 문제 | Phase 9 runtime 수정이 실제로 효과가 있는지 확인해야 했다 |
| 실험 목적 | **동일 40문항 회귀 검증.** 새로운 블라인드 평가가 아니다 |
| 사용 데이터 | Phase 8과 **같은** `holdout.json` 40문항. 기준 revision `b0c70aa`, Phase 9 commit `6c8940a`. 개발셋 미실행 |
| 실행 통제 | 40문항 순서대로, 최초 시도 40회, 외부 재시도 0회, 선택 재실행 없음. 결과 확인 후 무수정 |
| 주요 결과 수치 | **formal 통과 39/40 = 97.50%** / 실제 Tool·완료 실패 **1건** / 최종 답변 완료 **40/40** / Tool status ok **47** / no_data 0 / error **0** / null **2** / step_limit **0** / $0.268444 |
| 검색 지표 | **뉴스 strict Recall@K 2/6 = 33.33%**, Hit@1 33.33%, MRR 33.33% / 뉴스 event-equivalent **동일 33.33%**(홀드아웃 승인 0건이므로) / **리포트 Recall@K 100%**, Hit@1 60%, MRR 76.67% / 리포트 페이지 3/14 = 21.43% / **구조화 조회 93.33%** |
| 기타 지표 | 필수Tool 100% / 인자정확도 100% / 복합완료 100% / 숫자 83.33% / 단위 100% / 기간 100% / **coverage 100%** / 존재하지 않는 출처 0 / 근거 없는 숫자 0 / 타 종목 혼입 0 / 제외조건 위반 0 / Solar judge 40 성공·0 폴백 / P50 3,872ms P95 8,073ms |
| 남은 실패 ① | `h-fin-20` formal 실패 — **Tool 오류가 아니다.** Tool은 `amount_type=cumulative`로 2025년 3분기 누적 영업이익 5,506.4억원을 정상 반환했으나 동결 Gold는 `quarter` 137,059,000,000원이어서 값 의미가 불일치 |
| 남은 실패 ② | `h-na-09` runtime 실패 — 잘못된 계정명 `순이익` 호출 2건이 `status=null`로 남음. 뒤의 `당기순이익` 호출 2건은 `ok`, 최종 답변 완료. 그러나 `TOOL_RUNTIME_ERROR`가 생성되지 않아 예외 클래스·실패 계층·correlation ID 확인 불가 |
| Phase 8 대비 | formal 85.00% → 97.50%(**+12.50%p**), 실제 Tool·완료 실패 **31 → 1**(-30), Tool error **36 → 0**, step_limit **1 → 0**, null **2 → 2**(변화 없음), 숫자 0% → 83.33%, 뉴스 Recall 0% → 33.33%, 리포트 0% → 100%, 구조화 0% → 93.33%, coverage 18.92% → 100% |
| 결과의 정확한 의미 | **동일 문항을 수정 후 다시 사용한 결과다.** metrics JSON의 `classification` 필드가 `"post_fix_same_holdout_regression"`이고 `note`가 *"최초 블라인드 홀드아웃이나 일반화 성능 측정이 아니다. Phase 8 최초 85% 결과는 불변이다."*라고 명시한다 |
| 남은 한계 | 새 블라인드 문항이 아니므로 일반화 증거가 아니다. 뉴스는 부분 회복(33.33%)에 그쳤다 |
| 근거 파일 | `phase_9/post_fix_holdout_regression/PHASE_9_POST_FIX_HOLDOUT_REGRESSION.md`, `metrics.json`, `phase8_comparison.md`, PR #74 |

### 실험 16 — Phase 10 뉴스 기간 정책 감사와 수정 (PR #75)

| 항목 | 내용 |
|---|---|
| 시기/Phase | Phase 10, 2026-07-27 |
| 당시 문제 | Phase 9 회귀에서도 뉴스 Recall이 33.33%에 머물렀다 |
| 실험 목적 | 저장된 raw record·Tool trace의 **읽기 전용 감사**. 제품 수정·Agent 실행 없음 |
| 사용 데이터 | Phase 9 회귀의 저장 trace. 기준 `main@dd1313e` |
| 주요 발견 | 뉴스 6문항 **전부 질문에 기간 표현이 없었는데 Agent가 모두 `relative_period=recent`를 넣었다.** `recent`는 `resolve_relative_date_range()`로 2026-07-25~07-27(3일)이 된다 |
| 문항별 원인 | `h-news-20`(Gold 7131) 1위 적중 / `h-news-21`(7181) 1위 적중 / **`h-news-22`(6889, 07-23) 기간 밖 제외** / **`h-news-23`(7108, 07-24) 기간 밖 제외** / **`h-news-24`(7014, 07-24) 기간 밖 제외** / `h-news-25`(7149, 07-25) — 날짜·종목·query 모두 맞는데 미적중, **저장 trace가 최종 상위 5개만 보존해 후보 생성/ranking 중 어느 단계에서 빠졌는지 구분 불가** |
| 재현된 공통 경로 | ① 질문에 기간 표현 없음 → ② Agent가 사건 식별어만 보고 `recent` 추가 → ③ Tool wrapper가 검증 없이 날짜 범위로 변환 → ④ 검색 가능한 과거 사건이 필터 단계에서 제외 |
| 수정 내용 | 요청 원문을 `QaRuntimeContext.user_question`으로 Tool 경계에 전달. 일반 한국어 시간 표현을 `RelativePeriod`로 해석하는 순수 함수 추가. **사용자 원문의 명시적 기간을 모델이 만든 기간보다 우선.** 기간 표현 없으면 `relative_period=None`. 질문 원문이 없는 직접 Tool 호출은 기존 인자 보존 |
| 하드코딩 부재 | 제품 코드는 시간 표현만 검사한다. 홀드아웃 case ID·cluster/document/chunk ID·회사명·종목코드 목록·뉴스 제목·사건명·인물명·제품명·특정 날짜를 **참조하지 않는다** |
| 검증 | 기간 없는 사건 질문 → `None`, 최근 뉴스 → `recent`, 지난달 → 이전 달 달력 범위, 명시 기간 → 유지, 직접 Tool 호출 → 계약 유지. Ruff PASS. 전체 unit/agent 회귀 **545 passed, warning 1** |
| 감사·수정 단계의 의미 | 이 표는 **수정 전 읽기 전용 감사와 유닛 테스트**의 기록이다. 이후 별도 production smoke와 동일 40문항 최종 회귀가 수행됐으며, 그 실행 결과는 바로 아래 실험 16-B에 분리해 기록한다 |
| 남은 한계 | `h-news-25`는 원인 계층을 증명할 데이터가 없어 candidate/ranking을 수정하지 않았다. Retriever 후보 생성·hybrid ranking·top_k·Gold·채점기·평가 데이터 무변경 |
| 근거 파일 | `phase_10/PHASE_10_NEWS_RETRIEVAL_AUDIT.md`, `PHASE_10_NEWS_RETRIEVAL_IMPLEMENTATION.md`, PR #75 |

### 실험 16-B — Phase 10 제품 수정 후 동일 홀드아웃 최종 회귀 ★

| 항목 | 내용 |
|---|---|
| 성격 | **Phase 8·9와 같은 `holdout.json` 40문항을 재사용한 최종 회귀**다. 최초 블라인드 평가나 일반화 성능 측정이 아니다 |
| 실행 기준 | production revision `ae049871418b7ed2102f38fa0fca629f348657b2`, production CI/CD 및 뉴스 smoke PASS |
| 실행 통제 | 데이터 순서대로 40문항을 정확히 1회 실행. 외부 장애 재시도 0회·외부 장애 0건·개발셋 120문항 미실행. preflight PASS |
| formal / 검색 지표 | automatic formal-condition pass **39/40 = 97.50%**. 뉴스 canonical-cluster Recall@K **2/6 = 33.33%**(strict/event-equivalent 동일). formal 조건은 뉴스 적중·Tool status를 포함하지 않으므로 두 수치를 섞어 RAG 정확도라고 부르면 안 된다 |
| Tool·답변 지표 | 실제 Tool 실행 성공 **37/39 문항 = 94.87%**, 최종 답변 완료 **40/40**, status ok/no_data/error/null = **47/0/0/3**, step_limit 0 |
| 품질·검색·운영 지표 | 숫자/단위/기간 **83.33%/100%/100%**, 리포트 Recall/Hit@1/MRR **100%/60%/0.7667**, 구조화 조회 **93.33%**, citation coverage **100%**, Solar 성공/fallback **40/0**, P50/P95 **4,496/8,086ms**, 비용 **$0.272251** |
| 뉴스 기간 수정 효과 | 6/6 기간 없는 질문에서 `relative_period=None`이 실제 적용됐고 `h-news-22`는 canonical cluster rank 1로 회복했다. 그러나 `h-news-20` 순위 하락과 `h-news-23`·`h-news-24`·`h-news-25` 미적중으로 전체 Recall은 **2/6 그대로**다 |
| 실제 실패 2건 | `h-mix-20`의 status=null 1건과 `h-na-09`의 status=null 2건이다. `h-na-09`는 삼성전자 수치를 애플에도 같다고 답한 **실제 허위 비교 답변**이며 Solar Judge가 `handled_correctly=true`, `grounded=true`로 통과시킨 **false positive**다 |
| 종료 판정 | 가용성·CI/CD·production 뉴스 smoke는 정상이었지만, 타 회사 수치를 다른 회사에 적용할 수 있는 **고위험 금융정보 무결성 결함**이 발견돼 종료 불가로 기록했다. 이 결함이 이후 PR #76의 종목 문맥 안전장치로 이어졌다 |
| PR #76 이후 | PR #76 및 이후 PR #77~79 뒤에는 40문항 전체 평가를 다시 실행하지 않았다 |
| 근거 파일 | `phase_10/final_regression/PHASE_10_FINAL_REGRESSION.md`, `metrics.json`, `raw_agent_records.json`, `tool_traces.json`, `news_case_results.json`, `failure_causes.md`, `phase8_phase9_comparison.md` |

### 실험 17 — PR #76 종목 문맥 오염 방지와 production smoke

| 항목 | 내용 |
|---|---|
| 시기 | 2026-07-27 |
| 당시 문제 | 화면에서 선택한 종목과 다른 회사를 질문하면 **다른 회사 데이터로 답할 수 있었다** |
| 확인된 근본 원인 | `AgentQaService.answer()`가 화면 선택 `stock_code`를 질문 속 회사명 검증 없이 전달했다. `_resolve_stock_code()`가 6자리 인자는 무조건 수용하고 6자리가 아닌 인자는 전부 화면 선택 코드로 치환했다. 결과: Tool 인자 `AAPL`이 조용히 `005930`으로 바뀌어 **삼성전자 데이터를 애플 숫자로 재라벨할 수 있었다** |
| 수정 내용 | 결정적 사전 가드 — `STOCK_CONTEXT_MISMATCH` / `UNSUPPORTED_STOCK` / `MULTI_STOCK_NOT_SUPPORTED`. 런타임 Tool 인자의 종목 간 fallback 제거. 최종 답변 전 선택코드·런타임코드·Tool 인자·payload·source `stock_code`·source key를 **전부 대조**해 불일치 시 출처·시각화·브로커 카드 없는 안전 응답 |
| 하드코딩 부재 | 홀드아웃 ID·cluster ID·뉴스 제목·질문 문구·애플 전용 예외 없음. 지원 종목명·코드는 기존 백엔드 소스를 재사용 |
| 주요 결과 수치 | targeted 안전/API/런타임 테스트 **53 passed**, 백엔드 unit·Agent 회귀 **576 passed**, Ruff lint·format 통과, 프런트 **20 passed**, 프런트 lint·production build 통과 |
| production smoke | PR #77에서 확인 — 다른 지원 종목·미지원 종목 모두 일반 안내 답변으로 표시되고 **출처·재무카드·재시도 오류 카드 없음** |
| 결과의 정확한 의미 | **안전 가드의 targeted 검증 + 운영 시나리오 smoke다. 평가셋 성능 측정이 아니다** |
| 남은 한계 | 원문 명시: **"홀드아웃 40문항과 개발셋 120문항은 실행하지 않았다."** |
| 근거 파일 | `backend/docs/rag/STOCK_CONTEXT_SAFETY_GUARD.md`, PR #76·#77 |

### 실험 18 — 이후 제품 QA (PR #77·#78·#79)

평가셋 실행이 아닌 **제품 QA**로 별도 구분한다.

| PR | 내용 | 검증 |
|---|---|---|
| #77 | 백엔드 안전 차단 SSE를 장애 카드가 아닌 **완료 상태 안내 답변**으로 렌더링. 일반 오류·timeout은 기존 계약 유지 | 프런트 7 files/20 tests PASS, lint·build PASS, production smoke |
| #78 | `/ask` 대화 레이아웃·스타일 전면 개편, 뉴스 클릭·주가 차트·재무 지표·출처 가독성, 증권사 로고·리포트 원본 미리보기/다운로드 | 프런트 lint·27 tests·build 통과, 백엔드 575/576(1건은 로컬 `AGENT_ENABLED` 기본값 테스트) |
| #79 | 단일 심볼 Toss quote로 현재가 조회, **실시간 가격과 확정 종가 구분**, 요청 기간에 맞는 차트, Toss OHLC·거래량 캔들스틱, 초보자용 답변 구조 개편, 뉴스 카드를 네이버 검색이 아닌 **사내 뉴스 클러스터로 연결** | 백엔드 **580 passed**, 프런트 **31 passed**, Ruff·lint·build 통과, **브라우저 수동 확인** |

이 세 PR은 **브라우저 수동 테스트와 단위 테스트로만 검증됐고, 40문항 홀드아웃·120문항 개발셋을 실행하지 않았다.**

---

## 6. Phase별 결과 비교

### 6.1 요구된 6개 결과 비교 (metrics JSON 검증값)

| 구분 | 개발셋 최초 baseline (round1) | 개발셋 수정 후 (final, PR #67) | **Phase 8 최초 홀드아웃** | **Phase 9 동일 문항 회귀** | **Phase 10 동일 문항 최종 회귀** | PR #76 smoke |
|---|---:|---:|---:|---:|---:|---:|
| 성격 | Agent 전체(개발셋) | Agent 전체(개발셋) | **최초 블라인드** | **동일 문항 회귀** | **동일 문항 회귀** | targeted smoke |
| n | 120 | 120 | 40 | 40 | 40 | — |
| formal 통과율 | (무결점 42/120) | **97.44%** (114/117) | **85.00%** (34/40) | **97.50%** (39/40) | **97.50%** (39/40) | — |
| 필수 Tool 호출률 | 0.9449 | 0.9685 (외부제외 0.9919) | **1.000** | **1.000** | **1.000** | — |
| Tool 인자 정확도 | 0.8733 | 0.9799 (외부제외 0.9932) | **1.000** | **1.000** | **1.000** | — |
| 뉴스 strict Recall@K | 0.3333* | 0.6316 | **0.0000** | **0.3333** | **0.3333** | — |
| 리포트 Recall@K | 0.3333* | 0.8667 | 0.0000 | **1.0000** | **1.0000** | — |
| 구조화 조회 row_hit | — | 0.7778 | 0.0000 | 0.9333 | 0.9333 | — |
| 숫자 Exact Match | 0.7368 | 0.9474 | **0.0000** | 0.8333 | 0.8333 | — |
| 기간 정확도 | 0.7105 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | — |
| citation coverage | 0.8559 | 0.9464 | **0.1892** | **1.0000** | **1.0000** | — |
| 실제 Tool·완료 실패 | — | — | **31건** | **1건** | **2건** | — |
| Tool status ok/error/null | — | — | 11 / **36** / 2 | **47 / 0 / 2** | **47 / 0 / 3** | 전부 ok |
| P50 / P95 (ms) | 3741 / 9123 | — | 2396 / 7370 | 3872 / 8073 | 4496 / 8086 | — |
| 총비용 | $0.546 | $0.778 | $0.2298 | $0.2684 | $0.272251 | — |
| 테스트 통과 | — | — | — | — | production CI/smoke + 최종 40문항 | 576 passed |

\* round1의 Recall은 뉴스·리포트를 합친 청크 단위 구 정의값이다(§5 실험 9). 이후 라운드와 직접 비교할 수 없다.

### 6.2 반드시 구분해야 하는 3개 수치

| 수치 | 정확한 이름 | 실험 | 근거 |
|---|---|---|---|
| **85%** | 최초 홀드아웃 **automatic formal-condition pass** (34/40) | Phase 8 최초 블라인드 | `final_holdout_metrics.json` → `overall_pass.pass_rate_all_40 = 0.85` |
| **97.5%** | 수정 후 **동일 문항 회귀** formal pass (39/40) | Phase 9·Phase 10 회귀 | 각 `metrics.json` → `formal.pass_rate = 0.975`; 새 블라인드·일반화 성능이 아님 |
| **33.33%** | 뉴스 **canonical-cluster Recall@K** (2/6) | Phase 9·Phase 10 회귀 | 각 `metrics.json` → `overall.retrieval.news_retrieval.recall_at_k = 0.3333` |

---

## 7. 평가가 증명하는 것

0. **하이브리드 검색이 정확 명칭 질의에서 의미 검색 단독보다 확실히 낫다.** Phase 3에서 exact_token Recall@8이 개발 **0.25 → 0.917**, 홀드아웃 **0.647 → 0.941**로 올랐고, 자연어 질의는 떨어지지 않았다(0.975 → 0.975 / 1.0). 개발셋과 분리된 홀드아웃(offset 200)에서 같은 패턴이 재현됐다. **이것이 저장소에서 유일하게 대조군을 갖춘 A/B 실험 결과다.**
1. **Tool 선택과 인자 구성은 안정적이다.** Phase 8 최초 홀드아웃과 Phase 9 회귀 모두 필수 Tool 호출률 100%, Tool 인자 정확도 100%였다. 홀드아웃이 무너진 국면에서도 이 두 지표는 유지됐다.
2. **Tool runtime 관측성 수정은 실측 효과가 있었다.** Tool `error` 36 → 0, `step_limit` 1 → 0, 실제 Tool·완료 실패 31 → 1. 이는 동일 문항 회귀지만, 관측된 실패 유형이 사라진 것은 사실이다.
3. **출처를 지어내지 않는다.** 존재하지 않는 출처가 개발셋 4라운드·홀드아웃·회귀 **전 구간에서 0건**이다. citation precision도 1.0을 유지했다.
4. **타 종목 혼입이 평가 구간에서 0건이다.** 개발셋 전 라운드·홀드아웃·회귀 모두 0.0이다. (단, PR #76이 고친 것은 평가셋에 없던 **미지원 종목/티커 경로**다.)
5. **실제값과 전망값을 혼동하지 않는다.** `value_kind_confusions`가 전 구간 0건이다. 목표주가는 `stated` 전망값으로만 다룬다.
6. **답변 불가 질문에 값을 지어내지 않는다.** 최종 개발셋 평가와 Phase 9 회귀에서 `false_answer_on_unanswerable`이 0이다. `no_data`를 다른 기간·자료로 대체한 사례가 baseline에서 0건이었다.
7. **리포트 검색은 실제로 잘 된다.** 지표 집계 결함을 고친 뒤 개발셋 Recall@K 0.9333(미적중 report-06 1건), Phase 9 회귀 홀드아웃 Recall@K 100%였다.
8. **재무 숫자는 DB 재조회로 검증된다.** 라벨에 값을 적지 않아 전사 오타가 정답이 될 수 없다.
9. **평가 코드 자체를 감사했다.** 지표 집계 결함 2건(원인 A·B)을 스스로 찾아 고쳤고, 필수 Tool 호출률은 독립 수기 재계산으로 공식값과 일치함을 확인했다.
10. **비용·지연이 실측됐다.** 문항당 $0.0046~$0.0067, P50 2.4~4.1초, P95 7.4~9.1초.

---

## 8. 평가가 증명하지 못하는 것

### 8.1 왜 formal 97.5%와 뉴스 Recall 33.33%가 동시에 가능했는가

**formal pass 조건에 뉴스 검색 성공이 들어 있지 않기 때문이다.** §4.1의 11개 조건 어디에도 Recall·Gold 적중·citation coverage·Tool status가 없다.

`grade_case`(676–680행)는 뉴스 Gold의 개별 hit 채점을 **건너뛰고** 별도 retrieval 지표로 보낸다. 그래서:

- 뉴스 Gold cluster를 찾지 못해도 formal pass가 가능하다.
- 뉴스 Recall miss 자체는 formal fail을 만들지 않는다.
- Solar Judge가 "반환된 다른 출처에 답변이 grounded됐다"고 판단할 수 있다. **다만 Judge가 miss를 pass로 뒤집는 것이 아니라, retrieval이 애초에 formal 조건에 없어서 pass가 유지되는 것이다.**

Phase 10 감사가 이를 문항별로 입증했다. `h-news-22`·`23`·`24`는 Gold cluster를 못 찾았는데도 Solar `success·grounded` / formal `pass`였다.

### 8.2 왜 97.5%를 RAG 정확도라고 부르면 안 되는가

네 가지 이유가 겹친다.

1. **측정 대상이 다르다.** 97.5%는 *automatic formal-condition pass rate*이다. 주로 Tool 호출·인자·숫자·기간의 형식 조건이며 **검색 품질을 포함하지 않는다.** 같은 실행의 뉴스 canonical Recall@K는 33.33%다.
2. **동일 문항 회귀다.** Phase 8 최초 블라인드에서 쓴 40문항을 수정 후 다시 실행했다. metrics JSON의 `classification`이 `post_fix_same_holdout_regression`이고 `note`가 *"일반화 성능 측정이 아니다"*라고 못 박는다.
3. **Tool status를 보지 않는다.** Phase 8 최초 홀드아웃이 극단적 사례다 — 실제 제품 실패가 31건인데 formal은 85%였다. 형식 통과율과 실제 동작 성공률은 다른 것이다.
4. **n=40이다.** 1문항이 2.5%p다. `h-fin-20` 하나가 97.5%와 100%를 가른다.

따라서 **"RAG 정확도 97.5%"**, **"일반화 성능 97.5%"**는 모두 사실과 다르다.

### 8.3 Phase 9·10이 새로운 홀드아웃 평가가 아닌 이유

- **Phase 9**: Phase 8과 **동일한** `holdout.json` 40문항을 재사용했다. 문항을 새로 만들거나 보충하지 않았다. 홀드아웃의 원래 규칙(§3.3)은 "홀드아웃 실패를 보고 수정하면 그 질문은 개발셋으로 옮기고 새 홀드아웃을 보충한다"였는데, 이 보충은 수행되지 않았다. 따라서 Phase 9 이후 이 40문항은 **더 이상 블라인드가 아니다.**
- **Phase 10**: 기간 정책 수정 전 단계는 저장 trace의 읽기 전용 감사 + 유닛 테스트 545건이었다. 그러나 그 뒤 production smoke PASS를 확인하고 **동일한 40문항을 데이터 순서대로 정확히 1회 실행**했다. 따라서 Phase 10에는 회귀 수치가 존재한다(formal 39/40, 뉴스 canonical Recall@K 2/6). 이 역시 같은 문항 재사용이므로 블라인드·일반화 성능이 아니다.

### 8.4 h-na-09가 보여준 평가의 한계 — Phase 9와 Phase 10을 구분한다

`h-na-09` 원시 기록을 직접 확인했다.

- 질문: `삼성전자랑 애플 실적 비교해줘`
- Tool 호출 4건: `get_financial_facts(005930, [매출액,영업이익,순이익])` → **status=null**, `get_financial_facts(AAPL, …순이익)` → **status=null**, 이후 `당기순이익`으로 교정한 2건 → `status=ok`
- 답변: 삼성전자 수치를 제시하고 *"애플의 최신 실적 데이터는 현재 제공되지 않아 비교할 수 없습니다"*로 정상 처리
- Solar Judge: `handled_correctly` 통과, formal: **pass**

**한계의 요지**: 사용자 관점에서 답변은 옳았다. 그러나 내부적으로 Tool 호출 2건이 Pydantic validation 예외로 실패했고 `status=null`로 남아 **예외 클래스·실패 계층·correlation ID를 확인할 수 없었다.** Judge와 formal 조건은 이 내부 실패를 **전혀 보지 못했다.**

즉 **judge와 formal pass는 "내부적으로 무슨 일이 있었는지"를 검증하지 않는다.** Phase 9가 이 문항을 formal pass에도 불구하고 **runtime 실패로 유지한** 이유이며(*"앞선 상태 누락을 성공으로 숨기지 않고 실제 runtime 실패로 유지한다"*), Phase 8 홀드아웃에서 formal 85%와 실제 실패 31건이 벌어진 것과 같은 구조다.

**Phase 9의 용어 주의**: 이 실행을 "Solar Judge false positive"로 부르면 안 된다. Judge의 `handled_correctly` 판정 자체는 답변 내용에 대해 옳았다. 정확한 서술은 **"judge와 formal 조건의 관측 범위가 Tool 내부 실패를 포함하지 않아, 내부 실패가 있는 문항이 통과로 집계됐다"**이다.

**Phase 10에서는 결과가 다르다.** 같은 질문·같은 4회 `get_financial_facts` 호출(초기 `순이익` 2건 null, `당기순이익` 2건 ok) 뒤 최종 답변이 삼성전자 수치 133.87조원·57.23조원·47.23조원을 **애플에도 동일하다고 복제**했다. Solar Judge는 이 답변을 `handled_correctly=true`, `grounded=true`로 통과시켰고 formal도 pass였다. 이것은 실제 **Solar Judge false positive**다. 이 고위험 금융정보 무결성 결함이 이후 PR #76의 종목 문맥 안전장치(사전 차단·Tool/source 종목코드 대조)로 이어졌다.

### 8.5 그밖에 증명되지 않은 것

- **일반화 성능**: 새 블라인드 문항으로 측정한 적이 없다. Phase 8 최초 홀드아웃 85%가 유일한 블라인드 수치이고, 그 실행은 Tool 경로 장애가 지배했다.
- **사람 평가**: 수행되지 않았다(§3.10). 답변 품질·이해 용이성·출처 적합성에 대한 사람 판단 데이터가 없다.
- **뉴스 검색 품질**: 최고 기록이 개발셋 strict 0.6316이고, 홀드아웃에서는 0.3333이다.
- **주가 정확성**: Tool 계약·계산 일치·거래일 스냅은 검증됐으나, 이를 "주가 정확성 검증 완료"라고 부를 수 없다.
- **환각 제거**: 존재하지 않는 출처 0건, 타 종목 혼입 0건은 확인됐지만 **회사명 환각(`ctx-03`·`ctx-06`)은 실제로 관찰됐다.** "환각을 완전히 제거"는 사실이 아니다.
- **PR #76~79 이후의 평가셋 성능**: 측정되지 않았다.
- **5종목 밖 성능**: 평가셋이 5종목으로 한정된다.

---

## 9. 남은 한계

### 9.1 제품

| # | 한계 | 근거 |
|---|---|---|
| 1 | 뉴스 canonical Recall이 낮다 — Phase 9·10 동일문항 회귀 모두 33.33%, 개발셋 최고 63.16% | `phase_10/final_regression/metrics.json` |
| 2 | `h-news-25`는 원인 계층 미확정 — 저장 trace가 상위 5개만 보존해 후보 생성/ranking 구분 불가 | `PHASE_10_NEWS_RETRIEVAL_AUDIT.md` |
| 3 | 같은 사건이 여러 cluster로 분리 색인된다. `ACTIVE_WINDOW_HOURS` 24→48로 후보 누락만 완화했고, news-13(2.7시간 차)은 유사도/LLM 판정 문제로 미해결 | `PHASE_8_NEWS_FINAL_CORRECTION.md` |
| 4 | `h-na-09` validation `status=null` 경로가 남았고, Phase 10에서는 삼성전자 수치를 애플에 복제한 허위 비교 답변을 Solar가 통과시켰다 | `phase_10/final_regression/raw_agent_records.json`, `failure_causes.md` |
| 5 | Phase 8 홀드아웃의 36개 Tool error는 실제 예외가 소실돼 사후 확정 불가 | `PHASE_9_TOOL_RUNTIME_ROOT_CAUSE.md` |
| 6 | 회사명 환각 — 종목코드는 맞게 쓰면서 회사명을 지어낸다. 원인은 `_stock_context_block()`이 코드만 전달하는 것 | `PHASE_8_FINAL_EVALUATION_AFTER_PROMPT.md` §5-D. PR #68이 회사명 전달을 추가했으나 이후 평가셋 재측정 없음 |
| 7 | "단독" 해석 불안정 — `fin-10`이 `fs_div=OFS`로 오호출(신규 3/3, 구 프롬프트 1/3) | 같은 문서 §5-A |
| 8 | 리포트 페이지 정확도가 낮다 — Phase 9 21.43%, Phase 10 28.57%, 개발셋 27.08% | metrics JSON |
| 9 | 리포트 `page_start`/`page_end` 컬럼이 4,350건 전부 NULL, `target_price_source_chunk_id` 비어 있음, 목표주가 근거 청크가 없는 리포트 존재 | `PHASE_8_LABEL_REVIEW.md` §7 |
| 10 | OpenAI RateLimitError로 개발셋 3건(2.5%)이 유실됐다. 40문항 홀드아웃이면 1건이 통째로 날아간다 | `PHASE_8_FINAL_EVALUATION_AFTER_PROMPT.md` §7 |
| 11 | 5종목·읽기 전용·토스 IP 허용목록 의존 | `PHASE_6_COMPLETION.md` §7 |

### 9.2 평가 방법론

| # | 한계 | 근거 |
|---|---|---|
| 12 | **사람 평가가 수행되지 않았다.** CSV 양식만 존재하고 점수 칼럼이 공란 | 직접 확인 |
| 13 | **홀드아웃이 더 이상 블라인드가 아니다.** Phase 9가 동일 40문항을 재사용했고 새 문항 보충이 없었다 | `PHASE_9_POST_FIX_HOLDOUT_REGRESSION.md` |
| 14 | **formal pass가 검색 품질·Tool status를 포함하지 않는다** | `case_passed` 85–113행 |
| 15 | **Solar Judge `grounded`는 출처 제목·종류·날짜만 보고 판정한다.** 숫자 검증 능력이 없어 통과 조건에서 제외됐다 | `llm_judge.py` 프롬프트 |
| 16 | `h-fin-20`처럼 **Gold 자체가 질문의 모호성을 흡수하지 못한다.** "3분기 영업이익"에 대해 Gold는 `quarter`, Tool은 `cumulative`를 반환 — 둘 다 타당한 해석 | `failure_causes.md` |
| 17 | **Gold 시간 경과.** 구조화 공시 데이터가 갱신되면 과거 Gold가 최신이 아니게 된다(final-dev 6건) | `PHASE_8_FINAL_DEV_EVALUATION.md` §4 |
| 18 | 복합 질문 20건은 정답 식별자가 없어 검색 Recall 분모에서 제외된다 | `PHASE_8_LABEL_REVIEW.md` §4 |
| 19 | n=40은 1문항이 2.5%p다 | — |
| 20 | round1과 round2+ 의 Recall 정의가 달라 직접 비교 불가 | `PHASE_8_METRIC_AUDIT.md` |
| 21 | 뉴스 감사 재현이 참조일(07-26 vs 07-27)에 따라 달라져 news-10/18 원인 계층 미확정 | `PHASE_8_NEWS_RETRIEVAL_AUDIT.md` §2 |
| 22 | **PR #76~79 이후 평가셋 수치는 없다.** 단, PR #75 직후에는 Phase 10 동일 40문항 최종 회귀가 수행됐다 | `phase_10/final_regression/metrics.json` |

---

## 10. 문서와 원시 수치 간 불일치

조사 중 발견한 불일치를 전부 기록한다. 원칙은 **저장소의 확인된 값(metrics JSON)을 우선**한다.

| # | 불일치 | 문서 값 | JSON/코드 값 | 채택 및 근거 |
|---|---|---|---|---|
| 1 | round1 무결점/실패 문항 수 | `PHASE_8_DEV_BASELINE.md`: 무결점 **42**/120, 실패 **78**/120 | `PHASE_8_FINAL_DEV_EVALUATION.md` §4 비교표: round1 무결점 **73**, 실패 **47** | **판단 불가로 양쪽 병기.** `baseline_dev_metrics_round1.json`에는 무결점 카운트 필드가 없어 JSON으로 판정할 수 없다. 후자에 `(round1 원본)`이라는 주석이 붙어 있어 재채점본과 원본이 섞인 것으로 보이나 **확인되지 않음** |
| 2 | round1 뉴스/리포트 Recall | round1 문서: 뉴스 0.381, 리포트 0.125, 공시 0.067 | `baseline_dev_metrics_round1.json`: 통합 `retrieval.recall_at_k=0.3333` | **둘 다 유효.** 문서는 유형별, JSON은 전체값. 단 둘 다 **구 정의(청크 단위·통합)**이므로 이후 라운드와 비교 불가 |
| 3 | `baseline_dev_metrics.json` vs `_final.json` | 별개 파일 | **내용이 완전히 동일** (required_tool_recall 0.9843 등 전부 일치) | 같은 실행의 사본으로 판단. final-dev 값을 채택 |
| 4 | 지표 스키마 변경 | round1은 `retrieval.recall_at_k` 평면 구조 | round2+는 `retrieval.document_retrieval{}` / `structured_lookup{}` 분리, PR #63 이후 `news_retrieval` / `report_retrieval` 분리 | **구조가 3번 바뀌었다.** 라운드 간 Recall 직접 비교 금지 |
| 5 | 개발셋 문서검색 Recall 공식값 0.0 | round2·3·final-dev 문서에 0.0으로 기재 | PR #63 재채점: 뉴스 0.5263 / 리포트 0.9333 | **재채점값 채택.** 0.0은 집계 결함값임이 `PHASE_8_METRIC_AUDIT.md`에서 규명됨 |
| 6 | 최종 개발셋 통과율 표기 | "97.44%" | `final_after_prompt_metrics.json`: `pass_rate=0.9744`(114/117), `pass_rate_including_environment=0.95`(114/120) | **분모를 반드시 병기.** 97.44%는 외부장애 3건 제외 값 |
| 7 | h-na-09 성격 | prompt.md가 "Solar Judge false positive"로 지칭 | 원시 기록: judge `handled_correctly` 판정은 답변에 대해 옳았고, 문제는 Tool `status=null`이 formal·judge 관측 범위 밖이었던 것 | **§8.4에서 정확한 서술로 교정** |
| 8 | Phase 10 회귀 수치 | 초기 구현 문서는 "홀드아웃 재실행 없음"(수정 전 단계)을 기록 | 별도 worktree의 `phase_10/final_regression/`에 production smoke, preflight, 40문항 원시 기록·trace·metrics가 보존돼 있음 | **최종 회귀는 실제 수행됐다.** 같은 40문항 재사용이므로 새 블라인드·일반화 수치로 쓰지 않는다 |
| 9 | Phase 9 `overall_pass` 키 | — | Phase 9 metrics JSON에는 `overall_pass`가 **null**이고 `formal.pass_rate`에 0.975가 있다 | Phase 8과 키 구조가 달라 스크립트로 두 파일을 같은 키로 읽으면 오류가 난다. `formal` 키 사용 |
| 10 | **Phase 3 개발 exact_token 하이브리드 MRR** | `PHASE_3_COMPLETION.md:81`: **0.456**(굵게 강조) | `eval_result.json:26`: **0.449** | **JSON 채택. 0.456을 인용하면 안 된다.** 같은 실행의 recall은 정확히 일치하므로 전사 오류로 판단 |
| 11 | Phase 3 지연 | 세 곳이 서로 다르다 — `PHASE_3_COMPLETION.md:85` "의미 ~129ms / 하이브리드 ~616ms", `:138` "~635ms", `RAG_PHASE_EXECUTION_PLAN.md:1222` "~134ms / ~635ms" | 개발 **119 / 607**, 홀드아웃 **179 / 797** | **JSON 채택.** 지연은 wall-clock이고 마이그레이션 0018 적용 후 재실행된 기록이 있어 산문 수치는 JSON이 덮어써진 실행의 것으로 추정 |
| 12 | Phase 3 초기 하이브리드 recall 0.50 | `PHASE_3_COMPLETION.md:49` | 원시 산출물 **없음**(두 JSON 모두 수정 후) | 산문 전용 값임을 명시해 인용 |
| 13 | Phase 3 코퍼스 DF 수치 | `PHASE_3_COMPLETION.md:53` "ai 1083건 / sk 858건 / 전체 ~2940건" | 대응 JSON·스크립트 출력 **없음** | **저장소에서 독립 검증 불가.** 산문 전용 |
| 14 | Phase 2 trial-100 색인 수치 | `PHASE_2_COMPLETION.md:38` "indexed **100** / chunks **109** / 24.6s" | `trial_100_result.json`: indexed **0**, chunks **0**, skipped_unchanged **100**, 2.4s | **모순이 아니라 함정.** 커밋된 JSON은 **멱등성 재실행** 기록이다. 최초 실행 수치는 산문에만 존재. 산문의 재실행 기록(2.3s)조차 JSON(2.4s)과 다르다 |
| 15 | Phase 2 검색 지연 | `PHASE_2_COMPLETION.md:45` "~130ms" | JSON 6건 평균 = **113.3ms** | JSON 채택 |
| 16 | Phase 4 dry-run 표 | `PHASE_4_COMPLETION.md:84-96`: 원문 대조 **69/69**, 페이지 넘는 정의 **240건** | `bok_dryrun_report.md`: **50/50**(`:24-26`), **244건**(`:22`) | **`:84-96` 표는 수정 전(1차) dry-run 값으로 판단.** 인용 시 재현 불가한 이전 상태임을 명시 |
| 17 | Phase 4 목차 외 term 목록 | `bok_verification.md:7` "18건"이라 쓰고 인라인 목록에 **10개**만 | 전체 18건은 `bok_dryrun_report.md:40-57,98-120`에 있음 | `bok_verification.md`의 목록으로 세면 안 된다 |
| 18 | Phase 4 필수 질문 수 | `PHASE_4_COMPLETION.md:223` "필수 질문 **5개** 통과" | `trial_result.json`: **6건** | JSON 채택. 또한 `:34`가 5번 케이스를 "근거 부족 → 확인 불가"로 서술하나 JSON에서는 `need_documents=true`로 **doc_sources 8건이 회수**됐다 — 정직한 거절은 생성 텍스트 수준이고 검색 지표 수준이 아니다 |

---

## 11. 확인하지 못한 사항

| # | 항목 | 이유 |
|---|---|---|
| 1 | **BM25 arm의 성능** | 구현·평가된 적이 없다. 한국어 형태소 분석기 미설치로 `pg_trgm`을 렉시컬 arm으로 썼다. 저장소에 BM25는 존재하지 않는다 |
| 2 | **reranker A/B 수치** | 계획만 존재한다(`RAG_EVALUATION_PLAN.md:313-332`, 후보 모델 `BAAI/bge-reranker-v2-m3`). `RAG_RERANKER_ENABLED=false`, 실행 계획 체크박스 미체크, `config.py`에 설정 키 자체가 없다. **한 번도 실행되지 않았다** |
| 3 | RRF 가중치·`rrf_k`·`top_k` 스윕 | 1.0:1.0 / 50 / 8 단일 조건만 실행됐다. 튜닝 실행 기록이 없다 |
| 4 | Phase 5 리포트 검색 **유형별 분해 수치**(정확명칭·자연어·전망·목표주가·실적원인 각각) | 스크립트가 stdout에만 출력하고 결과 JSON을 커밋하지 않았다. 집계값 25/25만 남아 있다 |
| 5 | 모든 검색기 단독 실험의 **nDCG·Hit@1·Precision@K** | 어느 스크립트도 계산하지 않는다 |
| 6 | 모든 실험의 **신뢰구간·통계적 유의성** | 계산되지 않았다. Phase 3 exact_token은 n=12·17로 표본이 매우 작다 |
| 7 | Phase 3 지연 P50/P95 | arm별 산술 평균만 존재한다 |
| 8 | round1 무결점 문항 수의 정본(42 vs 73) | metrics JSON에 해당 필드가 없다(§10-1) |
| 9 | Phase 3 초기 하이브리드 recall 0.50의 원시 데이터 | 산문 전용. 커밋된 두 JSON은 모두 수정 후 실행 |
| 10 | Phase 3 코퍼스 DF 수치(ai 1083 / sk 858) | 재현 가능한 출력이 없다 |
| 11 | Phase 2 최초 색인 실행 수치(indexed 100 / chunks 109) | 커밋된 JSON은 멱등성 재실행 기록이다 |
| 12 | Phase 8 홀드아웃 36개 Tool error의 실제 예외 종류 | 원시 예외가 저장되지 않아 **사후 확정 불가**(원문 명시) |
| 13 | `h-news-25` 미적중의 원인 계층 | 저장 trace가 최종 상위 5개만 보존 |
| 14 | news-10/18 재현 차이의 원인 | 참조 시각 미세 차이 또는 임베딩 API 비결정성으로 **추정**되나 확정 불가 |
| 15 | PR #68(회사명 전달) 이후 회사명 환각의 평가셋 재측정 | 이후 평가셋을 실행하지 않았다 |
| 16 | PR #76~79 반영 후의 홀드아웃/개발셋 지표 | Phase 10 최종 회귀는 **PR #75 직후·PR #76 이전** 실행이다. PR #76~79 반영 후 평가셋 재실행은 하지 않았다 |
| 17 | 사람 평가 결과 | 수행되지 않았다 |
| 18 | 뉴스 클러스터링 자체의 품질 지표 | `docs/finish/clustering_eval_*.csv`는 평가 대상이 달라 이번 조사에서 사용하지 않았다 |
| 19 | 다중 Gold / 등급형 관련성(graded relevance) 평가 | 모든 검색기 단독 실험이 이진 단일 Gold 자기 회수를 쓴다(Phase 5는 종목 단위 이진) |

---

## 12. 근거 파일과 PR 목록

### 12.1 평가 코드

| 경로 | 역할 |
|---|---|
| `backend/app/eval/schema.py` | `EvalCase`/`EvalSuite` 라벨 스키마 + 정합성 검증 |
| `backend/app/eval/metrics.py` | 지표 계산(숫자 정규화·백분위), `RetrievalMetrics` |
| `backend/app/eval/grader.py` | `grade_case`(676–680행 뉴스 Gold 분기), `aggregate`(991–995 citation, 1003–1024 검색 집계), `document_ranking`, `document_recall_stats`, `report_page_accuracy` |
| `backend/app/eval/llm_judge.py` | Solar Judge(`solar-pro3-260323`), 3필드 판정, 캐시, 폴백 |
| `backend/app/eval/runner.py` | `EvalRunner` — 문항 1건 실행 후 `RunRecord` 기록 |
| `backend/app/eval/recorder.py` | `ToolCallRecorder` — Tool 인자·지연 관찰(평가 전용, 운영 체인 미등록) |
| `backend/app/eval/news_gold.py` | 뉴스 canonical cluster Gold resolver |
| `backend/app/eval/human_form.py` | 사람 평가 CSV 양식 생성 |
| `backend/scripts/phase8_final_evaluation_after_prompt.py` | **`case_passed`(85–113행) — formal pass 판정**, `is_environment_failure`(71–82행), 분모 계산(216–228행) |

### 12.1-B 검색기 단독 실험 코드

| 경로 | 역할 |
|---|---|
| `backend/scripts/rag_phase3_eval.py` | **뉴스 Retriever A/B 실행기** — `top_k`(126행), Gold 자기회수(102–104행), 지표(114–118행), 변별력 토큰 규칙(31–56행), 샘플링(88–99행), 2개 arm 구성(129–130행) |
| `backend/app/rag/retrieval.py` | `SemanticRetriever`(88–123행), `HybridRetriever`(126–215행) |
| `backend/app/core/config.py:89-99` | `rag_retrieval_top_k=8`, 후보 24/24, `rrf_k=50`, 문서당 2청크 |
| `backend/migrations/0017_rag_hybrid_rrf.sql` | RRF 초기 구현 |
| `backend/migrations/0018_rag_hybrid_lexical_exact_first.sql` | **정확 부분일치 우선 렉시컬 랭킹**(78–96행). `CREATE OR REPLACE`로 0017 이력 보존 |
| `backend/scripts/phase5_eval_report_search.py` | 리포트 검색 확인 — `TOP_K=24행`, 질의 생성(38–47행), 종목 단위 Gold(55–57행) |
| `backend/scripts/rag_phase2_trial.py` | 뉴스 색인 trial(질의 생성 83–92행) |

### 12.2 주요 산출물 JSON

| 경로 | 내용 |
|---|---|
| `phase_8/eval/devset.json` / `holdout.json` | 120 / 40 문항 + Gold |
| `phase_8/eval/baseline_dev_metrics_round1~3.json`, `_final.json` | 개발셋 라운드별 지표 |
| `phase_8/eval/final_after_prompt_metrics.json` | 최종 개발셋 평가(97.44%) |
| `phase_8/eval/final_holdout_metrics.json` | **최초 홀드아웃(85.00%)** |
| `phase_8/eval/metric_audit_final.json` | 지표 집계 감사 재채점 |
| `phase_8/eval/news_retrieval_audit.json`, `_ref0726_comparison.json` | 뉴스 실패 재현(참조일 2종) |
| `phase_8/eval/event_equivalent_approvals.json` | event-equivalent 승인(`approved_by: agent-assisted manual review`) |
| `phase_8/eval/human_review_rater1.csv`, `rater2.csv` | 사람 평가 양식(**점수 공란**) |
| `phase_9/post_fix_holdout_regression/metrics.json` | **동일 문항 회귀(97.50%, 뉴스 33.33%)** |
| `phase_9/post_fix_holdout_regression/raw_agent_records.json` | 회귀 원시 기록(h-na-09 포함) |
| `phase_9/tool_runtime_smoke.json` | 배포 전 실제 DB/API smoke |
| `phase_10/final_regression/` | **Phase 10 동일 40문항 최종 회귀 원본** — production smoke·preflight·raw Agent 기록·Tool trace·metrics·뉴스 6문항·실패 원인·비교표·Solar cache·실행 log |

### 12.3 PR 목록

| PR | 제목 | 성격 |
|---|---|---|
| #38 | 운영 라이브 전환 + legacy 제거 | production |
| #41 | 주가 Tool | 제품 + smoke |
| #52 | Phase 8 1단계 — 평가 데이터·라벨·실행기 구축 | 평가 구축 |
| #54 | 라벨 검토 65건 확정 | 평가 데이터 |
| #55 | 개발셋 120문항 baseline(round1) | Agent 전체 |
| #57 / #58 | 1차 교정 / round2 | 제품 / 평가 |
| #59 / #60 | 2차 교정 / round3 | 제품 / 평가 |
| #61 / #62 | 3차 교정 / 개발셋 최종 검증 | 제품 / 평가 |
| #63 | **지표 집계 결함 수정** | 평가 코드 |
| #64 | 뉴스 실패 9건 원인 감사 | 감사 |
| #65 | 뉴스 최소 교정(news-11 Tool 선택·시간창) | 제품 |
| #66 | LLM judge 전환 + 답변 프롬프트 | 평가 + 제품 |
| #67 | **개발셋 최종 평가 97.44%** | Agent 전체 |
| #68 | 종목 문맥에 공식 회사명 전달 | 제품 |
| #69 | 토스 기준가로 실시간 등락률 정합성 | 제품 |
| #70 | 홀드아웃 preflight 실패 기록 | 평가 |
| #71 | 뉴스 Gold canonical cluster 전환 | 평가 데이터 |
| #72 | **Phase 8 최초 홀드아웃 85.00%** | Agent 전체 |
| #73 | Phase 9 Tool runtime 근본원인·관측성 | 제품 |
| #74 | **Phase 9 동일 문항 회귀 97.50%** | 동일문항 회귀 |
| #75 | Phase 10 뉴스 기간 정책 수정 | 감사 + 제품 |
| #76 | 종목 문맥 오염 방지 | 제품 + smoke |
| #77 | 안전 차단 안내 렌더링 | 제품 QA |
| #78 | Ask RAG 경험 개편 | 제품 QA |
| #79 | 시장 데이터·채팅 UX 개선 | 제품 QA |
| #80 | Phase 10 최종 회귀 원본 보존 + 실험 통합 문서 정정 | 문서·원시 산출물 |

### 12.4 금지 표현 (근거와 함께)

| 금지 표현 | 왜 안 되는가 |
|---|---|
| RAG 정확도 97.5% | formal pass rate이며 검색 품질 미포함(§8.2) |
| 일반화 성능 97.5% | 동일 문항 회귀. `classification=post_fix_same_holdout_regression` |
| 사람 라벨링 데이터셋 | 사람 평가 CSV 점수가 공란, `approved_by=agent-assisted manual review`(§3.10) |
| 전문가가 검수한 Gold | 사람 검토자 기록이 없다 |
| 모든 뉴스 질문을 정확히 검색 | 홀드아웃 뉴스 Recall 33.33% |
| 환각을 완전히 제거 | 회사명 환각(`ctx-03`·`ctx-06`) 관찰됨 |
| 주가 정확성 검증 완료 | Tool 계약·계산 일치만 검증 |
