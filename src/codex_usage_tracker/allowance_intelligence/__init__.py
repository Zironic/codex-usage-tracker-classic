"""Allowance history and change-evidence diagnostics."""

from typing import Any

from codex_usage_tracker.allowance_intelligence.model import (
    EVIDENCE_GRADES,
    WINDOW_KIND_CHOICES,
    build_allowance_analysis,
)

__all__ = (
    "ALLOWANCE_EXPORT_COMPACT_SCHEMA",
    "ALLOWANCE_EXPORT_FORMATS",
    "ALLOWANCE_EXPORT_SCHEMA",
    "ALLOWANCE_EXPORT_VERBOSE_SCHEMA",
    "PLAN_COMPARISON_VERSION",
    "AllowanceReport",
    "EVIDENCE_GRADES",
    "WINDOW_KIND_CHOICES",
    "build_allowance_analysis",
    "build_allowance_diagnostics_report",
    "build_allowance_export_report",
    "build_allowance_history_report",
    "build_allowance_status",
    "build_allowance_series",
    "build_allowance_evidence",
    "build_plan_meter_comparison",
)


def __getattr__(name: str) -> Any:
    """Load report builders lazily to keep store materialization acyclic."""

    if name in {
        "ALLOWANCE_EXPORT_COMPACT_SCHEMA",
        "ALLOWANCE_EXPORT_FORMATS",
        "ALLOWANCE_EXPORT_VERBOSE_SCHEMA",
    }:
        from codex_usage_tracker.allowance_intelligence import export_payload

        return getattr(export_payload, name)
    if name == "ALLOWANCE_EXPORT_SCHEMA":
        from codex_usage_tracker.allowance_intelligence.reports import (
            ALLOWANCE_EXPORT_SCHEMA,
        )

        return ALLOWANCE_EXPORT_SCHEMA
    if name in {"PLAN_COMPARISON_VERSION", "build_plan_meter_comparison"}:
        from codex_usage_tracker.allowance_intelligence import plan_comparison

        return getattr(plan_comparison, name)
    if name in {
        "AllowanceReport",
        "build_allowance_diagnostics_report",
        "build_allowance_export_report",
        "build_allowance_history_report",
    }:
        from codex_usage_tracker.allowance_intelligence import reports

        return getattr(reports, name)
    if name in {
        "build_allowance_status",
        "build_allowance_series",
        "build_allowance_evidence",
    }:
        from codex_usage_tracker.allowance_intelligence import service

        return getattr(service, name)
    raise AttributeError(name)
