from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.pipeline.chunker import CUAD_CLAUSE_HINTS, extract_clause_hints_from_question
from src.pipeline.embedder import ContractVectorStore


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    score: float
    rerank_score: float
    hint_match_score: float
    retriever: str = "clause_aware_chroma"


class ClauseAwareRetriever:
    def __init__(
        self,
        vector_store: ContractVectorStore,
        default_k: int = 5,
        candidate_k: int = 24,
        clause_boost: float = 0.18,
    ) -> None:
        self.vector_store = vector_store
        self.default_k = default_k
        self.candidate_k = candidate_k
        self.clause_boost = clause_boost

    def get_top_k(
        self,
        query: str,
        contract_id: str | None = None,
        k: int | None = None,
        clause_hints: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        resolved_k = max(1, int(k or self.default_k))
        hints = clause_hints or extract_clause_hints_from_question(query)
        where_filter = {"contract_id": contract_id} if contract_id else None

        raw_results = self._similarity_search(query=query, k=max(resolved_k, self.candidate_k), where=where_filter)

        reranked: list[RetrievedChunk] = []
        for index, (document, raw_score) in enumerate(raw_results, start=1):
            metadata = dict(getattr(document, "metadata", {}) or {})
            text = str(getattr(document, "page_content", "") or "")
            chunk_id = str(metadata.get("chunk_id", f"retrieved_{index}"))
            clause_type = str(metadata.get("clause_type", ""))

            base_score = _normalize_similarity(raw_score)
            boost = self.clause_boost if hints and clause_type in hints else 0.0
            hint_match_score = _hint_match_score(text=text, metadata=metadata, hints=hints)
            rerank_score = max(0.0, min(1.0, base_score + boost + min(0.25, hint_match_score * 0.05)))

            reranked.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    text=text,
                    metadata=metadata,
                    score=round(base_score, 4),
                    rerank_score=round(rerank_score, 4),
                    hint_match_score=round(hint_match_score, 4),
                )
            )

        reranked.sort(key=lambda item: item.rerank_score, reverse=True)

        if hints:
            prioritized = _prioritize_for_clause_hints(reranked, hints)
            if prioritized:
                return [asdict(item) for item in prioritized[:resolved_k]]
            return []

        return [asdict(item) for item in reranked[:resolved_k]]

    def _similarity_search(
        self,
        query: str,
        k: int,
        where: dict[str, Any] | None,
    ) -> list[tuple[Any, float | None]]:
        store = self.vector_store.get_store()

        if hasattr(store, "similarity_search_with_score"):
            try:
                kwargs = {"query": query, "k": k}
                if where:
                    kwargs["filter"] = where
                return list(store.similarity_search_with_score(**kwargs))
            except Exception:
                pass

        if hasattr(store, "similarity_search_with_relevance_scores"):
            try:
                kwargs = {"query": query, "k": k}
                if where:
                    kwargs["filter"] = where
                return list(store.similarity_search_with_relevance_scores(**kwargs))
            except Exception:
                pass

        kwargs = {"query": query, "k": k}
        if where:
            kwargs["filter"] = where

        documents = list(store.similarity_search(**kwargs))
        return [(document, None) for document in documents]


def _normalize_similarity(raw_score: float | None) -> float:
    if raw_score is None:
        return 0.0

    value = float(raw_score)

    # Relevance-score APIs typically return [0, 1].
    if 0.0 <= value <= 1.0:
        return value

    # Some vector stores return cosine-like scores in [-1, 1].
    if -1.0 <= value < 0.0:
        return value + 1.0

    # Distance-like scores are mapped inversely to [0, 1].
    if value > 1.0:
        return 1.0 / (1.0 + value)

    return 0.0


def _prioritize_for_clause_hints(results: list[RetrievedChunk], hints: list[str]) -> list[RetrievedChunk]:
    hint_set = set(hints)
    direct = [item for item in results if str(item.metadata.get("clause_type", "")) in hint_set]
    if direct:
        direct.sort(key=lambda item: (item.hint_match_score, item.rerank_score), reverse=True)
        return direct

    lexical = [item for item in results if _chunk_matches_hints(item=item, hints=hints)]
    lexical.sort(key=lambda item: (item.hint_match_score, item.rerank_score), reverse=True)
    return lexical


def _chunk_matches_hints(item: RetrievedChunk, hints: list[str]) -> bool:
    haystack = f"{item.text}\n{item.metadata.get('section_heading', '')}".lower()

    for hint in hints:
        terms = set(CUAD_CLAUSE_HINTS.get(hint, []))
        terms.update(part for part in hint.split("_") if len(part) >= 4)
        if "termination" in hint:
            terms.update({"terminate", "termination", "terminating", "terminated"})

        for term in terms:
            candidate = term.strip().lower()
            if not candidate:
                continue
            if candidate in haystack:
                return True

    return False


def _hint_match_score(text: str, metadata: dict[str, Any], hints: list[str]) -> float:
    if not hints:
        return 0.0

    haystack = f"{text}\n{metadata.get('section_heading', '')}".lower()
    score = 0.0

    for hint in hints:
        terms = set(CUAD_CLAUSE_HINTS.get(hint, []))
        terms.update(part for part in hint.split("_") if len(part) >= 4)
        if "termination" in hint:
            terms.update({"terminate", "termination", "terminating", "terminated", "for convenience", "for default"})

        for term in terms:
            candidate = term.strip().lower()
            if not candidate:
                continue
            if candidate in haystack:
                score += max(0.5, len(candidate) / 10.0)

    return score
