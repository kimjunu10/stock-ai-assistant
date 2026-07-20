# LLM 배정 3가지 수정·검증 보고서

> prompt.md 요청 3가지(invalid_response 처리 / 후보 recall 측정 / anchor 정책)만 수정·검증.
> 운영 연결·커밋은 하지 않음.

---

## 변경 파일

| 파일 | 변경 |
|---|---|
| `assign_llm.py` | invalid_response 처리 강화, anchor(최초 기사) 정책 추가 |
| `overmerge_fix/test_assign_llm.py` | 테스트 2개 추가(invalid_response 4종 / anchor 고정) |
| `overmerge_fix/measure_candidate_recall.py` | **신규** — 후보 검색 recall 측정(LLM 미호출) |
| `config.py` | 변경 없음(기존 `LLM_ASSIGN_CANDIDATE_MIN_SIM=0.55` 사용) |

---

## 1. LLM 응답 오류 → 전부 `invalid_response` + `pending_retry`

다음 4가지를 모두 `invalid_response` 로 처리하고 결과를 `pending_retry` 로 남긴다.
**기존 클러스터 배정도, 신규 클러스터 생성도 하지 않는다.** (`_seen` 에도 안 넣어 재시도 가능)

- 후보에 없는 cluster_id (환각)
- 잘못된 JSON
- 필수 필드 누락 (`matched_cluster_id` 없는 existing 등)
- `decision` 값 오류 (existing/new 외)

`AssignResult.error = "invalid_response"` 로 분류. 통신 실패/타임아웃은 `error="transport_error"`
로 구분(둘 다 pending_retry).

> 변경 전에는 "후보에 없는 cluster_id" 를 신규 생성으로 처리했으나, 지시대로 pending_retry 로 변경.

---

## 2. 후보 검색 recall (validation 212건, 추가 LLM 호출 없음)

정답: exp_a `validation.csv` 의 `gold_event_id`(검수된 동일사건 라벨).
방법: 종목별·시간순 스트리밍, 각 기사 시점의 활성 클러스터 anchor 와 cosine 으로 후보 정렬.
평가대상 = 정답 클러스터가 활성창(72h) 내 존재하는 **144건**.

| 지표 | 값 |
|---|---|
| **recall@1** | **0.944** (136/144) |
| **recall@3** | **1.000** (144/144) |
| **recall@5** | **1.000** (144/144) |

**cosine ≥ 0.55 로 정답 후보가 제외된 건수 = 0건.**
→ 0.55 임계값이 정답을 하나도 놓치지 않으며, 후보 5개 안에 정답이 항상 포함된다.

로그: `candidate_recall.txt`

---

## 3. 판정용 대표 기사(anchor) 정책

구현 위치: `assign_llm.py`

- `Cluster.anchor_title` / `anchor_description` — **클러스터 최초 기사로 고정** (`_new_cluster` 에서
  설정, 새 기사가 붙어도 **변경하지 않음**)
- LLM 동일사건 판정에는 **anchor 의 title+description 만** 전달 (`assign()` 의 후보 payload)
- `Cluster.rep_title` / `rep_description` — **UI 대표 기사(anchor 와 분리 가능)**. 기본은 anchor 와
  동일하나, 필요 시 UI 정책에 따라 갱신해도 판정용 anchor 에는 영향 없음.

---

## 테스트 결과 — 11/11 PASS (Mock Solar)

`test_assign_llm.py`. 신규 추가:
- **test_9**: invalid_response 4종(후보밖 id·잘못된 JSON·필드 누락·decision 오류) → 전부
  pending_retry, 배정·신규 생성 없음 확인
- **test_10**: anchor 가 최초 기사로 고정되고, 판정 프롬프트에 anchor 제목이 들어가는지 확인

로그: `assign_test_results.txt`

---

## 요약

| 항목 | 결과 |
|---|---|
| invalid_response → pending_retry | 4종 모두 처리, 배정/생성 금지 |
| recall@1 / @3 / @5 | 0.944 / 1.000 / 1.000 |
| 0.55 로 누락된 정답 | 0건 |
| anchor 정책 | 최초 기사 고정, UI 대표와 분리, 판정엔 anchor만 |
| 테스트 | 11/11 PASS |

재현:
```bash
cd backend/experiments/exp_b_factual_summaries/overmerge_fix
PY=../../../../.venv-exp/bin/python
$PY test_assign_llm.py            # 11/11
$PY measure_candidate_recall.py   # recall (LLM 미호출)
```
