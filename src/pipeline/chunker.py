from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

APPROX_CHARS_PER_PAGE = 3200

# CUAD-inspired clause families used to guide retrieval.
CUAD_CLAUSE_HINTS: dict[str, list[str]] = {
    "document_name": ["document name", "contract name", "agreement title", "contract no", "contract number"],
    "parties": ["parties", "between", "party", "licensor", "licensee"],
    "agreement_date": ["agreement date", "dated", "date of this agreement", "as of"],
    "effective_date": ["effective date", "commence", "commencement"],
    "expiration_date": ["expiration", "expire", "end date", "term ends"],
    "renewal_term": ["renew", "renewal", "automatic renewal"],
    "notice_to_terminate_renewal": ["terminate renewal", "non-renewal", "notice of non-renewal"],
    "governing_law": ["governing law", "laws of", "jurisdiction"],
    "most_favored_nation": ["most favored nation", "mfn"],
    "non_compete": ["non-compete", "non compete", "restrict competition"],
    "exclusivity": ["exclusive", "exclusivity", "sole"],
    "no_solicit_of_customers": ["no-solicit", "non-solicit", "solicit customers"],
    "competitive_restriction_exception": ["exception", "carveout", "carve-out", "notwithstanding"],
    "non_disparagement": ["non-disparagement", "disparage"],
    "termination_for_convenience": [
        "early termination",
        "termination for convenience",
        "terminate at any time",
        "terminate this agreement",
        "without cause",
        "for its convenience",
        "thirty-day written notice",
    ],
    "termination_for_cause": ["for cause", "material breach", "default", "cure period", "breach"],
    "change_of_control": ["change of control", "control", "acquisition", "merger"],
    "anti_assignment": ["assignment", "assign", "transfer"],
    "revenue_profit_sharing": ["revenue", "profit", "royalty", "share"],
    "price_restrictions": ["price", "pricing", "pricing restrictions"],
    "minimum_commitment": ["minimum", "commitment", "minimum purchase"],
    "volume_restriction": ["volume", "quantity", "quota"],
    "ip_ownership_assignment": ["intellectual property", "ownership", "assignment", "work product"],
    "joint_ip_ownership": ["jointly owned", "joint ownership"],
    "license_grant": ["license grant", "license", "licensed"],
    "non_transferable_license": ["non-transferable", "nontransferable"],
    "affiliate_license_licensee": ["affiliate license", "licensee affiliate"],
    "affiliate_license_licensor": ["licensor affiliate", "affiliate of licensor"],
    "unlimited_license": ["unlimited", "all-you-can-eat", "all you can eat"],
    "irrevocable_or_perpetual_license": ["irrevocable", "perpetual"],
    "source_code_escrow": ["source code", "escrow"],
    "post_termination_services": ["post-termination", "post termination", "transition services"],
    "audit_rights": ["audit", "inspect books", "records"],
    "uncapped_liability": ["uncapped", "unlimited liability"],
    "cap_on_liability": ["cap on liability", "limitation of liability", "maximum liability"],
    "liquidated_damages": ["liquidated damages"],
    "warranty_duration": ["warranty", "warranty period", "duration"],
    "insurance": ["insurance", "insured", "coverage"],
    "covenant_not_to_sue": ["covenant not to sue", "not to sue"],
    "third_party_beneficiary": ["third-party beneficiary", "third party beneficiary"],
    "indemnification": ["indemnify", "indemnification", "hold harmless"],
}

HEADING_PATTERN = re.compile(
    r"^\s*(?:article|section|clause)?\s*[0-9IVX]+(?:\.[0-9IVX]+)*\s*[-:.]?\s+.+$",
    re.IGNORECASE,
)
ALL_CAPS_HEADING_PATTERN = re.compile(r"^[A-Z][A-Z0-9 ,/&()'\-]{6,}$")


@dataclass
class ClauseAwareChunker:
    max_chunk_chars: int = 1400
    chunk_overlap_chars: int = 180

    def chunk_contract(self, contract_id: str, text: str) -> list[dict[str, Any]]:
        normalized = text.replace("\r\n", "\n")
        if not normalized.strip():
            return []

        sections = _split_sections(normalized)
        chunks: list[dict[str, Any]] = []
        cursor = 0

        for section_index, section in enumerate(sections):
            heading = section["heading"]
            section_text = section["text"].strip()
            if not section_text:
                continue

            pieces = _split_long_text(
                section_text,
                max_chars=self.max_chunk_chars,
                overlap=self.chunk_overlap_chars,
            )

            for piece_index, piece in enumerate(pieces):
                chunk_text = piece.strip()
                if not chunk_text:
                    continue

                start = normalized.find(chunk_text, cursor)
                if start < 0:
                    start = normalized.find(chunk_text)
                if start < 0:
                    start = max(cursor, 0)

                end = start + len(chunk_text)
                cursor = max(end - self.chunk_overlap_chars, 0)

                clause_type = infer_clause_type(f"{heading}\n{chunk_text}")
                chunk_id = f"{contract_id}_{section_index}_{piece_index}"
                page_number = (start // APPROX_CHARS_PER_PAGE) + 1

                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "text": chunk_text,
                        "metadata": {
                            "contract_id": contract_id,
                            "contract_name": contract_id,
                            "clause_type": clause_type,
                            "section_heading": heading,
                            "page_number": page_number,
                            "char_start": start,
                            "char_end": end,
                        },
                    }
                )

        return chunks


def _split_sections(text: str) -> list[dict[str, str]]:
    lines = text.split("\n")
    sections: list[dict[str, str]] = []

    current_heading = "preamble"
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if _is_heading(stripped):
            if current_lines:
                sections.append({"heading": current_heading, "text": "\n".join(current_lines).strip()})
            current_heading = stripped.lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append({"heading": current_heading, "text": "\n".join(current_lines).strip()})

    if not sections:
        sections.append({"heading": "preamble", "text": text})

    return sections


def _is_heading(line: str) -> bool:
    if not line:
        return False
    if len(line) > 160:
        return False
    return bool(HEADING_PATTERN.match(line) or ALL_CAPS_HEADING_PATTERN.match(line))


def _split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if not current:
            current = paragraph
            continue

        if len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap > 0 else ""
            current = f"{tail}\n\n{paragraph}".strip()

    if current:
        chunks.append(current)

    return chunks


def infer_clause_type(text: str) -> str:
    lowered = text.lower()
    heading, body = _split_heading_and_body(lowered)

    direct_match = _detect_direct_clause_type(heading=heading, body=body)
    if direct_match is not None:
        return direct_match

    clause_scores: dict[str, int] = {}

    best_clause = "general"
    best_score = 0

    for clause_type, hints in CUAD_CLAUSE_HINTS.items():
        score = _score_clause_hints(
            clause_type=clause_type,
            hints=hints,
            heading=heading,
            body=body,
        )
        clause_scores[clause_type] = score
        if score > best_score:
            best_clause = clause_type
            best_score = score

    if best_clause in {"termination_for_convenience", "termination_for_cause"}:
        signal_score = _termination_signal_score(heading=heading, body=body)
        if signal_score < 3 and not _is_termination_heading(heading):
            fallback_candidates = [
                (clause, score)
                for clause, score in clause_scores.items()
                if clause not in {"termination_for_convenience", "termination_for_cause"}
            ]
            if fallback_candidates:
                fallback_clause, fallback_score = max(fallback_candidates, key=lambda item: item[1])
                if fallback_score > 0:
                    best_clause = fallback_clause
                else:
                    best_clause = "general"
            else:
                best_clause = "general"

    if best_clause == "document_name" and _termination_signal_score(heading=heading, body=body) >= 2:
        return "termination_for_convenience"

    return best_clause


def _split_heading_and_body(text: str) -> tuple[str, str]:
    heading, separator, body = text.partition("\n")
    if not separator:
        return text, text
    return heading.strip(), body


def _detect_direct_clause_type(heading: str, body: str) -> str | None:
    combined = f"{heading}\n{body}"

    convenience_patterns = (
        r"\bearly termination\b",
        r"\btermination for convenience\b",
        r"\bfor its convenience\b",
        r"\bterminate(?:d|s|ing)?\s+this\s+agreement\b",
        r"\bthirty[- ]day\b.{0,80}\bwritten notice\b",
    )
    cause_patterns = (
        r"\bfor cause\b",
        r"\bmaterial breach\b",
        r"\bconsultant'?s default\b",
        r"\bdefault\b.{0,80}\bterminate",
        r"\bterminate\b.{0,80}\bdefault",
        r"\bcure\b.{0,40}\bday",
    )

    convenience_hits = sum(1 for pattern in convenience_patterns if re.search(pattern, combined))
    cause_hits = sum(1 for pattern in cause_patterns if re.search(pattern, combined))

    heading_has_termination = _is_termination_heading(heading)

    if convenience_hits == 0 and cause_hits == 0:
        return None

    if not heading_has_termination and convenience_hits < 2 and cause_hits < 2:
        return None

    if cause_hits > convenience_hits:
        return "termination_for_cause"
    return "termination_for_convenience"


def _score_clause_hints(clause_type: str, hints: list[str], heading: str, body: str) -> int:
    heading_space = heading
    body_space = body

    # Document metadata should come from headings/front-matter, not deep body text.
    if clause_type == "document_name":
        body_space = body[:220]

    score = 0
    for hint in hints:
        normalized_hint = hint.strip().lower()
        if not normalized_hint:
            continue

        pattern = re.compile(rf"\b{re.escape(normalized_hint)}\b")

        heading_hits = len(pattern.findall(heading_space))
        body_hits = len(pattern.findall(body_space))
        if heading_hits > 0:
            score += heading_hits * (len(normalized_hint) + 4)
        if body_hits > 0:
            score += body_hits * max(1, len(normalized_hint) // 2 + 2)

        if heading_hits == 0 and body_hits == 0 and normalized_hint in body_space:
            score += max(1, len(normalized_hint) // 3)

    return score


def _termination_signal_score(heading: str, body: str) -> int:
    combined = f"{heading}\n{body}"
    patterns = (
        r"\bterminat(?:e|ed|es|ing|ion)?\b",
        r"\bearly termination\b",
        r"\bfor cause\b",
        r"\bdefault\b",
    )
    return sum(1 for pattern in patterns if re.search(pattern, combined))


def _is_termination_heading(heading: str) -> bool:
    normalized = heading.lower()
    return bool(re.search(r"\bterminat(?:e|ed|es|ing|ion)?\b", normalized))


def extract_clause_hints_from_question(question: str) -> list[str]:
    lowered = question.lower()
    boosted_hints: list[str] = []

    if re.search(r"\bterminat(?:e|es|ed|ing|ion)?\b", lowered):
        boosted_hints.extend(["termination_for_convenience", "termination_for_cause"])
    if re.search(r"\brenew(?:al|als|ed|ing)?\b", lowered):
        boosted_hints.extend(["renewal_term", "notice_to_terminate_renewal"])

    scored: list[tuple[int, str]] = []

    for clause_type, hints in CUAD_CLAUSE_HINTS.items():
        score = 0
        for hint in hints:
            normalized_hint = hint.strip().lower()
            if not normalized_hint:
                continue

            pattern = re.compile(rf"\b{re.escape(normalized_hint)}\b")
            if pattern.search(lowered):
                score += len(normalized_hint) + 2
            elif normalized_hint in lowered:
                score += max(1, len(normalized_hint) // 2)
        if score > 0:
            scored.append((score, clause_type))

    scored.sort(reverse=True)
    hinted = [clause_type for _, clause_type in scored[:5]]

    ordered: list[str] = []
    seen: set[str] = set()
    for clause_type in boosted_hints + hinted:
        if clause_type not in seen:
            seen.add(clause_type)
            ordered.append(clause_type)

    return ordered[:5]
