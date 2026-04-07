from __future__ import annotations

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
