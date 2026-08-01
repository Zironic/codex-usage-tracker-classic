"""JSON contracts for compact allowance export and plan comparison."""

from __future__ import annotations

from typing import Any

NoneType = type(None)

_COMPACT_EXPORT_REQUIRED = {
    "generated_at": str,
    "privacy_mode": str,
    "request": dict,
    "coverage": dict,
    "layout": dict,
    "summary": dict,
    "windows": list,
    "notes": list,
}
_COMPACT_EXPORT_COVERAGE = {
    "matched_observation_count": int,
    "exported_observation_count": int,
    "start_date": (str, NoneType),
    "end_date": (str, NoneType),
    "window_count": int,
    "span_count": int,
    "truncated": bool,
}

ALLOWANCE_EXTENSION_JSON_PAYLOAD_CONTRACTS: dict[str, dict[str, Any]] = {
    "codex-usage-tracker-allowance-evidence-export-v3": {
        "required": _COMPACT_EXPORT_REQUIRED,
        "nested": {
            "coverage": _COMPACT_EXPORT_COVERAGE,
            "layout": {
                "time_origin": (str, NoneType),
                "time_unit": str,
                "timestamp_precision": str,
                "span_columns": list,
                "conventions": dict,
            },
        },
    },
    "codex-usage-tracker-allowance-evidence-export-v2": {
        "required": _COMPACT_EXPORT_REQUIRED,
        "nested": {"coverage": _COMPACT_EXPORT_COVERAGE},
    },
    "codex-usage-tracker-allowance-analysis-v2": {
        "required": {
            "status": str,
            "snapshot_id": str,
            "source_revision": str,
            "model_version": str,
            "rate_card_revision": str,
            "parameters": dict,
            "plan_comparison": (dict, NoneType),
        }
    },
}
