from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request

from src.api.routes._pipeline_qa import run_pipeline_query, schedule_pipeline_metrics
from src.api.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_contract(
    payload: QueryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> QueryResponse:
    result = await run_pipeline_query(
        request=request,
        query=payload.query,
        contract_id=payload.contract_id,
        ground_truth="",
        chat_id=payload.chat_id,
    )
    schedule_pipeline_metrics(
        background_tasks=background_tasks,
        request=request,
        query=payload.query,
        result=result,
    )

    return QueryResponse(
        answer=str(result.get("answer", "")),
        citations=list(result.get("citations", [])),
        sources=list(result.get("sources", [])),
        source_chunks=list(result.get("source_chunks", [])),
        tool_used=str(result.get("tool_used", "pipeline_contract_search")),
        route_reason=str(result.get("route_reason", "")),
        used_web_fallback=bool(result.get("used_web_fallback", False)),
    )
