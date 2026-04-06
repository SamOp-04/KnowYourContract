from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from src.evaluation.metrics_store import MetricsStore
from src.evaluation.ragas_evaluator import RagasEvaluator
from src.ingestion.loader import load_cuad_dataset, normalize_row

DEFAULT_EVAL_PATH = Path("data/eval_samples/cuad_eval_samples.jsonl")
DEFAULT_RAW_PATH = Path("data/raw/cuad_train.jsonl")


def _load_raw_rows(raw_path: Path = DEFAULT_RAW_PATH) -> list[dict[str, Any]]:
    if not raw_path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with raw_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _build_synthetic_eval_rows(rows: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    text_rows = [row for row in rows if str(row.get("contract_text", "")).strip()]
    if not text_rows:
        return []

    random.seed(42)
    sampled = random.sample(text_rows, k=min(sample_size, len(text_rows)))
    synthetic: list[dict[str, Any]] = []

    for item in sampled:
        contract_name = str(item.get("contract_name", "contract"))
        context = str(item.get("contract_text", ""))[:2500]
        ground_truth = context[:600]
        question = f"Summarize obligations, risks, and liability terms in contract {contract_name}."
        answer = ground_truth[:350]

        synthetic.append(
            {
                "question": question,
                "ground_truth": ground_truth,
                "contexts": [context],
                "answer": answer,
                "tool_used": "offline_eval_synthetic",
            }
        )

    return synthetic


def build_eval_samples(sample_size: int = 100, output_path: Path = DEFAULT_EVAL_PATH) -> Path:
    rows = _load_raw_rows()
    qa_rows = [
        row
        for row in rows
        if str(row.get("question", "")).strip() and str(row.get("contract_text", "")).strip()
    ]

    if qa_rows:
        random.seed(42)
        sampled = random.sample(qa_rows, k=min(sample_size, len(qa_rows)))
    else:
        sampled = _build_synthetic_eval_rows(rows=rows, sample_size=sample_size)

    if not sampled:
        dataset = load_cuad_dataset(split="train")
        normalized_rows = [normalize_row(dict(row), index) for index, row in enumerate(dataset)]
        filtered_rows = [row for row in normalized_rows if row["question"].strip() and row["contract_text"].strip()]
        random.seed(42)
        sampled = random.sample(filtered_rows, k=min(sample_size, len(filtered_rows)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for item in sampled:
            record = {
                "question": item.get("question", ""),
                "ground_truth": (
                    item.get("ground_truth", "")
                    if "ground_truth" in item
                    else (item.get("answers", [""])[0] if item.get("answers") else "")
                ),
                "contexts": item.get("contexts", [item.get("contract_text", "")[:2500]]),
                "answer": (
                    item.get("answer", "")
                    if "answer" in item
                    else (item.get("answers", [""])[0] if item.get("answers") else "")
                ),
                "tool_used": item.get("tool_used", "offline_eval"),
            }
            file.write(json.dumps(record) + "\n")

    return output_path


def load_eval_samples(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                samples.append(json.loads(line))
    return samples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run batch RAG evaluation over CUAD samples.")
    parser.add_argument("--sample-size", type=int, default=100, help="Number of Q&A pairs to evaluate")
    parser.add_argument("--samples-path", default=str(DEFAULT_EVAL_PATH), help="JSONL eval samples path")
    parser.add_argument("--build-samples", action="store_true", help="Build sample file from CUAD before eval")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples_path = Path(args.samples_path)

    if args.build_samples or not samples_path.exists():
        samples_path = build_eval_samples(sample_size=args.sample_size, output_path=samples_path)

    raw_samples = load_eval_samples(samples_path)
    evaluator = RagasEvaluator(use_ragas=True)
    store = MetricsStore()
    store.init_db()

    results: list[dict[str, float]] = []
    for sample in raw_samples:
        eval_metrics = evaluator.evaluate_single(
            question=sample.get("question", ""),
            answer=sample.get("answer", ""),
            contexts=sample.get("contexts", []),
            ground_truth=sample.get("ground_truth", ""),
        )
        payload = {
            "query": sample.get("question", ""),
            "answer": sample.get("answer", ""),
            "tool_used": sample.get("tool_used", "offline_eval"),
            "used_web_fallback": False,
            **eval_metrics,
        }
        store.save_metric(payload)

        results.append(eval_metrics)

    summary = evaluator.summarize(results)
    print(f"Evaluated {len(raw_samples)} samples from {samples_path}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
