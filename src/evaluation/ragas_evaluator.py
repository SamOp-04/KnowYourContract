from __future__ import annotations

import os
import re
from dataclasses import dataclass
from statistics import mean
from typing import Any

try:
    from datasets import Dataset
except Exception:
    Dataset = None

try:
    from ragas import evaluate
    from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

    RAGAS_AVAILABLE = True
except Exception:
    RAGAS_AVAILABLE = False


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_PATTERN.findall(text)}


def safe_divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def jaccard_similarity(left: str, right: str) -> float:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens and not right_tokens:
        return 1.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return safe_divide(intersection, union)


@dataclass
class EvalSample:
    question: str
    answer: str
    contexts: list[str]
    ground_truth: str


class RagasEvaluator:
    def __init__(self, use_ragas: bool = True) -> None:
        self.use_ragas = use_ragas and RAGAS_AVAILABLE and bool(os.getenv("OPENAI_API_KEY"))

    def evaluate_single(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str = "",
    ) -> dict[str, float]:
        if self.use_ragas:
            try:
                return self._evaluate_with_ragas(question, answer, contexts, ground_truth)
            except Exception:
                pass

        return self._evaluate_heuristic(question, answer, contexts, ground_truth)

    def evaluate_batch(self, samples: list[EvalSample]) -> list[dict[str, float]]:
        outputs = []
        for sample in samples:
            outputs.append(
                self.evaluate_single(
                    question=sample.question,
                    answer=sample.answer,
                    contexts=sample.contexts,
                    ground_truth=sample.ground_truth,
                )
            )
        return outputs

    def summarize(self, results: list[dict[str, float]]) -> dict[str, float]:
        if not results:
            return {
                "faithfulness": 0.0,
                "answer_relevance": 0.0,
                "context_precision": 0.0,
                "context_recall": 0.0,
            }

        return {
            "faithfulness": mean(item["faithfulness"] for item in results),
            "answer_relevance": mean(item["answer_relevance"] for item in results),
            "context_precision": mean(item["context_precision"] for item in results),
            "context_recall": mean(item["context_recall"] for item in results),
        }

    def _evaluate_with_ragas(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str,
    ) -> dict[str, float]:
        if Dataset is None:
            raise RuntimeError("The datasets package is required to run RAGAs evaluation.")

        dataset = Dataset.from_dict(
            {
                "question": [question],
                "answer": [answer],
                "contexts": [contexts],
                "ground_truth": [ground_truth],
            }
        )
        result = evaluate(
            dataset,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        )
        row = result.to_pandas().iloc[0]
        return {
            "faithfulness": float(row["faithfulness"]),
            "answer_relevance": float(row["answer_relevancy"]),
            "context_precision": float(row["context_precision"]),
            "context_recall": float(row["context_recall"]),
        }

    def _evaluate_heuristic(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str,
    ) -> dict[str, float]:
        context_blob = "\n".join(contexts)
        answer_sentences = [segment.strip() for segment in re.split(r"[.!?]", answer) if segment.strip()]

        if answer_sentences:
            sentence_support_scores = [jaccard_similarity(sentence, context_blob) for sentence in answer_sentences]
            faithfulness_score = mean(sentence_support_scores)
        else:
            faithfulness_score = 0.0

        answer_relevance_score = jaccard_similarity(question, answer)
        context_precision_score = mean([jaccard_similarity(question, context) for context in contexts]) if contexts else 0.0

        if ground_truth.strip():
            context_recall_score = jaccard_similarity(ground_truth, context_blob)
        else:
            context_recall_score = min(1.0, context_precision_score + 0.05)

        return {
            "faithfulness": round(faithfulness_score, 4),
            "answer_relevance": round(answer_relevance_score, 4),
            "context_precision": round(context_precision_score, 4),
            "context_recall": round(context_recall_score, 4),
        }
