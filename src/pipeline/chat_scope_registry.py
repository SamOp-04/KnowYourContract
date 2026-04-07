from __future__ import annotations

import json
from pathlib import Path


class ChatScopeRegistry:
    def __init__(
        self,
        registry_path: Path | str = Path("data/processed/chat_scope_registry.json"),
    ) -> None:
        self.registry_path = Path(registry_path)

    def add_contracts(self, chat_id: str, contract_ids: list[str]) -> None:
        resolved_chat_id = self._normalize_chat_id(chat_id)
        if not resolved_chat_id:
            raise ValueError("chat_id is required.")

        normalized_contract_ids = self._normalize_contract_ids(contract_ids)
        if not normalized_contract_ids:
            return

        payload = self._read_payload()
        existing = self._normalize_contract_ids(payload.get(resolved_chat_id, []))
        merged = self._normalize_contract_ids(existing + normalized_contract_ids)
        payload[resolved_chat_id] = merged
        self._write_payload(payload)

    def list_contract_ids(self, chat_id: str) -> list[str]:
        resolved_chat_id = self._normalize_chat_id(chat_id)
        if not resolved_chat_id:
            return []

        payload = self._read_payload()
        return self._normalize_contract_ids(payload.get(resolved_chat_id, []))

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
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
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
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
