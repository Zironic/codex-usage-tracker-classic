"""Deterministic statistics for fixed weekly plan comparisons."""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from itertools import combinations
from math import comb
from statistics import median
from typing import Any

from codex_usage_tracker.allowance_intelligence.statistics import (
    _cliffs_delta,
    _rounded,
    _wilson_interval,
)

_EXACT_LABEL_ASSIGNMENT_LIMIT = 50_000
_STRONG_EFFECT_THRESHOLD = 0.474


def relative_meter_size(
    before_values: Sequence[float],
    after_values: Sequence[float],
) -> dict[str, float | None]:
    """Return the post-plan capacity as a ratio of pre-plan capacity."""
    if not before_values or not after_values:
        return _empty_relative_size()
    before = median(before_values)
    after = median(after_values)
    if before <= 0 or after <= 0:
        return _empty_relative_size()
    ratio = after / before
    return {
        "after_to_before_ratio": _rounded(ratio),
        "after_as_percent_of_before": _rounded(ratio * 100),
        "before_to_after_multiplier": _rounded(1 / ratio),
        "relative_change_percent": _rounded((ratio - 1) * 100),
    }


def comparison_statistics(
    before: list[float],
    after: list[float],
    *,
    semantic_key: str,
    bootstrap_samples: int,
    permutation_samples: int,
) -> dict[str, Any]:
    """Build fixed-label bootstrap, permutation, and effect-size evidence."""
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


def comparison_status(
    *,
    before_count: int,
    after_count: int,
    minimum: int,
    relative: Mapping[str, Any],
    statistics: Mapping[str, Any],
) -> str:
    """Classify whether the fixed comparison supports a larger or smaller meter."""
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


def quantile(values: Sequence[float], fraction: float) -> float:
    """Return a linearly interpolated sample quantile."""
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


def _empty_relative_size() -> dict[str, float | None]:
    return {
        "after_to_before_ratio": None,
        "after_as_percent_of_before": None,
        "before_to_after_multiplier": None,
        "relative_change_percent": None,
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
        "low": _rounded(quantile(ratios, 0.025)) if ratios else None,
        "high": _rounded(quantile(ratios, 0.975)) if ratios else None,
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
    if assignment_count <= _EXACT_LABEL_ASSIGNMENT_LIMIT:
        assignments = combinations(range(len(values)), before_size)
        return _evaluate_assignments(
            values,
            assignments,
            before_size=before_size,
            observed_ratio=observed_ratio,
            observed_statistic=observed_statistic,
            method="exact_fixed_label_permutation",
            seed=None,
            monte_carlo=False,
        )
    generator = random.Random(seed)  # nosec B311 - deterministic statistical sampling
    assignments = (
        tuple(sorted(generator.sample(range(len(values)), before_size)))
        for _ in range(samples)
    )
    return _evaluate_assignments(
        values,
        assignments,
        before_size=before_size,
        observed_ratio=observed_ratio,
        observed_statistic=observed_statistic,
        method="deterministic_monte_carlo_fixed_label",
        seed=seed,
        monte_carlo=True,
    )


def _evaluate_assignments(
    values: list[float],
    assignments: object,
    *,
    before_size: int,
    observed_ratio: float,
    observed_statistic: float,
    method: str,
    seed: int | None,
    monte_carlo: bool,
) -> dict[str, Any]:
    two_sided_extreme = 0
    smaller_extreme = 0
    evaluated = 0
    for before_indices in assignments:  # type: ignore[union-attr]
        before_set = set(before_indices)
        permuted_before = [values[index] for index in before_indices]
        permuted_after = [
            value for index, value in enumerate(values) if index not in before_set
        ]
        if len(permuted_before) != before_size:
            continue
        denominator = median(permuted_before)
        if denominator <= 0:
            continue
        ratio = median(permuted_after) / denominator
        statistic = abs(math.log(ratio)) if ratio > 0 else math.inf
        two_sided_extreme += statistic >= observed_statistic - 1e-12
        smaller_extreme += ratio <= observed_ratio + 1e-12
        evaluated += 1
    return _permutation_payload(
        method=method,
        seed=seed,
        monte_carlo=monte_carlo,
        two_sided_extreme=two_sided_extreme,
        smaller_extreme=smaller_extreme,
        evaluated=evaluated,
    )


def _permutation_payload(
    *,
    method: str,
    seed: int | None,
    monte_carlo: bool,
    two_sided_extreme: int,
    smaller_extreme: int,
    evaluated: int,
) -> dict[str, Any]:
    if evaluated <= 0:
        return {
            "method": method,
            "two_sided_p_value": None,
            "one_sided_p_value_after_smaller": None,
            "assignments_evaluated": 0,
            "seed": seed,
            "monte_carlo_uncertainty": None,
        }
    offset = 1 if monte_carlo else 0
    denominator = evaluated + offset
    low, high = _wilson_interval(two_sided_extreme, evaluated)
    return {
        "method": method,
        "two_sided_p_value": _rounded((two_sided_extreme + offset) / denominator),
        "one_sided_p_value_after_smaller": _rounded(
            (smaller_extreme + offset) / denominator
        ),
        "assignments_evaluated": evaluated,
        "seed": seed,
        "monte_carlo_uncertainty": (
            {
                "confidence_interval_95": {
                    "low": _rounded(low),
                    "high": _rounded(high),
                }
            }
            if monte_carlo
            else None
        ),
    }
