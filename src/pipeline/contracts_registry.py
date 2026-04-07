from __future__ import annotations

import json
import os
import re
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
    from sqlalchemy import DateTime, Integer, String, create_engine, desc, select
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

    return datetime.now(timezone.utc).replace(tzinfo=None)


if SQLALCHEMY_AVAILABLE:
    class Base(DeclarativeBase):
        pass


    class ContractRecord(Base):
        __tablename__ = "contracts_registry"

        contract_id: Mapped[str] = mapped_column(String(256), primary_key=True)
        display_name: Mapped[str] = mapped_column(String(512), nullable=False)
        source_name: Mapped[str] = mapped_column(String(512), nullable=False)
        chunks_ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
        uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)


else:
    class Base:  # type: ignore[no-redef]
        pass


    class ContractRecord:  # type: ignore[no-redef]
        pass


class ContractRegistry:
    def __init__(
        self,
        registry_path: Path | str = Path("data/processed/contracts_registry.json"),
        raw_upload_dir: Path | str = Path("data/raw/uploads"),
        chunk_metadata_path: Path | str = Path("data/processed/chunk_metadata.json"),
        backend: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.raw_upload_dir = Path(raw_upload_dir)
        self.chunk_metadata_path = Path(chunk_metadata_path)
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
                raise RuntimeError("Failed to initialize DB-backed ContractRegistry.") from error

    def list_contracts(self) -> list[dict[str, Any]]:
        if self._db_enabled:
            return self._list_contracts_db()

        with self._locked():
            rows = self._read_rows()
            merged_rows = self._merge_with_existing_uploads(rows)
            if merged_rows != rows:
                self._write_rows(merged_rows)
            merged_rows.sort(key=lambda row: str(row.get("uploaded_at", "")), reverse=True)
            return merged_rows

    def upsert(
        self,
        contract_id: str,
        source_name: str,
        chunks_ingested: int,
        uploaded_at: str | None = None,
    ) -> dict[str, Any]:
        if self._db_enabled:
            return self._upsert_db(
                contract_id=contract_id,
                source_name=source_name,
                chunks_ingested=chunks_ingested,
                uploaded_at=uploaded_at,
            )

        with self._locked():
            rows = self._read_rows()
            now_iso = uploaded_at or datetime.utcnow().isoformat()

            record = {
                "contract_id": contract_id,
                "display_name": _to_display_name(source_name=source_name, contract_id=contract_id),
                "source_name": source_name,
                "chunks_ingested": int(chunks_ingested),
                "uploaded_at": now_iso,
            }

            updated = False
            for index, row in enumerate(rows):
                if str(row.get("contract_id", "")) == contract_id:
                    rows[index] = record
                    updated = True
                    break

            if not updated:
                rows.append(record)

            rows = self._merge_with_existing_uploads(rows)
            self._write_rows(rows)
            return record

    def _upsert_db(
        self,
        contract_id: str,
        source_name: str,
        chunks_ingested: int,
        uploaded_at: str | None = None,
    ) -> dict[str, Any]:
        if self.SessionLocal is None:
            raise RuntimeError("DB session is not initialized for ContractRegistry.")

        resolved_uploaded_at = _as_utc_naive(uploaded_at)
        display_name = _to_display_name(source_name=source_name, contract_id=contract_id)

        with self.SessionLocal() as session:
            existing = session.get(ContractRecord, contract_id)
            if existing is None:
                existing = ContractRecord(
                    contract_id=contract_id,
                    display_name=display_name,
                    source_name=source_name,
                    chunks_ingested=int(chunks_ingested),
                    uploaded_at=resolved_uploaded_at,
                )
                session.add(existing)
            else:
                existing.display_name = display_name
                existing.source_name = source_name
                existing.chunks_ingested = int(chunks_ingested)
                existing.uploaded_at = resolved_uploaded_at

            session.commit()

            return {
                "contract_id": existing.contract_id,
                "display_name": existing.display_name,
                "source_name": existing.source_name,
                "chunks_ingested": int(existing.chunks_ingested),
                "uploaded_at": existing.uploaded_at.isoformat(),
            }

    def _list_contracts_db(self) -> list[dict[str, Any]]:
        if self.SessionLocal is None:
            return []

        with self.SessionLocal() as session:
            rows = session.execute(
                select(ContractRecord).order_by(desc(ContractRecord.uploaded_at))
            ).scalars().all()

            return [
                {
                    "contract_id": row.contract_id,
                    "display_name": row.display_name,
                    "source_name": row.source_name,
                    "chunks_ingested": int(row.chunks_ingested),
                    "uploaded_at": row.uploaded_at.isoformat(),
                }
                for row in rows
            ]

    @contextmanager
    def _locked(self):
        with self._lock:
            if self._file_lock is None:
                yield
            else:
                with self._file_lock:
                    yield

    def _read_rows(self) -> list[dict[str, Any]]:
        if not self.registry_path.exists():
            return []

        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                return []
            rows = []
            for item in payload:
                if isinstance(item, dict) and str(item.get("contract_id", "")).strip():
                    rows.append(item)
            return rows
        except Exception:
            return []

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.registry_path.with_suffix(f"{self.registry_path.suffix}.tmp")
        temp_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        temp_path.replace(self.registry_path)

    def _merge_with_existing_uploads(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        discovered_by_id: dict[str, dict[str, Any]] = {}
        for discovered in self._discover_existing_uploads():
            contract_id = str(discovered.get("contract_id", "")).strip()
            if contract_id:
                discovered_by_id[contract_id] = discovered

        merged_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            contract_id = str(row.get("contract_id", "")).strip()
            if not contract_id:
                continue

            discovered = discovered_by_id.get(contract_id, {})
            source_name = str(row.get("source_name") or discovered.get("source_name") or "").strip()
            merged_by_id[contract_id] = {
                "contract_id": contract_id,
                "display_name": _to_display_name(source_name=source_name, contract_id=contract_id),
                "source_name": source_name or f"{contract_id}.txt",
                "chunks_ingested": int(max(int(row.get("chunks_ingested", 0)), int(discovered.get("chunks_ingested", 0)))),
                "uploaded_at": str(row.get("uploaded_at") or discovered.get("uploaded_at") or datetime.utcnow().isoformat()),
            }

        for contract_id, discovered in discovered_by_id.items():
            if contract_id not in merged_by_id:
                merged_by_id[contract_id] = discovered

        return list(merged_by_id.values())

    def _discover_existing_uploads(self) -> list[dict[str, Any]]:
        if not self.raw_upload_dir.exists():
            return []

        chunk_counts = self._read_chunk_counts()
        source_names = self._read_source_names()

        records: list[dict[str, Any]] = []
        for path in sorted(self.raw_upload_dir.glob("*.txt")):
            contract_id = path.stem.strip()
            if not contract_id:
                continue
            uploaded_at = datetime.utcfromtimestamp(path.stat().st_mtime).isoformat()
            source_name = source_names.get(contract_id, path.name)
            records.append(
                {
                    "contract_id": contract_id,
                    "display_name": _to_display_name(source_name=source_name, contract_id=contract_id),
                    "source_name": source_name,
                    "chunks_ingested": int(chunk_counts.get(contract_id, 0)),
                    "uploaded_at": uploaded_at,
                }
            )

        return records

    def _read_chunk_counts(self) -> dict[str, int]:
        if not self.chunk_metadata_path.exists():
            return {}

        try:
            payload = json.loads(self.chunk_metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(payload, list):
            return {}

        counts: dict[str, int] = {}
        seen_chunk_ids: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue

            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            contract_id = str(
                item.get("contract_id")
                or item.get("contract_name")
                or metadata.get("contract_id")
                or metadata.get("contract_name")
                or ""
            ).strip()
            if not contract_id:
                continue

            chunk_id = str(item.get("chunk_id") or metadata.get("chunk_id") or "").strip()
            if chunk_id:
                dedupe_key = f"{contract_id}:{chunk_id}"
                if dedupe_key in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(dedupe_key)

            counts[contract_id] = counts.get(contract_id, 0) + 1

        return counts

    def _read_source_names(self) -> dict[str, str]:
        if not self.chunk_metadata_path.exists():
            return {}

        try:
            payload = json.loads(self.chunk_metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(payload, list):
            return {}

        output: dict[str, str] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            contract_id = str(
                item.get("contract_id")
                or item.get("contract_name")
                or metadata.get("contract_id")
                or metadata.get("contract_name")
                or ""
            ).strip()
            source_name = str(item.get("source_name") or metadata.get("source_name") or "").strip()
            if contract_id and source_name and contract_id not in output:
                output[contract_id] = source_name

        return output


def _to_display_name(source_name: str, contract_id: str) -> str:
    stem = Path(source_name).stem.strip() if source_name else ""
    if stem and stem != contract_id:
        normalized_stem = re.sub(r"[_\-]+", " ", stem).strip()
        if normalized_stem:
            return normalized_stem
        return stem

    candidate = contract_id
    timestamp_match = re.match(r"^(.*)_\d{14}$", contract_id)
    if timestamp_match:
        candidate = timestamp_match.group(1).strip("_")

    normalized = re.sub(r"[_\-]+", " ", candidate).strip()
    if normalized:
        return normalized

    if stem:
        return stem

    return contract_id
