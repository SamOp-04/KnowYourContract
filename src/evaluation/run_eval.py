from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from src.evaluation.metrics_store import MetricsStore
from src.evaluation.ragas_evaluator import EvalSample, RagasEvaluator
from src.ingestion.loader import load_cuad_dataset, normalize_row

DEFAULT_EVAL_PATH = Path("data/eval_samples/cuad_eval_samples.jsonl")


def build_eval_samples(sample_size: int = 100, output_path: Path = DEFAULT_EVAL_PATH) -> Path:
    dataset = load_cuad_dataset(split="train")
    rows = [normalize_row(dict(row), index) for index, row in enumerate(dataset)]
    rows = [row for row in rows if row["question"].strip() and row["contract_text"].strip()]

    random.seed(42)
    sampled = random.sample(rows, k=min(sample_size, len(rows)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for item in sampled:
            record = {
                "question": item["question"],
                "ground_truth": item["answers"][0] if item["answers"] else "",
                "contexts": [item["contract_text"][:2500]],
                "answer": item["answers"][0] if item["answers"] else "",
                "tool_used": "offline_eval",
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

    results = []
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

        results.append(EvalSample(**{**sample, "answer": sample.get("answer", "")}))

    summary = evaluator.summarize([evaluator.evaluate_single(s.question, s.answer, s.contexts, s.ground_truth) for s in results])
    print(f"Evaluated {len(raw_samples)} samples from {samples_path}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
