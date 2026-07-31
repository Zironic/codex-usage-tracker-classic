"""Fixed before/after comparison of weekly meter capacity across plan changes."""

from __future__ import annotations

import hashlib
import math
import random
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import combinations
from math import comb
from statistics import median
from typing import Any

from codex_usage_tracker.allowance_intelligence.capacity_history import (
    capacity_cycle_exclusion_reason,
    eligible_capacity_cycles,
    load_capacity_cycles,
)
from codex_usage_tracker.allowance_intelligence.cycles import normalize_plan_type
from codex_usage_tracker.allowance_intelligence.statistics import (
    _cliffs_delta,
    _rounded,
    _wilson_interval,
)

PLAN_COMPARISON_VERSION = "fixed-plan-cycle-v1"
DEFAULT_MIN_CYCLES_PER_PLAN = 4
DEFAULT_BOOTSTRAP_SAMPLES = 4_999
DEFAULT_PERMUTATION_SAMPLES = 4_999
INVALID_PLAN_TYPES = frozenset({"", "unknown", "mixed"})
_EXACT_LABEL_ASSIGNMENT_LIMIT = 50_000
_STRONG_EFFECT_THRESHOLD = 0.474


def build_plan_meter_comparison(
    connection: sqlite3.Connection,
    *,
    source_revision: str,
    archive_scope: str = "active",
    window_kind: str = "weekly",
    cohort_key: str = "codex",
    from_plan: str | None = None,
    to_plan: str | None = None,
    min_cycles_per_plan: int = DEFAULT_MIN_CYCLES_PER_PLAN,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    permutation_samples: int = DEFAULT_PERMUTATION_SAMPLES,
) -> dict[str, Any]:
    """Compare contiguous completed-cycle capacity on each side of a plan change."""

    _validate_arguments(
        from_plan=from_plan,
        to_plan=to_plan,
        min_cycles_per_plan=min_cycles_per_plan,
        bootstrap_samples=bootstrap_samples,
        permutation_samples=permutation_samples,
    )
    cycles = load_capacity_cycles(
        connection,
        source_revision=source_revision,
        archive_scope=archive_scope,
        window_kind=window_kind,
        cohort_key=cohort_key,
    )
    selected = _select_plan_transition(
        cycles,
        from_plan=from_plan,
        to_plan=to_plan,
    )
    semantic_key = ":".join(
        (
            source_revision,
            PLAN_COMPARISON_VERSION,
            archive_scope,
            window_kind,
            cohort_key,
            normalize_plan_type(from_plan) if from_plan else "auto",
            normalize_plan_type(to_plan) if to_plan else "auto",
            str(min_cycles_per_plan),
            str(bootstrap_samples),
            str(permutation_samples),
        )
    )
    if selected is None:
        return _no_transition_result(
            from_plan=from_plan,
            to_plan=to_plan,
            observed_plan_types=_known_plan_types(cycles),
        )
    result = _compare_selected_transition(
        selected,
        semantic_key=semantic_key,
        min_cycles_per_plan=min_cycles_per_plan,
        bootstrap_samples=bootstrap_samples,
        permutation_samples=permutation_samples,
    )
    result["early_interval_estimate"] = _early_interval_estimate(
        connection,
        source_revision=source_revision,
        before_cycle_ids=[str(row.get("cycle_id")) for row in selected["before_cycles"]],
        after_cycle_ids=[str(row.get("cycle_id")) for row in selected["after_cycles"]],
    )
    return result


def compare_plan_capacity_cycles(
    cycles: Sequence[Mapping[str, Any]],
    *,
    semantic_key: str,
    from_plan: str | None = None,
    to_plan: str | None = None,
    min_cycles_per_plan: int = DEFAULT_MIN_CYCLES_PER_PLAN,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    permutation_samples: int = DEFAULT_PERMUTATION_SAMPLES,
) -> dict[str, Any]:
    """Pure comparison entry point used by focused tests and offline analysis."""

    _validate_arguments(
        from_plan=from_plan,
        to_plan=to_plan,
        min_cycles_per_plan=min_cycles_per_plan,
        bootstrap_samples=bootstrap_samples,
        permutation_samples=permutation_samples,
    )
    selected = _select_plan_transition(
        cycles,
        from_plan=from_plan,
        to_plan=to_plan,
    )
    if selected is None:
        return _no_transition_result(
            from_plan=from_plan,
            to_plan=to_plan,
            observed_plan_types=_known_plan_types(cycles),
        )
    result = _compare_selected_transition(
        selected,
        semantic_key=semantic_key,
        min_cycles_per_plan=min_cycles_per_plan,
        bootstrap_samples=bootstrap_samples,
        permutation_samples=permutation_samples,
    )
    result["early_interval_estimate"] = {
        "status": "unavailable_without_interval_store",
        "before_interval_count": 0,
        "after_interval_count": 0,
        "before_median_credits_per_percent": None,
        "after_median_credits_per_percent": None,
        "after_to_before_ratio": None,
        "token_mix": {"before": None, "after": None},
    }
    return result


def _validate_arguments(
    *,
    from_plan: str | None,
    to_plan: str | None,
    min_cycles_per_plan: int,
    bootstrap_samples: int,
    permutation_samples: int,
) -> None:
    if bool(from_plan) != bool(to_plan):
        raise ValueError("from_plan and to_plan must be provided together")
    if from_plan and normalize_plan_type(from_plan) == normalize_plan_type(to_plan):
        raise ValueError("from_plan and to_plan must differ")
    if min_cycles_per_plan < 2:
        raise ValueError("min_cycles_per_plan must be at least 2")
    if bootstrap_samples < 99:
        raise ValueError("bootstrap_samples must be at least 99")
    if permutation_samples < 99:
        raise ValueError("permutation_samples must be at least 99")


def _select_plan_transition(
    cycles: Sequence[Mapping[str, Any]],
    *,
    from_plan: str | None,
    to_plan: str | None,
) -> dict[str, Any] | None:
    ordered = sorted(
        (dict(row) for row in cycles),
        key=lambda row: (
            str(row.get("first_observed_at") or row.get("last_observed_at") or ""),
            str(row.get("last_observed_at") or ""),
            str(row.get("cycle_id") or ""),
        ),
    )
    runs: list[dict[str, Any]] = []
    for cycle in ordered:
        plan_type = normalize_plan_type(cycle.get("plan_type"))
        if not runs or runs[-1]["plan_type"] != plan_type:
            runs.append({"plan_type": plan_type, "cycles": [cycle]})
        else:
            runs[-1]["cycles"].append(cycle)
    known_indices = [
        index for index, run in enumerate(runs) if run["plan_type"] not in INVALID_PLAN_TYPES
    ]
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


def _compare_selected_transition(
    selected: Mapping[str, Any],
    *,
    semantic_key: str,
    min_cycles_per_plan: int,
    bootstrap_samples: int,
    permutation_samples: int,
) -> dict[str, Any]:
    before_cycles = [dict(row) for row in selected["before_cycles"]]
    after_cycles = [dict(row) for row in selected["after_cycles"]]
    before_eligible = eligible_capacity_cycles(before_cycles)
    after_eligible = eligible_capacity_cycles(after_cycles)
    before_values = [float(row["credits_per_percent"]) for row in before_eligible]
    after_values = [float(row["credits_per_percent"]) for row in after_eligible]
    before_summary = _cohort_summary(
        str(selected["before_plan"]), before_cycles, before_eligible
    )
    after_summary = _cohort_summary(
        str(selected["after_plan"]), after_cycles, after_eligible
    )
    relative = _relative_meter_size(before_values, after_values)
    statistics = _comparison_statistics(
        before_values,
        after_values,
        semantic_key=semantic_key,
        bootstrap_samples=bootstrap_samples,
        permutation_samples=permutation_samples,
    )
    status = _comparison_status(
        before_count=len(before_values),
        after_count=len(after_values),
        minimum=min_cycles_per_plan,
        relative=relative,
        statistics=statistics,
    )
    boundary_cycles = [dict(row) for row in selected["boundary_cycles"]]
    return {
        "status": status,
        "model_version": PLAN_COMPARISON_VERSION,
        "transition": {
            "selection_mode": selected["selection_mode"],
            "from_plan": selected["before_plan"],
            "to_plan": selected["after_plan"],
            "before_run_start_date": _run_date(before_cycles, first=True),
            "before_run_end_date": _run_date(before_cycles, first=False),
            "after_run_start_date": _run_date(after_cycles, first=True),
            "after_run_end_date": _run_date(after_cycles, first=False),
            "boundary_cycle_count": len(boundary_cycles),
            "boundary_plan_types": list(selected["boundary_plan_types"]),
        },
        "before": before_summary,
        "after": after_summary,
        "relative_meter_size": relative,
        "statistics": statistics,
        "exclusions": {
            "before": _exclusion_counts(before_cycles),
            "after": _exclusion_counts(after_cycles),
            "boundary_cycle_count": len(boundary_cycles),
        },
        "caveats": [
            "The comparison uses locally visible, model-normalized Codex usage rather than OpenAI's internal ledger.",
            "Completed reset cycles receive one vote each; mixed and unknown boundary cycles receive no vote.",
            "Published credit weights are assumed to be proportional to hidden weekly-meter accounting.",
            "Usage on other devices or surfaces can lower observed local credits per percentage point.",
        ],
    }


def _cohort_summary(
    plan_type: str,
    observed: Sequence[Mapping[str, Any]],
    eligible: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
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
        "start_date": _run_date(observed, first=True),
        "end_date": _run_date(observed, first=False),
        "median_credits_per_percent": _rounded(capacity),
        "estimated_full_meter_credits": _rounded(capacity * 100) if capacity else None,
        "q1_credits_per_percent": _rounded(_quantile(values, 0.25)) if values else None,
        "q3_credits_per_percent": _rounded(_quantile(values, 0.75)) if values else None,
        "minimum_credits_per_percent": _rounded(min(values)) if values else None,
        "maximum_credits_per_percent": _rounded(max(values)) if values else None,
        "median_price_coverage": (
            _rounded(median(coverage_values)) if coverage_values else None
        ),
    }


def _relative_meter_size(
    before_values: Sequence[float], after_values: Sequence[float]
) -> dict[str, float | None]:
    if not before_values or not after_values:
        return {
            "after_to_before_ratio": None,
            "after_as_percent_of_before": None,
            "before_to_after_multiplier": None,
            "relative_change_percent": None,
        }
    before = median(before_values)
    after = median(after_values)
    if before <= 0 or after <= 0:
        return {
            "after_to_before_ratio": None,
            "after_as_percent_of_before": None,
            "before_to_after_multiplier": None,
            "relative_change_percent": None,
        }
    ratio = after / before
    return {
        "after_to_before_ratio": _rounded(ratio),
        "after_as_percent_of_before": _rounded(ratio * 100),
        "before_to_after_multiplier": _rounded(1 / ratio),
        "relative_change_percent": _rounded((ratio - 1) * 100),
    }


def _comparison_statistics(
    before: list[float],
    after: list[float],
    *,
    semantic_key: str,
    bootstrap_samples: int,
    permutation_samples: int,
) -> dict[str, Any]:
    if not before or not after:
        return {
            "ratio_confidence_interval_95": None,
            "permutation": None,
            "cliffs_delta_after_vs_before": None,
        }
    seed = int.from_bytes(hashlib.sha256(semantic_key.encode()).digest()[:8], "big")
    confidence = _bootstrap_ratio_interval(
        before,
        after,
        samples=bootstrap_samples,
        seed=seed,
    )
    permutation = _fixed_label_permutation(
        before,
        after,
        samples=permutation_samples,
        seed=seed ^ 0x9E3779B97F4A7C15,
    )
    return {
        "ratio_confidence_interval_95": confidence,
        "permutation": permutation,
        "cliffs_delta_after_vs_before": _rounded(_cliffs_delta(before, after)),
    }


def _bootstrap_ratio_interval(
    before: list[float],
    after: list[float],
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    generator = random.Random(seed)  # nosec B311 - deterministic statistical sampling
    ratios: list[float] = []
    for _ in range(samples):
        before_sample = [generator.choice(before) for _ in before]
        after_sample = [generator.choice(after) for _ in after]
        denominator = median(before_sample)
        if denominator > 0:
            ratios.append(median(after_sample) / denominator)
    return {
        "method": "deterministic_cycle_bootstrap",
        "low": _rounded(_quantile(ratios, 0.025)) if ratios else None,
        "high": _rounded(_quantile(ratios, 0.975)) if ratios else None,
        "samples": len(ratios),
        "seed": seed,
    }


def _fixed_label_permutation(
    before: list[float],
    after: list[float],
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    values = before + after
    before_size = len(before)
    observed_ratio = median(after) / median(before)
    observed_statistic = abs(math.log(observed_ratio))
    assignment_count = comb(len(values), before_size)
    two_sided_extreme = 0
    smaller_extreme = 0
    evaluated = 0
    if assignment_count <= _EXACT_LABEL_ASSIGNMENT_LIMIT:
        assignments = combinations(range(len(values)), before_size)
        method = "exact_fixed_label_permutation"
        adjusted = False
    else:
        generator = random.Random(seed)  # nosec B311 - deterministic statistical sampling
        assignments = (
            tuple(sorted(generator.sample(range(len(values)), before_size)))
            for _ in range(samples)
        )
        method = "deterministic_monte_carlo_fixed_label"
        adjusted = True
    for before_indices in assignments:
        before_set = set(before_indices)
        permuted_before = [values[index] for index in before_indices]
        permuted_after = [
            value for index, value in enumerate(values) if index not in before_set
        ]
        denominator = median(permuted_before)
        if denominator <= 0:
            continue
        ratio = median(permuted_after) / denominator
        statistic = abs(math.log(ratio)) if ratio > 0 else math.inf
        two_sided_extreme += statistic >= observed_statistic - 1e-12
        smaller_extreme += ratio <= observed_ratio + 1e-12
        evaluated += 1
    if not evaluated:
        return {
            "method": method,
            "two_sided_p_value": None,
            "one_sided_p_value_after_smaller": None,
            "assignments_evaluated": 0,
            "seed": None if not adjusted else seed,
            "monte_carlo_uncertainty": None,
        }
    denominator = evaluated + 1 if adjusted else evaluated
    offset = 1 if adjusted else 0
    low, high = _wilson_interval(two_sided_extreme, evaluated)
    return {
        "method": method,
        "two_sided_p_value": _rounded((two_sided_extreme + offset) / denominator),
        "one_sided_p_value_after_smaller": _rounded(
            (smaller_extreme + offset) / denominator
        ),
        "assignments_evaluated": evaluated,
        "seed": seed if adjusted else None,
        "monte_carlo_uncertainty": (
            {
                "confidence_interval_95": {
                    "low": _rounded(low),
                    "high": _rounded(high),
                }
            }
            if adjusted
            else None
        ),
    }


def _comparison_status(
    *,
    before_count: int,
    after_count: int,
    minimum: int,
    relative: Mapping[str, Any],
    statistics: Mapping[str, Any],
) -> str:
    ratio = relative.get("after_to_before_ratio")
    if not isinstance(ratio, int | float):
        return "descriptive_only"
    if before_count < minimum or after_count < minimum:
        return "insufficient_completed_cycles"
    interval = statistics.get("ratio_confidence_interval_95")
    permutation = statistics.get("permutation")
    cliffs_delta = statistics.get("cliffs_delta_after_vs_before")
    if not isinstance(interval, Mapping) or not isinstance(permutation, Mapping):
        return "descriptive_only"
    low = interval.get("low")
    high = interval.get("high")
    p_value = permutation.get("two_sided_p_value")
    supported = (
        isinstance(low, int | float)
        and isinstance(high, int | float)
        and isinstance(p_value, int | float)
        and isinstance(cliffs_delta, int | float)
        and float(p_value) < 0.05
        and abs(float(cliffs_delta)) >= _STRONG_EFFECT_THRESHOLD
    )
    if supported and float(ratio) < 1 and float(high) < 1:
        return "supported_smaller"
    if supported and float(ratio) > 1 and float(low) > 1:
        return "supported_larger"
    return "no_supported_difference"


def _early_interval_estimate(
    connection: sqlite3.Connection,
    *,
    source_revision: str,
    before_cycle_ids: Sequence[str],
    after_cycle_ids: Sequence[str],
) -> dict[str, Any]:
    before_rows = _interval_rows(connection, source_revision, before_cycle_ids)
    after_rows = _interval_rows(connection, source_revision, after_cycle_ids)
    before_values = _interval_values(before_rows)
    after_values = _interval_values(after_rows)
    relative = _relative_meter_size(before_values, after_values)
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


def _exclusion_counts(cycles: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(
        reason
        for reason in (capacity_cycle_exclusion_reason(row) for row in cycles)
        if reason is not None
    )
    return dict(sorted(counts.items()))


def _run_date(cycles: Sequence[Mapping[str, Any]], *, first: bool) -> str | None:
    values = [
        str(row.get("first_observed_at" if first else "last_observed_at") or "")
        for row in cycles
    ]
    values = [value for value in values if value]
    if not values:
        return None
    return (min(values) if first else max(values))[:10]


def _known_plan_types(cycles: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            normalized
            for normalized in (normalize_plan_type(row.get("plan_type")) for row in cycles)
            if normalized not in INVALID_PLAN_TYPES
        }
    )


def _no_transition_result(
    *,
    from_plan: str | None,
    to_plan: str | None,
    observed_plan_types: Sequence[str],
) -> dict[str, Any]:
    return {
        "status": "no_transition",
        "model_version": PLAN_COMPARISON_VERSION,
        "transition": {
            "selection_mode": "explicit" if from_plan and to_plan else "auto",
            "from_plan": normalize_plan_type(from_plan) if from_plan else None,
            "to_plan": normalize_plan_type(to_plan) if to_plan else None,
            "observed_plan_types": list(observed_plan_types),
        },
        "before": None,
        "after": None,
        "relative_meter_size": {
            "after_to_before_ratio": None,
            "after_as_percent_of_before": None,
            "before_to_after_multiplier": None,
            "relative_change_percent": None,
        },
        "statistics": {
            "ratio_confidence_interval_95": None,
            "permutation": None,
            "cliffs_delta_after_vs_before": None,
        },
        "early_interval_estimate": {
            "status": "unavailable_without_transition",
            "before_interval_count": 0,
            "after_interval_count": 0,
            "before_median_credits_per_percent": None,
            "after_median_credits_per_percent": None,
            "after_to_before_ratio": None,
            "token_mix": {"before": None, "after": None},
        },
        "exclusions": {},
        "caveats": [
            "No contiguous transition between two known weekly plan types was found."
        ],
    }


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("quantile requires at least one value")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)
