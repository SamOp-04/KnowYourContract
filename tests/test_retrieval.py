from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.retrieval.hybrid_retriever import HybridRetriever, rrf_merge
from src.retrieval.sparse_retriever import SparseRetriever, build_and_save_bm25


def _sample_chunks() -> list[dict]:
    return [
        {
            "chunk_id": "c1",
            "text": "This clause defines indemnification obligations and liability cap.",
            "metadata": {"contract_name": "contract_alpha", "clause_type": "indemnification"},
        },
        {
            "chunk_id": "c2",
            "text": "Termination for convenience is allowed with 30 days written notice.",
            "metadata": {"contract_name": "contract_alpha", "clause_type": "termination"},
        },
        {
            "chunk_id": "c3",
            "text": "Confidential information must not be disclosed to third parties.",
            "metadata": {"contract_name": "contract_alpha", "clause_type": "confidentiality"},
        },
    ]


def test_sparse_retriever_returns_expected_chunk(tmp_path: Path) -> None:
    chunks = _sample_chunks()
    chunks_path = tmp_path / "chunks.jsonl"
    index_path = tmp_path / "bm25.pkl"

    with chunks_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk) + "\n")

    build_and_save_bm25(chunks=chunks, output_path=index_path)

    retriever = SparseRetriever(chunks_path=chunks_path, index_path=index_path)
    results = retriever.get_top_k("termination for convenience", k=2)

    assert results
    assert results[0].chunk_id == "c2"


@dataclass
class _MockResult:
    chunk_id: str
    text: str
    metadata: dict
    score: float


def test_rrf_merge_prefers_docs_ranked_by_both_retrievers() -> None:
    dense_results = [
        _MockResult("a", "dense a", {}, 0.11),
        _MockResult("b", "dense b", {}, 0.18),
    ]
    sparse_results = [
        _MockResult("b", "sparse b", {}, 4.0),
        _MockResult("c", "sparse c", {}, 3.5),
    ]

    fused = rrf_merge(dense_results, sparse_results, k=60)

    assert fused
    assert fused[0].chunk_id == "b"


class _FakeDenseRetriever:
    def get_top_k(self, query: str, k: int = 20) -> list[_MockResult]:
        return [
            _MockResult("a", "dense text a", {}, 0.2),
            _MockResult("b", "dense text b", {}, 0.3),
        ]

    def reload(self) -> None:
        return None


class _FakeSparseRetriever:
    def get_top_k(self, query: str, k: int = 20) -> list[_MockResult]:
        return [
            _MockResult("b", "sparse text b", {}, 7.1),
            _MockResult("c", "sparse text c", {}, 6.9),
        ]

    def reload(self) -> None:
        return None


def test_hybrid_retriever_uses_rrf_merge() -> None:
    hybrid = HybridRetriever(dense_retriever=_FakeDenseRetriever(), sparse_retriever=_FakeSparseRetriever())
    top = hybrid.get_top_k("indemnification clause", k=2)

    assert len(top) == 2
    assert top[0]["chunk_id"] == "b"
