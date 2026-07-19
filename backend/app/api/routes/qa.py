"""RAG question-answering API routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/qa", tags=["qa"])
