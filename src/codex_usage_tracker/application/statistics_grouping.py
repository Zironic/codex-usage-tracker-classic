"""Grouped cohort, decomposition, project, and thread statistics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from codex_usage_tracker.application.statistics_activity import EnrichedCall


@dataclass
class AggregateState:
    """Mutable aggregate used by all dashboard statistics groupings."""

    label: str
    calls: int = 0
    total_tokens: int = 0
    known_credits: float = 0.0
    priced_calls: int = 0
    active_seconds: float = 0.0
    subagent_calls: int = 0
    turns: set[str] = field(default_factory=set)
    models: Counter[str] = field(default_factory=Counter)
    efforts: Counter[str] = field(default_factory=Counter)
    first_at: datetime | None = None
    last_at: datetime | None = None
    primary_meter: list[tuple[datetime, float]] = field(default_factory=list)
    secondary_meter: list[tuple[datetime, float]] = field(default_factory=list)

    def add(self, call: EnrichedCall) -> None:
        self.calls += 1
        self.total_tokens += call.total_tokens
        self.active_seconds += call.active_seconds
        self.turns.add(call.turn_key)
        self.models[call.model] += 1
        self.efforts[call.effort] += 1
        self.subagent_calls += int(call.is_subagent)
        if call.credits is not None:
            self.known_credits += call.credits
            self.priced_calls += 1
        self.first_at = call.call_started_at if self.first_at is None else min(
            self.first_at, call.call_started_at
        )
        self.last_at = call.observed if self.last_at is None else max(self.last_at, call.observed)
        if call.primary_meter_percent is not None:
            self.primary_meter.append((call.observed, call.primary_meter_percent))
        if call.secondary_meter_percent is not None:
            self.secondary_meter.append((call.observed, call.secondary_meter_percent))


def build_breakdowns(
    calls: list[EnrichedCall],
    *,
    total_calls: int,
    total_credits: float,
    total_active_seconds: float,
    top_limit: int,
) -> dict[str, list[dict[str, object]]]:
    """Return the recurring explanatory decompositions used by the Statistics page."""

    dimensions: dict[str, Callable[[EnrichedCall], tuple[Hashable, str]]] = {
        "initiator_kind": lambda call: (call.initiator_kind, call.initiator_kind),
        "initiator": lambda call: (call.initiator, call.initiator),
        "effort": lambda call: (call.effort, call.effort),
        "service_tier": lambda call: (call.service_tier, call.service_tier),
        "fast_mode": lambda call: (call.fast_mode, call.fast_mode),
        "model_effort": lambda call: (
            (call.model, call.effort),
            f"{call.model} · {call.effort}",
        ),
        "initiator_model": lambda call: (
            (call.initiator_kind, call.model),
            f"{call.initiator_kind} · {call.model}",
        ),
        "initiator_active_hour": lambda call: (
            (call.initiator_kind, call.local_hour),
            f"{call.initiator_kind} · {call.local_hour:02d}:00",
        ),
    }
    return {
        name: _group_rows(
            calls,
            selector,
            total_calls=total_calls,
            total_credits=total_credits,
            total_active_seconds=total_active_seconds,
            top_limit=top_limit,
        )
        for name, selector in dimensions.items()
    }


def build_attribution(
    calls: list[EnrichedCall],
    *,
    total_calls: int,
    total_credits: float,
    total_active_seconds: float,
    top_limit: int,
) -> dict[str, object]:
    """Attribute usage to privacy-safe project basenames and visible thread labels."""

    projects = _group_rows(
        calls,
        lambda call: (call.project, call.project),
        total_calls=total_calls,
        total_credits=total_credits,
        total_active_seconds=total_active_seconds,
        top_limit=top_limit,
        include_mix=True,
    )
    thread_states: dict[tuple[str, str], AggregateState] = {}
    for call in calls:
        key = (call.project, call.thread)
        state = thread_states.setdefault(key, AggregateState(call.thread))
        state.add(call)
    threads = [
        {
            **_state_payload(
                state,
                total_calls=total_calls,
                total_credits=total_credits,
                total_active_seconds=total_active_seconds,
                include_mix=True,
            ),
            "project": project,
            "thread": thread,
        }
        for (project, thread), state in thread_states.items()
    ]
    threads.sort(key=_row_sort_key, reverse=True)
    project_states = _states_by(calls, lambda call: (call.project, call.project))
    return {
        "projects": projects,
        "threads": threads[:top_limit],
        "concentration": {
            "top_project_credit_share": _top_share(project_states.values(), "credits"),
            "top_thread_credit_share": _top_share(thread_states.values(), "credits"),
            "project_credit_hhi": _hhi(project_states.values(), "credits"),
            "thread_credit_hhi": _hhi(thread_states.values(), "credits"),
            "project_call_hhi": _hhi(project_states.values(), "calls"),
            "thread_call_hhi": _hhi(thread_states.values(), "calls"),
        },
    }


def build_cohorts(
    calls: list[EnrichedCall],
    *,
    range_start: datetime,
    range_end: datetime,
    comparison_at: datetime | None,
    total_calls: int,
    total_credits: float,
    total_active_seconds: float,
) -> dict[str, object]:
    """Build automatic plan-rate segments and an optional arbitrary before/after split."""

    ordered = sorted(
        calls,
        key=lambda call: (call.observed, str(call.row.get("record_id") or "")),
    )
    plan_rate_rows: list[dict[str, object]] = []
    state: AggregateState | None = None
    state_key: tuple[str, str] | None = None
    for call in ordered:
        key = (call.plan, call.rate_revision)
        if state is None or key != state_key:
            if state is not None:
                plan_rate_rows.append(
                    _cohort_payload(
                        state,
                        plan=state_key[0] if state_key else "Unknown plan",
                        rate_revision=state_key[1] if state_key else "Unknown rate revision",
                        since=state.first_at or range_start,
                        until=state.last_at or range_start,
                        total_calls=total_calls,
                        total_credits=total_credits,
                        total_active_seconds=total_active_seconds,
                    )
                )
            state_key = key
            state = AggregateState(f"{key[0]} · {key[1]}")
        state.add(call)
    if state is not None:
        plan_rate_rows.append(
            _cohort_payload(
                state,
                plan=state_key[0] if state_key else "Unknown plan",
                rate_revision=state_key[1] if state_key else "Unknown rate revision",
                since=state.first_at or range_start,
                until=state.last_at or range_start,
                total_calls=total_calls,
                total_credits=total_credits,
                total_active_seconds=total_active_seconds,
            )
        )

    breakpoint_rows: list[dict[str, object]] = []
    if comparison_at is not None:
        before = AggregateState("Before")
        after = AggregateState("After")
        for call in ordered:
            (before if call.observed < comparison_at else after).add(call)
        breakpoint_rows = [
            _cohort_payload(
                before,
                plan=None,
                rate_revision=None,
                since=range_start,
                until=comparison_at,
                total_calls=total_calls,
                total_credits=total_credits,
                total_active_seconds=total_active_seconds,
            ),
            _cohort_payload(
                after,
                plan=None,
                rate_revision=None,
                since=comparison_at,
                until=range_end,
                total_calls=total_calls,
                total_credits=total_credits,
                total_active_seconds=total_active_seconds,
            ),
        ]
    return {
        "comparison_at": comparison_at.isoformat().replace("+00:00", "Z")
        if comparison_at is not None
        else None,
        "plan_rate_rows": plan_rate_rows,
        "breakpoint_rows": breakpoint_rows,
    }


def _group_rows(
    calls: list[EnrichedCall],
    selector: Callable[[EnrichedCall], tuple[Hashable, str]],
    *,
    total_calls: int,
    total_credits: float,
    total_active_seconds: float,
    top_limit: int,
    include_mix: bool = False,
) -> list[dict[str, object]]:
    states = _states_by(calls, selector)
    rows = [
        _state_payload(
            state,
            total_calls=total_calls,
            total_credits=total_credits,
            total_active_seconds=total_active_seconds,
            include_mix=include_mix,
        )
        for state in states.values()
    ]
    rows.sort(key=_row_sort_key, reverse=True)
    return rows[:top_limit]


def _states_by(
    calls: list[EnrichedCall],
    selector: Callable[[EnrichedCall], tuple[Hashable, str]],
) -> dict[Hashable, AggregateState]:
    states: dict[Hashable, AggregateState] = {}
    for call in calls:
        key, label = selector(call)
        states.setdefault(key, AggregateState(label)).add(call)
    return states


def _state_payload(
    state: AggregateState,
    *,
    total_calls: int,
    total_credits: float,
    total_active_seconds: float,
    include_mix: bool,
) -> dict[str, object]:
    turns = len(state.turns)
    active_hours = state.active_seconds / 3600
    payload: dict[str, object] = {
        "label": state.label,
        "calls": state.calls,
        "call_share": _rate(state.calls, total_calls),
        "total_tokens": state.total_tokens,
        "tokens_per_call": _rate(state.total_tokens, state.calls),
        "known_credits": round(state.known_credits, 6),
        "priced_calls": state.priced_calls,
        "priced_call_ratio": _rate(state.priced_calls, state.calls),
        "credit_share": _rate(state.known_credits, total_credits),
        "active_minutes": round(state.active_seconds / 60, 3),
        "active_time_share": _rate(state.active_seconds, total_active_seconds),
        "turns": turns,
        "calls_per_turn": _rate(state.calls, turns),
        "credits_per_turn": _rate(state.known_credits, turns),
        "credits_per_active_hour": _rate(state.known_credits, active_hours),
        "subagent_calls": state.subagent_calls,
        "subagent_calls_per_turn": _rate(state.subagent_calls, turns),
    }
    if include_mix:
        payload["model_mix"] = _mix(state.models)
        payload["effort_mix"] = _mix(state.efforts)
    return payload


def _cohort_payload(
    state: AggregateState,
    *,
    plan: str | None,
    rate_revision: str | None,
    since: datetime,
    until: datetime,
    total_calls: int,
    total_credits: float,
    total_active_seconds: float,
) -> dict[str, object]:
    elapsed_days = max((until - since).total_seconds() / 86400, 1 / 1440)
    base = _state_payload(
        state,
        total_calls=total_calls,
        total_credits=total_credits,
        total_active_seconds=total_active_seconds,
        include_mix=True,
    )
    return {
        **base,
        "plan": plan,
        "rate_revision": rate_revision,
        "since": since.isoformat().replace("+00:00", "Z"),
        "until": until.isoformat().replace("+00:00", "Z"),
        "elapsed_days": round(elapsed_days, 6),
        "calls_per_day": _rate(state.calls, elapsed_days),
        "active_minutes_per_day": _rate(state.active_seconds / 60, elapsed_days),
        "turns_per_day": _rate(len(state.turns), elapsed_days),
        "credits_per_day": _rate(state.known_credits, elapsed_days),
        "credits_per_call": _rate(state.known_credits, state.priced_calls),
        "primary_meter_burn_percent_per_day": _meter_burn_per_day(state.primary_meter),
        "secondary_meter_burn_percent_per_day": _meter_burn_per_day(state.secondary_meter),
    }


def _meter_burn_per_day(observations: list[tuple[datetime, float]]) -> float | None:
    ordered = sorted(observations)
    if len(ordered) < 2:
        return None
    positive_delta = sum(
        current - previous
        for (_previous_at, previous), (_current_at, current) in zip(
            ordered,
            ordered[1:],
            strict=False,
        )
        if current >= previous
    )
    elapsed_days = (ordered[-1][0] - ordered[0][0]).total_seconds() / 86400
    return _rate(positive_delta, elapsed_days) if elapsed_days > 0 else None


def _mix(values: Counter[str]) -> list[dict[str, object]]:
    total = sum(values.values())
    return [
        {"label": label, "calls": count, "share": _rate(count, total)}
        for label, count in values.most_common(8)
    ]


def _top_share(
    states: Iterable[AggregateState],
    metric: str,
) -> float | None:
    values = [_state_metric(state, metric) for state in states]
    total = sum(values)
    return _rate(max(values, default=0.0), total)


def _hhi(states: Iterable[AggregateState], metric: str) -> float | None:
    values = [_state_metric(state, metric) for state in states]
    total = sum(values)
    if total <= 0:
        return None
    return round(sum((value / total) ** 2 for value in values), 6)


def _state_metric(state: AggregateState, metric: str) -> float:
    return state.known_credits if metric == "credits" else float(state.calls)


def _row_sort_key(row: dict[str, object]) -> tuple[float, int, str]:
    return (
        _number(row.get("known_credits")),
        _integer(row.get("calls")),
        str(row.get("label") or ""),
    )


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _rate(numerator: float | int, denominator: float | int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)
