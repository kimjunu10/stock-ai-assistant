"""Solar Pro 답변 생성 경계 (SPEC §5, Phase 2).

- 스트리밍(SSE)과 비스트리밍 모두 지원.
- temperature 는 사실성 우선(기본 0.0).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from app.core.config import Settings


class SolarGenerator:
    def __init__(self, cfg: Settings, session: requests.Session | None = None) -> None:
        self._cfg = cfg
        self._session = session or requests.Session()

    def _payload(self, system: str, user: str, stream: bool) -> dict:
        return {
            "model": self._cfg.rag_chat_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._cfg.rag_chat_temperature,
            "stream": stream,
        }

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._cfg.upstage_api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, system: str, user: str) -> str:
        resp = self._session.post(
            f"{self._cfg.upstage_base_url}/chat/completions",
            headers=self._headers,
            json=self._payload(system, user, stream=False),
            timeout=self._cfg.rag_request_timeout_seconds,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def stream(self, system: str, user: str) -> Iterator[str]:
        """토큰 델타 텍스트를 순차적으로 yield 한다."""

        resp = self._session.post(
            f"{self._cfg.upstage_base_url}/chat/completions",
            headers=self._headers,
            json=self._payload(system, user, stream=True),
            timeout=self._cfg.rag_request_timeout_seconds,
            stream=True,
        )
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw or not raw.startswith(b"data:"):
                continue
            data = raw[len(b"data:") :].strip()
            if data == b"[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content")
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta:
                yield delta
