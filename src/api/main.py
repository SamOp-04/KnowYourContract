from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv() -> bool:  # type: ignore[no-redef]
        return False

from src.agent.agent import LegalContractAgent
from src.api.routes.metrics import router as metrics_router
from src.api.routes.query import router as query_router
from src.api.routes.upload import router as upload_router
from src.evaluation.metrics_store import MetricsStore
from src.evaluation.ragas_evaluator import RagasEvaluator
from src.retrieval.hybrid_retriever import HybridRetriever

load_dotenv()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Legal Contract Analyzer API",
        version="1.0.0",
        description="Agentic RAG backend for legal contract analysis using CUAD.",
    )

    @app.on_event("startup")
    def startup() -> None:
        metrics_store = MetricsStore()
        metrics_store.init_db()
        app.state.metrics_store = metrics_store
        app.state.evaluator = RagasEvaluator(use_ragas=True)

        chunks_path = Path("data/processed/chunks.jsonl")
        faiss_dir = Path("data/processed/faiss_index")

        if chunks_path.exists() and faiss_dir.exists():
            hybrid_retriever = HybridRetriever.from_artifacts()
            app.state.hybrid_retriever = hybrid_retriever
            app.state.agent = LegalContractAgent(hybrid_retriever=hybrid_retriever)
        else:
            app.state.hybrid_retriever = None
            app.state.agent = None

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(query_router)
    app.include_router(upload_router)
    app.include_router(metrics_router)
    return app


app = create_app()
