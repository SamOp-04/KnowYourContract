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
    from dotenv import load_dotenv
except Exception:
    def load_dotenv() -> bool:  # type: ignore[no-redef]
        return False

try:
    from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
except Exception:
    HuggingFaceInferenceAPIEmbeddings = None

DEFAULT_FAISS_DIR = Path("data/processed/faiss_index")


load_dotenv()


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


def resolve_embeddings(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> Embeddings:
    hf_token = os.getenv("HF_TOKEN", "").strip()
    if HuggingFaceInferenceAPIEmbeddings is not None and hf_token:
        embedding_kwargs: dict[str, Any] = {
            "api_key": hf_token,
            "model_name": model_name,
        }
        api_url = os.getenv("HF_EMBEDDING_API_URL", "").strip()
        if api_url:
            embedding_kwargs["api_url"] = api_url
        return HuggingFaceInferenceAPIEmbeddings(**embedding_kwargs)

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
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
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
