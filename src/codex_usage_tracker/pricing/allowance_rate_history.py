"""Timestamped Codex credit-rate revision parsing and selection."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from codex_usage_tracker.pricing.allowance_rate_card import (
    optional_str,
    parse_credit_rate_metadata,
    parse_credit_rates,
)


@dataclass(frozen=True)
class CreditRateRevision:
    """One cumulative credit-rate snapshot selected by event timestamp."""

    revision_id: str
    effective_at: datetime | None
    effective_at_text: str | None
    effective_at_precision: str
    credit_rates: dict[str, dict[str, float]]
    rate_metadata: dict[str, dict[str, Any]]
    source: dict[str, Any]


def parse_rate_revisions(
    raw: object,
    *,
    default_source: dict[str, Any],
) -> tuple[CreditRateRevision, ...]:
    """Parse ordered baseline-plus-dated rate revisions into cumulative snapshots."""

    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("rate_revisions must be a list")

    revisions: list[CreditRateRevision] = []
    cumulative_rates: dict[str, dict[str, float]] = {}
    cumulative_metadata: dict[str, dict[str, Any]] = {}
    previous_effective_at: datetime | None = None
    baseline_seen = False

    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise ValueError(f"rate_revisions[{index}] must be an object")
        effective_at_text = optional_str(value.get("effective_at"))
        effective_at = _parse_effective_at(effective_at_text, index=index)
        if effective_at is None:
            if baseline_seen or index != 0:
                raise ValueError("only the first rate revision may be an undated baseline")
            baseline_seen = True
        elif previous_effective_at is not None and effective_at <= previous_effective_at:
            raise ValueError("dated rate revisions must be strictly increasing")
        if effective_at is not None:
            previous_effective_at = effective_at

        source_value = value.get("source")
        revision_source = {
            **default_source,
            **(source_value if isinstance(source_value, dict) else {}),
        }
        rates = parse_credit_rates(value.get("credit_rates", {}))
        if not rates:
            raise ValueError(f"rate_revisions[{index}] must contain credit_rates")
        metadata = parse_credit_rate_metadata(
            value.get("credit_rates", {}),
            source=revision_source,
            default_confidence="exact",
        )
        cumulative_rates.update(rates)
        cumulative_metadata.update(metadata)

        revision_id = optional_str(value.get("revision_id")) or (
            effective_at_text or "baseline"
        )
        precision = optional_str(value.get("effective_at_precision")) or (
            "unknown" if effective_at is None else "second"
        )
        snapshot_metadata = {
            model: {
                **details,
                "rate_revision": revision_id,
                "effective_at": effective_at_text,
                "effective_at_precision": precision,
            }
            for model, details in cumulative_metadata.items()
        }
        revisions.append(
            CreditRateRevision(
                revision_id=revision_id,
                effective_at=effective_at,
                effective_at_text=effective_at_text,
                effective_at_precision=precision,
                credit_rates={model: dict(rate) for model, rate in cumulative_rates.items()},
                rate_metadata={
                    model: dict(details) for model, details in snapshot_metadata.items()
                },
                source=dict(revision_source),
            )
        )

    return tuple(revisions)


def revision_for_timestamp(
    revisions: Sequence[CreditRateRevision],
    observed_at: object,
) -> CreditRateRevision | None:
    """Return the latest revision effective at one observed event timestamp."""

    observed = _optional_observed_at(observed_at)
    if observed is None:
        return None
    selected: CreditRateRevision | None = None
    for revision in revisions:
        if revision.effective_at is None:
            selected = revision
            continue
        if revision.effective_at <= observed:
            selected = revision
            continue
        break
    return selected


def revision_signature(revisions: Sequence[CreditRateRevision]) -> list[dict[str, object]]:
    """Return a stable JSON-ready representation for cache invalidation."""

    return [
        {
            "revision_id": revision.revision_id,
            "effective_at": revision.effective_at_text,
            "effective_at_precision": revision.effective_at_precision,
            "credit_rates": revision.credit_rates,
            "rate_metadata": revision.rate_metadata,
        }
        for revision in revisions
    ]


def _parse_effective_at(value: str | None, *, index: int) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid effective_at in rate_revisions[{index}]") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"rate_revisions[{index}].effective_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _optional_observed_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)
