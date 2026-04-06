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

from src.retrieval.hybrid_retriever import HybridRetriever


def build_contract_search_tool(hybrid_retriever: HybridRetriever) -> StructuredTool:
    def contract_search(query: str, contract_id: str | None = None) -> str:
        results = hybrid_retriever.get_top_k(query=query, k=5, dense_k=20, sparse_k=20)

        if contract_id:
            filtered = []
            for item in results:
                contract_name = str(item.get("metadata", {}).get("contract_name", "")).lower()
                if contract_name == contract_id.lower():
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
            "Search legal contract chunks with hybrid BM25 + dense retrieval and return top passages. "
            "Use this for questions about clause text, obligations, limits, termination terms, and definitions."
        ),
        func=contract_search,
    )


def build_web_search_tool(max_results: int = 5) -> StructuredTool:
    def web_search(query: str) -> str:
        if not os.getenv("TAVILY_API_KEY"):
            return json.dumps(
                {
                    "tool": "web_search",
                    "results": [],
                    "warning": "TAVILY_API_KEY is not configured.",
                }
            )

        if tavily_client is None:
            return json.dumps(
                {
                    "tool": "web_search",
                    "results": [],
                    "warning": "Tavily client is unavailable because langchain-community is not installed.",
                }
            )

        try:
            tavily_client = TavilySearchResults(max_results=max_results)
        except Exception as error:
            return json.dumps(
                {
                    "tool": "web_search",
                    "results": [],
                    "warning": f"Tavily client could not be initialized: {error}",
                }
            )

        try:
            raw_results: Any = tavily_client.invoke(query)
        except Exception as error:
            return json.dumps(
                {
                    "tool": "web_search",
                    "results": [],
                    "error": str(error),
                }
            )

        if not isinstance(raw_results, list):
            raw_results = [raw_results]

        simplified = []
        for item in raw_results:
            if isinstance(item, dict):
                simplified.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "content": item.get("content", item.get("snippet", "")),
                    }
                )
            else:
                simplified.append({"title": "", "url": "", "content": str(item)})

        return json.dumps(
            {
                "tool": "web_search",
                "results": simplified,
            }
        )

    return StructuredTool.from_function(
        name="web_search",
        description=(
            "Search the web for legal benchmarks, regulations, and market standards when contract content is missing."
        ),
        func=web_search,
    )


def build_tools(hybrid_retriever: HybridRetriever) -> list[StructuredTool]:
    return [
        build_contract_search_tool(hybrid_retriever=hybrid_retriever),
        build_web_search_tool(),
    ]
