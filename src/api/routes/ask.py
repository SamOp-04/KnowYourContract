from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request

from src.api.routes._pipeline_qa import run_pipeline_query, schedule_pipeline_metrics
from src.api.schemas import AskRequest, AskResponse

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
async def ask_contract(
    payload: AskRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> AskResponse:
    result = await run_pipeline_query(
        request=request,
        query=payload.query,
        contract_id=payload.contract_id,
        ground_truth=payload.ground_truth or "",
        chat_id=payload.chat_id,
    )
    evaluation = schedule_pipeline_metrics(
        background_tasks=background_tasks,
        request=request,
        query=payload.query,
        result=result,
    )

    return AskResponse(
        answer=str(result.get("answer", "")),
        citations=list(result.get("citations", [])),
        sources=list(result.get("sources", [])),
        source_chunks=list(result.get("source_chunks", [])),
        tool_used=str(result.get("tool_used", "pipeline_contract_search")),
        route_reason=str(result.get("route_reason", "")),
        used_web_fallback=bool(result.get("used_web_fallback", False)),
        matched_clause_hints=list(result.get("matched_clause_hints", [])),
        evaluation=evaluation,
    )
