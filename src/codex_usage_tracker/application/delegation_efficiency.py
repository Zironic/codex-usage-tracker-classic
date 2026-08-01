"""Descriptive delegation-efficiency adapter over aggregate subagent usage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codex_usage_tracker.core.json_contract_efficiency import DELEGATION_EFFICIENCY_SCHEMA
from codex_usage_tracker.core.paths import DEFAULT_DB_PATH, DEFAULT_PRICING_PATH
from codex_usage_tracker.core.projects import validate_privacy_mode
from codex_usage_tracker.reports.subagent_usage import build_subagent_usage_report
from codex_usage_tracker.store.delegation_efficiency_queries import (
    query_direct_sol_before_after_luna,
)

_RESOURCE_FIELDS = (
    "calls",
    "turns",
    "observed_spawns",
    "input_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "latest_event",
)
_PRICING_FIELDS = (
    "priced_model_count",
    "estimated_model_count",
    "unpriced_model_count",
    "priced_tokens",
    "estimated_tokens",
    "unpriced_tokens",
)


@dataclass(frozen=True)
class DelegationEfficiencyRequest:
    """Strict aggregate-only filters for the descriptive operation."""

    since: str | None = None
    until: str | None = None
    adoption_at: str | None = None
    parent_thread: str | None = None
    include_archived: bool = False
    limit: int = 10
    privacy_mode: str = "normal"

    def __post_init__(self) -> None:
        _validate_datetime(self.since, "since")
        _validate_datetime(self.until, "until")
        _validate_datetime(self.adoption_at, "adoption_at")
        if self.parent_thread is not None and (
            not isinstance(self.parent_thread, str) or not self.parent_thread.strip()
        ):
            raise ValueError("parent_thread must be a non-empty string")
        if type(self.include_archived) is not bool:
            raise ValueError("include_archived must be a bool")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("limit must be an integer from 1 through 100")
        validate_privacy_mode(self.privacy_mode)


def build_delegation_efficiency(
    request: DelegationEfficiencyRequest,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    pricing_path: Path = DEFAULT_PRICING_PATH,
) -> dict[str, Any]:
    """Return a descriptive, role-observed resource comparison.

    This operation deliberately reuses the existing aggregate subagent report.
    It does not infer work-item outcomes, lifecycle timing, controlled pairs, or
    model-alias qualification from usage rows that do not carry those fields.
    """

    if not isinstance(request, DelegationEfficiencyRequest):
        raise TypeError("request must be a DelegationEfficiencyRequest")
    # Re-run validation for callers that may have supplied an object created by
    # a serializer or an untrusted adapter rather than the dataclass constructor.
    request.__post_init__()

    report_arguments: dict[str, Any] = {
        "db_path": db_path,
        "pricing_path": pricing_path,
        "since": request.since,
        "until": request.until,
        "parent_thread": request.parent_thread,
        "include_archived": request.include_archived,
        "limit": request.limit,
        "privacy_mode": request.privacy_mode,
    }
    legacy = build_subagent_usage_report(
        **report_arguments,
    )
    high_legacy = build_subagent_usage_report(
        **report_arguments,
        agent_role="luna_worker_high",
    )
    low_legacy = build_subagent_usage_report(
        **report_arguments,
        agent_role="luna_worker_low",
    )
    payload = _payload_mapping(legacy)
    high_payload = _payload_mapping(high_legacy)
    low_payload = _payload_mapping(low_legacy)
    comparison = _mapping(payload.get("comparison"))
    direct = _mapping(comparison.get("direct"))
    subagent = _mapping(comparison.get("subagent"))
    high = _role_report_bucket(high_payload)
    low = _role_report_bucket(low_payload)

    raw_filters = _mapping(payload.get("filters"))
    historical = query_direct_sol_before_after_luna(
        db_path,
        since=request.since,
        until=request.until,
        adoption_at=request.adoption_at,
        parent_thread=request.parent_thread,
        include_archived=request.include_archived,
    )
    before = _mapping(historical.get("before"))
    after = _mapping(historical.get("after"))
    before_rate = _optional_number(before.get("tokens_per_turn"))
    after_rate = _optional_number(after.get("tokens_per_turn"))
    absolute_delta = (
        after_rate - before_rate
        if before_rate is not None and after_rate is not None
        else None
    )
    relative_delta = (
        absolute_delta / before_rate
        if absolute_delta is not None and before_rate not in {None, 0.0}
        else None
    )
    direction = _delta_direction(absolute_delta)
    filters = {
        "since": request.since,
        "until": request.until,
        "adoption_at": request.adoption_at,
        "parent_thread": raw_filters.get("parent_thread", request.parent_thread),
        "include_archived": request.include_archived,
        "limit": request.limit,
        "privacy_mode": request.privacy_mode,
    }
    resources = {
        "direct": _cohort(
            "direct_observed",
            label="Direct observed",
            classification="direct_observed",
            resource=_resource_bucket(direct),
        ),
        "luna_worker_high": _cohort(
            "luna_worker_high",
            label="Luna worker high",
            classification="role_observed",
            role="luna_worker_high",
            resource=_resource_bucket(high),
        ),
        "luna_worker_low": _cohort(
            "luna_worker_low",
            label="Luna worker low",
            classification="role_observed",
            role="luna_worker_low",
            resource=_resource_bucket(low),
        ),
    }

    raw_coverage = _mapping(payload.get("coverage"))
    denominators = {
        "direct_calls": _number(direct.get("calls")),
        "direct_turns": _number(direct.get("turns")),
        "direct_tokens": _number(direct.get("total_tokens")),
        "subagent_calls": _number(subagent.get("calls")),
        "subagent_turns": _number(subagent.get("turns")),
        "subagent_tokens": _number(subagent.get("total_tokens")),
        "observed_spawns": _number(_mapping(payload.get("summary")).get("observed_spawns")),
        "luna_worker_high_calls": _number(high.get("calls")),
        "luna_worker_high_spawns": _number(high.get("observed_spawns")),
        "luna_worker_low_calls": _number(low.get("calls")),
        "luna_worker_low_spawns": _number(low.get("observed_spawns")),
    }

    limitations = [
        "Outcomes and work-item identity are unavailable; acceptance, rejection, rework, failure, cancellation, and timeout denominators are not measured.",
        "Lifecycle timing is unavailable; queue, child runtime, integration, elapsed-time, and concurrency metrics are not measured.",
        "Controlled attribution is unavailable; this is a descriptive observational response, not a controlled comparison.",
        "Model-alias completeness is unavailable; Luna cohorts are role-observed only and are not model-qualified.",
        "Credit and derived-duration accounting are not included in this response; use usage.query for those descriptive measures.",
        "Observed resource differences do not establish causality, acceptance, speedup, or controlled efficiency.",
    ]
    return {
        "schema": DELEGATION_EFFICIENCY_SCHEMA,
        "schema_id": DELEGATION_EFFICIENCY_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "claim_level": "descriptive",
        "comparison_ready": False,
        "filters": filters,
        "cohorts": resources,
        "historical_comparison": {
            **historical,
            "metric": "direct_sol_tokens_per_turn",
            "boundary_semantics": {"before": "event_timestamp < adoption_at", "after": "event_timestamp >= adoption_at"},
            "absolute_delta": absolute_delta,
            "relative_delta": relative_delta,
            "percent_delta": relative_delta * 100 if relative_delta is not None else None,
            "direction": direction,
            "interpretation": _historical_interpretation(direction),
        },
        "coverage": {
            "denominators": denominators,
            "linkage": dict(raw_coverage),
            "role_linkage": {
                "luna_worker_high": _mapping(high_payload.get("coverage")),
                "luna_worker_low": _mapping(low_payload.get("coverage")),
            },
            "pricing": {
                key: resources[key]["resource"]["pricing_coverage"]
                for key in resources
            },
            "model_alias": {"status": "unavailable", "qualified": False},
        },
        "readiness": {
            "status": "descriptive_only",
            "comparison_ready": False,
            "controlled_attribution": False,
        },
        "limitations": limitations,
        "definitions": {
            "claim_level": "descriptive",
            "direct_cohort": "Rows outside the existing observed-subagent predicate; not a model-qualified Sol cohort.",
            "role_observed": "Rows grouped by exact agent_role; model aliases are not qualified.",
            "observed_spawn": "A distinct known-session subagent row grouping in aggregate usage.",
            "historical_turn": "A distinct known session_id plus turn_id; rows missing either identity are conservatively counted as individual fallback turns and disclosed per period.",
            "historical_boundary": "Before excludes adoption_at; after includes adoption_at. Caller-supplied since and until filters bound both periods and automatic boundary discovery.",
        },
        "availability": {
            "outcomes": False,
            "work_items": False,
            "lifecycle_timing": False,
            "controlled_attribution": False,
            "model_alias_qualification": False,
            "credit_accounting": False,
            "derived_duration": False,
        },
        "source_report_schema": payload.get(
            "schema_id", "codex-usage-tracker.subagent-usage.v1"
        ),
    }


def _payload_mapping(value: object) -> dict[str, Any]:
    if hasattr(value, "payload"):
        value = value.payload()  # type: ignore[operator]
    if not isinstance(value, dict):
        raise TypeError("subagent report must return an object payload")
    return dict(value)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _role_report_bucket(payload: dict[str, Any]) -> dict[str, Any]:
    comparison = _mapping(payload.get("comparison"))
    return _mapping(comparison.get("subagent"))


def _cohort(
    cohort: str,
    *,
    label: str,
    classification: str,
    resource: dict[str, Any],
    role: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "cohort": cohort,
        "label": label,
        "classification": classification,
        "resource": resource,
        "model_alias": {"status": "unavailable", "qualified": False},
    }
    if role is not None:
        result["observed_role"] = role
    return result


def _resource_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in _RESOURCE_FIELDS:
        value = bucket.get(key)
        if key == "latest_event":
            result[key] = value if isinstance(value, str) else None
        else:
            result[key] = _number(value)
    cost = bucket.get("estimated_cost_usd")
    result["estimated_cost_usd"] = float(cost) if isinstance(cost, int | float) else None
    pricing = _mapping(bucket.get("pricing_coverage"))
    result["pricing_coverage"] = {
        key: _number(pricing.get(key)) for key in _PRICING_FIELDS
    }
    return result


def _number(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    return 0


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def _validate_datetime(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty ISO-8601 date or datetime")
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 date or datetime") from exc


def _delta_direction(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if value < 0:
        return "decreased"
    if value > 0:
        return "increased"
    return "unchanged"


def _historical_interpretation(direction: str) -> str:
    if direction == "unavailable":
        result = "The before/after rate is unavailable because one period has no observed direct Sol turns."
    else:
        result = f"Observed direct Sol tokens per turn {direction} after the Luna boundary."
    return f"{result} Descriptive only; task mix and other changes are not controlled."


__all__ = [
    "DELEGATION_EFFICIENCY_SCHEMA",
    "DelegationEfficiencyRequest",
    "build_delegation_efficiency",
]
