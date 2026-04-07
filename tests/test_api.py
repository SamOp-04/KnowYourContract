from __future__ import annotations



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


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_metrics.db"
    app = create_app()
    with TestClient(app) as test_client:
        store = MetricsStore(database_url=f"sqlite:///{db_path}")
        store.init_db()
        app.state.metrics_store = store
        app.state.evaluator = _FakeEvaluator()
        app.state.pipeline = _FakePipeline()
        app.state.chat_scope_registry = ChatScopeRegistry(registry_path=tmp_path / "chat_scope_registry.json")
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
