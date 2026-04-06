from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from src.evaluation.metrics_store import MetricsStore
from src.evaluation.ragas_evaluator import RagasEvaluator
from src.ingestion.loader import load_cuad_dataset, normalize_row

DEFAULT_EVAL_PATH = Path("data/eval_samples/cuad_eval_samples.jsonl")
DEFAULT_RAW_PATH = Path("data/raw/cuad_train.jsonl")
DEFAULT_CUAD_QA_JSON = "hf://datasets/theatticusproject/cuad/CUAD_v1/CUAD_v1.json"

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def _load_raw_rows(raw_path: Path = DEFAULT_RAW_PATH) -> list[dict[str, Any]]:
    if not raw_path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with raw_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def extract_relevant_passage(text: str, question: str, window: int = 700) -> str:
    normalized = " ".join(str(text).split())
    if not normalized:
        return ""

    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", normalized) if segment.strip()]
    if not sentences:
        return normalized[:window]

    question_tokens = {
        token.lower()
        for token in TOKEN_PATTERN.findall(question)
        if len(token) > 2
    }
    if not question_tokens:
        return normalized[:window]

    scored = []
    for index, sentence in enumerate(sentences):
        lowered = sentence.lower()
        score = sum(1 for token in question_tokens if token in lowered)
        scored.append((score, index, sentence))

    best_index = max(scored, key=lambda item: item[0])[1]
    start = max(0, best_index - 2)
    candidate = ". ".join(sentences[start : start + 8]).strip()
    if not candidate:
        candidate = normalized
    return candidate[:window]


def _build_synthetic_eval_rows(rows: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    text_rows = [row for row in rows if str(row.get("contract_text", "")).strip()]
    if not text_rows:
        return []

    random.seed(42)
    sampled = random.sample(text_rows, k=min(sample_size, len(text_rows)))
    synthetic: list[dict[str, Any]] = []

    for item in sampled:
        contract_name = str(item.get("contract_name", "contract"))
        question = f"Summarize obligations, risks, and liability terms in contract {contract_name}."
        full_text = str(item.get("contract_text", ""))
        context = full_text[:3000]
        ground_truth = extract_relevant_passage(full_text, question=question, window=700)
        if not ground_truth.strip():
            ground_truth = context[:700]
        answer = ground_truth

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


def _build_real_eval_rows_from_cuad_json(sample_size: int) -> list[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except Exception:
        return []

    data_path = DEFAULT_CUAD_QA_JSON
    try:
        dataset = load_dataset("json", data_files=data_path, split="train")
        if not dataset:
            return []

        payload = dataset[0]
        data_items = payload.get("data", []) if isinstance(payload, dict) else []
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for item in data_items:
        if not isinstance(item, dict):
            continue

        contract_name = str(item.get("title", "contract"))
        paragraphs = item.get("paragraphs", [])
        if not isinstance(paragraphs, list):
            continue

        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue

            context_blob = str(paragraph.get("context", ""))
            if not context_blob.strip():
                continue

            qas = paragraph.get("qas", [])
            if not isinstance(qas, list):
                continue

            for qa in qas:
                if not isinstance(qa, dict):
                    continue

                question = str(qa.get("question", "")).strip()
                if not question:
                    continue

                answers = qa.get("answers", [])
                if not isinstance(answers, list):
                    continue

                answer_texts = [
                    str(answer.get("text", "")).strip()
                    for answer in answers
                    if isinstance(answer, dict) and str(answer.get("text", "")).strip()
                ]
                if not answer_texts:
                    continue

                ground_truth = answer_texts[0]
                context = extract_relevant_passage(context_blob, question=question, window=3000)
                if not context.strip():
                    context = context_blob[:3000]

                rows.append(
                    {
                        "question": question,
                        "ground_truth": ground_truth,
                        "contexts": [context],
                        "answer": ground_truth,
                        "tool_used": "offline_eval_real_qa",
                        "contract_name": contract_name,
                    }
                )

    if not rows:
        return []

    random.seed(42)
    return random.sample(rows, k=min(sample_size, len(rows)))


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
        sampled = _build_real_eval_rows_from_cuad_json(sample_size=sample_size)

    if not sampled:
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
    synthetic_count = sum(1 for sample in raw_samples if sample.get("tool_used") == "offline_eval_synthetic")
    if synthetic_count:
        print(
            "Warning: "
            f"{synthetic_count}/{len(raw_samples)} samples are synthetic (offline_eval_synthetic), "
            "metrics may be conservative."
        )

    evaluator = RagasEvaluator(use_ragas=True)
    store = MetricsStore()
    store.init_db()

    results: list[dict[str, Any]] = []
    for sample in raw_samples:
        eval_metrics = evaluator.evaluate_single(
            question=sample.get("question", ""),
            answer=sample.get("answer", ""),
            contexts=sample.get("contexts", []),
            ground_truth=sample.get("ground_truth", ""),
        )
        score_source = str(eval_metrics.get("score_source", "unknown"))
        print(f"score_source: {score_source}")

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
