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
from src.api.schemas import UploadResponse
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


@router.post("/upload", response_model=UploadResponse)
async def upload_contract(request: Request, file: UploadFile = File(...)) -> UploadResponse:

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    text = _extract_text(file.filename or "contract.txt", file_bytes)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from uploaded file.")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_name = Path(file.filename or "contract").stem
    contract_id = f"{base_name}_{timestamp}"

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

    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks created from uploaded contract.")

    _append_chunks(chunks)

    try:
        await run_in_threadpool(_rebuild_indexes_and_reload_agent, request)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to update retriever indexes: {error}") from error

    return UploadResponse(
        contract_id=contract_id,
        chunks_ingested=len(chunks),
        message="Contract uploaded and indexed successfully.",
    )
