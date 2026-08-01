"""One-pass aggregation for dashboard-only usage statistics."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from statistics import fmean, pstdev
from typing import Any
from zoneinfo import ZoneInfo

from codex_usage_tracker.application.statistics_activity import EnrichedCall, enrich_call
from codex_usage_tracker.application.statistics_grouping import (
    build_attribution,
    build_breakdowns,
    build_cohorts,
)
from codex_usage_tracker.application.statistics_model_rows import (
    build_model_rows,
    new_model_state,
    record_model_call,
)
from codex_usage_tracker.application.statistics_models import StatisticsRequest
from codex_usage_tracker.pricing.allowance_rate_history import (
    CreditRateRevision,
    revision_for_timestamp,
)

MAX_HOURLY_SERIES_DAYS = 30


def aggregate_usage_statistics(
    rows: list[dict[str, Any]],
    request: StatisticsRequest,
    *,
    start: datetime,
    end: datetime,
    rate_revisions: Sequence[CreditRateRevision],
) -> dict[str, object]:
    """Build the Statistics payload from one timestamp-ordered row stream."""

    zone = ZoneInfo(request.timezone)
    credits: list[float] = []
    confidence = Counter[str]()
    models: dict[str, dict[str, Any]] = defaultdict(new_model_state)
    daily_calls: Counter[date] = Counter()
    daily_credits: defaultdict[date, float] = defaultdict(float)
    daily_active_seconds: defaultdict[date, float] = defaultdict(float)
    hourly_calls: Counter[datetime] = Counter()
    hourly_credits: defaultdict[datetime, float] = defaultdict(float)
    hourly_active_seconds: defaultdict[datetime, float] = defaultdict(float)
    heat_calls: Counter[tuple[int, int]] = Counter()
    heat_credits: defaultdict[tuple[int, int], float] = defaultdict(float)
    heat_active_seconds: defaultdict[tuple[int, int], float] = defaultdict(float)
    heat_dates: dict[tuple[int, int], set[date]] = defaultdict(set)
    sessions: list[dict[str, Any]] = []
    current_session: dict[str, Any] | None = None
    turns: dict[str, dict[str, Any]] = {}
    transitions: Counter[tuple[str, str]] = Counter()
    previous_model: str | None = None
    previous_at: datetime | None = None
    top_calls: list[dict[str, object]] = []
    enriched_calls: list[EnrichedCall] = []
    session_gap_seconds = request.session_gap_minutes * 60
    active_gap_cap_seconds = request.active_gap_cap_minutes * 60

    for row in rows:
        observed = _timestamp(row.get("event_timestamp"))
        if observed is None:
            continue
        local = observed.astimezone(zone)
        revision = revision_for_timestamp(rate_revisions, row.get("event_timestamp"))
        call = enrich_call(
            row,
            observed=observed,
            range_start=start,
            local_day=local.date(),
            local_hour=local.hour,
            gap_cap_seconds=active_gap_cap_seconds,
            rate_revision=revision.revision_id if revision is not None else "",
        )
        enriched_calls.append(call)
        hour = observed.replace(minute=0, second=0, microsecond=0)
        label = str(row.get("usage_credit_confidence") or "unpriced")
        if call.credits is None:
            label = "unpriced"
        confidence[label] += 1
        daily_calls[call.local_day] += 1
        daily_active_seconds[call.local_day] += call.active_seconds
        hourly_calls[hour] += 1
        hourly_active_seconds[hour] += call.active_seconds
        heat_key = (local.weekday(), local.hour)
        heat_calls[heat_key] += 1
        heat_active_seconds[heat_key] += call.active_seconds
        heat_dates[heat_key].add(call.local_day)
        record_model_call(
            models[call.model],
            row,
            day=call.local_day,
            hour=hour,
            credit=call.credits,
        )
        if call.credits is not None:
            credits.append(call.credits)
            daily_credits[call.local_day] += call.credits
            hourly_credits[hour] += call.credits
            heat_credits[heat_key] += call.credits
            top_calls.append(_top_call_payload(call, label))

        new_session = (
            previous_at is None
            or (observed - previous_at).total_seconds() > session_gap_seconds
        )
        if new_session:
            if current_session is not None:
                sessions.append(current_session)
            current_session = _new_session(call)
            previous_model = None
        if current_session is None:
            raise RuntimeError("statistics session state was not initialized")
        _add_session_call(current_session, call)
        _add_turn_call(turns, call)
        if previous_model is not None and previous_model != call.model:
            transitions[(previous_model, call.model)] += 1
            current_session["model_switches"] += 1
        previous_model = call.model
        previous_at = observed
    if current_session is not None:
        sessions.append(current_session)

    days = _days(start, end, zone)
    series = _series(days, daily_calls, daily_credits, daily_active_seconds)
    hourly_series = _hourly_series(
        start,
        end,
        zone,
        hourly_calls,
        hourly_credits,
        hourly_active_seconds,
        all_time=request.all_time,
    )
    total_credits = sum(credits)
    total_active_seconds = sum(call.active_seconds for call in enriched_calls)
    active_hours = total_active_seconds / 3600
    distribution = _distribution(credits)
    active_days = sum(1 for item in series if item["calls"])
    elapsed_hours = max((end - start).total_seconds() / 3600, 0)
    session_rows = [_session_payload(item) for item in sessions]
    session_rows.sort(key=lambda item: _object_number(item.get("active_seconds")), reverse=True)
    turn_rows = [_turn_payload(item) for item in turns.values()]
    turn_rows.sort(key=lambda item: _object_number(item.get("active_seconds")), reverse=True)
    top_calls.sort(key=lambda item: _object_number(item.get("usage_credits")), reverse=True)
    total_calls = len(enriched_calls)
    comparison_at = request.comparison_timestamp()

    return {
        "coverage": {
            "total_call_count": total_calls,
            "priced_call_count": len(credits),
            "unpriced_call_count": total_calls - len(credits),
            "priced_call_ratio": _rate(len(credits), total_calls) or 0.0,
            "known_usage_credits": round(total_credits, 6),
            "confidence_counts": dict(confidence),
            "first_event_at": _iso(enriched_calls[0].observed) if enriched_calls else None,
            "last_event_at": _iso(enriched_calls[-1].observed) if enriched_calls else None,
        },
        "headline": {
            "known_usage_credits": round(total_credits, 6),
            "calls": total_calls,
            "estimated_active_minutes": round(total_active_seconds / 60, 3),
            "estimated_active_hours": round(active_hours, 6),
            "distinct_turns": len(turns),
            "mean_credits_per_priced_call": distribution["mean"],
            "median_credits_per_priced_call": distribution["median"],
            "credits_per_calendar_day": _rate(total_credits, len(days)),
            "credits_per_active_hour": _rate(total_credits, active_hours),
            "calls_per_active_hour": _rate(total_calls, active_hours),
            "credits_per_turn": _rate(total_credits, len(turns)),
            "calls_per_turn": _rate(total_calls, len(turns)),
            "subagent_calls_per_turn": _rate(
                sum(int(call.is_subagent) for call in enriched_calls),
                len(turns),
            ),
        },
        "distribution": distribution,
        "time_rates": {
            "calendar_day_count": len(days),
            "active_day_count": active_days,
            "elapsed_hours": round(elapsed_hours, 6),
            "active_hour_bucket_count": len(hourly_calls),
            "estimated_active_minutes": round(total_active_seconds / 60, 3),
            "estimated_active_hours": round(active_hours, 6),
            "credits_per_calendar_day": _rate(total_credits, len(days)),
            "credits_per_active_day": _rate(total_credits, active_days),
            "credits_per_elapsed_hour": _rate(total_credits, elapsed_hours),
            "credits_per_active_hour_bucket": _rate(total_credits, len(hourly_calls)),
            "credits_per_active_hour": _rate(total_credits, active_hours),
            "calls_per_calendar_day": _rate(total_calls, len(days)),
            "calls_per_active_day": _rate(total_calls, active_days),
            "calls_per_elapsed_hour": _rate(total_calls, elapsed_hours),
            "calls_per_active_hour_bucket": _rate(total_calls, len(hourly_calls)),
            "calls_per_active_hour": _rate(total_calls, active_hours),
        },
        "activity": _activity_payload(
            enriched_calls,
            session_rows,
            turn_rows,
            total_credits=total_credits,
            total_active_seconds=total_active_seconds,
            top_limit=request.top_limit,
        ),
        "model_rows": build_model_rows(
            models,
            total_credits=total_credits,
            total_calls=total_calls,
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
                "active_minutes": round(
                    heat_active_seconds[(weekday, hour_value)] / 60,
                    3,
                ),
                "active_dates": len(heat_dates[(weekday, hour_value)]),
            }
            for weekday in range(7)
            for hour_value in range(24)
        ],
        "sessions": {
            "count": len(session_rows),
            "average_calls_per_session": _rate(total_calls, len(session_rows)),
            "duration_distribution": _distribution(
                [_object_number(item.get("duration_seconds")) for item in session_rows]
            ),
            "active_duration_distribution": _distribution(
                [_object_number(item.get("active_seconds")) for item in session_rows]
            ),
            "rows": session_rows[: request.top_limit],
        },
        "turns": {
            "count": len(turn_rows),
            "calls_per_turn": _rate(total_calls, len(turn_rows)),
            "credits_per_turn": _rate(total_credits, len(turn_rows)),
            "subagent_calls_per_turn": _rate(
                sum(int(call.is_subagent) for call in enriched_calls),
                len(turn_rows),
            ),
            "rows": turn_rows[: request.top_limit],
        },
        "breakdowns": build_breakdowns(
            enriched_calls,
            total_calls=total_calls,
            total_credits=total_credits,
            total_active_seconds=total_active_seconds,
            top_limit=request.top_limit,
        ),
        "attribution": build_attribution(
            enriched_calls,
            total_calls=total_calls,
            total_credits=total_credits,
            total_active_seconds=total_active_seconds,
            top_limit=request.top_limit,
        ),
        "cohorts": build_cohorts(
            enriched_calls,
            range_start=start,
            range_end=end,
            comparison_at=comparison_at,
            total_calls=total_calls,
            total_credits=total_credits,
            total_active_seconds=total_active_seconds,
        ),
        "concentration": _concentration(credits, daily_credits, hourly_credits, session_rows),
        "model_transitions": {
            "switch_count": sum(transitions.values()),
            "switches_per_100_calls": _rate(sum(transitions.values()) * 100, total_calls),
            "rows": [
                {"from_model": source, "to_model": target, "count": count}
                for (source, target), count in transitions.most_common(request.top_limit)
            ],
        },
        "top_calls": top_calls[: request.top_limit],
    }


def _activity_payload(
    calls: list[EnrichedCall],
    session_rows: list[dict[str, object]],
    turn_rows: list[dict[str, object]],
    *,
    total_credits: float,
    total_active_seconds: float,
    top_limit: int,
) -> dict[str, object]:
    active_hours = total_active_seconds / 3600
    turn_count = len(turn_rows)
    subagent_calls = sum(int(call.is_subagent) for call in calls)
    session_durations = [_object_number(row.get("duration_seconds")) for row in session_rows]
    return {
        "estimated_active_seconds": round(total_active_seconds, 3),
        "estimated_active_minutes": round(total_active_seconds / 60, 3),
        "estimated_active_hours": round(active_hours, 6),
        "measured_call_duration_seconds": round(sum(call.duration_seconds for call in calls), 3),
        "capped_inter_call_gap_seconds": round(sum(call.capped_gap_seconds for call in calls), 3),
        "distinct_turns": turn_count,
        "calls_per_turn": _rate(len(calls), turn_count),
        "credits_per_turn": _rate(total_credits, turn_count),
        "subagent_calls": subagent_calls,
        "subagent_calls_per_turn": _rate(subagent_calls, turn_count),
        "calls_per_active_hour": _rate(len(calls), active_hours),
        "credits_per_active_hour": _rate(total_credits, active_hours),
        "median_session_duration_seconds": _quantile_or_none(session_durations, 0.5),
        "p75_session_duration_seconds": _quantile_or_none(session_durations, 0.75),
        "p90_session_duration_seconds": _quantile_or_none(session_durations, 0.9),
        "longest_work_periods": session_rows[:top_limit],
        "most_active_turns": turn_rows[:top_limit],
    }


def _new_session(call: EnrichedCall) -> dict[str, Any]:
    return {
        "start_at": call.call_started_at,
        "end_at": call.observed,
        "calls": 0,
        "known_credits": 0.0,
        "priced_calls": 0,
        "active_seconds": 0.0,
        "models": set(),
        "turns": set(),
        "subagent_calls": 0,
        "model_switches": 0,
    }


def _add_session_call(state: dict[str, Any], call: EnrichedCall) -> None:
    state["start_at"] = min(state["start_at"], call.call_started_at)
    state["end_at"] = max(state["end_at"], call.observed)
    state["calls"] += 1
    state["active_seconds"] += call.active_seconds
    state["models"].add(call.model)
    state["turns"].add(call.turn_key)
    state["subagent_calls"] += int(call.is_subagent)
    if call.credits is not None:
        state["known_credits"] += call.credits
        state["priced_calls"] += 1


def _add_turn_call(turns: dict[str, dict[str, Any]], call: EnrichedCall) -> None:
    state = turns.setdefault(
        call.turn_key,
        {
            "turn_key": call.turn_key,
            "start_at": call.call_started_at,
            "end_at": call.observed,
            "calls": 0,
            "known_credits": 0.0,
            "priced_calls": 0,
            "active_seconds": 0.0,
            "subagent_calls": 0,
            "models": set(),
        },
    )
    state["start_at"] = min(state["start_at"], call.call_started_at)
    state["end_at"] = max(state["end_at"], call.observed)
    state["calls"] += 1
    state["active_seconds"] += call.active_seconds
    state["subagent_calls"] += int(call.is_subagent)
    state["models"].add(call.model)
    if call.credits is not None:
        state["known_credits"] += call.credits
        state["priced_calls"] += 1


def _session_payload(item: dict[str, Any]) -> dict[str, object]:
    active_hours = float(item["active_seconds"]) / 3600
    turns = len(item["turns"])
    return {
        "start_at": _iso(item["start_at"]),
        "end_at": _iso(item["end_at"]),
        "duration_seconds": round((item["end_at"] - item["start_at"]).total_seconds(), 3),
        "active_seconds": round(float(item["active_seconds"]), 3),
        "active_minutes": round(float(item["active_seconds"]) / 60, 3),
        "calls": item["calls"],
        "turns": turns,
        "known_credits": round(float(item["known_credits"]), 6),
        "priced_calls": item["priced_calls"],
        "priced_call_ratio": _rate(item["priced_calls"], item["calls"]),
        "credits_per_active_hour": _rate(item["known_credits"], active_hours),
        "models": sorted(item["models"]),
        "subagent_calls": item["subagent_calls"],
        "model_switches": item["model_switches"],
    }


def _turn_payload(item: dict[str, Any]) -> dict[str, object]:
    active_hours = float(item["active_seconds"]) / 3600
    return {
        "turn_group": item["turn_key"],
        "start_at": _iso(item["start_at"]),
        "end_at": _iso(item["end_at"]),
        "duration_seconds": round((item["end_at"] - item["start_at"]).total_seconds(), 3),
        "active_seconds": round(float(item["active_seconds"]), 3),
        "active_minutes": round(float(item["active_seconds"]) / 60, 3),
        "calls": item["calls"],
        "known_credits": round(float(item["known_credits"]), 6),
        "priced_calls": item["priced_calls"],
        "credits_per_active_hour": _rate(item["known_credits"], active_hours),
        "subagent_calls": item["subagent_calls"],
        "models": sorted(item["models"]),
    }


def _top_call_payload(call: EnrichedCall, confidence: str) -> dict[str, object]:
    row = call.row
    return {
        "record_id": str(row.get("record_id") or ""),
        "event_timestamp": _iso(call.observed),
        "model": call.model,
        "effort": call.effort,
        "initiator_kind": call.initiator_kind,
        "project": call.project,
        "thread": call.thread,
        "usage_credits": round(call.credits or 0.0, 6),
        "usage_credit_confidence": confidence,
        "total_tokens": call.total_tokens,
        "duration_seconds": round(call.duration_seconds, 3),
        "active_seconds": round(call.active_seconds, 3),
        "reasoning_output_tokens": int(row.get("reasoning_output_tokens") or 0),
        "cache_ratio": _rate(
            int(row.get("cached_input_tokens") or 0),
            int(row.get("input_tokens") or 0),
        ),
        "context_window_percent": _optional_float(row.get("context_window_percent")),
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


def _quantile_or_none(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    return round(_quantile(sorted(values), fraction), 3)


def _series(
    days: list[date],
    calls: Mapping[date, int],
    credits: Mapping[date, float],
    active_seconds: Mapping[date, float],
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
                "active_minutes": round(float(active_seconds.get(day, 0.0)) / 60, 3),
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
    active_seconds: Mapping[datetime, float],
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
                "active_minutes": round(float(active_seconds.get(hour, 0.0)) / 60, 3),
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
            share(ordered, max(1, math.ceil(len(ordered) * 0.1))) if ordered else None
        ),
        "top_day_share": share(sorted(daily.values(), reverse=True)),
        "top_hour_share": share(sorted(hourly.values(), reverse=True)),
        "top_session_share": share(
            sorted(
                [_object_number(item.get("known_credits")) for item in sessions],
                reverse=True,
            )
        ),
    }


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


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _object_number(value: object) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else 0.0


def _rate(numerator: float | int, denominator: float | int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
