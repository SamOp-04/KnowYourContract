from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except Exception:
    class RecursiveCharacterTextSplitter:  # type: ignore[no-redef]
        def __init__(self, chunk_size: int, chunk_overlap: int, separators: list[str], length_function) -> None:
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap

        def split_text(self, text: str) -> list[str]:
            chunks = []
            start = 0
            while start < len(text):
                end = min(start + self.chunk_size, len(text))
                chunks.append(text[start:end])
                if end == len(text):
                    break
                start = max(end - self.chunk_overlap, 0)
            return chunks

from src.ingestion.loader import build_contract_records, load_cuad_dataset

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 64
DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " "]
DEFAULT_OUTPUT_PATH = Path("data/processed/chunks.jsonl")
DEFAULT_RAW_PATH = Path("data/raw/cuad_train.jsonl")
APPROX_CHARS_PER_PAGE = 3200


def build_splitter(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    separators: list[str] | None = None,
) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=separators or DEFAULT_SEPARATORS,
        length_function=len,
    )


def _safe_chunk_id(contract_name: str, chunk_index: int) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in contract_name.lower())
    return f"{normalized}_{chunk_index}"


def _find_chunk_span(full_text: str, chunk_text: str, search_start: int) -> tuple[int, int]:
    start = full_text.find(chunk_text, search_start)
    if start < 0:
        start = full_text.find(chunk_text)
    if start < 0:
        start = max(search_start, 0)

    end = start + len(chunk_text)
    return start, end


def chunk_contract(contract: dict[str, Any], splitter: RecursiveCharacterTextSplitter) -> list[dict[str, Any]]:
    contract_text = contract.get("contract_text", "")
    if not contract_text.strip():
        return []

    contract_name = str(contract.get("contract_name", "unknown_contract"))
    clause_type = str(contract.get("clause_type", "unknown"))
    raw_chunks = splitter.split_text(contract_text)

    chunks: list[dict[str, Any]] = []
    cursor = 0
    for chunk_index, chunk_text in enumerate(raw_chunks):
        char_start, char_end = _find_chunk_span(contract_text, chunk_text, cursor)
        cursor = max(char_end - DEFAULT_CHUNK_OVERLAP, 0)
        page_number = (char_start // APPROX_CHARS_PER_PAGE) + 1

        chunks.append(
            {
                "chunk_id": _safe_chunk_id(contract_name, chunk_index),
                "text": chunk_text,
                "metadata": {
                    "contract_name": contract_name,
                    "clause_type": clause_type,
                    "page_number": page_number,
                    "char_start": char_start,
                    "char_end": char_end,
                },
            }
        )

    return chunks


def load_contract_records_from_raw(
    raw_path: Path = DEFAULT_RAW_PATH,
    limit_contracts: int | None = None,
) -> list[dict[str, Any]]:
    if not raw_path.exists():
        return []

    grouped: dict[str, dict[str, Any]] = {}
    with raw_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            row = json.loads(line)
            contract_name = str(row.get("contract_name", "")).strip()
            contract_text = str(row.get("contract_text", "")).strip()
            clause_type = str(row.get("clause_type", "unknown")).strip() or "unknown"

            if not contract_name or not contract_text:
                continue

            if contract_name not in grouped:
                if limit_contracts is not None and len(grouped) >= limit_contracts:
                    continue

                grouped[contract_name] = {
                    "contract_name": contract_name,
                    "contract_text": contract_text,
                    "clause_type": clause_type,
                }

    return list(grouped.values())


def build_chunks_from_cuad(split: str = "train", limit_contracts: int | None = None) -> list[dict[str, Any]]:
    records = load_contract_records_from_raw(limit_contracts=limit_contracts)
    if not records:
        dataset = load_cuad_dataset(split=split)

        if limit_contracts is not None:
            dataset = dataset.select(range(min(limit_contracts, len(dataset))))

        records = build_contract_records(dataset)

    splitter = build_splitter()
    all_chunks: list[dict[str, Any]] = []
    for record in records:
        all_chunks.extend(chunk_contract(record, splitter))

    return all_chunks


def save_chunks(chunks: list[dict[str, Any]], output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk) + "\n")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chunk CUAD contracts into retrieval-ready JSONL chunks.")
    parser.add_argument("--split", default="train", help="Dataset split")
    parser.add_argument("--limit-contracts", type=int, default=None, help="Optional limit for quick iteration")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Output JSONL for processed chunks")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    chunks = build_chunks_from_cuad(split=args.split, limit_contracts=args.limit_contracts)
    output_path = save_chunks(chunks, output_path=Path(args.output))
    print(f"Saved {len(chunks)} chunks to {output_path}")


if __name__ == "__main__":
    main()
