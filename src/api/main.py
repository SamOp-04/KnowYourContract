from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv() -> bool:  # type: ignore[no-redef]
        return False

from src.agent.agent import LegalContractAgent
from src.api.routes.ask import router as ask_router
from src.api.routes.contracts import router as contracts_router
from src.api.routes.metrics import router as metrics_router
from src.api.routes.query import router as query_router
from src.api.routes.upload import router as upload_router
from src.evaluation.metrics_store import MetricsStore
from src.evaluation.ragas_evaluator import ContractQAEvaluator
from src.pipeline.chat_scope_registry import ChatScopeRegistry
from src.pipeline.pipeline import ContractQAPipeline

load_dotenv()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        metrics_store = MetricsStore()
        metrics_store.init_db()
        app.state.metrics_store = metrics_store
        app.state.evaluator = ContractQAEvaluator(use_llm_judge=True)
        app.state.pipeline = ContractQAPipeline(evaluator=app.state.evaluator)
        app.state.chat_scope_registry = ChatScopeRegistry()
        app.state.agent = LegalContractAgent(clause_retriever=app.state.pipeline.retriever)
            
        yield

    app = FastAPI(
        title="Legal Contract Analyzer API",
        version="1.0.0",
        description="Agentic RAG backend for legal contract analysis using CUAD.",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(query_router)
    app.include_router(ask_router)
    app.include_router(upload_router)
    app.include_router(contracts_router)
    app.include_router(metrics_router)
    return app


app = create_app()
