from __future__ import annotations

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
