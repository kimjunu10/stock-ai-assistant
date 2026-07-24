# EXP-5 산출물 — 사건 클러스터별 사실 통합 본문

이 폴더는 확정된 뉴스 클러스터링 설정을 재사용/재현하여 각 사건 클러스터의
**라벨 비의존 사실 통합 본문**과 원문 출처 목록을 생성한 오프라인 산출물이다.
감성 분류, gold label, Supabase 반영, API/UI는 이 단계에서 하지 않았다.

## 이 산출물을 만들 당시의 실험 설정

> 이 절은 과거 오프라인 실험을 재현하기 위한 기록이다. 현재 운영 클러스터링 설정을
> 뜻하지 않는다.

- 임베딩: `BAAI/bge-m3` (revision `5617a9f61b02…`), 1024차원
- 입력: title + description
- 클러스터링: online centroid, cosine ≥ 0.74, 활성창 72h, 같은 stock_code끼리만
- 요약: Solar Pro `solar-pro3-260323`, prompt version `factual_v1`

기존 확정 클러스터링 결과가 DB에 없어(clusters 테이블 미존재) prompt.md 2번 경로에 따라
위 확정 설정으로 신규 생성했다.

## 현재 운영 기준과의 차이

- 임베딩 모델과 입력은 동일하게 BGE-M3 `title + description`을 사용한다.
- 활성 후보 창은 현재 24시간이다.
- BGE-M3 유사도는 최종 병합 판정이 아니라 같은 종목의 사건 후보를 찾는 데 사용한다.
- 유사도 0.55 이상 후보 중 최종 동일 사건 여부는 Solar가 사건명, 주최자, 행사 형태,
  장소, 목적, 핵심 행위가 같은지 보수적으로 판정한다.
- 감성분류는 대표 기사 제목이 아니라 Solar 요약이 성공한 뒤 확정된
  `news_clusters.summary_title`을 사용한다.

따라서 이 폴더의 72시간 배치 결과를 현재 운영 결과나 감성 입력 기준으로 해석하면 안
된다.

## 실행
```bash
# .env 의 DATABASE_URL, UPSTAGE_API_KEY 사용
python -m experiments.exp_b_factual_summaries.run --device mps
```

## 데이터/결과 요약
- 입력 relevant (기사,종목) 연결: 7735
- 생성 클러스터: 1298 (단독 957, 복수기사 341)
- Solar 요약: 시도 1298 / 성공 1257 / 파싱실패 1 / HTTP실패 40

## 산출물
1. `clustered_articles.jsonl` — 기사별 cluster_id, assigned_similarity, is_new_cluster
2. `cluster_sources.jsonl` — 클러스터별 article_ids, 언론사, 원문 URL, 대표 기사, 활성 구간
3. `factual_summaries.jsonl` — factual_title, factual_summary, source mapping, prompt/version
4. `sentiment_reference_template.csv` — 빈 `gold_label`, `label_reason` (사람이 작성)
5. `summary_run_env.json` — git commit, 모델·프롬프트 버전, 입력/출력 통계
6. `README.md` — 이 문서

## 다음 단계에서 사람이 결정/작성할 것
- `sentiment_reference_template.csv` 의 `gold_label` (positive/negative/neutral) 과 `label_reason` 을 사람이 작성하고 reference version 을 동결한다.
- 이 실험 산출물만으로 감성 예측을 생성·노출하지 않는다.

## 한계
- 원문 body 크롤 실패 기사는 title+description 만으로 임베딩·요약된다.
- 이번 클러스터링은 시간순 holdout 이 아니라 현재 축적분 전체에 대한 배치 재현이다.
