from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_bool_env(name: str) -> bool | None:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return None
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return None


def should_auto_create_tables(database_url: str) -> bool:
    """
    Decide whether runtime startup should create tables automatically.

    DB_AUTO_CREATE_TABLES wins when set explicitly. Otherwise, keep auto-create
    enabled only for local SQLite workflows and disabled for shared DB engines.
    """
    explicit = _parse_bool_env("DB_AUTO_CREATE_TABLES")
    if explicit is not None:
        return explicit

    normalized_url = str(database_url or "").strip().lower()
    return normalized_url.startswith("sqlite:///")
