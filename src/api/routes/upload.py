from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from src.api.schemas import UploadBatchResponse, UploadItemResponse, UploadResponse

router = APIRouter(tags=["upload"])

@router.post("/upload", response_model=UploadResponse | UploadBatchResponse)
async def upload_contract(
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    chat_id: str | None = Form(default=None),
) -> UploadResponse | UploadBatchResponse:

    upload_items: list[UploadFile] = []
    if file is not None:
        upload_items.append(file)
    if files:
        upload_items.extend(files)

    if not upload_items:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline is not initialized.")

    chat_scope_registry = getattr(request.app.state, "chat_scope_registry", None)
    if chat_scope_registry is None:
        raise HTTPException(status_code=503, detail="Chat scope registry is not initialized.")

    resolved_chat_id = str(chat_id or "").strip() or str(uuid.uuid4())

    upload_results: list[UploadItemResponse] = []

    for index, upload in enumerate(upload_items, start=1):
        file_bytes = bytearray()
        CHUNK_SIZE = 1024 * 1024
        MAX_SIZE = 10 * 1024 * 1024

        while chunk := await upload.read(CHUNK_SIZE):
            file_bytes.extend(chunk)
            if len(file_bytes) > MAX_SIZE:
                raise HTTPException(status_code=413, detail=f"File too large: {upload.filename}")

        file_bytes = bytes(file_bytes)
        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded file is empty: {upload.filename or f'file_{index}'}",
            )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        base_name = Path(upload.filename or f"contract_{index}").stem
        contract_id = f"{base_name}_{timestamp}"

        try:
            pipeline_result = await run_in_threadpool(
                pipeline.ingest_upload,
                upload.filename or "contract.txt",
                file_bytes,
                contract_id,
            )
        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail=f"Pipeline ingestion failed for {upload.filename or contract_id}: {error}",
            ) from error

        upload_results.append(
            UploadItemResponse(
                contract_id=str(pipeline_result.get("contract_id", contract_id)),
                source_name=upload.filename or f"contract_{index}",
                chunks_ingested=int(pipeline_result.get("chunks_ingested", 0)),
                message=str(pipeline_result.get("message", "Contract uploaded and indexed successfully.")),
            )
        )

    await run_in_threadpool(
        chat_scope_registry.add_contracts,
        resolved_chat_id,
        [item.contract_id for item in upload_results],
    )

    if len(upload_results) == 1:
        single = upload_results[0]
        return UploadResponse(
            chat_id=resolved_chat_id,
            contract_id=single.contract_id,
            chunks_ingested=single.chunks_ingested,
            message=single.message,
        )

    return UploadBatchResponse(
        chat_id=resolved_chat_id,
        uploads=upload_results,
        total_files=len(upload_results),
        message=f"Indexed {len(upload_results)} files using the unified Chroma pipeline.",
    )
