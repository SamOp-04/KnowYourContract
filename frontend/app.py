from __future__ import annotations

import os
import uuid
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
]

st.set_page_config(page_title="Legal Contract Analyzer", layout="wide")

# Custom CSS for chat bubbles
st.markdown(
    '''
    <style>
    .chat-bubble-user {
        background-color: #2b313e;
        color: white;
        padding: 10px 15px;
        border-radius: 15px;
        margin-bottom: 15px;
        max-width: 80%;
        float: right;
        clear: both;
    }
    .chat-bubble-assistant {
        background-color: #f0f2f6;
        color: black;
        padding: 10px 15px;
        border-radius: 15px;
        margin-bottom: 15px;
        max-width: 80%;
        float: left;
        clear: both;
    }
    .chat-container {
        display: flex;
        flex-direction: column;
        width: 100%;
    }
    .clearfix::after {
        content: "";
        clear: both;
        display: table;
    }
    </style>
    ''',
    unsafe_allow_html=True
)

if "sessions" not in st.session_state:
    st.session_state.sessions = {}
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None
if "contract_id" not in st.session_state:
    st.session_state.contract_id = None
if "contracts" not in st.session_state:
    st.session_state.contracts = []

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

def start_new_session():
    new_id = str(uuid.uuid4())
    st.session_state.sessions[new_id] = []
    st.session_state.current_session_id = new_id

if not st.session_state.current_session_id:
    start_new_session()

_refresh_contracts()

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
            
    st.markdown("---")
    st.header("Contract Context")
    
    with st.expander("Upload & Select Contract"):
        uploaded_files = st.file_uploader(
            "Upload contract(s) (.txt or .pdf)",
            type=["txt", "pdf"],
            accept_multiple_files=True,
        )
        if uploaded_files and st.button("Index", type="primary"):
            try:
                payload = _post_files("/upload", uploads=list(uploaded_files))
                uploaded_items = list(payload.get("uploads", []))
                if uploaded_items:
                    st.session_state.contract_id = uploaded_items[-1].get("contract_id")
                else:
                    st.session_state.contract_id = payload.get("contract_id")
                _refresh_contracts()
                st.success("Indexing complete!")
            except Exception as e:
                st.error(f"Upload failed: {e}")

        contracts = st.session_state.contracts
        if contracts:
            contracts_by_id = {str(item.get("contract_id")): item for item in contracts if item.get("contract_id")}
            scope_options = ["__all_contracts__"] + list(contracts_by_id.keys())
            
            selected_scope = st.selectbox(
                "Active Contract:",
                options=scope_options,
                format_func=lambda item: "All contracts" if item == "__all_contracts__" else f"{contracts_by_id.get(item, {}).get('display_name', item)}"
            )
            st.session_state.contract_id = None if selected_scope == "__all_contracts__" else selected_scope

st.title("Contract Analyzer")

current_messages = st.session_state.sessions[st.session_state.current_session_id]

# Display history
st.markdown('<div class="chat-container">', unsafe_allow_html=True)
for msg in current_messages:
    if msg["role"] == "user":
        st.markdown(f'<div class="chat-bubble-user">{msg["content"]}</div><div class="clearfix"></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="chat-bubble-assistant">{msg["content"]}</div>', unsafe_allow_html=True)
        if "citations" in msg and msg["citations"]:
            with st.expander("View Source Chunks"):
                for cit in msg["citations"]:
                    st.markdown(f"**From:** `{cit.get('source_document', 'Unknown')}`")
                    st.write(cit.get('text', 'No text provided.'))
                    st.divider()
        st.markdown('<div class="clearfix"></div>', unsafe_allow_html=True)
st.markdown('</div>', unsafe_allow_html=True)

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
    st.markdown(f'<div class="chat-bubble-user">{query}</div><div class="clearfix"></div>', unsafe_allow_html=True)
    
    with st.spinner("Analyzing contract..."):
        try:
            payload = {
                "question": query,
                "contract_id": st.session_state.contract_id,
            }
            result = _post_json("/ask", payload)
            answer = result.get("answer", "No answer generated.")
            citations = result.get("citations", [])
            
            # Append assistant message
            st.session_state.sessions[st.session_state.current_session_id].append({
                "role": "assistant",
                "content": answer,
                "citations": citations
            })
            st.rerun()
            
        except Exception as e:
            st.error(f"Error querying backend: {e}")
