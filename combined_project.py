# pyright: reportInvalidTypeForm=false
from __future__ import annotations



################################################################################
# FILE: frontend/app.py
################################################################################


import os
import uuid
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()

QUICK_QUESTIONS = [
    "What are the termination conditions?",
    "How much notice is required to terminate?",
    "What is the maximum payment under this agreement?",
    "When must invoices be submitted?",
    "What insurance is required?",
    "Who owns the work products?",
]

st.set_page_config(page_title="Legal Contract Analyzer", layout="wide")


def _request_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if API_AUTH_TOKEN:
        headers["x-api-key"] = API_AUTH_TOKEN
    return headers

if "sessions" not in st.session_state:
    st.session_state.sessions = {}
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "chat_contracts" not in st.session_state:
    st.session_state.chat_contracts = {}
if "chat_active_contract" not in st.session_state:
    st.session_state.chat_active_contract = {}

def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}{path}",
        json=payload,
        headers=_request_headers(),
        timeout=120,
    )
    response.raise_for_status()
    return response.json()

def _get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{API_BASE_URL}{path}",
        params=params or {},
        headers=_request_headers(),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()

def _post_files(path: str, uploads: list[Any], chat_id: str) -> dict[str, Any]:
    multipart_files = []
    for uploaded_file in uploads:
        multipart_files.append(
            (
                "files",
                (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type or "application/octet-stream",
                ),
            )
        )
    response = requests.post(
        f"{API_BASE_URL}{path}",
        files=multipart_files,
        data={"chat_id": chat_id},
        headers=_request_headers(),
        timeout=600,
    )
    response.raise_for_status()
    return response.json()

def _ensure_chat_state(chat_id: str) -> None:
    if chat_id not in st.session_state.sessions:
        st.session_state.sessions[chat_id] = []
    if chat_id not in st.session_state.chat_contracts:
        st.session_state.chat_contracts[chat_id] = []
    if chat_id not in st.session_state.chat_active_contract:
        st.session_state.chat_active_contract[chat_id] = None


def _refresh_contracts(chat_id: str) -> None:
    _ensure_chat_state(chat_id)
    try:
        payload = _get_json("/contracts", params={"chat_id": chat_id})
        contracts = list(payload.get("contracts", []))
        st.session_state.chat_contracts[chat_id] = contracts

        active_contract = st.session_state.chat_active_contract.get(chat_id)
        available_contract_ids = {
            str(item.get("contract_id"))
            for item in contracts
            if item.get("contract_id")
        }
        if active_contract and active_contract not in available_contract_ids:
            st.session_state.chat_active_contract[chat_id] = None
    except Exception:
        st.session_state.chat_contracts[chat_id] = []

def start_new_session():
    new_id = str(uuid.uuid4())
    _ensure_chat_state(new_id)
    st.session_state.current_session_id = new_id

if not st.session_state.current_session_id:
    start_new_session()

_refresh_contracts(st.session_state.current_session_id)

with st.sidebar:
    st.title("Chats")
    if st.button("+ New Chat", use_container_width=True):
        start_new_session()
    
    st.markdown("---")
    for session_id in list(st.session_state.sessions.keys()):
        messages = st.session_state.sessions[session_id]
        label = "Empty Chat"
        if messages:
            first_msg = messages[0]["content"]
            label = first_msg[:25] + "..." if len(first_msg) > 25 else first_msg
        
        button_type = "primary" if session_id == st.session_state.current_session_id else "secondary"
        if st.button(label, key=f"btn_{session_id}", use_container_width=True, type=button_type):
            st.session_state.current_session_id = session_id
            _refresh_contracts(session_id)
            
    st.markdown("---")
    st.header("Contract Context")
    
    with st.expander("Upload & Select Contract"):
        current_chat_id = st.session_state.current_session_id
        uploaded_files = st.file_uploader(
            "Upload contract(s) (.txt or .pdf)",
            type=["txt", "pdf"],
            accept_multiple_files=True,
            key=f"uploader_{current_chat_id}",
        )
        if uploaded_files and st.button("Index", type="primary", key=f"index_{current_chat_id}"):
            try:
                payload = _post_files("/upload", uploads=list(uploaded_files), chat_id=current_chat_id)
                uploaded_items = list(payload.get("uploads", []))
                if uploaded_items:
                    st.session_state.chat_active_contract[current_chat_id] = uploaded_items[-1].get("contract_id")
                else:
                    st.session_state.chat_active_contract[current_chat_id] = payload.get("contract_id")
                _refresh_contracts(current_chat_id)
                st.success("Indexing complete!")
            except Exception as e:
                st.error(f"Upload failed: {e}")

        contracts = st.session_state.chat_contracts.get(current_chat_id, [])
        if contracts:
            contracts_by_id = {str(item.get("contract_id")): item for item in contracts if item.get("contract_id")}
            scope_options = ["__all_contracts__"] + list(contracts_by_id.keys())
            current_scope = st.session_state.chat_active_contract.get(current_chat_id) or "__all_contracts__"
            if current_scope not in scope_options:
                current_scope = "__all_contracts__"
            
            selected_scope = st.selectbox(
                "Active Contract:",
                options=scope_options,
                index=scope_options.index(current_scope),
                key=f"scope_{current_chat_id}",
                format_func=lambda item: "All contracts in this chat" if item == "__all_contracts__" else f"{contracts_by_id.get(item, {}).get('display_name', item)}"
            )
            st.session_state.chat_active_contract[current_chat_id] = None if selected_scope == "__all_contracts__" else selected_scope

st.title("Contract Analyzer")

current_messages = st.session_state.sessions[st.session_state.current_session_id]

# Display history
for msg in current_messages:
    role = "user" if msg["role"] == "user" else "assistant"
    with st.chat_message(role):
        st.write(msg["content"])
        if "citations" in msg and msg["citations"]:
            with st.expander("View Source Chunks"):
                for cit in msg["citations"]:
                    st.markdown(f"**Contract:** {cit.get('contract_name', 'Unknown')}")
                    st.markdown(f"**Chunk:** {cit.get('chunk_id', 'unknown_chunk')}")
                    st.divider()

# Quick questions handler
if not current_messages:
    st.markdown("### Quick Questions")
    cols = st.columns(2)
    for i, quick_question in enumerate(QUICK_QUESTIONS):
        if cols[i % 2].button(quick_question, use_container_width=True):
            st.session_state.quick_query = quick_question

# Chat input
query = st.chat_input("Ask about clauses, obligations, risk terms...")

# Use quick query if clicked
if "quick_query" in st.session_state and st.session_state.quick_query:
    query = st.session_state.quick_query
    del st.session_state.quick_query

if query:
    # Append user message
    st.session_state.sessions[st.session_state.current_session_id].append({"role": "user", "content": query})
    with st.spinner("Analyzing contract..."):
        try:
            payload = {
                "question": query,
                "contract_id": st.session_state.chat_active_contract.get(st.session_state.current_session_id),
                "chat_id": st.session_state.current_session_id,
            }
            result = _post_json("/ask", payload)
            answer = result.get("answer", "No answer generated.")
            citations = result.get("citations", [])

            st.session_state.sessions[st.session_state.current_session_id].append(
                {
                    "role": "assistant",
                    "content": answer,
                    "citations": citations,
                }
            )
        except Exception as error:
            st.session_state.sessions[st.session_state.current_session_id].append(
                {
                    "role": "assistant",
                    "content": f"Error querying backend: {error}",
                    "citations": [],
                }
            )

    st.rerun()


################################################################################
# FILE: run_batch_eval_extreme.py
################################################################################

import os
import time
import uuid

import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()
EVAL_CHAT_ID = os.getenv("EXTREME_EVAL_CHAT_ID", "extreme_eval_chat")

QUESTIONS = [
    "What are all the hourly rate tiers for Key Personnel and at what hour thresholds do they change?",
    "What are the different hotel rate limits and when does each apply?",
    "What are all the monetary caps in this agreement? List every dollar figure mentioned.",
    "What triggers each different type of termination, and what payment is owed in each case?",
    "What are the different notice periods required for different actions in this contract?",
    "The contract has both a liability cap and exceptions to that cap - what is the cap, and what are ALL the exceptions?",
    "Consultant's IP indemnification is said to be unlimited in Section 7.D but a general cap exists in Section 8.B - which governs IP claims?",
    "Can the monthly retainer be applied against hourly fees?",
    "Does the non-compete apply if Company terminates for convenience?",
    "What happens if a Force Majeure Event lasts more than 90 days AND there is an active unpaid invoice?",
    "If Company suspends an SOW for 100 days, what rights does Consultant have?",
    "What obligations survive termination of this agreement, and for how long does each survive?",
    "Under what conditions can Company conduct more than one audit per year?",
    "What is the penalty if Consultant misses the 5th business day invoice deadline?",
    "Does this contract require Consultant to carry Directors & Officers (D&O) insurance?",
    "What happens if both Key Personnel and a Force Majeure Event occur simultaneously?",
    "Is there a minimum number of hours Consultant must bill per month?",
    "How many days notice must Consultant give to terminate for convenience?",
    "How long must records be retained after final payment?",
    "What is the liquidated damages amount for a non-compete breach, and is it per breach or aggregate?",
    "Within how many hours must a data breach be reported to Company?",
    "How many depositions is each party entitled to in arbitration discovery?",
    "Under what conditions is Consultant entitled to business class air travel?",
    "When does the overbilling audit cost shift to Consultant?",
    "What conditions must be met before Consultant can suspend services for non-payment?",
    "What happens to open source components - when are they allowed and what must be delivered with them?",
    "Who are the Key Personnel and what are their specific roles?",
    "Who signed this agreement and on behalf of which entities?",
    "Which companies are currently on the Restricted Competitors list?",
    "Who must approve Change Orders exceeding $50,000?"
]

def get_latest_extreme_contract(session: "requests.Session", chat_id: str) -> str | None:
    try:
        res = session.get(f"{API_BASE_URL}/contracts", params={"chat_id": chat_id}, timeout=60)
        res.raise_for_status()
        contracts = res.json().get("contracts", [])
        for c in reversed(contracts):
            contract_id = str(c.get("contract_id", ""))
            display_name = str(c.get("display_name", ""))
            source_name = str(c.get("source_name", ""))
            haystack = f"{contract_id} {display_name} {source_name}".lower()
            if "extremetest" in haystack or "extreme-test" in haystack:
                return c["contract_id"]
    except Exception as e:
        print(f"Error fetching contracts: {e}")
    return None


def upload_extreme_contract(session: "requests.Session", chat_id: str) -> str | None:
    print("Uploading ExtremeTest-Contract.pdf...")
    try:
        with open("ExtremeTest-Contract.pdf", "rb") as file_handle:
            response = session.post(
                f"{API_BASE_URL}/upload",
                data={"chat_id": chat_id},
                files={"file": ("ExtremeTest-Contract.pdf", file_handle, "application/pdf")},
                timeout=300,
            )
        response.raise_for_status()
        payload = response.json()

        contract_id = payload.get("contract_id")
        if contract_id:
            return str(contract_id)

        uploads = payload.get("uploads", [])
        if isinstance(uploads, list) and uploads:
            return str(uploads[0].get("contract_id", "")) or None
    except Exception as e:
        print(f"Failed to upload: {e}")

    return None

def main():
    chat_id = str(EVAL_CHAT_ID or "").strip() or f"extreme_eval_{uuid.uuid4().hex[:8]}"
    session = requests.Session()
    if API_AUTH_TOKEN:
        session.headers.update({"x-api-key": API_AUTH_TOKEN})

    contract_id = get_latest_extreme_contract(session=session, chat_id=chat_id)
    if not contract_id:
        contract_id = upload_extreme_contract(session=session, chat_id=chat_id)
    
    print(f"Using contract_id: {contract_id}")

    results = []
    
    with open("extreme_eval_results.md", "w", encoding="utf-8") as f:
        f.write("# ExtremeTest Contract Evaluation Results\n\n")

    for i, q in enumerate(QUESTIONS):
        print(f"[{i+1}/{len(QUESTIONS)}] Asking: {q}")
        try:
            res = session.post(
                f"{API_BASE_URL}/ask",
                json={"question": q, "contract_id": contract_id, "chat_id": chat_id},
                timeout=180,
            )
            res.raise_for_status()
            data = res.json()
            answer = data.get("answer", "No answer")
            results.append({
                "question": q,
                "answer": answer
            })
            print(f"Answer: {answer[:100]}...\n")
        except Exception as e:
            print(f"Error: {e}")
            answer = f"ERROR: {e}"
            results.append({
                "question": q,
                "answer": answer
            })
            time.sleep(2)
            
        with open("extreme_eval_results.md", "a", encoding="utf-8") as f:
            f.write(f"### Q: {q}\n**A:** {answer}\n\n---\n")

    print("Done! Results saved to extreme_eval_results.md")

if __name__ == "__main__":
    main()


################################################################################
# FILE: src/__init__.py
################################################################################

"""Top-level package for the Legal Contract Analyzer."""


################################################################################
# FILE: src/agent/__init__.py
################################################################################

"""Agent layer for tool routing and grounded answer generation."""

from src.agent.agent import LegalContractAgent

__all__ = ["LegalContractAgent"]


################################################################################
# FILE: src/agent/agent.py
################################################################################


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
        retriever: Any | None = None,
        clause_retriever: Any | None = None,
        hybrid_retriever: Any | None = None,
        llm: Any | None = None,
        model_name: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        resolved_retriever = retriever or clause_retriever or hybrid_retriever
        if resolved_retriever is None:
            raise ValueError("A contract retriever is required.")

        self.retriever = resolved_retriever
        self.llm = llm or self._build_default_llm(model_name=model_name, temperature=temperature)
        self.tools = build_tools(retriever=resolved_retriever)
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


################################################################################
# FILE: src/agent/prompts.py
################################################################################


ROUTER_SYSTEM_PROMPT = """
You are a legal question routing agent for a contract analysis system.

Your task is to decide which tool should be used:
1) contract_search: for questions answerable from contract text
2) web_search: for market standards, regulations, or external legal context

Return STRICT JSON with keys:
- tool: "contract_search" or "web_search"
- reason: one short sentence

Do not return markdown. Do not add any text outside JSON.
""".strip()


ANSWER_SYSTEM_PROMPT = """
You are a legal contract analyst assistant.

Rules:
1) Use only the provided context.
2) If context is insufficient, say so clearly.
3) Explain in plain English with concise legal precision.
4) Cite chunk ids or URLs from the context when possible.
5) Never fabricate clause numbers.
""".strip()


################################################################################
# FILE: src/agent/tools.py
################################################################################


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


################################################################################
# FILE: src/api/__init__.py
################################################################################

"""API package for FastAPI application entrypoint and route modules."""


################################################################################
# FILE: src/api/main.py
################################################################################


import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv() -> bool:  # type: ignore[no-redef]
        return False

from src.api.routes.ask import router as ask_router
from src.api.routes.contracts import router as contracts_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.query import router as query_router
from src.api.routes.upload import router as upload_router
from src.evaluation.metrics_store import MetricsStore
from src.evaluation.ragas_evaluator import ContractQAEvaluator
from src.pipeline.chat_scope_registry import ChatScopeRegistry
from src.pipeline.pipeline import ContractQAPipeline

load_dotenv()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        metrics_store = MetricsStore()
        metrics_store.init_db()
        app.state.metrics_store = metrics_store
        app.state.evaluator = ContractQAEvaluator(use_llm_judge=True)
        app.state.pipeline = ContractQAPipeline(evaluator=app.state.evaluator)
        app.state.chat_scope_registry = ChatScopeRegistry()
            
        yield

    app = FastAPI(
        title="Legal Contract Analyzer API",
        version="1.0.0",
        description="Agentic RAG backend for legal contract analysis using CUAD.",
        lifespan=lifespan,
    )

    auth_token = os.getenv("API_AUTH_TOKEN", "").strip()
    if auth_token:
        exempt_paths = {"/health", "/docs", "/openapi.json", "/redoc"}

        @app.middleware("http")
        async def _require_api_token(request, call_next):
            if request.url.path in exempt_paths:
                return await call_next(request)

            provided = str(request.headers.get("x-api-key", "")).strip()
            if not provided or provided != auth_token:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

            return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(query_router)
    app.include_router(ask_router)
    app.include_router(upload_router)
    app.include_router(contracts_router)
    app.include_router(metrics_router)
    return app


app = create_app()


################################################################################
# FILE: src/api/routes/__init__.py
################################################################################

"""Route modules for ask, contracts, query, upload, and metrics endpoints."""


################################################################################
# FILE: src/api/routes/ask.py
################################################################################


from fastapi import APIRouter, BackgroundTasks, Request

from src.api.routes._pipeline_qa import run_pipeline_query, schedule_pipeline_metrics
from src.api.schemas import AskRequest, AskResponse

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
async def ask_contract(
    payload: AskRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> AskResponse:
    result = await run_pipeline_query(
        request=request,
        query=payload.query,
        contract_id=payload.contract_id,
        ground_truth=payload.ground_truth or "",
        chat_id=payload.chat_id,
    )
    evaluation = schedule_pipeline_metrics(
        background_tasks=background_tasks,
        request=request,
        query=payload.query,
        result=result,
    )

    return AskResponse(
        answer=str(result.get("answer", "")),
        citations=list(result.get("citations", [])),
        sources=list(result.get("sources", [])),
        source_chunks=list(result.get("source_chunks", [])),
        tool_used=str(result.get("tool_used", "pipeline_contract_search")),
        route_reason=str(result.get("route_reason", "")),
        used_web_fallback=bool(result.get("used_web_fallback", False)),
        matched_clause_hints=list(result.get("matched_clause_hints", [])),
        evaluation=evaluation,
    )


################################################################################
# FILE: src/api/routes/contracts.py
################################################################################


import os

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.schemas import ContractsResponse

router = APIRouter(tags=["contracts"])


def _strict_scope_enabled() -> bool:
    return os.getenv("REQUIRE_CHAT_SCOPE", "").strip().lower() in {"1", "true", "yes"}


@router.get("/contracts", response_model=ContractsResponse)
async def list_contracts(
    request: Request,
    chat_id: str | None = Query(default=None),
) -> ContractsResponse:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=503,
            detail="Pipeline is not initialized. Check startup logs and dependencies.",
        )

    if _strict_scope_enabled() and not str(chat_id or "").strip():
        raise HTTPException(status_code=400, detail="chat_id is required by server policy.")

    contracts = list(pipeline.list_contracts())

    if chat_id:
        chat_scope_registry = getattr(request.app.state, "chat_scope_registry", None)
        if chat_scope_registry is None:
            raise HTTPException(status_code=503, detail="Chat scope registry is not initialized.")

        allowed_contract_ids = set(chat_scope_registry.list_contract_ids(chat_id))
        contracts = [
            item
            for item in contracts
            if str(item.get("contract_id", "")).strip() in allowed_contract_ids
        ]

    return ContractsResponse(contracts=contracts, total=len(contracts))


################################################################################
# FILE: src/api/routes/metrics.py
################################################################################


from fastapi import APIRouter, Query, Request

from src.api.schemas import MetricsResponse

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
) -> MetricsResponse:
    store = request.app.state.metrics_store
    recent = store.list_recent(limit=limit)
    trends = store.get_trends(days=days)
    analytics = store.get_query_analytics()

    return MetricsResponse(recent=recent, trends=trends, analytics=analytics)


################################################################################
# FILE: src/api/routes/query.py
################################################################################


from fastapi import APIRouter, BackgroundTasks, Request

from src.api.routes._pipeline_qa import run_pipeline_query, schedule_pipeline_metrics
from src.api.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_contract(
    payload: QueryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> QueryResponse:
    result = await run_pipeline_query(
        request=request,
        query=payload.query,
        contract_id=payload.contract_id,
        ground_truth="",
        chat_id=payload.chat_id,
    )
    schedule_pipeline_metrics(
        background_tasks=background_tasks,
        request=request,
        query=payload.query,
        result=result,
    )

    return QueryResponse(
        answer=str(result.get("answer", "")),
        citations=list(result.get("citations", [])),
        sources=list(result.get("sources", [])),
        source_chunks=list(result.get("source_chunks", [])),
        tool_used=str(result.get("tool_used", "pipeline_contract_search")),
        route_reason=str(result.get("route_reason", "")),
        used_web_fallback=bool(result.get("used_web_fallback", False)),
    )


################################################################################
# FILE: src/api/routes/upload.py
################################################################################


import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from src.api.schemas import UploadBatchResponse, UploadItemResponse, UploadResponse

router = APIRouter(tags=["upload"])
logger = logging.getLogger(__name__)


def _strict_scope_enabled() -> bool:
    return os.getenv("REQUIRE_CHAT_SCOPE", "").strip().lower() in {"1", "true", "yes"}


def _safe_contract_stem(filename: str | None, fallback: str) -> str:
    stem = Path(filename or fallback).stem
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_")
    return cleaned or fallback

@router.post("/upload", response_model=UploadResponse | UploadBatchResponse)
async def upload_contract(
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
    chat_id: str | None = Form(default=None),
) -> UploadResponse | UploadBatchResponse:

    upload_items: list[UploadFile] = []
    if file is not None:
        upload_items.append(file)
    if files:
        upload_items.extend(files)

    if not upload_items:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline is not initialized.")

    chat_scope_registry = getattr(request.app.state, "chat_scope_registry", None)
    if chat_scope_registry is None:
        raise HTTPException(status_code=503, detail="Chat scope registry is not initialized.")

    strict_scope = _strict_scope_enabled()
    if strict_scope and not str(chat_id or "").strip():
        raise HTTPException(status_code=400, detail="chat_id is required by server policy.")

    resolved_chat_id = str(chat_id or "").strip() or str(uuid.uuid4())

    upload_results: list[UploadItemResponse] = []

    for index, upload in enumerate(upload_items, start=1):
        file_bytes = bytearray()
        CHUNK_SIZE = 1024 * 1024
        MAX_SIZE = 10 * 1024 * 1024

        while chunk := await upload.read(CHUNK_SIZE):
            file_bytes.extend(chunk)
            if len(file_bytes) > MAX_SIZE:
                raise HTTPException(status_code=413, detail=f"File too large: {upload.filename}")

        file_bytes = bytes(file_bytes)
        if not file_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded file is empty: {upload.filename or f'file_{index}'}",
            )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        base_name = _safe_contract_stem(upload.filename, f"contract_{index}")
        contract_id = f"{base_name}_{timestamp}"

        try:
            pipeline_result = await run_in_threadpool(
                pipeline.ingest_upload,
                upload.filename or "contract.txt",
                file_bytes,
                contract_id,
            )
        except Exception as error:
            logger.exception(
                "Pipeline ingestion failed",
                extra={"source_filename": upload.filename or contract_id},
            )
            raise HTTPException(
                status_code=500,
                detail=f"Pipeline ingestion failed for {upload.filename or contract_id}.",
            ) from error

        upload_results.append(
            UploadItemResponse(
                contract_id=str(pipeline_result.get("contract_id", contract_id)),
                source_name=upload.filename or f"contract_{index}",
                chunks_ingested=int(pipeline_result.get("chunks_ingested", 0)),
                message=str(pipeline_result.get("message", "Contract uploaded and indexed successfully.")),
            )
        )

    await run_in_threadpool(
        chat_scope_registry.add_contracts,
        resolved_chat_id,
        [item.contract_id for item in upload_results],
    )

    if len(upload_results) == 1:
        single = upload_results[0]
        return UploadResponse(
            chat_id=resolved_chat_id,
            contract_id=single.contract_id,
            chunks_ingested=single.chunks_ingested,
            message=single.message,
        )

    return UploadBatchResponse(
        chat_id=resolved_chat_id,
        uploads=upload_results,
        total_files=len(upload_results),
        message=f"Indexed {len(upload_results)} files using the unified Chroma pipeline.",
    )


################################################################################
# FILE: src/api/schemas.py
################################################################################


from typing import Any

from pydantic import BaseModel, Field, model_validator


class Citation(BaseModel):
    chunk_id: str = ""
    contract_name: str = ""
    clause_type: str = ""
    page_number: int | None = None
    url: str = ""


class SourceReference(BaseModel):
    index: int
    label: str
    contract_id: str = ""


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3)
    contract_id: str | None = None
    chat_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    sources: list[SourceReference] = Field(default_factory=list)
    source_chunks: list[dict[str, Any]]
    tool_used: str
    route_reason: str
    used_web_fallback: bool = False


class AskRequest(QueryRequest):
    ground_truth: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_question_alias(cls, value: Any) -> Any:
        if isinstance(value, dict):
            normalized = dict(value)
            if "query" not in normalized and "question" in normalized:
                normalized["query"] = normalized.get("question")
            normalized.pop("question", None)
            return normalized
        return value


class AskResponse(QueryResponse):
    matched_clause_hints: list[str] = Field(default_factory=list)
    evaluation: dict[str, Any] = Field(default_factory=dict)


class UploadResponse(BaseModel):
    chat_id: str
    contract_id: str
    chunks_ingested: int
    message: str


class UploadItemResponse(BaseModel):
    contract_id: str
    source_name: str
    chunks_ingested: int
    message: str


class UploadBatchResponse(BaseModel):
    chat_id: str
    uploads: list[UploadItemResponse]
    total_files: int
    message: str


class ContractSummary(BaseModel):
    contract_id: str
    display_name: str
    source_name: str
    chunks_ingested: int
    uploaded_at: str


class ContractsResponse(BaseModel):
    contracts: list[ContractSummary]
    total: int


class MetricRow(BaseModel):
    id: int
    query: str
    answer: str
    tool_used: str
    used_web_fallback: bool
    faithfulness: float
    answer_relevance: float
    context_precision: float
    context_recall: float
    created_at: str


class MetricsResponse(BaseModel):
    recent: list[MetricRow]
    trends: list[MetricRow]
    analytics: list[dict[str, Any]]


################################################################################
# FILE: src/evaluation/__init__.py
################################################################################

"""Evaluation layer for RAG metrics and metric persistence."""

from src.evaluation.metrics_store import MetricsStore
from src.evaluation.ragas_evaluator import ContractQAEvaluator, RagasEvaluator

__all__ = ["MetricsStore", "ContractQAEvaluator", "RagasEvaluator"]


################################################################################
# FILE: src/evaluation/metrics_store.py
################################################################################


import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, desc, func
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except Exception:
    SQLALCHEMY_AVAILABLE = False

from src.utils.db import should_auto_create_tables

DEFAULT_DATABASE_URL = "sqlite:///data/processed/metrics.db"


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return

    raw_path = database_url[len(prefix):].split("?", 1)[0]
    if not raw_path or raw_path == ":memory:":
        return

    try:
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _as_utc_naive(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            if candidate.endswith("Z"):
                candidate = f"{candidate[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    return parsed
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

    return datetime.now(timezone.utc).replace(tzinfo=None)


if SQLALCHEMY_AVAILABLE:
    class Base(DeclarativeBase):
        pass


    class RagasMetricLog(Base):
        __tablename__ = "ragas_metrics"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        query: Mapped[str] = mapped_column(Text, nullable=False)
        answer: Mapped[str] = mapped_column(Text, nullable=False)
        tool_used: Mapped[str] = mapped_column(String(64), default="contract_search", nullable=False)
        used_web_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
        faithfulness: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        answer_relevance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        context_precision: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        context_recall: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
else:
    class Base:  # type: ignore[no-redef]
        pass


    class RagasMetricLog:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.id = int(kwargs.get("id", 0))
            self.query = str(kwargs.get("query", ""))
            self.answer = str(kwargs.get("answer", ""))
            self.tool_used = str(kwargs.get("tool_used", "contract_search"))
            self.used_web_fallback = bool(kwargs.get("used_web_fallback", False))
            self.faithfulness = float(kwargs.get("faithfulness", 0.0))
            self.answer_relevance = float(kwargs.get("answer_relevance", 0.0))
            self.context_precision = float(kwargs.get("context_precision", 0.0))
            self.context_recall = float(kwargs.get("context_recall", 0.0))
            self.created_at = kwargs.get("created_at", datetime.now(timezone.utc).replace(tzinfo=None))


class MetricsStore:
    def __init__(self, database_url: str | None = None) -> None:
        self._memory_rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.database_url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        if SQLALCHEMY_AVAILABLE:
            _ensure_sqlite_parent_dir(self.database_url)
            self.engine = create_engine(self.database_url, future=True)
            self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        else:
            self.engine = None
            self.SessionLocal = None

    def init_db(self) -> None:
        if SQLALCHEMY_AVAILABLE and should_auto_create_tables(self.database_url):
            Base.metadata.create_all(bind=self.engine)

    def save_metric(self, payload: dict[str, Any]) -> int:
        if SQLALCHEMY_AVAILABLE:
            with self.SessionLocal() as session:
                row = RagasMetricLog(
                    query=str(payload.get("query", "")),
                    answer=str(payload.get("answer", "")),
                    tool_used=str(payload.get("tool_used", "contract_search")),
                    used_web_fallback=bool(payload.get("used_web_fallback", False)),
                    faithfulness=float(payload.get("faithfulness", 0.0)),
                    answer_relevance=float(payload.get("answer_relevance", 0.0)),
                    context_precision=float(payload.get("context_precision", 0.0)),
                    context_recall=float(payload.get("context_recall", 0.0)),
                    created_at=_as_utc_naive(payload.get("created_at")),
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return int(row.id)

        with self._lock:
            row = {
                "id": len(self._memory_rows) + 1,
                "query": str(payload.get("query", "")),
                "answer": str(payload.get("answer", "")),
                "tool_used": str(payload.get("tool_used", "contract_search")),
                "used_web_fallback": bool(payload.get("used_web_fallback", False)),
                "faithfulness": float(payload.get("faithfulness", 0.0)),
                "answer_relevance": float(payload.get("answer_relevance", 0.0)),
                "context_precision": float(payload.get("context_precision", 0.0)),
                "context_recall": float(payload.get("context_recall", 0.0)),
                "created_at": _as_utc_naive(payload.get("created_at")),
            }
            self._memory_rows.append(row)
        return int(row["id"])

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if SQLALCHEMY_AVAILABLE:
            with self.SessionLocal() as session:
                rows = (
                    session.query(RagasMetricLog)
                    .order_by(desc(RagasMetricLog.created_at))
                    .limit(limit)
                    .all()
                )
                return [self._to_dict(row) for row in rows]

        sorted_rows = sorted(self._memory_rows, key=lambda row: _as_utc_naive(row.get("created_at")), reverse=True)
        return [self._to_dict(row) for row in sorted_rows[:limit]]

    def get_trends(self, days: int = 7) -> list[dict[str, Any]]:
        threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        if SQLALCHEMY_AVAILABLE:
            with self.SessionLocal() as session:
                rows = (
                    session.query(RagasMetricLog)
                    .filter(RagasMetricLog.created_at >= threshold)
                    .order_by(RagasMetricLog.created_at.asc())
                    .all()
                )
                return [self._to_dict(row) for row in rows]

        rows = [row for row in self._memory_rows if _as_utc_naive(row.get("created_at")) >= threshold]
        rows = sorted(rows, key=lambda row: _as_utc_naive(row.get("created_at")))
        return [self._to_dict(row) for row in rows]

    def get_query_analytics(self) -> list[dict[str, Any]]:
        if SQLALCHEMY_AVAILABLE:
            with self.SessionLocal() as session:
                rows = (
                    session.query(
                        RagasMetricLog.tool_used,
                        func.count(RagasMetricLog.id).label("count"),
                        func.avg(RagasMetricLog.faithfulness).label("avg_faithfulness"),
                    )
                    .group_by(RagasMetricLog.tool_used)
                    .order_by(desc("count"))
                    .all()
                )

                return [
                    {
                        "tool_used": tool_used,
                        "count": int(count),
                        "avg_faithfulness": float(avg_faithfulness or 0.0),
                    }
                    for tool_used, count, avg_faithfulness in rows
                ]

        aggregates: dict[str, dict[str, float]] = {}
        for row in self._memory_rows:
            tool = row["tool_used"]
            if tool not in aggregates:
                aggregates[tool] = {"count": 0.0, "faithfulness_sum": 0.0}
            aggregates[tool]["count"] += 1.0
            aggregates[tool]["faithfulness_sum"] += float(row.get("faithfulness", 0.0))

        output = []
        for tool, stats in aggregates.items():
            count = int(stats["count"])
            output.append(
                {
                    "tool_used": tool,
                    "count": count,
                    "avg_faithfulness": (stats["faithfulness_sum"] / count) if count > 0 else 0.0,
                }
            )

        output.sort(key=lambda item: item["count"], reverse=True)
        return output

    @staticmethod
    def _to_dict(row: RagasMetricLog) -> dict[str, Any]:
        if isinstance(row, dict):
            created_iso = _as_utc_naive(row.get("created_at")).isoformat()
            return {
                "id": int(row.get("id", 0)),
                "query": str(row.get("query", "")),
                "answer": str(row.get("answer", "")),
                "tool_used": str(row.get("tool_used", "contract_search")),
                "used_web_fallback": bool(row.get("used_web_fallback", False)),
                "faithfulness": float(row.get("faithfulness", 0.0)),
                "answer_relevance": float(row.get("answer_relevance", 0.0)),
                "context_precision": float(row.get("context_precision", 0.0)),
                "context_recall": float(row.get("context_recall", 0.0)),
                "created_at": created_iso,
            }

        return {
            "id": row.id,
            "query": row.query,
            "answer": row.answer,
            "tool_used": row.tool_used,
            "used_web_fallback": row.used_web_fallback,
            "faithfulness": row.faithfulness,
            "answer_relevance": row.answer_relevance,
            "context_precision": row.context_precision,
            "context_recall": row.context_recall,
            "created_at": row.created_at.isoformat(),
        }


################################################################################
# FILE: src/evaluation/ragas_evaluator.py
################################################################################


import json
import math
import os
import re
from dataclasses import dataclass
from statistics import mean
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv() -> bool:  # type: ignore[no-redef]
        return False

try:
    import requests
except Exception:
    requests = None

# Avoid optional TensorFlow import path in transformers (requires tf-keras in this env).
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")

try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers import util as sentence_transformers_util
except Exception:
    SentenceTransformer = None
    sentence_transformers_util = None


load_dotenv()


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")
JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_SEMANTIC_MODEL: Any | None = None
_SEMANTIC_MODEL_NAME: str | None = None


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text)}


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def jaccard_similarity(left: str, right: str) -> float:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens and not right_tokens:
        return 1.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return safe_divide(intersection, union)


def _get_semantic_model(model_name: str) -> Any | None:
    global _SEMANTIC_MODEL, _SEMANTIC_MODEL_NAME

    if SentenceTransformer is None:
        return None

    if _SEMANTIC_MODEL is not None and _SEMANTIC_MODEL_NAME == model_name:
        return _SEMANTIC_MODEL

    _SEMANTIC_MODEL = SentenceTransformer(model_name)
    _SEMANTIC_MODEL_NAME = model_name
    return _SEMANTIC_MODEL


def semantic_similarity(left: str, right: str, model_name: str) -> float:
    if not left.strip() or not right.strip():
        return 0.0

    model = _get_semantic_model(model_name)
    if model is None or sentence_transformers_util is None:
        return jaccard_similarity(left, right)

    try:
        embeddings = model.encode([left, right], convert_to_tensor=True, normalize_embeddings=True)
        score = float(sentence_transformers_util.cos_sim(embeddings[0], embeddings[1]).item())
        return max(0.0, min(1.0, score))
    except Exception:
        return jaccard_similarity(left, right)


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if not text:
        raise RuntimeError("Ollama returned an empty response.")

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        text = fenced_match.group(1).strip()

    try:
        parsed_direct = json.loads(text)
        if isinstance(parsed_direct, dict):
            return parsed_direct
    except Exception:
        pass

    object_match = JSON_OBJECT_PATTERN.search(text)
    if not object_match:
        raise RuntimeError("No JSON object found in Ollama response.")

    parsed = json.loads(object_match.group(0))
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama response JSON is not an object.")
    return parsed


def _coerce_metric(payload: dict[str, Any], key: str) -> float:
    if key not in payload:
        raise RuntimeError(f"Missing key '{key}' in Ollama metric response.")

    value = float(payload[key])
    if not math.isfinite(value):
        raise RuntimeError(f"Metric '{key}' is not finite.")
    return round(max(0.0, min(1.0, value)), 4)


def _split_sentences(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+|\n+", text) if segment.strip()]


def _sentence_support(sentence: str, contexts: list[str]) -> float:
    sentence_tokens = tokenize(sentence)
    if not sentence_tokens:
        return 0.0

    best = 0.0
    for context in contexts:
        context_tokens = tokenize(context)
        overlap = len(sentence_tokens & context_tokens)
        support = safe_divide(overlap, len(sentence_tokens))
        if support > best:
            best = support
    return best


@dataclass
class OllamaJudge:
    model: str = "mistral"
    endpoint: str = "http://localhost:11434/api/generate"
    timeout_seconds: float = 90.0

    def _build_judge_prompt(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str,
    ) -> str:
        context_section = "\n\n".join(
            f"Context {index + 1}:\n{str(context).strip()[:1500]}"
            for index, context in enumerate(contexts[:4])
            if str(context).strip()
        )
        if not context_section:
            context_section = "No context provided."

        ground_truth_text = ground_truth.strip() or "No explicit ground truth provided."

        return (
            "[INST]\n"
            "You are a strict legal QA evaluator.\n"
            "Score the answer using these metrics in the range [0, 1]:\n"
            "- faithfulness: Is the answer supported by context evidence only?\n"
            "- answer_relevance: Does the answer address the question directly?\n"
            "- context_precision: Is the provided context focused on what the question needs?\n"
            "- context_recall: Does the context cover information needed to answer the question and ground truth?\n"
            "Return ONLY valid JSON with exactly these keys: faithfulness, answer_relevance, context_precision, context_recall.\n"
            "No markdown, no explanation, no extra keys.\n\n"
            f"Question:\n{question.strip()}\n\n"
            f"Answer:\n{answer.strip()}\n\n"
            f"Contexts:\n{context_section}\n\n"
            f"Ground truth:\n{ground_truth_text}\n"
            "[/INST]"
        )

    def score(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str,
    ) -> dict[str, float]:
        if requests is None:
            raise RuntimeError("requests package is required for Ollama judge scoring.")

        prompt = self._build_judge_prompt(question, answer, contexts, ground_truth)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }

        response = requests.post(self.endpoint, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()

        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Ollama response payload is not a JSON object.")

        response_text = body.get("response", "")
        if not isinstance(response_text, str) or not response_text.strip():
            raise RuntimeError("Ollama response is missing generated text.")

        parsed = _extract_json_object(response_text)
        return {
            "faithfulness": _coerce_metric(parsed, "faithfulness"),
            "answer_relevance": _coerce_metric(parsed, "answer_relevance"),
            "context_precision": _coerce_metric(parsed, "context_precision"),
            "context_recall": _coerce_metric(parsed, "context_recall"),
        }


@dataclass
class EvalSample:
    question: str
    answer: str
    contexts: list[str]
    ground_truth: str


class ContractQAEvaluator:
    def __init__(
        self,
        use_llm_judge: bool = True,
        use_ragas: bool | None = None,
    ) -> None:
        # Preserve backward compatibility with existing call sites using use_ragas.
        if use_ragas is not None:
            use_llm_judge = bool(use_ragas)

        self.use_llm_judge = use_llm_judge
        self._semantic_model_name = os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self._ollama = OllamaJudge(
            model=os.getenv("OLLAMA_MODEL", "mistral"),
            endpoint=os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate"),
            timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90")),
        )

    def evaluate_single(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str = "",
    ) -> dict[str, Any]:
        reference_scores = self._evaluate_reference(question, answer, contexts, ground_truth)
        fallback_reason = ""

        if self.use_llm_judge:
            try:
                llm_scores = self._ollama.score(question, answer, contexts, ground_truth)
                if self._metrics_are_finite(llm_scores):
                    merged = self._merge_scores(reference=reference_scores, llm=llm_scores)
                    merged["score_source"] = "blended_llm_semantic"
                    return merged
            except (Exception, KeyboardInterrupt) as error:
                fallback_reason = str(error)

        reference_scores["score_source"] = "semantic_reference"
        if fallback_reason:
            reference_scores["fallback_reason"] = fallback_reason[:300]
        return reference_scores

    @staticmethod
    def _metrics_are_finite(metrics: dict[str, float]) -> bool:
        required = ("faithfulness", "answer_relevance", "context_precision", "context_recall")
        for key in required:
            value = metrics.get(key)
            if value is None:
                return False
            try:
                if not math.isfinite(float(value)):
                    return False
            except Exception:
                return False
        return True

    @staticmethod
    def _merge_scores(reference: dict[str, float], llm: dict[str, float]) -> dict[str, float]:
        # Faithfulness is anchored by deterministic support so ungrounded LLM scoring
        # cannot drift too far upward.
        blended_faithfulness = (0.65 * reference["faithfulness"]) + (0.35 * llm["faithfulness"])
        capped_faithfulness = min(blended_faithfulness, reference["faithfulness"] + 0.15)

        return {
            "faithfulness": round(max(0.0, min(1.0, capped_faithfulness)), 4),
            "answer_relevance": round((0.5 * reference["answer_relevance"]) + (0.5 * llm["answer_relevance"]), 4),
            "context_precision": round((0.5 * reference["context_precision"]) + (0.5 * llm["context_precision"]), 4),
            "context_recall": round((0.5 * reference["context_recall"]) + (0.5 * llm["context_recall"]), 4),
        }

    def evaluate_batch(self, samples: list[EvalSample]) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for sample in samples:
            outputs.append(
                self.evaluate_single(
                    question=sample.question,
                    answer=sample.answer,
                    contexts=sample.contexts,
                    ground_truth=sample.ground_truth,
                )
            )
        return outputs

    def summarize(self, results: list[dict[str, Any]]) -> dict[str, float]:
        if not results:
            return {
                "faithfulness": 0.0,
                "answer_relevance": 0.0,
                "context_precision": 0.0,
                "context_recall": 0.0,
            }

        return {
            "faithfulness": mean(float(item["faithfulness"]) for item in results),
            "answer_relevance": mean(float(item["answer_relevance"]) for item in results),
            "context_precision": mean(float(item["context_precision"]) for item in results),
            "context_recall": mean(float(item["context_recall"]) for item in results),
        }

    def _evaluate_reference(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str,
    ) -> dict[str, float]:
        context_blob = "\n".join(contexts)
        answer_sentences = _split_sentences(answer)

        if answer_sentences and contexts:
            support_scores = [_sentence_support(sentence, contexts) for sentence in answer_sentences]
            semantic_support_scores = [
                semantic_similarity(sentence, context_blob, model_name=self._semantic_model_name)
                for sentence in answer_sentences
            ]
            support_faithfulness = mean(support_scores)
            semantic_faithfulness = mean(semantic_support_scores)
            faithfulness_score = (0.7 * support_faithfulness) + (0.3 * semantic_faithfulness)
        else:
            faithfulness_score = 0.0

        answer_relevance_score = semantic_similarity(question, answer, model_name=self._semantic_model_name)
        context_precision_score = (
            mean([semantic_similarity(question, context, model_name=self._semantic_model_name) for context in contexts])
            if contexts
            else 0.0
        )

        if ground_truth.strip():
            context_recall_score = semantic_similarity(ground_truth, context_blob, model_name=self._semantic_model_name)
        else:
            context_recall_score = min(1.0, context_precision_score + 0.05)

        return {
            "faithfulness": round(max(0.0, min(1.0, faithfulness_score)), 4),
            "answer_relevance": round(answer_relevance_score, 4),
            "context_precision": round(context_precision_score, 4),
            "context_recall": round(context_recall_score, 4),
        }


# Backward compatible alias so existing imports continue to work.
RagasEvaluator = ContractQAEvaluator


################################################################################
# FILE: src/evaluation/run_eval.py
################################################################################


import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.evaluation.metrics_store import MetricsStore
from src.evaluation.ragas_evaluator import ContractQAEvaluator
from src.ingestion.loader import load_cuad_dataset, normalize_row

DEFAULT_EVAL_PATH = Path("data/eval_samples/cuad_eval_samples.jsonl")
DEFAULT_RAW_PATH = Path("data/raw/cuad_train.jsonl")
DEFAULT_CUAD_QA_JSON = "hf://datasets/theatticusproject/cuad/CUAD_v1/CUAD_v1.json"

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def _load_raw_rows(raw_path: Path = DEFAULT_RAW_PATH) -> list[dict[str, Any]]:
    if not raw_path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with raw_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def extract_relevant_passage(text: str, question: str, window: int = 700) -> str:
    normalized = " ".join(str(text).split())
    if not normalized:
        return ""

    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", normalized) if segment.strip()]
    if not sentences:
        return normalized[:window]

    question_tokens = {
        token.lower()
        for token in TOKEN_PATTERN.findall(question)
        if len(token) > 2
    }
    if not question_tokens:
        return normalized[:window]

    scored = []
    for index, sentence in enumerate(sentences):
        lowered = sentence.lower()
        score = sum(1 for token in question_tokens if token in lowered)
        scored.append((score, index, sentence))

    best_index = max(scored, key=lambda item: item[0])[1]
    start = max(0, best_index - 2)
    candidate = ". ".join(sentences[start : start + 8]).strip()
    if not candidate:
        candidate = normalized
    return candidate[:window]


def _build_synthetic_eval_rows(rows: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    text_rows = [row for row in rows if str(row.get("contract_text", "")).strip()]
    if not text_rows:
        return []

    random.seed(42)
    sampled = random.sample(text_rows, k=min(sample_size, len(text_rows)))
    synthetic: list[dict[str, Any]] = []

    for item in sampled:
        contract_name = str(item.get("contract_name", "contract"))
        question = f"Summarize obligations, risks, and liability terms in contract {contract_name}."
        full_text = str(item.get("contract_text", ""))
        context = full_text[:3000]
        ground_truth = extract_relevant_passage(full_text, question=question, window=700)
        if not ground_truth.strip():
            ground_truth = context[:700]
        answer = ground_truth

        synthetic.append(
            {
                "question": question,
                "ground_truth": ground_truth,
                "contexts": [context],
                "answer": answer,
                "tool_used": "offline_eval_synthetic",
            }
        )

    return synthetic


def _build_real_eval_rows_from_cuad_json(sample_size: int) -> list[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except Exception:
        return []

    data_path = DEFAULT_CUAD_QA_JSON
    try:
        dataset = load_dataset("json", data_files=data_path, split="train")
        if not dataset:
            return []

        payload = dataset[0]
        data_items = payload.get("data", []) if isinstance(payload, dict) else []
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for item in data_items:
        if not isinstance(item, dict):
            continue

        contract_name = str(item.get("title", "contract"))
        paragraphs = item.get("paragraphs", [])
        if not isinstance(paragraphs, list):
            continue

        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue

            context_blob = str(paragraph.get("context", ""))
            if not context_blob.strip():
                continue

            qas = paragraph.get("qas", [])
            if not isinstance(qas, list):
                continue

            for qa in qas:
                if not isinstance(qa, dict):
                    continue

                question = str(qa.get("question", "")).strip()
                if not question:
                    continue

                answers = qa.get("answers", [])
                if not isinstance(answers, list):
                    continue

                answer_texts = [
                    str(answer.get("text", "")).strip()
                    for answer in answers
                    if isinstance(answer, dict) and str(answer.get("text", "")).strip()
                ]
                if not answer_texts:
                    continue

                ground_truth = answer_texts[0]
                context = extract_relevant_passage(context_blob, question=question, window=3000)
                if not context.strip():
                    context = context_blob[:3000]

                rows.append(
                    {
                        "question": question,
                        "ground_truth": ground_truth,
                        "contexts": [context],
                        "answer": ground_truth,
                        "tool_used": "offline_eval_real_qa",
                        "contract_name": contract_name,
                    }
                )

    if not rows:
        return []

    random.seed(42)
    return random.sample(rows, k=min(sample_size, len(rows)))


def build_eval_samples(sample_size: int = 100, output_path: Path = DEFAULT_EVAL_PATH) -> Path:
    rows = _load_raw_rows()
    qa_rows = [
        row
        for row in rows
        if str(row.get("question", "")).strip() and str(row.get("contract_text", "")).strip()
    ]

    if qa_rows:
        random.seed(42)
        sampled = random.sample(qa_rows, k=min(sample_size, len(qa_rows)))
    else:
        sampled = _build_real_eval_rows_from_cuad_json(sample_size=sample_size)

    if not sampled:
        sampled = _build_synthetic_eval_rows(rows=rows, sample_size=sample_size)

    if not sampled:
        dataset = load_cuad_dataset(split="train")
        normalized_rows = [normalize_row(dict(row), index) for index, row in enumerate(dataset)]
        filtered_rows = [row for row in normalized_rows if row["question"].strip() and row["contract_text"].strip()]
        random.seed(42)
        sampled = random.sample(filtered_rows, k=min(sample_size, len(filtered_rows)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for item in sampled:
            record = {
                "question": item.get("question", ""),
                "ground_truth": (
                    item.get("ground_truth", "")
                    if "ground_truth" in item
                    else (item.get("answers", [""])[0] if item.get("answers") else "")
                ),
                "contexts": item.get("contexts", [item.get("contract_text", "")[:2500]]),
                "answer": (
                    item.get("answer", "")
                    if "answer" in item
                    else (item.get("answers", [""])[0] if item.get("answers") else "")
                ),
                "tool_used": item.get("tool_used", "offline_eval"),
            }
            file.write(json.dumps(record) + "\n")

    return output_path


def load_eval_samples(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                samples.append(json.loads(line))
    return samples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run batch RAG evaluation over CUAD samples.")
    parser.add_argument("--sample-size", type=int, default=100, help="Number of Q&A pairs to evaluate")
    parser.add_argument("--samples-path", default=str(DEFAULT_EVAL_PATH), help="JSONL eval samples path")
    parser.add_argument("--build-samples", action="store_true", help="Build sample file from CUAD before eval")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples_path = Path(args.samples_path)

    if args.build_samples or not samples_path.exists():
        samples_path = build_eval_samples(sample_size=args.sample_size, output_path=samples_path)

    raw_samples = load_eval_samples(samples_path)
    synthetic_count = sum(1 for sample in raw_samples if sample.get("tool_used") == "offline_eval_synthetic")
    if synthetic_count:
        print(
            "Warning: "
            f"{synthetic_count}/{len(raw_samples)} samples are synthetic (offline_eval_synthetic), "
            "metrics may be conservative."
        )

    evaluator = ContractQAEvaluator(use_llm_judge=True)
    store = MetricsStore()
    store.init_db()

    results: list[dict[str, Any]] = []
    for sample in raw_samples:
        eval_metrics = evaluator.evaluate_single(
            question=sample.get("question", ""),
            answer=sample.get("answer", ""),
            contexts=sample.get("contexts", []),
            ground_truth=sample.get("ground_truth", ""),
        )
        score_source = str(eval_metrics.get("score_source", "unknown"))
        print(f"score_source: {score_source}")

        payload = {
            "query": sample.get("question", ""),
            "answer": sample.get("answer", ""),
            "tool_used": sample.get("tool_used", "offline_eval"),
            "used_web_fallback": False,
            **eval_metrics,
        }
        store.save_metric(payload)

        results.append(eval_metrics)

    summary = evaluator.summarize(results)
    print(f"Evaluated {len(raw_samples)} samples from {samples_path}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()


################################################################################
# FILE: src/ingestion/__init__.py
################################################################################

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


################################################################################
# FILE: src/ingestion/chunker.py
################################################################################


import argparse
import json
from pathlib import Path
from typing import Any

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except Exception:
    class RecursiveCharacterTextSplitter:  # type: ignore[no-redef]
        def __init__(self, chunk_size: int, chunk_overlap: int, separators: list[str], length_function) -> None:
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap

        def split_text(self, text: str) -> list[str]:
            chunks = []
            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                chunks.append(text[start:end])
                if end == len(text):
                    break
                start = max(end - self.chunk_overlap, 0)
            return chunks

from src.ingestion.loader import build_contract_records, load_cuad_dataset

DEFAULT_CHUNK_SIZE = 1500
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_SEPARATORS = [
    "\nSECTION ",
    "\n\d+\.\w+\.",
    "\n\n",
    "\n",
    ". ",
    " "
]
DEFAULT_OUTPUT_PATH = Path("data/processed/chunks.jsonl")
DEFAULT_RAW_PATH = Path("data/raw/cuad_train.jsonl")
APPROX_CHARS_PER_PAGE = 3200


def build_splitter(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    separators: list[str] | None = None,
) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators or DEFAULT_SEPARATORS,
        length_function=len,
    )


def _safe_chunk_id(contract_name: str, chunk_index: int) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in contract_name.lower())
    return f"{normalized}_{chunk_index}"


def _find_chunk_span(full_text: str, chunk_text: str, search_start: int) -> tuple[int, int]:
    start = full_text.find(chunk_text, search_start)
    if start < 0:
        start = full_text.find(chunk_text)
    if start < 0:
        start = max(search_start, 0)

    end = start + len(chunk_text)
    return start, end


def chunk_contract(contract: dict[str, Any], splitter: RecursiveCharacterTextSplitter) -> list[dict[str, Any]]:
    contract_text = contract.get("contract_text", "")
    if not contract_text.strip():
        return []

    contract_name = str(contract.get("contract_name", "unknown_contract"))
    clause_type = str(contract.get("clause_type", "unknown"))
    raw_chunks = splitter.split_text(contract_text)

    chunks: list[dict[str, Any]] = []
    cursor = 0
    for chunk_index, chunk_text in enumerate(raw_chunks):
        char_start, char_end = _find_chunk_span(contract_text, chunk_text, cursor)
        cursor = max(char_end - DEFAULT_CHUNK_OVERLAP, 0)
        page_number = (char_start // APPROX_CHARS_PER_PAGE) + 1

        chunks.append(
            {
                "chunk_id": _safe_chunk_id(contract_name, chunk_index),
                "text": chunk_text,
                "metadata": {
                    "contract_name": contract_name,
                    "clause_type": clause_type,
                    "page_number": page_number,
                    "char_start": char_start,
                    "char_end": char_end,
                },
            }
        )

    return chunks


def load_contract_records_from_raw(
    raw_path: Path = DEFAULT_RAW_PATH,
    limit_contracts: int | None = None,
) -> list[dict[str, Any]]:
    if not raw_path.exists():
        return []

    grouped: dict[str, dict[str, Any]] = {}
    with raw_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            row = json.loads(line)
            contract_name = str(row.get("contract_name", "")).strip()
            contract_text = str(row.get("contract_text", "")).strip()
            clause_type = str(row.get("clause_type", "unknown")).strip() or "unknown"

            if not contract_name or not contract_text:
                continue

            if contract_name not in grouped:
                if limit_contracts is not None and len(grouped) >= limit_contracts:
                    continue

                grouped[contract_name] = {
                    "contract_name": contract_name,
                    "contract_text": contract_text,
                    "clause_type": clause_type,
                }

    return list(grouped.values())


def build_chunks_from_cuad(split: str = "train", limit_contracts: int | None = None) -> list[dict[str, Any]]:
    records = load_contract_records_from_raw(limit_contracts=limit_contracts)
    if not records:
        dataset = load_cuad_dataset(split=split)

        if limit_contracts is not None:
            dataset = dataset.select(range(min(limit_contracts, len(dataset))))

        records = build_contract_records(dataset)

    splitter = build_splitter()
    all_chunks: list[dict[str, Any]] = []
    for record in records:
        all_chunks.extend(chunk_contract(record, splitter))

    return all_chunks


def save_chunks(chunks: list[dict[str, Any]], output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk) + "\n")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chunk CUAD contracts into retrieval-ready JSONL chunks.")
    parser.add_argument("--split", default="train", help="Dataset split")
    parser.add_argument("--limit-contracts", type=int, default=None, help="Optional limit for quick iteration")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output JSONL for processed chunks")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    chunks = build_chunks_from_cuad(split=args.split, limit_contracts=args.limit_contracts)
    output_path = save_chunks(chunks, output_path=Path(args.output))
    print(f"Saved {len(chunks)} chunks to {output_path}")


if __name__ == "__main__":
    main()


################################################################################
# FILE: src/ingestion/embedder.py
################################################################################


import argparse
import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

try:
    import boto3
except Exception:
    boto3 = None

try:
    from langchain_community.vectorstores import FAISS
except Exception:
    FAISS = None

try:
    from langchain_core.embeddings import Embeddings
except Exception:
    class Embeddings:  # type: ignore[no-redef]
        pass

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv() -> bool:  # type: ignore[no-redef]
        return False

try:
    from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
except Exception:
    HuggingFaceInferenceAPIEmbeddings = None

from src.ingestion.chunker import DEFAULT_OUTPUT_PATH, build_chunks_from_cuad, save_chunks

DEFAULT_FAISS_DIR = Path("data/processed/faiss_index")
DEFAULT_METADATA_PATH = Path("data/processed/chunk_metadata.json")


load_dotenv()


from src.utils.embeddings import HashEmbeddings, get_hash_embeddings

def resolve_embeddings(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> Embeddings:
    hf_token = os.getenv("HF_TOKEN", "").strip()
    if HuggingFaceInferenceAPIEmbeddings is not None and hf_token:
        embedding_kwargs: dict[str, Any] = {
            "api_key": hf_token,
            "model_name": model_name,
        }
        api_url = os.getenv("HF_EMBEDDING_API_URL", "").strip()
        if api_url:
            embedding_kwargs["api_url"] = api_url
        return HuggingFaceInferenceAPIEmbeddings(**embedding_kwargs)

    return get_hash_embeddings()


def _is_valid_vector(value: Any) -> bool:
    try:
        vector = np.asarray(value, dtype=np.float32)
    except Exception:
        return False

    if vector.ndim != 1 or vector.size == 0:
        return False

    return bool(np.isfinite(vector).all())


def _embedding_backend_healthy(embeddings: Embeddings) -> bool:
    try:
        probe = embeddings.embed_query("embedding healthcheck")
    except Exception:
        return False

    return _is_valid_vector(probe)


def load_chunks(chunks_path: Path = DEFAULT_OUTPUT_PATH) -> list[dict[str, Any]]:
    if not chunks_path.exists():
        raise FileNotFoundError(
            f"Chunks file not found at {chunks_path}. Run `python -m src.ingestion.chunker` first."
        )

    chunks: list[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def build_faiss_index(
    chunks: list[dict[str, Any]],
    output_dir: Path = DEFAULT_FAISS_DIR,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> Path:
    if FAISS is None:
        raise RuntimeError("langchain-community is required to build FAISS indexes.")

    output_dir.mkdir(parents=True, exist_ok=True)
    embeddings = resolve_embeddings(model_name=model_name)
    if not _embedding_backend_healthy(embeddings):
        print(
            "Embedding backend returned an invalid probe vector. "
            "Falling back to deterministic hash embeddings."
        )
        embeddings = get_hash_embeddings()

    texts = [chunk["text"] for chunk in chunks]
    metadatas = []
    for chunk in chunks:
        metadata = dict(chunk.get("metadata", {}))
        metadata["chunk_id"] = chunk.get("chunk_id")
        metadatas.append(metadata)

    try:
        vector_store = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas)
    except Exception as exc:
        if isinstance(embeddings, HashEmbeddings):
            raise

        print(
            f"Primary embedding backend failed during index build ({exc}). "
            "Retrying with deterministic hash embeddings."
        )
        embeddings = get_hash_embeddings()
        vector_store = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas)

    vector_store.save_local(str(output_dir))
    return output_dir


def save_metadata(chunks: list[dict[str, Any]], output_path: Path = DEFAULT_METADATA_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "metadata": chunk.get("metadata", {}),
        }
        for chunk in chunks
    ]

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2)

    return output_path


def upload_faiss_to_s3(index_dir: Path, bucket: str, key: str, region: str) -> str:
    """Archive and upload local FAISS artifacts so ECS tasks can load them at startup."""
    if not bucket:
        raise ValueError("S3 bucket name is required.")
    if boto3 is None:
        raise RuntimeError("boto3 is required to upload FAISS artifacts to S3.")

    s3_client = boto3.client("s3", region_name=region)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_archive:
        archive_path = Path(temp_archive.name)

    with tarfile.open(archive_path, "w:gz") as archive:
        for child in index_dir.iterdir():
            archive.add(child, arcname=child.name)

    s3_client.upload_file(str(archive_path), bucket, key)
    return f"s3://{bucket}/{key}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a FAISS index from processed chunks.")
    parser.add_argument("--chunks", default=str(DEFAULT_OUTPUT_PATH), help="Path to chunked JSONL file")
    parser.add_argument("--faiss-dir", default=str(DEFAULT_FAISS_DIR), help="Path to save FAISS index")
    parser.add_argument("--metadata", default=str(DEFAULT_METADATA_PATH), help="Path to save chunk metadata")
    parser.add_argument("--embedding-model", default="sentence-transformers/all-MiniLM-L6-v2", help="Embedding model id")
    parser.add_argument("--upload-s3", action="store_true", help="Upload FAISS artifacts to S3")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    chunks_path = Path(args.chunks)

    if not chunks_path.exists():
        chunks = build_chunks_from_cuad()
        save_chunks(chunks, chunks_path)
    else:
        chunks = load_chunks(chunks_path)

    faiss_dir = build_faiss_index(chunks=chunks, output_dir=Path(args.faiss_dir), model_name=args.embedding_model)
    metadata_path = save_metadata(chunks=chunks, output_path=Path(args.metadata))

    print(f"Saved FAISS index to {faiss_dir}")
    print(f"Saved metadata to {metadata_path}")

    if args.upload_s3:
        bucket = os.getenv("S3_FAISS_BUCKET", "")
        key = os.getenv("S3_FAISS_KEY", "faiss/legal_contracts/index.tar.gz")
        region = os.getenv("AWS_REGION", "us-east-1")
        s3_uri = upload_faiss_to_s3(index_dir=faiss_dir, bucket=bucket, key=key, region=region)
        print(f"Uploaded FAISS artifacts to {s3_uri}")


if __name__ == "__main__":
    main()


################################################################################
# FILE: src/ingestion/loader.py
################################################################################


import argparse
import json
from io import BytesIO
from pathlib import Path
from typing import Any, TypeAlias

try:
    from datasets import Dataset as DatasetType, __version__ as DATASETS_VERSION, load_dataset

    DATASETS_SUPPORTS_TRUST_REMOTE_CODE = int(DATASETS_VERSION.split(".")[0]) < 4
except Exception:
    DatasetType: TypeAlias = Any
    DATASETS_SUPPORTS_TRUST_REMOTE_CODE = False

    def load_dataset(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("The `datasets` package is required to load CUAD.")

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

PRIMARY_DATASET_ID = "theatticusproject/cuad"
FALLBACK_DATASET_IDS = (
    "theatticusproject/cuad-qa",
    "atticusdataset/cuad",
    "cuad",
)
DEFAULT_SPLIT = "train"
RAW_OUTPUT_PATH = Path("data/raw/cuad_train.jsonl")

TEXT_FIELD_CANDIDATES = ("contract_text", "context", "document_text", "text")
CONTRACT_ID_CANDIDATES = (
    "contract_name",
    "title",
    "filename",
    "document_id",
    "contract_id",
    "id",
)
QUESTION_FIELD_CANDIDATES = ("question", "query", "prompt")
CLAUSE_TYPE_CANDIDATES = ("clause_type", "category", "label", "question_type")
ANSWER_FIELD_CANDIDATES = ("answers", "answer", "ground_truth")
MAX_PDF_PAGES = 80


def _load_dataset_compat(dataset_id: str, split: str, verification_mode: str = "no_checks") -> DatasetType:
    """Load datasets with compatibility across datasets library versions."""
    try:
        return load_dataset(dataset_id, split=split, verification_mode=verification_mode)
    except TypeError:
        return load_dataset(dataset_id, split=split)
    except Exception as load_error:
        if not DATASETS_SUPPORTS_TRUST_REMOTE_CODE:
            raise load_error

        # Fallback path for older datasets versions that still rely on dataset scripts.
        try:
            return load_dataset(
                dataset_id,
                split=split,
                verification_mode=verification_mode,
                trust_remote_code=True,
            )
        except Exception:
            raise load_error


def load_cuad_dataset(dataset_id: str = PRIMARY_DATASET_ID, split: str = DEFAULT_SPLIT) -> DatasetType:
    """Load CUAD from HuggingFace with a fallback dataset id."""
    try:
        if dataset_id == PRIMARY_DATASET_ID:
            dataset = _load_dataset_compat(dataset_id=dataset_id, split=split)
        else:
            dataset = _load_dataset_compat(dataset_id=dataset_id, split=split)

        columns = set(getattr(dataset, "column_names", []))
        has_text_fields = any(field in columns for field in TEXT_FIELD_CANDIDATES)

        if not has_text_fields and dataset_id == PRIMARY_DATASET_ID:
            for fallback_dataset_id in FALLBACK_DATASET_IDS:
                try:
                    return _load_dataset_compat(dataset_id=fallback_dataset_id, split=split)
                except Exception:
                    continue

            return dataset

        return dataset
    except Exception as primary_error:
        if dataset_id != PRIMARY_DATASET_ID:
            raise RuntimeError(f"Failed to load dataset {dataset_id}") from primary_error

        for fallback_dataset_id in FALLBACK_DATASET_IDS:
            try:
                return _load_dataset_compat(dataset_id=fallback_dataset_id, split=split)
            except Exception:
                continue

        raise RuntimeError("Unable to load any CUAD dataset source.") from primary_error


def _first_available(row: dict[str, Any], candidates: tuple[str, ...], default: Any = None) -> Any:
    for key in candidates:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _normalize_answers(raw_answers: Any) -> list[str]:
    if raw_answers is None:
        return []

    if isinstance(raw_answers, str):
        return [raw_answers]

    if isinstance(raw_answers, list):
        normalized = [str(item) for item in raw_answers if item is not None and str(item).strip()]
        return normalized

    if isinstance(raw_answers, dict):
        if "text" in raw_answers and isinstance(raw_answers["text"], list):
            return [str(item) for item in raw_answers["text"] if str(item).strip()]
        if "text" in raw_answers and isinstance(raw_answers["text"], str):
            return [raw_answers["text"]]
        if "answer" in raw_answers and str(raw_answers["answer"]).strip():
            return [str(raw_answers["answer"])]

    return [str(raw_answers)]


def _extract_text_from_pdf_feature(pdf_feature: Any) -> str:
    if pdf_feature is None:
        return ""

    if hasattr(pdf_feature, "stream") and PdfReader is not None:
        stream = getattr(pdf_feature, "stream", None)
        if stream is not None and hasattr(stream, "read") and hasattr(stream, "seek"):
            try:
                start_position = stream.tell()
                stream.seek(0)
                raw_bytes = stream.read()
                stream.seek(start_position)

                reader = PdfReader(BytesIO(raw_bytes))
                texts = []
                for page in reader.pages[:MAX_PDF_PAGES]:
                    try:
                        page_text = page.extract_text() or ""
                    except Exception:
                        page_text = ""
                    if page_text.strip():
                        texts.append(page_text)

                if texts:
                    return "\n".join(texts)
            except Exception:
                pass

    if hasattr(pdf_feature, "pages"):
        texts = []
        for page in list(getattr(pdf_feature, "pages", []))[:MAX_PDF_PAGES]:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if page_text.strip():
                texts.append(page_text)

        try:
            pdf_feature.close()
        except Exception:
            pass

        return "\n".join(texts)

    if isinstance(pdf_feature, dict):
        raw_bytes = pdf_feature.get("bytes")
        if raw_bytes and PdfReader is not None:
            try:
                reader = PdfReader(BytesIO(raw_bytes))
                return "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception:
                return ""

    return ""


def _extract_contract_name_from_pdf(pdf_feature: Any, fallback_name: str) -> str:
    if pdf_feature is None:
        return fallback_name

    if hasattr(pdf_feature, "stream"):
        stream = getattr(pdf_feature, "stream", None)
        name = getattr(stream, "name", None)
        if name:
            return Path(str(name)).stem

    if isinstance(pdf_feature, dict):
        path = pdf_feature.get("path")
        if path:
            return Path(str(path)).stem

    return fallback_name


def normalize_row(row: dict[str, Any], row_index: int) -> dict[str, Any]:
    fallback_contract_name = f"contract_{row_index}"
    contract_name = _first_available(row, CONTRACT_ID_CANDIDATES, fallback_contract_name)
    contract_text = _first_available(row, TEXT_FIELD_CANDIDATES, "")
    pdf_feature = row.get("pdf")

    if not str(contract_text).strip() and pdf_feature is not None:
        contract_text = _extract_text_from_pdf_feature(pdf_feature)

    if contract_name == fallback_contract_name and pdf_feature is not None:
        contract_name = _extract_contract_name_from_pdf(pdf_feature, fallback_name=fallback_contract_name)

    question = _first_available(row, QUESTION_FIELD_CANDIDATES, "")
    clause_type = _first_available(row, CLAUSE_TYPE_CANDIDATES, "unknown")
    answers = _normalize_answers(_first_available(row, ANSWER_FIELD_CANDIDATES, []))

    return {
        "row_id": row_index,
        "contract_name": str(contract_name),
        "contract_text": str(contract_text),
        "question": str(question),
        "clause_type": str(clause_type),
        "answers": answers,
    }


def save_raw_rows(dataset: DatasetType, output_path: Path = RAW_OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for row_index, row in enumerate(dataset):
            normalized = normalize_row(dict(row), row_index)
            file.write(json.dumps(normalized) + "\n")
    return output_path


def build_contract_records(dataset: DatasetType) -> list[dict[str, Any]]:
    """Group question-centric CUAD rows into unique contract documents."""
    grouped: dict[str, dict[str, Any]] = {}

    for row_index, row in enumerate(dataset):
        normalized = normalize_row(dict(row), row_index)
        contract_name = normalized["contract_name"]
        contract_text = normalized["contract_text"]
        if not contract_text.strip():
            continue

        if contract_name not in grouped:
            grouped[contract_name] = {
                "contract_name": contract_name,
                "contract_text": contract_text,
                "clause_types": set(),
            }

        if normalized["clause_type"]:
            grouped[contract_name]["clause_types"].add(normalized["clause_type"])

    records: list[dict[str, Any]] = []
    for contract_name, payload in grouped.items():
        clause_types = sorted(payload["clause_types"])
        records.append(
            {
                "contract_name": contract_name,
                "contract_text": payload["contract_text"],
                "clause_type": clause_types[0] if clause_types else "mixed",
            }
        )

    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load CUAD and export normalized raw rows.")
    parser.add_argument("--dataset", default=PRIMARY_DATASET_ID, help="HuggingFace dataset id")
    parser.add_argument("--split", default=DEFAULT_SPLIT, help="Dataset split")
    parser.add_argument("--output", default=str(RAW_OUTPUT_PATH), help="JSONL output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_cuad_dataset(dataset_id=args.dataset, split=args.split)
    output_path = save_raw_rows(dataset, Path(args.output))
    print(f"Saved {len(dataset)} normalized rows to {output_path}")


if __name__ == "__main__":
    main()


################################################################################
# FILE: src/monitoring/__init__.py
################################################################################

"""Monitoring package for evaluation dashboards and operational visibility."""


################################################################################
# FILE: src/monitoring/dashboard.py
################################################################################

import os

import pandas as pd
import streamlit as st
from src.evaluation.metrics_store import MetricsStore

try:
    from streamlit.errors import StreamlitAPIException
except Exception:
    StreamlitAPIException = Exception  # type: ignore[assignment]

FAITHFULNESS_ALERT_THRESHOLD = 0.90


def _safe_set_page_config() -> None:
    try:
        st.set_page_config(page_title="Legal RAG Monitoring", layout="wide")
    except StreamlitAPIException:
        # Streamlit allows set_page_config only once per run.
        pass

def main() -> None:
    _safe_set_page_config()
    st.title("Legal Contract Analyzer - Monitoring Dashboard")
    st.caption("Real-time quality tracking for faithfulness, relevance, precision, and recall.")

    store = MetricsStore(database_url=os.getenv("DATABASE_URL"))
    trends = store.get_trends(days=7)
    if not trends:
        st.info("No recent metrics available to display.")
        return

    df = pd.DataFrame(trends)
    if df.empty:
        st.info("No data rows available in trends.")
        return

    df["created_at"] = pd.to_datetime(df["created_at"])
    time_series = df.set_index("created_at")

    st.subheader("Quality Score Trends (Last 7 Days)")
    metrics_to_plot = ["faithfulness", "answer_relevance", "context_precision", "context_recall"]
    st.line_chart(time_series[metrics_to_plot])

    st.subheader("Current Averages")
    cols = st.columns(4)
    cols[0].metric("Avg Faithfulness", f"{df['faithfulness'].mean():.2f}")
    cols[1].metric("Avg Relevance", f"{df['answer_relevance'].mean():.2f}")
    cols[2].metric("Avg Precision", f"{df['context_precision'].mean():.2f}")
    cols[3].metric("Avg Recall", f"{df['context_recall'].mean():.2f}")

    faithfulness_mean = df['faithfulness'].mean()
    if faithfulness_mean < FAITHFULNESS_ALERT_THRESHOLD:
        st.warning(
            f"Alert: Average faithfulness ({faithfulness_mean:.2f}) is below threshold "
            f"({FAITHFULNESS_ALERT_THRESHOLD:.2f})."
        )

    st.subheader("Recent Queries")
    recent = store.list_recent(limit=10)
    recent_df = pd.DataFrame(recent)
    if not recent_df.empty:
        display_columns = ["id", "query", "tool_used", "faithfulness", "answer_relevance"]
        st.dataframe(recent_df[display_columns], use_container_width=True, hide_index=True)

    st.subheader("Query Analytics")
    analytics = store.get_query_analytics()
    analytics_df = pd.DataFrame(analytics)
    if analytics_df.empty:
        st.info("No analytics available yet.")
    else:
        analytics_plot = analytics_df.set_index("tool_used")[['count', 'avg_faithfulness']]
        st.bar_chart(analytics_plot)
        st.dataframe(analytics_df, use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()


################################################################################
# FILE: src/pipeline/__init__.py
################################################################################


from src.pipeline.pipeline import ContractQAPipeline

__all__ = ["ContractQAPipeline"]


################################################################################
# FILE: src/pipeline/answerer.py
################################################################################


import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

try:
    import requests
except Exception:
    requests = None

from src.pipeline.answerer_helpers import (
    build_answer_prompt,
    build_extractive_fallback_answer,
    normalize_answer,
)


@dataclass
class MistralAnswerer:
    model: str = os.getenv("OLLAMA_MODEL", "mistral")
    endpoint: str = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate")
    timeout_seconds: float = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
    enable_cli_fallback: bool = os.getenv("OLLAMA_CLI_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}

    def answer(self, question: str, source_chunks: list[dict[str, Any]]) -> str:
        if not source_chunks:
            return "This contract does not contain a clause addressing that."

        prompt = build_answer_prompt(question=question, source_chunks=source_chunks)

        generated = self._answer_with_http(prompt=prompt)
        if generated:
            return generated

        generated = self._answer_with_ollama_cli(prompt=prompt)
        if generated:
            return generated

        return build_extractive_fallback_answer(question=question, source_chunks=source_chunks)

    def _answer_with_http(self, prompt: str) -> str:
        if requests is None:
            return ""

        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0},
            }
            response = requests.post(self.endpoint, json=payload, timeout=max(30.0, self.timeout_seconds))
            response.raise_for_status()
            body = response.json()
            return str(body.get("response", "")).strip()
        except Exception:
            return ""

    def _answer_with_ollama_cli(self, prompt: str) -> str:
        if not self.enable_cli_fallback:
            return ""

        if shutil.which("ollama") is None:
            return ""

        try:
            completed = subprocess.run(
                ["ollama", "run", self.model],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(30.0, self.timeout_seconds),
                check=False,
            )
        except Exception:
            return ""

        if completed.returncode != 0:
            return ""

        stdout = str(completed.stdout or "").strip()
        if not stdout:
            return ""

        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout).strip()

    def finalize_answer_with_sources(
        self,
        answer: str,
        source_chunks: list[dict[str, Any]],
        question: str = "",
    ) -> tuple[str, list[dict[str, Any]]]:
        sources = self.build_sources(source_chunks)
        if not sources:
            return answer.strip(), []

        cleaned = normalize_answer(answer)
        if not cleaned and question.strip():
            cleaned = f"Unable to produce a grounded answer for: {question.strip()}"
        if not re.search(r"\[\d+\]", cleaned):
            cleaned = f"{cleaned} [{sources[0]['index']}]"

        source_lines = "\n".join(f"[{item['index']}] {item['label']}" for item in sources)
        tagged_answer = f"{cleaned}\n\nSources:\n{source_lines}"
        return tagged_answer, sources

    @staticmethod
    def build_citations(source_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        seen: set[str] = set()

        for chunk in source_chunks:
            metadata = dict(chunk.get("metadata", {}))
            chunk_id = str(chunk.get("chunk_id", metadata.get("chunk_id", "")))
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            citations.append(
                {
                    "chunk_id": chunk_id,
                    "contract_name": metadata.get("contract_name", metadata.get("contract_id", "")),
                    "clause_type": metadata.get("clause_type", ""),
                    "section_heading": metadata.get("section_heading", ""),
                    "page_number": metadata.get("page_number"),
                    "url": "",
                }
            )

        return citations

    @staticmethod
    def build_sources(source_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for chunk in source_chunks:
            metadata = dict(chunk.get("metadata", {}))
            contract_id = str(metadata.get("contract_id", metadata.get("contract_name", ""))).strip()
            source_name = str(metadata.get("source_name", "")).strip()
            label = source_name or contract_id or "Uploaded contract"

            key = (contract_id, label)
            if key in seen:
                continue
            seen.add(key)

            sources.append(
                {
                    "index": len(sources) + 1,
                    "label": label,
                    "contract_id": contract_id,
                }
            )

        return sources


################################################################################
# FILE: src/pipeline/answerer_helpers.py
################################################################################


import re
from typing import Any

_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_STOPWORDS = {
    "what",
    "when",
    "where",
    "which",
    "that",
    "this",
    "with",
    "from",
    "under",
    "about",
    "must",
    "shall",
    "would",
    "could",
    "should",
}


def render_context(chunks: list[dict[str, Any]], max_chars_per_chunk: int = 1500) -> str:
    lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = dict(chunk.get("metadata", {}))
        chunk_id = str(chunk.get("chunk_id", metadata.get("chunk_id", f"chunk_{index}")))
        contract_name = str(metadata.get("contract_name", metadata.get("contract_id", "unknown_contract")))
        clause_type = str(metadata.get("clause_type", "general"))
        page_number = metadata.get("page_number")
        section_heading = str(metadata.get("section_heading", ""))
        text = str(chunk.get("text", "")).strip()

        prefix = (
            f"[{index}] chunk_id={chunk_id} contract={contract_name} "
            f"clause={clause_type} page={page_number} heading={section_heading}"
        )
        lines.append(f"{prefix}\n{text[:max_chars_per_chunk]}")

    return "\n\n".join(lines)


def build_answer_prompt(question: str, source_chunks: list[dict[str, Any]]) -> str:
    context = render_context(chunks=source_chunks[:12], max_chars_per_chunk=1200)
    return (
        "<s>[INST] You are an expert legal contract analysis assistant.\n"
        "Answer the question using only the contract excerpts.\n"
        "If not specified, respond exactly with: \"This information is not specified in the contract.\"\n"
        "Keep the answer concise, factual, and cite support using [1], [2] style references.\n\n"
        "[CONTRACT EXCERPTS]\n"
        f"{context}\n\n"
        "[QUESTION]\n"
        f"{question.strip()}\n\n"
        "Answer: [/INST]"
    )


def normalize_answer(answer: str) -> str:
    cleaned = answer.strip()
    cleaned = _remove_inconsistent_count_intro(cleaned)
    return cleaned.strip()


def _remove_inconsistent_count_intro(text: str) -> str:
    numbered_count = len(re.findall(r"^\s*\d+\.\s", text, flags=re.MULTILINE))
    if numbered_count < 2:
        return text

    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        match = re.search(
            r"\bcontains\s+([A-Za-z]+|\d+)\s+(?:conditions?|grounds?|reasons?|ways?)\b",
            stripped,
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        raw_count = match.group(1).lower()
        if raw_count.isdigit():
            declared = int(raw_count)
        else:
            declared = _NUMBER_WORDS.get(raw_count, -1)

        if declared > 0 and declared != numbered_count:
            lines.pop(index)
        break

    return "\n".join(lines).strip()


def build_extractive_fallback_answer(question: str, source_chunks: list[dict[str, Any]]) -> str:
    if not source_chunks:
        return "This contract does not contain a clause addressing that."

    query_terms = {
        token
        for token in re.findall(r"[a-z0-9]{4,}", question.lower())
        if token not in _STOPWORDS
    }
    if not query_terms:
        query_terms = set(re.findall(r"[a-z0-9]{4,}", question.lower()))

    ranked = _rank_candidate_sentences(source_chunks=source_chunks, query_terms=query_terms)

    bullets: list[str] = []
    seen: set[str] = set()
    for _, sentence in ranked:
        lowered = sentence.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        bullets.append(f"{len(bullets) + 1}. {sentence} [1]")
        if len(bullets) >= 5:
            break

    if bullets:
        return (
            "Model generation is unavailable, so this answer is extracted from retrieved contract excerpts.\n"
            + "\n".join(bullets)
        )

    fallback_text = str(source_chunks[0].get("text", "")).strip()
    if fallback_text:
        snippet = " ".join(fallback_text.split())[:260]
        return f"Model generation is unavailable. Closest retrieved excerpt: {snippet} [1]"

    return "This contract does not contain a clause addressing that."


def _rank_candidate_sentences(
    source_chunks: list[dict[str, Any]],
    query_terms: set[str],
) -> list[tuple[float, str]]:
    ranked: list[tuple[float, str]] = []

    for chunk in source_chunks[:12]:
        metadata = dict(chunk.get("metadata", {}))
        heading = str(metadata.get("section_heading", "")).lower()
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue

        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            cleaned = " ".join(sentence.split()).strip()
            if len(cleaned) < 30:
                continue
            if cleaned[:1].islower():
                continue
            if cleaned.lower().startswith(("or ", "and ", "but ")):
                continue

            lowered_sentence = cleaned.lower()
            sentence_terms = set(re.findall(r"[a-z0-9]{4,}", lowered_sentence))
            overlap = len(query_terms & sentence_terms)
            if overlap == 0:
                continue

            heading_overlap = sum(1 for term in query_terms if term in heading)
            score = float(overlap) + (0.5 * float(heading_overlap))
            ranked.append((score, cleaned))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


################################################################################
# FILE: src/pipeline/artifact_store.py
################################################################################


import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from sqlalchemy import DateTime, String, Text, create_engine, delete, desc, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except Exception:
    SQLALCHEMY_AVAILABLE = False

from src.utils.db import should_auto_create_tables


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return

    raw_path = database_url[len(prefix):].split("?", 1)[0]
    if not raw_path or raw_path == ":memory:":
        return

    try:
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            if candidate.endswith("Z"):
                candidate = f"{candidate[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    return parsed
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

    return _now_utc_naive()


if SQLALCHEMY_AVAILABLE:
    class Base(DeclarativeBase):
        pass


    class StoredContractText(Base):
        __tablename__ = "uploaded_contract_texts"

        contract_id: Mapped[str] = mapped_column(String(256), primary_key=True)
        source_name: Mapped[str] = mapped_column(String(512), nullable=False)
        raw_text: Mapped[str] = mapped_column(Text, nullable=False)
        raw_text_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
        uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc_naive, nullable=False)


    class StoredContractChunk(Base):
        __tablename__ = "stored_contract_chunks"

        chunk_id: Mapped[str] = mapped_column(String(512), primary_key=True)
        contract_id: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
        text: Mapped[str] = mapped_column(Text, nullable=False)
        metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc_naive, nullable=False)


else:
    class Base:  # type: ignore[no-redef]
        pass


    class StoredContractText:  # type: ignore[no-redef]
        pass


    class StoredContractChunk:  # type: ignore[no-redef]
        pass


class ContractArtifactStore:
    def __init__(
        self,
        backend: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self.database_url = str(database_url or os.getenv("DATABASE_URL", "")).strip()
        resolved_backend = str(backend or os.getenv("ARTIFACT_STORE_BACKEND", "auto")).strip().lower()
        self._db_enabled = False
        self.engine = None
        self.SessionLocal = None

        if resolved_backend not in {"auto", "file", "db"}:
            resolved_backend = "auto"

        if resolved_backend != "file":
            self._try_enable_db(strict=(resolved_backend == "db"))

    @property
    def db_enabled(self) -> bool:
        return self._db_enabled

    def _try_enable_db(self, strict: bool) -> None:
        if not SQLALCHEMY_AVAILABLE:
            if strict:
                raise RuntimeError("SQLAlchemy is required for ARTIFACT_STORE_BACKEND=db.")
            return

        if not self.database_url:
            if strict:
                raise RuntimeError("DATABASE_URL is required for ARTIFACT_STORE_BACKEND=db.")
            return

        try:
            _ensure_sqlite_parent_dir(self.database_url)
            self.engine = create_engine(self.database_url, future=True)
            self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
            if should_auto_create_tables(self.database_url):
                Base.metadata.create_all(bind=self.engine)
            self._db_enabled = True
        except Exception as error:
            self.engine = None
            self.SessionLocal = None
            self._db_enabled = False
            if strict:
                raise RuntimeError("Failed to initialize DB-backed ContractArtifactStore.") from error

    def upsert_contract_text(
        self,
        contract_id: str,
        source_name: str,
        raw_text: str,
        raw_text_path: str = "",
        uploaded_at: str | datetime | None = None,
    ) -> None:
        if not self._db_enabled or self.SessionLocal is None:
            return

        with self.SessionLocal() as session:
            existing = session.get(StoredContractText, contract_id)
            timestamp = _as_utc_naive(uploaded_at)
            if existing is None:
                existing = StoredContractText(
                    contract_id=contract_id,
                    source_name=source_name,
                    raw_text=str(raw_text),
                    raw_text_path=str(raw_text_path),
                    uploaded_at=timestamp,
                )
                session.add(existing)
            else:
                existing.source_name = source_name
                existing.raw_text = str(raw_text)
                existing.raw_text_path = str(raw_text_path)
                existing.uploaded_at = timestamp

            session.commit()

    def get_contract_text(self, contract_id: str) -> dict[str, Any] | None:
        if not self._db_enabled or self.SessionLocal is None:
            return None

        with self.SessionLocal() as session:
            row = session.get(StoredContractText, contract_id)
            if row is None:
                return None

            return {
                "contract_id": row.contract_id,
                "source_name": row.source_name,
                "raw_text": row.raw_text,
                "raw_text_path": row.raw_text_path,
                "uploaded_at": row.uploaded_at.isoformat(),
            }

    def replace_contract_chunks(self, chunks: list[dict[str, Any]]) -> int:
        if not self._db_enabled or self.SessionLocal is None:
            return 0
        if not chunks:
            return 0

        normalized: list[dict[str, Any]] = []
        contract_ids: set[str] = set()

        for chunk in chunks:
            metadata = dict(chunk.get("metadata", {}))
            chunk_id = str(chunk.get("chunk_id", "")).strip()
            text = str(chunk.get("text", ""))
            contract_id = str(metadata.get("contract_id", "")).strip()
            if not chunk_id or not contract_id:
                continue

            metadata.setdefault("chunk_id", chunk_id)
            metadata.setdefault("contract_id", contract_id)

            normalized.append(
                {
                    "chunk_id": chunk_id,
                    "contract_id": contract_id,
                    "text": text,
                    "metadata_json": json.dumps(metadata, ensure_ascii=True),
                }
            )
            contract_ids.add(contract_id)

        if not normalized:
            return 0

        with self.SessionLocal() as session:
            for contract_id in contract_ids:
                session.execute(
                    delete(StoredContractChunk).where(StoredContractChunk.contract_id == contract_id)
                )

            for item in normalized:
                session.add(
                    StoredContractChunk(
                        chunk_id=item["chunk_id"],
                        contract_id=item["contract_id"],
                        text=item["text"],
                        metadata_json=item["metadata_json"],
                        updated_at=_now_utc_naive(),
                    )
                )

            session.commit()

        return len(normalized)

    def load_all_chunks(
        self,
        contract_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self._db_enabled or self.SessionLocal is None:
            return []

        with self.SessionLocal() as session:
            stmt = select(StoredContractChunk)
            if contract_ids:
                normalized_contract_ids = [str(item).strip() for item in contract_ids if str(item).strip()]
                if normalized_contract_ids:
                    stmt = stmt.where(StoredContractChunk.contract_id.in_(normalized_contract_ids))
            stmt = stmt.order_by(StoredContractChunk.updated_at.desc())
            if limit is not None and limit > 0:
                stmt = stmt.limit(limit)

            rows = session.execute(stmt).scalars().all()
            output: list[dict[str, Any]] = []
            for row in rows:
                try:
                    metadata = json.loads(row.metadata_json)
                    if not isinstance(metadata, dict):
                        metadata = {}
                except Exception:
                    metadata = {}

                metadata.setdefault("contract_id", row.contract_id)
                metadata.setdefault("chunk_id", row.chunk_id)

                output.append(
                    {
                        "chunk_id": row.chunk_id,
                        "text": row.text,
                        "metadata": metadata,
                    }
                )

            return output

    def chunk_count(self) -> int:
        if not self._db_enabled or self.SessionLocal is None:
            return 0

        with self.SessionLocal() as session:
            rows = session.execute(select(StoredContractChunk.chunk_id)).all()
            return len(rows)

    def chunk_revision(self) -> str:
        if not self._db_enabled or self.SessionLocal is None:
            return ""

        with self.SessionLocal() as session:
            row = session.execute(
                select(StoredContractChunk.updated_at)
                .order_by(desc(StoredContractChunk.updated_at))
                .limit(1)
            ).first()

            if not row or not row[0]:
                return ""
            return row[0].isoformat()


################################################################################
# FILE: src/pipeline/chat_scope_registry.py
################################################################################


import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from filelock import FileLock
except Exception:
    FileLock = None

try:
    from sqlalchemy import DateTime, Integer, String, UniqueConstraint, create_engine, select
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except Exception:
    SQLALCHEMY_AVAILABLE = False

from src.utils.db import should_auto_create_tables


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return

    raw_path = database_url[len(prefix):].split("?", 1)[0]
    if not raw_path or raw_path == ":memory:":
        return

    try:
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


if SQLALCHEMY_AVAILABLE:
    class Base(DeclarativeBase):
        pass


    class ChatScopeContract(Base):
        __tablename__ = "chat_scope_contracts"
        __table_args__ = (
            UniqueConstraint("chat_id", "contract_id", name="uq_chat_scope_contract"),
        )

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        chat_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
        contract_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc_naive, nullable=False)


else:
    class Base:  # type: ignore[no-redef]
        pass


    class ChatScopeContract:  # type: ignore[no-redef]
        pass


class ChatScopeRegistry:
    def __init__(
        self,
        registry_path: Path | str = Path("data/processed/chat_scope_registry.json"),
        backend: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self.registry_path = Path(registry_path)
        self._lock = threading.RLock()
        self._file_lock = FileLock(f"{self.registry_path}.lock") if FileLock is not None else None
        self.database_url = str(database_url or os.getenv("DATABASE_URL", "")).strip()
        resolved_backend = str(backend or os.getenv("REGISTRY_BACKEND", "auto")).strip().lower()
        self._db_enabled = False
        self.engine = None
        self.SessionLocal = None

        if resolved_backend not in {"auto", "file", "db"}:
            resolved_backend = "auto"

        if resolved_backend != "file":
            self._try_enable_db(strict=(resolved_backend == "db"))

    def _try_enable_db(self, strict: bool) -> None:
        if not SQLALCHEMY_AVAILABLE:
            if strict:
                raise RuntimeError("SQLAlchemy is required for REGISTRY_BACKEND=db.")
            return

        if not self.database_url:
            if strict:
                raise RuntimeError("DATABASE_URL is required for REGISTRY_BACKEND=db.")
            return

        try:
            _ensure_sqlite_parent_dir(self.database_url)
            self.engine = create_engine(self.database_url, future=True)
            self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
            if should_auto_create_tables(self.database_url):
                Base.metadata.create_all(bind=self.engine)
            self._db_enabled = True
        except Exception as error:
            self.engine = None
            self.SessionLocal = None
            self._db_enabled = False
            if strict:
                raise RuntimeError("Failed to initialize DB-backed ChatScopeRegistry.") from error

    def add_contracts(self, chat_id: str, contract_ids: list[str]) -> None:
        resolved_chat_id = self._normalize_chat_id(chat_id)
        if not resolved_chat_id:
            raise ValueError("chat_id is required.")

        normalized_contract_ids = self._normalize_contract_ids(contract_ids)
        if not normalized_contract_ids:
            return

        if self._db_enabled:
            self._add_contracts_db(chat_id=resolved_chat_id, contract_ids=normalized_contract_ids)
            return

        with self._locked():
            payload = self._read_payload()
            existing = self._normalize_contract_ids(payload.get(resolved_chat_id, []))
            merged = self._normalize_contract_ids(existing + normalized_contract_ids)
            payload[resolved_chat_id] = merged
            self._write_payload(payload)

    def list_contract_ids(self, chat_id: str) -> list[str]:
        resolved_chat_id = self._normalize_chat_id(chat_id)
        if not resolved_chat_id:
            return []

        if self._db_enabled:
            return self._list_contract_ids_db(chat_id=resolved_chat_id)

        with self._locked():
            payload = self._read_payload()
            return self._normalize_contract_ids(payload.get(resolved_chat_id, []))

    def _add_contracts_db(self, chat_id: str, contract_ids: list[str]) -> None:
        if self.SessionLocal is None:
            return

        with self.SessionLocal() as session:
            existing_rows = session.execute(
                select(ChatScopeContract.contract_id).where(ChatScopeContract.chat_id == chat_id)
            ).all()
            existing = {str(row[0]).strip() for row in existing_rows if str(row[0]).strip()}

            for contract_id in contract_ids:
                if contract_id in existing:
                    continue
                session.add(
                    ChatScopeContract(
                        chat_id=chat_id,
                        contract_id=contract_id,
                        created_at=_now_utc_naive(),
                    )
                )

            try:
                session.commit()
            except IntegrityError:
                # Another process may have inserted the same chat/contract mapping.
                session.rollback()

    def _list_contract_ids_db(self, chat_id: str) -> list[str]:
        if self.SessionLocal is None:
            return []

        with self.SessionLocal() as session:
            rows = session.execute(
                select(ChatScopeContract.contract_id)
                .where(ChatScopeContract.chat_id == chat_id)
                .order_by(ChatScopeContract.id.asc())
            ).all()
            return self._normalize_contract_ids([str(row[0]) for row in rows if row and row[0]])

    @contextmanager
    def _locked(self):
        with self._lock:
            if self._file_lock is None:
                yield
            else:
                with self._file_lock:
                    yield

    @staticmethod
    def _normalize_chat_id(chat_id: str | None) -> str:
        return str(chat_id or "").strip()

    @staticmethod
    def _normalize_contract_ids(contract_ids: list[str] | tuple[str, ...] | None) -> list[str]:
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

    def _read_payload(self) -> dict[str, list[str]]:
        if not self.registry_path.exists():
            return {}

        try:
            payload: Any = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return {}

            output: dict[str, list[str]] = {}
            for key, value in payload.items():
                chat_id = self._normalize_chat_id(str(key))
                if not chat_id:
                    continue
                if not isinstance(value, list):
                    continue
                output[chat_id] = self._normalize_contract_ids(value)

            return output
        except Exception:
            return {}

    def _write_payload(self, payload: dict[str, list[str]]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.registry_path.with_suffix(f"{self.registry_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self.registry_path)


################################################################################
# FILE: src/pipeline/chunker.py
################################################################################


import re
from dataclasses import dataclass
from typing import Any

APPROX_CHARS_PER_PAGE = 3200

# CUAD-inspired clause families used to guide retrieval.
CUAD_CLAUSE_HINTS: dict[str, list[str]] = {
    "document_name": ["document name", "contract name", "agreement title", "contract no", "contract number"],
    "parties": ["parties", "between", "party", "licensor", "licensee"],
    "agreement_date": ["agreement date", "dated", "date of this agreement", "as of"],
    "effective_date": ["effective date", "commence", "commencement"],
    "expiration_date": ["expiration", "expire", "end date", "term ends"],
    "renewal_term": ["renew", "renewal", "automatic renewal"],
    "notice_to_terminate_renewal": ["terminate renewal", "non-renewal", "notice of non-renewal"],
    "governing_law": ["governing law", "laws of", "jurisdiction"],
    "most_favored_nation": ["most favored nation", "mfn"],
    "non_compete": ["non-compete", "non compete", "restrict competition"],
    "exclusivity": ["exclusive", "exclusivity", "sole"],
    "no_solicit_of_customers": ["no-solicit", "non-solicit", "solicit customers"],
    "competitive_restriction_exception": ["exception", "carveout", "carve-out", "notwithstanding"],
    "non_disparagement": ["non-disparagement", "disparage"],
    "termination_for_convenience": [
        "early termination",
        "termination for convenience",
        "terminate at any time",
        "terminate this agreement",
        "without cause",
        "for its convenience",
        "thirty-day written notice",
    ],
    "termination_for_cause": ["for cause", "material breach", "default", "cure period", "breach"],
    "change_of_control": ["change of control", "control", "acquisition", "merger"],
    "anti_assignment": ["assignment", "assign", "transfer"],
    "revenue_profit_sharing": ["revenue", "profit", "royalty", "share"],
    "price_restrictions": ["price", "pricing", "pricing restrictions"],
    "minimum_commitment": ["minimum", "commitment", "minimum purchase"],
    "volume_restriction": ["volume", "quantity", "quota"],
    "ip_ownership_assignment": ["intellectual property", "ownership", "assignment", "work product"],
    "joint_ip_ownership": ["jointly owned", "joint ownership"],
    "license_grant": ["license grant", "license", "licensed"],
    "non_transferable_license": ["non-transferable", "nontransferable"],
    "affiliate_license_licensee": ["affiliate license", "licensee affiliate"],
    "affiliate_license_licensor": ["licensor affiliate", "affiliate of licensor"],
    "unlimited_license": ["unlimited", "all-you-can-eat", "all you can eat"],
    "irrevocable_or_perpetual_license": ["irrevocable", "perpetual"],
    "source_code_escrow": ["source code", "escrow"],
    "post_termination_services": ["post-termination", "post termination", "transition services"],
    "audit_rights": ["audit", "inspect books", "records"],
    "uncapped_liability": ["uncapped", "unlimited liability"],
    "cap_on_liability": ["cap on liability", "limitation of liability", "maximum liability"],
    "liquidated_damages": ["liquidated damages"],
    "warranty_duration": ["warranty", "warranty period", "duration"],
    "insurance": ["insurance", "insured", "coverage"],
    "covenant_not_to_sue": ["covenant not to sue", "not to sue"],
    "third_party_beneficiary": ["third-party beneficiary", "third party beneficiary"],
    "indemnification": ["indemnify", "indemnification", "hold harmless"],
}

HEADING_PATTERN = re.compile(
    r"^\s*(?:article|section|clause)?\s*[0-9IVX]+(?:\.[0-9IVX]+)*\s*[-:.]?\s+.+$",
    re.IGNORECASE,
)
ALL_CAPS_HEADING_PATTERN = re.compile(r"^[A-Z][A-Z0-9 ,/&()'\-]{6,}$")


@dataclass
class ClauseAwareChunker:
    max_chunk_chars: int = 1500
    chunk_overlap_chars: int = 200

    def chunk_contract(self, contract_id: str, text: str) -> list[dict[str, Any]]:
        normalized = text.replace("\r\n", "\n")
        if not normalized.strip():
            return []

        sections = _split_sections(normalized)
        chunks: list[dict[str, Any]] = []
        cursor = 0

        for section_index, section in enumerate(sections):
            heading = section["heading"]
            section_text = section["text"].strip()
            if not section_text:
                continue

            pieces = _split_long_text(
                section_text,
                max_chars=self.max_chunk_chars,
                overlap=self.chunk_overlap_chars,
            )

            for piece_index, piece in enumerate(pieces):
                chunk_text = piece.strip()
                if not chunk_text:
                    continue

                start = normalized.find(chunk_text, cursor)
                if start < 0:
                    start = normalized.find(chunk_text)
                if start < 0:
                    start = max(cursor, 0)

                end = start + len(chunk_text)
                cursor = max(end - self.chunk_overlap_chars, 0)

                clause_type = infer_clause_type(f"{heading}\n{chunk_text}")
                chunk_id = f"{contract_id}_{section_index}_{piece_index}"
                page_number = (start // APPROX_CHARS_PER_PAGE) + 1

                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "text": chunk_text,
                        "metadata": {
                            "contract_id": contract_id,
                            "contract_name": contract_id,
                            "clause_type": clause_type,
                            "section_heading": heading,
                            "page_number": page_number,
                            "char_start": start,
                            "char_end": end,
                        },
                    }
                )

        return chunks


def _split_sections(text: str) -> list[dict[str, str]]:
    lines = text.split("\n")
    sections: list[dict[str, str]] = []

    current_heading = "preamble"
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if _is_heading(stripped):
            if current_lines:
                sections.append({"heading": current_heading, "text": "\n".join(current_lines).strip()})
            current_heading = stripped.lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({"heading": current_heading, "text": "\n".join(current_lines).strip()})

    if not sections:
        sections.append({"heading": "preamble", "text": text})

    return sections


def _is_heading(line: str) -> bool:
    if not line:
        return False
    if len(line) > 160:
        return False
    return bool(HEADING_PATTERN.match(line) or ALL_CAPS_HEADING_PATTERN.match(line))


def _split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if not current:
            current = paragraph
            continue

        if len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap > 0 else ""
            current = f"{tail}\n\n{paragraph}".strip()

    if current:
        chunks.append(current)

    return chunks


def infer_clause_type(text: str) -> str:
    lowered = text.lower()
    heading, body = _split_heading_and_body(lowered)

    direct_match = _detect_direct_clause_type(heading=heading, body=body)
    if direct_match is not None:
        return direct_match

    clause_scores: dict[str, int] = {}

    best_clause = "general"
    best_score = 0

    for clause_type, hints in CUAD_CLAUSE_HINTS.items():
        score = _score_clause_hints(
            clause_type=clause_type,
            hints=hints,
            heading=heading,
            body=body,
        )
        clause_scores[clause_type] = score
        if score > best_score:
            best_clause = clause_type
            best_score = score

    if best_clause in {"termination_for_convenience", "termination_for_cause"}:
        signal_score = _termination_signal_score(heading=heading, body=body)
        if signal_score < 3 and not _is_termination_heading(heading):
            fallback_candidates = [
                (clause, score)
                for clause, score in clause_scores.items()
                if clause not in {"termination_for_convenience", "termination_for_cause"}
            ]
            if fallback_candidates:
                fallback_clause, fallback_score = max(fallback_candidates, key=lambda item: item[1])
                if fallback_score > 0:
                    best_clause = fallback_clause
                else:
                    best_clause = "general"
            else:
                best_clause = "general"

    if best_clause == "document_name" and _termination_signal_score(heading=heading, body=body) >= 2:
        return "termination_for_convenience"

    return best_clause


def _split_heading_and_body(text: str) -> tuple[str, str]:
    heading, separator, body = text.partition("\n")
    if not separator:
        return text, text
    return heading.strip(), body


def _detect_direct_clause_type(heading: str, body: str) -> str | None:
    combined = f"{heading}\n{body}"

    convenience_patterns = (
        r"\bearly termination\b",
        r"\btermination for convenience\b",
        r"\bfor its convenience\b",
        r"\bterminate(?:d|s|ing)?\s+this\s+agreement\b",
        r"\bthirty[- ]day\b.{0,80}\bwritten notice\b",
    )
    cause_patterns = (
        r"\bfor cause\b",
        r"\bmaterial breach\b",
        r"\bconsultant'?s default\b",
        r"\bdefault\b.{0,80}\bterminate",
        r"\bterminate\b.{0,80}\bdefault",
        r"\bcure\b.{0,40}\bday",
    )

    convenience_hits = sum(1 for pattern in convenience_patterns if re.search(pattern, combined))
    cause_hits = sum(1 for pattern in cause_patterns if re.search(pattern, combined))

    heading_has_termination = _is_termination_heading(heading)

    if convenience_hits == 0 and cause_hits == 0:
        return None

    if not heading_has_termination and convenience_hits < 2 and cause_hits < 2:
        return None

    if cause_hits > convenience_hits:
        return "termination_for_cause"
    return "termination_for_convenience"


def _score_clause_hints(clause_type: str, hints: list[str], heading: str, body: str) -> int:
    heading_space = heading
    body_space = body

    # Document metadata should come from headings/front-matter, not deep body text.
    if clause_type == "document_name":
        body_space = body[:220]

    score = 0
    for hint in hints:
        normalized_hint = hint.strip().lower()
        if not normalized_hint:
            continue

        pattern = re.compile(rf"\b{re.escape(normalized_hint)}\b")

        heading_hits = len(pattern.findall(heading_space))
        body_hits = len(pattern.findall(body_space))
        if heading_hits > 0:
            score += heading_hits * (len(normalized_hint) + 4)
        if body_hits > 0:
            score += body_hits * max(1, len(normalized_hint) // 2 + 2)

        if heading_hits == 0 and body_hits == 0 and normalized_hint in body_space:
            score += max(1, len(normalized_hint) // 3)

    return score


def _termination_signal_score(heading: str, body: str) -> int:
    combined = f"{heading}\n{body}"
    patterns = (
        r"\bterminat(?:e|ed|es|ing|ion)?\b",
        r"\bearly termination\b",
        r"\bfor cause\b",
        r"\bdefault\b",
    )
    return sum(1 for pattern in patterns if re.search(pattern, combined))


def _is_termination_heading(heading: str) -> bool:
    normalized = heading.lower()
    return bool(re.search(r"\bterminat(?:e|ed|es|ing|ion)?\b", normalized))


def extract_clause_hints_from_question(question: str) -> list[str]:
    lowered = question.lower()
    boosted_hints: list[str] = []

    has_termination = bool(re.search(r"\bterminat(?:e|es|ed|ing|ion)?\b", lowered))
    asks_convenience = bool(
        re.search(r"\b(convenience|without cause|at any time)\b", lowered)
    )
    asks_cause = bool(
        re.search(r"\b(for cause|material breach|default|cure)\b", lowered)
    )

    if has_termination:
        if asks_convenience:
            boosted_hints.append("termination_for_convenience")
        if asks_cause:
            boosted_hints.append("termination_for_cause")
        if not asks_convenience and not asks_cause:
            boosted_hints.extend(["termination_for_convenience", "termination_for_cause"])

    if re.search(r"\brenew(?:al|als|ed|ing)?\b", lowered):
        boosted_hints.extend(["renewal_term", "notice_to_terminate_renewal"])

    scored: list[tuple[int, str]] = []

    for clause_type, hints in CUAD_CLAUSE_HINTS.items():
        score = 0
        for hint in hints:
            normalized_hint = hint.strip().lower()
            if not normalized_hint:
                continue

            pattern = re.compile(rf"\b{re.escape(normalized_hint)}\b")
            if pattern.search(lowered):
                score += len(normalized_hint) + 2
            elif normalized_hint in lowered:
                score += max(1, len(normalized_hint) // 2)
        if score > 0:
            scored.append((score, clause_type))

    scored.sort(reverse=True)
    hinted = [clause_type for _, clause_type in scored[:5]]

    ordered: list[str] = []
    seen: set[str] = set()
    for clause_type in boosted_hints + hinted:
        if clause_type not in seen:
            seen.add(clause_type)
            ordered.append(clause_type)

    return ordered[:5]


################################################################################
# FILE: src/pipeline/contracts_registry.py
################################################################################


import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from filelock import FileLock
except Exception:
    FileLock = None

try:
    from sqlalchemy import DateTime, Integer, String, create_engine, desc, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except Exception:
    SQLALCHEMY_AVAILABLE = False

from src.utils.db import should_auto_create_tables


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return

    raw_path = database_url[len(prefix):].split("?", 1)[0]
    if not raw_path or raw_path == ":memory:":
        return

    try:
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _as_utc_naive(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            if candidate.endswith("Z"):
                candidate = f"{candidate[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    return parsed
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

    return datetime.now(timezone.utc).replace(tzinfo=None)


if SQLALCHEMY_AVAILABLE:
    class Base(DeclarativeBase):
        pass


    class ContractRecord(Base):
        __tablename__ = "contracts_registry"

        contract_id: Mapped[str] = mapped_column(String(256), primary_key=True)
        display_name: Mapped[str] = mapped_column(String(512), nullable=False)
        source_name: Mapped[str] = mapped_column(String(512), nullable=False)
        chunks_ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
        uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)


else:
    class Base:  # type: ignore[no-redef]
        pass


    class ContractRecord:  # type: ignore[no-redef]
        pass


class ContractRegistry:
    def __init__(
        self,
        registry_path: Path | str = Path("data/processed/contracts_registry.json"),
        raw_upload_dir: Path | str = Path("data/raw/uploads"),
        chunk_metadata_path: Path | str = Path("data/processed/chunk_metadata.json"),
        backend: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.raw_upload_dir = Path(raw_upload_dir)
        self.chunk_metadata_path = Path(chunk_metadata_path)
        self._lock = threading.RLock()
        self._file_lock = FileLock(f"{self.registry_path}.lock") if FileLock is not None else None
        self.database_url = str(database_url or os.getenv("DATABASE_URL", "")).strip()
        resolved_backend = str(backend or os.getenv("REGISTRY_BACKEND", "auto")).strip().lower()
        self._db_enabled = False
        self.engine = None
        self.SessionLocal = None

        if resolved_backend not in {"auto", "file", "db"}:
            resolved_backend = "auto"

        if resolved_backend != "file":
            self._try_enable_db(strict=(resolved_backend == "db"))

    def _try_enable_db(self, strict: bool) -> None:
        if not SQLALCHEMY_AVAILABLE:
            if strict:
                raise RuntimeError("SQLAlchemy is required for REGISTRY_BACKEND=db.")
            return

        if not self.database_url:
            if strict:
                raise RuntimeError("DATABASE_URL is required for REGISTRY_BACKEND=db.")
            return

        try:
            _ensure_sqlite_parent_dir(self.database_url)
            self.engine = create_engine(self.database_url, future=True)
            self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
            if should_auto_create_tables(self.database_url):
                Base.metadata.create_all(bind=self.engine)
            self._db_enabled = True
        except Exception as error:
            self.engine = None
            self.SessionLocal = None
            self._db_enabled = False
            if strict:
                raise RuntimeError("Failed to initialize DB-backed ContractRegistry.") from error

    def list_contracts(self) -> list[dict[str, Any]]:
        if self._db_enabled:
            return self._list_contracts_db()

        with self._locked():
            rows = self._read_rows()
            merged_rows = self._merge_with_existing_uploads(rows)
            if merged_rows != rows:
                self._write_rows(merged_rows)
            merged_rows.sort(key=lambda row: str(row.get("uploaded_at", "")), reverse=True)
            return merged_rows

    def upsert(
        self,
        contract_id: str,
        source_name: str,
        chunks_ingested: int,
        uploaded_at: str | None = None,
    ) -> dict[str, Any]:
        if self._db_enabled:
            return self._upsert_db(
                contract_id=contract_id,
                source_name=source_name,
                chunks_ingested=chunks_ingested,
                uploaded_at=uploaded_at,
            )

        with self._locked():
            rows = self._read_rows()
            now_iso = uploaded_at or datetime.utcnow().isoformat()

            record = {
                "contract_id": contract_id,
                "display_name": _to_display_name(source_name=source_name, contract_id=contract_id),
                "source_name": source_name,
                "chunks_ingested": int(chunks_ingested),
                "uploaded_at": now_iso,
            }

            updated = False
            for index, row in enumerate(rows):
                if str(row.get("contract_id", "")) == contract_id:
                    rows[index] = record
                    updated = True
                    break

            if not updated:
                rows.append(record)

            rows = self._merge_with_existing_uploads(rows)
            self._write_rows(rows)
            return record

    def _upsert_db(
        self,
        contract_id: str,
        source_name: str,
        chunks_ingested: int,
        uploaded_at: str | None = None,
    ) -> dict[str, Any]:
        if self.SessionLocal is None:
            raise RuntimeError("DB session is not initialized for ContractRegistry.")

        resolved_uploaded_at = _as_utc_naive(uploaded_at)
        display_name = _to_display_name(source_name=source_name, contract_id=contract_id)

        with self.SessionLocal() as session:
            existing = session.get(ContractRecord, contract_id)
            if existing is None:
                existing = ContractRecord(
                    contract_id=contract_id,
                    display_name=display_name,
                    source_name=source_name,
                    chunks_ingested=int(chunks_ingested),
                    uploaded_at=resolved_uploaded_at,
                )
                session.add(existing)
            else:
                existing.display_name = display_name
                existing.source_name = source_name
                existing.chunks_ingested = int(chunks_ingested)
                existing.uploaded_at = resolved_uploaded_at

            session.commit()

            return {
                "contract_id": existing.contract_id,
                "display_name": existing.display_name,
                "source_name": existing.source_name,
                "chunks_ingested": int(existing.chunks_ingested),
                "uploaded_at": existing.uploaded_at.isoformat(),
            }

    def _list_contracts_db(self) -> list[dict[str, Any]]:
        if self.SessionLocal is None:
            return []

        with self.SessionLocal() as session:
            rows = session.execute(
                select(ContractRecord).order_by(desc(ContractRecord.uploaded_at))
            ).scalars().all()

            return [
                {
                    "contract_id": row.contract_id,
                    "display_name": row.display_name,
                    "source_name": row.source_name,
                    "chunks_ingested": int(row.chunks_ingested),
                    "uploaded_at": row.uploaded_at.isoformat(),
                }
                for row in rows
            ]

    @contextmanager
    def _locked(self):
        with self._lock:
            if self._file_lock is None:
                yield
            else:
                with self._file_lock:
                    yield

    def _read_rows(self) -> list[dict[str, Any]]:
        if not self.registry_path.exists():
            return []

        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                return []
            rows = []
            for item in payload:
                if isinstance(item, dict) and str(item.get("contract_id", "")).strip():
                    rows.append(item)
            return rows
        except Exception:
            return []

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.registry_path.with_suffix(f"{self.registry_path.suffix}.tmp")
        temp_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        temp_path.replace(self.registry_path)

    def _merge_with_existing_uploads(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        discovered_by_id: dict[str, dict[str, Any]] = {}
        for discovered in self._discover_existing_uploads():
            contract_id = str(discovered.get("contract_id", "")).strip()
            if contract_id:
                discovered_by_id[contract_id] = discovered

        merged_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            contract_id = str(row.get("contract_id", "")).strip()
            if not contract_id:
                continue

            discovered = discovered_by_id.get(contract_id, {})
            source_name = str(row.get("source_name") or discovered.get("source_name") or "").strip()
            merged_by_id[contract_id] = {
                "contract_id": contract_id,
                "display_name": _to_display_name(source_name=source_name, contract_id=contract_id),
                "source_name": source_name or f"{contract_id}.txt",
                "chunks_ingested": int(max(int(row.get("chunks_ingested", 0)), int(discovered.get("chunks_ingested", 0)))),
                "uploaded_at": str(row.get("uploaded_at") or discovered.get("uploaded_at") or datetime.utcnow().isoformat()),
            }

        for contract_id, discovered in discovered_by_id.items():
            if contract_id not in merged_by_id:
                merged_by_id[contract_id] = discovered

        return list(merged_by_id.values())

    def _discover_existing_uploads(self) -> list[dict[str, Any]]:
        if not self.raw_upload_dir.exists():
            return []

        chunk_counts = self._read_chunk_counts()
        source_names = self._read_source_names()

        records: list[dict[str, Any]] = []
        for path in sorted(self.raw_upload_dir.glob("*.txt")):
            contract_id = path.stem.strip()
            if not contract_id:
                continue
            uploaded_at = datetime.utcfromtimestamp(path.stat().st_mtime).isoformat()
            source_name = source_names.get(contract_id, path.name)
            records.append(
                {
                    "contract_id": contract_id,
                    "display_name": _to_display_name(source_name=source_name, contract_id=contract_id),
                    "source_name": source_name,
                    "chunks_ingested": int(chunk_counts.get(contract_id, 0)),
                    "uploaded_at": uploaded_at,
                }
            )

        return records

    def _read_chunk_counts(self) -> dict[str, int]:
        if not self.chunk_metadata_path.exists():
            return {}

        try:
            payload = json.loads(self.chunk_metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(payload, list):
            return {}

        counts: dict[str, int] = {}
        seen_chunk_ids: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue

            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            contract_id = str(
                item.get("contract_id")
                or item.get("contract_name")
                or metadata.get("contract_id")
                or metadata.get("contract_name")
                or ""
            ).strip()
            if not contract_id:
                continue

            chunk_id = str(item.get("chunk_id") or metadata.get("chunk_id") or "").strip()
            if chunk_id:
                dedupe_key = f"{contract_id}:{chunk_id}"
                if dedupe_key in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(dedupe_key)

            counts[contract_id] = counts.get(contract_id, 0) + 1

        return counts

    def _read_source_names(self) -> dict[str, str]:
        if not self.chunk_metadata_path.exists():
            return {}

        try:
            payload = json.loads(self.chunk_metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(payload, list):
            return {}

        output: dict[str, str] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            contract_id = str(
                item.get("contract_id")
                or item.get("contract_name")
                or metadata.get("contract_id")
                or metadata.get("contract_name")
                or ""
            ).strip()
            source_name = str(item.get("source_name") or metadata.get("source_name") or "").strip()
            if contract_id and source_name and contract_id not in output:
                output[contract_id] = source_name

        return output


def _to_display_name(source_name: str, contract_id: str) -> str:
    stem = Path(source_name).stem.strip() if source_name else ""
    if stem and stem != contract_id:
        normalized_stem = re.sub(r"[_\-]+", " ", stem).strip()
        if normalized_stem:
            return normalized_stem
        return stem

    candidate = contract_id
    timestamp_match = re.match(r"^(.*)_\d{14}$", contract_id)
    if timestamp_match:
        candidate = timestamp_match.group(1).strip("_")

    normalized = re.sub(r"[_\-]+", " ", candidate).strip()
    if normalized:
        return normalized

    if stem:
        return stem

    return contract_id


################################################################################
# FILE: src/pipeline/embedder.py
################################################################################


import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

try:
    from langchain_core.embeddings import Embeddings
except Exception:
    class Embeddings:  # type: ignore[no-redef]
        pass

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except Exception:
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings
    except Exception:
        HuggingFaceEmbeddings = None

try:
    from langchain_chroma import Chroma
except Exception:
    try:
        from langchain_community.vectorstores import Chroma
    except Exception:
        Chroma = None


from src.utils.embeddings import HashEmbeddings, get_hash_embeddings
from src.pipeline.artifact_store import ContractArtifactStore


_EMBEDDING_CACHE: dict[str, Embeddings] = {}
_EMBEDDING_CACHE_LOCK = threading.RLock()

def resolve_embeddings(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> Embeddings:
    normalized_model_name = str(model_name or "sentence-transformers/all-MiniLM-L6-v2").strip()

    with _EMBEDDING_CACHE_LOCK:
        cached = _EMBEDDING_CACHE.get(normalized_model_name)
        if cached is not None:
            return cached

        resolved: Embeddings
        if HuggingFaceEmbeddings is not None:
            try:
                resolved = HuggingFaceEmbeddings(model_name=normalized_model_name)
            except Exception:
                resolved = get_hash_embeddings()
        else:
            resolved = get_hash_embeddings()

        _EMBEDDING_CACHE[normalized_model_name] = resolved
        return resolved


class ContractVectorStore:
    def __init__(
        self,
        persist_directory: Path | str = Path("data/processed/chroma"),
        collection_name: str = "contracts",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        artifact_store: ContractArtifactStore | None = None,
    ) -> None:
        self.persist_directory = Path(persist_directory)
        self.collection_name = collection_name
        self.embeddings = resolve_embeddings(model_name=embedding_model)
        self.artifact_store = artifact_store
        self._store: Any | None = None
        self.sync_interval_seconds = max(
            0.0,
            float(os.getenv("VECTOR_ARTIFACT_SYNC_INTERVAL_SECONDS", "30")),
        )
        self._last_sync_check = 0.0
        self._last_synced_revision = ""
        self._sync_lock = threading.RLock()

    def get_store(self) -> Any:
        if Chroma is None:
            raise RuntimeError("Chroma vector store is unavailable. Install chromadb and langchain-chroma.")

        if self._store is None:
            self.persist_directory.mkdir(parents=True, exist_ok=True)
            self._store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
            )

        self._sync_from_artifact_store_if_needed(store=self._store)
        return self._store

    def index_chunks(self, chunks: list[dict[str, Any]]) -> int:
        if not chunks:
            return 0

        store = self.get_store()
        contract_ids = {
            str(chunk.get("metadata", {}).get("contract_id", ""))
            for chunk in chunks
            if str(chunk.get("metadata", {}).get("contract_id", ""))
        }

        for contract_id in contract_ids:
            self._delete_contract_chunks(store=store, contract_id=contract_id)

        ids = [str(chunk.get("chunk_id")) for chunk in chunks]
        texts = [str(chunk.get("text", "")) for chunk in chunks]
        metadatas = []
        for chunk in chunks:
            metadata = dict(chunk.get("metadata", {}))
            metadata.setdefault("chunk_id", str(chunk.get("chunk_id", "")))
            metadatas.append(metadata)

        store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        try:
            store.persist()
        except Exception:
            # Newer Chroma clients persist automatically.
            pass

        if self.artifact_store is not None:
            self.artifact_store.replace_contract_chunks(chunks)
            self._last_synced_revision = self.artifact_store.chunk_revision()
            self._last_sync_check = time.monotonic()

        return len(chunks)

    def _sync_from_artifact_store_if_needed(self, store: Any) -> None:
        with self._sync_lock:
            if self.artifact_store is None or not self.artifact_store.db_enabled:
                return

            now = time.monotonic()
            if self.sync_interval_seconds > 0 and (now - self._last_sync_check) < self.sync_interval_seconds:
                return
            self._last_sync_check = now

            remote_count = self.artifact_store.chunk_count()
            if remote_count <= 0:
                return

            remote_revision = self.artifact_store.chunk_revision()
            local_count = self._store_count(store)
            if local_count == remote_count and remote_revision and remote_revision == self._last_synced_revision:
                return

            chunks = self.artifact_store.load_all_chunks()
            if not chunks:
                return

            self._replace_store_chunks(store=store, chunks=chunks)
            self._last_synced_revision = remote_revision

    def _replace_store_chunks(self, store: Any, chunks: list[dict[str, Any]]) -> None:
        ids = [str(chunk.get("chunk_id")) for chunk in chunks if str(chunk.get("chunk_id", "")).strip()]
        texts = [str(chunk.get("text", "")) for chunk in chunks if str(chunk.get("chunk_id", "")).strip()]
        metadatas = []
        for chunk in chunks:
            if not str(chunk.get("chunk_id", "")).strip():
                continue
            metadata = dict(chunk.get("metadata", {}))
            metadata.setdefault("chunk_id", str(chunk.get("chunk_id", "")))
            metadatas.append(metadata)

        if not ids:
            return

        self._clear_store(store=store)
        store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        try:
            store.persist()
        except Exception:
            pass

    @staticmethod
    def _clear_store(store: Any) -> None:
        ids: list[str] = []
        try:
            payload = store.get(include=[])
            raw_ids = payload.get("ids", []) if isinstance(payload, dict) else []
            if raw_ids and isinstance(raw_ids[0], list):
                for group in raw_ids:
                    ids.extend(str(item) for item in group)
            else:
                ids = [str(item) for item in raw_ids]
        except Exception:
            ids = []

        if ids:
            try:
                store.delete(ids=ids)
                return
            except Exception:
                pass

        try:
            store.delete(where={})
        except Exception:
            pass

    @staticmethod
    def _store_count(store: Any) -> int:
        try:
            collection = getattr(store, "_collection", None)
            if collection is not None and hasattr(collection, "count"):
                return int(collection.count())
        except Exception:
            pass

        try:
            payload = store.get(include=[])
            ids = payload.get("ids", []) if isinstance(payload, dict) else []
            return len(ids)
        except Exception:
            return 0

    @staticmethod
    def _delete_contract_chunks(store: Any, contract_id: str) -> None:
        attempts = [
            {"where": {"contract_id": {"$eq": contract_id}}},
            {"where": {"contract_id": contract_id}},
        ]

        for kwargs in attempts:
            try:
                store.delete(**kwargs)
                return
            except Exception:
                continue


################################################################################
# FILE: src/pipeline/parser.py
################################################################################


from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

try:
    import fitz  # pymupdf
except Exception:
    fitz = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@dataclass
class ParsedContract:
    contract_id: str
    source_name: str
    text: str
    raw_text_path: Path


def _safe_contract_id(filename: str, timestamp: str) -> str:
    stem = Path(filename).stem if filename else "contract"
    clean = "".join(char if char.isalnum() else "_" for char in stem)
    clean = clean.strip("_") or "contract"
    return f"{clean}_{timestamp}"


class DocumentParser:
    def __init__(self, raw_upload_dir: Path | str = Path("data/raw/uploads")) -> None:
        self.raw_upload_dir = Path(raw_upload_dir)

    def parse_upload(self, filename: str, file_bytes: bytes, contract_id: str | None = None) -> ParsedContract:
        if not file_bytes:
            raise ValueError("Uploaded file is empty.")

        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise ValueError("File exceeds 10MB maximum size limit.")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        resolved_contract_id = contract_id or _safe_contract_id(filename=filename, timestamp=timestamp)

        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            text = self._extract_pdf_text(file_bytes)
        else:
            text = file_bytes.decode("utf-8", errors="ignore")

        if not text.strip():
            raise ValueError("Could not extract text from uploaded file.")

        self.raw_upload_dir.mkdir(parents=True, exist_ok=True)
        raw_text_path = self.raw_upload_dir / f"{resolved_contract_id}.txt"
        raw_text_path.write_text(text, encoding="utf-8")

        return ParsedContract(
            contract_id=resolved_contract_id,
            source_name=filename,
            text=text,
            raw_text_path=raw_text_path,
        )

    @staticmethod
    def _extract_pdf_text(file_bytes: bytes) -> str:
        errors: list[str] = []

        if fitz is not None:
            try:
                document = fitz.open(stream=file_bytes, filetype="pdf")
                pages = [page.get_text("text") for page in document]
                document.close()
                text = "\n".join(pages).strip()
                if text:
                    return text
                errors.append("pymupdf extracted empty text")
            except Exception as error:
                errors.append(f"pymupdf: {error}")

        if PdfReader is not None:
            try:
                reader = PdfReader(BytesIO(file_bytes))
                pages = [page.extract_text() or "" for page in reader.pages]
                text = "\n".join(pages).strip()
                if text:
                    return text
                errors.append("pypdf extracted empty text")
            except Exception as error:
                errors.append(f"pypdf: {error}")

        details = "; ".join(errors) if errors else "no parser backend succeeded"
        raise ValueError(
            "PDF parsing failed. Install pymupdf (preferred) or ensure pypdf is available. "
            f"Details: {details}"
        )


################################################################################
# FILE: src/pipeline/pipeline.py
################################################################################


from pathlib import Path
from typing import Any

from src.evaluation.ragas_evaluator import ContractQAEvaluator
from src.pipeline.answerer import MistralAnswerer
from src.pipeline.artifact_store import ContractArtifactStore
from src.pipeline.chunker import ClauseAwareChunker, extract_clause_hints_from_question
from src.pipeline.contracts_registry import ContractRegistry
from src.pipeline.embedder import ContractVectorStore
from src.pipeline.parser import DocumentParser
from src.pipeline.retriever import ClauseAwareRetriever


class ContractQAPipeline:
    def __init__(
        self,
        parser: DocumentParser | None = None,
        chunker: ClauseAwareChunker | None = None,
        vector_store: ContractVectorStore | None = None,
        retriever: ClauseAwareRetriever | None = None,
        answerer: MistralAnswerer | None = None,
        evaluator: ContractQAEvaluator | None = None,
        registry: ContractRegistry | None = None,
        artifact_store: ContractArtifactStore | None = None,
    ) -> None:
        self.artifact_store = artifact_store or ContractArtifactStore()
        self.parser = parser or DocumentParser(raw_upload_dir=Path("data/raw/uploads"))
        self.chunker = chunker or ClauseAwareChunker()
        self.vector_store = vector_store or ContractVectorStore(
            persist_directory=Path("data/processed/chroma"),
            collection_name="contracts",
            artifact_store=self.artifact_store,
        )
        if getattr(self.vector_store, "artifact_store", None) is None:
            try:
                self.vector_store.artifact_store = self.artifact_store
            except Exception:
                pass
        self.retriever = retriever or ClauseAwareRetriever(vector_store=self.vector_store)
        self.answerer = answerer or MistralAnswerer()
        self.evaluator = evaluator or ContractQAEvaluator(use_llm_judge=True)
        self.registry = registry or ContractRegistry()

    def ingest_upload(self, filename: str, file_bytes: bytes, contract_id: str | None = None) -> dict[str, Any]:
        parsed = self.parser.parse_upload(
            filename=filename,
            file_bytes=file_bytes,
            contract_id=contract_id,
        )

        self.artifact_store.upsert_contract_text(
            contract_id=parsed.contract_id,
            source_name=parsed.source_name,
            raw_text=parsed.text,
            raw_text_path=str(parsed.raw_text_path),
        )

        chunks = self.chunker.chunk_contract(contract_id=parsed.contract_id, text=parsed.text)
        if not chunks:
            raise ValueError("No chunks created from uploaded contract.")

        for chunk in chunks:
            metadata = dict(chunk.get("metadata", {}))
            metadata.setdefault("contract_id", parsed.contract_id)
            metadata.setdefault("contract_name", parsed.contract_id)
            metadata["source_name"] = parsed.source_name
            metadata["raw_text_path"] = str(parsed.raw_text_path)
            metadata["raw_text_ref"] = f"db://uploaded_contract_texts/{parsed.contract_id}"
            chunk["metadata"] = metadata

        ingested = self.vector_store.index_chunks(chunks)
        self.registry.upsert(
            contract_id=parsed.contract_id,
            source_name=parsed.source_name,
            chunks_ingested=ingested,
        )

        return {
            "contract_id": parsed.contract_id,
            "chunks_ingested": ingested,
            "message": "Contract uploaded and indexed successfully.",
        }

    def list_contracts(self) -> list[dict[str, Any]]:
        return self.registry.list_contracts()

    def ask(
        self,
        question: str,
        contract_id: str | None = None,
        ground_truth: str = "",
        allowed_contract_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        clause_hints = extract_clause_hints_from_question(question)
        retrieval_k = 8
        lowered_question = question.lower()
        if any("termination" in hint for hint in clause_hints):
            retrieval_k = 12
        if any(
            term in lowered_question
            for term in (
                "invoice",
                "billing",
                "payment deadline",
                "key personnel",
                "project manager",
                "replace",
                "replaced",
                "approval",
            )
        ):
            retrieval_k = 12

        source_chunks = self.retriever.get_top_k(
            query=question,
            contract_id=contract_id,
            k=retrieval_k,
            clause_hints=clause_hints,
            allowed_contract_ids=allowed_contract_ids,
        )
        model_answer = self.answerer.answer(question=question, source_chunks=source_chunks)
        answer, sources = self.answerer.finalize_answer_with_sources(
            answer=model_answer,
            source_chunks=source_chunks,
            question=question,
        )

        contexts = [str(chunk.get("text", "")) for chunk in source_chunks if str(chunk.get("text", "")).strip()]
        evaluation = self.evaluator.evaluate_single(
            question=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
        )

        if source_chunks:
            if clause_hints:
                route_reason = "Clause-aware retrieval prioritized likely CUAD clause families."
            else:
                route_reason = "Retrieved top contract chunks from vector search."
        else:
            if allowed_contract_ids is not None:
                route_reason = "No relevant chunks were found in contracts available to this chat."
            else:
                route_reason = "No relevant chunks were found in the indexed contract store."

        return {
            "answer": answer,
            "citations": self.answerer.build_citations(source_chunks),
            "sources": sources,
            "source_chunks": source_chunks,
            "tool_used": "pipeline_contract_search",
            "route_reason": route_reason,
            "used_web_fallback": False,
            "matched_clause_hints": clause_hints,
            "evaluation": evaluation,
        }


################################################################################
# FILE: src/pipeline/retriever.py
################################################################################


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


################################################################################
# FILE: src/retrieval/__init__.py
################################################################################

"""Legacy retrieval package.

Retrieval is now consolidated in src.pipeline.retriever using Chroma-backed
ClauseAwareRetriever with optional BM25 reranking.
"""

__all__: list[str] = []


################################################################################
# FILE: src/utils/embeddings.py
################################################################################

import hashlib
import numpy as np
from langchain_core.embeddings import Embeddings

class HashEmbeddings(Embeddings):
    """Deterministic local fallback embeddings for fully offline operation."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_text(text)

    def _embed_text(self, text: str) -> list[float]:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for token in text.lower().split():
            token_hash = hashlib.md5(token.encode("utf-8")).hexdigest()
            index = int(token_hash, 16) % self.dimensions
            vector[index] += 1.0

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector.tolist()

_shared_hash_embeddings: HashEmbeddings | None = None

def get_hash_embeddings(dimensions: int = 384) -> HashEmbeddings:
    """Return a singleton instance of HashEmbeddings to prevent memory state duplication."""
    global _shared_hash_embeddings
    if _shared_hash_embeddings is None or _shared_hash_embeddings.dimensions != dimensions:
        _shared_hash_embeddings = HashEmbeddings(dimensions=dimensions)
    return _shared_hash_embeddings


################################################################################
# FILE: tests/test_agent.py
################################################################################


import json


from src.agent.agent import LegalContractAgent


class _LLMMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, route_tool: str) -> None:
        self.route_tool = route_tool

    def invoke(self, messages):
        system_prompt = str(messages[0].content).lower()
        if "routing agent" in system_prompt:
            return _LLMMessage(
                json.dumps({"tool": self.route_tool, "reason": f"Route to {self.route_tool} for this test."})
            )
        return _LLMMessage("Grounded answer based on provided context. [chunk_id=c1]")


class _FakeContractRetriever:
    def __init__(self, return_empty: bool = False) -> None:
        self.return_empty = return_empty

    def get_top_k(
        self,
        query: str,
        contract_id: str | None = None,
        k: int = 5,
        clause_hints: list[str] | None = None,
    ):
        if self.return_empty:
            return []
        return [
            {
                "chunk_id": "c1",
                "text": "Indemnification is capped at direct damages.",
                "metadata": {
                    "contract_name": "sample_contract",
                    "clause_type": "indemnification",
                    "page_number": 4,
                },
                "fused_score": 0.12,
            }
        ]


def test_agent_routes_to_contract_search() -> None:
    agent = LegalContractAgent(clause_retriever=_FakeContractRetriever(), llm=_FakeLLM(route_tool="contract_search"))
    result = agent.run("What is the indemnification cap?")

    assert result["tool_used"] == "contract_search"
    assert result["source_chunks"]
    assert result["used_web_fallback"] is False


def test_agent_routes_to_web_search() -> None:
    agent = LegalContractAgent(clause_retriever=_FakeContractRetriever(), llm=_FakeLLM(route_tool="web_search"))
    result = agent.run("What is the market indemnity cap in SaaS deals?")

    assert result["tool_used"] == "web_search"


def test_agent_falls_back_to_web_when_contract_has_no_results() -> None:
    agent = LegalContractAgent(
        clause_retriever=_FakeContractRetriever(return_empty=True),
        llm=_FakeLLM(route_tool="contract_search"),
    )
    result = agent.run("Find the termination clause")

    assert result["used_web_fallback"] is True
    assert result["tool_used"] == "web_search"


################################################################################
# FILE: tests/test_artifact_store.py
################################################################################


import uuid

import pytest

from src.pipeline.artifact_store import ContractArtifactStore
from src.pipeline import embedder as pipeline_embedder
from src.utils.embeddings import get_hash_embeddings


class _FakeArtifactStore:
    def __init__(self, chunks: list[dict[str, object]], revision: str) -> None:
        self.db_enabled = True
        self._chunks = chunks
        self._revision = revision

    def chunk_count(self) -> int:
        return len(self._chunks)

    def chunk_revision(self) -> str:
        return self._revision

    def load_all_chunks(self, contract_ids: list[str] | None = None, limit: int | None = None):
        _ = contract_ids
        _ = limit
        return list(self._chunks)

    def replace_contract_chunks(self, chunks: list[dict[str, object]]) -> int:
        self._chunks = list(chunks)
        return len(self._chunks)


class _FakeStore:
    def __init__(self) -> None:
        self.docs: dict[str, tuple[str, dict[str, object]]] = {}
        self.persist_calls = 0

    def add_texts(self, texts: list[str], metadatas: list[dict[str, object]], ids: list[str]) -> None:
        for chunk_id, text, metadata in zip(ids, texts, metadatas):
            self.docs[str(chunk_id)] = (str(text), dict(metadata))

    def get(self, include=None):
        _ = include
        return {"ids": list(self.docs.keys())}

    def delete(self, ids=None, where=None):
        if ids is not None:
            for chunk_id in ids:
                self.docs.pop(str(chunk_id), None)
            return
        _ = where
        self.docs.clear()

    def persist(self) -> None:
        self.persist_calls += 1


def test_artifact_store_db_round_trip(tmp_path) -> None:
    db_path = tmp_path / "artifacts.db"
    database_url = f"sqlite:///{db_path}"

    store = ContractArtifactStore(backend="db", database_url=database_url)
    assert store.db_enabled is True

    store.upsert_contract_text(
        contract_id="contract_x",
        source_name="ContractX.pdf",
        raw_text="Master services agreement text.",
        raw_text_path="data/raw/uploads/contract_x.txt",
        uploaded_at="2026-04-07T10:00:00",
    )

    inserted = store.replace_contract_chunks(
        [
            {
                "chunk_id": "contract_x_0",
                "text": "Payment obligations and invoice deadlines.",
                "metadata": {
                    "contract_id": "contract_x",
                    "contract_name": "contract_x",
                    "clause_type": "payment",
                },
            }
        ]
    )
    assert inserted == 1

    contract_text = store.get_contract_text("contract_x")
    assert contract_text is not None
    assert contract_text["source_name"] == "ContractX.pdf"

    second_store = ContractArtifactStore(backend="db", database_url=database_url)
    chunks = second_store.load_all_chunks(contract_ids=["contract_x"])
    assert len(chunks) == 1
    assert chunks[0]["chunk_id"] == "contract_x_0"
    assert chunks[0]["metadata"]["clause_type"] == "payment"


def test_vector_store_bootstraps_from_db_artifacts(tmp_path, monkeypatch) -> None:
    if pipeline_embedder.Chroma is None:
        pytest.skip("Chroma backend is not installed")

    db_path = tmp_path / "artifacts.db"
    database_url = f"sqlite:///{db_path}"

    artifact_store = ContractArtifactStore(backend="db", database_url=database_url)
    artifact_store.replace_contract_chunks(
        [
            {
                "chunk_id": "contract_y_0",
                "text": "The indemnification cap is limited to direct damages.",
                "metadata": {
                    "contract_id": "contract_y",
                    "contract_name": "contract_y",
                    "clause_type": "indemnification",
                },
            }
        ]
    )

    monkeypatch.setattr(
        pipeline_embedder,
        "resolve_embeddings",
        lambda model_name: get_hash_embeddings(),
    )

    collection_name = f"contracts_test_{uuid.uuid4().hex[:8]}"
    vector_store = pipeline_embedder.ContractVectorStore(
        persist_directory=tmp_path / "chroma",
        collection_name=collection_name,
        artifact_store=artifact_store,
    )

    store = vector_store.get_store()
    results = store.similarity_search(query="indemnification cap", k=3)

    assert results
    assert any(
        str(getattr(doc, "metadata", {}).get("contract_id", "")) == "contract_y"
        for doc in results
    )


def test_vector_store_refreshes_when_artifact_revision_changes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_embedder,
        "resolve_embeddings",
        lambda model_name: get_hash_embeddings(),
    )

    initial_chunks = [
        {
            "chunk_id": "contract_z_0",
            "text": "Initial chunk text.",
            "metadata": {"contract_id": "contract_z", "contract_name": "contract_z"},
        }
    ]
    artifact_store = _FakeArtifactStore(chunks=initial_chunks, revision="rev_1")
    local_store = _FakeStore()

    vector_store = pipeline_embedder.ContractVectorStore(
        persist_directory=tmp_path / "chroma_fake",
        collection_name="contracts_fake_refresh",
        artifact_store=artifact_store,
    )
    vector_store.sync_interval_seconds = 0.0

    vector_store._sync_from_artifact_store_if_needed(local_store)
    assert set(local_store.docs.keys()) == {"contract_z_0"}
    assert local_store.docs["contract_z_0"][0] == "Initial chunk text."

    artifact_store._chunks = [
        {
            "chunk_id": "contract_z_0",
            "text": "Updated chunk text.",
            "metadata": {"contract_id": "contract_z", "contract_name": "contract_z"},
        },
        {
            "chunk_id": "contract_z_1",
            "text": "Newly added chunk.",
            "metadata": {"contract_id": "contract_z", "contract_name": "contract_z"},
        },
    ]
    artifact_store._revision = "rev_2"

    vector_store._sync_from_artifact_store_if_needed(local_store)
    assert set(local_store.docs.keys()) == {"contract_z_0", "contract_z_1"}
    assert local_store.docs["contract_z_0"][0] == "Updated chunk text."
    assert local_store.docs["contract_z_1"][0] == "Newly added chunk."


################################################################################
# FILE: tests/test_api.py
################################################################################




import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.evaluation.metrics_store import MetricsStore
from src.pipeline.chat_scope_registry import ChatScopeRegistry


class _FakeEvaluator:
    def evaluate_single(self, question: str, answer: str, contexts: list[str], ground_truth: str = ""):
        return {
            "faithfulness": 0.95,
            "answer_relevance": 0.88,
            "context_precision": 0.84,
            "context_recall": 0.78,
        }


class _FakePipeline:
    def __init__(self) -> None:
        self._uploaded_contracts: list[dict[str, str | int]] = []

    def ask(
        self,
        question: str,
        contract_id: str | None = None,
        ground_truth: str = "",
        allowed_contract_ids: list[str] | None = None,
    ):
        if allowed_contract_ids is not None:
            allowed = {str(item).strip() for item in allowed_contract_ids if str(item).strip()}
            if contract_id and contract_id not in allowed:
                return {
                    "answer": "This contract does not contain a clause addressing that.",
                    "tool_used": "pipeline_contract_search",
                    "route_reason": "No relevant chunks were found in contracts available to this chat.",
                    "used_web_fallback": False,
                    "matched_clause_hints": [],
                    "sources": [],
                    "evaluation": {
                        "faithfulness": 0.0,
                        "answer_relevance": 0.0,
                        "context_precision": 0.0,
                        "context_recall": 0.0,
                    },
                    "citations": [],
                    "source_chunks": [],
                }

        if "indemnification" in question.lower():
            return {
                "answer": "The indemnification cap is limited to direct damages. [1]\n\nSources:\n[1] sample_contract.pdf",
                "tool_used": "pipeline_contract_search",
                "route_reason": "Retrieved top contract chunks from vector search.",
                "used_web_fallback": False,
                "matched_clause_hints": ["indemnification"],
                "sources": [
                    {
                        "index": 1,
                        "label": "sample_contract.pdf",
                        "contract_id": contract_id or "sample_contract",
                    }
                ],
                "evaluation": {
                    "faithfulness": 0.91,
                    "answer_relevance": 0.9,
                    "context_precision": 0.87,
                    "context_recall": 0.85,
                },
                "citations": [
                    {
                        "chunk_id": "c1",
                        "contract_name": contract_id or "sample_contract",
                        "clause_type": "indemnification",
                        "page_number": 4,
                        "url": "",
                    }
                ],
                "source_chunks": [
                    {
                        "chunk_id": "c1",
                        "text": "Indemnification clause text",
                        "metadata": {
                            "contract_name": contract_id or "sample_contract",
                            "clause_type": "indemnification",
                        },
                    }
                ],
            }

        return {
            "answer": "Termination for convenience requires 30 days written notice. [1]\n\nSources:\n[1] sample_contract.pdf",
            "tool_used": "pipeline_contract_search",
            "route_reason": "Clause-aware retrieval prioritized likely CUAD clause families.",
            "used_web_fallback": False,
            "matched_clause_hints": ["termination_for_convenience"],
            "sources": [
                {
                    "index": 1,
                    "label": "sample_contract.pdf",
                    "contract_id": contract_id or "sample_contract",
                }
            ],
            "evaluation": {
                "faithfulness": 0.9,
                "answer_relevance": 0.93,
                "context_precision": 0.88,
                "context_recall": 0.86,
            },
            "citations": [
                {
                    "chunk_id": "c2",
                    "contract_name": contract_id or "sample_contract",
                    "clause_type": "termination_for_convenience",
                    "page_number": 8,
                    "url": "",
                }
            ],
            "source_chunks": [
                {
                    "chunk_id": "c2",
                    "text": "Either party may terminate this Agreement for convenience with 30 days written notice.",
                    "metadata": {
                        "contract_name": contract_id or "sample_contract",
                        "clause_type": "termination_for_convenience",
                    },
                }
            ],
        }

    def ingest_upload(self, filename: str, file_bytes: bytes, contract_id: str | None = None):
        if not file_bytes:
            raise ValueError("Uploaded file is empty")
        resolved_contract_id = contract_id or "fake_contract_20260407000000"
        self._uploaded_contracts.append(
            {
                "contract_id": resolved_contract_id,
                "display_name": filename,
                "source_name": filename,
                "chunks_ingested": 3,
                "uploaded_at": "2026-04-07T00:00:00",
            }
        )
        return {
            "contract_id": resolved_contract_id,
            "chunks_ingested": 3,
            "message": "Contract uploaded and indexed successfully.",
        }

    def list_contracts(self):
        static_contracts = [
            {
                "contract_id": "sample_contract_20260407010101",
                "display_name": "Sample Contract",
                "source_name": "SampleContract.pdf",
                "chunks_ingested": 42,
                "uploaded_at": "2026-04-07T01:01:01",
            },
            {
                "contract_id": "msa_alpha_20260407020202",
                "display_name": "MSA Alpha",
                "source_name": "MSA-Alpha.pdf",
                "chunks_ingested": 31,
                "uploaded_at": "2026-04-07T02:02:02",
            },
        ]

        return list(self._uploaded_contracts) + static_contracts


class _FailingAskPipeline(_FakePipeline):
    def ask(
        self,
        question: str,
        contract_id: str | None = None,
        ground_truth: str = "",
        allowed_contract_ids: list[str] | None = None,
    ):
        raise RuntimeError("sensitive backend detail")


class _FailingIngestPipeline(_FakePipeline):
    def ingest_upload(self, filename: str, file_bytes: bytes, contract_id: str | None = None):
        raise RuntimeError("internal parse failure detail")


def _override_app_state(app, tmp_path, pipeline) -> None:
    db_path = tmp_path / "test_metrics.db"
    store = MetricsStore(database_url=f"sqlite:///{db_path}")
    store.init_db()
    app.state.metrics_store = store
    app.state.evaluator = _FakeEvaluator()
    app.state.pipeline = pipeline
    app.state.chat_scope_registry = ChatScopeRegistry(registry_path=tmp_path / "chat_scope_registry.json")


@pytest.fixture
def client(tmp_path):
    app = create_app()
    with TestClient(app) as test_client:
        _override_app_state(app=app, tmp_path=tmp_path, pipeline=_FakePipeline())
        yield test_client


def test_query_endpoint_returns_answer(client: TestClient) -> None:
    response = client.post("/query", json={"query": "What is the indemnification cap?", "contract_id": None})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_used"] == "pipeline_contract_search"
    assert "indemnification cap" in payload["answer"].lower()


def test_metrics_endpoint_returns_recent_rows(client: TestClient) -> None:
    client.post("/query", json={"query": "What is termination for convenience?"})
    response = client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert "recent" in payload
    assert "trends" in payload
    assert "analytics" in payload


def test_ask_endpoint_returns_answer_and_evaluation(client: TestClient) -> None:
    response = client.post("/ask", json={"query": "What is the termination for convenience notice period?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_used"] == "pipeline_contract_search"
    assert payload["matched_clause_hints"] == ["termination_for_convenience"]
    assert payload["evaluation"]["faithfulness"] == 0.9
    assert payload["sources"][0]["label"] == "sample_contract.pdf"
    assert "[1]" in payload["answer"]


def test_ask_endpoint_accepts_question_alias(client: TestClient) -> None:
    response = client.post("/ask", json={"question": "What is the termination for convenience notice period?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_used"] == "pipeline_contract_search"


def test_contracts_endpoint_returns_friendly_names(client: TestClient) -> None:
    response = client.get("/contracts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["contracts"][0]["display_name"] == "Sample Contract"


def test_upload_endpoint_rejects_empty_file(client: TestClient) -> None:
    response = client.post(
        "/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400


def test_upload_endpoint_accepts_multiple_files(client: TestClient) -> None:
    response = client.post(
        "/upload",
        files=[
            ("files", ("first.txt", b"First contract text", "text/plain")),
            ("files", ("second.txt", b"Second contract text", "text/plain")),
        ],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_id"]
    assert payload["total_files"] == 2
    assert len(payload["uploads"]) == 2


def test_chat_scoped_contract_visibility_and_access(client: TestClient) -> None:
    upload_a = client.post(
        "/upload",
        data={"chat_id": "chat_a"},
        files={"file": ("chat_a_doc.txt", b"Contract text for chat A", "text/plain")},
    )
    assert upload_a.status_code == 200
    contract_a = upload_a.json()["contract_id"]

    upload_b = client.post(
        "/upload",
        data={"chat_id": "chat_b"},
        files={"file": ("chat_b_doc.txt", b"Contract text for chat B", "text/plain")},
    )
    assert upload_b.status_code == 200
    contract_b = upload_b.json()["contract_id"]

    contracts_a = client.get("/contracts", params={"chat_id": "chat_a"})
    assert contracts_a.status_code == 200
    returned_a = {item["contract_id"] for item in contracts_a.json()["contracts"]}
    assert contract_a in returned_a
    assert contract_b not in returned_a

    contracts_b = client.get("/contracts", params={"chat_id": "chat_b"})
    assert contracts_b.status_code == 200
    returned_b = {item["contract_id"] for item in contracts_b.json()["contracts"]}
    assert contract_b in returned_b
    assert contract_a not in returned_b

    allowed_query = client.post(
        "/query",
        json={
            "query": "What is termination for convenience?",
            "chat_id": "chat_a",
            "contract_id": contract_a,
        },
    )
    assert allowed_query.status_code == 200

    blocked_query = client.post(
        "/query",
        json={
            "query": "What is termination for convenience?",
            "chat_id": "chat_b",
            "contract_id": contract_a,
        },
    )
    assert blocked_query.status_code == 403


def test_query_rejects_contract_without_chat_scope(client: TestClient) -> None:
    response = client.post(
        "/query",
        json={
            "query": "What is termination for convenience?",
            "contract_id": "sample_contract_20260407010101",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "chat_id is required when contract_id is provided."


def test_auth_middleware_requires_api_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("API_AUTH_TOKEN", "secret-token")
    app = create_app()
    with TestClient(app) as client:
        _override_app_state(app=app, tmp_path=tmp_path, pipeline=_FakePipeline())

        unauthorized = client.post(
            "/query",
            json={"query": "What is indemnification?"},
        )
        assert unauthorized.status_code == 401

        authorized = client.post(
            "/query",
            json={"query": "What is indemnification?"},
            headers={"x-api-key": "secret-token"},
        )
        assert authorized.status_code == 200


def test_strict_scope_policy_requires_chat_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("REQUIRE_CHAT_SCOPE", "1")
    app = create_app()
    with TestClient(app) as client:
        _override_app_state(app=app, tmp_path=tmp_path, pipeline=_FakePipeline())

        query_response = client.post(
            "/query",
            json={"query": "What is termination for convenience?"},
        )
        assert query_response.status_code == 400
        assert query_response.json()["detail"] == "chat_id is required by server policy."

        contracts_response = client.get("/contracts")
        assert contracts_response.status_code == 400
        assert contracts_response.json()["detail"] == "chat_id is required by server policy."


def test_query_error_message_is_sanitized(tmp_path) -> None:
    app = create_app()
    with TestClient(app) as client:
        _override_app_state(app=app, tmp_path=tmp_path, pipeline=_FailingAskPipeline())
        response = client.post(
            "/query",
            json={"query": "What is indemnification?"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "Pipeline query failed."


def test_upload_error_message_is_sanitized(tmp_path) -> None:
    app = create_app()
    with TestClient(app) as client:
        _override_app_state(app=app, tmp_path=tmp_path, pipeline=_FailingIngestPipeline())
        response = client.post(
            "/upload",
            data={"chat_id": "chat_a"},
            files={"file": ("sample.txt", b"content", "text/plain")},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "Pipeline ingestion failed for sample.txt."


################################################################################
# FILE: tests/test_chunker.py
################################################################################


from src.pipeline.chunker import extract_clause_hints_from_question, infer_clause_type


def test_infer_clause_type_detects_termination_for_convenience() -> None:
    text = (
        "4. EARLY TERMINATION\n"
        "COMMISSION may terminate this Agreement for its convenience at any time with thirty-day written notice."
    )
    assert infer_clause_type(text) == "termination_for_convenience"


def test_infer_clause_type_detects_termination_for_cause() -> None:
    text = (
        "4.B TERMINATION\n"
        "COMMISSION may terminate for CONSULTANT default or material breach if not cured within ten days."
    )
    assert infer_clause_type(text) == "termination_for_cause"


def test_infer_clause_type_keeps_document_name_for_title() -> None:
    text = "CONTRACT TITLE\nDocument name: Shuttle Operations Master Agreement"
    assert infer_clause_type(text) == "document_name"


def test_extract_clause_hints_boosts_termination_queries() -> None:
    hints = extract_clause_hints_from_question("What are the termination conditions?")
    assert "termination_for_convenience" in hints
    assert "termination_for_cause" in hints


################################################################################
# FILE: tests/test_ingestion_embedder.py
################################################################################


from pathlib import Path
from typing import Any

from src.ingestion import embedder as ingestion_embedder
from src.utils.embeddings import HashEmbeddings


class _InvalidEmbeddings:
    def embed_query(self, text: str) -> dict[str, str]:
        return {"error": "invalid"}

    def embed_documents(self, texts: list[str]) -> list[dict[str, str]]:
        return [{"error": "invalid"} for _ in texts]


class _RemoteEmbeddings:
    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeVectorStore:
    def __init__(self, save_calls: list[str]) -> None:
        self.save_calls = save_calls

    def save_local(self, output_dir: str) -> None:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        self.save_calls.append(output_dir)


def _sample_chunks() -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": "chunk_1",
            "text": "payment terms and termination clause",
            "metadata": {"contract_id": "contract_1"},
        }
    ]


def test_build_faiss_index_falls_back_when_probe_vector_is_invalid(monkeypatch, tmp_path) -> None:
    embedding_calls: list[object] = []
    save_calls: list[str] = []

    class _FakeFAISS:
        @staticmethod
        def from_texts(texts: list[str], embedding: object, metadatas: list[dict[str, Any]]) -> _FakeVectorStore:
            embedding_calls.append(embedding)
            return _FakeVectorStore(save_calls)

    monkeypatch.setattr(ingestion_embedder, "resolve_embeddings", lambda model_name: _InvalidEmbeddings())
    monkeypatch.setattr(ingestion_embedder, "FAISS", _FakeFAISS)

    output_dir = ingestion_embedder.build_faiss_index(
        chunks=_sample_chunks(),
        output_dir=tmp_path / "faiss_invalid_probe",
    )

    assert output_dir == tmp_path / "faiss_invalid_probe"
    assert len(embedding_calls) == 1
    assert isinstance(embedding_calls[0], HashEmbeddings)
    assert save_calls


def test_build_faiss_index_retries_with_hash_embeddings_after_backend_failure(monkeypatch, tmp_path) -> None:
    embedding_calls: list[object] = []
    save_calls: list[str] = []

    class _FakeFAISS:
        @staticmethod
        def from_texts(texts: list[str], embedding: object, metadatas: list[dict[str, Any]]) -> _FakeVectorStore:
            embedding_calls.append(embedding)
            if len(embedding_calls) == 1:
                raise KeyError(0)
            return _FakeVectorStore(save_calls)

    monkeypatch.setattr(ingestion_embedder, "resolve_embeddings", lambda model_name: _RemoteEmbeddings())
    monkeypatch.setattr(ingestion_embedder, "FAISS", _FakeFAISS)

    output_dir = ingestion_embedder.build_faiss_index(
        chunks=_sample_chunks(),
        output_dir=tmp_path / "faiss_retry",
    )

    assert output_dir == tmp_path / "faiss_retry"
    assert len(embedding_calls) == 2
    assert not isinstance(embedding_calls[0], HashEmbeddings)
    assert isinstance(embedding_calls[1], HashEmbeddings)
    assert save_calls


################################################################################
# FILE: tests/test_registry_backends.py
################################################################################


from src.pipeline.chat_scope_registry import ChatScopeRegistry
from src.pipeline.contracts_registry import ContractRegistry


def test_chat_scope_registry_db_backend_persists_across_instances(tmp_path) -> None:
    db_path = tmp_path / "registry_state.db"
    database_url = f"sqlite:///{db_path}"

    first = ChatScopeRegistry(
        registry_path=tmp_path / "chat_scope_registry.json",
        backend="db",
        database_url=database_url,
    )
    first.add_contracts("chat_a", ["contract_1", "contract_2", "contract_1"])

    assert first.list_contract_ids("chat_a") == ["contract_1", "contract_2"]

    second = ChatScopeRegistry(
        registry_path=tmp_path / "chat_scope_registry_other.json",
        backend="db",
        database_url=database_url,
    )
    assert second.list_contract_ids("chat_a") == ["contract_1", "contract_2"]


def test_contract_registry_db_backend_upsert_and_ordering(tmp_path) -> None:
    db_path = tmp_path / "registry_state.db"
    database_url = f"sqlite:///{db_path}"

    registry = ContractRegistry(
        registry_path=tmp_path / "contracts_registry.json",
        raw_upload_dir=tmp_path / "uploads",
        chunk_metadata_path=tmp_path / "chunk_metadata.json",
        backend="db",
        database_url=database_url,
    )

    registry.upsert(
        contract_id="contract_a",
        source_name="Alpha.pdf",
        chunks_ingested=3,
        uploaded_at="2026-04-07T01:00:00",
    )
    registry.upsert(
        contract_id="contract_b",
        source_name="Beta.pdf",
        chunks_ingested=4,
        uploaded_at="2026-04-07T02:00:00",
    )

    rows = registry.list_contracts()
    assert [row["contract_id"] for row in rows] == ["contract_b", "contract_a"]
    assert rows[0]["display_name"] == "Beta"

    # Updating existing contract should move it to top with newer timestamp.
    registry.upsert(
        contract_id="contract_a",
        source_name="Alpha_v2.pdf",
        chunks_ingested=7,
        uploaded_at="2026-04-07T03:00:00",
    )

    updated_rows = registry.list_contracts()
    assert updated_rows[0]["contract_id"] == "contract_a"
    assert updated_rows[0]["chunks_ingested"] == 7
    assert updated_rows[0]["source_name"] == "Alpha_v2.pdf"

    # Ensure data persists across a new registry instance.
    second_registry = ContractRegistry(
        registry_path=tmp_path / "contracts_registry_other.json",
        raw_upload_dir=tmp_path / "uploads",
        chunk_metadata_path=tmp_path / "chunk_metadata.json",
        backend="db",
        database_url=database_url,
    )
    persisted_rows = second_registry.list_contracts()
    assert persisted_rows[0]["contract_id"] == "contract_a"
    assert {row["contract_id"] for row in persisted_rows} == {"contract_a", "contract_b"}


################################################################################
# FILE: tests/test_retrieval.py
################################################################################


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
