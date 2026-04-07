from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from sqlalchemy import DateTime, String, Text, create_engine, delete, desc, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except Exception:
    SQLALCHEMY_AVAILABLE = False

from src.utils.db import should_auto_create_tables


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return

    raw_path = database_url[len(prefix):].split("?", 1)[0]
    if not raw_path or raw_path == ":memory:":
        return

    try:
        Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc_naive(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            if candidate.endswith("Z"):
                candidate = f"{candidate[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    return parsed
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                pass

    return _now_utc_naive()


if SQLALCHEMY_AVAILABLE:
    class Base(DeclarativeBase):
        pass


    class StoredContractText(Base):
        __tablename__ = "uploaded_contract_texts"

        contract_id: Mapped[str] = mapped_column(String(256), primary_key=True)
        source_name: Mapped[str] = mapped_column(String(512), nullable=False)
        raw_text: Mapped[str] = mapped_column(Text, nullable=False)
        raw_text_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
        uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc_naive, nullable=False)


    class StoredContractChunk(Base):
        __tablename__ = "stored_contract_chunks"

        chunk_id: Mapped[str] = mapped_column(String(512), primary_key=True)
        contract_id: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
        text: Mapped[str] = mapped_column(Text, nullable=False)
        metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc_naive, nullable=False)


else:
    class Base:  # type: ignore[no-redef]
        pass


    class StoredContractText:  # type: ignore[no-redef]
        pass


    class StoredContractChunk:  # type: ignore[no-redef]
        pass


class ContractArtifactStore:
    def __init__(
        self,
        backend: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self.database_url = str(database_url or os.getenv("DATABASE_URL", "")).strip()
        resolved_backend = str(backend or os.getenv("ARTIFACT_STORE_BACKEND", "auto")).strip().lower()
        self._db_enabled = False
        self.engine = None
        self.SessionLocal = None

        if resolved_backend not in {"auto", "file", "db"}:
            resolved_backend = "auto"

        if resolved_backend != "file":
            self._try_enable_db(strict=(resolved_backend == "db"))

    @property
    def db_enabled(self) -> bool:
        return self._db_enabled

    def _try_enable_db(self, strict: bool) -> None:
        if not SQLALCHEMY_AVAILABLE:
            if strict:
                raise RuntimeError("SQLAlchemy is required for ARTIFACT_STORE_BACKEND=db.")
            return

        if not self.database_url:
            if strict:
                raise RuntimeError("DATABASE_URL is required for ARTIFACT_STORE_BACKEND=db.")
            return

        try:
            _ensure_sqlite_parent_dir(self.database_url)
            self.engine = create_engine(self.database_url, future=True)
            self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
            if should_auto_create_tables(self.database_url):
                Base.metadata.create_all(bind=self.engine)
            self._db_enabled = True
        except Exception as error:
            self.engine = None
            self.SessionLocal = None
            self._db_enabled = False
            if strict:
                raise RuntimeError("Failed to initialize DB-backed ContractArtifactStore.") from error

    def upsert_contract_text(
        self,
        contract_id: str,
        source_name: str,
        raw_text: str,
        raw_text_path: str = "",
        uploaded_at: str | datetime | None = None,
    ) -> None:
        if not self._db_enabled or self.SessionLocal is None:
            return

        with self.SessionLocal() as session:
            existing = session.get(StoredContractText, contract_id)
            timestamp = _as_utc_naive(uploaded_at)
            if existing is None:
                existing = StoredContractText(
                    contract_id=contract_id,
                    source_name=source_name,
                    raw_text=str(raw_text),
                    raw_text_path=str(raw_text_path),
                    uploaded_at=timestamp,
                )
                session.add(existing)
            else:
                existing.source_name = source_name
                existing.raw_text = str(raw_text)
                existing.raw_text_path = str(raw_text_path)
                existing.uploaded_at = timestamp

            session.commit()

    def get_contract_text(self, contract_id: str) -> dict[str, Any] | None:
        if not self._db_enabled or self.SessionLocal is None:
            return None

        with self.SessionLocal() as session:
            row = session.get(StoredContractText, contract_id)
            if row is None:
                return None

            return {
                "contract_id": row.contract_id,
                "source_name": row.source_name,
                "raw_text": row.raw_text,
                "raw_text_path": row.raw_text_path,
                "uploaded_at": row.uploaded_at.isoformat(),
            }

    def replace_contract_chunks(self, chunks: list[dict[str, Any]]) -> int:
        if not self._db_enabled or self.SessionLocal is None:
            return 0
        if not chunks:
            return 0

        normalized: list[dict[str, Any]] = []
        contract_ids: set[str] = set()

        for chunk in chunks:
            metadata = dict(chunk.get("metadata", {}))
            chunk_id = str(chunk.get("chunk_id", "")).strip()
            text = str(chunk.get("text", ""))
            contract_id = str(metadata.get("contract_id", "")).strip()
            if not chunk_id or not contract_id:
                continue

            metadata.setdefault("chunk_id", chunk_id)
            metadata.setdefault("contract_id", contract_id)

            normalized.append(
                {
                    "chunk_id": chunk_id,
                    "contract_id": contract_id,
                    "text": text,
                    "metadata_json": json.dumps(metadata, ensure_ascii=True),
                }
            )
            contract_ids.add(contract_id)

        if not normalized:
            return 0

        with self.SessionLocal() as session:
            for contract_id in contract_ids:
                session.execute(
                    delete(StoredContractChunk).where(StoredContractChunk.contract_id == contract_id)
                )

            for item in normalized:
                session.add(
                    StoredContractChunk(
                        chunk_id=item["chunk_id"],
                        contract_id=item["contract_id"],
                        text=item["text"],
                        metadata_json=item["metadata_json"],
                        updated_at=_now_utc_naive(),
                    )
                )

            session.commit()

        return len(normalized)

    def load_all_chunks(
        self,
        contract_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self._db_enabled or self.SessionLocal is None:
            return []

        with self.SessionLocal() as session:
            stmt = select(StoredContractChunk)
            if contract_ids:
                normalized_contract_ids = [str(item).strip() for item in contract_ids if str(item).strip()]
                if normalized_contract_ids:
                    stmt = stmt.where(StoredContractChunk.contract_id.in_(normalized_contract_ids))
            stmt = stmt.order_by(StoredContractChunk.updated_at.desc())
            if limit is not None and limit > 0:
                stmt = stmt.limit(limit)

            rows = session.execute(stmt).scalars().all()
            output: list[dict[str, Any]] = []
            for row in rows:
                try:
                    metadata = json.loads(row.metadata_json)
                    if not isinstance(metadata, dict):
                        metadata = {}
                except Exception:
                    metadata = {}

                metadata.setdefault("contract_id", row.contract_id)
                metadata.setdefault("chunk_id", row.chunk_id)

                output.append(
                    {
                        "chunk_id": row.chunk_id,
                        "text": row.text,
                        "metadata": metadata,
                    }
                )

            return output

    def chunk_count(self) -> int:
        if not self._db_enabled or self.SessionLocal is None:
            return 0

        with self.SessionLocal() as session:
            rows = session.execute(select(StoredContractChunk.chunk_id)).all()
            return len(rows)

    def chunk_revision(self) -> str:
        if not self._db_enabled or self.SessionLocal is None:
            return ""

        with self.SessionLocal() as session:
            row = session.execute(
                select(StoredContractChunk.updated_at)
                .order_by(desc(StoredContractChunk.updated_at))
                .limit(1)
            ).first()

            if not row or not row[0]:
                return ""
            return row[0].isoformat()
