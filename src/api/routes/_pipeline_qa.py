from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import BackgroundTasks, HTTPException, Request
from fastapi.concurrency import run_in_threadpool


logger = logging.getLogger(__name__)


def _pipeline_query_timeout_seconds() -> float:
    raw_value = os.getenv("PIPELINE_QUERY_TIMEOUT_SECONDS", "90").strip()
    try:
        value = float(raw_value)
    except Exception:
        return 90.0
    return value if value > 0 else 0.0


def _strict_scope_enabled() -> bool:
    return os.getenv("REQUIRE_CHAT_SCOPE", "").strip().lower() in {"1", "true", "yes"}


def store_pipeline_metrics(
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


async def run_pipeline_query(
    request: Request,
    query: str,
    contract_id: str | None = None,
    ground_truth: str = "",
    chat_id: str | None = None,
) -> dict[str, Any]:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Pipeline is not initialized. Check startup logs and dependencies.",
        )

    strict_scope = _strict_scope_enabled()
    if contract_id and not chat_id:
        raise HTTPException(
            status_code=400,
            detail="chat_id is required when contract_id is provided.",
        )
    if strict_scope and not chat_id:
        raise HTTPException(
            status_code=400,
            detail="chat_id is required by server policy.",
        )

    allowed_contract_ids: list[str] | None = None
    if chat_id:
        chat_scope_registry = getattr(request.app.state, "chat_scope_registry", None)
        if chat_scope_registry is None:
            raise HTTPException(status_code=503, detail="Chat scope registry is not initialized.")

        allowed_contract_ids = await run_in_threadpool(chat_scope_registry.list_contract_ids, chat_id)
        if contract_id and contract_id not in set(allowed_contract_ids):
            raise HTTPException(status_code=403, detail="Contract is not accessible from this chat.")

    try:
        timeout_seconds = _pipeline_query_timeout_seconds()
        query_call = run_in_threadpool(
            pipeline.ask,
            query,
            contract_id,
            ground_truth,
            allowed_contract_ids,
        )
        if timeout_seconds <= 0:
            return await query_call
        return await asyncio.wait_for(query_call, timeout=timeout_seconds)
    except asyncio.TimeoutError as error:
        logger.warning("Pipeline query timed out after %.1f seconds", _pipeline_query_timeout_seconds())
        raise HTTPException(status_code=504, detail="Pipeline query timed out.") from error
    except Exception as error:
        logger.exception("Pipeline query failed")
        raise HTTPException(status_code=500, detail="Pipeline query failed.") from error


def schedule_pipeline_metrics(
    background_tasks: BackgroundTasks,
    request: Request,
    query: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    evaluation = dict(result.get("evaluation", {}))
    background_tasks.add_task(
        store_pipeline_metrics,
        request,
        query,
        str(result.get("answer", "")),
        str(result.get("tool_used", "pipeline_contract_search")),
        bool(result.get("used_web_fallback", False)),
        evaluation,
    )
    return evaluation
