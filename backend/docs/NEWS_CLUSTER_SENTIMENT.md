# 뉴스 클러스터 감성분류 운영

## 기준

- 입력: Solar가 사건 단위로 확정한 `news_clusters.summary_title`만 사용
- 모델: `FISA-conclave/klue-roberta-news-sentiment`
- revision: `b1950b9499e5f24e1e36593c62720cc1b2326c6b`
- 입력 버전: `cluster_summary_title_v2`
- 라벨: `0=negative`, `1=neutral`, `2=positive`
- 최대 길이: 128 tokens

처리 순서는 `기사 클러스터링 → 사건 요약 저장 → summary_title 감성분류 → DB 저장`이다.
대표 기사 제목, 쉬운 설명, 사실 본문, 기업명은 감성 모델 입력에 사용하지 않는다.
요약이 성공하지 않았거나 `summary_title`이 비어 있으면 분류하지 않는다.

`representative_article_id`는 대표 원문을 연결하기 위한 값이며 감성분류 입력의 기준이
아니다. 한 기사에 등장하는 경쟁사나 부정적인 표현이 클러스터 전체 감성으로 오인되는
문제를 줄이기 위해, 사건 전체를 반영한 클러스터 제목을 사용한다.

저장되는 값은 모델의 원래 `positive`, `neutral`, `negative` 확률이다. 감성은 해당
뉴스 사건의 내용 방향을 보조적으로 보여주는 값이며, 중요도나 실제 주가의 상승·하락
예측이 아니다.

## 신규 클러스터 처리

`backend/scripts/run_full_news_v2.py`의 `phase_summary()`가 다음 순서로 처리한다.

1. 클러스터에 배정된 기사들을 Solar로 통합 요약한다.
2. `summary_title`, `easy_explanation`, `factual_body`, `summary_status=success`를 저장한다.
3. 저장된 `summary_title`을 감성 서비스에 전달한다.
4. 라벨·세 확률·모델 ID·revision·입력 버전·입력 hash·분석 시각을 저장한다.

요약 또는 감성 모델 호출이 실패해도 뉴스 수집·클러스터링 전체 작업은 중단하지 않는다.
감성 모델 실패 시 해당 결과만 `unknown`으로 격리한다.

## 마이그레이션

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f backend/migrations/0020_news_cluster_sentiment.sql
```

rollback:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f backend/migrations/rollback/0020_news_cluster_sentiment_down.sql
```

## 환경변수

```dotenv
SENTIMENT_ENABLED=true
SENTIMENT_MODEL_ID=FISA-conclave/klue-roberta-news-sentiment
SENTIMENT_MODEL_REVISION=b1950b9499e5f24e1e36593c62720cc1b2326c6b
SENTIMENT_MODEL_CACHE_DIR=
SENTIMENT_DEVICE=auto
```

`auto`는 CUDA가 있으면 CUDA, 없으면 CPU를 선택한다. 모델 로딩이 실패해도 FastAPI는
시작하고 감성 결과만 `unknown`으로 격리한다.

## 기존 데이터 backfill

대상은 현재 클러스터링 버전이면서 `summary_status=success`이고 `summary_title`이 있는
클러스터로 제한한다. 그중 미분류, `unknown`, 모델/revision/input version 불일치,
클러스터 요약 제목 hash 변경 대상만 처리한다.

```bash
cd backend
uv run python -m scripts.backfill_news_sentiment --batch-size 32
```

전체 강제 재분류:

```bash
cd backend
uv run python -m scripts.backfill_news_sentiment --batch-size 32 --force
```

클러스터를 id 순으로 page 처리하므로 전체 데이터를 메모리에 올리지 않는다. 성공한
클러스터는 다음 실행에서 건너뛰며, `unknown` 또는 저장 실패는 다음 실행에서 다시
시도할 수 있다.

이전 `cluster_title_v1` 결과는 현재 입력 버전과 다르므로 backfill 대상이 된다. 배포만
으로 기존 행이 자동 재분류되지는 않으며, 기존 배지를 갱신하려면 위 명령을 별도로
실행해야 한다.

## Docker 모델 캐시

`deploy/docker-compose.prod.yml`은 다음 경로를 기존 named volume에 연결한다.

```text
huggingface-cache -> /root/.cache/huggingface
SENTIMENT_MODEL_CACHE_DIR=/root/.cache/huggingface
```

컨테이너를 재생성해도 모델 cache는 유지된다. 첫 배포 전에 동일 image와 환경변수로
컨테이너를 한 번 기동해 고정 revision을 cache warming하거나, 배포 host에서 다음
명령으로 받아둘 수 있다.

```bash
docker compose -f deploy/docker-compose.prod.yml run --rm backend \
  python -c "from transformers import AutoTokenizer,AutoModelForSequenceClassification; r='b1950b9499e5f24e1e36593c62720cc1b2326c6b'; m='FISA-conclave/klue-roberta-news-sentiment'; AutoTokenizer.from_pretrained(m,revision=r); AutoModelForSequenceClassification.from_pretrained(m,revision=r)"
```

모델 파일은 Git에 커밋하지 않는다. BGE-M3와 FISA는 각각 process singleton으로
로드되며 Hugging Face cache volume만 공유한다.
