from __future__ import annotations

from fastapi import APIRouter, Query, Request

from src.api.schemas import MetricsResponse

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
) -> MetricsResponse:
    store = request.app.state.metrics_store
    recent = store.list_recent(limit=limit)
    trends = store.get_trends(days=days)
    analytics = store.get_query_analytics()

    return MetricsResponse(recent=recent, trends=trends, analytics=analytics)
