"""Focused descriptive queries for delegation-efficiency history."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from codex_usage_tracker.core.paths import DEFAULT_DB_PATH
from codex_usage_tracker.store.connection import connect
from codex_usage_tracker.store.query_sql import usage_where_clause
from codex_usage_tracker.store.rows import row_to_dict
from codex_usage_tracker.store.schema import init_db
from codex_usage_tracker.store.subagent_usage_queries import SUBAGENT_PREDICATE

DIRECT_SOL_MODEL = "gpt-5.6-sol"
LUNA_ROLES = ("luna_worker_high", "luna_worker_low")

_DIRECT_METRICS = """
    COUNT(*) AS calls,
    COUNT(DISTINCT CASE
      WHEN session_id_known = 1
       AND nullif(trim(session_id), '') IS NOT NULL
       AND nullif(trim(turn_id), '') IS NOT NULL
      THEN session_id || ':' || turn_id
      ELSE 'record:' || record_id
    END) AS turns,
    SUM(CASE
      WHEN session_id_known = 1
       AND nullif(trim(session_id), '') IS NOT NULL
       AND nullif(trim(turn_id), '') IS NOT NULL
      THEN 1 ELSE 0
    END) AS exact_turn_calls,
    SUM(CASE
      WHEN session_id_known = 1
       AND nullif(trim(session_id), '') IS NOT NULL
       AND nullif(trim(turn_id), '') IS NOT NULL
      THEN 0 ELSE 1
    END) AS fallback_turn_calls,
    coalesce(SUM(input_tokens), 0) AS input_tokens,
    coalesce(SUM(cached_input_tokens), 0) AS cached_input_tokens,
    coalesce(SUM(uncached_input_tokens), 0) AS uncached_input_tokens,
    coalesce(SUM(output_tokens), 0) AS output_tokens,
    coalesce(SUM(reasoning_output_tokens), 0) AS reasoning_output_tokens,
    coalesce(SUM(total_tokens), 0) AS total_tokens,
    MIN(event_timestamp) AS first_event,
    MAX(event_timestamp) AS last_event
"""

_TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def query_direct_sol_before_after_luna(
    db_path: Path = DEFAULT_DB_PATH,
    *,
    since: str | None = None,
    until: str | None = None,
    adoption_at: str | None = None,
    parent_thread: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Compare direct Sol tokens per turn around the first observed Luna role."""

    where_sql, params = usage_where_clause(
        since=since,
        until=until,
        thread=parent_thread,
        table_alias="usage_events",
        include_archived=include_archived,
    )
    with connect(db_path) as conn:
        init_db(conn)
        observed_boundary, observed_role = _first_luna_observation(conn, where_sql, params)
        boundary = adoption_at or observed_boundary
        if boundary is None:
            return {
                "adoption_at": None,
                "adoption_role": None,
                "adoption_source": "not_observed",
                "direct_model": DIRECT_SOL_MODEL,
                "before": _empty_period(),
                "after": _empty_period(),
            }
        direct_where = _append_clause(
            where_sql,
            f"usage_events.model = ? AND NOT coalesce({SUBAGENT_PREDICATE}, 0)",
        )
        direct_params = [*params, DIRECT_SOL_MODEL]
        before = _direct_period(
            conn,
            _append_clause(direct_where, "usage_events.event_timestamp < ?"),
            [*direct_params, boundary],
        )
        after = _direct_period(
            conn,
            _append_clause(direct_where, "usage_events.event_timestamp >= ?"),
            [*direct_params, boundary],
        )
    return {
        "adoption_at": boundary,
        "adoption_role": None if adoption_at is not None else observed_role,
        "adoption_source": "caller_supplied" if adoption_at is not None else "first_observed_luna_role",
        "direct_model": DIRECT_SOL_MODEL,
        "before": before,
        "after": after,
    }


def _first_luna_observation(
    conn: sqlite3.Connection,
    where_sql: str,
    params: list[Any],
) -> tuple[str | None, str | None]:
    luna_where = _append_clause(
        where_sql,
        f"{SUBAGENT_PREDICATE} AND usage_events.agent_role IN (?, ?)",
    )
    row = conn.execute(
        "SELECT usage_events.event_timestamp AS adoption_at, usage_events.agent_role "
        f"FROM canonical_usage_events AS usage_events {luna_where} "  # nosec B608
        "ORDER BY usage_events.event_timestamp, usage_events.record_id LIMIT 1",
        [*params, *LUNA_ROLES],
    ).fetchone()
    if row is None:
        return None, None
    timestamp = row["adoption_at"]
    role = row["agent_role"]
    return (
        str(timestamp) if timestamp is not None else None,
        str(role) if role is not None else None,
    )


def _direct_period(
    conn: sqlite3.Connection,
    where_sql: str,
    params: list[Any],
) -> dict[str, int | float | str | None]:
    row = row_to_dict(
        conn.execute(
            f"SELECT {_DIRECT_METRICS} "
            f"FROM canonical_usage_events AS usage_events {where_sql}",  # nosec B608
            params,
        ).fetchone()
    )
    turns = int(row.get("turns") or 0)
    result: dict[str, int | float | str | None] = {
        "calls": int(row.get("calls") or 0),
        "turns": turns,
        "calls_per_turn": int(row.get("calls") or 0) / turns if turns else None,
        "exact_turn_calls": int(row.get("exact_turn_calls") or 0),
        "fallback_turn_calls": int(row.get("fallback_turn_calls") or 0),
        "first_event": str(row["first_event"]) if row.get("first_event") else None,
        "last_event": str(row["last_event"]) if row.get("last_event") else None,
    }
    for field_name in _TOKEN_FIELDS:
        value = int(row.get(field_name) or 0)
        result[field_name] = value
        result[f"{field_name.removesuffix('_tokens')}_tokens_per_turn"] = (
            value / turns if turns else None
        )
    result["tokens_per_turn"] = result["total_tokens_per_turn"]
    return result


def _empty_period() -> dict[str, int | float | str | None]:
    result: dict[str, int | float | str | None] = {
        "calls": 0,
        "turns": 0,
        "calls_per_turn": None,
        "exact_turn_calls": 0,
        "fallback_turn_calls": 0,
        "first_event": None,
        "last_event": None,
    }
    for field_name in _TOKEN_FIELDS:
        result[field_name] = 0
        result[f"{field_name.removesuffix('_tokens')}_tokens_per_turn"] = None
    result["tokens_per_turn"] = None
    return result


def _append_clause(where_sql: str, clause: str) -> str:
    return f"{where_sql} AND ({clause})" if where_sql else f"WHERE ({clause})"


__all__ = ["DIRECT_SOL_MODEL", "LUNA_ROLES", "query_direct_sol_before_after_luna"]
