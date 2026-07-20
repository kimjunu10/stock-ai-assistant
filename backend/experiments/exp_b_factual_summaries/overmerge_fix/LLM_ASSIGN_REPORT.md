# LLM 동일사건 배정 (하이브리드) 구현 보고서

> 목적: 클러스터 배정을 `유사도 ≥ 0.74 → 즉시 배정`(거리 단독) 에서
> **`BGE-M3 후보 검색 → Solar Pro3 동일사건 판정 → 배정`** 하이브리드로 변경.
> 임베딩은 후보 검색·정렬에만 쓰고, 최종 배정 권한은 LLM 이 가진다.
> 범위: **company 기사만** LLM 판정(사용자 결정). market/info 는 기존 규칙+거리 유지.
> 이번 작업: 배정 모듈 구현 + 로컬 검증까지. Supabase·스케줄러 미연결. 커밋 안 함.

---

## 1. 처리 흐름 (`assign_llm.LLMAssigner`)

company 기사 1건마다:

1. 같은 `stock_code`, 최근 72h 활성 클러스터 중 **임베딩 유사 후보 최대 5개** 검색
   (cosine ≥ `LLM_ASSIGN_CANDIDATE_MIN_SIM`=0.55, centroid 유사도순 정렬 — **정렬 용도만**)
2. 후보 0개 → **신규 클러스터** (LLM 호출 안 함)
3. 후보 있으면 (새 기사 + 후보 5개 대표기사: cluster_id·제목·description) 를 **Solar 에 1회 호출**
4. Solar `{"decision":"existing","matched_cluster_id":N}` → 해당 클러스터 배정
5. Solar `{"decision":"new"}` → 신규 클러스터
6. 호출 실패/타임아웃/잘못된 JSON → **`pending_retry`** (배정·신규 생성 안 함, 재시도 가능)

핵심 규칙(prompt 준수):
- **centroid 이동만 보고 배정하지 않는다** — 후보 검색·정렬만 임베딩, 판정은 LLM.
- 후보 대표기사와 동일사건인지 LLM 이 보므로 **chaining(징검다리) 차단**.
- **후보마다 따로 호출하지 않고 최대 5개를 한 번에** 판정 → 기사당 최대 1회.
- LLM 이 후보에 없는 cluster_id 를 반환(환각)하면 임의 배정하지 않고 **신규**로 처리.

## 2. LLM 설정 (`config.py`)

| 항목 | 값 |
|---|---|
| 모델 | `solar-pro3-260323` |
| temperature | 0 |
| max_tokens | 200 |
| response_format | json_object |
| 입력 | 제목 + description 만 (본문 미사용) |
| 후보 정보 | cluster_id + 대표 기사 제목·description |
| 판정 기준 | 주체·행동·대상/프로젝트·발생 시점. 주제만 비슷하면 다른 사건. 애매하면 new. |

시스템 프롬프트에 이 기준을 명시했고, 출력은 지정 JSON 만 강제한다.

## 3. 안전·운영 조건 (prompt "중요한 조건" 전부 반영)

| 조건 | 구현 |
|---|---|
| 전체 클러스터를 LLM 에 보내지 않음 | 임베딩으로 최대 5개 후보만 |
| 후보 5개 1회 요청 | `build_user_prompt` 가 후보 전체를 한 프롬프트에 |
| centroid 단독 배정 금지 | 최종 배정은 `decision` 기반, 유사도는 후보 선별만 |
| chaining 차단 | 대표기사 동일사건 판정 |
| 실패/타임아웃/잘못된 JSON → pending_retry | `meta.ok`/`parse_success` 실패 시 배정 안 하고 `pending_retry`, `_seen` 에도 안 넣어 재시도 가능 |
| idempotent | `_seen[article_id]` 로 재처리 시 `duplicate` 반환(재배정·재호출 없음) |
| feature flag 롤백 | `USE_LLM_ASSIGN=False` 면 기존 거리 단독 배정으로 동작(로직 삭제 없음) |
| 요약과 배정 분리 | `summarize.py`(요약)와 별도 모듈 `assign_llm.py`(배정) |

JSON 파싱·cluster_id 유효성은 `parse_decision` 에서 검증(decision 값 화이트리스트,
existing 이면 matched_cluster_id 필수, 후보 집합 내 존재 여부까지 확인).

## 4. 단위 테스트 (`test_assign_llm.py`, Mock Solar) — **9/9 PASS**

| # | 테스트 | 결과 |
|---|---|---|
| 1 | 첫 기사·후보 없음 → 신규 | PASS |
| 2 | 동일 발표 후속 → 기존 배정 | PASS |
| 3 | 주제 비슷·주체 다름 → 신규 | PASS |
| 4 | 한화 군함 수주 vs HD현대 방산 협력 → 분리 | PASS |
| 5 | 후보 여러 개여도 호출 기사당 1회 | PASS |
| 6 | LLM 오류/잘못된 JSON → pending_retry | PASS |
| 7 | 중복 재처리 → 중복 배정 없음(idempotent) | PASS |
| 8 | flag OFF → 기존 거리 기반 동작(LLM 미호출) | PASS |
| + | parse_decision 형식 검증 | PASS |

로그: `assign_test_results.txt`

## 5. 실 Solar 소규모 검증 (`verify_solar_assign.py`) — 실제 API 4회 호출

후보 2개(101=군함 수주, 202=해상풍력 착공)에 대해 새 기사 4건 판정:

| 케이스 | 기대 | 실제 | |
|---|---|---|---|
| 해상풍력 착공 후속 | existing/202 | **existing/202** | ✓ |
| 무관한 실적 전망 | new | **new** | ✓ |
| 다른 회사(HD현대) 방산 협력 | new | **new** | ✓ (chaining 차단 확인) |
| 필리조선소 미사일시험선 수주 | existing/101 | new | ✗(아래) |

**판정 3/4.** 마지막 케이스에서 Solar 는 "미국이 한국에 군함 설계 정보 요청"(후보 101)과
"한화 필리조선소가 미사일시험 계측선을 수주"(새 기사)를 **다른 사건(new)** 으로 봤다.
주체(필리조선소)·대상(미사일시험선 vs 전투함 설계)·행동(수주 완료 vs 정보 요청)이 달라,
시스템 프롬프트의 "주제만 비슷하면 다른 사건, 애매하면 new" 규칙을 **보수적으로 적용한 결과**다.
이는 over-merge(chaining) 를 막는 목표 방향과 일치하며 오작동으로 보기 어렵다.
(엄밀한 정오 판정보다 "보수적 분리" 경향이 확인된 것이 이번 검증의 핵심이다.)

## 6. 호출 수 · 토큰 사용량 (실측)

- **호출 수**: 기사당 정확히 1회(후보가 있을 때만). 후보 0개면 0회.
- **실측 토큰**(후보 2개, 4회 호출): prompt 합 1,748 / completion 합 69
  → **평균 prompt ≈ 437 토큰/호출, completion ≈ 17 토큰/호출**.
- 후보 5개면 프롬프트가 다소 늘지만 대표기사 제목·description 만 넣어 증가폭은 작다(대략 600~700 예상).
- **운영 추정**: company 기사 중 "후보가 있는" 기사 N건에 대해서만 호출 →
  prompt ≈ 437·N, completion ≈ 17·N. (첫 기사·후보 없는 기사는 호출 0)
  · 예: 하루 신규 company 기사 500건 중 후보 있는 게 300건이면 ≈ prompt 13만·completion 5천 토큰/일.
- 요약(summarize.py, 클러스터당 1회)과는 별개 비용이다.

## 7. 변경/추가 파일

| 파일 | 내용 |
|---|---|
| `assign_llm.py` (**신규**) | `LLMAssigner`, `call_solar_assign`, `build_user_prompt`, `parse_decision`, `Cluster`, `AssignResult` |
| `config.py` | `USE_LLM_ASSIGN`(flag), `LLM_ASSIGN_MAX_CANDIDATES=5`, `LLM_ASSIGN_CANDIDATE_MIN_SIM=0.55`, `LLM_ASSIGN_MODEL`, `LLM_ASSIGN_PROMPT_VERSION`, `LLM_ASSIGN_MAX_TOKENS` |
| `overmerge_fix/test_assign_llm.py` (**신규**) | 단위 테스트 9종(Mock) |
| `overmerge_fix/verify_solar_assign.py` (**신규**) | 실 Solar 검증 + 토큰 실측 |

기존 거리·규칙 배정 로직(pipeline.py)은 **삭제하지 않았다**. `USE_LLM_ASSIGN=False`(기본)면
기존과 동일하게 동작한다. market/info 라우팅(classify_kind)도 그대로다.

## 8. 재현 명령어

```bash
cd backend/experiments/exp_b_factual_summaries/overmerge_fix
PY=../../../../.venv-exp/bin/python
$PY test_assign_llm.py         # 단위 테스트 9/9 (Mock, 무비용)
$PY verify_solar_assign.py     # 실 Solar 4회 호출 + 토큰 실측 (backend/.env 의 UPSTAGE_API_KEY)
```

운영 반영 시: `config.py` `USE_LLM_ASSIGN=True`. 끄면 즉시 기존 거리 방식으로 롤백.

## 9. 아직 안 한 것 (prompt 준수)

- 운영 크롤링 스케줄러 연결 안 함
- Supabase 연결/기록 안 함
- 커밋 안 함
- (다음 단계 후보) 파이프라인 배선: 크롤링 → classify_kind → company 는 LLMAssigner,
  market/info 는 기존 경로. pending_retry 큐 영속화.
