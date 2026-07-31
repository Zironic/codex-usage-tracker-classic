"""Compact and compatibility serializers for allowance evidence exports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

ALLOWANCE_EXPORT_COMPACT_SCHEMA = (
    "codex-usage-tracker-allowance-evidence-export-v2"
)
ALLOWANCE_EXPORT_VERBOSE_SCHEMA = (
    "codex-usage-tracker-allowance-evidence-export-v1"
)
ALLOWANCE_EXPORT_FORMATS = ("compact", "verbose")

SPAN_COLUMNS = (
    "start_observed_date",
    "end_observed_date",
    "start_used_percent",
    "end_used_percent",
    "estimated_usage_credits",
    "row_count",
)


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
) -> dict[str, object]:
    """Build the column-oriented v2 export intended for model analysis."""

    summary = diagnostics.get("summary")
    summary_mapping = summary if isinstance(summary, Mapping) else {}
    windows = _mapping_rows(diagnostics.get("windows"))
    return {
        "schema": ALLOWANCE_EXPORT_COMPACT_SCHEMA,
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
        "layout": {
            "span_columns": list(SPAN_COLUMNS),
            "conventions": {
                "null_end_observed_date": "same_as_start_observed_date",
                "delta_usage_percent": (
                    "end_used_percent - start_used_percent"
                ),
                "credits_per_percent": (
                    "estimated_usage_credits / delta_usage_percent"
                ),
                "confidence_override": (
                    "[zero_based_span_row_index, confidence]"
                ),
            },
        },
        "summary": {
            "primary_window_kind": summary_mapping.get(
                "primary_window_kind"
            ),
            "primary_evidence_grade": summary_mapping.get(
                "primary_evidence_grade"
            ),
            "candidate_change_count": summary_mapping.get(
                "candidate_change_count", 0
            ),
            "research_readiness": summary_mapping.get(
                "research_readiness", {}
            ),
        },
        "windows": [compact_window(window) for window in windows],
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


def compact_window(window: Mapping[str, object]) -> dict[str, object]:
    """Move invariant window facts out of individual span rows."""

    spans = _mapping_rows(window.get("spans"))
    span_rows, span_confidence = compact_span_rows(spans)
    candidates = [
        _compact_candidate(candidate)
        for candidate in _mapping_rows(window.get("change_candidates"))
    ]
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
    spans: Sequence[Mapping[str, object]],
) -> tuple[list[list[object]], dict[str, object]]:
    """Encode repeated span objects as one column declaration plus rows."""

    rows: list[list[object]] = []
    confidence_values: list[object] = []
    for span in spans:
        start_date = span.get("start_observed_date")
        end_date = span.get("end_observed_date")
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

    default = _confidence_default(confidence_values)
    overrides = [
        [index, confidence]
        for index, confidence in enumerate(confidence_values)
        if confidence != default
    ]
    return rows, {"default": default, "overrides": overrides}


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


def _compact_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    payload = {
        key: value
        for key, value in candidate.items()
        if key
        not in {
            "window_kind",
            "candidate_start_observed_at",
            "candidate_end_observed_at",
        }
    }
    payload["candidate_start_observed_date"] = _date_bucket(
        candidate.get("candidate_start_observed_at")
    )
    payload["candidate_end_observed_date"] = _date_bucket(
        candidate.get("candidate_end_observed_at")
    )
    return payload


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
