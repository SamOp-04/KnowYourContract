from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.retrieval.dense_retriever import DEFAULT_FAISS_DIR, DenseRetriever
from src.retrieval.sparse_retriever import DEFAULT_BM25_PATH, DEFAULT_CHUNKS_PATH, SparseRetriever

RRF_K = 60


@dataclass
class HybridResult:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    dense_score: float | None
    sparse_score: float | None
    dense_rank: int | None
    sparse_rank: int | None
    fused_score: float


def rrf_merge(
    dense_results: list[Any],
    sparse_results: list[Any],
    k: int = RRF_K,
) -> list[HybridResult]:
    merged: dict[str, HybridResult] = {}

    for rank, result in enumerate(dense_results, start=1):
        chunk_id = str(result.chunk_id)
        if chunk_id not in merged:
            merged[chunk_id] = HybridResult(
                chunk_id=chunk_id,
                text=str(result.text),
                metadata=dict(result.metadata),
                dense_score=float(result.score),
                sparse_score=None,
                dense_rank=rank,
                sparse_rank=None,
                fused_score=0.0,
            )
        merged[chunk_id].dense_rank = rank
        merged[chunk_id].dense_score = float(result.score)
        merged[chunk_id].fused_score += 1.0 / (rank + k)

    for rank, result in enumerate(sparse_results, start=1):
        chunk_id = str(result.chunk_id)
        if chunk_id not in merged:
            merged[chunk_id] = HybridResult(
                chunk_id=chunk_id,
                text=str(result.text),
                metadata=dict(result.metadata),
                dense_score=None,
                sparse_score=float(result.score),
                dense_rank=None,
                sparse_rank=rank,
                fused_score=0.0,
            )
        merged[chunk_id].sparse_rank = rank
        merged[chunk_id].sparse_score = float(result.score)
        merged[chunk_id].fused_score += 1.0 / (rank + k)

    return sorted(merged.values(), key=lambda item: item.fused_score, reverse=True)


class HybridRetriever:
    def __init__(
        self,
        dense_retriever: DenseRetriever,
        sparse_retriever: SparseRetriever,
    ) -> None:
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever

    @classmethod
    def from_artifacts(
        cls,
        faiss_dir: Path | str = DEFAULT_FAISS_DIR,
        chunks_path: Path | str = DEFAULT_CHUNKS_PATH,
        bm25_path: Path | str = DEFAULT_BM25_PATH,
    ) -> "HybridRetriever":
        dense = DenseRetriever(index_dir=faiss_dir)
        sparse = SparseRetriever(chunks_path=chunks_path, index_path=bm25_path)
        return cls(dense_retriever=dense, sparse_retriever=sparse)

    def refresh(self) -> None:
        self.dense_retriever.reload()
        self.sparse_retriever.reload()

    def get_top_k(
        self,
        query: str,
        k: int = 5,
        dense_k: int = 20,
        sparse_k: int = 20,
    ) -> list[dict[str, Any]]:
        dense_results = self.dense_retriever.get_top_k(query=query, k=dense_k)
        sparse_results = self.sparse_retriever.get_top_k(query=query, k=sparse_k)
        fused_results = rrf_merge(dense_results, sparse_results, k=RRF_K)
        return [asdict(item) for item in fused_results[:k]]
