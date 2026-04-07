from __future__ import annotations

import re
from typing import Any

_NUMBER_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_STOPWORDS = {
    "what",
    "when",
    "where",
    "which",
    "that",
    "this",
    "with",
    "from",
    "under",
    "about",
    "must",
    "shall",
    "would",
    "could",
    "should",
}


def render_context(chunks: list[dict[str, Any]], max_chars_per_chunk: int = 1500) -> str:
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


def build_answer_prompt(question: str, source_chunks: list[dict[str, Any]]) -> str:
    context = render_context(chunks=source_chunks[:12], max_chars_per_chunk=1200)
    return (
        "<s>[INST] You are an expert legal contract analysis assistant.\n"
        "Answer the question using only the contract excerpts.\n"
        "If not specified, respond exactly with: \"This information is not specified in the contract.\"\n"
        "Keep the answer concise, factual, and cite support using [1], [2] style references.\n\n"
        "[CONTRACT EXCERPTS]\n"
        f"{context}\n\n"
        "[QUESTION]\n"
        f"{question.strip()}\n\n"
        "Answer: [/INST]"
    )


def normalize_answer(answer: str) -> str:
    cleaned = answer.strip()
    cleaned = _remove_inconsistent_count_intro(cleaned)
    return cleaned.strip()


def _remove_inconsistent_count_intro(text: str) -> str:
    numbered_count = len(re.findall(r"^\s*\d+\.\s", text, flags=re.MULTILINE))
    if numbered_count < 2:
        return text

    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        match = re.search(
            r"\bcontains\s+([A-Za-z]+|\d+)\s+(?:conditions?|grounds?|reasons?|ways?)\b",
            stripped,
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        raw_count = match.group(1).lower()
        if raw_count.isdigit():
            declared = int(raw_count)
        else:
            declared = _NUMBER_WORDS.get(raw_count, -1)

        if declared > 0 and declared != numbered_count:
            lines.pop(index)
        break

    return "\n".join(lines).strip()


def build_extractive_fallback_answer(question: str, source_chunks: list[dict[str, Any]]) -> str:
    if not source_chunks:
        return "This contract does not contain a clause addressing that."

    query_terms = {
        token
        for token in re.findall(r"[a-z0-9]{4,}", question.lower())
        if token not in _STOPWORDS
    }
    if not query_terms:
        query_terms = set(re.findall(r"[a-z0-9]{4,}", question.lower()))

    ranked = _rank_candidate_sentences(source_chunks=source_chunks, query_terms=query_terms)

    bullets: list[str] = []
    seen: set[str] = set()
    for _, sentence in ranked:
        lowered = sentence.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        bullets.append(f"{len(bullets) + 1}. {sentence} [1]")
        if len(bullets) >= 5:
            break

    if bullets:
        return (
            "Model generation is unavailable, so this answer is extracted from retrieved contract excerpts.\n"
            + "\n".join(bullets)
        )

    fallback_text = str(source_chunks[0].get("text", "")).strip()
    if fallback_text:
        snippet = " ".join(fallback_text.split())[:260]
        return f"Model generation is unavailable. Closest retrieved excerpt: {snippet} [1]"

    return "This contract does not contain a clause addressing that."


def _rank_candidate_sentences(
    source_chunks: list[dict[str, Any]],
    query_terms: set[str],
) -> list[tuple[float, str]]:
    ranked: list[tuple[float, str]] = []

    for chunk in source_chunks[:12]:
        metadata = dict(chunk.get("metadata", {}))
        heading = str(metadata.get("section_heading", "")).lower()
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue

        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            cleaned = " ".join(sentence.split()).strip()
            if len(cleaned) < 30:
                continue
            if cleaned[:1].islower():
                continue
            if cleaned.lower().startswith(("or ", "and ", "but ")):
                continue

            lowered_sentence = cleaned.lower()
            sentence_terms = set(re.findall(r"[a-z0-9]{4,}", lowered_sentence))
            overlap = len(query_terms & sentence_terms)
            if overlap == 0:
                continue

            heading_overlap = sum(1 for term in query_terms if term in heading)
            score = float(overlap) + (0.5 * float(heading_overlap))
            ranked.append((score, cleaned))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked
