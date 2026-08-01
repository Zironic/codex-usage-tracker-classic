"""Interval-level inference for timestamped Codex credit-rate changes."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from codex_usage_tracker.pricing.allowance_config import UsageAllowanceConfig
from codex_usage_tracker.pricing.allowance_rate_card import normalize_model, number_value
from codex_usage_tracker.pricing.allowance_rate_history import CreditRateRevision
from codex_usage_tracker.pricing.allowance_usage import estimate_standard_usage_credits
from codex_usage_tracker.pricing.fast_tier import credit_multiplier_for_row

RATE_CHANGE_DETECTOR_VERSION = "known-rate-hypothesis-interval-v1"
_MIN_INTERVALS_PER_SIDE = 3
_PRIMARY_PRIOR_RADIUS = timedelta(hours=72)
_ANALYSIS_RADIUS = timedelta(days=7)
_MIN_HYPOTHESIS_DELTA = 0.02
_MIN_SUPPORTED_IMPROVEMENT = 0.20
_MIN_DIRECTIONAL_ADVANTAGE = 0.10


@dataclass(frozen=True)
class RateHypothesisInterval:
    """One weekly meter interval priced under adjacent rate revisions."""

    start_at: datetime
    end_at: datetime
    movement: float
    old_credits: float
    new_credits: float
    signal_share: float
    plan_type: str


def infer_timestamped_rate_change(
    connection: sqlite3.Connection,
    *,
    source_revision: str,
    archive_scope: str,
    window_kind: str,
    cohort_key: str,
    config: UsageAllowanceConfig,
) -> dict[str, Any]:
    """Infer the latest official rate revision boundary from local meter evidence."""

    if archive_scope not in {"active", "all"}:
        raise ValueError("archive_scope must be active or all")
    if window_kind != "weekly":
        return _unavailable("unsupported_window_kind")
    pair = _latest_changed_revision_pair(config)
    if pair is None:
        return _unavailable("no_adjacent_changed_rate_revisions")
    before, after, changed_models = pair
    if after.effective_at_text is None:
        return _unavailable("latest_changed_revision_has_no_timestamp")
    evidence = _load_rate_hypothesis_intervals(
        connection,
        source_revision=source_revision,
        archive_scope=archive_scope,
        window_kind=window_kind,
        cohort_key=cohort_key,
        config=config,
        before=before,
        after=after,
        changed_models=changed_models,
    )
    return detect_rate_change_from_evidence(
        evidence,
        configured_effective_at=after.effective_at_text,
        configured_effective_at_precision=after.effective_at_precision,
        before_revision_id=before.revision_id,
        after_revision_id=after.revision_id,
        changed_models=changed_models,
        source_modified_at=_optional_text(after.source.get("source_modified_at")),
        first_observed_at=_optional_text(after.source.get("fetched_at")),
    )


def detect_rate_change_from_evidence(
    evidence: Sequence[RateHypothesisInterval | Mapping[str, object]],
    *,
    configured_effective_at: str,
    configured_effective_at_precision: str,
    before_revision_id: str,
    after_revision_id: str,
    changed_models: Sequence[str],
    source_modified_at: str | None = None,
    first_observed_at: str | None = None,
) -> dict[str, Any]:
    """Compare old→new, old-only, new-only, and reversed rate hypotheses."""

    prior = _parse_time(configured_effective_at)
    normalized = sorted(
        (item for item in (_coerce_interval(row) for row in evidence) if item is not None),
        key=lambda row: (row.end_at, row.start_at),
    )
    normalized = _select_plan_segment(normalized, prior)
    normalized = [
        row
        for row in normalized
        if abs(row.end_at - prior) <= _ANALYSIS_RADIUS
        and _relative_delta(row.old_credits, row.new_credits) >= _MIN_HYPOTHESIS_DELTA
    ]
    common = {
        "detector_version": RATE_CHANGE_DETECTOR_VERSION,
        "revision": {
            "before_revision_id": before_revision_id,
            "after_revision_id": after_revision_id,
            "changed_models": list(changed_models),
            "configured_effective_at": configured_effective_at,
            "configured_effective_at_precision": configured_effective_at_precision,
            "source_modified_at": source_modified_at,
            "first_observed_at": first_observed_at,
        },
        "caveats": _caveats(configured_effective_at_precision),
    }
    if len(normalized) < 2 * _MIN_INTERVALS_PER_SIDE:
        return {
            **common,
            "status": "insufficient_evidence",
            "confidence": "none",
            "reason": "too_few_informative_weekly_intervals",
            "estimate": None,
            "evidence": {
                "informative_interval_count": len(normalized),
                "minimum_intervals_per_side": _MIN_INTERVALS_PER_SIDE,
            },
        }

    candidates = _candidate_fits(normalized, prior)
    if not candidates:
        return {
            **common,
            "status": "insufficient_evidence",
            "confidence": "none",
            "reason": "no_candidate_boundary_with_enough_evidence_on_both_sides",
            "estimate": None,
            "evidence": {
                "informative_interval_count": len(normalized),
                "minimum_intervals_per_side": _MIN_INTERVALS_PER_SIDE,
            },
        }

    old_only_loss = _fit_loss(normalized, "old")
    new_only_loss = _fit_loss(normalized, "new")
    null_loss = min(old_only_loss, new_only_loss)
    best = min(candidates, key=lambda candidate: candidate["forward_loss"])
    improvement = _relative_improvement(null_loss, best["forward_loss"])
    directional_advantage = _relative_improvement(
        best["reverse_loss"], best["forward_loss"]
    )
    capacity_ratio = _capacity_ratio(normalized, int(best["split_index"]))
    supported = (
        improvement >= _MIN_SUPPORTED_IMPROVEMENT
        and directional_advantage >= _MIN_DIRECTIONAL_ADVANTAGE
        and 0.80 <= capacity_ratio <= 1.25
    )
    plausible = _plausible_candidates(
        candidates,
        null_loss=null_loss,
        best_loss=float(best["forward_loss"]),
    )
    lower = min(candidate["lower_bound"] for candidate in plausible)
    upper = max(candidate["upper_bound"] for candidate in plausible)
    estimate = best["estimate"]
    confidence = _confidence(
        supported=supported,
        improvement=improvement,
        directional_advantage=directional_advantage,
        before_count=int(best["split_index"]),
        after_count=len(normalized) - int(best["split_index"]),
        bound_width=upper - lower,
        capacity_ratio=capacity_ratio,
    )
    median_signal_share = median(row.signal_share for row in normalized)
    configured_distance = (estimate - prior).total_seconds()
    return {
        **common,
        "status": "supported_change" if supported else "no_supported_change",
        "confidence": confidence,
        "reason": None if supported else "known_rate_hypothesis_did_not_clear_support_gates",
        "estimate": {
            "effective_at_estimate": _iso(estimate),
            "effective_at_lower_bound": _iso(lower),
            "effective_at_upper_bound": _iso(upper),
            "precision": "interval_bounded",
            "configured_distance_seconds": round(configured_distance),
        },
        "evidence": {
            "informative_interval_count": len(normalized),
            "before_interval_count": int(best["split_index"]),
            "after_interval_count": len(normalized) - int(best["split_index"]),
            "candidate_count": len(candidates),
            "plausible_candidate_count": len(plausible),
            "median_changed_model_token_share": round(median_signal_share, 6),
            "old_only_loss": round(old_only_loss, 6),
            "new_only_loss": round(new_only_loss, 6),
            "old_to_new_loss": round(float(best["forward_loss"]), 6),
            "new_to_old_loss": round(float(best["reverse_loss"]), 6),
            "fit_improvement_over_best_null": round(improvement, 6),
            "directional_advantage_over_reversed": round(directional_advantage, 6),
            "after_to_before_capacity_ratio": round(capacity_ratio, 6),
            "support_thresholds": {
                "minimum_fit_improvement": _MIN_SUPPORTED_IMPROVEMENT,
                "minimum_directional_advantage": _MIN_DIRECTIONAL_ADVANTAGE,
                "acceptable_capacity_ratio_low": 0.80,
                "acceptable_capacity_ratio_high": 1.25,
            },
        },
    }


def _latest_changed_revision_pair(
    config: UsageAllowanceConfig,
) -> tuple[CreditRateRevision, CreditRateRevision, list[str]] | None:
    revisions = config.rate_revisions
    for index in range(len(revisions) - 1, 0, -1):
        before, after = revisions[index - 1], revisions[index]
        changed = sorted(
            model
            for model in set(before.credit_rates) | set(after.credit_rates)
            if before.credit_rates.get(model) != after.credit_rates.get(model)
            and model not in config.local_rate_models
        )
        if changed:
            return before, after, changed
    return None


def _load_rate_hypothesis_intervals(
    connection: sqlite3.Connection,
    *,
    source_revision: str,
    archive_scope: str,
    window_kind: str,
    cohort_key: str,
    config: UsageAllowanceConfig,
    before: CreditRateRevision,
    after: CreditRateRevision,
    changed_models: Sequence[str],
) -> list[RateHypothesisInterval]:
    include_archived = archive_scope == "all"
    interval_rows = [
        dict(row)
        for row in connection.execute(
            "SELECT i.*, c.plan_type FROM allowance_intervals AS i "
            "JOIN allowance_cycles AS c ON c.cycle_id = i.cycle_id "
            "WHERE i.source_revision = ? AND i.window_kind = ? "
            "AND i.cohort_key = ? AND (? OR i.is_archived = 0) "
            "AND i.point_kind = 'positive' AND i.eligible_for_change_detection = 1 "
            "ORDER BY i.end_observed_at, i.interval_id",
            (source_revision, window_kind, cohort_key, include_archived),
        )
    ]
    observation_groups = _observation_groups(
        connection,
        archive_scope=archive_scope,
        window_kind=window_kind,
        cohort_key=cohort_key,
    )
    changed = set(changed_models)
    evidence: list[RateHypothesisInterval] = []
    for interval in interval_rows:
        movement = number_value(interval.get("visible_percent_delta"))
        if movement <= 0:
            continue
        key = _interval_group_key(interval)
        grouped = observation_groups.get(key)
        if grouped is None:
            continue
        rows, positions = grouped
        start_index = positions.get(str(interval.get("start_observation_id") or ""))
        end_index = positions.get(str(interval.get("end_observation_id") or ""))
        if start_index is None or end_index is None or end_index <= start_index:
            continue
        usage_rows = rows[start_index + 1 : end_index + 1]
        priced = _price_interval_rows(
            usage_rows,
            before=before,
            after=after,
            config=config,
            changed_models=changed,
        )
        if priced is None:
            continue
        start_at = _optional_time(interval.get("start_observed_at"))
        end_at = _optional_time(interval.get("end_observed_at"))
        if start_at is None or end_at is None:
            continue
        evidence.append(
            RateHypothesisInterval(
                start_at=start_at,
                end_at=end_at,
                movement=movement,
                old_credits=priced[0],
                new_credits=priced[1],
                signal_share=priced[2],
                plan_type=str(interval.get("plan_type") or "unknown"),
            )
        )
    return evidence


def _observation_groups(
    connection: sqlite3.Connection,
    *,
    archive_scope: str,
    window_kind: str,
    cohort_key: str,
) -> dict[
    tuple[bool, str, str, str],
    tuple[list[dict[str, Any]], dict[str, int]],
]:
    include_archived = archive_scope == "all"
    rows = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM allowance_observations WHERE window_kind = ? "
            "AND COALESCE(NULLIF(limit_id, ''), 'codex') = ? "
            "AND (? OR is_archived = 0) "
            "ORDER BY event_timestamp, cumulative_total_tokens, observation_id",
            (window_kind, cohort_key, include_archived),
        )
    ]
    grouped_rows: dict[tuple[bool, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped_rows.setdefault(_observation_group_key(row), []).append(row)
    return {
        key: (
            group,
            {str(row.get("observation_id") or ""): index for index, row in enumerate(group)},
        )
        for key, group in grouped_rows.items()
    }


def _price_interval_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    before: CreditRateRevision,
    after: CreditRateRevision,
    config: UsageAllowanceConfig,
    changed_models: set[str],
) -> tuple[float, float, float] | None:
    old_credits = 0.0
    new_credits = 0.0
    total_tokens = 0.0
    priced_tokens = 0.0
    changed_tokens = 0.0
    for row in rows:
        tokens = number_value(row.get("total_tokens"))
        total_tokens += tokens
        target = _target_model(row.get("model"), config)
        if target is None:
            continue
        if target in config.local_rate_models:
            old_rates = new_rates = config.credit_rates.get(target)
        else:
            old_rates = before.credit_rates.get(target)
            new_rates = after.credit_rates.get(target)
        if old_rates is None or new_rates is None:
            continue
        multiplier, _match, _fallback = credit_multiplier_for_row(
            dict(row), config.fast_multipliers
        )
        old_credits += estimate_standard_usage_credits(dict(row), old_rates) * multiplier
        new_credits += estimate_standard_usage_credits(dict(row), new_rates) * multiplier
        priced_tokens += tokens
        if target in changed_models:
            changed_tokens += tokens
    if total_tokens <= 0 or priced_tokens / total_tokens < 0.95:
        return None
    if old_credits <= 0 or new_credits <= 0:
        return None
    return old_credits, new_credits, changed_tokens / total_tokens


def _target_model(model: object, config: UsageAllowanceConfig) -> str | None:
    normalized = normalize_model(model)
    if not normalized:
        return None
    alias = config.aliases.get(normalized)
    if alias:
        target = normalize_model(alias.get("model"))
        if target:
            return target
    return normalized


def _candidate_fits(
    rows: Sequence[RateHypothesisInterval],
    prior: datetime,
) -> list[dict[str, Any]]:
    all_candidates: list[dict[str, Any]] = []
    primary: list[dict[str, Any]] = []
    for split in range(_MIN_INTERVALS_PER_SIDE, len(rows) - _MIN_INTERVALS_PER_SIDE + 1):
        lower = rows[split - 1].end_at
        upper = rows[split].start_at
        if upper < lower:
            upper = rows[split].end_at
        estimate = lower + ((upper - lower) / 2)
        candidate = {
            "split_index": split,
            "lower_bound": lower,
            "upper_bound": upper,
            "estimate": estimate,
            "forward_loss": _split_loss(rows, split, reverse=False),
            "reverse_loss": _split_loss(rows, split, reverse=True),
        }
        all_candidates.append(candidate)
        if abs(estimate - prior) <= _PRIMARY_PRIOR_RADIUS:
            primary.append(candidate)
    return primary or all_candidates


def _split_loss(
    rows: Sequence[RateHypothesisInterval],
    split: int,
    *,
    reverse: bool,
) -> float:
    points: list[tuple[float, float]] = []
    for index, row in enumerate(rows):
        before = index < split
        use_old = before != reverse
        credits = row.old_credits if use_old else row.new_credits
        points.append((_log_ratio(credits, row.movement), _weight(row)))
    return _weighted_absolute_loss(points)


def _fit_loss(rows: Sequence[RateHypothesisInterval], hypothesis: str) -> float:
    return _weighted_absolute_loss(
        [
            (
                _log_ratio(
                    row.old_credits if hypothesis == "old" else row.new_credits,
                    row.movement,
                ),
                _weight(row),
            )
            for row in rows
        ]
    )


def _weighted_absolute_loss(points: Sequence[tuple[float, float]]) -> float:
    center = _weighted_median(points)
    total_weight = sum(weight for _value, weight in points)
    if total_weight <= 0:
        return math.inf
    return sum(weight * abs(value - center) for value, weight in points) / total_weight


def _weighted_median(points: Sequence[tuple[float, float]]) -> float:
    ordered = sorted(points, key=lambda point: point[0])
    total = sum(weight for _value, weight in ordered)
    threshold = total / 2
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= threshold:
            return value
    return ordered[-1][0]


def _capacity_ratio(rows: Sequence[RateHypothesisInterval], split: int) -> float:
    before = [row.old_credits / row.movement for row in rows[:split]]
    after = [row.new_credits / row.movement for row in rows[split:]]
    return median(after) / median(before)


def _plausible_candidates(
    candidates: Sequence[dict[str, Any]],
    *,
    null_loss: float,
    best_loss: float,
) -> list[dict[str, Any]]:
    allowance = max((null_loss - best_loss) * 0.25, 0.01)
    plausible = [
        candidate
        for candidate in candidates
        if float(candidate["forward_loss"]) <= best_loss + allowance
    ]
    return plausible or [min(candidates, key=lambda candidate: candidate["forward_loss"])]


def _confidence(
    *,
    supported: bool,
    improvement: float,
    directional_advantage: float,
    before_count: int,
    after_count: int,
    bound_width: timedelta,
    capacity_ratio: float,
) -> str:
    if not supported:
        return "low"
    if (
        improvement >= 0.50
        and directional_advantage >= 0.30
        and min(before_count, after_count) >= 5
        and bound_width <= timedelta(hours=24)
        and 0.90 <= capacity_ratio <= 1.10
    ):
        return "high"
    return "medium"


def _select_plan_segment(
    rows: Sequence[RateHypothesisInterval], prior: datetime
) -> list[RateHypothesisInterval]:
    known = [row for row in rows if row.plan_type not in {"", "unknown", "mixed"}]
    if not known:
        return list(rows)
    nearest = min(known, key=lambda row: abs(row.end_at - prior))
    return [row for row in rows if row.plan_type == nearest.plan_type]


def _coerce_interval(
    value: RateHypothesisInterval | Mapping[str, object],
) -> RateHypothesisInterval | None:
    if isinstance(value, RateHypothesisInterval):
        return value
    start = _optional_time(value.get("start_at"))
    end = _optional_time(value.get("end_at"))
    movement = number_value(value.get("movement"))
    old_credits = number_value(value.get("old_credits"))
    new_credits = number_value(value.get("new_credits"))
    signal_share = number_value(value.get("signal_share"))
    if start is None or end is None or movement <= 0 or old_credits <= 0 or new_credits <= 0:
        return None
    return RateHypothesisInterval(
        start_at=start,
        end_at=end,
        movement=movement,
        old_credits=old_credits,
        new_credits=new_credits,
        signal_share=max(0.0, min(signal_share, 1.0)),
        plan_type=str(value.get("plan_type") or "unknown"),
    )


def _observation_group_key(row: Mapping[str, Any]) -> tuple[bool, str, str, str]:
    return (
        bool(row.get("is_archived")),
        str(row.get("window_kind") or "unknown"),
        str(row.get("window_key") or "primary"),
        str(row.get("limit_id") or "codex"),
    )


def _interval_group_key(row: Mapping[str, Any]) -> tuple[bool, str, str, str]:
    return (
        bool(row.get("is_archived")),
        str(row.get("window_kind") or "unknown"),
        str(row.get("window_key") or "primary"),
        str(row.get("cohort_key") or "codex"),
    )


def _relative_delta(old: float, new: float) -> float:
    return abs(old - new) / max(old, new, 1e-12)


def _relative_improvement(baseline: float, candidate: float) -> float:
    if not math.isfinite(baseline) or baseline <= 1e-12:
        return 0.0
    return max(0.0, min(1.0, (baseline - candidate) / baseline))


def _weight(row: RateHypothesisInterval) -> float:
    return max(row.movement, 0.1) * max(row.signal_share, 0.05)


def _log_ratio(credits: float, movement: float) -> float:
    return math.log(max(credits / movement, 1e-12))


def _parse_time(value: str) -> datetime:
    parsed = _optional_time(value)
    if parsed is None:
        raise ValueError("configured rate revision timestamp must be timezone-aware ISO-8601")
    return parsed


def _optional_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _caveats(configured_precision: str) -> list[str]:
    caveats = [
        "Boundary is inferred from local weekly-meter movement, not an official billing ledger.",
        "Intervals containing usage outside indexed Codex logs can weaken or shift the estimate.",
        "Fast-mode, routing, and model-mix metadata must be correct for both hypotheses.",
        "The detector compares a known old-to-new rate transition against old-only, new-only, and reversed alternatives.",
    ]
    if configured_precision == "day":
        caveats.append(
            "The configured revision timestamp is only a date-level prior and is not treated as an exact rollout instant."
        )
    return caveats


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "detector_version": RATE_CHANGE_DETECTOR_VERSION,
        "status": "unavailable",
        "confidence": "none",
        "reason": reason,
        "revision": None,
        "estimate": None,
        "evidence": None,
        "caveats": [],
    }
