from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

from src.agent.agent import LegalContractAgent
from src.api.schemas import UploadBatchResponse, UploadItemResponse, UploadResponse
from src.ingestion.chunker import build_splitter, chunk_contract
from src.ingestion.embedder import build_faiss_index, build_sparse_index, save_metadata
from src.retrieval.hybrid_retriever import HybridRetriever

router = APIRouter(tags=["upload"])

RAW_UPLOAD_DIR = Path("data/raw/uploads")
CHUNKS_PATH = Path("data/processed/chunks.jsonl")
FAISS_DIR = Path("data/processed/faiss_index")
METADATA_PATH = Path("data/processed/chunk_metadata.json")


def _extract_text(filename: str, file_bytes: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        if PdfReader is None:
            raise ValueError("PDF parsing requires pypdf to be installed.")
        reader = PdfReader(BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    return file_bytes.decode("utf-8", errors="ignore")


def _append_chunks(chunks: list[dict[str, Any]]) -> None:
    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("a", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk) + "\n")


def _rebuild_indexes_and_reload_agent(request: Request) -> None:
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Missing chunks file at {CHUNKS_PATH}")

    chunks = []
    with CHUNKS_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))

    build_faiss_index(chunks=chunks, output_dir=FAISS_DIR)
    save_metadata(chunks=chunks, output_path=METADATA_PATH)
    build_sparse_index(chunks=chunks)

    hybrid_retriever = HybridRetriever.from_artifacts()
    request.app.state.hybrid_retriever = hybrid_retriever
    request.app.state.agent = LegalContractAgent(hybrid_retriever=hybrid_retriever)


@router.post("/upload", response_model=UploadResponse | UploadBatchResponse)
async def upload_contract(
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
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

    upload_results: list[UploadItemResponse] = []
    legacy_chunks_to_append: list[dict[str, Any]] = []

    for index, upload in enumerate(upload_items, start=1):
        file_bytes = await upload.read()
        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded file is empty: {upload.filename or f'file_{index}'}",
            )

        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
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

        try:
            text = _extract_text(upload.filename or "contract.txt", file_bytes)
            if text.strip():
                RAW_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                raw_text_path = RAW_UPLOAD_DIR / f"{contract_id}.txt"
                raw_text_path.write_text(text, encoding="utf-8")

                splitter = build_splitter()
                chunks = chunk_contract(
                    {
                        "contract_name": contract_id,
                        "contract_text": text,
                        "clause_type": "uploaded_contract",
                    },
                    splitter=splitter,
                )
                if chunks:
                    legacy_chunks_to_append.extend(chunks)
        except Exception:
            # Ignore legacy indexing prep errors; primary pipeline indexing already succeeded.
            pass

        upload_results.append(
            UploadItemResponse(
                contract_id=str(pipeline_result.get("contract_id", contract_id)),
                source_name=upload.filename or f"contract_{index}",
                chunks_ingested=int(pipeline_result.get("chunks_ingested", 0)),
                message=str(pipeline_result.get("message", "Contract uploaded and indexed successfully.")),
            )
        )

    legacy_status = "Legacy FAISS/BM25 index updated for /query compatibility."
    try:
        if legacy_chunks_to_append:
            _append_chunks(legacy_chunks_to_append)
            await run_in_threadpool(_rebuild_indexes_and_reload_agent, request)
        else:
            legacy_status = "Legacy index update skipped: no legacy chunks were produced."
    except Exception as error:
        legacy_status = f"Legacy index update skipped: {error}"

    if len(upload_results) == 1:
        single = upload_results[0]
        return UploadResponse(
            contract_id=single.contract_id,
            chunks_ingested=single.chunks_ingested,
            message=f"{single.message} {legacy_status}",
        )

    return UploadBatchResponse(
        uploads=upload_results,
        total_files=len(upload_results),
        message=f"Indexed {len(upload_results)} files. {legacy_status}",
    )
