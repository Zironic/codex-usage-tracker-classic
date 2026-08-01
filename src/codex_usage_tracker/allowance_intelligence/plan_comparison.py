"""Fixed before/after comparison of weekly meter capacity across plan changes."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from codex_usage_tracker.allowance_intelligence.capacity_history import (
    eligible_capacity_cycles,
    load_capacity_cycles,
)
from codex_usage_tracker.allowance_intelligence.cycles import normalize_plan_type
from codex_usage_tracker.allowance_intelligence.plan_comparison_statistics import (
    comparison_statistics,
    comparison_status,
    relative_meter_size,
)
from codex_usage_tracker.allowance_intelligence.plan_comparison_support import (
    cohort_summary,
    early_interval_estimate,
    exclusion_counts,
    known_plan_types,
    no_transition_result,
    run_date,
    select_plan_transition,
    unavailable_interval_estimate,
)

PLAN_COMPARISON_VERSION = "fixed-plan-cycle-v1"
DEFAULT_MIN_CYCLES_PER_PLAN = 4
DEFAULT_BOOTSTRAP_SAMPLES = 4_999
DEFAULT_PERMUTATION_SAMPLES = 4_999


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
    selected = select_plan_transition(
        cycles,
        from_plan=from_plan,
        to_plan=to_plan,
    )
    if selected is None:
        return no_transition_result(
            version=PLAN_COMPARISON_VERSION,
            from_plan=from_plan,
            to_plan=to_plan,
            observed_plan_types=known_plan_types(cycles),
        )
    result = _compare_selected_transition(
        selected,
        semantic_key=_semantic_key(
            source_revision=source_revision,
            archive_scope=archive_scope,
            window_kind=window_kind,
            cohort_key=cohort_key,
            from_plan=from_plan,
            to_plan=to_plan,
            min_cycles_per_plan=min_cycles_per_plan,
            bootstrap_samples=bootstrap_samples,
            permutation_samples=permutation_samples,
        ),
        min_cycles_per_plan=min_cycles_per_plan,
        bootstrap_samples=bootstrap_samples,
        permutation_samples=permutation_samples,
    )
    before_cycles = _cycles(selected, "before_cycles")
    after_cycles = _cycles(selected, "after_cycles")
    result["early_interval_estimate"] = early_interval_estimate(
        connection,
        source_revision=source_revision,
        before_cycle_ids=[str(row.get("cycle_id")) for row in before_cycles],
        after_cycle_ids=[str(row.get("cycle_id")) for row in after_cycles],
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
    selected = select_plan_transition(
        cycles,
        from_plan=from_plan,
        to_plan=to_plan,
    )
    if selected is None:
        return no_transition_result(
            version=PLAN_COMPARISON_VERSION,
            from_plan=from_plan,
            to_plan=to_plan,
            observed_plan_types=known_plan_types(cycles),
        )
    result = _compare_selected_transition(
        selected,
        semantic_key=semantic_key,
        min_cycles_per_plan=min_cycles_per_plan,
        bootstrap_samples=bootstrap_samples,
        permutation_samples=permutation_samples,
    )
    result["early_interval_estimate"] = unavailable_interval_estimate(
        "unavailable_without_interval_store"
    )
    return result


def _compare_selected_transition(
    selected: Mapping[str, Any],
    *,
    semantic_key: str,
    min_cycles_per_plan: int,
    bootstrap_samples: int,
    permutation_samples: int,
) -> dict[str, Any]:
    before_cycles = _cycles(selected, "before_cycles")
    after_cycles = _cycles(selected, "after_cycles")
    before_eligible = eligible_capacity_cycles(
        before_cycles,
        require_known_plan=True,
    )
    after_eligible = eligible_capacity_cycles(
        after_cycles,
        require_known_plan=True,
    )
    before_values = [float(row["credits_per_percent"]) for row in before_eligible]
    after_values = [float(row["credits_per_percent"]) for row in after_eligible]
    relative = relative_meter_size(before_values, after_values)
    statistics = comparison_statistics(
        before_values,
        after_values,
        semantic_key=semantic_key,
        bootstrap_samples=bootstrap_samples,
        permutation_samples=permutation_samples,
    )
    boundary_cycles = _cycles(selected, "boundary_cycles")
    return {
        "status": comparison_status(
            before_count=len(before_values),
            after_count=len(after_values),
            minimum=min_cycles_per_plan,
            relative=relative,
            statistics=statistics,
        ),
        "model_version": PLAN_COMPARISON_VERSION,
        "transition": _transition_payload(
            selected,
            before_cycles=before_cycles,
            after_cycles=after_cycles,
            boundary_cycles=boundary_cycles,
        ),
        "before": cohort_summary(
            str(selected["before_plan"]),
            before_cycles,
            before_eligible,
        ),
        "after": cohort_summary(
            str(selected["after_plan"]),
            after_cycles,
            after_eligible,
        ),
        "relative_meter_size": relative,
        "statistics": statistics,
        "exclusions": {
            "before": exclusion_counts(before_cycles),
            "after": exclusion_counts(after_cycles),
            "boundary_cycle_count": len(boundary_cycles),
        },
        "caveats": _comparison_caveats(),
    }


def _transition_payload(
    selected: Mapping[str, Any],
    *,
    before_cycles: Sequence[Mapping[str, Any]],
    after_cycles: Sequence[Mapping[str, Any]],
    boundary_cycles: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    boundary_types = selected.get("boundary_plan_types")
    return {
        "selection_mode": selected["selection_mode"],
        "from_plan": selected["before_plan"],
        "to_plan": selected["after_plan"],
        "before_run_start_date": run_date(before_cycles, first=True),
        "before_run_end_date": run_date(before_cycles, first=False),
        "after_run_start_date": run_date(after_cycles, first=True),
        "after_run_end_date": run_date(after_cycles, first=False),
        "boundary_cycle_count": len(boundary_cycles),
        "boundary_plan_types": (
            list(boundary_types) if isinstance(boundary_types, list) else []
        ),
    }


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


def _semantic_key(
    *,
    source_revision: str,
    archive_scope: str,
    window_kind: str,
    cohort_key: str,
    from_plan: str | None,
    to_plan: str | None,
    min_cycles_per_plan: int,
    bootstrap_samples: int,
    permutation_samples: int,
) -> str:
    return ":".join(
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


def _cycles(selected: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = selected.get(key)
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _comparison_caveats() -> list[str]:
    return [
        "The comparison uses locally visible, model-normalized Codex usage rather than OpenAI's internal ledger.",
        "Completed reset cycles receive one vote each; mixed and unknown boundary cycles receive no vote.",
        "Published credit weights are assumed to be proportional to hidden weekly-meter accounting.",
        "Usage on other devices or surfaces can lower observed local credits per percentage point.",
    ]
