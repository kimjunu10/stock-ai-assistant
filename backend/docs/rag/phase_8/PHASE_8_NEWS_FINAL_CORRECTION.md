# Phase 8 뉴스 최종 최소 교정

브랜치: `phase/8-news-final-correction` (base: `main`, PR #64 머지 후 `d16f15e`)

목적: `PHASE_8_NEWS_RETRIEVAL_AUDIT.md`(PR #64)에서 확인된 뉴스 실패 9건 중 실제
제품 문제(Tool 선택 오류, 후보 탐색 시간창 누락)와 평가 데이터 문제(비현행/범위
밖 gold, 중복 클러스터 라벨)를 분리해 최소 수정한다. 전체 120문항·홀드아웃은
실행하지 않았다.

---

## 1. news-11 Tool 선택 오류 수정

**원인**: `app/agent/prompts.py`의 기존 지침이 "무슨 일 있었어" 류 사건 질문에는
`search_news`를, 숫자만 묻는 질문에는 해당 숫자 Tool만 부르라고 안내했지만, 두
조건이 한 문장에 겹치는 경우("SK하이닉스 2분기 영업이익 64조원 관련해서 무슨 일
있었어?")를 명시적으로 다루지 않아, 모델이 문장 속 구체적 금액을 "수치 확인
요청"으로 오인해 `search_news` 대신 `get_financial_facts`만 호출했다(PR #64
raw 기록 확인: `tool_calls=[get_financial_facts(no_data)]`, `search_news` 미호출).

**수정**: `app/agent/prompts.py`의 공통 정책 문구만 수정했다(특정 질문 문자열
하드코딩 없음).
- 사건·배경·이슈 표현이 있으면 문장에 수치가 언급돼도 `search_news`를 호출한다.
  그 수치는 사건을 특정하는 문맥일 뿐이라고 명시.
- "맞아/사실이야/정말/실제로"처럼 수치 자체를 의심·검증해 달라는 표현이 별도로
  있을 때만 `get_financial_facts`를 함께 호출한다는 판단 기준을 명시.

**검증 결과**: 실제 devset `news-11` 케이스를 그대로(운영 Agent, 실제 LLM) 재실행 →
`tool_sequence=['search_news']` (search_news 호출, get_financial_facts 미호출).
같은 devset의 `fin-01`(순수 재무 숫자 질문)도 재실행해 `tool_sequence=['get_financial_facts']`
로 회귀 없음을 함께 확인했다.

---

## 2. 중복 클러스터 4건의 원인

`news_clusters` 테이블을 직접 조회해 gold와 실제 반환 클러스터의 핵심 회사·사건·
날짜·고유식별어·선후속 관계를 대조했다.

| 문항 | gold 클러스터 | 실제 반환(대표) | 판정 |
|---|---|---|---|
| news-10 | 6974 (2026-07-24, "한화오션, 레이도스 깁스 앤 콕스와 글로벌 전략 수송함 공동 설계 계약 체결") | 7222 (2026-07-26, "한화오션, 미국 레이도스와 글로벌 고속수송선 공동설계 계약 체결"), 7167 (2026-07-25, "레이도스 깁스 앤 콕스와 조선업 협력 양해각서 체결") | **동일 사건**(같은 회사·같은 상대·같은 계약 유형, 후속 보도) |
| news-13 | 7182 (2026-07-25, "삼성전자, 연내 출시 예정인 '인텔리전트 아이웨어' 공개") | 7195 (2026-07-26, "삼성전자, 구글 협업 스마트안경 개발 뒷이야기 공개") | **동일 사건**(같은 회사·같은 제품, 후속 보도) |
| news-18 | 6944 (2026-07-23, "한미 조선협력센터 워싱턴 개소…1500억달러 마스가 프로젝트") | 7193 (2026-07-26, "한미 조선협력센터 개소 및 마스가 프로젝트 본격 가동") | **동일 사건**(같은 고유식별어 "마스가"/"1500억달러"/"한미 조선협력센터", 후속 보도) |
| news-19 | 7117 (2026-07-24, "최태원·노소영 재산분할금 9440억원 확정") | 5611 (2026-07-21, "최태원-노소영 재산분할 소송 파기환송심 선고") | **별개 사건**(같은 소송의 다른 절차 단계 — "선고"와 "확정"은 사건 진행 단계가 다름) |

**직접 원인 조사(공통 원인 확인)**: 뉴스 클러스터링 파이프라인
(`experiments/exp_b_factual_summaries/assign_llm_v2.py`, `app/jobs/scheduler.py`가
직접 호출하는 실제 운영 코드)의 `_find_candidates()`가 `t_h - cl.last_active_h >
self.window_h`(시간창, `ACTIVE_WINDOW_HOURS=24`)를 넘는 후보를 **유사도 계산
전에 무조건 배제**한다. news-10(gold→반환 실제 간격 약 48시간), news-18(약 40시간)
은 이 24시간 시간창을 벗어나 유사도·LLM 판정 기회 자체를 받지 못하고 무조건 새
클러스터가 생성됐다 — 공통 원인으로 확인.

news-13(7182→7195, 약 2.7시간 차이)은 시간창 안인데도 새 클러스터가 생겼다 —
시간창 문제가 아니라 유사도/LLM 판정 자체의 문제로 추정되며, 이번 라운드에서는
"유사도 기준의 과도한 완화" 금지 항목에 해당해 손대지 않았다.

news-19는 회사·인물만 같을 뿐 사건 진행 단계가 다른 별개 보도로 판단해 병합
대상에서 제외했다(§2 금지 항목 "회사명만 같다는 이유로 병합" 회피).

**최소 수정**: `experiments/exp_b_factual_summaries/config.py`의
`ACTIVE_WINDOW_HOURS`를 24 → 48로 확장했다. 최종 병합 여부는 여전히
`COSINE_THRESHOLD`(0.74)/`LLM_ASSIGN_AUTO_MERGE_MIN_SIM`(0.85)·Solar LLM
판정이 결정하므로 유사도 기준 자체를 완화한 것은 아니다 — 후보 누락만 방지.

---

## 3. 연결·병합한 클러스터와 과병합 방지 근거

이번 라운드에서 **DB의 클러스터를 직접 병합·연결하지 않았다**(§2 금지 "원본
기사 삭제" 회피, 데이터 자체는 그대로 둠). 대신:

1. **운영 파이프라인 수정**: `ACTIVE_WINDOW_HOURS` 24→48h — 다음 스케줄러
   실행부터 새로 들어오는 기사에 적용되며, 과거에 이미 분리 생성된 클러스터를
   소급 병합하지 않는다.
2. **평가용 사람 승인 매핑**: `docs/rag/phase_8/eval/event_equivalent_approvals.json`에
   news-10/13/18 3건만 사람이 직접 내용을 대조해 승인 기록(핵심 회사·사건·고유
   식별어 대조 근거 포함)으로 남겼다. news-19는 `explicitly_not_approved`에
   사유와 함께 명시적으로 **미승인** 처리했다 — 자동 승인 없음, 전체 클러스터
   일괄 병합 없음, 회사명만 같다는 이유의 병합 없음.

과병합 방지: 승인 파일은 devset.json/holdout.json을 변경하지 않으며, 각 승인
항목이 어떤 근거(고유 식별어·행위·상대방 일치)로 승인됐는지 파일 자체에 기록돼
있어 추적 가능하다.

---

## 4. 비현행 Gold 사례 수

PR #64 데이터 무결성 점검 재확인: **3건**(news-11, news-13, news-15)의 gold
`note`가 가리키는 `rag_documents.id`가 현재 `is_current=false`다(news-15는
`rag_chunks`도 `is_active=false`). 이번 라운드에서 devset gold는 변경하지
않았다.

---

## 5. 현재 상대 기간 밖 Gold 사례 수

**2건**(news-04, news-09) — gold 발행일 2026-07-22가 실제 실행 시각(raw 파일
저장 시각 기준 2026-07-27) 대비 `recent`(실행 시각부터 2일 전, `RECENT_LOOKBACK_DAYS=2`)
범위인 07-25~07-27 밖이다.

**한계 고지**: 새로 추가한 `gold_out_of_relative_range()`(§7 참고)는 `RunRecord.evaluation_run_at`이
있어야 판정할 수 있다. PR #64까지 저장된 raw 기록(`baseline_dev_records_final.json`)은
이 필드가 생기기 전에 실행된 것이라 값이 없다 — 그래서 이번 라운드가 재계산한
공식 지표(§9)에서는 news-04/09가 여전히 "retriever_failure"로 표시되고
`missed_case_ids_stale_gold`가 0건으로 나온다. 코드 자체는 합성 데이터로
정확히 동작함을 단위 테스트로 확인했다(§7) — **다음 devset/홀드아웃 실행부터
`evaluation_run_at`이 채워지면 이 2건은 자동으로 stale_gold로 정확히 분류된다.**
과거 raw 데이터에 소급 적용하지 않았다(가짜 시각을 임의로 채워 넣지 않음).

---

## 6. 실제 서비스 날짜 계산 방식

기존에도 이미 원칙대로였다(이번 라운드에서 제품 코드를 고치지 않음, 확인만
함): `app/services/agent_qa.py:83`의 `request_now = current_seoul_datetime()`이
질문마다 새로 계산되고, `app/agent/runtime.py:228`의 `search_news` Tool이
그 값을 `QaRuntimeContext.current_date`로 받아 `resolve_relative_date_range()`를
호출한다. "최근 3일"은 항상 그 순간의 KST 오늘 기준이며, 과거 라벨링 시점을
고정해서 쓰는 코드는 없다. `EvalRunner.run()`도 `AgentQaService.answer()` 호출
직전에 같은 방식으로 시각을 잰다(§7에서 `evaluation_run_at`으로 기록에 추가).

---

## 7. 홀드아웃 preflight 동작

`app/eval/grader.py`에 `preflight_check_relative_gold_validity(cases, *,
planned_run_at)`를 추가했다:
- 실행 기록 없이 case 목록만으로 동작(실행 전 점검용 순수 함수).
- gold 발행일이 `planned_run_at` 기준 가장 좁은 상대 기간(`recent`)에도 들지
  못하면 `should_abort=True`와 함께 케이스 ID·gold 발행일·계산된 범위를 반환.
- **실행을 직접 중단시키지 않는다** — 반환값을 보고 호출부(향후 홀드아웃 실행
  스크립트)가 중단 여부를 결정한다.
- devset 케이스로만 테스트했다(홀드아웃은 이번 라운드에서 열지 않음).

같은 파일에 `RunRecord.evaluation_run_at`(신규 필드, `app/eval/runner.py`),
`gold_out_of_relative_range()`(사후 채점용), `document_recall_stats()`의
`missed_case_ids_stale_gold`/`missed_case_ids_retriever_failure`(부가 분류)를
추가했다 — 이 모두가 §3의 "홀드아웃 정책"이 요구하는 실행 전/후 계약을 구성한다.

---

## 8. strict Recall

(PR #64/#63과 동일 정의로 재확인, 저장된 raw 재사용 — 변경 없음)

| 구분 | n_eval | recall_hit | recall@K | Hit@1 | MRR |
|---|---|---|---|---|---|
| 뉴스 | 19 | 10 | 0.5263 | 0.4737 | 0.5000 |
| 리포트 | 15 | 14 | 0.9333 | 0.9333 | 0.9333 |

---

## 9. event-equivalent Recall

사람 승인 매핑(§3, `event_equivalent_approvals.json`) 적용 결과:

| 구분 | n_eval | recall_hit | recall@K |
|---|---|---|---|
| 뉴스 | 19 | 13 | **0.6842** (strict 대비 +0.1579, news-10/13/18 3건 추가 적중) |
| 리포트 | 15 | 14 | 0.9333 (변화 없음 — 승인 대상 없음) |

news-04/09/11/14/15/19는 event-equivalent 에서도 여전히 미스다(각각 §5 상대
기간 문제, §1 Tool 오류 — 이번 재계산엔 미반영, §2 비현행 gold, query 없는
list_recent_news 경로, 순수 의미 검색 한계, 별개 사건 판정).

---

## 10. 평가 데이터 문제 수

**5건**: 비현행 gold 3건(§4: news-11/13/15) + 상대 기간 밖 gold 2건(§5:
news-04/09). 중복 클러스터 관련 데이터 문제(같은 사건이 다른 클러스터로
분리된 라벨 문제)는 news-10/13/18 3건이며 §3의 사람 승인으로 별도 처리했다
(§4D "같은 사건이 중복 클러스터로 분리된 라벨 문제"에 해당, 위 5건과 별도
집계).

---

## 11. 기존 Gold·질문 변경 여부

**변경 없음.** `devset.json`/`holdout.json`을 이번 라운드에서 열거나 수정하지
않았다(`git diff --stat`으로 확인, 아래 §13). `event_equivalent_approvals.json`은
devset과 별도의 보조 승인 파일이며 gold_sources 자체를 대체하지 않는다.

---

## 12. 다음 단계 권고

- **뉴스 클러스터링**: `ACTIVE_WINDOW_HOURS` 48h 적용을 다음 스케줄러 실행에서
  관찰하고, news-13 유형(시간창 안인데도 분리)은 유사도/LLM 판정 로직 자체를
  별도 라운드에서 조사할 것을 권고(이번 라운드 범위 밖 — "유사도 기준의 과도한
  완화" 금지에 해당하므로 신중한 별도 검토 필요).
- **평가 계약**: 다음 devset 재실행부터 `evaluation_run_at`이 자동 기록되므로,
  §5의 한계(과거 raw 데이터 소급 불가)가 해소되고 news-04/09가 정확히
  stale_gold로 분류될 것으로 예상.
- **홀드아웃**: 최초 실행 직전 `preflight_check_relative_gold_validity()`를
  실제 홀드아웃 케이스에 호출해 `should_abort` 확인 후 진행 여부를 사람이
  결정할 것을 권고(이번 라운드에서 홀드아웃 자체는 열지 않음).
- 코드 동결 여부는 이번 라운드가 판단할 사항이 아니다(PR #64가 이미 "코드
  동결" 권고를 냈고, 이번 라운드는 그 권고 이후 명시적으로 허용된 최소 교정만
  수행했다).

---

## 13. 변경 파일

```
app/agent/prompts.py                                   (news-11 정책 수정)
app/eval/runner.py                                      (evaluation_run_at 필드 추가)
app/eval/grader.py                                      (stale_gold 판정, event-equivalent/
                                                          product-failure 계산, preflight 함수)
app/eval/metrics.py                                     (RetrievalMetrics 신규 필드)
experiments/exp_b_factual_summaries/config.py           (ACTIVE_WINDOW_HOURS 24→48)
tests/unit/test_news_v2.py                              (시간창 테스트 갱신)
tests/unit/test_news_final_correction.py                (신규, 16개 단위 테스트)
scripts/phase8_news_final_correction.py                 (신규, targeted regression 스크립트)
docs/rag/phase_8/eval/event_equivalent_approvals.json   (신규, 사람 승인 매핑)
docs/rag/phase_8/eval/news_final_correction_regression.json (신규, 회귀 실행 결과)
docs/rag/phase_8/eval/news_final_correction_metrics.json    (신규, strict/event-equivalent/
                                                              product-failure 재계산 결과)
docs/rag/phase_8/PHASE_8_NEWS_FINAL_CORRECTION.md       (신규, 이 문서)
```

`devset.json`/`holdout.json`/Agent Tool 스키마/Validator/Grader 의 채점 원칙
(strict 지표 계산 로직 자체)은 변경하지 않았다 — grader.py 변경은 전부 기존
strict 함수 위에 새 함수를 **추가**한 것이다.

---

## 14. 테스트 결과

- 신규 단위 테스트: `tests/unit/test_news_final_correction.py` 16개 전부 통과
  (stale_gold 4개, event-equivalent 3개, product-failure 3개, strict 보존 2개,
  preflight 4개).
- `tests/unit/test_news_v2.py`: `ACTIVE_WINDOW_HOURS` 48h 반영 갱신 후 33개
  전부 통과.
- 전체 스위트: `pytest tests/` **504 passed**, 1 deselected
  (`test_feature_flag_off_returns_none` — 로컬 `.env`의 `AGENT_ENABLED=true`
  때문에 이번 변경과 무관하게 main에서도 이미 실패하던 사전 존재 이슈, 확인
  후 제외).
- `ruff check .` / `ruff format --check .` 모두 통과.
- news-11 targeted regression 스크립트(`scripts/phase8_news_final_correction.py`,
  실제 LLM+DB, read-only): 5개 케이스 3회 반복 실행 모두 5/5 PASS.
- 실제 devset `news-11`/`fin-01` 재실행(운영 Agent 그대로): `search_news` 정상
  호출, 순수 재무 질문 회귀 없음.
- 전체 120문항 devset·홀드아웃은 실행하지 않았다.

---

## 15. 다음 단계 권고

(§12와 중복 — prompt.md 최종 보고 15번 항목 요구에 맞춰 동일 내용 반복 게재)
§12 참고.

---

## 16. PR 주소

PR 생성 후 이 섹션에 URL을 채운다(아래 "최종 보고" 참고).

자동 머지 하지 않았다.
