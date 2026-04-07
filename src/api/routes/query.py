from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from src.api.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


def _store_pipeline_metrics(
    request: Request,
    query: str,
    answer: str,
    tool_used: str,
    used_web_fallback: bool,
    evaluation: dict[str, Any],
) -> None:
    metrics_store = request.app.state.metrics_store
    metrics_store.save_metric(
        {
            "query": query,
            "answer": answer,
            "tool_used": tool_used,
            "used_web_fallback": used_web_fallback,
            "faithfulness": float(evaluation.get("faithfulness", 0.0)),
            "answer_relevance": float(evaluation.get("answer_relevance", 0.0)),
            "context_precision": float(evaluation.get("context_precision", 0.0)),
            "context_recall": float(evaluation.get("context_recall", 0.0)),
        }
    )


@router.post("/query", response_model=QueryResponse)
async def query_contract(
    payload: QueryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> QueryResponse:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Pipeline is not initialized. Check startup logs and dependencies.",
        )

    allowed_contract_ids: list[str] | None = None
    if payload.chat_id:
        chat_scope_registry = getattr(request.app.state, "chat_scope_registry", None)
        if chat_scope_registry is None:
            raise HTTPException(status_code=503, detail="Chat scope registry is not initialized.")

        allowed_contract_ids = await run_in_threadpool(chat_scope_registry.list_contract_ids, payload.chat_id)
        if payload.contract_id and payload.contract_id not in set(allowed_contract_ids):
            raise HTTPException(status_code=403, detail="Contract is not accessible from this chat.")

    try:
        result = await run_in_threadpool(
            pipeline.ask,
            payload.query,
            payload.contract_id,
            "",
            allowed_contract_ids,
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Query failed: {error}") from error

    evaluation = dict(result.get("evaluation", {}))
    background_tasks.add_task(
        _store_pipeline_metrics,
        request,
        payload.query,
        str(result.get("answer", "")),
        str(result.get("tool_used", "pipeline_contract_search")),
        bool(result.get("used_web_fallback", False)),
        evaluation,
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
