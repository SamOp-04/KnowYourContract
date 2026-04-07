from __future__ import annotations

import argparse
import json
from io import BytesIO
from pathlib import Path
from typing import Any, TypeAlias

try:
    from datasets import Dataset as DatasetType, __version__ as DATASETS_VERSION, load_dataset

    DATASETS_SUPPORTS_TRUST_REMOTE_CODE = int(DATASETS_VERSION.split(".")[0]) < 4
except Exception:
    DatasetType: TypeAlias = Any
    DATASETS_SUPPORTS_TRUST_REMOTE_CODE = False

    def load_dataset(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError("The `datasets` package is required to load CUAD.")

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

PRIMARY_DATASET_ID = "theatticusproject/cuad"
FALLBACK_DATASET_IDS = (
    "theatticusproject/cuad-qa",
    "atticusdataset/cuad",
    "cuad",
)
DEFAULT_SPLIT = "train"
RAW_OUTPUT_PATH = Path("data/raw/cuad_train.jsonl")

TEXT_FIELD_CANDIDATES = ("contract_text", "context", "document_text", "text")
CONTRACT_ID_CANDIDATES = (
    "contract_name",
    "title",
    "filename",
    "document_id",
    "contract_id",
    "id",
)
QUESTION_FIELD_CANDIDATES = ("question", "query", "prompt")
CLAUSE_TYPE_CANDIDATES = ("clause_type", "category", "label", "question_type")
ANSWER_FIELD_CANDIDATES = ("answers", "answer", "ground_truth")
MAX_PDF_PAGES = 80


def _load_dataset_compat(dataset_id: str, split: str, verification_mode: str = "no_checks") -> DatasetType:
    """Load datasets with compatibility across datasets library versions."""
    try:
        return load_dataset(dataset_id, split=split, verification_mode=verification_mode)
    except TypeError:
        return load_dataset(dataset_id, split=split)
    except Exception as load_error:
        if not DATASETS_SUPPORTS_TRUST_REMOTE_CODE:
            raise load_error

        # Fallback path for older datasets versions that still rely on dataset scripts.
        try:
            return load_dataset(
                dataset_id,
                split=split,
                verification_mode=verification_mode,
                trust_remote_code=True,
            )
        except Exception:
            raise load_error


def load_cuad_dataset(dataset_id: str = PRIMARY_DATASET_ID, split: str = DEFAULT_SPLIT) -> DatasetType:
    """Load CUAD from HuggingFace with a fallback dataset id."""
    try:
        if dataset_id == PRIMARY_DATASET_ID:
            dataset = _load_dataset_compat(dataset_id=dataset_id, split=split)
        else:
            dataset = _load_dataset_compat(dataset_id=dataset_id, split=split)

        columns = set(getattr(dataset, "column_names", []))
        has_text_fields = any(field in columns for field in TEXT_FIELD_CANDIDATES)

        if not has_text_fields and dataset_id == PRIMARY_DATASET_ID:
            for fallback_dataset_id in FALLBACK_DATASET_IDS:
                try:
                    return _load_dataset_compat(dataset_id=fallback_dataset_id, split=split)
                except Exception:
                    continue

            return dataset

        return dataset
    except Exception as primary_error:
        if dataset_id != PRIMARY_DATASET_ID:
            raise RuntimeError(f"Failed to load dataset {dataset_id}") from primary_error

        for fallback_dataset_id in FALLBACK_DATASET_IDS:
            try:
                return _load_dataset_compat(dataset_id=fallback_dataset_id, split=split)
            except Exception:
                continue

        raise RuntimeError("Unable to load any CUAD dataset source.") from primary_error


def _first_available(row: dict[str, Any], candidates: tuple[str, ...], default: Any = None) -> Any:
    for key in candidates:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _normalize_answers(raw_answers: Any) -> list[str]:
    if raw_answers is None:
        return []

    if isinstance(raw_answers, str):
        return [raw_answers]

    if isinstance(raw_answers, list):
        normalized = [str(item) for item in raw_answers if item is not None and str(item).strip()]
        return normalized

    if isinstance(raw_answers, dict):
        if "text" in raw_answers and isinstance(raw_answers["text"], list):
            return [str(item) for item in raw_answers["text"] if str(item).strip()]
        if "text" in raw_answers and isinstance(raw_answers["text"], str):
            return [raw_answers["text"]]
        if "answer" in raw_answers and str(raw_answers["answer"]).strip():
            return [str(raw_answers["answer"])]

    return [str(raw_answers)]


def _extract_text_from_pdf_feature(pdf_feature: Any) -> str:
    if pdf_feature is None:
        return ""

    if hasattr(pdf_feature, "stream") and PdfReader is not None:
        stream = getattr(pdf_feature, "stream", None)
        if stream is not None and hasattr(stream, "read") and hasattr(stream, "seek"):
            try:
                start_position = stream.tell()
                stream.seek(0)
                raw_bytes = stream.read()
                stream.seek(start_position)

                reader = PdfReader(BytesIO(raw_bytes))
                texts = []
                for page in reader.pages[:MAX_PDF_PAGES]:
                    try:
                        page_text = page.extract_text() or ""
                    except Exception:
                        page_text = ""
                    if page_text.strip():
                        texts.append(page_text)

                if texts:
                    return "\n".join(texts)
            except Exception:
                pass

    if hasattr(pdf_feature, "pages"):
        texts = []
        for page in list(getattr(pdf_feature, "pages", []))[:MAX_PDF_PAGES]:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if page_text.strip():
                texts.append(page_text)

        try:
            pdf_feature.close()
        except Exception:
            pass

        return "\n".join(texts)

    if isinstance(pdf_feature, dict):
        raw_bytes = pdf_feature.get("bytes")
        if raw_bytes and PdfReader is not None:
            try:
                reader = PdfReader(BytesIO(raw_bytes))
                return "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception:
                return ""

    return ""


def _extract_contract_name_from_pdf(pdf_feature: Any, fallback_name: str) -> str:
    if pdf_feature is None:
        return fallback_name

    if hasattr(pdf_feature, "stream"):
        stream = getattr(pdf_feature, "stream", None)
        name = getattr(stream, "name", None)
        if name:
            return Path(str(name)).stem

    if isinstance(pdf_feature, dict):
        path = pdf_feature.get("path")
        if path:
            return Path(str(path)).stem

    return fallback_name


def normalize_row(row: dict[str, Any], row_index: int) -> dict[str, Any]:
    fallback_contract_name = f"contract_{row_index}"
    contract_name = _first_available(row, CONTRACT_ID_CANDIDATES, fallback_contract_name)
    contract_text = _first_available(row, TEXT_FIELD_CANDIDATES, "")
    pdf_feature = row.get("pdf")

    if not str(contract_text).strip() and pdf_feature is not None:
        contract_text = _extract_text_from_pdf_feature(pdf_feature)

    if contract_name == fallback_contract_name and pdf_feature is not None:
        contract_name = _extract_contract_name_from_pdf(pdf_feature, fallback_name=fallback_contract_name)

    question = _first_available(row, QUESTION_FIELD_CANDIDATES, "")
    clause_type = _first_available(row, CLAUSE_TYPE_CANDIDATES, "unknown")
    answers = _normalize_answers(_first_available(row, ANSWER_FIELD_CANDIDATES, []))

    return {
        "row_id": row_index,
        "contract_name": str(contract_name),
        "contract_text": str(contract_text),
        "question": str(question),
        "clause_type": str(clause_type),
        "answers": answers,
    }


def save_raw_rows(dataset: DatasetType, output_path: Path = RAW_OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for row_index, row in enumerate(dataset):
            normalized = normalize_row(dict(row), row_index)
            file.write(json.dumps(normalized) + "\n")
    return output_path


def build_contract_records(dataset: DatasetType) -> list[dict[str, Any]]:
    """Group question-centric CUAD rows into unique contract documents."""
    grouped: dict[str, dict[str, Any]] = {}

    for row_index, row in enumerate(dataset):
        normalized = normalize_row(dict(row), row_index)
        contract_name = normalized["contract_name"]
        contract_text = normalized["contract_text"]
        if not contract_text.strip():
            continue

        if contract_name not in grouped:
            grouped[contract_name] = {
                "contract_name": contract_name,
                "contract_text": contract_text,
                "clause_types": set(),
            }

        if normalized["clause_type"]:
            grouped[contract_name]["clause_types"].add(normalized["clause_type"])

    records: list[dict[str, Any]] = []
    for contract_name, payload in grouped.items():
        clause_types = sorted(payload["clause_types"])
        records.append(
            {
                "contract_name": contract_name,
                "contract_text": payload["contract_text"],
                "clause_type": clause_types[0] if clause_types else "mixed",
            }
        )

    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load CUAD and export normalized raw rows.")
    parser.add_argument("--dataset", default=PRIMARY_DATASET_ID, help="HuggingFace dataset id")
    parser.add_argument("--split", default=DEFAULT_SPLIT, help="Dataset split")
    parser.add_argument("--output", default=str(RAW_OUTPUT_PATH), help="JSONL output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_cuad_dataset(dataset_id=args.dataset, split=args.split)
    output_path = save_raw_rows(dataset, Path(args.output))
    print(f"Saved {len(dataset)} normalized rows to {output_path}")


if __name__ == "__main__":
    main()
