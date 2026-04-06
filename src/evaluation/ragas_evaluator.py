from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from statistics import mean
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv() -> bool:  # type: ignore[no-redef]
        return False

try:
    import requests
except Exception:
    requests = None

# Avoid optional TensorFlow import path in transformers (requires tf-keras in this env).
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")

try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers import util as sentence_transformers_util
except Exception:
    SentenceTransformer = None
    sentence_transformers_util = None


load_dotenv()


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")
JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
_SEMANTIC_MODEL: Any | None = None
_SEMANTIC_MODEL_NAME: str | None = None


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


def _get_semantic_model(model_name: str) -> Any | None:
    global _SEMANTIC_MODEL, _SEMANTIC_MODEL_NAME

    if SentenceTransformer is None:
        return None

    if _SEMANTIC_MODEL is not None and _SEMANTIC_MODEL_NAME == model_name:
        return _SEMANTIC_MODEL

    _SEMANTIC_MODEL = SentenceTransformer(model_name)
    _SEMANTIC_MODEL_NAME = model_name
    return _SEMANTIC_MODEL


def semantic_similarity(left: str, right: str, model_name: str) -> float:
    if not left.strip() or not right.strip():
        return 0.0

    model = _get_semantic_model(model_name)
    if model is None or sentence_transformers_util is None:
        return jaccard_similarity(left, right)

    try:
        embeddings = model.encode([left, right], convert_to_tensor=True, normalize_embeddings=True)
        score = float(sentence_transformers_util.cos_sim(embeddings[0], embeddings[1]).item())
        return max(0.0, min(1.0, score))
    except Exception:
        return jaccard_similarity(left, right)


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if not text:
        raise RuntimeError("Ollama returned an empty response.")

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        text = fenced_match.group(1).strip()

    try:
        parsed_direct = json.loads(text)
        if isinstance(parsed_direct, dict):
            return parsed_direct
    except Exception:
        pass

    object_match = JSON_OBJECT_PATTERN.search(text)
    if not object_match:
        raise RuntimeError("No JSON object found in Ollama response.")

    parsed = json.loads(object_match.group(0))
    if not isinstance(parsed, dict):
        raise RuntimeError("Ollama response JSON is not an object.")
    return parsed


def _coerce_metric(payload: dict[str, Any], key: str) -> float:
    if key not in payload:
        raise RuntimeError(f"Missing key '{key}' in Ollama metric response.")

    value = float(payload[key])
    if not math.isfinite(value):
        raise RuntimeError(f"Metric '{key}' is not finite.")
    return round(max(0.0, min(1.0, value)), 4)


@dataclass
class OllamaLLM:
    model: str = "mistral"
    endpoint: str = "http://localhost:11434/api/generate"
    timeout_seconds: float = 90.0

    def _build_judge_prompt(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str,
    ) -> str:
        context_section = "\n\n".join(
            f"Context {index + 1}:\n{str(context).strip()[:1500]}"
            for index, context in enumerate(contexts[:4])
            if str(context).strip()
        )
        if not context_section:
            context_section = "No context provided."

        ground_truth_text = ground_truth.strip() or "No explicit ground truth provided."

        return (
            "[INST]\n"
            "You are a strict legal QA evaluator.\n"
            "Score the answer using these metrics in the range [0, 1]:\n"
            "- faithfulness: Is the answer supported by context evidence only?\n"
            "- answer_relevance: Does the answer address the question directly?\n"
            "- context_precision: Is the provided context focused on what the question needs?\n"
            "- context_recall: Does the context cover information needed to answer the question and ground truth?\n"
            "Return ONLY valid JSON with exactly these keys: faithfulness, answer_relevance, context_precision, context_recall.\n"
            "No markdown, no explanation, no extra keys.\n\n"
            f"Question:\n{question.strip()}\n\n"
            f"Answer:\n{answer.strip()}\n\n"
            f"Contexts:\n{context_section}\n\n"
            f"Ground truth:\n{ground_truth_text}\n"
            "[/INST]"
        )

    def score(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str,
    ) -> dict[str, float]:
        if requests is None:
            raise RuntimeError("requests package is required for Ollama judge scoring.")

        prompt = self._build_judge_prompt(question, answer, contexts, ground_truth)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        }

        response = requests.post(self.endpoint, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()

        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Ollama response payload is not a JSON object.")

        response_text = body.get("response", "")
        if not isinstance(response_text, str) or not response_text.strip():
            raise RuntimeError("Ollama response is missing generated text.")

        parsed = _extract_json_object(response_text)
        return {
            "faithfulness": _coerce_metric(parsed, "faithfulness"),
            "answer_relevance": _coerce_metric(parsed, "answer_relevance"),
            "context_precision": _coerce_metric(parsed, "context_precision"),
            "context_recall": _coerce_metric(parsed, "context_recall"),
        }


@dataclass
class EvalSample:
    question: str
    answer: str
    contexts: list[str]
    ground_truth: str


class RagasEvaluator:
    def __init__(self, use_ragas: bool = True) -> None:
        self._semantic_model_name = os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self.use_ragas = use_ragas
        self._ollama = OllamaLLM(
            model=os.getenv("OLLAMA_MODEL", "mistral"),
            endpoint=os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate"),
            timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90")),
        )

    def evaluate_single(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ground_truth: str = "",
    ) -> dict[str, Any]:
        fallback_reason = ""

        if self.use_ragas:
            try:
                ollama_scores = self._ollama.score(question, answer, contexts, ground_truth)
                if self._metrics_are_finite(ollama_scores):
                    ollama_scores["score_source"] = "ollama_mistral"
                    return ollama_scores
            except (Exception, KeyboardInterrupt) as error:
                fallback_reason = str(error)

        fallback_scores = self._evaluate_heuristic(question, answer, contexts, ground_truth)
        fallback_scores["score_source"] = "semantic_fallback"
        if fallback_reason:
            fallback_scores["fallback_reason"] = fallback_reason[:300]
        return fallback_scores

    @staticmethod
    def _metrics_are_finite(metrics: dict[str, float]) -> bool:
        required = ("faithfulness", "answer_relevance", "context_precision", "context_recall")
        for key in required:
            value = metrics.get(key)
            if value is None:
                return False
            try:
                if not math.isfinite(float(value)):
                    return False
            except Exception:
                return False
        return True

    def evaluate_batch(self, samples: list[EvalSample]) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
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

    def summarize(self, results: list[dict[str, Any]]) -> dict[str, float]:
        if not results:
            return {
                "faithfulness": 0.0,
                "answer_relevance": 0.0,
                "context_precision": 0.0,
                "context_recall": 0.0,
            }

        return {
            "faithfulness": mean(float(item["faithfulness"]) for item in results),
            "answer_relevance": mean(float(item["answer_relevance"]) for item in results),
            "context_precision": mean(float(item["context_precision"]) for item in results),
            "context_recall": mean(float(item["context_recall"]) for item in results),
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
            sentence_support_scores = [
                semantic_similarity(sentence, context_blob, model_name=self._semantic_model_name)
                for sentence in answer_sentences
            ]
            faithfulness_score = mean(sentence_support_scores)
        else:
            faithfulness_score = 0.0

        answer_relevance_score = semantic_similarity(question, answer, model_name=self._semantic_model_name)
        context_precision_score = (
            mean([semantic_similarity(question, context, model_name=self._semantic_model_name) for context in contexts])
            if contexts
            else 0.0
        )

        if ground_truth.strip():
            context_recall_score = semantic_similarity(ground_truth, context_blob, model_name=self._semantic_model_name)
        else:
            context_recall_score = min(1.0, context_precision_score + 0.05)

        return {
            "faithfulness": round(faithfulness_score, 4),
            "answer_relevance": round(answer_relevance_score, 4),
            "context_precision": round(context_precision_score, 4),
            "context_recall": round(context_recall_score, 4),
        }
