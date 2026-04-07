from __future__ import annotations

from src.pipeline.chat_scope_registry import ChatScopeRegistry
from src.pipeline.contracts_registry import ContractRegistry


def test_chat_scope_registry_db_backend_persists_across_instances(tmp_path) -> None:
    db_path = tmp_path / "registry_state.db"
    database_url = f"sqlite:///{db_path}"

    first = ChatScopeRegistry(
        registry_path=tmp_path / "chat_scope_registry.json",
        backend="db",
        database_url=database_url,
    )
    first.add_contracts("chat_a", ["contract_1", "contract_2", "contract_1"])

    assert first.list_contract_ids("chat_a") == ["contract_1", "contract_2"]

    second = ChatScopeRegistry(
        registry_path=tmp_path / "chat_scope_registry_other.json",
        backend="db",
        database_url=database_url,
    )
    assert second.list_contract_ids("chat_a") == ["contract_1", "contract_2"]


def test_contract_registry_db_backend_upsert_and_ordering(tmp_path) -> None:
    db_path = tmp_path / "registry_state.db"
    database_url = f"sqlite:///{db_path}"

    registry = ContractRegistry(
        registry_path=tmp_path / "contracts_registry.json",
        raw_upload_dir=tmp_path / "uploads",
        chunk_metadata_path=tmp_path / "chunk_metadata.json",
        backend="db",
        database_url=database_url,
    )

    registry.upsert(
        contract_id="contract_a",
        source_name="Alpha.pdf",
        chunks_ingested=3,
        uploaded_at="2026-04-07T01:00:00",
    )
    registry.upsert(
        contract_id="contract_b",
        source_name="Beta.pdf",
        chunks_ingested=4,
        uploaded_at="2026-04-07T02:00:00",
    )

    rows = registry.list_contracts()
    assert [row["contract_id"] for row in rows] == ["contract_b", "contract_a"]
    assert rows[0]["display_name"] == "Beta"

    # Updating existing contract should move it to top with newer timestamp.
    registry.upsert(
        contract_id="contract_a",
        source_name="Alpha_v2.pdf",
        chunks_ingested=7,
        uploaded_at="2026-04-07T03:00:00",
    )

    updated_rows = registry.list_contracts()
    assert updated_rows[0]["contract_id"] == "contract_a"
    assert updated_rows[0]["chunks_ingested"] == 7
    assert updated_rows[0]["source_name"] == "Alpha_v2.pdf"

    # Ensure data persists across a new registry instance.
    second_registry = ContractRegistry(
        registry_path=tmp_path / "contracts_registry_other.json",
        raw_upload_dir=tmp_path / "uploads",
        chunk_metadata_path=tmp_path / "chunk_metadata.json",
        backend="db",
        database_url=database_url,
    )
    persisted_rows = second_registry.list_contracts()
    assert persisted_rows[0]["contract_id"] == "contract_a"
    assert {row["contract_id"] for row in persisted_rows} == {"contract_a", "contract_b"}
