from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Legal Contract Analyzer", layout="wide")
st.title("Legal Contract Analyzer")
st.caption("Agentic RAG over contracts with hybrid retrieval and source-grounded answers.")

if "contract_id" not in st.session_state:
    st.session_state.contract_id = None


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def _post_file(path: str, filename: str, content: bytes, mime_type: str) -> dict[str, Any]:
    files = {"file": (filename, content, mime_type)}
    response = requests.post(f"{API_BASE_URL}{path}", files=files, timeout=300)
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.header("Contract Upload")
    uploaded_file = st.file_uploader("Upload contract (.txt or .pdf)", type=["txt", "pdf"])
    if uploaded_file is not None and st.button("Index Uploaded Contract", type="primary"):
        try:
            payload = _post_file(
                "/upload",
                filename=uploaded_file.name,
                content=uploaded_file.getvalue(),
                mime_type=uploaded_file.type or "application/octet-stream",
            )
            st.session_state.contract_id = payload.get("contract_id")
            st.success(
                f"Indexed contract: {payload.get('contract_id')} ({payload.get('chunks_ingested')} chunks)"
            )
        except requests.HTTPError as error:
            st.error(f"Upload failed: {error.response.text}")
        except Exception as error:
            st.error(f"Upload failed: {error}")

    st.markdown("---")
    st.write("Current contract scope:")
    st.code(st.session_state.contract_id or "all indexed contracts")

query = st.text_area(
    "Ask a question about clauses, obligations, risk terms, or contract comparisons:",
    height=120,
    placeholder="What is the indemnification limit in this contract?",
)

if st.button("Analyze", type="primary", use_container_width=True):
    if not query.strip():
        st.warning("Please enter a query.")
    else:
        payload = {
            "query": query.strip(),
            "contract_id": st.session_state.contract_id,
        }

        try:
            with st.spinner("Running agentic retrieval and answer generation..."):
                result = _post_json("/query", payload)

            st.subheader("Answer")
            st.write(result.get("answer", "No answer generated."))

            meta_col1, meta_col2 = st.columns(2)
            with meta_col1:
                st.metric("Tool Used", result.get("tool_used", "unknown"))
            with meta_col2:
                st.metric("Web Fallback", "Yes" if result.get("used_web_fallback") else "No")

            st.subheader("Routing Reason")
            st.info(result.get("route_reason", "No routing rationale available."))

            citations = result.get("citations", [])
            st.subheader("Citations")
            if citations:
                st.dataframe(citations, use_container_width=True, hide_index=True)
            else:
                st.write("No citations returned.")

            st.subheader("Source Chunks")
            for index, chunk in enumerate(result.get("source_chunks", []), start=1):
                with st.expander(f"Source {index}"):
                    if isinstance(chunk, dict):
                        st.json(chunk)
                    else:
                        st.write(chunk)
        except requests.HTTPError as error:
            st.error(f"Query failed: {error.response.text}")
        except Exception as error:
            st.error(f"Query failed: {error}")
