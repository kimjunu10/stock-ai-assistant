"""Stock and stock-home API routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/stocks", tags=["stocks"])
