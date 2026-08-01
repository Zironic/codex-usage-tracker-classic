"""Dashboard-only statistics over materialized canonical calls."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codex_usage_tracker.application.statistics_analysis import aggregate_usage_statistics
from codex_usage_tracker.application.statistics_models import (
    StatisticsRequest,
    parse_statistics_timestamp,
)
from codex_usage_tracker.core.paths import DEFAULT_DB_PATH
from codex_usage_tracker.pricing.allowance_config import load_allowance_config
from codex_usage_tracker.pricing.allowance_rate_history import CreditRateRevision
from codex_usage_tracker.store.usage_statistics_queries import query_usage_statistics_rows

STATISTICS_SCHEMA = "codex-usage-tracker.dashboard-statistics.v1"


def get_usage_statistics(
    request: StatisticsRequest,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, object]:
    """Build one compact dashboard payload from a single ordered database read."""

    start = parse_statistics_timestamp(request.since, "since")
    end = parse_statistics_timestamp(request.until, "until")
    selected = query_usage_statistics_rows(
        db_path=db_path,
        since=_iso(start),
        until=_iso(end),
        include_archived=request.history == "all",
        model=request.model,
    )
    effective_start = _effective_start(start, selected.rows, all_time=request.all_time)
    revisions = _rate_revisions()
    payload: dict[str, object] = {
        "schema": STATISTICS_SCHEMA,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "source_generation": selected.source_generation,
        "fact_generation": selected.fact_generation,
        "materialized_call_count": selected.materialized_call_count,
        "data_state": selected.data_state,
        "reason": selected.reason,
        "scope": {
            "since": _iso(start),
            "until": _iso(end),
            "effective_since": _iso(effective_start),
            "timezone": request.timezone,
            "history": request.history,
            "model": request.model,
            "session_gap_minutes": request.session_gap_minutes,
            "active_gap_cap_minutes": request.active_gap_cap_minutes,
            "comparison_at": request.comparison_at,
            "all_time": request.all_time,
            "rate_revision_count": len(revisions),
        },
    }
    if selected.data_state != "ready":
        return payload
    analysis = aggregate_usage_statistics(
        selected.rows,
        request,
        start=effective_start,
        end=end,
        rate_revisions=revisions,
    )
    _replace_private_turn_keys(analysis)
    payload.update(analysis)
    return payload


def _replace_private_turn_keys(payload: dict[str, object]) -> None:
    """Replace persisted turn identifiers with response-local ordinal labels."""

    seen: dict[str, int] = {}
    next_index = 0
    for section in (payload.get("turns"), payload.get("activity")):
        if not isinstance(section, dict):
            continue
        candidates = (
            section.get("rows")
            if "rows" in section
            else section.get("most_active_turns")
        )
        if not isinstance(candidates, list):
            continue
        for item in candidates:
            if not isinstance(item, dict):
                continue
            raw = item.pop("turn_group", None)
            if not isinstance(raw, str):
                continue
            if raw not in seen:
                seen[raw] = next_index
                next_index += 1
            item["turn_group"] = seen[raw]


def _effective_start(
    requested_start: datetime,
    rows: list[dict[str, Any]],
    *,
    all_time: bool,
) -> datetime:
    if not all_time or not rows:
        return requested_start
    first = _timestamp(rows[0].get("event_timestamp"))
    return max(requested_start, first) if first is not None else requested_start


def _rate_revisions() -> tuple[CreditRateRevision, ...]:
    try:
        return load_allowance_config().rate_revisions
    except (OSError, TypeError, ValueError):
        return ()


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
