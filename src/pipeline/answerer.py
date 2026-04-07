from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

try:
    import requests
except Exception:
    requests = None

from src.pipeline.answerer_helpers import (
    build_answer_prompt,
    build_extractive_fallback_answer,
    normalize_answer,
)


@dataclass
class MistralAnswerer:
    model: str = os.getenv("OLLAMA_MODEL", "mistral")
    endpoint: str = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434/api/generate")
    timeout_seconds: float = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
    enable_cli_fallback: bool = os.getenv("OLLAMA_CLI_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}

    def answer(self, question: str, source_chunks: list[dict[str, Any]]) -> str:
        if not source_chunks:
            return "This contract does not contain a clause addressing that."

        prompt = build_answer_prompt(question=question, source_chunks=source_chunks)

        generated = self._answer_with_http(prompt=prompt)
        if generated:
            return generated

        generated = self._answer_with_ollama_cli(prompt=prompt)
        if generated:
            return generated

        return build_extractive_fallback_answer(question=question, source_chunks=source_chunks)

    def _answer_with_http(self, prompt: str) -> str:
        if requests is None:
            return ""

        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0},
            }
            response = requests.post(self.endpoint, json=payload, timeout=max(30.0, self.timeout_seconds))
            response.raise_for_status()
            body = response.json()
            return str(body.get("response", "")).strip()
        except Exception:
            return ""

    def _answer_with_ollama_cli(self, prompt: str) -> str:
        if not self.enable_cli_fallback:
            return ""

        if shutil.which("ollama") is None:
            return ""

        try:
            completed = subprocess.run(
                ["ollama", "run", self.model],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(30.0, self.timeout_seconds),
                check=False,
            )
        except Exception:
            return ""

        if completed.returncode != 0:
            return ""

        stdout = str(completed.stdout or "").strip()
        if not stdout:
            return ""

        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout).strip()

    def finalize_answer_with_sources(
        self,
        answer: str,
        source_chunks: list[dict[str, Any]],
        question: str = "",
    ) -> tuple[str, list[dict[str, Any]]]:
        sources = self.build_sources(source_chunks)
        if not sources:
            return answer.strip(), []

        cleaned = normalize_answer(answer)
        if not cleaned and question.strip():
            cleaned = f"Unable to produce a grounded answer for: {question.strip()}"
        if not re.search(r"\[\d+\]", cleaned):
            cleaned = f"{cleaned} [{sources[0]['index']}]"

        source_lines = "\n".join(f"[{item['index']}] {item['label']}" for item in sources)
        tagged_answer = f"{cleaned}\n\nSources:\n{source_lines}"
        return tagged_answer, sources

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
                    "section_heading": metadata.get("section_heading", ""),
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
