from __future__ import annotations

import json
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

try:
    from rank_bm25 import BM25Okapi
except Exception:
    class BM25Okapi:  # type: ignore[no-redef]
        def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
            self.corpus = corpus
            self.k1 = k1
            self.b = b
            self.doc_count = len(corpus)
            self.avgdl = float(sum(len(doc) for doc in corpus)) / max(self.doc_count, 1)

            self.doc_freqs: list[dict[str, int]] = []
            self.df: dict[str, int] = {}
            for doc in corpus:
                freqs: dict[str, int] = {}
                for token in doc:
                    freqs[token] = freqs.get(token, 0) + 1
                self.doc_freqs.append(freqs)

                for token in freqs:
                    self.df[token] = self.df.get(token, 0) + 1

        def _idf(self, token: str) -> float:
            n_q = self.df.get(token, 0)
            numerator = self.doc_count - n_q + 0.5
            denominator = n_q + 0.5
            return float(np.log((numerator / max(denominator, 1e-12)) + 1.0))

        def get_scores(self, query_tokens: list[str]) -> np.ndarray:
            scores = np.zeros(self.doc_count, dtype=np.float64)
            if self.doc_count == 0:
                return scores

            for doc_idx, freqs in enumerate(self.doc_freqs):
                doc_len = len(self.corpus[doc_idx])
                for token in query_tokens:
                    if token not in freqs:
                        continue
                    tf = freqs[token]
                    idf = self._idf(token)
                    numerator = tf * (self.k1 + 1.0)
                    denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / max(self.avgdl, 1e-12)))
                    scores[doc_idx] += idf * (numerator / max(denominator, 1e-12))

            return scores

DEFAULT_CHUNKS_PATH = Path("data/processed/chunks.jsonl")
DEFAULT_BM25_PATH = Path("data/processed/bm25_index.pkl")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")


@dataclass
class SparseResult:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    score: float
    rank: int
    retriever: str = "sparse"


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def load_chunks(chunks_path: Path | str = DEFAULT_CHUNKS_PATH) -> list[dict[str, Any]]:
    path = Path(chunks_path)
    if not path.exists():
        raise FileNotFoundError(f"Chunk file not found: {path}")

    chunks: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def build_and_save_bm25(chunks: list[dict[str, Any]], output_path: Path | str = DEFAULT_BM25_PATH) -> Path:
    payload = []
    for chunk in chunks:
        payload.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "text": chunk.get("text", ""),
                "metadata": chunk.get("metadata", {}),
                "tokens": tokenize(chunk.get("text", "")),
            }
        )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as file:
        pickle.dump(payload, file)
    return output


class SparseRetriever:
    def __init__(
        self,
        chunks_path: Path | str = DEFAULT_CHUNKS_PATH,
        index_path: Path | str = DEFAULT_BM25_PATH,
    ) -> None:
        self.chunks_path = Path(chunks_path)
        self.index_path = Path(index_path)

        self.documents: list[dict[str, Any]] = []
        self.tokenized_corpus: list[list[str]] = []
        self.bm25: BM25Okapi | None = None

        self.reload()

    def reload(self) -> None:
        if self.index_path.exists():
            with self.index_path.open("rb") as file:
                stored_docs = pickle.load(file)
            self.documents = stored_docs
        elif self.chunks_path.exists():
            chunks = load_chunks(self.chunks_path)
            self.documents = [
                {
                    "chunk_id": chunk.get("chunk_id"),
                    "text": chunk.get("text", ""),
                    "metadata": chunk.get("metadata", {}),
                    "tokens": tokenize(chunk.get("text", "")),
                }
                for chunk in chunks
            ]
            build_and_save_bm25(chunks=chunks, output_path=self.index_path)
        else:
            raise FileNotFoundError(
                f"Neither BM25 index ({self.index_path}) nor chunks file ({self.chunks_path}) exists."
            )

        self.tokenized_corpus = [doc["tokens"] for doc in self.documents]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def get_top_k(self, query: str, k: int = 20) -> list[SparseResult]:
        if self.bm25 is None:
            raise RuntimeError("Sparse retriever is not initialized.")

        query_tokens = tokenize(query)
        scores = self.bm25.get_scores(query_tokens)
        if len(scores) == 0:
            return []

        top_indices = np.argsort(scores)[::-1][:k]
        results: list[SparseResult] = []

        for rank, index in enumerate(top_indices, start=1):
            score = float(scores[index])
            if score <= 0:
                continue

            doc = self.documents[int(index)]
            results.append(
                SparseResult(
                    chunk_id=str(doc["chunk_id"]),
                    text=str(doc["text"]),
                    metadata=dict(doc["metadata"]),
                    score=score,
                    rank=rank,
                )
            )

        return results
