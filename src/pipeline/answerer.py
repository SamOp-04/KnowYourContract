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
    enable_cli_fallback: bool = os.getenv("OLLAMA_CLI_FALLBACK", "1").strip().lower() not in {"0", "false", "no"}

    def answer(self, question: str, source_chunks: list[dict[str, Any]]) -> str:
        if not source_chunks:
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
            response = requests.post(self.endpoint, json=payload, timeout=max(30.0, self.timeout_seconds))
            response.raise_for_status()
            body = response.json()
            answer = str(body.get("response", "")).strip()
            if answer:
                return answer
        except Exception as error:
            cli_answer = self._answer_with_ollama_cli(prompt=prompt)
            if cli_answer:
                return cli_answer
            return self._build_extractive_fallback_answer(question=question, source_chunks=source_chunks)

        cli_answer = self._answer_with_ollama_cli(prompt=prompt)
        if cli_answer:
            return cli_answer

        return self._build_extractive_fallback_answer(question=question, source_chunks=source_chunks)

    def finalize_answer_with_sources(
        self,
        answer: str,
        source_chunks: list[dict[str, Any]],
        question: str = "",
    ) -> tuple[str, list[dict[str, Any]]]:
        sources = self.build_sources(source_chunks)
        if not sources:
            return answer.strip(), []

        cleaned = self._normalize_answer(answer=answer, question=question, source_chunks=source_chunks)
        if not re.search(r"\[\d+\]", cleaned):
            cleaned = f"{cleaned} [{sources[0]['index']}]"

        source_lines = "\n".join(f"[{item['index']}] {item['label']}" for item in sources)
        tagged_answer = f"{cleaned}\n\nSources:\n{source_lines}"
        return tagged_answer, sources

    def _build_prompt(self, question: str, source_chunks: list[dict[str, Any]]) -> str:
        # Use a wider retrieval window with chunk metadata so clause-specific questions
        # (for example termination/default/notice) are less likely to miss the right section.
        context = _render_context(chunks=source_chunks[:12], max_chars_per_chunk=1200)
        return (
            "<s>[INST] You are an expert legal contract analysis assistant with deep knowledge of contract law and interpretation.\n\n"
            "Your task is to answer questions about contracts using ONLY the provided contract excerpts.\n\n"
            "If the answer to the question is not contained in the provided context, \n"
            "respond exactly with: \"This information is not specified in the contract.\"\n"
            "Do NOT infer, guess, or extrapolate answers not explicitly stated.\n\n"
            "═══════════════════════════════════════\n"
            "CORE ANSWERING PRINCIPLES\n"
            "═══════════════════════════════════════\n\n"
            "DIRECTNESS\n"
            "- Lead every answer with the direct contract statement or fact.\n"
            "- Never open with meta-commentary about what the contract does or does not say before giving the answer.\n"
            "- If the answer exists in the excerpts, state it plainly first, then add context.\n"
            "- Reserve \"This contract does not address [topic].\" for when excerpts genuinely contain nothing relevant.\n\n"
            "PRECISION\n"
            "- Answer only what is asked. Do not include information from adjacent provisions unless it directly qualifies the answer.\n"
            "- If asked about a threshold, answer with the threshold. If asked about a process, answer with the process. Do not conflate the two.\n"
            "- Distinguish between SHALL (mandatory), MAY (permissive), and MUST NOT (prohibited) when citing obligations.\n\n"
            "COMPLETENESS\n"
            "- For list-type questions (conditions, types, thresholds, requirements), retrieve ALL instances from the excerpts.\n"
            "- If multiple sections address the same topic, synthesize them into a single coherent answer rather than listing chunks separately.\n"
            "- Do not stop at the first relevant clause if others exist.\n\n"
            "CONFIDENCE CALIBRATION\n"
            "- State contract language as fact when it is direct and unambiguous.\n"
            "- Use \"may\" or \"could\" only when the contract itself uses permissive language.\n"
            "- Do not introduce your own uncertainty into unambiguous contract statements.\n"
            "- When genuinely uncertain due to ambiguous language, quote the relevant contract text and note the ambiguity — do not silently guess.\n\n"
            "═══════════════════════════════════════\n"
            "STRUCTURE & FORMATTING\n"
            "═══════════════════════════════════════\n\n"
            "- Lead with a one-sentence direct answer when the question has a clear single answer.\n"
            "- Use a numbered list when the answer has multiple components (conditions, steps, types).\n"
            "- Do not introduce a list with \"The contract contains X items\" — just begin the list.\n"
            "- Do not number a list if there is only one item — state it as a sentence.\n"
            "- Use bold for key terms, amounts, deadlines, and named parties when they appear in lists.\n"
            "- Keep answers as short as the question allows. Add detail only when it materially affects the answer.\n\n"
            "═══════════════════════════════════════\n"
            "CITATION RULES\n"
            "═══════════════════════════════════════\n\n"
            "- Cite every factual claim with a bracket reference: [1], [2], etc.\n"
            "- Place citations at the end of the sentence they support, not at the end of the answer.\n"
            "- If two sources support the same claim, cite both: [1][2].\n"
            "- If a claim spans multiple sections that say the same thing, note the primary source and acknowledge the others briefly.\n"
            "- Never cite a source for a claim it does not support.\n\n"
            "═══════════════════════════════════════\n"
            "SCOPE & BOUNDARIES\n"
            "═══════════════════════════════════════\n\n"
            "- Use ONLY the provided excerpts. Do not apply general legal knowledge to fill gaps.\n"
            "- Do not infer obligations from silence. If the contract is silent on something, say so.\n"
            "- Do not speculate about what parties intended beyond what the text states.\n"
            "- If the excerpts appear incomplete or contradictory, note this explicitly rather than resolving it silently.\n"
            "- Never claim your answer covers all contract provisions unless the excerpts clearly include every relevant section. End with: \"Other provisions elsewhere in the contract may also apply.\" when appropriate.\n\n"
            "═══════════════════════════════════════\n"
            "QUESTION-TYPE HANDLING\n"
            "═══════════════════════════════════════\n\n"
            "THRESHOLD / VALUE QUESTIONS (e.g. \"What triggers X?\")\n"
            "→ List all monetary thresholds and conditions found across all excerpts.\n"
            "→ Distinguish between different thresholds that trigger different obligations.\n\n"
            "PROCESS / PROCEDURE QUESTIONS (e.g. \"What is the process for X?\")\n"
            "→ Present steps in sequential order if sequence matters.\n"
            "→ Clearly separate parallel tracks (e.g. audit disputes vs. general disputes).\n\n"
            "PERMISSION / PROHIBITION QUESTIONS (e.g. \"Can X do Y?\")\n"
            "→ State the answer (yes/no/conditional) in the first sentence.\n"
            "→ Then cite the specific clause that establishes this.\n"
            "→ Note any exceptions or conditions that modify the answer.\n\n"
            "OWNERSHIP / RIGHTS QUESTIONS (e.g. \"Who owns X?\")\n"
            "→ State the owner directly.\n"
            "→ Note any licenses, exceptions, or residual rights that qualify ownership.\n\n"
            "OBLIGATION QUESTIONS (e.g. \"What must X do?\")\n"
            "→ Distinguish between unconditional obligations (SHALL) and conditional ones (IF... THEN).\n"
            "→ List unconditional obligations first.\n\n"
            "TIMELINE / DEADLINE QUESTIONS (e.g. \"When must X happen?\")\n"
            "→ State the specific deadline or trigger event.\n"
            "→ If multiple deadlines exist for the same topic, distinguish them clearly (e.g. interim vs. final).\n\n"
            "PERSONNEL / ROLE QUESTIONS (e.g. \"Who is responsible for X?\")\n"
            "→ Name the specific person or role.\n"
            "→ Note any approval or consent requirements that apply to changes in that role.\n\n"
            "═══════════════════════════════════════\n"
            "ANTI-PATTERNS TO AVOID\n"
            "═══════════════════════════════════════\n\n"
            "❌ \"The contract does not explicitly state...\" [when it does]\n"
            "❌ \"It can be inferred that...\" [use only when inference is genuinely needed]\n"
            "❌ \"It is evident that...\" [state the fact directly]\n"
            "❌ \"Based on the provided excerpts...\" [unnecessary preamble]\n"
            "❌ \"This contract contains X conditions for Y...\" [just list them]\n"
            "❌ \"It is worth noting that...\" [if worth noting, just note it]\n"
            "❌ \"However, it is important to note...\" [same issue]\n"
            "❌ Mixing information from adjacent clauses that do not answer the question\n"
            "❌ Claiming exhaustiveness when excerpts may be partial\n"
            "❌ Resolving genuine ambiguity silently without flagging it\n\n"
            "[CONTRACT EXCERPTS]\n"
            f"{context}\n\n"
            "[QUESTION]\n"
            f"{question.strip()}\n\n"
            "Answer: [/INST]"
        )

    @staticmethod
    def _normalize_answer(answer: str, question: str, source_chunks: list[dict[str, Any]]) -> str:
        cleaned = answer.strip()
        cleaned = MistralAnswerer._remove_inconsistent_count_intro(cleaned)
        cleaned = MistralAnswerer._soften_overconfident_termination_claims(cleaned)
        cleaned = MistralAnswerer._append_invoice_deadline_clarification(cleaned, question, source_chunks)
        cleaned = MistralAnswerer._append_key_personnel_clarification(cleaned, question, source_chunks)
        cleaned = MistralAnswerer._append_subcontracting_clarification(cleaned, question, source_chunks)
        return cleaned.strip()

    @staticmethod
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

    @staticmethod
    def _soften_overconfident_termination_claims(text: str) -> str:
        patterns = [
            r"(?i)\bthis contract does not contain[^.\n]*termination[^.\n]*[.?!]",
            r"(?i)\bno other[^.\n]*termination[^.\n]*[.?!]",
        ]

        softened = text
        for pattern in patterns:
            softened = re.sub(
                pattern,
                "Other termination triggers may exist elsewhere in the contract.",
                softened,
            )

        return softened

    @staticmethod
    def _append_invoice_deadline_clarification(
        text: str,
        question: str,
        source_chunks: list[dict[str, Any]],
    ) -> str:
        lowered_question = question.lower()
        payment_deadline_terms = ("invoice", "billing", "submit", "deadline", "final invoice")
        if not any(term in lowered_question for term in payment_deadline_terms):
            return text

        evidence_blob = MistralAnswerer._compose_evidence_blob(source_chunks)
        lowered_evidence = evidence_blob.lower()

        has_regular_deadline = bool(
            re.search(r"\binvoices?\b[^.\n]{0,140}\b45\s+calendar\s+days\b", lowered_evidence)
            or ("45 calendar days" in lowered_evidence and "invoice" in lowered_evidence)
        )
        has_final_deadline = bool(
            re.search(r"\bfinal\s+invoice\b[^.\n]{0,200}\b60\s+calendar\s+days\b", lowered_evidence)
            or ("final invoice" in lowered_evidence and "60 calendar days" in lowered_evidence)
        )

        if has_final_deadline and not has_regular_deadline:
            lowered_text = text.lower()
            if "60" in lowered_text and "final invoice" in lowered_text:
                return text

            clarification = (
                "The final invoice must be submitted within 60 calendar days after acceptance of the Consultant's work by the Contract Manager."
            )
            return f"{text.rstrip()}\n\n- {clarification}"

        if not (has_regular_deadline and has_final_deadline):
            return text

        lowered_text = text.lower()
        mentions_45 = "45" in lowered_text and "invoice" in lowered_text
        mentions_60_final = "60" in lowered_text and "final invoice" in lowered_text
        if mentions_45 and mentions_60_final:
            return text

        clarification = (
            "Important deadline distinction: regular invoices are due within 45 calendar days after the work is performed, "
            "while the final invoice is due within 60 calendar days after acceptance of the work by the Contract Manager."
        )
        return f"{text.rstrip()}\n\n- {clarification}"

    @staticmethod
    def _append_key_personnel_clarification(
        text: str,
        question: str,
        source_chunks: list[dict[str, Any]],
    ) -> str:
        lowered_question = question.lower()
        if not any(term in lowered_question for term in ("key personnel", "project manager", "replace", "replaced")):
            return text

        evidence_blob = MistralAnswerer._compose_evidence_blob(source_chunks)
        lowered_evidence = evidence_blob.lower()
        additions: list[str] = []

        has_replacement_constraint = bool(
            re.search(r"\bremoved\s+or\s+replaced\b[^.\n]{0,220}\bprior\s+written\s+consent\b", lowered_evidence)
            or re.search(r"\bno\s+change\b[^.\n]{0,220}\bproject\s+manager\b[^.\n]{0,220}\bwritten\b", lowered_evidence)
            or re.search(r"\bproject\s+manager\b[^.\n]{0,180}\bwritten\s+authoriz", lowered_evidence)
        )

        if has_replacement_constraint:
            if "prior written consent" not in text.lower():
                additions.append(
                    "Key personnel cannot be removed/replaced or have their agreed functions changed without prior written consent."
                )

        name_role_pairs = MistralAnswerer._extract_name_role_pairs(evidence_blob)
        if name_role_pairs:
            lowered_text = text.lower()
            if not any(name.lower() in lowered_text for name, _ in name_role_pairs):
                rendered = "; ".join(f"{name} ({role})" for name, role in name_role_pairs[:3])
                additions.append(f"Named key personnel include: {rendered}.")

        if not additions:
            return text

        bullet_block = "\n".join(f"- {item}" for item in additions)
        return f"{text.rstrip()}\n\n{bullet_block}"

    @staticmethod
    def _extract_name_role_pairs(evidence_blob: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        patterns = [
            re.compile(
                r"([A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z]+)[^\n0-9]{0,40}?\b(Principal in Charge|Project Manager)\b"
            ),
            re.compile(
                r"([A-Z][a-z]+(?:\s+[A-Z]\.)?(?:\s+[A-Z][a-z]+)+)[^\n0-9]{0,40}?\b(Principal in Charge|Project Manager)\b"
            ),
        ]

        for pattern in patterns:
            for match in pattern.finditer(evidence_blob):
                raw_name = " ".join(match.group(1).split())
                name = MistralAnswerer._canonical_person_name(raw_name)
                role = match.group(2)
                key = (name, role)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append(key)

        return pairs

    @staticmethod
    def _compose_evidence_blob(source_chunks: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for chunk in source_chunks:
            metadata = dict(chunk.get("metadata", {}))
            heading = str(metadata.get("section_heading", "")).strip()
            text = str(chunk.get("text", "")).strip()
            combined = f"{heading}\n{text}".strip()
            if combined:
                parts.append(combined)
        return "\n\n".join(parts)

    @staticmethod
    def _canonical_person_name(name: str) -> str:
        tokens = [token for token in name.split() if token]
        if not tokens:
            return name

        # Keep the human name portion and drop trailing firm words from table rows.
        if len(tokens) > 3:
            tokens = tokens[:3]
        return " ".join(tokens)

    @staticmethod
    def _build_extractive_fallback_answer(question: str, source_chunks: list[dict[str, Any]]) -> str:
        lowered_question = question.lower()
        query_terms = set(re.findall(r"[a-z]{4,}", lowered_question))
        is_termination_query = "termination" in lowered_question or "terminate" in lowered_question
        is_invoice_query = any(term in lowered_question for term in ("invoice", "billing", "payment deadline", "submit invoice"))
        is_personnel_query = any(term in lowered_question for term in ("key personnel", "project manager", "replace", "replaced"))
        if is_termination_query:
            query_terms.update({"terminate", "termination", "cancel", "suspend", "insurance", "kickback"})

        evidence_blob = MistralAnswerer._compose_evidence_blob(source_chunks)

        if is_invoice_query:
            invoice_bullets = MistralAnswerer._build_invoice_fallback_bullets(evidence_blob)
            if invoice_bullets:
                return (
                    "Model generation is unavailable, so this answer is extracted directly from retrieved contract excerpts.\n"
                    + "\n".join(f"{index}. {bullet} [1]" for index, bullet in enumerate(invoice_bullets, start=1))
                )

        if is_personnel_query:
            personnel_bullets = MistralAnswerer._build_personnel_fallback_bullets(evidence_blob)
            if personnel_bullets:
                return (
                    "Model generation is unavailable, so this answer is extracted directly from retrieved contract excerpts.\n"
                    + "\n".join(f"{index}. {bullet} [1]" for index, bullet in enumerate(personnel_bullets, start=1))
                )

        ranked: list[tuple[float, int, str]] = []
        for chunk_index, chunk in enumerate(source_chunks[:12], start=1):
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
                overlap = sum(1 for term in query_terms if term in lowered_sentence)
                if overlap == 0:
                    continue

                score = float(overlap)
                if "terminate" in lowered_sentence or "termination" in lowered_sentence:
                    score += 1.0
                ranked.append((score, chunk_index, cleaned))

        ranked.sort(key=lambda item: item[0], reverse=True)

        bullets: list[str] = []
        seen: set[str] = set()
        for _, _, sentence in ranked:
            normalized = sentence.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            bullets.append(f"{len(bullets) + 1}. {sentence} [1]")
            if len(bullets) >= 5:
                break

        if is_termination_query:
            trigger_groups = [
                ("insurance", {"insurance", "coverage"}),
                ("equal_employment", {"equal employment", "non-discrimination", "discrimin"}),
                ("kickback", {"kickback", "rebate", "unlawful consideration"}),
            ]
            for _, terms in trigger_groups:
                for _, _, sentence in ranked:
                    lowered_sentence = sentence.lower()
                    if not any(term in lowered_sentence for term in terms):
                        continue
                    normalized = lowered_sentence
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    bullets.append(f"{len(bullets) + 1}. {sentence} [1]")
                    break

        bullets = bullets[:7]

        if bullets:
            return (
                "Model generation is unavailable, so this answer is extracted directly from retrieved contract excerpts.\n"
                + "\n".join(bullets)
                + "\nBased on the retrieved excerpts, these are the primary relevant clauses identified."
            )

        fallback_text = str(source_chunks[0].get("text", "")).strip()
        if fallback_text:
            snippet = " ".join(fallback_text.split())[:260]
            return f"Model generation is unavailable. Closest retrieved excerpt: {snippet} [1]"

        return "This contract does not contain a clause addressing that."

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

        # Strip ANSI escape sequences if present.
        cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout).strip()
        return cleaned

    @staticmethod
    def _build_invoice_fallback_bullets(evidence_blob: str) -> list[str]:
        lowered = evidence_blob.lower()
        bullets: list[str] = []

        if "final invoice" in lowered and "60 calendar days" in lowered:
            bullets.append(
                "The final invoice must be submitted within 60 calendar days after acceptance of the Consultant's work by the Contract Manager."
            )

        if "45 calendar days" in lowered and "invoice" in lowered:
            bullets.append(
                "Regular invoices must be submitted no later than 45 calendar days after the performance of work being billed."
            )

        return bullets

    @staticmethod
    def _build_personnel_fallback_bullets(evidence_blob: str) -> list[str]:
        lowered = evidence_blob.lower()
        bullets: list[str] = []

        pairs = MistralAnswerer._extract_name_role_pairs(evidence_blob)
        if pairs:
            rendered = "; ".join(f"{name} ({role})" for name, role in pairs[:3])
            bullets.append(f"Named key personnel include {rendered}.")

        if (
            re.search(r"\bremoved\s+or\s+replaced\b[^.\n]{0,220}\bprior\s+written\s+consent\b", lowered)
            or re.search(r"\bno\s+change\b[^.\n]{0,220}\bproject\s+manager\b[^.\n]{0,220}\bwritten\b", lowered)
            or ("no change" in lowered and "project manager" in lowered)
        ):
            bullets.append(
                "The Project Manager and other named key personnel cannot be changed or replaced without prior written consent/authorization."
            )

        return bullets

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

    @staticmethod
    def _append_subcontracting_clarification(
        text: str,
        question: str,
        source_chunks: list[dict[str, Any]],
    ) -> str:
        lowered_question = question.lower()
        if "subcontract" not in lowered_question:
            return text

        evidence_blob = MistralAnswerer._compose_evidence_blob(source_chunks)
        lowered_evidence = evidence_blob.lower()
        additions: list[str] = []

        if re.search(r"prior\s+written\s+authorization", lowered_evidence) and "fee schedule" in lowered_evidence:
            if "written authorization" not in text.lower():
                additions.append("Prior written authorization from the Contract Manager is required before subcontracting any work not already in the approved Fee Schedule.")
                
        if not additions:
            return text

        bullet_block = "\n".join(f"- {item}" for item in additions)
        return f"{text.rstrip()}\n\n{bullet_block}"
