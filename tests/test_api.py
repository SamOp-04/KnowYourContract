from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.evaluation.metrics_store import MetricsStore


@dataclass
class _FakeEvaluator:
    def evaluate_single(self, question: str, answer: str, contexts: list[str], ground_truth: str = ""):
        return {
            "faithfulness": 0.95,
            "answer_relevance": 0.88,
            "context_precision": 0.84,
            "context_recall": 0.78,
        }


@dataclass
class _FakeAgent:
    def run(self, query: str, contract_id: str | None = None):
        return {
            "answer": "The indemnification cap is limited to direct damages.",
            "tool_used": "contract_search",
            "route_reason": "Query is about a contract clause.",
            "used_web_fallback": False,
            "citations": [
                {
                    "chunk_id": "c1",
                    "contract_name": "sample_contract",
                    "clause_type": "indemnification",
                    "page_number": 4,
                    "url": "",
                }
            ],
            "source_chunks": [
                {
                    "chunk_id": "c1",
                    "text": "Indemnification clause text",
                    "metadata": {"contract_name": "sample_contract", "clause_type": "indemnification"},
                }
            ],
        }


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_metrics.db"
    app = create_app()
    with TestClient(app) as test_client:
        store = MetricsStore(database_url=f"sqlite:///{db_path}")
        store.init_db()
        app.state.metrics_store = store
        app.state.evaluator = _FakeEvaluator()
        app.state.agent = _FakeAgent()
        yield test_client


def test_query_endpoint_returns_answer(client: TestClient) -> None:
    response = client.post("/query", json={"query": "What is the indemnification cap?", "contract_id": None})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_used"] == "contract_search"
    assert "indemnification cap" in payload["answer"].lower()


def test_metrics_endpoint_returns_recent_rows(client: TestClient) -> None:
    client.post("/query", json={"query": "What is termination for convenience?"})
    response = client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert "recent" in payload
    assert "trends" in payload
    assert "analytics" in payload


def test_upload_endpoint_rejects_empty_file(client: TestClient) -> None:
    response = client.post(
        "/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 400
