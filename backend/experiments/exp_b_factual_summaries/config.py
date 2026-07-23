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

# --- over-merge 보호 (시장 뉴스 + 비사건형 투자정보 브리지 차단) ---
# 기본은 끄기(False) → 기존 결과와 100% 동일. 켜면 시황(market)·비사건형 투자정보(info)
# 기사가 종목 고유 사건(company) 클러스터에 붙지 못하게 하고, market/info 끼리는 같은
# 거래일 안에서만 묶는다. 자세한 근거: overmerge_fix/OVER_MERGE_FIX_REPORT.md
BLOCK_MARKET_BRIDGE = False
MARKET_DAY_BOUNDARY = True  # market/info 클러스터는 같은 거래일만(BLOCK_MARKET_BRIDGE=True일 때만)
SEPARATE_INFO = (
    True  # 비사건형 투자정보(info)를 별도 유형으로 분리(BLOCK_MARKET_BRIDGE=True일 때만)
)
# 보호 기능을 켰을 때 사용할 새 클러스터링 버전명(기존 산출물과 구분).
CLUSTERING_VERSION_PROTECTED = "bge_m3_title_desc_centroid_bridge_info_v3"

# --- Solar 사실 통합 본문 (SPEC Step 6) ---
SOLAR_MODEL = "solar-pro3-260323"  # solar-pro3 pinned revision
SOLAR_BASE_URL = "https://api.upstage.ai/v1"
SUMMARY_PROMPT_VERSION = "factual_easy_v5_plain_core"
SOLAR_TEMPERATURE = 0.0
SOLAR_MAX_TOKENS = 1800

# 요약 입력에 넣을 클러스터당 최대 기사 수(과도한 토큰 방지). 넘으면 발행 시간순으로 자름.
MAX_ARTICLES_PER_SUMMARY = 12
# 기사 본문(body)을 요약 입력에 포함할 때 기사당 최대 글자 수.
MAX_BODY_CHARS = 2400

# --- LLM 동일사건 배정 (하이브리드: BGE-M3 후보검색 → Solar Pro3 판정) ---
# feature flag. True 면 company 기사를 LLM 판정으로 배정, False 면 기존 거리 단독 배정.
# 끄면 기존 방식으로 롤백된다(로직 삭제 없음).
USE_LLM_ASSIGN = False
# LLM 에 넘길 임베딩 후보 최대 개수(한 번의 요청으로 판정).
LLM_ASSIGN_MAX_CANDIDATES = 5
# 후보 검색 시 최소 유사도 하한(이 미만 후보는 애초에 배정 후보에서 제외).
# threshold(0.74)보다 낮춰 LLM 이 판정할 여지를 넓히되, 완전 무관한 건 거른다.
LLM_ASSIGN_CANDIDATE_MIN_SIM = 0.55
LLM_ASSIGN_MODEL = "solar-pro3-260323"
LLM_ASSIGN_PROMPT_VERSION = "same_event_v1"
LLM_ASSIGN_MAX_TOKENS = 200

STOCKS = ["005930", "000660", "034020", "042660", "005380"]
