"""Dashboard-only descriptive statistics over materialized canonical calls."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any
from zoneinfo import ZoneInfo

from codex_usage_tracker.application.statistics_model_rows import (
    build_model_rows,
    new_model_state,
    normalize_model_label,
    record_model_call,
)
from codex_usage_tracker.application.statistics_models import (
    StatisticsRequest,
    parse_statistics_timestamp,
)
from codex_usage_tracker.core.paths import DEFAULT_DB_PATH
from codex_usage_tracker.store.usage_statistics_queries import query_usage_statistics_rows

STATISTICS_SCHEMA = "codex-usage-tracker.dashboard-statistics.v1"
MAX_HOURLY_SERIES_DAYS = 30


def get_usage_statistics(
    request: StatisticsRequest,
    *,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, object]:
    """Build a compact statistics payload from one timestamp-ordered database read."""

    start = parse_statistics_timestamp(request.since, "since")
    end = parse_statistics_timestamp(request.until, "until")
    selected = query_usage_statistics_rows(
        db_path=db_path,
        since=_iso(start),
        until=_iso(end),
        include_archived=request.history == "all",
        model=request.model,
    )
    effective_start = start
    if request.all_time and selected.rows:
        first = _timestamp(selected.rows[0].get("event_timestamp"))
        if first is not None:
            effective_start = max(start, first)
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
            "all_time": request.all_time,
        },
    }
    if selected.data_state != "ready":
        return payload
    payload.update(_aggregate(selected.rows, request, effective_start, end))
    return payload


def _aggregate(
    rows: list[dict[str, Any]],
    request: StatisticsRequest,
    start: datetime,
    end: datetime,
) -> dict[str, object]:
    zone = ZoneInfo(request.timezone)
    credits: list[float] = []
    confidence = Counter[str]()
    models: dict[str, dict[str, Any]] = defaultdict(new_model_state)
    daily_calls: Counter[date] = Counter()
    daily_credits: defaultdict[date, float] = defaultdict(float)
    hourly_calls: Counter[datetime] = Counter()
    hourly_credits: defaultdict[datetime, float] = defaultdict(float)
    heat_calls: Counter[tuple[int, int]] = Counter()
    heat_credits: defaultdict[tuple[int, int], float] = defaultdict(float)
    heat_dates: dict[tuple[int, int], set[date]] = defaultdict(set)
    sessions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    transitions: Counter[tuple[str, str]] = Counter()
    previous_model: str | None = None
    previous_at: datetime | None = None
    top_calls: list[dict[str, object]] = []
    gap = request.session_gap_minutes * 60

    for row in rows:
        observed = _timestamp(row.get("event_timestamp"))
        if observed is None:
            continue
        local = observed.astimezone(zone)
        day = local.date()
        hour = observed.replace(minute=0, second=0, microsecond=0)
        model = normalize_model_label(row.get("model"))
        value = _credit(row.get("usage_credits"))
        label = str(row.get("usage_credit_confidence") or "unpriced")
        if value is None:
            label = "unpriced"
        confidence[label] += 1
        daily_calls[day] += 1
        hourly_calls[hour] += 1
        heat_key = (local.weekday(), local.hour)
        heat_calls[heat_key] += 1
        heat_dates[heat_key].add(day)
        record_model_call(models[model], row, day=day, hour=hour, credit=value)
        if value is not None:
            credits.append(value)
            daily_credits[day] += value
            hourly_credits[hour] += value
            heat_credits[heat_key] += value
            top_calls.append(
                {
                    "record_id": str(row.get("record_id") or ""),
                    "event_timestamp": _iso(observed),
                    "model": model,
                    "usage_credits": round(value, 6),
                    "usage_credit_confidence": label,
                    "total_tokens": int(row.get("total_tokens") or 0),
                }
            )
        new_session = previous_at is None or (observed - previous_at).total_seconds() > gap
        if new_session:
            if current is not None:
                sessions.append(current)
            current = _new_session(observed, model)
            previous_model = None
        assert current is not None
        current["end_at"] = observed
        current["calls"] += 1
        current["models"].add(model)
        if value is not None:
            current["known_credits"] += value
            current["priced_calls"] += 1
        if previous_model is not None and previous_model != model:
            transitions[(previous_model, model)] += 1
            current["model_switches"] += 1
        previous_model = model
        previous_at = observed
    if current is not None:
        sessions.append(current)

    days = _days(start, end, zone)
    series = _series(days, daily_calls, daily_credits)
    hourly_series = _hourly_series(
        start,
        end,
        zone,
        hourly_calls,
        hourly_credits,
        all_time=request.all_time,
    )
    total_credits = sum(credits)
    distribution = _distribution(credits)
    active_days = sum(1 for item in series if item["calls"])
    elapsed_hours = max((end - start).total_seconds() / 3600, 0)
    session_rows = [_session_payload(item) for item in sessions]
    top_calls.sort(
        key=lambda item: _object_number(item.get("usage_credits")),
        reverse=True,
    )
    session_rows.sort(
        key=lambda item: _object_number(item.get("known_credits")),
        reverse=True,
    )
    return {
        "coverage": {
            "total_call_count": len(rows),
            "priced_call_count": len(credits),
            "unpriced_call_count": len(rows) - len(credits),
            "priced_call_ratio": _rate(len(credits), len(rows)) or 0.0,
            "known_usage_credits": round(total_credits, 6),
            "confidence_counts": dict(confidence),
            "first_event_at": rows[0].get("event_timestamp") if rows else None,
            "last_event_at": rows[-1].get("event_timestamp") if rows else None,
        },
        "headline": {
            "known_usage_credits": round(total_credits, 6),
            "calls": len(rows),
            "mean_credits_per_priced_call": distribution["mean"],
            "median_credits_per_priced_call": distribution["median"],
            "credits_per_calendar_day": _rate(total_credits, len(days)),
            "credits_per_active_hour": _rate(total_credits, len(hourly_calls)),
        },
        "distribution": distribution,
        "time_rates": {
            "calendar_day_count": len(days),
            "active_day_count": active_days,
            "elapsed_hours": round(elapsed_hours, 6),
            "active_hour_bucket_count": len(hourly_calls),
            "credits_per_calendar_day": _rate(total_credits, len(days)),
            "credits_per_active_day": _rate(total_credits, active_days),
            "credits_per_elapsed_hour": _rate(total_credits, elapsed_hours),
            "credits_per_active_hour": _rate(total_credits, len(hourly_calls)),
            "calls_per_calendar_day": _rate(len(rows), len(days)),
            "calls_per_active_day": _rate(len(rows), active_days),
            "calls_per_elapsed_hour": _rate(len(rows), elapsed_hours),
            "calls_per_active_hour": _rate(len(rows), len(hourly_calls)),
        },
        "model_rows": build_model_rows(
            models,
            total_credits=total_credits,
            total_calls=len(rows),
            distribution=_distribution,
            rate=_rate,
        ),
        "series": {"granularity": "day", "points": series},
        "hourly_series": hourly_series,
        "heatmap": [
            {
                "weekday": weekday,
                "hour": hour_value,
                "calls": heat_calls[(weekday, hour_value)],
                "known_credits": round(heat_credits[(weekday, hour_value)], 6),
                "active_dates": len(heat_dates[(weekday, hour_value)]),
            }
            for weekday in range(7)
            for hour_value in range(24)
        ],
        "sessions": {
            "count": len(session_rows),
            "average_calls_per_session": _rate(len(rows), len(session_rows)),
            "rows": session_rows[: request.top_limit],
        },
        "concentration": _concentration(credits, daily_credits, hourly_credits, session_rows),
        "model_transitions": {
            "switch_count": sum(transitions.values()),
            "switches_per_100_calls": _rate(sum(transitions.values()) * 100, len(rows)),
            "rows": [
                {"from_model": source, "to_model": target, "count": count}
                for (source, target), count in transitions.most_common(request.top_limit)
            ],
        },
        "top_calls": top_calls[: request.top_limit],
    }


def _distribution(values: list[float]) -> dict[str, object]:
    if not values:
        empty: dict[str, object] = {
            key: None
            for key in (
                "mean",
                "median",
                "p75",
                "p90",
                "p95",
                "minimum",
                "maximum",
                "population_standard_deviation",
            )
        }
        empty["count"] = 0
        return empty
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(fmean(ordered), 6),
        "median": round(_quantile(ordered, 0.5), 6),
        "p75": round(_quantile(ordered, 0.75), 6),
        "p90": round(_quantile(ordered, 0.9), 6),
        "p95": round(_quantile(ordered, 0.95), 6),
        "minimum": round(ordered[0], 6),
        "maximum": round(ordered[-1], 6),
        "population_standard_deviation": round(pstdev(ordered), 6),
    }


def _quantile(values: list[float], fraction: float) -> float:
    position = (len(values) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _series(
    days: list[date],
    calls: Mapping[date, int],
    credits: Mapping[date, float],
) -> list[dict[str, object]]:
    values: list[float] = []
    result = []
    for day in days:
        value = float(credits.get(day, 0.0))
        values.append(value)
        result.append(
            {
                "period_start": day.isoformat(),
                "calls": calls.get(day, 0),
                "known_credits": round(value, 6),
                "rolling_7d_credits": round(fmean(values[-7:]), 6),
                "rolling_30d_credits": round(fmean(values[-30:]), 6),
            }
        )
    return result


def _hourly_series(
    start: datetime,
    end: datetime,
    zone: ZoneInfo,
    calls: Mapping[datetime, int],
    credits: Mapping[datetime, float],
    *,
    all_time: bool,
) -> dict[str, object] | None:
    if all_time or end - start > timedelta(days=MAX_HOURLY_SERIES_DAYS):
        return None
    return {
        "granularity": "hour",
        "timezone": str(zone.key),
        "points": [
            {
                "period_start": _iso(hour),
                "local_period_start": hour.astimezone(zone).isoformat(),
                "calls": calls.get(hour, 0),
                "known_credits": round(float(credits.get(hour, 0.0)), 6),
            }
            for hour in _hours(start, end)
        ],
    }


def _days(start: datetime, end: datetime, zone: ZoneInfo) -> list[date]:
    if start >= end:
        return []
    first = start.astimezone(zone).date()
    last = (end - timedelta(microseconds=1)).astimezone(zone).date()
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _hours(start: datetime, end: datetime) -> list[datetime]:
    if start >= end:
        return []
    first = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    last = (end - timedelta(microseconds=1)).astimezone(timezone.utc).replace(
        minute=0,
        second=0,
        microsecond=0,
    )
    count = int((last - first).total_seconds() // 3600) + 1
    return [first + timedelta(hours=offset) for offset in range(count)]


def _new_session(observed: datetime, model: str) -> dict[str, Any]:
    return {
        "start_at": observed,
        "end_at": observed,
        "calls": 0,
        "known_credits": 0.0,
        "priced_calls": 0,
        "models": {model},
        "model_switches": 0,
    }


def _session_payload(item: dict[str, Any]) -> dict[str, object]:
    return {
        "start_at": _iso(item["start_at"]),
        "end_at": _iso(item["end_at"]),
        "duration_seconds": round((item["end_at"] - item["start_at"]).total_seconds(), 6),
        "calls": item["calls"],
        "known_credits": round(item["known_credits"], 6),
        "priced_calls": item["priced_calls"],
        "priced_call_ratio": _rate(item["priced_calls"], item["calls"]),
        "models": sorted(item["models"]),
        "model_switches": item["model_switches"],
    }


def _concentration(
    credits: list[float],
    daily: Mapping[date, float],
    hourly: Mapping[datetime, float],
    sessions: list[dict[str, object]],
) -> dict[str, object]:
    ordered = sorted(credits, reverse=True)
    total = sum(ordered)

    def share(values: list[float], count: int = 1) -> float | None:
        return _rate(sum(values[:count]), total)

    return {
        "top_1_percent_call_share": (
            share(ordered, max(1, math.ceil(len(ordered) * 0.01))) if ordered else None
        ),
        "top_10_percent_call_share": (
            share(ordered, max(1, math.ceil(len(ordered) * 0.10))) if ordered else None
        ),
        "busiest_day_share": share(sorted(daily.values(), reverse=True)) if daily else None,
        "busiest_hour_share": share(sorted(hourly.values(), reverse=True)) if hourly else None,
        "busiest_session_share": (
            share([_object_number(row.get("known_credits")) for row in sessions])
            if sessions
            else None
        ),
    }


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (
        parsed.astimezone(timezone.utc)
        if parsed.tzinfo
        else parsed.replace(tzinfo=timezone.utc)
    )


def _credit(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _object_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _rate(numerator: float | int, denominator: float | int) -> float | None:
    return round(float(numerator) / float(denominator), 6) if denominator else None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
