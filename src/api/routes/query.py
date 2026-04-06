from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from src.api.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


def _extract_contexts(source_chunks: list[dict[str, Any]]) -> list[str]:
    contexts = []
    for chunk in source_chunks:
        if not isinstance(chunk, dict):
            continue
        text = chunk.get("text") or chunk.get("content") or ""
        if text:
            contexts.append(str(text))
    return contexts


def _evaluate_and_store(
    request: Request,
    query: str,
    answer: str,
    contexts: list[str],
    tool_used: str,
    used_web_fallback: bool,
) -> None:
    evaluator = request.app.state.evaluator
    store = request.app.state.metrics_store

    metrics = evaluator.evaluate_single(
        question=query,
        answer=answer,
        contexts=contexts,
        ground_truth="",
    )

    payload = {
        "query": query,
        "answer": answer,
        "tool_used": tool_used,
        "used_web_fallback": used_web_fallback,
        **metrics,
    }
    store.save_metric(payload)


@router.post("/query", response_model=QueryResponse)
async def query_contract(
    payload: QueryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> QueryResponse:
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="Agent is not initialized. Run ingestion and embedding pipeline first.",
        )

    try:
        result = await run_in_threadpool(agent.run, payload.query, payload.contract_id)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Query failed: {error}") from error

    source_chunks = result.get("source_chunks", [])
    contexts = _extract_contexts(source_chunks)
    background_tasks.add_task(
        _evaluate_and_store,
        request,
        payload.query,
        result.get("answer", ""),
        contexts,
        result.get("tool_used", "contract_search"),
        bool(result.get("used_web_fallback", False)),
    )

    return QueryResponse(
        answer=result.get("answer", ""),
        citations=result.get("citations", []),
        sources=result.get("sources", []),
        source_chunks=source_chunks,
        tool_used=result.get("tool_used", "contract_search"),
        route_reason=result.get("route_reason", ""),
        used_web_fallback=bool(result.get("used_web_fallback", False)),
    )
