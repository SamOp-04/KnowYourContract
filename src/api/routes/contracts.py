from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.schemas import ContractsResponse

router = APIRouter(tags=["contracts"])


@router.get("/contracts", response_model=ContractsResponse)
async def list_contracts(
    request: Request,
    chat_id: str | None = Query(default=None),
) -> ContractsResponse:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Pipeline is not initialized. Check startup logs and dependencies.",
        )

    contracts = list(pipeline.list_contracts())

    if chat_id:
        chat_scope_registry = getattr(request.app.state, "chat_scope_registry", None)
        if chat_scope_registry is None:
            raise HTTPException(status_code=503, detail="Chat scope registry is not initialized.")

        allowed_contract_ids = set(chat_scope_registry.list_contract_ids(chat_id))
        contracts = [
            item
            for item in contracts
            if str(item.get("contract_id", "")).strip() in allowed_contract_ids
        ]

    return ContractsResponse(contracts=contracts, total=len(contracts))
