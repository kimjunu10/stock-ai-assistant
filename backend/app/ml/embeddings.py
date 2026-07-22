"""Upstage Embed 2 임베딩 경계 (SPEC §5, Phase 0 검증).

- 문서(passage)와 질문(query)에 서로 다른 모델명을 쓴다(같은 검색쌍).
- 차원은 1024. 다른 세대/차원 벡터를 섞지 않는다(고정 원칙).
- 배치 최대 100개. 429/5xx 는 지수 백오프 재시도.
"""

from __future__ import annotations

import hashlib
import time

import requests

from app.core.config import Settings


def content_hash(text: str) -> str:
    """청크/문서 내용 해시. 동일 내용 재임베딩 방지에 사용."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class UpstageEmbedder:
    """Upstage Embed 2 클라이언트(동기)."""

    def __init__(self, cfg: Settings, session: requests.Session | None = None) -> None:
        self._cfg = cfg
        self._session = session or requests.Session()

    def _embed(self, model: str, inputs: list[str], max_retries: int = 4) -> list[list[float]]:
        if not inputs:
            return []
        url = f"{self._cfg.upstage_base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._cfg.upstage_api_key}",
            "Content-Type": "application/json",
        }
        out: list[list[float]] = []
        batch = self._cfg.rag_embedding_batch_size
        for start in range(0, len(inputs), batch):
            chunk = inputs[start : start + batch]
            payload = {"model": model, "input": chunk}
            delay = 1.0
            for attempt in range(max_retries):
                resp = self._session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self._cfg.rag_request_timeout_seconds,
                )
                if resp.status_code == 200:
                    data = sorted(resp.json()["data"], key=lambda d: d["index"])
                    vectors = [d["embedding"] for d in data]
                    self._check_dimension(vectors)
                    out.extend(vectors)
                    break
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
        return out

    def _check_dimension(self, vectors: list[list[float]]) -> None:
        expected = self._cfg.rag_embedding_dimension
        for v in vectors:
            if len(v) != expected:
                raise ValueError(
                    f"임베딩 차원 불일치: expected {expected}, got {len(v)} "
                    "(다른 세대/차원 벡터 혼용 금지)"
                )

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed(self._cfg.rag_embedding_passage_model, texts)

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embed(self._cfg.rag_embedding_query_model, [text])
        return vectors[0] if vectors else []
