"""Semantic stock-reference classification for ambiguous natural-language questions."""

from __future__ import annotations

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.core.config import Settings

StockReferenceRelation = Literal["none", "selected", "other", "multiple"]


class StockReferenceClassification(BaseModel):
    """Whether a question explicitly targets a company other than the UI selection."""

    relation: StockReferenceRelation
    company_names: list[str] = Field(default_factory=list, max_length=4)


_SYSTEM_PROMPT = """\
당신은 주식 질문에서 '질문의 대상 회사'만 분류하는 분류기입니다.
답변하거나 투자 정보를 생성하지 말고 제공된 스키마로만 분류하세요.

relation 기준:
- none: 회사가 명시되지 않았고 선택된 종목을 가리키는 일반 질문
- selected: 선택된 회사가 명시적으로 질문 대상임
- other: 선택 회사가 아닌 회사 하나가 질문 대상임
- multiple: 둘 이상의 회사가 질문 대상이거나 비교 요청임

중요:
- '가장 최근 공시', '제일 중요한 뉴스', '주요 리포트'의 가장/제일/주요/최근은
  회사명이 아니라 수식어입니다. 이런 표현만 있으면 none입니다.
- '이 종목', '이 회사', '해당 종목'은 selected입니다.
- 문장에 회사가 배경으로 등장해도 실제 질문 대상이 아니면 company_names에 넣지 마세요.
- company_names에는 실제 질문 대상 회사명만 원문 표기로 담으세요.
"""


class StockReferenceClassifier:
    """Small structured-output model used only for ambiguous company-like text."""

    def __init__(self, cfg: Settings, *, api_key: str, base_url: str):
        model = ChatOpenAI(
            model=cfg.agent_chat_model,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            timeout=cfg.agent_model_timeout_seconds,
            max_retries=0,
        )
        self._model = model.with_structured_output(
            StockReferenceClassification,
            method="function_calling",
        )

    def classify(
        self,
        question: str,
        *,
        selected_stock_code: str,
        selected_stock_name: str | None,
        supported_stock_names: list[str],
    ) -> StockReferenceClassification:
        payload = {
            "selected_stock_code": selected_stock_code,
            "selected_stock_name": selected_stock_name,
            "supported_stock_names": supported_stock_names,
            "question": question,
        }
        result = self._model.invoke(
            [
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ]
        )
        if isinstance(result, StockReferenceClassification):
            return result
        return StockReferenceClassification.model_validate(result)
