from __future__ import annotations

from typing import Any

import pytest

from codex_usage_tracker.allowance_intelligence.plan_comparison import (
    compare_plan_capacity_cycles,
)


def _cycle(
    index: int,
    plan: str,
    capacity: float | None,
    *,
    status: str = "completed",
    quality: str = "high",
    coverage: float = 1.0,
    conflicts: int = 0,
) -> dict[str, Any]:
    day = index + 1
    return {
        "cycle_id": f"cycle-{index}",
        "plan_type": plan,
        "first_observed_at": f"2026-07-{day:02d}T00:00:00Z",
        "last_observed_at": f"2026-07-{day:02d}T23:00:00Z",
        "credits_per_percent": capacity,
        "status": status,
        "quality_grade": quality,
        "price_coverage": coverage,
        "conflict_count": conflicts,
    }


def test_plan_comparison_recovers_two_to_one_meter_change() -> None:
    before = [300.0, 290.0, 310.0, 300.0, 305.0]
    after = [150.0, 145.0, 155.0, 150.0, 152.0]
    cycles = [
        *[_cycle(index, "pro", value) for index, value in enumerate(before)],
        *[
            _cycle(index + len(before), "prolite", value)
            for index, value in enumerate(after)
        ],
    ]

    result = compare_plan_capacity_cycles(
        cycles,
        semantic_key="two-to-one",
        bootstrap_samples=499,
        permutation_samples=499,
    )

    assert result["status"] == "supported_smaller"
    assert result["transition"]["from_plan"] == "pro"
    assert result["transition"]["to_plan"] == "prolite"
    assert result["relative_meter_size"]["after_to_before_ratio"] == pytest.approx(0.5, abs=0.01)
    assert result["relative_meter_size"]["before_to_after_multiplier"] == pytest.approx(2.0, abs=0.05)
    assert result["statistics"]["cliffs_delta_after_vs_before"] == -1.0


def test_mixed_transition_cycle_is_excluded_from_both_cohorts() -> None:
    cycles = [
        *[_cycle(index, "pro", 300.0 + index) for index in range(4)],
        _cycle(4, "mixed", 220.0),
        *[_cycle(index, "prolite", 150.0 + index) for index in range(5, 9)],
    ]

    result = compare_plan_capacity_cycles(
        cycles,
        semantic_key="mixed-boundary",
        bootstrap_samples=199,
        permutation_samples=199,
    )

    assert result["transition"]["boundary_cycle_count"] == 1
    assert result["transition"]["boundary_plan_types"] == ["mixed"]
    assert result["before"]["observed_cycle_count"] == 4
    assert result["after"]["observed_cycle_count"] == 4


def test_automatic_comparison_uses_latest_contiguous_transition() -> None:
    cycles = [
        *[_cycle(index, "pro", 300.0) for index in range(4)],
        *[_cycle(index, "prolite", 150.0) for index in range(4, 8)],
        *[_cycle(index, "pro", 290.0) for index in range(8, 12)],
    ]

    automatic = compare_plan_capacity_cycles(
        cycles,
        semantic_key="latest",
        bootstrap_samples=199,
        permutation_samples=199,
    )
    explicit = compare_plan_capacity_cycles(
        cycles,
        semantic_key="explicit",
        from_plan="pro",
        to_plan="prolite",
        bootstrap_samples=199,
        permutation_samples=199,
    )

    assert automatic["transition"]["from_plan"] == "prolite"
    assert automatic["transition"]["to_plan"] == "pro"
    assert explicit["transition"]["from_plan"] == "pro"
    assert explicit["transition"]["to_plan"] == "prolite"


def test_quality_failures_do_not_vote_in_primary_comparison() -> None:
    cycles = [
        *[_cycle(index, "pro", 300.0 + index) for index in range(4)],
        _cycle(4, "pro", 400.0, status="open"),
        _cycle(5, "pro", 400.0, coverage=0.8),
        *[_cycle(index, "prolite", 150.0 + index) for index in range(6, 10)],
        _cycle(10, "prolite", 10.0, conflicts=1),
        _cycle(11, "prolite", None),
    ]

    result = compare_plan_capacity_cycles(
        cycles,
        semantic_key="quality",
        bootstrap_samples=199,
        permutation_samples=199,
    )

    assert result["before"]["eligible_cycle_count"] == 4
    assert result["after"]["eligible_cycle_count"] == 4
    assert result["exclusions"]["before"] == {
        "low_pricing_coverage": 1,
        "open_cycle": 1,
    }
    assert result["exclusions"]["after"] == {
        "conflict": 1,
        "missing_capacity": 1,
    }


def test_insufficient_post_switch_history_remains_exploratory() -> None:
    cycles = [
        *[_cycle(index, "pro", 300.0 + index) for index in range(5)],
        _cycle(5, "prolite", 150.0),
    ]

    result = compare_plan_capacity_cycles(
        cycles,
        semantic_key="early",
        bootstrap_samples=199,
        permutation_samples=199,
    )

    assert result["status"] == "insufficient_completed_cycles"
    assert result["relative_meter_size"]["after_to_before_ratio"] is not None


def test_no_plan_transition_returns_no_transition() -> None:
    cycles = [_cycle(index, "pro", 300.0 + index) for index in range(8)]

    result = compare_plan_capacity_cycles(
        cycles,
        semantic_key="one-plan",
        bootstrap_samples=199,
        permutation_samples=199,
    )

    assert result["status"] == "no_transition"
    assert result["transition"]["observed_plan_types"] == ["pro"]


def test_statistical_sampling_is_deterministic() -> None:
    cycles = [
        *[_cycle(index, "pro", 300.0 + index) for index in range(5)],
        *[_cycle(index, "prolite", 150.0 + index) for index in range(5, 10)],
    ]

    first = compare_plan_capacity_cycles(
        cycles,
        semantic_key="deterministic",
        bootstrap_samples=499,
        permutation_samples=499,
    )
    second = compare_plan_capacity_cycles(
        cycles,
        semantic_key="deterministic",
        bootstrap_samples=499,
        permutation_samples=499,
    )

    assert first == second


def test_plan_arguments_must_be_paired() -> None:
    with pytest.raises(ValueError, match="provided together"):
        compare_plan_capacity_cycles(
            [],
            semantic_key="invalid",
            from_plan="pro",
            bootstrap_samples=199,
            permutation_samples=199,
        )
