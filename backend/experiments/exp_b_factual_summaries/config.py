"""EXP-5 (사실 통합 본문) 고정 설정.

운영 확정 클러스터링 설정과 Solar 요약 설정을 한곳에 모은다. 재현성을 위해
모델 revision까지 고정한다. 이 값들은 SPEC v2.6 Step 4~6 및 prompt.md와 일치한다.
"""

from __future__ import annotations

# --- 클러스터링 (운영 확정값, SPEC Step 4~5) ---
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"  # 재현성 고정 (exp_a와 동일)
EMBEDDING_DIM = 1024
INPUT_TYPE = "B_title_desc"  # title + " " + description
PREPROCESS_VERSION = "v1"  # exp_a clustering_lib.PREPROCESS_VERSION과 동일해야 함
CLUSTERING_METHOD = "online_centroid"
COSINE_THRESHOLD = 0.74
ACTIVE_WINDOW_HOURS = 72
CLUSTERING_VERSION = "bge_m3_title_desc_centroid_v1"

# --- Solar 사실 통합 본문 (SPEC Step 6) ---
SOLAR_MODEL = "solar-pro3-260323"  # solar-pro3 pinned revision
SOLAR_BASE_URL = "https://api.upstage.ai/v1"
SUMMARY_PROMPT_VERSION = "factual_v1"
SOLAR_TEMPERATURE = 0.0
SOLAR_MAX_TOKENS = 700

# 요약 입력에 넣을 클러스터당 최대 기사 수(과도한 토큰 방지). 넘으면 발행 시간순으로 자름.
MAX_ARTICLES_PER_SUMMARY = 12
# 기사 본문(body)을 요약 입력에 포함할 때 기사당 최대 글자 수.
MAX_BODY_CHARS = 1200

STOCKS = ["005930", "000660", "034020", "042660", "005380"]
