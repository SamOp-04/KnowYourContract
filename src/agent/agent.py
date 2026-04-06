from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

try:
    from langchain_openai import ChatOpenAI
except Exception:
    ChatOpenAI = None

from src.agent.prompts import ANSWER_SYSTEM_PROMPT, ROUTER_SYSTEM_PROMPT
from src.agent.tools import build_tools
from src.retrieval.hybrid_retriever import HybridRetriever

try:
    from langchain_community.chat_models import ChatOllama
except Exception:
    ChatOllama = None


JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def _safe_json_parse(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = JSON_BLOCK_PATTERN.search(raw_text)
    if not match:
        return {}

    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return {}

    return {}


class LegalContractAgent:
    """LangChain-based routing agent with contract search and web fallback tools."""

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        llm: Any | None = None,
        model_name: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.hybrid_retriever = hybrid_retriever
        self.llm = llm or self._build_default_llm(model_name=model_name, temperature=temperature)
        self.tools = build_tools(hybrid_retriever=hybrid_retriever)
        self.tools_by_name = {tool.name: tool for tool in self.tools}

    def _build_default_llm(self, model_name: str | None, temperature: float) -> Any:
        configured_model = model_name or os.getenv("LLM_MODEL", "gpt-4o-mini")
        if ChatOpenAI is not None and os.getenv("OPENAI_API_KEY"):
            return ChatOpenAI(model=configured_model, temperature=temperature)

        if ChatOllama is not None:
            return ChatOllama(model="mistral:7b-instruct", temperature=temperature)

        raise RuntimeError("No LLM provider configured. Set OPENAI_API_KEY or install and run Ollama.")

    def route_query(self, query: str) -> dict[str, str]:
        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=f"Question: {query}"),
        ]
        response = self.llm.invoke(messages)
        content = getattr(response, "content", str(response))
        payload = _safe_json_parse(content)

        tool = str(payload.get("tool", "contract_search"))
        if tool not in self.tools_by_name:
            tool = "contract_search"

        reason = str(payload.get("reason", "Defaulted to contract search for in-document grounding."))
        return {"tool": tool, "reason": reason}

    def _invoke_tool(self, tool_name: str, query: str, contract_id: str | None = None) -> dict[str, Any]:
        tool = self.tools_by_name[tool_name]
        if tool_name == "contract_search":
            raw_output = tool.invoke({"query": query, "contract_id": contract_id})
        else:
            raw_output = tool.invoke({"query": query})

        if isinstance(raw_output, str):
            return _safe_json_parse(raw_output)

        if isinstance(raw_output, dict):
            return raw_output

        return {"tool": tool_name, "results": [{"content": str(raw_output)}]}

    def _render_context(self, tool_payload: dict[str, Any]) -> str:
        results = tool_payload.get("results", [])
        if not isinstance(results, list) or not results:
            return "No supporting context retrieved."

        lines = []
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                lines.append(f"[{index}] {item}")
                continue

            chunk_id = item.get("chunk_id") or item.get("metadata", {}).get("chunk_id") or "unknown_chunk"
            contract_name = item.get("metadata", {}).get("contract_name", "external")
            text = item.get("text") or item.get("content") or ""
            url = item.get("url", "")

            prefix = f"[{index}] chunk_id={chunk_id} contract={contract_name}"
            if url:
                prefix += f" url={url}"
            lines.append(f"{prefix}\n{text}")

        return "\n\n".join(lines)

    def _collect_citations(self, tool_payload: dict[str, Any]) -> list[dict[str, Any]]:
        citations = []
        for item in tool_payload.get("results", []):
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata", {})
            citations.append(
                {
                    "chunk_id": item.get("chunk_id", metadata.get("chunk_id", "")),
                    "contract_name": metadata.get("contract_name", ""),
                    "clause_type": metadata.get("clause_type", ""),
                    "page_number": metadata.get("page_number"),
                    "url": item.get("url", ""),
                }
            )
        return citations

    def generate_answer(self, query: str, tool_payload: dict[str, Any]) -> str:
        context = self._render_context(tool_payload)
        messages = [
            SystemMessage(content=ANSWER_SYSTEM_PROMPT),
            HumanMessage(content=f"Question: {query}\n\nContext:\n{context}"),
        ]
        response = self.llm.invoke(messages)
        return str(getattr(response, "content", response)).strip()

    def run(self, query: str, contract_id: str | None = None) -> dict[str, Any]:
        route = self.route_query(query)
        selected_tool = route["tool"]
        route_reason = route["reason"]

        tool_payload = self._invoke_tool(tool_name=selected_tool, query=query, contract_id=contract_id)

        used_web_fallback = False
        if selected_tool == "contract_search" and not tool_payload.get("results"):
            tool_payload = self._invoke_tool(tool_name="web_search", query=query)
            selected_tool = "web_search"
            used_web_fallback = True
            route_reason = f"{route_reason} Contract retrieval had no context; used web fallback."

        answer = self.generate_answer(query=query, tool_payload=tool_payload)

        return {
            "answer": answer,
            "tool_used": selected_tool,
            "route_reason": route_reason,
            "used_web_fallback": used_web_fallback,
            "source_chunks": tool_payload.get("results", []),
            "citations": self._collect_citations(tool_payload),
        }

    def invoke(self, query: str, contract_id: str | None = None) -> dict[str, Any]:
        return self.run(query=query, contract_id=contract_id)
