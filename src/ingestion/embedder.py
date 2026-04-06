from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

try:
    import boto3
except Exception:
    boto3 = None

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

from src.ingestion.chunker import DEFAULT_OUTPUT_PATH, build_chunks_from_cuad, save_chunks

DEFAULT_FAISS_DIR = Path("data/processed/faiss_index")
DEFAULT_METADATA_PATH = Path("data/processed/chunk_metadata.json")
DEFAULT_BM25_PATH = Path("data/processed/bm25_index.pkl")


load_dotenv()


class HashEmbeddings(Embeddings):
    """Deterministic local fallback embeddings for offline development and tests."""

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


def load_chunks(chunks_path: Path = DEFAULT_OUTPUT_PATH) -> list[dict[str, Any]]:
    if not chunks_path.exists():
        raise FileNotFoundError(
            f"Chunks file not found at {chunks_path}. Run `python -m src.ingestion.chunker` first."
        )

    chunks: list[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def build_faiss_index(
    chunks: list[dict[str, Any]],
    output_dir: Path = DEFAULT_FAISS_DIR,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> Path:
    if FAISS is None:
        raise RuntimeError("langchain-community is required to build FAISS indexes.")

    output_dir.mkdir(parents=True, exist_ok=True)
    embeddings = resolve_embeddings(model_name=model_name)

    texts = [chunk["text"] for chunk in chunks]
    metadatas = []
    for chunk in chunks:
        metadata = dict(chunk.get("metadata", {}))
        metadata["chunk_id"] = chunk.get("chunk_id")
        metadatas.append(metadata)

    vector_store = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas)
    vector_store.save_local(str(output_dir))
    return output_dir


def save_metadata(chunks: list[dict[str, Any]], output_path: Path = DEFAULT_METADATA_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "metadata": chunk.get("metadata", {}),
        }
        for chunk in chunks
    ]

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2)

    return output_path


def build_sparse_index(chunks: list[dict[str, Any]], output_path: Path = DEFAULT_BM25_PATH) -> Path:
    from src.retrieval.sparse_retriever import build_and_save_bm25

    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_and_save_bm25(chunks=chunks, output_path=output_path)
    return output_path


def upload_faiss_to_s3(index_dir: Path, bucket: str, key: str, region: str) -> str:
    """Archive and upload local FAISS artifacts so ECS tasks can load them at startup."""
    if not bucket:
        raise ValueError("S3 bucket name is required.")
    if boto3 is None:
        raise RuntimeError("boto3 is required to upload FAISS artifacts to S3.")

    s3_client = boto3.client("s3", region_name=region)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as temp_archive:
        archive_path = Path(temp_archive.name)

    with tarfile.open(archive_path, "w:gz") as archive:
        for child in index_dir.iterdir():
            archive.add(child, arcname=child.name)

    s3_client.upload_file(str(archive_path), bucket, key)
    return f"s3://{bucket}/{key}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FAISS and BM25 indexes from processed chunks.")
    parser.add_argument("--chunks", default=str(DEFAULT_OUTPUT_PATH), help="Path to chunked JSONL file")
    parser.add_argument("--faiss-dir", default=str(DEFAULT_FAISS_DIR), help="Path to save FAISS index")
    parser.add_argument("--metadata", default=str(DEFAULT_METADATA_PATH), help="Path to save chunk metadata")
    parser.add_argument("--embedding-model", default="sentence-transformers/all-MiniLM-L6-v2", help="Embedding model id")
    parser.add_argument("--upload-s3", action="store_true", help="Upload FAISS artifacts to S3")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    chunks_path = Path(args.chunks)

    if not chunks_path.exists():
        chunks = build_chunks_from_cuad()
        save_chunks(chunks, chunks_path)
    else:
        chunks = load_chunks(chunks_path)

    faiss_dir = build_faiss_index(chunks=chunks, output_dir=Path(args.faiss_dir), model_name=args.embedding_model)
    metadata_path = save_metadata(chunks=chunks, output_path=Path(args.metadata))
    bm25_path = build_sparse_index(chunks=chunks)

    print(f"Saved FAISS index to {faiss_dir}")
    print(f"Saved metadata to {metadata_path}")
    print(f"Saved BM25 index to {bm25_path}")

    if args.upload_s3:
        bucket = os.getenv("S3_FAISS_BUCKET", "")
        key = os.getenv("S3_FAISS_KEY", "faiss/legal_contracts/index.tar.gz")
        region = os.getenv("AWS_REGION", "us-east-1")
        s3_uri = upload_faiss_to_s3(index_dir=faiss_dir, bucket=bucket, key=key, region=region)
        print(f"Uploaded FAISS artifacts to {s3_uri}")


if __name__ == "__main__":
    main()
