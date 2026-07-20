# over-merge 수정 보고서

> 목적: 뉴스 사건 클러스터링의 **시장 뉴스 over-merge** 문제를 최소 코드 변경으로 완화.
> 방식: 기존 알고리즘(BGE-M3 + online centroid, cosine 0.74, 활성창 72h)은 그대로 두고,
> 켜고 끌 수 있는 보호 옵션 하나만 추가.
> 데이터: DB 의 relevant 기사 **7,782건**(종목 5개), 임베딩 1회 생성 후 캐시 재사용.

---

## 1. 기존 분석의 원인이 맞았나 → **맞았다**

`OVER_MERGE_ANALYSIS.md` 는 "종목 기사에 **시장 전체 시황 기사**(코스피·증시·급락·마감·사이드카 등)가
섞이면, 서로 다른 거래일의 다른 장세 기사가 sliding 72h 활성창을 타고 한 덩어리로
계속 이어붙는다"고 진단했다.

baseline 산출물에서 직접 확인한 결과 이 진단과 정확히 일치했다.

| 검증 클러스터(대표 제목) | 건수 | 걸친 일수 | 시황 기사 비율 |
|---|---:|---:|---:|
| **over-merge 의심** | | | |
| 코스피 8300선 하락 마감 (om_600) | 296 | **18일** | 40% |
| 코스피 6% 급락 사이드카 (om_997) | 284 | 5일 | 65% |
| 반도체 쇼크 코스피 패닉 (om_371) | 248 | 4일 | 35% |
| 코스피·코스닥 동반 급락 (om_26) | 231 | 3일 | **69%** |
| 뉴욕증시 브리핑 (om_364) | 115 | 4일 | 15% |
| **정상 대형 단일사건** | | | |
| 현대차 노조 부분 파업 (nm_992) | 193 | 6일 | **0%** |
| 신안우이 해상풍력 (nm_881) | 180 | 6일 | **0%** |
| 보스턴다이내믹스 지분 (nm_1008) | 137 | 6일 | **0%** |
| 두산 발전기 모니터링 (nm_663) | 108 | 4일 | **0%** |

- over-merge 클러스터는 시황 기사 비율이 15~69% 로 높고 여러 거래일에 걸친다.
- 정상 대형 클러스터는 시황 비율이 **0%** 다(하나의 기업 사건을 여러 언론사가 보도).
- 즉 **"시황 기사 섞임"이 두 그룹을 가르는 결정적 신호**임이 데이터로 확인됐다.
  (cid 는 데이터 증가로 매 실행 달라지므로, 대표 제목으로 재식별해 검증했다 — `case_resolved.json`.)

---

## 2. 실험 A / B / C 결과

세 실험을 **같은 임베딩**으로 돌려 비교했다(`overmerge_experiment_comparison.csv`).

| 변형 | 클러스터 수 | singleton 비율 | 최대 크기 | 50+ 클러스터 |
|---|---:|---:|---:|---:|
| baseline | 1310 | 0.7382 | 379 | 35 |
| **A (시장 브리지 차단)** | **1428** | **0.7283** | 362 | 37 |
| B (drift 보호) | 1447 | 0.7408 | 331 | 34 |
| C (A+B) | 1578 | 0.7370 | 317 | 34 |

### over-merge 케이스가 얼마나 쪼개졌나 (최대조각이 원래의 몇 %인가 — 낮을수록 잘 분리)

| 케이스 | A | B | C |
|---|---:|---:|---:|
| om_600 | 41% | 72% | 30% |
| om_997 | **44%** | 98%(거의 못 나눔) | 44% |
| om_371 | 36% | 59% | 35% |
| om_26 | 73% | 85% | 73% |
| om_364 | 37% | 81% | 37% |

### 정상 대형 클러스터가 얼마나 보존됐나 (높을수록 좋음)

| 케이스 | A | B | C |
|---|---:|---:|---:|
| nm_992 | **100%** | 96% | 96% |
| nm_881 | **100%** | 100% | 100% |
| nm_1008 | **100%** | 100% | 100% |
| nm_663 | **100%** | 99% | 99% |

**해석**
- **A**: 시황 over-merge 를 크게 분해(최대조각 36~73%)하면서 정상 대형은 **4/4 완벽 보존(100%)**.
  singleton 비율은 오히려 소폭 감소(0.738→0.728).
- **B**: om_997 을 거의 못 나눔(98%). 분해력이 A 보다 약하고, 정상 클러스터를 조금씩 깎는다.
- **C**: 분해력은 가장 강하나(om_600 30%), B 성분이 정상 클러스터도 깎아(nm_992 96%) 부작용이 생긴다.

---

## 3. 선택한 최종 방법 → **A (시장 뉴스 브리지 차단)**

prompt 우선순위(①시장 over-merge 감소 ②정상 대형 보존 ③singleton 과증가 방지 ④단순성 ⑤비용)에 따라:

1. A 는 명백한 시황 over-merge(다른 거래일 연결)를 해소한다.
2. A 는 정상 대형 클러스터를 **깎지 않는다**(C·B 는 깎는다 → 기준② 위배).
3. singleton 이 늘지 않는다(0.738→0.728).
4. **규칙이 하나뿐이라 가장 단순하다**(C 는 두 개).
5. 추가 계산 비용이 사실상 없다(0.47s).

C 의 추가 이득(om_600 을 41%→30%로 조금 더 쪼갬)은 작고, 그 대가로 정상 클러스터를 손상시킨다.
prompt 7절 "차이가 작으면 가장 단순한 방법 선택"에 따라 **A** 를 최종안으로 확정했다.

### A 가 하는 일
- 각 기사를 **투명한 규칙 점수**로 시황(`market_wide`) 여부 판별(`market_rules.py`):
  시장 주체(코스피·코스닥·뉴욕증시…) + 시장 움직임(마감·급락·약세·순매도…) 이 있으면 가점,
  회사 고유 사건(계약·착공·인수·수주·실적…) 이 있으면 감점. 임계값 2.0 이상이면 시황.
  (키워드 하나만으로 판별하지 않음 — 조합 점수.)
- 시황 기사는 `kind='market'`, 나머지는 `'company'`. **kind 가 다르면 서로 클러스터에 붙지 않는다**
  → 시장 뉴스가 종목 사건들을 잇는 **다리(bridge) 역할을 못 한다.**
- 시황 클러스터는 **같은 거래일 안에서만** 묶인다 → 다른 날의 시황이 자동 연결되지 않는다.

---

## 4. 정상 대형 클러스터 보존 결과

A 적용 후에도 정상 대형 4개는 **원래 기사를 100% 유지**했고 날짜 범위도 그대로다
(파업 6일, 해상풍력 6일, 보스턴다이내믹스 6일, 두산 원전 4일). 시황 비율 0% 라 애초에
`market` 으로 분류되지 않아 아무 영향도 받지 않는다.

---

## 5. over-merge 사례가 어떻게 분리됐나

`verify_A_daysplit.py` 로 A 적용 후 **최대조각이 며칠에 걸치는지** 확인했다.

| 케이스 | baseline | A 최대조각 | 판정 |
|---|---|---|---|
| om_997 | 5일 1덩어리 | market **1일** 126건 | 다른 날 시황 분리됨 ✅ |
| om_371 | 4일 1덩어리 | market **1일** 88건 | 분리됨 ✅ |
| om_26 | 3일 1덩어리 | market **1일** 168건 | 분리됨 ✅ |
| om_364 | 4일 1덩어리 | company 3일 42건 | 대폭 축소 ✅ |
| om_600 | 18일 1덩어리 | company 16일 122건 | **부분만 해소(한계, §7)** |

핵심 시황 over-merge(om_997·371·26)는 이제 **거래일별 market 클러스터로 깔끔히 분리**된다.

---

## 6. 부작용

- 시황 기사가 거래일별로 나뉘므로 **시황 성격의 클러스터 수가 늘어난다**(전체 1310→1428, +118).
  이는 의도된 동작이며 singleton 비율은 오히려 감소했다(과분할 아님).
- 시황 기사끼리는 종목 사건과 섞이지 않고 별도(`kind='market'`, 125개)로 모인다.
  UI 에서 "시황" 유형을 종목 사건과 구분해 다룰 수 있어 오히려 이점이다.
- 정상 기업 사건 클러스터에는 **부작용이 관측되지 않았다**(보존 100%).

---

## 7. 남은 한계

- **om_600(두산, 16일)** 의 잔여 company 덩어리(122건)는 완전히 해소되지 않았다.
  원인: "코스피 2% 하락", "1% 초고수의 선택", "서울데이터랩 인기 검색 종목" 같은
  **시황·투자정보·데이터성 기사**가 특정 회사 이벤트도 아니고 명확한 시황 주체+움직임 패턴도
  아니어서 규칙 점수 2.0 에 못 미친다. 이들을 다 잡으려면 규칙을 계속 늘려야 하는데,
  이는 prompt 원칙("규칙을 추가로 더 만들지 마라")에 어긋나고 정상 기사 오분류 위험을 키운다.
  → 무리한 규칙 확장 대신 **한계로 남긴다.** (후속: "투자정보/데이터성" 유형을 별도 분류하는
     것을 검토할 수 있으나 이번 범위 밖.)
- 규칙 키워드는 한국어 시황 표현 기준으로 손으로 작성했다. 새로운 표현이 나오면 갱신이 필요하다.
- 임계값 0.74·활성창 72h 는 **바꾸지 않았다**(prompt 금지 사항 준수).

---

## 8. 변경된 코드

| 파일 | 변경 |
|---|---|
| `experiments/exp_b_factual_summaries/config.py` | `BLOCK_MARKET_BRIDGE`(기본 False), `MARKET_DAY_BOUNDARY`, `CLUSTERING_VERSION_PROTECTED` 추가 |
| `experiments/exp_b_factual_summaries/market_rules.py` | **신규** — 시황 판별 규칙(투명 점수) |
| `experiments/exp_b_factual_summaries/pipeline.py` | `cluster_stock`/`cluster_all` 에 `block_market_bridge`·`market_day_boundary` 옵션 추가. **기본 OFF 면 기존과 100% 동일**(실데이터로 OFF=1310=baseline 확인). 기존 알고리즘 미삭제. |
| `experiments/exp_b_factual_summaries/build_protected_clusters.py` | **신규** — 서비스 코드로 보호 ON 최종 결과 생성(Solar 미호출, 새 경로에만 기록) |

실험/분석 스크립트(덮어쓰기 아님, `overmerge_fix/` 아래 신규):
`market_rules.py`, `cluster_variants.py`, `run_experiments.py`, `baseline_metrics.py`,
`rematch_cases.py`, `verify_A_daysplit.py`, `inspect_A_bridge.py`, `test_overmerge_fix.py`.

---

## 9. 테스트 (`test_overmerge_fix.py`) — **6/6 통과**

1. 동일 기업 발표를 여러 언론사가 보도 → 하나로 유지 ✅
2. 서로 다른 거래일의 시황 기사는 시장 단어가 유사해도 연결 안 됨 ✅
3. 시장 뉴스가 서로 다른 기업 사건을 잇는 다리가 되지 않음 ✅
4. 날짜가 달라도(활성창 내) 동일 기업 사건이면 유지됨 ✅
5. 보호 기능을 끄면 기존 방식과 완전히 동일 ✅ (합성 데이터 + 실데이터 OFF=1310=baseline)
6. 실험 폴더 `market_rules.py` 복사본이 서비스 정본과 동일(갈라지면 실패) ✅

결과 로그: `test_results.txt`

---

## 10. 산출물

| 파일 | 내용 |
|---|---|
| `overmerge_baseline_metrics.json` | baseline 지표(기존 산출물 기준) + 검증 케이스 상세 |
| `overmerge_experiment_comparison.csv` | baseline/A/B/C 지표 비교 |
| `overmerge_case_comparison.md` | 검증 케이스가 각 변형에서 어떻게 쪼개졌나 |
| `case_resolved.json` | 대표 제목으로 재식별한 검증 케이스 실제 cid |
| `clustered_articles_protected.jsonl` | **보호 ON 최종 결과**(기사별, 새 버전) |
| `cluster_sources_protected.jsonl` | **보호 ON 최종 결과**(클러스터별, kind 포함) |
| `variant_labels.json` | 각 변형의 article→cluster 매핑 |
| `test_results.txt` | 테스트 실행 결과 |

기존 `artifacts/clustered_articles.jsonl` 등은 **덮어쓰지 않았다.**

---

## 11. 재현 실행 명령어

```bash
# 실험 전용 venv (임베딩 패키지)
python3 -m venv .venv-exp
.venv-exp/bin/pip install "numpy>=1.26" "sentence-transformers>=3.0" "torch>=2.2" \
    "huggingface_hub>=0.24" psycopg2-binary

cd backend/experiments/exp_b_factual_summaries/overmerge_fix
PY=../../../../.venv-exp/bin/python

# (1) baseline 지표 (기존 산출물만 읽음, 임베딩 불필요)
$PY baseline_metrics.py

# (2) A/B/C 실험 비교 (임베딩 1회 생성 후 emb_cache 재사용)
PYTHONUNBUFFERED=1 $PY run_experiments.py mps

# (3) A 최대조각 날짜폭 검증
$PY verify_A_daysplit.py A

# (4) 테스트
$PY test_overmerge_fix.py

# (5) 보호 ON 최종 클러스터 결과 생성 (서비스 코드 경로, backend/ 에서 모듈 실행)
cd ../../..    # -> backend/
PYTHONUNBUFFERED=1 $PY -m experiments.exp_b_factual_summaries.build_protected_clusters --device mps
```

운영에서 보호를 켜려면 `config.py` 의 `BLOCK_MARKET_BRIDGE = True` 로 두면 된다(끄면 기존과 동일).

---

## 12. 지키지 않은/하지 않은 것 (prompt 3절 준수)

- Solar API 미호출 · Supabase 미기록 · 감성 분석 미실행
- threshold(0.74)·임베딩 모델 교체 실험 안 함
- 임베딩 1회만 생성 후 캐시 재사용
- 대형 JSONL 원문을 대화에 통째로 출력하지 않음(스크립트 요약·대표 제목만)
- 기존 파일·구현 미삭제, 미덮어쓰기
