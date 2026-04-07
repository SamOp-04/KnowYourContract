from __future__ import annotations

import json
import os
from typing import Any

try:
    from langchain.tools import StructuredTool
except Exception:
    class StructuredTool:  # type: ignore[no-redef]
        def __init__(self, name: str, description: str, func):
            self.name = name
            self.description = description
            self._func = func

        def invoke(self, args):
            if isinstance(args, dict):
                return self._func(**args)
            return self._func(args)

        @classmethod
        def from_function(cls, name: str, description: str, func):
            return cls(name=name, description=description, func=func)

try:
    from langchain_community.tools.tavily_search import TavilySearchResults
except Exception:
    TavilySearchResults = None

def _coerce_results(raw_results: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_results, list):
        return []

    output: list[dict[str, Any]] = []
    for item in raw_results:
        if isinstance(item, dict):
            output.append(item)
            continue

        metadata = dict(getattr(item, "metadata", {}) or {})
        output.append(
            {
                "chunk_id": str(getattr(item, "chunk_id", metadata.get("chunk_id", ""))),
                "text": str(getattr(item, "text", getattr(item, "page_content", ""))),
                "metadata": metadata,
            }
        )

    return output


def _retrieve_contract_chunks(
    retriever: Any,
    query: str,
    contract_id: str | None,
    k: int,
) -> list[dict[str, Any]]:
    attempts = [
        {"query": query, "contract_id": contract_id, "k": k, "clause_hints": []},
        {"query": query, "contract_id": contract_id, "k": k},
        {"query": query, "k": k, "dense_k": max(12, k * 4), "sparse_k": max(12, k * 4)},
        {"query": query, "k": k},
    ]

    for kwargs in attempts:
        try:
            raw_results = retriever.get_top_k(**kwargs)
        except TypeError:
            continue
        return _coerce_results(raw_results)

    raise RuntimeError("Retriever does not expose a compatible get_top_k signature.")


def build_contract_search_tool(retriever: Any) -> StructuredTool:
    def contract_search(query: str, contract_id: str | None = None) -> str:
        results = _retrieve_contract_chunks(
            retriever=retriever,
            query=query,
            contract_id=contract_id,
            k=5,
        )

        if contract_id:
            normalized_contract_id = str(contract_id).strip().lower()
            filtered = []
            for item in results:
                metadata = item.get("metadata", {})
                metadata_contract_id = str(metadata.get("contract_id", "")).strip().lower()
                contract_name = str(metadata.get("contract_name", "")).strip().lower()
                resolved_chunk_contract_id = metadata_contract_id or contract_name
                if resolved_chunk_contract_id == normalized_contract_id:
                    filtered.append(item)
            results = filtered

        return json.dumps(
            {
                "tool": "contract_search",
                "results": results,
            }
        )

    return StructuredTool.from_function(
        name="contract_search",
        description=(
            "Search legal contract chunks with clause-aware Chroma retrieval and optional BM25 reranking, "
            "and return top passages. "
            "Use this for questions about clause text, obligations, limits, termination terms, and definitions."
        ),
        func=contract_search,
    )


def build_web_search_tool(max_results: int = 5) -> StructuredTool:
    def web_search(query: str) -> str:
        if not os.getenv("TAVILY_API_KEY"):
            return json.dumps({"tool": "web_search", "results": [], "warning": "TAVILY_API_KEY is not configured."})

        if TavilySearchResults is None:
            return json.dumps({"tool": "web_search", "results": [], "warning": "Tavily client is unavailable because langchain-community is not installed."})

        try:
            tavily_client = TavilySearchResults(max_results=max_results)
            raw_results: Any = tavily_client.invoke(query)
        except Exception as error:
            return json.dumps({"tool": "web_search", "results": [], "error": str(error)})

        if not isinstance(raw_results, list):
            raw_results = [raw_results]

        simplified = []
        for item in raw_results:
            if isinstance(item, dict):
                simplified.append({"title": item.get("title", ""), "url": item.get("url", ""), "content": item.get("content", item.get("snippet", ""))})
            else:
                simplified.append({"title": "", "url": "", "content": str(item)})

        return json.dumps({"tool": "web_search", "results": simplified})

    return StructuredTool.from_function(
        name="web_search",
        description=(
            "Search the web for legal benchmarks, regulations, and market standards when contract content is missing."
        ),
        func=web_search,
    )


def build_tools(retriever: Any) -> list[StructuredTool]:
    return [
        build_contract_search_tool(retriever=retriever),
        build_web_search_tool(),
    ]
