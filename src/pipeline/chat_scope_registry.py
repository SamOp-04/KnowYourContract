from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from filelock import FileLock
except Exception:
    FileLock = None

try:
    from sqlalchemy import DateTime, Integer, String, UniqueConstraint, create_engine, select
    from sqlalchemy.exc import IntegrityError
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


if SQLALCHEMY_AVAILABLE:
    class Base(DeclarativeBase):
        pass


    class ChatScopeContract(Base):
        __tablename__ = "chat_scope_contracts"
        __table_args__ = (
            UniqueConstraint("chat_id", "contract_id", name="uq_chat_scope_contract"),
        )

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        chat_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
        contract_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_utc_naive, nullable=False)


else:
    class Base:  # type: ignore[no-redef]
        pass


    class ChatScopeContract:  # type: ignore[no-redef]
        pass


class ChatScopeRegistry:
    def __init__(
        self,
        registry_path: Path | str = Path("data/processed/chat_scope_registry.json"),
        backend: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self.registry_path = Path(registry_path)
        self._lock = threading.RLock()
        self._file_lock = FileLock(f"{self.registry_path}.lock") if FileLock is not None else None
        self.database_url = str(database_url or os.getenv("DATABASE_URL", "")).strip()
        resolved_backend = str(backend or os.getenv("REGISTRY_BACKEND", "auto")).strip().lower()
        self._db_enabled = False
        self.engine = None
        self.SessionLocal = None

        if resolved_backend not in {"auto", "file", "db"}:
            resolved_backend = "auto"

        if resolved_backend != "file":
            self._try_enable_db(strict=(resolved_backend == "db"))

    def _try_enable_db(self, strict: bool) -> None:
        if not SQLALCHEMY_AVAILABLE:
            if strict:
                raise RuntimeError("SQLAlchemy is required for REGISTRY_BACKEND=db.")
            return

        if not self.database_url:
            if strict:
                raise RuntimeError("DATABASE_URL is required for REGISTRY_BACKEND=db.")
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
                raise RuntimeError("Failed to initialize DB-backed ChatScopeRegistry.") from error

    def add_contracts(self, chat_id: str, contract_ids: list[str]) -> None:
        resolved_chat_id = self._normalize_chat_id(chat_id)
        if not resolved_chat_id:
            raise ValueError("chat_id is required.")

        normalized_contract_ids = self._normalize_contract_ids(contract_ids)
        if not normalized_contract_ids:
            return

        if self._db_enabled:
            self._add_contracts_db(chat_id=resolved_chat_id, contract_ids=normalized_contract_ids)
            return

        with self._locked():
            payload = self._read_payload()
            existing = self._normalize_contract_ids(payload.get(resolved_chat_id, []))
            merged = self._normalize_contract_ids(existing + normalized_contract_ids)
            payload[resolved_chat_id] = merged
            self._write_payload(payload)

    def list_contract_ids(self, chat_id: str) -> list[str]:
        resolved_chat_id = self._normalize_chat_id(chat_id)
        if not resolved_chat_id:
            return []

        if self._db_enabled:
            return self._list_contract_ids_db(chat_id=resolved_chat_id)

        with self._locked():
            payload = self._read_payload()
            return self._normalize_contract_ids(payload.get(resolved_chat_id, []))

    def _add_contracts_db(self, chat_id: str, contract_ids: list[str]) -> None:
        if self.SessionLocal is None:
            return

        with self.SessionLocal() as session:
            existing_rows = session.execute(
                select(ChatScopeContract.contract_id).where(ChatScopeContract.chat_id == chat_id)
            ).all()
            existing = {str(row[0]).strip() for row in existing_rows if str(row[0]).strip()}

            for contract_id in contract_ids:
                if contract_id in existing:
                    continue
                session.add(
                    ChatScopeContract(
                        chat_id=chat_id,
                        contract_id=contract_id,
                        created_at=_now_utc_naive(),
                    )
                )

            try:
                session.commit()
            except IntegrityError:
                # Another process may have inserted the same chat/contract mapping.
                session.rollback()

    def _list_contract_ids_db(self, chat_id: str) -> list[str]:
        if self.SessionLocal is None:
            return []

        with self.SessionLocal() as session:
            rows = session.execute(
                select(ChatScopeContract.contract_id)
                .where(ChatScopeContract.chat_id == chat_id)
                .order_by(ChatScopeContract.id.asc())
            ).all()
            return self._normalize_contract_ids([str(row[0]) for row in rows if row and row[0]])

    @contextmanager
    def _locked(self):
        with self._lock:
            if self._file_lock is None:
                yield
            else:
                with self._file_lock:
                    yield

    @staticmethod
    def _normalize_chat_id(chat_id: str | None) -> str:
        return str(chat_id or "").strip()

    @staticmethod
    def _normalize_contract_ids(contract_ids: list[str] | tuple[str, ...] | None) -> list[str]:
        if not contract_ids:
            return []

        output: list[str] = []
        seen: set[str] = set()
        for contract_id in contract_ids:
            normalized = str(contract_id or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(normalized)

        return output

    def _read_payload(self) -> dict[str, list[str]]:
        if not self.registry_path.exists():
            return {}

        try:
            payload: Any = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return {}

            output: dict[str, list[str]] = {}
            for key, value in payload.items():
                chat_id = self._normalize_chat_id(str(key))
                if not chat_id:
                    continue
                if not isinstance(value, list):
                    continue
                output[chat_id] = self._normalize_contract_ids(value)

            return output
        except Exception:
            return {}

    def _write_payload(self, payload: dict[str, list[str]]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.registry_path.with_suffix(f"{self.registry_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self.registry_path)
