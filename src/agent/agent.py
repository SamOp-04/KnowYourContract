from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv() -> bool:  # type: ignore[no-redef]
        return False

try:
    from huggingface_hub import InferenceClient
except Exception:
    InferenceClient = None

from src.agent.prompts import ANSWER_SYSTEM_PROMPT, ROUTER_SYSTEM_PROMPT
from src.agent.tools import build_tools
from src.retrieval.hybrid_retriever import HybridRetriever

try:
    from langchain_community.chat_models import ChatOllama
except Exception:
    ChatOllama = None


load_dotenv()


JSON_BLOCK_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
QUESTION_PATTERN = re.compile(r"Question:\s*(.*)", re.IGNORECASE | re.DOTALL)
CHUNK_ID_PATTERN = re.compile(r"chunk_id=([^\s]+)")


@dataclass
class _LocalMessage:
    content: str


class RuleBasedLocalLLM:
    """Lightweight local fallback used when no cloud/local chat model is configured."""

    WEB_HINTS = {
        "market",
        "benchmark",
        "industry",
        "india",
        "statute",
        "regulation",
        "standard",
        "typical",
    }

    def invoke(self, messages: list[Any]) -> _LocalMessage:
        system_prompt = str(getattr(messages[0], "content", "")).lower() if messages else ""
        user_prompt = str(getattr(messages[-1], "content", "")) if messages else ""

        question_match = QUESTION_PATTERN.search(user_prompt)
        question = question_match.group(1).strip() if question_match else user_prompt.strip()

        if "routing agent" in system_prompt:
            lowered = question.lower()
            tool = "web_search" if any(hint in lowered for hint in self.WEB_HINTS) else "contract_search"
            reason = (
                "Question asks for external legal/market context." if tool == "web_search" else "Question is clause-focused and document-groundable."
            )
            return _LocalMessage(content=json.dumps({"tool": tool, "reason": reason}))

        context = ""
        if "Context:\n" in user_prompt:
            context = user_prompt.split("Context:\n", 1)[1].strip()

        if not context or "No supporting context retrieved." in context:
            return _LocalMessage(
                content=(
                    "I could not find enough supporting context in the indexed contract data to answer confidently. "
                    "Please upload a more relevant contract or broaden the query."
                )
            )

        chunk_ids = CHUNK_ID_PATTERN.findall(context)
        citation_text = ", ".join(chunk_ids[:3]) if chunk_ids else "retrieved chunks"

        context_lines = [line.strip() for line in context.splitlines() if line.strip() and not line.startswith("[")]
        excerpt = " ".join(context_lines[:2])[:500]
        answer = (
            "Based on the retrieved contract clauses, the relevant terms are found in "
            f"{citation_text}. Summary: {excerpt}"
        )
        return _LocalMessage(content=answer)


def _extract_message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)

    return str(content)


def _to_chat_messages(messages: list[Any]) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    for message in messages:
        message_type = str(getattr(message, "type", "")).lower()
        if message_type == "system":
            role = "system"
        elif message_type in {"ai", "assistant"}:
            role = "assistant"
        else:
            role = "user"

        converted.append({"role": role, "content": _extract_message_content(message)})

    return converted


class HuggingFaceRouterLLM:
    """HuggingFace Router chat client backed by HF API key."""

    def __init__(
        self,
        token: str,
        model: str,
        base_url: str = "https://router.huggingface.co/v1",
        temperature: float = 0.0,
        max_tokens: int = 900,
    ) -> None:
        if InferenceClient is None:
            raise RuntimeError("huggingface_hub is required for HuggingFace Router integration.")

        # huggingface_hub>=1.9 does not allow model and base_url together at init.
        if base_url:
            self.client = InferenceClient(base_url=base_url, api_key=token)
        else:
            self.client = InferenceClient(model=model, api_key=token)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def invoke(self, messages: list[Any]) -> _LocalMessage:
        payload = _to_chat_messages(messages)
        completion = self.client.chat_completion(
            messages=payload,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        text = ""
        if getattr(completion, "choices", None):
            message = completion.choices[0].message
            text = getattr(message, "content", "")
        return _LocalMessage(content=str(text or ""))


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
        hf_token = os.getenv("HF_TOKEN", "").strip()
        if hf_token:
            hf_model = model_name or os.getenv("HF_MODEL") or os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
            hf_base_url = os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1")
            try:
                return HuggingFaceRouterLLM(
                    token=hf_token,
                    model=hf_model,
                    base_url=hf_base_url,
                    temperature=temperature,
                )
            except Exception:
                pass

        use_ollama = os.getenv("USE_OLLAMA", "").strip().lower() in {"1", "true", "yes"}
        if ChatOllama is not None and use_ollama:
            return ChatOllama(model="mistral:7b-instruct", temperature=temperature)

        return RuleBasedLocalLLM()

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
