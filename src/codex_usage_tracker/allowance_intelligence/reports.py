"""Allowance intelligence report builders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codex_usage_tracker.allowance_intelligence.export_payload import (
    ALLOWANCE_EXPORT_COMPACT_SCHEMA,
    ALLOWANCE_EXPORT_FORMATS,
    ALLOWANCE_EXPORT_VERBOSE_SCHEMA,
    AllowanceExportCoverage,
    build_compact_allowance_export,
    build_verbose_allowance_export,
)
from codex_usage_tracker.allowance_intelligence.model import (
    WINDOW_KIND_CHOICES,
    build_allowance_analysis,
)
from codex_usage_tracker.allowance_intelligence.plan_comparison import (
    build_plan_meter_comparison,
)
from codex_usage_tracker.core.paths import (
    DEFAULT_ALLOWANCE_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_RATE_CARD_PATH,
)
from codex_usage_tracker.core.projects import validate_privacy_mode
from codex_usage_tracker.pricing.allowance import (
    annotate_rows_with_allowance,
    load_allowance_config,
)
from codex_usage_tracker.store.allowance_materialization import (
    materialize_allowance_intelligence,
)
from codex_usage_tracker.store.allowance_observations import (
    AllowanceObservationSelection,
    query_allowance_observation_selection,
)
from codex_usage_tracker.store.connection import connect

ALLOWANCE_HISTORY_SCHEMA = "codex-usage-tracker-allowance-history-v1"
ALLOWANCE_DIAGNOSTICS_SCHEMA = "codex-usage-tracker-allowance-diagnostics-v1"
ALLOWANCE_EXPORT_SCHEMA = ALLOWANCE_EXPORT_VERBOSE_SCHEMA


@dataclass(frozen=True)
class AllowanceReport:
    """Resolved allowance intelligence report."""

    payload: dict[str, Any]

    def render(self) -> str:
        schema = self.payload.get("schema")
        if schema == ALLOWANCE_HISTORY_SCHEMA:
            return _render_history(self.payload)
        if schema in {
            ALLOWANCE_EXPORT_COMPACT_SCHEMA,
            ALLOWANCE_EXPORT_VERBOSE_SCHEMA,
        }:
            return _render_export(self.payload)
        return _render_diagnostics(self.payload)


def build_allowance_history_report(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    allowance_path: Path = DEFAULT_ALLOWANCE_PATH,
    rate_card_path: Path = DEFAULT_RATE_CARD_PATH,
    include_archived: bool = False,
    window_kind: str | None = None,
    limit: int | None = 1000,
    privacy_mode: str = "strict",
) -> AllowanceReport:
    """Build normalized observed allowance history."""

    privacy_mode = validate_privacy_mode(privacy_mode)
    _validate_window_kind(window_kind)
    selection, rows = _annotated_observation_selection(
        db_path=db_path,
        allowance_path=allowance_path,
        rate_card_path=rate_card_path,
        include_archived=include_archived,
        window_kind=window_kind,
        limit=limit,
    )
    return AllowanceReport(
        {
            "schema": ALLOWANCE_HISTORY_SCHEMA,
            "generated_at": _generated_at(),
            "privacy_mode": privacy_mode,
            "include_archived": include_archived,
            "window_kind": window_kind,
            "row_count": selection.exported_count,
            "rows": [_history_row(row, privacy_mode=privacy_mode) for row in rows],
            "notes": _privacy_notes(),
        }
    )


def build_allowance_diagnostics_report(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    allowance_path: Path = DEFAULT_ALLOWANCE_PATH,
    rate_card_path: Path = DEFAULT_RATE_CARD_PATH,
    include_archived: bool = False,
    window_kind: str | None = None,
    limit: int | None = None,
    privacy_mode: str = "strict",
) -> AllowanceReport:
    """Build evidence-graded allowance change diagnostics."""

    privacy_mode = validate_privacy_mode(privacy_mode)
    _validate_window_kind(window_kind)
    _selection, rows = _annotated_observation_selection(
        db_path=db_path,
        allowance_path=allowance_path,
        rate_card_path=rate_card_path,
        include_archived=include_archived,
        window_kind=window_kind,
        limit=limit,
    )
    return AllowanceReport(
        _diagnostics_payload(
            rows,
            generated_at=_generated_at(),
            include_archived=include_archived,
            window_kind=window_kind,
            privacy_mode=privacy_mode,
        )
    )


def build_allowance_export_report(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    allowance_path: Path = DEFAULT_ALLOWANCE_PATH,
    rate_card_path: Path = DEFAULT_RATE_CARD_PATH,
    include_archived: bool = False,
    window_kind: str | None = None,
    limit: int | None = None,
    export_format: str = "verbose",
    from_plan: str | None = None,
    to_plan: str | None = None,
) -> AllowanceReport:
    """Build a strict-privacy local evidence bundle for manual sharing."""

    _validate_window_kind(window_kind)
    if export_format not in ALLOWANCE_EXPORT_FORMATS:
        raise ValueError("export_format must be compact or verbose")
    if bool(from_plan) != bool(to_plan):
        raise ValueError("from_plan and to_plan must be provided together")
    selection, rows = _annotated_observation_selection(
        db_path=db_path,
        allowance_path=allowance_path,
        rate_card_path=rate_card_path,
        include_archived=include_archived,
        window_kind=window_kind,
        limit=limit,
    )
    generated_at = _generated_at()
    diagnostics = _diagnostics_payload(
        rows,
        generated_at=generated_at,
        include_archived=include_archived,
        window_kind=window_kind,
        privacy_mode="strict",
    )
    notes = [
        *_privacy_notes(),
        "This bundle is local evidence only and is not an official OpenAI usage ledger.",
        "Exact timestamps are bucketed to dates and local record identifiers are omitted.",
    ]
    if export_format == "verbose":
        return AllowanceReport(
            build_verbose_allowance_export(
                diagnostics,
                generated_at=generated_at,
                include_archived=include_archived,
                notes=notes,
            )
        )
    windows = diagnostics.get("windows", [])
    span_count = sum(
        len(window.get("spans", []))
        for window in windows
        if isinstance(window, dict)
    )
    selected_start_at = selection.rows[0].get("event_timestamp") if selection.rows else None
    selected_end_at = selection.rows[-1].get("event_timestamp") if selection.rows else None
    coverage = AllowanceExportCoverage(
        matched_observation_count=selection.matched_count,
        exported_observation_count=selection.exported_count,
        start_date=_date_bucket(selected_start_at),
        end_date=_date_bucket(selected_end_at),
        window_count=len(windows),
        span_count=span_count,
        truncated=selection.truncated,
    )
    plan_comparison = _plan_comparison_for_export(
        db_path,
        include_archived=include_archived,
        from_plan=from_plan,
        to_plan=to_plan,
    )
    return AllowanceReport(
        build_compact_allowance_export(
            diagnostics,
            generated_at=generated_at,
            include_archived=include_archived,
            window_kind=window_kind,
            requested_limit=limit,
            coverage=coverage,
            plan_comparison=plan_comparison,
            notes=notes,
        )
    )


def _plan_comparison_for_export(
    db_path: Path,
    *,
    include_archived: bool,
    from_plan: str | None,
    to_plan: str | None,
) -> dict[str, Any]:
    with connect(db_path) as connection:
        materialize_allowance_intelligence(connection)
        source = connection.execute(
            "SELECT source_revision FROM allowance_source_state WHERE state_id = 1"
        ).fetchone()
        source_revision = str(source[0]) if source else "missing"
        return build_plan_meter_comparison(
            connection,
            source_revision=source_revision,
            archive_scope="all" if include_archived else "active",
            window_kind="weekly",
            cohort_key="codex",
            from_plan=from_plan,
            to_plan=to_plan,
        )


def _annotated_observation_selection(
    *,
    db_path: Path,
    allowance_path: Path,
    rate_card_path: Path,
    include_archived: bool,
    window_kind: str | None,
    limit: int | None,
) -> tuple[AllowanceObservationSelection, list[dict[str, Any]]]:
    selection = query_allowance_observation_selection(
        db_path=db_path,
        include_archived=include_archived,
        window_kind=window_kind,
        limit=limit,
    )
    allowance = load_allowance_config(allowance_path, rate_card_path=rate_card_path)
    return selection, annotate_rows_with_allowance(selection.rows, allowance)


def _diagnostics_payload(
    rows: list[dict[str, Any]],
    *,
    generated_at: str,
    include_archived: bool,
    window_kind: str | None,
    privacy_mode: str,
) -> dict[str, Any]:
    analysis = build_allowance_analysis(rows)
    return {
        "schema": ALLOWANCE_DIAGNOSTICS_SCHEMA,
        "generated_at": generated_at,
        "privacy_mode": privacy_mode,
        "include_archived": include_archived,
        "window_kind": window_kind,
        **_privacy_filtered_analysis(analysis, privacy_mode=privacy_mode),
    }


def _history_row(row: dict[str, Any], *, privacy_mode: str) -> dict[str, Any]:
    payload = {
        "observed_at": row.get("event_timestamp"),
        "observed_date": _date_bucket(row.get("event_timestamp")),
        "source": row.get("source"),
        "window_key": row.get("window_key"),
        "window_kind": row.get("window_kind"),
        "window_minutes": row.get("window_minutes"),
        "used_percent": row.get("used_percent"),
        "remaining_percent": row.get("remaining_percent"),
        "resets_at": row.get("resets_at"),
        "plan_type": row.get("plan_type"),
        "limit_id": row.get("limit_id"),
        "model": row.get("model"),
        "effort": row.get("effort"),
        "total_tokens": row.get("total_tokens"),
        "usage_credits": row.get("usage_credits"),
        "usage_credit_confidence": row.get("usage_credit_confidence"),
    }
    if privacy_mode != "strict":
        payload["record_id"] = row.get("record_id")
        payload["session_id"] = row.get("session_id")
        payload["line_number"] = row.get("line_number")
    return payload


def _privacy_filtered_analysis(
    analysis: dict[str, Any], *, privacy_mode: str
) -> dict[str, Any]:
    return {
        "summary": analysis["summary"],
        "windows": [
            _privacy_filtered_window(window, privacy_mode=privacy_mode)
            for window in analysis["windows"]
        ],
        "spans": [
            _privacy_filtered_span(span, privacy_mode=privacy_mode)
            for span in analysis["spans"]
        ],
        "change_candidates": analysis["change_candidates"],
        "notes": [*analysis["notes"], *_privacy_notes()],
    }


def _privacy_filtered_window(
    window: dict[str, Any], *, privacy_mode: str
) -> dict[str, Any]:
    return {
        "window_kind": window.get("window_kind"),
        "plan_type": window.get("plan_type"),
        "limit_id": window.get("limit_id"),
        "observation_count": window.get("observation_count"),
        "positive_span_count": window.get("positive_span_count"),
        "evidence_grade": window.get("evidence_grade"),
        "span_stats": window.get("span_stats"),
        "change_candidates": window.get("change_candidates"),
        "spans": [
            _privacy_filtered_span(span, privacy_mode=privacy_mode)
            for span in window.get("spans", [])
        ],
    }


def _privacy_filtered_span(
    span: dict[str, Any], *, privacy_mode: str
) -> dict[str, Any]:
    payload = dict(span)
    payload["start_observed_date"] = _date_bucket(payload.get("start_observed_at"))
    payload["end_observed_date"] = _date_bucket(payload.get("end_observed_at"))
    if privacy_mode == "strict":
        payload.pop("record_id", None)
        payload.pop("start_observed_at", None)
        payload.pop("end_observed_at", None)
    return payload


def _validate_window_kind(window_kind: str | None) -> None:
    if window_kind is not None and window_kind not in WINDOW_KIND_CHOICES:
        allowed = ", ".join(WINDOW_KIND_CHOICES)
        raise ValueError(f"window_kind must be one of: {allowed}")


def _privacy_notes() -> list[str]:
    return [
        "Allowance intelligence uses aggregate token counters and observed usage percentages only.",
        "Strict privacy output omits prompts, assistant text, tool output, file paths, thread names, and record identifiers.",
    ]


def _render_history(payload: dict[str, Any]) -> str:
    return (
        "Allowance history: "
        f"{payload.get('row_count', 0)} normalized observations "
        f"({payload.get('privacy_mode')} privacy)."
    )


def _render_diagnostics(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        return "Allowance diagnostics unavailable."
    return (
        "Allowance diagnostics: "
        f"{summary.get('primary_evidence_grade')} across "
        f"{summary.get('observation_count', 0)} observations and "
        f"{summary.get('positive_span_count', 0)} positive spans."
    )


def _render_export(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    grade = summary.get("primary_evidence_grade") if isinstance(summary, dict) else None
    coverage = payload.get("coverage")
    if isinstance(coverage, dict):
        return (
            "Allowance evidence export ready with strict privacy "
            f"({grade}; {coverage.get('exported_observation_count', 0)} observations)."
        )
    return f"Allowance evidence export ready with strict privacy ({grade})."


def _generated_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _date_bucket(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:10]
