from __future__ import annotations

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


def test_vector_store_resets_incompatible_chroma_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline_embedder,
        "resolve_embeddings",
        lambda model_name: get_hash_embeddings(),
    )

    persist_dir = tmp_path / "chroma_broken"
    persist_dir.mkdir(parents=True, exist_ok=True)
    marker = persist_dir / "marker.txt"
    marker.write_text("stale", encoding="utf-8")

    class _FlakyChroma:
        calls = 0

        def __init__(self, **kwargs) -> None:
            _ = kwargs
            type(self).calls += 1
            if type(self).calls == 1:
                raise KeyError("_type")

        def get(self, include=None):
            _ = include
            return {"ids": []}

    monkeypatch.setattr(pipeline_embedder, "Chroma", _FlakyChroma)

    vector_store = pipeline_embedder.ContractVectorStore(
        persist_directory=persist_dir,
        collection_name="contracts_recover",
        artifact_store=None,
    )

    store = vector_store.get_store()
    assert isinstance(store, _FlakyChroma)
    assert _FlakyChroma.calls == 2

    backups = list(tmp_path.glob("chroma_broken_corrupt_*"))
    assert backups
    assert (backups[0] / "marker.txt").exists()
