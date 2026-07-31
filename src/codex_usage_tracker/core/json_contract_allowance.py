"""JSON contracts for compact allowance export and plan comparison."""

from __future__ import annotations

from typing import Any

NoneType = type(None)

ALLOWANCE_EXTENSION_JSON_PAYLOAD_CONTRACTS: dict[str, dict[str, Any]] = {
    "codex-usage-tracker-allowance-evidence-export-v2": {
        "required": {
            "generated_at": str,
            "privacy_mode": str,
            "request": dict,
            "coverage": dict,
            "layout": dict,
            "summary": dict,
            "plan_comparison": dict,
            "windows": list,
            "notes": list,
        },
        "nested": {
            "coverage": {
                "matched_observation_count": int,
                "exported_observation_count": int,
                "start_date": (str, NoneType),
                "end_date": (str, NoneType),
                "window_count": int,
                "span_count": int,
                "truncated": bool,
            }
        },
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
