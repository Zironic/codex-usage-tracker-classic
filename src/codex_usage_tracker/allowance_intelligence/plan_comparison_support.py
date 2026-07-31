"""Transition selection and aggregate evidence helpers for plan comparisons."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any

from codex_usage_tracker.allowance_intelligence.capacity_history import (
    capacity_cycle_exclusion_reason,
)
from codex_usage_tracker.allowance_intelligence.cycles import normalize_plan_type
from codex_usage_tracker.allowance_intelligence.plan_comparison_statistics import (
    quantile,
    relative_meter_size,
)
from codex_usage_tracker.allowance_intelligence.statistics import _rounded

INVALID_PLAN_TYPES = frozenset({"", "unknown", "mixed"})


def select_plan_transition(
    cycles: Sequence[Mapping[str, Any]],
    *,
    from_plan: str | None,
    to_plan: str | None,
) -> dict[str, Any] | None:
    """Select the latest contiguous known-plan transition, or an explicit pair."""
    ordered = sorted(
        (dict(row) for row in cycles),
        key=lambda row: (
            str(row.get("first_observed_at") or row.get("last_observed_at") or ""),
            str(row.get("last_observed_at") or ""),
            str(row.get("cycle_id") or ""),
        ),
    )
    runs = _plan_runs(ordered)
    known_indices = [
        index for index, run in enumerate(runs) if run["plan_type"] not in INVALID_PLAN_TYPES
    ]
    candidates = _transition_candidates(runs, known_indices)
    if from_plan and to_plan:
        wanted_before = normalize_plan_type(from_plan)
        wanted_after = normalize_plan_type(to_plan)
        candidates = [
            candidate
            for candidate in candidates
            if candidate["before_plan"] == wanted_before
            and candidate["after_plan"] == wanted_after
        ]
    if not candidates:
        return None
    selected = candidates[-1]
    selected["selection_mode"] = "explicit" if from_plan and to_plan else "auto"
    return selected


def cohort_summary(
    plan_type: str,
    observed: Sequence[Mapping[str, Any]],
    eligible: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize one side of the plan transition with one vote per cycle."""
    values = [float(row["credits_per_percent"]) for row in eligible]
    coverage_values = [
        float(row["price_coverage"])
        for row in eligible
        if isinstance(row.get("price_coverage"), int | float)
    ]
    capacity = median(values) if values else None
    return {
        "plan_type": plan_type,
        "observed_cycle_count": len(observed),
        "eligible_cycle_count": len(eligible),
        "start_date": run_date(observed, first=True),
        "end_date": run_date(observed, first=False),
        "median_credits_per_percent": _rounded(capacity),
        "estimated_full_meter_credits": _rounded(capacity * 100) if capacity else None,
        "q1_credits_per_percent": _rounded(quantile(values, 0.25)) if values else None,
        "q3_credits_per_percent": _rounded(quantile(values, 0.75)) if values else None,
        "minimum_credits_per_percent": _rounded(min(values)) if values else None,
        "maximum_credits_per_percent": _rounded(max(values)) if values else None,
        "median_price_coverage": (
            _rounded(median(coverage_values)) if coverage_values else None
        ),
    }


def early_interval_estimate(
    connection: sqlite3.Connection,
    *,
    source_revision: str,
    before_cycle_ids: Sequence[str],
    after_cycle_ids: Sequence[str],
) -> dict[str, Any]:
    """Return descriptive interval evidence while complete cycles accumulate."""
    before_rows = _interval_rows(connection, source_revision, before_cycle_ids)
    after_rows = _interval_rows(connection, source_revision, after_cycle_ids)
    before_values = _interval_values(before_rows)
    after_values = _interval_values(after_rows)
    relative = relative_meter_size(before_values, after_values)
    return {
        "status": "ready" if before_values and after_values else "insufficient_intervals",
        "before_interval_count": len(before_values),
        "after_interval_count": len(after_values),
        "before_median_credits_per_percent": (
            _rounded(median(before_values)) if before_values else None
        ),
        "after_median_credits_per_percent": (
            _rounded(median(after_values)) if after_values else None
        ),
        "after_to_before_ratio": relative["after_to_before_ratio"],
        "after_as_percent_of_before": relative["after_as_percent_of_before"],
        "token_mix": {
            "before": _token_mix(before_rows),
            "after": _token_mix(after_rows),
        },
        "interpretation": "exploratory_interval_estimate_not_an_independent_cycle_test",
    }


def exclusion_counts(cycles: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Count comparison-specific reasons that cycles could not vote."""
    counts = Counter(
        reason
        for reason in (
            capacity_cycle_exclusion_reason(row, require_known_plan=True)
            for row in cycles
        )
        if reason is not None
    )
    return dict(sorted(counts.items()))


def run_date(cycles: Sequence[Mapping[str, Any]], *, first: bool) -> str | None:
    """Return the first or last observed date across one contiguous plan run."""
    field = "first_observed_at" if first else "last_observed_at"
    values = [str(row.get(field) or "") for row in cycles]
    values = [value for value in values if value]
    if not values:
        return None
    return (min(values) if first else max(values))[:10]


def known_plan_types(cycles: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return normalized known plan labels observed in cycle history."""
    return sorted(
        {
            normalized
            for normalized in (normalize_plan_type(row.get("plan_type")) for row in cycles)
            if normalized not in INVALID_PLAN_TYPES
        }
    )


def no_transition_result(
    *,
    version: str,
    from_plan: str | None,
    to_plan: str | None,
    observed_plan_types: Sequence[str],
) -> dict[str, Any]:
    """Return the stable empty comparison shape."""
    return {
        "status": "no_transition",
        "model_version": version,
        "transition": {
            "selection_mode": "explicit" if from_plan and to_plan else "auto",
            "from_plan": normalize_plan_type(from_plan) if from_plan else None,
            "to_plan": normalize_plan_type(to_plan) if to_plan else None,
            "observed_plan_types": list(observed_plan_types),
        },
        "before": None,
        "after": None,
        "relative_meter_size": relative_meter_size([], []),
        "statistics": {
            "ratio_confidence_interval_95": None,
            "permutation": None,
            "cliffs_delta_after_vs_before": None,
        },
        "early_interval_estimate": unavailable_interval_estimate(
            "unavailable_without_transition"
        ),
        "exclusions": {},
        "caveats": [
            "No contiguous transition between two known weekly plan types was found."
        ],
    }


def unavailable_interval_estimate(status: str) -> dict[str, Any]:
    """Return the stable empty interval-estimate shape."""
    return {
        "status": status,
        "before_interval_count": 0,
        "after_interval_count": 0,
        "before_median_credits_per_percent": None,
        "after_median_credits_per_percent": None,
        "after_to_before_ratio": None,
        "after_as_percent_of_before": None,
        "token_mix": {"before": None, "after": None},
    }


def _plan_runs(cycles: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for cycle in cycles:
        plan_type = normalize_plan_type(cycle.get("plan_type"))
        if not runs or runs[-1]["plan_type"] != plan_type:
            runs.append({"plan_type": plan_type, "cycles": [cycle]})
        else:
            runs[-1]["cycles"].append(cycle)
    return runs


def _transition_candidates(
    runs: Sequence[dict[str, Any]],
    known_indices: Sequence[int],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left_index, right_index in zip(known_indices, known_indices[1:]):
        before_run = runs[left_index]
        after_run = runs[right_index]
        if before_run["plan_type"] == after_run["plan_type"]:
            continue
        boundary_runs = runs[left_index + 1 : right_index]
        candidates.append(
            {
                "before_plan": before_run["plan_type"],
                "after_plan": after_run["plan_type"],
                "before_cycles": before_run["cycles"],
                "after_cycles": after_run["cycles"],
                "boundary_cycles": [
                    cycle for run in boundary_runs for cycle in run["cycles"]
                ],
                "boundary_plan_types": [run["plan_type"] for run in boundary_runs],
            }
        )
    return candidates


def _interval_rows(
    connection: sqlite3.Connection,
    source_revision: str,
    cycle_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not cycle_ids:
        return []
    placeholders = ",".join("?" for _ in cycle_ids)
    return [
        dict(row)
        for row in connection.execute(
            "SELECT cycle_id,visible_percent_delta,estimated_credits,input_tokens,"
            "cached_input_tokens,uncached_input_tokens,output_tokens,"
            "reasoning_output_tokens,total_tokens,price_coverage "
            "FROM allowance_intervals WHERE source_revision = ? "
            "AND point_kind = 'positive' AND eligible_for_change_detection = 1 "
            f"AND cycle_id IN ({placeholders}) ORDER BY end_observed_at, interval_id",
            (source_revision, *cycle_ids),
        )
    ]


def _interval_values(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        movement = row.get("visible_percent_delta")
        credits = row.get("estimated_credits")
        if (
            isinstance(movement, int | float)
            and isinstance(credits, int | float)
            and float(movement) > 0
            and float(credits) > 0
        ):
            values.append(float(credits) / float(movement))
    return values


def _token_mix(rows: Sequence[Mapping[str, Any]]) -> dict[str, float] | None:
    cached = sum(float(row.get("cached_input_tokens") or 0) for row in rows)
    uncached = sum(float(row.get("uncached_input_tokens") or 0) for row in rows)
    output = sum(float(row.get("output_tokens") or 0) for row in rows)
    denominator = cached + uncached + output
    if denominator <= 0:
        return None
    return {
        "cached_input_share": _rounded(cached / denominator) or 0.0,
        "uncached_input_share": _rounded(uncached / denominator) or 0.0,
        "output_share": _rounded(output / denominator) or 0.0,
    }
