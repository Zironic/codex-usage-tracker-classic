"""Compact and compatibility serializers for allowance evidence exports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

ALLOWANCE_EXPORT_COMPACT_SCHEMA = "codex-usage-tracker-allowance-evidence-export-v3"
ALLOWANCE_EXPORT_COMPACT_V2_SCHEMA = "codex-usage-tracker-allowance-evidence-export-v2"
ALLOWANCE_EXPORT_VERBOSE_SCHEMA = "codex-usage-tracker-allowance-evidence-export-v1"
ALLOWANCE_EXPORT_FORMATS = ("compact", "compact-v2", "verbose")

SPAN_COLUMNS = (
    "start_minute",
    "end_minute",
    "start_used_percent",
    "end_used_percent",
    "estimated_usage_credits",
    "row_count",
)
SPAN_COLUMNS_V2 = (
    "start_observed_date",
    "end_observed_date",
    "start_used_percent",
    "end_used_percent",
    "estimated_usage_credits",
    "row_count",
)

_FORBIDDEN_COMPARISON_KEYS = {
    "cycle_id",
    "cycle_ids",
    "record_id",
    "record_ids",
    "session_id",
    "session_ids",
    "snapshot_id",
    "source_revision",
    "thread_key",
    "path",
}


@dataclass(frozen=True)
class AllowanceExportCoverage:
    """Completeness metadata for one allowance export."""

    matched_observation_count: int
    exported_observation_count: int
    start_date: str | None
    end_date: str | None
    window_count: int
    span_count: int
    truncated: bool


def build_compact_allowance_export(
    diagnostics: Mapping[str, object],
    *,
    generated_at: str,
    include_archived: bool,
    window_kind: str | None,
    requested_limit: int | None,
    coverage: AllowanceExportCoverage,
    notes: Sequence[str],
    time_origin: str | None,
    plan_comparison: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the minute-resolution column-oriented v3 export."""

    normalized_origin = normalize_time_origin(time_origin)
    payload = _compact_payload_base(
        diagnostics,
        schema=ALLOWANCE_EXPORT_COMPACT_SCHEMA,
        generated_at=generated_at,
        include_archived=include_archived,
        window_kind=window_kind,
        requested_limit=requested_limit,
        coverage=coverage,
        layout={
            "time_origin": normalized_origin,
            "time_unit": "minute",
            "timestamp_precision": "minute_floor",
            "span_columns": list(SPAN_COLUMNS),
            "conventions": {
                "minute_offset": (
                    "integer UTC minutes from layout.time_origin after flooring each "
                    "timestamp to its minute"
                ),
                "null_end_minute": "same_as_start_minute",
                "delta_usage_percent": "end_used_percent - start_used_percent",
                "credits_per_percent": "estimated_usage_credits / delta_usage_percent",
                "confidence_override": "[zero_based_span_row_index, confidence]",
                "after_to_before_ratio": (
                    "after median completed-cycle credits_per_percent divided by "
                    "before median completed-cycle credits_per_percent"
                ),
            },
        },
        windows=[
            compact_window(window, time_origin=normalized_origin)
            for window in _mapping_rows(diagnostics.get("windows"))
        ],
        notes=notes,
    )
    if plan_comparison:
        payload["plan_comparison"] = compact_plan_comparison(plan_comparison)
    return payload


def build_compact_allowance_export_v2(
    diagnostics: Mapping[str, object],
    *,
    generated_at: str,
    include_archived: bool,
    window_kind: str | None,
    requested_limit: int | None,
    coverage: AllowanceExportCoverage,
    notes: Sequence[str],
    plan_comparison: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the historical date-only column-oriented v2 export."""

    payload = _compact_payload_base(
        diagnostics,
        schema=ALLOWANCE_EXPORT_COMPACT_V2_SCHEMA,
        generated_at=generated_at,
        include_archived=include_archived,
        window_kind=window_kind,
        requested_limit=requested_limit,
        coverage=coverage,
        layout={
            "span_columns": list(SPAN_COLUMNS_V2),
            "conventions": {
                "null_end_observed_date": "same_as_start_observed_date",
                "delta_usage_percent": "end_used_percent - start_used_percent",
                "credits_per_percent": "estimated_usage_credits / delta_usage_percent",
                "confidence_override": "[zero_based_span_row_index, confidence]",
                "after_to_before_ratio": (
                    "after median completed-cycle credits_per_percent divided by "
                    "before median completed-cycle credits_per_percent"
                ),
            },
        },
        windows=[
            compact_window_v2(window)
            for window in _mapping_rows(diagnostics.get("windows"))
        ],
        notes=notes,
    )
    if plan_comparison:
        payload["plan_comparison"] = compact_plan_comparison(plan_comparison)
    return payload


def _compact_payload_base(
    diagnostics: Mapping[str, object],
    *,
    schema: str,
    generated_at: str,
    include_archived: bool,
    window_kind: str | None,
    requested_limit: int | None,
    coverage: AllowanceExportCoverage,
    layout: Mapping[str, object],
    windows: list[dict[str, object]],
    notes: Sequence[str],
) -> dict[str, object]:
    summary = diagnostics.get("summary")
    summary_mapping = summary if isinstance(summary, Mapping) else {}
    return {
        "schema": schema,
        "generated_at": generated_at,
        "privacy_mode": "strict",
        "request": {
            "window_kind": window_kind,
            "include_archived": include_archived,
            "limit": requested_limit,
        },
        "coverage": {
            "matched_observation_count": coverage.matched_observation_count,
            "exported_observation_count": coverage.exported_observation_count,
            "start_date": coverage.start_date,
            "end_date": coverage.end_date,
            "window_count": coverage.window_count,
            "span_count": coverage.span_count,
            "truncated": coverage.truncated,
        },
        "layout": dict(layout),
        "summary": {
            "primary_window_kind": summary_mapping.get("primary_window_kind"),
            "primary_evidence_grade": summary_mapping.get("primary_evidence_grade"),
            "candidate_change_count": summary_mapping.get("candidate_change_count", 0),
            "research_readiness": summary_mapping.get("research_readiness", {}),
        },
        "windows": windows,
        "notes": list(notes),
    }


def build_verbose_allowance_export(
    diagnostics: Mapping[str, object],
    *,
    generated_at: str,
    include_archived: bool,
    notes: Sequence[str],
) -> dict[str, object]:
    """Build the historical object-per-span v1 export."""

    return {
        "schema": ALLOWANCE_EXPORT_VERBOSE_SCHEMA,
        "generated_at": generated_at,
        "privacy_mode": "strict",
        "include_archived": include_archived,
        "summary": diagnostics.get("summary", {}),
        "windows": [
            _verbose_window(window)
            for window in _mapping_rows(diagnostics.get("windows"))
        ],
        "change_candidates": diagnostics.get("change_candidates", []),
        "notes": list(notes),
    }


def compact_window(
    window: Mapping[str, object], *, time_origin: str | None
) -> dict[str, object]:
    """Move invariant window facts out of v3 minute-offset span rows."""

    spans = _mapping_rows(window.get("spans"))
    span_rows, span_confidence = compact_span_rows(spans, time_origin=time_origin)
    candidates = [
        _compact_candidate(candidate, time_origin=time_origin)
        for candidate in _mapping_rows(window.get("change_candidates"))
    ]
    return _compact_window_payload(window, span_rows, span_confidence, candidates)


def compact_window_v2(window: Mapping[str, object]) -> dict[str, object]:
    """Move invariant window facts out of v2 date-only span rows."""

    spans = _mapping_rows(window.get("spans"))
    span_rows, span_confidence = compact_span_rows_v2(spans)
    candidates = [
        _compact_candidate_v2(candidate)
        for candidate in _mapping_rows(window.get("change_candidates"))
    ]
    return _compact_window_payload(window, span_rows, span_confidence, candidates)


def _compact_window_payload(
    window: Mapping[str, object],
    span_rows: list[list[object]],
    span_confidence: dict[str, object],
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "scope": {
            "window_kind": window.get("window_kind"),
            "plan_type": window.get("plan_type"),
            "limit_id": window.get("limit_id"),
        },
        "observation_count": window.get("observation_count", 0),
        "positive_span_count": window.get("positive_span_count", 0),
        "evidence_grade": window.get("evidence_grade"),
        "span_stats": window.get("span_stats", {}),
        "span_rows": span_rows,
        "span_confidence": span_confidence,
        "change_candidates": candidates,
    }


def compact_span_rows(
    spans: Sequence[Mapping[str, object]], *, time_origin: str | None
) -> tuple[list[list[object]], dict[str, object]]:
    """Encode exact internal span timestamps as minute offsets for v3."""

    rows: list[list[object]] = []
    confidence_values: list[object] = []
    for span in spans:
        start_minute = minute_offset(span.get("start_observed_at"), time_origin)
        end_minute = minute_offset(span.get("end_observed_at"), time_origin)
        rows.append(
            [
                start_minute,
                None if end_minute == start_minute else end_minute,
                span.get("start_used_percent"),
                span.get("end_used_percent"),
                span.get("estimated_usage_credits"),
                span.get("row_count", 0),
            ]
        )
        confidence_values.append(_normalized_confidence(span))
    return rows, _compact_confidence(confidence_values)


def compact_span_rows_v2(
    spans: Sequence[Mapping[str, object]],
) -> tuple[list[list[object]], dict[str, object]]:
    """Encode date-only spans using the historical v2 layout."""

    rows: list[list[object]] = []
    confidence_values: list[object] = []
    for span in spans:
        start_date = span.get("start_observed_date") or _date_bucket(
            span.get("start_observed_at")
        )
        end_date = span.get("end_observed_date") or _date_bucket(
            span.get("end_observed_at")
        )
        rows.append(
            [
                start_date,
                None if end_date == start_date else end_date,
                span.get("start_used_percent"),
                span.get("end_used_percent"),
                span.get("estimated_usage_credits"),
                span.get("row_count", 0),
            ]
        )
        confidence_values.append(_normalized_confidence(span))
    return rows, _compact_confidence(confidence_values)


def _compact_confidence(values: Sequence[object]) -> dict[str, object]:
    default = _confidence_default(values)
    overrides = [
        [index, confidence]
        for index, confidence in enumerate(values)
        if confidence != default
    ]
    return {"default": default, "overrides": overrides}


def compact_plan_comparison(
    comparison: Mapping[str, object],
) -> dict[str, object]:
    """Strip local identifiers while preserving aggregate plan evidence."""

    sanitized = _sanitize_comparison_value(comparison)
    return dict(sanitized) if isinstance(sanitized, Mapping) else {}


def _sanitize_comparison_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_comparison_value(item)
            for key, item in value.items()
            if not _forbidden_comparison_key(str(key))
        }
    if isinstance(value, list | tuple):
        return [_sanitize_comparison_value(item) for item in value]
    return value


def _forbidden_comparison_key(key: str) -> bool:
    return (
        key in _FORBIDDEN_COMPARISON_KEYS
        or key.endswith("_cycle_id")
        or key.endswith("_record_id")
        or key.endswith("_session_id")
    )


def _confidence_default(values: Sequence[object]) -> str | None:
    labels = [value for value in values if isinstance(value, str)]
    if not labels:
        return None
    counts = Counter(labels)
    maximum = max(counts.values())
    return min(label for label, count in counts.items() if count == maximum)


def _normalized_confidence(span: Mapping[str, object]) -> object:
    raw_mix = span.get("credit_confidence_mix")
    if not isinstance(raw_mix, Mapping):
        return {}
    mix = {
        str(label): int(count)
        for label, count in sorted(raw_mix.items(), key=lambda item: str(item[0]))
        if isinstance(count, int)
    }
    row_count = span.get("row_count")
    if len(mix) == 1:
        label, count = next(iter(mix.items()))
        if isinstance(row_count, int) and count == row_count:
            return label
    return mix


def _compact_candidate(
    candidate: Mapping[str, object], *, time_origin: str | None
) -> dict[str, object]:
    payload = _candidate_without_time_fields(candidate)
    payload["candidate_start_minute"] = minute_offset(
        candidate.get("candidate_start_observed_at"), time_origin
    )
    payload["candidate_end_minute"] = minute_offset(
        candidate.get("candidate_end_observed_at"), time_origin
    )
    return payload


def _compact_candidate_v2(candidate: Mapping[str, object]) -> dict[str, object]:
    payload = _candidate_without_time_fields(candidate)
    payload["candidate_start_observed_date"] = _date_bucket(
        candidate.get("candidate_start_observed_at")
    )
    payload["candidate_end_observed_date"] = _date_bucket(
        candidate.get("candidate_end_observed_at")
    )
    return payload


def _candidate_without_time_fields(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): value
        for key, value in candidate.items()
        if key
        not in {
            "window_kind",
            "candidate_start_observed_at",
            "candidate_end_observed_at",
        }
    }


def normalize_time_origin(value: object) -> str | None:
    """Normalize one timestamp to a UTC minute ISO origin."""

    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    floored = parsed.replace(second=0, microsecond=0)
    return floored.isoformat().replace("+00:00", "Z")


def minute_offset(value: object, time_origin: object) -> int | None:
    """Return a floored UTC-minute offset from the export-wide origin."""

    timestamp = _parse_timestamp(value)
    origin = _parse_timestamp(time_origin)
    if timestamp is None or origin is None:
        return None
    timestamp = timestamp.replace(second=0, microsecond=0)
    origin = origin.replace(second=0, microsecond=0)
    return int((timestamp - origin).total_seconds() // 60)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _verbose_window(window: Mapping[str, object]) -> dict[str, object]:
    allowed_span_fields = {
        "window_kind",
        "plan_type",
        "limit_id",
        "start_observed_date",
        "end_observed_date",
        "start_used_percent",
        "end_used_percent",
        "delta_usage_percent",
        "estimated_usage_credits",
        "credits_per_percent",
        "row_count",
        "credit_confidence_mix",
    }
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
            {
                key: value
                for key, value in span.items()
                if key in allowed_span_fields
            }
            for span in _mapping_rows(window.get("spans"))
        ],
    }


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _date_bucket(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:10]
