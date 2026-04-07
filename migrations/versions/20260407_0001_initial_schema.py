"""Create initial shared relational schema.

Revision ID: 20260407_0001
Revises:
Create Date: 2026-04-07 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260407_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ragas_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("tool_used", sa.String(length=64), nullable=False),
        sa.Column("used_web_fallback", sa.Boolean(), nullable=False),
        sa.Column("faithfulness", sa.Float(), nullable=False),
        sa.Column("answer_relevance", sa.Float(), nullable=False),
        sa.Column("context_precision", sa.Float(), nullable=False),
        sa.Column("context_recall", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "chat_scope_contracts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.String(length=128), nullable=False),
        sa.Column("contract_id", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("chat_id", "contract_id", name="uq_chat_scope_contract"),
    )
    op.create_index("ix_chat_scope_contracts_chat_id", "chat_scope_contracts", ["chat_id"])
    op.create_index("ix_chat_scope_contracts_contract_id", "chat_scope_contracts", ["contract_id"])

    op.create_table(
        "contracts_registry",
        sa.Column("contract_id", sa.String(length=256), primary_key=True, nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("source_name", sa.String(length=512), nullable=False),
        sa.Column("chunks_ingested", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "uploaded_contract_texts",
        sa.Column("contract_id", sa.String(length=256), primary_key=True, nullable=False),
        sa.Column("source_name", sa.String(length=512), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("raw_text_path", sa.String(length=1024), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "stored_contract_chunks",
        sa.Column("chunk_id", sa.String(length=512), primary_key=True, nullable=False),
        sa.Column("contract_id", sa.String(length=256), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stored_contract_chunks_contract_id", "stored_contract_chunks", ["contract_id"])


def downgrade() -> None:
    op.drop_index("ix_stored_contract_chunks_contract_id", table_name="stored_contract_chunks")
    op.drop_table("stored_contract_chunks")

    op.drop_table("uploaded_contract_texts")
    op.drop_table("contracts_registry")

    op.drop_index("ix_chat_scope_contracts_contract_id", table_name="chat_scope_contracts")
    op.drop_index("ix_chat_scope_contracts_chat_id", table_name="chat_scope_contracts")
    op.drop_table("chat_scope_contracts")

    op.drop_table("ragas_metrics")
