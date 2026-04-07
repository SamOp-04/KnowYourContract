from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, desc, func
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

    SQLALCHEMY_AVAILABLE = True
except Exception:
    SQLALCHEMY_AVAILABLE = False

from src.utils.db import should_auto_create_tables

DEFAULT_DATABASE_URL = "sqlite:///data/processed/metrics.db"


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


    class RagasMetricLog(Base):
        __tablename__ = "ragas_metrics"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        query: Mapped[str] = mapped_column(Text, nullable=False)
        answer: Mapped[str] = mapped_column(Text, nullable=False)
        tool_used: Mapped[str] = mapped_column(String(64), default="contract_search", nullable=False)
        used_web_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
        faithfulness: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        answer_relevance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        context_precision: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        context_recall: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
else:
    class Base:  # type: ignore[no-redef]
        pass


    class RagasMetricLog:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.id = int(kwargs.get("id", 0))
            self.query = str(kwargs.get("query", ""))
            self.answer = str(kwargs.get("answer", ""))
            self.tool_used = str(kwargs.get("tool_used", "contract_search"))
            self.used_web_fallback = bool(kwargs.get("used_web_fallback", False))
            self.faithfulness = float(kwargs.get("faithfulness", 0.0))
            self.answer_relevance = float(kwargs.get("answer_relevance", 0.0))
            self.context_precision = float(kwargs.get("context_precision", 0.0))
            self.context_recall = float(kwargs.get("context_recall", 0.0))
            self.created_at = kwargs.get("created_at", datetime.now(timezone.utc).replace(tzinfo=None))


class MetricsStore:
    def __init__(self, database_url: str | None = None) -> None:
        self._memory_rows: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.database_url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        if SQLALCHEMY_AVAILABLE:
            _ensure_sqlite_parent_dir(self.database_url)
            self.engine = create_engine(self.database_url, future=True)
            self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        else:
            self.engine = None
            self.SessionLocal = None

    def init_db(self) -> None:
        if SQLALCHEMY_AVAILABLE and should_auto_create_tables(self.database_url):
            Base.metadata.create_all(bind=self.engine)

    def save_metric(self, payload: dict[str, Any]) -> int:
        if SQLALCHEMY_AVAILABLE:
            with self.SessionLocal() as session:
                row = RagasMetricLog(
                    query=str(payload.get("query", "")),
                    answer=str(payload.get("answer", "")),
                    tool_used=str(payload.get("tool_used", "contract_search")),
                    used_web_fallback=bool(payload.get("used_web_fallback", False)),
                    faithfulness=float(payload.get("faithfulness", 0.0)),
                    answer_relevance=float(payload.get("answer_relevance", 0.0)),
                    context_precision=float(payload.get("context_precision", 0.0)),
                    context_recall=float(payload.get("context_recall", 0.0)),
                    created_at=_as_utc_naive(payload.get("created_at")),
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return int(row.id)

        with self._lock:
            row = {
                "id": len(self._memory_rows) + 1,
                "query": str(payload.get("query", "")),
                "answer": str(payload.get("answer", "")),
                "tool_used": str(payload.get("tool_used", "contract_search")),
                "used_web_fallback": bool(payload.get("used_web_fallback", False)),
                "faithfulness": float(payload.get("faithfulness", 0.0)),
                "answer_relevance": float(payload.get("answer_relevance", 0.0)),
                "context_precision": float(payload.get("context_precision", 0.0)),
                "context_recall": float(payload.get("context_recall", 0.0)),
                "created_at": _as_utc_naive(payload.get("created_at")),
            }
            self._memory_rows.append(row)
        return int(row["id"])

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if SQLALCHEMY_AVAILABLE:
            with self.SessionLocal() as session:
                rows = (
                    session.query(RagasMetricLog)
                    .order_by(desc(RagasMetricLog.created_at))
                    .limit(limit)
                    .all()
                )
                return [self._to_dict(row) for row in rows]

        sorted_rows = sorted(self._memory_rows, key=lambda row: _as_utc_naive(row.get("created_at")), reverse=True)
        return [self._to_dict(row) for row in sorted_rows[:limit]]

    def get_trends(self, days: int = 7) -> list[dict[str, Any]]:
        threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        if SQLALCHEMY_AVAILABLE:
            with self.SessionLocal() as session:
                rows = (
                    session.query(RagasMetricLog)
                    .filter(RagasMetricLog.created_at >= threshold)
                    .order_by(RagasMetricLog.created_at.asc())
                    .all()
                )
                return [self._to_dict(row) for row in rows]

        rows = [row for row in self._memory_rows if _as_utc_naive(row.get("created_at")) >= threshold]
        rows = sorted(rows, key=lambda row: _as_utc_naive(row.get("created_at")))
        return [self._to_dict(row) for row in rows]

    def get_query_analytics(self) -> list[dict[str, Any]]:
        if SQLALCHEMY_AVAILABLE:
            with self.SessionLocal() as session:
                rows = (
                    session.query(
                        RagasMetricLog.tool_used,
                        func.count(RagasMetricLog.id).label("count"),
                        func.avg(RagasMetricLog.faithfulness).label("avg_faithfulness"),
                    )
                    .group_by(RagasMetricLog.tool_used)
                    .order_by(desc("count"))
                    .all()
                )

                return [
                    {
                        "tool_used": tool_used,
                        "count": int(count),
                        "avg_faithfulness": float(avg_faithfulness or 0.0),
                    }
                    for tool_used, count, avg_faithfulness in rows
                ]

        aggregates: dict[str, dict[str, float]] = {}
        for row in self._memory_rows:
            tool = row["tool_used"]
            if tool not in aggregates:
                aggregates[tool] = {"count": 0.0, "faithfulness_sum": 0.0}
            aggregates[tool]["count"] += 1.0
            aggregates[tool]["faithfulness_sum"] += float(row.get("faithfulness", 0.0))

        output = []
        for tool, stats in aggregates.items():
            count = int(stats["count"])
            output.append(
                {
                    "tool_used": tool,
                    "count": count,
                    "avg_faithfulness": (stats["faithfulness_sum"] / count) if count > 0 else 0.0,
                }
            )

        output.sort(key=lambda item: item["count"], reverse=True)
        return output

    @staticmethod
    def _to_dict(row: RagasMetricLog) -> dict[str, Any]:
        if isinstance(row, dict):
            created_iso = _as_utc_naive(row.get("created_at")).isoformat()
            return {
                "id": int(row.get("id", 0)),
                "query": str(row.get("query", "")),
                "answer": str(row.get("answer", "")),
                "tool_used": str(row.get("tool_used", "contract_search")),
                "used_web_fallback": bool(row.get("used_web_fallback", False)),
                "faithfulness": float(row.get("faithfulness", 0.0)),
                "answer_relevance": float(row.get("answer_relevance", 0.0)),
                "context_precision": float(row.get("context_precision", 0.0)),
                "context_recall": float(row.get("context_recall", 0.0)),
                "created_at": created_iso,
            }

        return {
            "id": row.id,
            "query": row.query,
            "answer": row.answer,
            "tool_used": row.tool_used,
            "used_web_fallback": row.used_web_fallback,
            "faithfulness": row.faithfulness,
            "answer_relevance": row.answer_relevance,
            "context_precision": row.context_precision,
            "context_recall": row.context_recall,
            "created_at": row.created_at.isoformat(),
        }
