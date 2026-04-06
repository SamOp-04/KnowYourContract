from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

QUICK_QUESTIONS = [
    "What are the termination conditions?",
    "How much notice is required to terminate?",
    "What is the maximum payment under this agreement?",
    "When must invoices be submitted?",
    "What insurance is required?",
    "Who owns the work products?",
    "How are disputes resolved?",
    "Can the consultant subcontract work?",
    "What audit rights does the commission have?",
    "What records must be maintained and for how long?",
]

st.set_page_config(page_title="Legal Contract Analyzer", layout="wide")
st.title("Legal Contract Analyzer")
st.caption("Agentic RAG over contracts with hybrid retrieval and source-grounded answers.")

if "contract_id" not in st.session_state:
    st.session_state.contract_id = None
if "contracts" not in st.session_state:
    st.session_state.contracts = []
if "question" not in st.session_state:
    st.session_state.question = ""


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def _get_json(path: str) -> dict[str, Any]:
    response = requests.get(f"{API_BASE_URL}{path}", timeout=60)
    response.raise_for_status()
    return response.json()


def _post_files(path: str, uploads: list[Any]) -> dict[str, Any]:
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

    response = requests.post(f"{API_BASE_URL}{path}", files=multipart_files, timeout=600)
    response.raise_for_status()
    return response.json()


def _refresh_contracts() -> None:
    try:
        payload = _get_json("/contracts")
        st.session_state.contracts = list(payload.get("contracts", []))
    except Exception:
        st.session_state.contracts = []


_refresh_contracts()


with st.sidebar:
    st.header("Contract Upload")
    uploaded_files = st.file_uploader(
        "Upload contract(s) (.txt or .pdf)",
        type=["txt", "pdf"],
        accept_multiple_files=True,
    )
    if uploaded_files and st.button("Index Uploaded Contract(s)", type="primary"):
        try:
            payload = _post_files(
                "/upload",
                uploads=list(uploaded_files),
            )

            uploaded_items = list(payload.get("uploads", []))
            if uploaded_items:
                for item in uploaded_items:
                    st.success(
                        f"Indexed {item.get('source_name')}: {item.get('contract_id')} "
                        f"({item.get('chunks_ingested')} chunks)"
                    )
                st.session_state.contract_id = uploaded_items[-1].get("contract_id")
            else:
                st.session_state.contract_id = payload.get("contract_id")
                st.success(
                    f"Indexed contract: {payload.get('contract_id')} ({payload.get('chunks_ingested')} chunks)"
                )

            _refresh_contracts()
        except requests.HTTPError as error:
            st.error(f"Upload failed: {error.response.text}")
        except Exception as error:
            st.error(f"Upload failed: {error}")

    st.markdown("---")

    if st.button("Refresh Contract List"):
        _refresh_contracts()

    contracts = st.session_state.contracts
    if contracts:
        selected = st.selectbox(
            "Contract scope",
            options=[None] + contracts,
            format_func=lambda item: (
                "All indexed contracts"
                if item is None
                else f"{item.get('display_name', item.get('contract_id', 'contract'))} ({item.get('contract_id', '')})"
            ),
        )
        st.session_state.contract_id = selected.get("contract_id") if isinstance(selected, dict) else None
    else:
        st.write("No uploaded contracts found yet.")

    st.write("Current contract scope:")
    st.code(st.session_state.contract_id or "all indexed contracts")

st.markdown("### Quick Questions")
quick_question_columns = st.columns(2)
for index, quick_question in enumerate(QUICK_QUESTIONS):
    if quick_question_columns[index % 2].button(
        quick_question,
        key=f"quick_question_{index}",
        use_container_width=True,
    ):
        st.session_state.question = quick_question

query = st.text_area(
    "Ask a question about clauses, obligations, risk terms, or contract comparisons:",
    height=120,
    placeholder="What is the indemnification limit in this contract?",
    value=st.session_state.question,
)

if st.button("Analyze", type="primary", use_container_width=True):
    if not query.strip():
        st.warning("Please enter a query.")
    else:
        payload = {
            "question": query.strip(),
            "contract_id": st.session_state.contract_id,
        }

        try:
            with st.spinner("Running retrieval and answer generation..."):
                result = _post_json("/ask", payload)

            st.session_state.question = ""

            st.subheader("Answer")
            st.write(result.get("answer", "No answer generated."))

            citations = result.get("citations", [])
            st.subheader("Citations")
            if citations:
                st.dataframe(citations, use_container_width=True, hide_index=True)
            else:
                st.write("No citations returned.")

            evaluation = result.get("evaluation", {})
            if evaluation:
                st.subheader("Evaluation Scores")
                score_cols = st.columns(4)
                score_cols[0].metric("Faithfulness", round(evaluation.get("faithfulness", 0), 2))
                score_cols[1].metric("Answer Relevance", round(evaluation.get("answer_relevance", 0), 2))
                score_cols[2].metric("Context Precision", round(evaluation.get("context_precision", 0), 2))
                score_cols[3].metric("Context Recall", round(evaluation.get("context_recall", 0), 2))
                st.caption(f"Score source: {evaluation.get('score_source', 'unknown')}")

            st.subheader("Source Chunks")
            for index, chunk in enumerate(result.get("source_chunks", []), start=1):
                if isinstance(chunk, dict):
                    metadata = chunk.get("metadata", {}) if isinstance(chunk.get("metadata", {}), dict) else {}
                    page_number = metadata.get("page_number", "?")
                    clause_type = metadata.get("clause_type", "")
                    with st.expander(
                        f"Source chunk {index} - page {page_number}"
                        f"{f' . {clause_type}' if clause_type else ''}"
                    ):
                        st.write(chunk.get("text", ""))
                else:
                    with st.expander(f"Source chunk {index}"):
                        st.write(chunk)

            meta_col1, meta_col2 = st.columns(2)
            with meta_col1:
                st.metric("Tool Used", result.get("tool_used", "unknown"))
            with meta_col2:
                st.metric("Web Fallback", "Yes" if result.get("used_web_fallback") else "No")

            st.info(result.get("route_reason", ""))
        except requests.HTTPError as error:
            st.error(f"Query failed: {error.response.text}")
        except Exception as error:
            st.error(f"Query failed: {error}")
