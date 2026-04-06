from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class ContractRegistry:
    def __init__(
        self,
        registry_path: Path | str = Path("data/processed/contracts_registry.json"),
        raw_upload_dir: Path | str = Path("data/raw/uploads"),
        chunk_metadata_path: Path | str = Path("data/processed/chunk_metadata.json"),
    ) -> None:
        self.registry_path = Path(registry_path)
        self.raw_upload_dir = Path(raw_upload_dir)
        self.chunk_metadata_path = Path(chunk_metadata_path)

    def list_contracts(self) -> list[dict[str, Any]]:
        rows = self._read_rows()
        rows = self._merge_with_existing_uploads(rows)
        rows.sort(key=lambda row: str(row.get("uploaded_at", "")), reverse=True)
        return rows

    def upsert(
        self,
        contract_id: str,
        source_name: str,
        chunks_ingested: int,
        uploaded_at: str | None = None,
    ) -> dict[str, Any]:
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
        self.registry_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

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

        merged = list(merged_by_id.values())
        self._write_rows(merged)
        return merged

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
        for item in payload:
            if not isinstance(item, dict):
                continue
            contract_id = str(item.get("contract_id") or item.get("contract_name") or "").strip()
            if not contract_id:
                continue
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
            contract_id = str(item.get("contract_id") or item.get("contract_name") or "").strip()
            source_name = str(item.get("source_name", "")).strip()
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
