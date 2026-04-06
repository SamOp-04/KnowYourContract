from __future__ import annotations

from src.pipeline.chunker import extract_clause_hints_from_question, infer_clause_type


def test_infer_clause_type_detects_termination_for_convenience() -> None:
    text = (
        "4. EARLY TERMINATION\n"
        "COMMISSION may terminate this Agreement for its convenience at any time with thirty-day written notice."
    )
    assert infer_clause_type(text) == "termination_for_convenience"


def test_infer_clause_type_detects_termination_for_cause() -> None:
    text = (
        "4.B TERMINATION\n"
        "COMMISSION may terminate for CONSULTANT default or material breach if not cured within ten days."
    )
    assert infer_clause_type(text) == "termination_for_cause"


def test_infer_clause_type_keeps_document_name_for_title() -> None:
    text = "CONTRACT TITLE\nDocument name: Shuttle Operations Master Agreement"
    assert infer_clause_type(text) == "document_name"


def test_extract_clause_hints_boosts_termination_queries() -> None:
    hints = extract_clause_hints_from_question("What are the termination conditions?")
    assert "termination_for_convenience" in hints
    assert "termination_for_cause" in hints
