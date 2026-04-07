from __future__ import annotations

from pathlib import Path
from typing import Any

from src.evaluation.ragas_evaluator import RagasEvaluator
from src.pipeline.answerer import MistralAnswerer
from src.pipeline.chunker import ClauseAwareChunker, extract_clause_hints_from_question
from src.pipeline.contracts_registry import ContractRegistry
from src.pipeline.embedder import ContractVectorStore
from src.pipeline.parser import DocumentParser
from src.pipeline.retriever import ClauseAwareRetriever


class ContractQAPipeline:
    def __init__(
        self,
        parser: DocumentParser | None = None,
        chunker: ClauseAwareChunker | None = None,
        vector_store: ContractVectorStore | None = None,
        retriever: ClauseAwareRetriever | None = None,
        answerer: MistralAnswerer | None = None,
        evaluator: RagasEvaluator | None = None,
        registry: ContractRegistry | None = None,
    ) -> None:
        self.parser = parser or DocumentParser(raw_upload_dir=Path("data/raw/uploads"))
        self.chunker = chunker or ClauseAwareChunker()
        self.vector_store = vector_store or ContractVectorStore(
            persist_directory=Path("data/processed/chroma"),
            collection_name="contracts",
        )
        self.retriever = retriever or ClauseAwareRetriever(vector_store=self.vector_store)
        self.answerer = answerer or MistralAnswerer()
        self.evaluator = evaluator or RagasEvaluator(use_ragas=True)
        self.registry = registry or ContractRegistry()

    def ingest_upload(self, filename: str, file_bytes: bytes, contract_id: str | None = None) -> dict[str, Any]:
        parsed = self.parser.parse_upload(
            filename=filename,
            file_bytes=file_bytes,
            contract_id=contract_id,
        )

        chunks = self.chunker.chunk_contract(contract_id=parsed.contract_id, text=parsed.text)
        if not chunks:
            raise ValueError("No chunks created from uploaded contract.")

        for chunk in chunks:
            metadata = dict(chunk.get("metadata", {}))
            metadata.setdefault("contract_id", parsed.contract_id)
            metadata.setdefault("contract_name", parsed.contract_id)
            metadata["source_name"] = parsed.source_name
            metadata["raw_text_path"] = str(parsed.raw_text_path)
            chunk["metadata"] = metadata

        ingested = self.vector_store.index_chunks(chunks)
        self.registry.upsert(
            contract_id=parsed.contract_id,
            source_name=parsed.source_name,
            chunks_ingested=ingested,
        )

        return {
            "contract_id": parsed.contract_id,
            "chunks_ingested": ingested,
            "message": "Contract uploaded and indexed successfully.",
        }

    def list_contracts(self) -> list[dict[str, Any]]:
        return self.registry.list_contracts()

    def ask(
        self,
        question: str,
        contract_id: str | None = None,
        ground_truth: str = "",
    ) -> dict[str, Any]:
        clause_hints = extract_clause_hints_from_question(question)
        retrieval_k = 8
        lowered_question = question.lower()
        if any("termination" in hint for hint in clause_hints):
            retrieval_k = 12
        if any(
            term in lowered_question
            for term in (
                "invoice",
                "billing",
                "payment deadline",
                "key personnel",
                "project manager",
                "replace",
                "replaced",
                "approval",
            )
        ):
            retrieval_k = 12

        source_chunks = self.retriever.get_top_k(
            query=question,
            contract_id=contract_id,
            k=retrieval_k,
            clause_hints=clause_hints,
        )
        model_answer = self.answerer.answer(question=question, source_chunks=source_chunks)
        answer, sources = self.answerer.finalize_answer_with_sources(
            answer=model_answer,
            source_chunks=source_chunks,
            question=question,
        )

        contexts = [str(chunk.get("text", "")) for chunk in source_chunks if str(chunk.get("text", "")).strip()]
        evaluation = self.evaluator.evaluate_single(
            question=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
        )

        if source_chunks:
            if clause_hints:
                route_reason = "Clause-aware retrieval prioritized likely CUAD clause families."
            else:
                route_reason = "Retrieved top contract chunks from vector search."
        else:
            route_reason = "No relevant chunks were found in the indexed contract store."

        return {
            "answer": answer,
            "citations": self.answerer.build_citations(source_chunks),
            "sources": sources,
            "source_chunks": source_chunks,
            "tool_used": "pipeline_contract_search",
            "route_reason": route_reason,
            "used_web_fallback": False,
            "matched_clause_hints": clause_hints,
            "evaluation": evaluation,
        }
