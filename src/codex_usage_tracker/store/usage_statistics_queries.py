"""Read-only call selection for dashboard usage statistics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codex_usage_tracker.core.paths import DEFAULT_DB_PATH
from codex_usage_tracker.store.connection import connect
from codex_usage_tracker.store.rows import row_to_dict
from codex_usage_tracker.store.schema import init_db


@dataclass(frozen=True)
class UsageStatisticsSelection:
    """Ordered materialized calls plus source-generation readiness metadata."""

    rows: list[dict[str, Any]]
    data_state: str
    reason: str | None
    source_generation: int
    fact_generation: int | None
    materialized_call_count: int


def query_usage_statistics_rows(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    since: str,
    until: str,
    include_archived: bool,
    model: str | None = None,
) -> UsageStatisticsSelection:
    """Return timestamp-ordered materialized calls for one dashboard statistics range."""

    with connect(db_path) as connection:
        init_db(connection)
        readiness = _statistics_readiness(connection)
        if readiness["data_state"] != "ready":
            return UsageStatisticsSelection(
                rows=[],
                data_state=str(readiness["data_state"]),
                reason=str(readiness["reason"]),
                source_generation=int(readiness["source_generation"]),
                fact_generation=(
                    int(readiness["fact_generation"])
                    if readiness["fact_generation"] is not None
                    else None
                ),
                materialized_call_count=int(readiness["materialized_call_count"]),
            )

        clauses = ["event_timestamp >= ?", "event_timestamp < ?"]
        params: list[object] = [since, until]
        if not include_archived:
            clauses.append("is_archived = 0")
        if model == "Unknown model":
            clauses.append("model IS NULL")
        elif model:
            clauses.append("model = ?")
            params.append(model)

        rows = connection.execute(
            f"""
            SELECT
                record_id,
                event_timestamp,
                thread_key,
                model,
                effort,
                total_tokens,
                usage_credits,
                usage_credit_confidence
            FROM recommendation_facts
            WHERE {' AND '.join(clauses)}
            ORDER BY event_timestamp ASC, record_id ASC
            """,  # nosec B608 - clauses are selected from fixed internal predicates.
            params,
        ).fetchall()

    return UsageStatisticsSelection(
        rows=[row_to_dict(row) for row in rows],
        data_state="ready",
        reason=None,
        source_generation=int(readiness["source_generation"]),
        fact_generation=int(readiness["fact_generation"]),
        materialized_call_count=int(readiness["materialized_call_count"]),
    )


def _statistics_readiness(connection: Any) -> dict[str, object]:
    source_row = connection.execute(
        "SELECT generation FROM compression_source_state WHERE singleton = 1"
    ).fetchone()
    source_generation = int(source_row["generation"] if source_row is not None else 0)
    fact_row = connection.execute(
        """
        SELECT source_generation, record_count
        FROM recommendation_fact_state
        WHERE singleton = 1
        """
    ).fetchone()
    if fact_row is None:
        return {
            "data_state": "refresh_required",
            "reason": "recommendation_facts_missing",
            "source_generation": source_generation,
            "fact_generation": None,
            "materialized_call_count": 0,
        }
    fact_generation = int(fact_row["source_generation"])
    record_count = int(fact_row["record_count"])
    if fact_generation != source_generation:
        return {
            "data_state": "refresh_required",
            "reason": "recommendation_facts_stale",
            "source_generation": source_generation,
            "fact_generation": fact_generation,
            "materialized_call_count": record_count,
        }
    return {
        "data_state": "ready",
        "reason": None,
        "source_generation": source_generation,
        "fact_generation": fact_generation,
        "materialized_call_count": record_count,
    }
