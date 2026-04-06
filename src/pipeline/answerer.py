from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

try:
    import requests
except Exception:
    requests = None


def _render_context(chunks: list[dict[str, Any]], max_chars_per_chunk: int = 1500) -> str:
    lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        metadata = dict(chunk.get("metadata", {}))
        chunk_id = str(chunk.get("chunk_id", metadata.get("chunk_id", f"chunk_{index}")))
        contract_name = str(metadata.get("contract_name", metadata.get("contract_id", "unknown_contract")))
        clause_type = str(metadata.get("clause_type", "general"))
        page_number = metadata.get("page_number")
        section_heading = str(metadata.get("section_heading", ""))
        text = str(chunk.get("text", "")).strip()

        prefix = (
            f"[{index}] chunk_id={chunk_id} contract={contract_name} "
            f"clause={clause_type} page={page_number} heading={section_heading}"
        )
        lines.append(f"{prefix}\n{text[:max_chars_per_chunk]}")

    return "\n\n".join(lines)


@dataclass
class MistralAnswerer:
    model: str = os.getenv("OLLAMA_MODEL", "mistral")
    endpoint: str = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate")
    timeout_seconds: float = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))

    def answer(self, question: str, source_chunks: list[dict[str, Any]]) -> str:
        if not source_chunks:
            return "This contract does not contain a clause addressing that."

        if self._question_likely_unanswered(question=question, source_chunks=source_chunks):
            return "This contract does not contain a clause addressing that."

        prompt = self._build_prompt(question=question, source_chunks=source_chunks)

        if requests is None:
            return "Could not reach the configured model backend to generate an answer."

        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0},
            }
            response = requests.post(self.endpoint, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            body = response.json()
            answer = str(body.get("response", "")).strip()
            if answer:
                return answer
        except Exception as error:
            return f"Could not generate an answer from model '{self.model}': {error}"

        return "Could not generate an answer from the model output."

    def finalize_answer_with_sources(self, answer: str, source_chunks: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        sources = self.build_sources(source_chunks)
        if not sources:
            return answer.strip(), []

        cleaned = answer.strip()
        if not re.search(r"\[\d+\]", cleaned):
            cleaned = f"{cleaned} [{sources[0]['index']}]"

        source_lines = "\n".join(f"[{item['index']}] {item['label']}" for item in sources)
        tagged_answer = f"{cleaned}\n\nSources:\n{source_lines}"
        return tagged_answer, sources

    def _build_prompt(self, question: str, source_chunks: list[dict[str, Any]]) -> str:
        context = "\n\n".join(str(chunk.get("text", "")) for chunk in source_chunks[:3] if str(chunk.get("text", "")).strip())
        return (
            "<s>[INST] You are a contract analysis assistant.\n"
            "Using only the contract excerpts below, answer the question clearly and specifically.\n"
            "If the answer is not in the excerpts, say \"This contract does not contain a clause addressing that.\"\n\n"
            "Cite evidence using bracket tags like [1], [2] mapped to sources.\n\n"
            f"Question:\n{question.strip()}\n\n"
            f"Contract excerpts:\n{context}\n"
            "[/INST]"
        )

    @staticmethod
    def _question_likely_unanswered(question: str, source_chunks: list[dict[str, Any]]) -> bool:
        lowered_question = question.lower()
        text_blob = "\n".join(str(chunk.get("text", "")) for chunk in source_chunks).lower()

        if "terminat" in lowered_question and "terminat" not in text_blob:
            return True
        if "indemn" in lowered_question and "indemn" not in text_blob:
            return True

        return False

    @staticmethod
    def build_citations(source_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        seen: set[str] = set()

        for chunk in source_chunks:
            metadata = dict(chunk.get("metadata", {}))
            chunk_id = str(chunk.get("chunk_id", metadata.get("chunk_id", "")))
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            citations.append(
                {
                    "chunk_id": chunk_id,
                    "contract_name": metadata.get("contract_name", metadata.get("contract_id", "")),
                    "clause_type": metadata.get("clause_type", ""),
                    "page_number": metadata.get("page_number"),
                    "url": "",
                }
            )

        return citations

    @staticmethod
    def build_sources(source_chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for chunk in source_chunks:
            metadata = dict(chunk.get("metadata", {}))
            contract_id = str(metadata.get("contract_id", metadata.get("contract_name", ""))).strip()
            source_name = str(metadata.get("source_name", "")).strip()
            label = source_name or contract_id or "Uploaded contract"

            key = (contract_id, label)
            if key in seen:
                continue
            seen.add(key)

            sources.append(
                {
                    "index": len(sources) + 1,
                    "label": label,
                    "contract_id": contract_id,
                }
            )

        return sources
