from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

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
    from langchain_openai import OpenAIEmbeddings
except Exception:
    OpenAIEmbeddings = None

DEFAULT_FAISS_DIR = Path("data/processed/faiss_index")


class HashEmbeddings(Embeddings):
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


def resolve_embeddings(model_name: str = "text-embedding-3-small") -> Embeddings:
    if OpenAIEmbeddings is not None and os.getenv("OPENAI_API_KEY"):
        return OpenAIEmbeddings(model=model_name)
    return HashEmbeddings()


@dataclass
class DenseResult:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    score: float
    rank: int
    retriever: str = "dense"


class DenseRetriever:
    def __init__(
        self,
        index_dir: Path | str = DEFAULT_FAISS_DIR,
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        self.index_dir = Path(index_dir)
        self.embedding_model = embedding_model
        self.vector_store: Any | None = None
        self.reload()

    def reload(self) -> None:
        if FAISS is None:
            raise RuntimeError("langchain-community is required for FAISS retrieval.")

        if not self.index_dir.exists():
            raise FileNotFoundError(
                f"FAISS index directory not found: {self.index_dir}. Run embedding pipeline first."
            )

        embeddings = resolve_embeddings(model_name=self.embedding_model)
        self.vector_store = FAISS.load_local(
            str(self.index_dir),
            embeddings,
            allow_dangerous_deserialization=True,
        )

    def get_top_k(self, query: str, k: int = 20) -> list[DenseResult]:
        if self.vector_store is None:
            raise RuntimeError("Dense retriever is not initialized.")

        raw_results = self.vector_store.similarity_search_with_score(query, k=k)
        results: list[DenseResult] = []

        for rank, (document, score) in enumerate(raw_results, start=1):
            metadata = dict(document.metadata or {})
            chunk_id = str(metadata.get("chunk_id", f"dense_{rank}"))
            results.append(
                DenseResult(
                    chunk_id=chunk_id,
                    text=document.page_content,
                    metadata=metadata,
                    score=float(score),
                    rank=rank,
                )
            )

        return results
