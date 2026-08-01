"""Stable JSON contract for descriptive delegation-efficiency responses."""

from __future__ import annotations

from typing import Any

NoneType = type(None)

DELEGATION_EFFICIENCY_SCHEMA = "codex-usage-tracker.delegation-efficiency.v1"

DELEGATION_EFFICIENCY_JSON_PAYLOAD_CONTRACTS: dict[str, dict[str, Any]] = {
    DELEGATION_EFFICIENCY_SCHEMA: {
        "required": {
            "schema": str,
            "schema_id": str,
            "generated_at": str,
            "claim_level": str,
            "comparison_ready": bool,
            "filters": dict,
            "cohorts": dict,
            "historical_comparison": dict,
            "coverage": dict,
            "readiness": dict,
            "limitations": list,
            "definitions": dict,
            "availability": dict,
            "source_report_schema": str,
        },
        "nested": {
            "filters": {
                "since": (str, NoneType),
                "until": (str, NoneType),
                "adoption_at": (str, NoneType),
                "parent_thread": (str, NoneType),
                "include_archived": bool,
                "limit": int,
                "privacy_mode": str,
            },
            "cohorts": {
                "direct": dict,
                "luna_worker_high": dict,
                "luna_worker_low": dict,
            },
            "readiness": {
                "status": str,
                "comparison_ready": bool,
                "controlled_attribution": bool,
            },
            "historical_comparison": {
                "adoption_at": (str, NoneType),
                "adoption_role": (str, NoneType),
                "adoption_source": str,
                "direct_model": str,
                "before": dict,
                "after": dict,
                "metric": str,
                "boundary_semantics": dict,
                "absolute_delta": (int, float, NoneType),
                "relative_delta": (int, float, NoneType),
                "percent_delta": (int, float, NoneType),
                "direction": str,
                "interpretation": str,
            },
        },
    }
}


__all__ = [
    "DELEGATION_EFFICIENCY_JSON_PAYLOAD_CONTRACTS",
    "DELEGATION_EFFICIENCY_SCHEMA",
]
