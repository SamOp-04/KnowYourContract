from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.pipeline.retriever import BM25Okapi, ClauseAwareRetriever


@dataclass
class _Doc:
    page_content: str
    metadata: dict[str, Any]


class _FakeChromaStore:
    def __init__(self, results_by_query: dict[str, list[tuple[_Doc, float]]]) -> None:
        self.results_by_query = results_by_query

    def similarity_search_with_score(
        self,
        query: str,
        k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[tuple[_Doc, float]]:
        results = list(self.results_by_query.get(query, []))
        if filter:
            filtered_results: list[tuple[_Doc, float]] = []
            for document, score in results:
                matches = True
                for key, value in filter.items():
                    if str(document.metadata.get(key)) != str(value):
                        matches = False
                        break
                if matches:
                    filtered_results.append((document, score))
            results = filtered_results
        return results[:k]


class _FakeVectorStore:
    def __init__(self, store: _FakeChromaStore) -> None:
        self.store = store

    def get_store(self) -> _FakeChromaStore:
        return self.store


def test_clause_aware_retriever_applies_contract_filter() -> None:
    query = "termination notice"
    store = _FakeChromaStore(
        {
            query: [
                (_Doc("Contract A termination terms", {"chunk_id": "a", "contract_id": "contract_a"}), 0.92),
                (_Doc("Contract B termination terms", {"chunk_id": "b", "contract_id": "contract_b"}), 0.91),
            ]
        }
    )
    retriever = ClauseAwareRetriever(
        vector_store=_FakeVectorStore(store),
        default_k=2,
        candidate_k=2,
        enable_sparse_rerank=False,
    )

    results = retriever.get_top_k(query=query, contract_id="contract_b", k=2, clause_hints=[])

    assert results
    assert all(item.get("metadata", {}).get("contract_id") == "contract_b" for item in results)


def test_clause_aware_retriever_sparse_rerank_changes_order() -> None:
    query = "obligation breach remedy"
    store = _FakeChromaStore(
        {
            query: [
                (_Doc("obligation breach remedy", {"chunk_id": "a", "contract_id": "contract_a"}), 0.76),
                (
                    _Doc(
                        "obligation obligation obligation breach breach remedy remedy remedy remedy",
                        {"chunk_id": "b", "contract_id": "contract_a"},
                    ),
                    0.75,
                ),
            ]
        }
    )
    vector_store = _FakeVectorStore(store)

    without_sparse = ClauseAwareRetriever(
        vector_store=vector_store,
        default_k=2,
        candidate_k=2,
        enable_sparse_rerank=False,
    )
    with_sparse = ClauseAwareRetriever(
        vector_store=vector_store,
        default_k=2,
        candidate_k=2,
        enable_sparse_rerank=True,
        sparse_rerank_weight=0.3,
    )

    without_sparse_results = without_sparse.get_top_k(query=query, k=2, clause_hints=[])
    with_sparse_results = with_sparse.get_top_k(query=query, k=2, clause_hints=[])

    assert without_sparse_results[0]["chunk_id"] == "a"

    if BM25Okapi is None:
        # Optional dependency path: rerank is skipped when rank_bm25 is unavailable.
        assert with_sparse_results[0]["chunk_id"] == "a"
        return

    baseline_by_id = {item["chunk_id"]: item for item in without_sparse_results}
    sparse_by_id = {item["chunk_id"]: item for item in with_sparse_results}
    assert sparse_by_id["b"]["rerank_score"] >= baseline_by_id["b"]["rerank_score"]
