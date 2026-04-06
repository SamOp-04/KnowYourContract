from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class Citation(BaseModel):
    chunk_id: str = ""
    contract_name: str = ""
    clause_type: str = ""
    page_number: int | None = None
    url: str = ""


class SourceReference(BaseModel):
    index: int
    label: str
    contract_id: str = ""


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3)
    contract_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    sources: list[SourceReference] = Field(default_factory=list)
    source_chunks: list[dict[str, Any]]
    tool_used: str
    route_reason: str
    used_web_fallback: bool = False


class AskRequest(QueryRequest):
    ground_truth: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_question_alias(cls, value: Any) -> Any:
        if isinstance(value, dict) and "query" not in value and "question" in value:
            normalized = dict(value)
            normalized["query"] = normalized.get("question")
            return normalized
        return value


class AskResponse(QueryResponse):
    matched_clause_hints: list[str] = Field(default_factory=list)
    evaluation: dict[str, Any] = Field(default_factory=dict)


class UploadResponse(BaseModel):
    contract_id: str
    chunks_ingested: int
    message: str


class UploadItemResponse(BaseModel):
    contract_id: str
    source_name: str
    chunks_ingested: int
    message: str


class UploadBatchResponse(BaseModel):
    uploads: list[UploadItemResponse]
    total_files: int
    message: str


class ContractSummary(BaseModel):
    contract_id: str
    display_name: str
    source_name: str
    chunks_ingested: int
    uploaded_at: str


class ContractsResponse(BaseModel):
    contracts: list[ContractSummary]
    total: int


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
