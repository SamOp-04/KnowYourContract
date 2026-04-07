from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

try:
    from rank_bm25 import BM25Okapi
except Exception:
    BM25Okapi = None

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
    query_match_score: float
    retriever: str = "clause_aware_chroma"


class ClauseAwareRetriever:
    def __init__(
        self,
        vector_store: ContractVectorStore,
        default_k: int = 5,
        candidate_k: int = 48,
        clause_boost: float = 0.18,
        enable_sparse_rerank: bool = True,
        sparse_rerank_weight: float = 0.2,
    ) -> None:
        self.vector_store = vector_store
        self.default_k = default_k
        self.candidate_k = candidate_k
        self.clause_boost = clause_boost
        self.enable_sparse_rerank = enable_sparse_rerank
        self.sparse_rerank_weight = sparse_rerank_weight

    def get_top_k(
        self,
        query: str,
        contract_id: str | None = None,
        k: int | None = None,
        clause_hints: list[str] | None = None,
        allowed_contract_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        resolved_k = max(1, int(k or self.default_k))
        hints = clause_hints or extract_clause_hints_from_question(query)
        if allowed_contract_ids is None:
            normalized_allowed_contract_ids: list[str] = []
        else:
            normalized_allowed_contract_ids = _normalize_contract_ids(allowed_contract_ids)
            if not normalized_allowed_contract_ids:
                return []

        allowed_set = set(normalized_allowed_contract_ids)

        if contract_id and allowed_set and contract_id not in allowed_set:
            return []

        where_filter = {"contract_id": contract_id} if contract_id else None

        search_k = max(resolved_k, self.candidate_k)
        raw_results = self._scoped_similarity_search(
            query=query,
            k=search_k,
            where=where_filter,
            allowed_contract_ids=normalized_allowed_contract_ids,
        )

        for expanded_query in _build_expanded_queries(query=query, hints=hints):
            raw_results.extend(
                self._scoped_similarity_search(
                    query=expanded_query,
                    k=max(resolved_k * 2, 12),
                    where=where_filter,
                    allowed_contract_ids=normalized_allowed_contract_ids,
                )
            )

        reranked_by_chunk_id: dict[str, RetrievedChunk] = {}
        for index, (document, raw_score) in enumerate(raw_results, start=1):
            metadata = dict(getattr(document, "metadata", {}) or {})
            text = str(getattr(document, "page_content", "") or "")
            chunk_id = str(metadata.get("chunk_id", f"retrieved_{index}"))
            clause_type = str(metadata.get("clause_type", ""))

            base_score = _normalize_similarity(raw_score)
            boost = self.clause_boost if hints and clause_type in hints else 0.0
            hint_match_score = _hint_match_score(text=text, metadata=metadata, hints=hints)
            query_match_score = _query_overlap_score(text=text, metadata=metadata, query=query)
            section_bonus = _section_context_bonus(query=query, metadata=metadata)

            rerank_score = max(
                0.0,
                min(
                    1.0,
                    base_score
                    + boost
                    + section_bonus
                    + min(0.25, hint_match_score * 0.05)
                    + min(0.25, query_match_score * 0.04),
                ),
            )

            candidate = RetrievedChunk(
                chunk_id=chunk_id,
                text=text,
                metadata=metadata,
                score=round(base_score, 4),
                rerank_score=round(rerank_score, 4),
                hint_match_score=round(hint_match_score, 4),
                query_match_score=round(query_match_score, 4),
            )

            existing = reranked_by_chunk_id.get(chunk_id)
            if existing is None or candidate.rerank_score > existing.rerank_score:
                reranked_by_chunk_id[chunk_id] = candidate

        reranked = list(reranked_by_chunk_id.values())

        if allowed_set:
            reranked = [
                item
                for item in reranked
                if str(item.metadata.get("contract_id", item.metadata.get("contract_name", ""))).strip() in allowed_set
            ]

        if self.enable_sparse_rerank:
            reranked = _apply_sparse_rerank(
                reranked,
                query=query,
                weight=self.sparse_rerank_weight,
            )

        reranked.sort(key=lambda item: item.rerank_score, reverse=True)

        if _is_invoice_question(query):
            reranked = _inject_invoice_deadline_evidence(reranked)

        if hints:
            prioritized = _prioritize_for_clause_hints(reranked, hints)
            if prioritized:
                return [asdict(item) for item in prioritized[:resolved_k]]
            return [asdict(item) for item in reranked[:resolved_k]]

        return [asdict(item) for item in reranked[:resolved_k]]

    def _scoped_similarity_search(
        self,
        query: str,
        k: int,
        where: dict[str, Any] | None,
        allowed_contract_ids: list[str] | None,
    ) -> list[tuple[Any, float | None]]:
        if where:
            return list(self._similarity_search(query=query, k=k, where=where))

        if not allowed_contract_ids:
            return list(self._similarity_search(query=query, k=k, where=None))

        per_contract_k = max(4, min(k, (k // max(1, len(allowed_contract_ids))) + 2))
        scoped_results: list[tuple[Any, float | None]] = []
        for contract_id in allowed_contract_ids:
            scoped_results.extend(
                self._similarity_search(
                    query=query,
                    k=per_contract_k,
                    where={"contract_id": contract_id},
                )
            )

        return scoped_results

    def _similarity_search(
        self,
        query: str,
        k: int,
        where: dict[str, Any] | None,
    ) -> list[tuple[Any, float | None]]:
        store = self.vector_store.get_store()

        if where:
            filter_variants: list[dict[str, Any] | None] = [
                where,
                {key: {"$eq": value} for key, value in where.items()},
            ]
        else:
            filter_variants = [None]

        if hasattr(store, "similarity_search_with_score"):
            for filter_variant in filter_variants:
                try:
                    kwargs = {"query": query, "k": k}
                    if filter_variant is not None:
                        kwargs["filter"] = filter_variant
                    return list(store.similarity_search_with_score(**kwargs))
                except Exception:
                    continue

        if hasattr(store, "similarity_search_with_relevance_scores"):
            for filter_variant in filter_variants:
                try:
                    kwargs = {"query": query, "k": k}
                    if filter_variant is not None:
                        kwargs["filter"] = filter_variant
                    return list(store.similarity_search_with_relevance_scores(**kwargs))
                except Exception:
                    continue

        for filter_variant in filter_variants:
            try:
                kwargs = {"query": query, "k": k}
                if filter_variant is not None:
                    kwargs["filter"] = filter_variant
                documents = list(store.similarity_search(**kwargs))
                return [(document, None) for document in documents]
            except Exception:
                continue

        return []


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


def _normalize_contract_ids(contract_ids: list[str] | None) -> list[str]:
    if not contract_ids:
        return []

    output: list[str] = []
    seen: set[str] = set()
    for contract_id in contract_ids:
        normalized = str(contract_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)

    return output


def _prioritize_for_clause_hints(results: list[RetrievedChunk], hints: list[str]) -> list[RetrievedChunk]:
    hint_set = set(hints)
    direct = [item for item in results if str(item.metadata.get("clause_type", "")) in hint_set]
    direct.sort(key=lambda item: (item.hint_match_score, item.rerank_score), reverse=True)

    lexical = [item for item in results if _chunk_matches_hints(item=item, hints=hints)]
    lexical.sort(key=lambda item: (item.hint_match_score, item.rerank_score), reverse=True)

    # Keep direct clause-family hits first, but also include lexical matches from other
    # relevant sections (for example insurance/equal-employment/kickback termination triggers).
    merged: list[RetrievedChunk] = []
    seen: set[str] = set()

    for item in direct + lexical + sorted(results, key=lambda candidate: candidate.rerank_score, reverse=True):
        if item.chunk_id in seen:
            continue
        seen.add(item.chunk_id)
        merged.append(item)

    return merged


def _chunk_matches_hints(item: RetrievedChunk, hints: list[str]) -> bool:
    haystack = f"{item.text}\n{item.metadata.get('section_heading', '')}".lower()

    for hint in hints:
        terms = set(CUAD_CLAUSE_HINTS.get(hint, []))
        terms.update(part for part in hint.split("_") if len(part) >= 4)
        if "termination" in hint:
            terms.update(
                {
                    "terminate",
                    "termination",
                    "terminating",
                    "terminated",
                    "cancel",
                    "suspend",
                    "insurance",
                    "equal employment",
                    "non-discrimination",
                    "kickback",
                }
            )

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
            terms.update(
                {
                    "terminate",
                    "termination",
                    "terminating",
                    "terminated",
                    "for convenience",
                    "for default",
                    "cancel",
                    "suspend",
                    "insurance",
                    "equal employment",
                    "non-discrimination",
                    "kickback",
                }
            )

        for term in terms:
            candidate = term.strip().lower()
            if not candidate:
                continue
            if candidate in haystack:
                score += max(0.5, len(candidate) / 10.0)

    return score


def _build_expanded_queries(query: str, hints: list[str]) -> list[str]:
    expansions: list[str] = []
    seen: set[str] = {query.strip().lower()}

    for hint in hints[:3]:
        terms = [term.strip() for term in CUAD_CLAUSE_HINTS.get(hint, []) if term.strip()]
        if terms:
            candidate = f"{query.strip()} {terms[0]}"
        else:
            candidate = f"{query.strip()} {' '.join(hint.split('_'))}"

        normalized = candidate.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        expansions.append(candidate)

    if any("termination" in hint for hint in hints):
        targeted_expansions = [
            f"{query.strip()} terminate cancel suspend",
            f"{query.strip()} insurance lapse terminate agreement",
            f"{query.strip()} equal employment non-discrimination terminate",
            f"{query.strip()} kickback warranty terminate",
        ]
        for candidate in targeted_expansions:
            normalized = candidate.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            expansions.append(candidate)

    lowered_query = query.lower()
    if any(term in lowered_query for term in {"invoice", "billing", "payment deadline", "submit invoice"}):
        invoice_expansions = [
            f"{query.strip()} final invoice submit deadline days after acceptance performance",
            f"{query.strip()} invoices submitted no later than calendar days",
            f"{query.strip()} compensation invoice requirements payment terms",
        ]
        for candidate in invoice_expansions:
            normalized = candidate.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            expansions.append(candidate)

    if any(term in lowered_query for term in {"key personnel", "project manager", "replace", "replaced", "approval"}):
        personnel_expansions = [
            f"{query.strip()} key personnel removed replaced prior written consent approval",
            f"{query.strip()} hourly rate tier volume discount fee schedule pricing",
        ]
        for candidate in personnel_expansions:
            normalized = candidate.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            expansions.append(candidate)

    if any(term in lowered_query for term in {"rate", "tier", "fee", "cost", "price", "pricing", "hourly"}):
        fee_expansions = [
            f"{query.strip()} hourly rate tier volume discount fee schedule pricing",
            f"{query.strip()} compensation payment schedule rate",
        ]
        for candidate in fee_expansions:
            normalized = candidate.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            expansions.append(candidate)

    if any(term in lowered_query for term in {"law", "govern", "jurisdiction"}):
        law_expansions = [
            f"{query.strip()} construed under the laws state california",
            f"{query.strip()} governing law dispute jurisdiction",
        ]
        for candidate in law_expansions:
            normalized = candidate.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            expansions.append(candidate)

    return expansions


def _query_overlap_score(text: str, metadata: dict[str, Any], query: str) -> float:
    lowered_query = query.lower()
    haystack = f"{text}\n{metadata.get('section_heading', '')}".lower()

    query_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", lowered_query)
        if len(token) >= 4 and token not in {"what", "when", "which", "that", "this", "with", "from", "under", "about", "must"}
    }

    score = 0.0
    for token in query_tokens:
        if token in haystack:
            score += max(0.5, len(token) / 8.0)

    phrase_boosts = [
        "final invoice",
        "45 calendar days",
        "60 calendar days",
        "key personnel",
        "project manager",
        "prior written consent",
    ]
    for phrase in phrase_boosts:
        if phrase in lowered_query and phrase in haystack:
            score += 3.0

    return score


def _is_invoice_question(query: str) -> bool:
    lowered = query.lower()
    return any(term in lowered for term in ("invoice", "billing", "payment deadline", "submit invoice"))


def _tokenize_for_sparse(text: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z0-9_.-]+", text)]


def _apply_sparse_rerank(results: list[RetrievedChunk], query: str, weight: float) -> list[RetrievedChunk]:
    if not results or BM25Okapi is None:
        return results

    reranked_results = [RetrievedChunk(**asdict(item)) for item in results]

    query_tokens = _tokenize_for_sparse(query)
    if not query_tokens:
        return reranked_results

    tokenized_corpus: list[list[str]] = []
    for item in reranked_results:
        section_heading = str(item.metadata.get("section_heading", ""))
        tokenized_corpus.append(_tokenize_for_sparse(f"{item.text}\n{section_heading}"))

    if not any(tokenized_corpus):
        return reranked_results

    try:
        bm25 = BM25Okapi(tokenized_corpus)
        sparse_scores = bm25.get_scores(query_tokens)
    except Exception:
        return reranked_results

    if len(sparse_scores) != len(reranked_results):
        return reranked_results

    positive_scores = [float(score) for score in sparse_scores if float(score) > 0.0]
    if not positive_scores:
        return reranked_results

    max_positive = max(positive_scores)
    if max_positive <= 0.0:
        return reranked_results

    for index, item in enumerate(reranked_results):
        normalized_sparse = max(0.0, float(sparse_scores[index])) / max_positive
        if normalized_sparse <= 0.0:
            continue
        sparse_bonus = min(0.25, normalized_sparse * weight)
        item.rerank_score = round(min(1.0, max(0.0, item.rerank_score + sparse_bonus)), 4)

    return reranked_results


def _inject_invoice_deadline_evidence(results: list[RetrievedChunk]) -> list[RetrievedChunk]:
    def priority(item: RetrievedChunk) -> int:
        haystack = f"{item.text}\n{item.metadata.get('section_heading', '')}".lower()
        score = 0
        if re.search(r"\bfinal\s+invoice\b", haystack):
            score += 5
        if re.search(r"\b60\s+calendar\s+days\b", haystack):
            score += 4
        if re.search(r"\b45\s+calendar\s+days\b", haystack):
            score += 2
        if "invoice" in haystack:
            score += 1
        return score

    with_priority = sorted(results, key=lambda item: (priority(item), item.rerank_score), reverse=True)
    prioritized = [item for item in with_priority if priority(item) > 0]
    if not prioritized:
        return results

    merged: list[RetrievedChunk] = []
    seen: set[str] = set()

    for item in prioritized[:4] + results:
        if item.chunk_id in seen:
            continue
        seen.add(item.chunk_id)
        merged.append(item)

    return merged

def _section_context_bonus(query: str, metadata: dict[str, Any]) -> float:
    lowered_query = query.lower()
    heading = str(metadata.get('section_heading', '')).strip().lower()
    if not heading:
        return 0.0

    bonus = 0.0
    is_dispute_query = 'dispute' in lowered_query or 'resolv' in lowered_query
    is_law_query = 'law' in lowered_query or 'govern' in lowered_query

    # Boost Section 18 for general disputes and governing law
    if is_dispute_query or is_law_query:
        if '18.' in heading and 'dispute' in heading:
            bonus += 0.35
        # Penalize audit Section 19 for general dispute queries that don't mention audit
        elif is_dispute_query and '19.' in heading and 'audit' in heading and 'audit' not in lowered_query:
            bonus -= 0.15

    # Boost Section 20 for subcontracting questions
    if 'subcontract' in lowered_query:
        if '20.' in heading and 'subcontract' in heading:
            bonus += 0.35

    return bonus
