import hashlib
import numpy as np
from langchain_core.embeddings import Embeddings

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

_shared_hash_embeddings: HashEmbeddings | None = None

def get_hash_embeddings(dimensions: int = 384) -> HashEmbeddings:
    """Return a singleton instance of HashEmbeddings to prevent memory state duplication."""
    global _shared_hash_embeddings
    if _shared_hash_embeddings is None or _shared_hash_embeddings.dimensions != dimensions:
        _shared_hash_embeddings = HashEmbeddings(dimensions=dimensions)
    return _shared_hash_embeddings
