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


@dataclass(frozen=True)
class _StatisticsReadiness:
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
    """Return one ordered scan of priced facts joined to canonical call dimensions."""

    with connect(db_path) as connection:
        init_db(connection)
        readiness = _statistics_readiness(connection)
        if readiness.data_state != "ready":
            return UsageStatisticsSelection(
                rows=[],
                data_state=readiness.data_state,
                reason=readiness.reason,
                source_generation=readiness.source_generation,
                fact_generation=readiness.fact_generation,
                materialized_call_count=readiness.materialized_call_count,
            )

        clauses = ["facts.event_timestamp >= ?", "facts.event_timestamp < ?"]
        params: list[object] = [since, until]
        if not include_archived:
            clauses.append("facts.is_archived = 0")
        if model == "Unknown model":
            clauses.append("(facts.model IS NULL OR trim(facts.model) = '')")
        elif model:
            clauses.append("trim(facts.model) = ?")
            params.append(model.strip())

        rows = connection.execute(
            f"""
            SELECT
                facts.record_id,
                facts.event_timestamp,
                facts.thread_key,
                facts.model,
                facts.effort,
                facts.input_tokens,
                facts.cached_input_tokens,
                facts.uncached_input_tokens,
                facts.output_tokens,
                facts.reasoning_output_tokens,
                facts.total_tokens,
                facts.context_window_percent,
                facts.usage_credits,
                facts.usage_credit_confidence,
                usage_events.session_id,
                usage_events.turn_id,
                usage_events.turn_timestamp,
                usage_events.thread_name,
                usage_events.cwd,
                usage_events.call_initiator,
                usage_events.rate_limit_plan_type,
                usage_events.rate_limit_primary_used_percent,
                usage_events.rate_limit_primary_window_minutes,
                usage_events.rate_limit_secondary_used_percent,
                usage_events.rate_limit_secondary_window_minutes,
                usage_events.service_tier,
                usage_events.fast,
                usage_events.thread_source,
                usage_events.subagent_type,
                usage_events.agent_role,
                usage_events.parent_session_id,
                previous_usage.event_timestamp AS previous_call_event_timestamp,
                previous_usage.session_id AS previous_call_session_id,
                previous_usage.turn_id AS previous_call_turn_id
            FROM recommendation_facts AS facts
            JOIN canonical_usage_events AS usage_events
                ON usage_events.record_id = facts.record_id
            LEFT JOIN usage_events AS previous_usage
                ON previous_usage.record_id = usage_events.previous_record_id
            WHERE {' AND '.join(clauses)}
            ORDER BY facts.event_timestamp ASC, facts.record_id ASC
            """,  # nosec B608 - clauses are selected from fixed internal predicates.
            params,
        ).fetchall()

    return UsageStatisticsSelection(
        rows=[row_to_dict(row) for row in rows],
        data_state="ready",
        reason=None,
        source_generation=readiness.source_generation,
        fact_generation=readiness.fact_generation,
        materialized_call_count=readiness.materialized_call_count,
    )


def _statistics_readiness(connection: Any) -> _StatisticsReadiness:
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
        return _StatisticsReadiness(
            data_state="refresh_required",
            reason="recommendation_facts_missing",
            source_generation=source_generation,
            fact_generation=None,
            materialized_call_count=0,
        )
    fact_generation = int(fact_row["source_generation"])
    record_count = int(fact_row["record_count"])
    if fact_generation != source_generation:
        return _StatisticsReadiness(
            data_state="refresh_required",
            reason="recommendation_facts_stale",
            source_generation=source_generation,
            fact_generation=fact_generation,
            materialized_call_count=record_count,
        )
    return _StatisticsReadiness(
        data_state="ready",
        reason=None,
        source_generation=source_generation,
        fact_generation=fact_generation,
        materialized_call_count=record_count,
    )
