from __future__ import annotations

import json


from src.agent.agent import LegalContractAgent


class _LLMMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, route_tool: str) -> None:
        self.route_tool = route_tool

    def invoke(self, messages):
        system_prompt = str(messages[0].content).lower()
        if "routing agent" in system_prompt:
            return _LLMMessage(
                json.dumps({"tool": self.route_tool, "reason": f"Route to {self.route_tool} for this test."})
            )
        return _LLMMessage("Grounded answer based on provided context. [chunk_id=c1]")


class _FakeContractRetriever:
    def __init__(self, return_empty: bool = False) -> None:
        self.return_empty = return_empty

    def get_top_k(
        self,
        query: str,
        contract_id: str | None = None,
        k: int = 5,
        clause_hints: list[str] | None = None,
    ):
        if self.return_empty:
            return []
        return [
            {
                "chunk_id": "c1",
                "text": "Indemnification is capped at direct damages.",
                "metadata": {
                    "contract_name": "sample_contract",
                    "clause_type": "indemnification",
                    "page_number": 4,
                },
                "fused_score": 0.12,
            }
        ]


def test_agent_routes_to_contract_search() -> None:
    agent = LegalContractAgent(clause_retriever=_FakeContractRetriever(), llm=_FakeLLM(route_tool="contract_search"))
    result = agent.run("What is the indemnification cap?")

    assert result["tool_used"] == "contract_search"
    assert result["source_chunks"]
    assert result["used_web_fallback"] is False


def test_agent_routes_to_web_search() -> None:
    agent = LegalContractAgent(clause_retriever=_FakeContractRetriever(), llm=_FakeLLM(route_tool="web_search"))
    result = agent.run("What is the market indemnity cap in SaaS deals?")

    assert result["tool_used"] == "web_search"


def test_agent_falls_back_to_web_when_contract_has_no_results() -> None:
    agent = LegalContractAgent(
        clause_retriever=_FakeContractRetriever(return_empty=True),
        llm=_FakeLLM(route_tool="contract_search"),
    )
    result = agent.run("Find the termination clause")

    assert result["used_web_fallback"] is True
    assert result["tool_used"] == "web_search"
