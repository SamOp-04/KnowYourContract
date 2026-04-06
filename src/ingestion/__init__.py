"""Data ingestion utilities for loading, chunking, and embedding CUAD contracts."""

from src.ingestion.chunker import build_chunks_from_cuad
from src.ingestion.embedder import build_faiss_index
from src.ingestion.loader import build_contract_records, load_cuad_dataset

__all__ = [
    "build_chunks_from_cuad",
    "build_contract_records",
    "build_faiss_index",
    "load_cuad_dataset",
]
