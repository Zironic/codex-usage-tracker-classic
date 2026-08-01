from __future__ import annotations

from datetime import datetime, timedelta, timezone

from codex_usage_tracker.allowance_intelligence.rate_change_detection import (
    detect_rate_change_from_evidence,
)

_PRIOR = datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_known_old_to_new_rates_recover_interval_bounded_change() -> None:
    result = detect_rate_change_from_evidence(
        _changed_evidence(),
        configured_effective_at="2026-08-01T00:00:00Z",
        configured_effective_at_precision="day",
        before_revision_id="old",
        after_revision_id="new",
        changed_models=["gpt-5.6-luna"],
        source_modified_at="2026-07-31T21:22:00Z",
        first_observed_at="2026-08-01T06:43:00Z",
    )

    assert result["status"] == "supported_change"
    assert result["confidence"] == "high"
    estimate = result["estimate"]
    assert estimate is not None
    assert estimate["effective_at_estimate"] == "2026-08-01T00:00:00Z"
    assert estimate["effective_at_lower_bound"] == "2026-07-31T23:00:00Z"
    assert estimate["effective_at_upper_bound"] == "2026-08-01T01:00:00Z"
    evidence = result["evidence"]
    assert evidence["before_interval_count"] == 6
    assert evidence["after_interval_count"] == 6
    assert evidence["fit_improvement_over_best_null"] == 1.0
    assert evidence["directional_advantage_over_reversed"] == 1.0
    assert evidence["after_to_before_capacity_ratio"] == 1.0


def test_old_rates_remaining_active_do_not_create_false_transition() -> None:
    evidence = []
    for index in range(-6, 6):
        start = _PRIOR + timedelta(hours=index)
        evidence.append(
            {
                "start_at": _iso(start),
                "end_at": _iso(start + timedelta(hours=1)),
                "movement": 1.0,
                "old_credits": 100.0,
                "new_credits": 50.0,
                "signal_share": 1.0,
                "plan_type": "prolite",
            }
        )

    result = detect_rate_change_from_evidence(
        evidence,
        configured_effective_at="2026-08-01T00:00:00Z",
        configured_effective_at_precision="day",
        before_revision_id="old",
        after_revision_id="new",
        changed_models=["gpt-5.6-luna"],
    )

    assert result["status"] == "no_supported_change"
    assert result["confidence"] == "low"
    assert result["evidence"]["old_only_loss"] == 0.0
    assert result["evidence"]["fit_improvement_over_best_null"] == 0.0


def test_too_few_informative_intervals_are_reported_without_estimate() -> None:
    result = detect_rate_change_from_evidence(
        _changed_evidence()[:5],
        configured_effective_at="2026-08-01T00:00:00Z",
        configured_effective_at_precision="day",
        before_revision_id="old",
        after_revision_id="new",
        changed_models=["gpt-5.6-luna"],
    )

    assert result["status"] == "insufficient_evidence"
    assert result["confidence"] == "none"
    assert result["estimate"] is None
    assert result["reason"] == "too_few_informative_weekly_intervals"


def test_nearest_known_plan_isolated_from_subscription_transition() -> None:
    evidence = _changed_evidence()
    evidence.extend(
        {
            "start_at": _iso(_PRIOR - timedelta(days=3, hours=index)),
            "end_at": _iso(_PRIOR - timedelta(days=3, hours=index - 1)),
            "movement": 1.0,
            "old_credits": 400.0,
            "new_credits": 20.0,
            "signal_share": 1.0,
            "plan_type": "plus",
        }
        for index in range(6)
    )

    result = detect_rate_change_from_evidence(
        evidence,
        configured_effective_at="2026-08-01T00:00:00Z",
        configured_effective_at_precision="day",
        before_revision_id="old",
        after_revision_id="new",
        changed_models=["gpt-5.6-luna"],
    )

    assert result["status"] == "supported_change"
    assert result["evidence"]["informative_interval_count"] == 12


def _changed_evidence() -> list[dict[str, object]]:
    evidence: list[dict[str, object]] = []
    for index in range(-6, 0):
        start = _PRIOR + timedelta(hours=index)
        evidence.append(
            {
                "start_at": _iso(start),
                "end_at": _iso(start + timedelta(hours=1)),
                "movement": 1.0,
                "old_credits": 100.0,
                "new_credits": 50.0,
                "signal_share": 1.0,
                "plan_type": "prolite",
            }
        )
    for index in range(0, 6):
        start = _PRIOR + timedelta(hours=index)
        evidence.append(
            {
                "start_at": _iso(start),
                "end_at": _iso(start + timedelta(hours=1)),
                "movement": 1.0,
                "old_credits": 200.0,
                "new_credits": 100.0,
                "signal_share": 1.0,
                "plan_type": "prolite",
            }
        )
    return evidence


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
