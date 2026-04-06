from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas import ContractsResponse

router = APIRouter(tags=["contracts"])


@router.get("/contracts", response_model=ContractsResponse)
async def list_contracts(request: Request) -> ContractsResponse:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Pipeline is not initialized. Check startup logs and dependencies.",
        )

    contracts = list(pipeline.list_contracts())
    return ContractsResponse(contracts=contracts, total=len(contracts))
