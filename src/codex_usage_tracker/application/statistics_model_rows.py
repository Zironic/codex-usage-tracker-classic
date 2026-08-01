"""Per-model token composition and credit statistics helpers."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

DistributionBuilder = Callable[[list[float]], dict[str, object]]
RateBuilder = Callable[[float | int, float | int], float | None]

_TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def new_model_state() -> dict[str, Any]:
    """Return mutable counters for one normalized model label."""

    return {
        "calls": 0,
        "credits": [],
        "days": set(),
        "hours": set(),
        **{field: 0 for field in _TOKEN_FIELDS},
        "context_window_total": 0.0,
        "context_window_count": 0,
    }


def record_model_call(
    state: dict[str, Any],
    row: dict[str, Any],
    *,
    day: date,
    hour: datetime,
    credit: float | None,
) -> None:
    """Accumulate one call into a model cohort."""

    state["calls"] += 1
    state["days"].add(day)
    state["hours"].add(hour)
    for field in _TOKEN_FIELDS:
        state[field] += _nonnegative_number(row.get(field))
    context = _optional_nonnegative_number(row.get("context_window_percent"))
    if context is not None:
        state["context_window_total"] += context
        state["context_window_count"] += 1
    if credit is not None:
        state["credits"].append(credit)


def build_model_rows(
    models: dict[str, dict[str, Any]],
    *,
    total_credits: float,
    total_calls: int,
    distribution: DistributionBuilder,
    rate: RateBuilder,
) -> list[dict[str, object]]:
    """Return sortable model rows with credit and weighted token composition metrics."""

    rows = [
        _model_row(
            model,
            state,
            total_credits=total_credits,
            total_calls=total_calls,
            distribution=distribution,
            rate=rate,
        )
        for model, state in models.items()
    ]
    return sorted(
        rows,
        key=lambda row: (
            -_object_number(row.get("known_credits")),
            -_object_number(row.get("calls")),
            str(row.get("model") or ""),
        ),
    )


def _model_row(
    model: str,
    state: dict[str, Any],
    *,
    total_credits: float,
    total_calls: int,
    distribution: DistributionBuilder,
    rate: RateBuilder,
) -> dict[str, object]:
    calls = int(state["calls"])
    credits = list(state["credits"])
    known_credits = sum(credits)
    input_tokens = float(state["input_tokens"])
    total_tokens = float(state["total_tokens"])
    output_tokens = float(state["output_tokens"])
    dist = distribution(credits)
    return {
        "model": model,
        "calls": calls,
        "call_share": rate(calls, total_calls),
        "priced_calls": len(credits),
        "priced_call_ratio": rate(len(credits), calls),
        "known_credits": round(known_credits, 6),
        "credit_share": rate(known_credits, total_credits),
        "active_days": len(state["days"]),
        "active_hour_buckets": len(state["hours"]),
        "total_tokens": int(total_tokens),
        "input_tokens": int(input_tokens),
        "cached_input_tokens": int(state["cached_input_tokens"]),
        "uncached_input_tokens": int(state["uncached_input_tokens"]),
        "output_tokens": int(output_tokens),
        "reasoning_output_tokens": int(state["reasoning_output_tokens"]),
        "avg_total_tokens_per_call": rate(total_tokens, calls),
        "avg_input_tokens_per_call": rate(input_tokens, calls),
        "avg_cached_input_tokens_per_call": rate(state["cached_input_tokens"], calls),
        "avg_uncached_input_tokens_per_call": rate(state["uncached_input_tokens"], calls),
        "avg_output_tokens_per_call": rate(output_tokens, calls),
        "avg_reasoning_tokens_per_call": rate(state["reasoning_output_tokens"], calls),
        "weighted_cache_ratio": rate(state["cached_input_tokens"], input_tokens),
        "output_ratio": rate(output_tokens, total_tokens),
        "reasoning_output_ratio": rate(state["reasoning_output_tokens"], output_tokens),
        "average_context_window_percent": rate(
            state["context_window_total"],
            state["context_window_count"],
        ),
        "credits_per_million_total_tokens": (
            rate(known_credits * 1_000_000, total_tokens) if credits else None
        ),
        **{
            key: dist[key]
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
        },
    }


def _object_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _nonnegative_number(value: object) -> float:
    parsed = _optional_nonnegative_number(value)
    return parsed if parsed is not None else 0.0


def _optional_nonnegative_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) and parsed >= 0 else None
