# 뉴스 클러스터 FISA 감성분류 운영

## 기준

- 입력: `news_clusters.representative_article_id`가 가리키는 `articles.title`만 사용
- 모델: `FISA-conclave/klue-roberta-news-sentiment`
- revision: `b1950b9499e5f24e1e36593c62720cc1b2326c6b`
- 입력 버전: `cluster_title_v1`
- 라벨: `0=negative`, `1=neutral`, `2=positive`
- 최대 길이: 128 tokens

요약 제목, 요약문, 기업명, 기사 본문은 입력에 사용하지 않는다. 감성은 뉴스 내용의
방향이며 중요도나 주가 예측이 아니다.

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

미분류, `unknown`, 모델/revision/input version 불일치, 대표 제목 hash 변경 대상만 처리:

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
