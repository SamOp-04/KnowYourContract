from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np

try:
    from langchain_core.embeddings import Embeddings
except Exception:
    class Embeddings:  # type: ignore[no-redef]
        pass

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


def resolve_embeddings(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> Embeddings:
    if HuggingFaceEmbeddings is not None:
        try:
            return HuggingFaceEmbeddings(model_name=model_name)
        except Exception:
            pass

    return HashEmbeddings()


class ContractVectorStore:
    def __init__(
        self,
        persist_directory: Path | str = Path("data/processed/chroma"),
        collection_name: str = "contracts",
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self.persist_directory = Path(persist_directory)
        self.collection_name = collection_name
        self.embeddings = resolve_embeddings(model_name=embedding_model)
        self._store: Any | None = None

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
            try:
                store.delete(where={"contract_id": contract_id})
            except Exception:
                # Some vector store adapters raise when no records match.
                pass

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
        return len(chunks)
