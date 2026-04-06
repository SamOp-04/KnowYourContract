from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Citation(BaseModel):
    chunk_id: str = ""
    contract_name: str = ""
    clause_type: str = ""
    page_number: int | None = None
    url: str = ""


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3)
    contract_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    source_chunks: list[dict[str, Any]]
    tool_used: str
    route_reason: str
    used_web_fallback: bool = False


class UploadResponse(BaseModel):
    contract_id: str
    chunks_ingested: int
    message: str


class MetricRow(BaseModel):
    id: int
    query: str
    answer: str
    tool_used: str
    used_web_fallback: bool
    faithfulness: float
    answer_relevance: float
    context_precision: float
    context_recall: float
    created_at: str


class MetricsResponse(BaseModel):
    recent: list[MetricRow]
    trends: list[MetricRow]
    analytics: list[dict[str, Any]]
