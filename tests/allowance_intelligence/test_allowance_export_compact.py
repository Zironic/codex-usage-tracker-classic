from __future__ import annotations

import json
from pathlib import Path

from codex_usage_tracker.allowance_intelligence import build_allowance_export_report
from codex_usage_tracker.allowance_intelligence.export_payload import (
    AllowanceExportCoverage,
    build_compact_allowance_export,
    build_compact_allowance_export_v2,
    build_verbose_allowance_export,
    compact_span_rows,
    compact_span_rows_v2,
)
from codex_usage_tracker.store.api import upsert_usage_events
from tests.store_dashboard_helpers import _usage_event


def test_compact_span_rows_encode_utc_minute_offsets() -> None:
    spans = [
        {
            "start_observed_at": "2026-07-01T10:00:45Z",
            "end_observed_at": "2026-07-01T10:00:59Z",
            "start_used_percent": 10.0,
            "end_used_percent": 11.0,
            "estimated_usage_credits": 250.0,
            "row_count": 2,
            "credit_confidence_mix": {"exact": 2},
        },
        {
            "start_observed_at": "2026-07-01T12:01:00+02:00",
            "end_observed_at": "2026-07-01T10:02:59Z",
            "start_used_percent": 11.0,
            "end_used_percent": 13.0,
            "estimated_usage_credits": 400.0,
            "row_count": 3,
            "credit_confidence_mix": {"estimated": 3},
        },
    ]

    rows, confidence = compact_span_rows(
        spans,
        time_origin="2026-07-01T10:00:30Z",
    )

    assert rows == [
        [0, None, 10.0, 11.0, 250.0, 2],
        [1, 2, 11.0, 13.0, 400.0, 3],
    ]
    assert confidence == {
        "default": "estimated",
        "overrides": [[0, "exact"]],
    }


def test_compact_v2_span_rows_preserve_date_layout() -> None:
    spans = [
        {
            "start_observed_at": "2026-07-01T23:59:00Z",
            "end_observed_at": "2026-07-02T00:01:00Z",
            "start_used_percent": 10.0,
            "end_used_percent": 11.0,
            "estimated_usage_credits": 250.0,
            "row_count": 2,
            "credit_confidence_mix": {"exact": 2},
        }
    ]

    rows, confidence = compact_span_rows_v2(spans)

    assert rows == [["2026-07-01", "2026-07-02", 10.0, 11.0, 250.0, 2]]
    assert confidence == {"default": "exact", "overrides": []}


def test_compact_v3_is_substantially_smaller_than_verbose_span_objects() -> None:
    spans = [
        {
            "window_kind": "weekly",
            "plan_type": "prolite",
            "limit_id": "codex",
            "start_observed_at": f"2026-07-28T{index // 60:02d}:{index % 60:02d}:00Z",
            "end_observed_at": f"2026-07-28T{index // 60:02d}:{index % 60:02d}:30Z",
            "start_observed_date": "2026-07-28",
            "end_observed_date": "2026-07-28",
            "start_used_percent": float(index),
            "end_used_percent": float(index + 1),
            "delta_usage_percent": 1.0,
            "estimated_usage_credits": 250.0 + index,
            "credits_per_percent": 250.0 + index,
            "row_count": 62,
            "credit_confidence_mix": {"exact": 62},
        }
        for index in range(200)
    ]
    diagnostics = _diagnostics_with_spans(spans)
    compact = build_compact_allowance_export(
        diagnostics,
        generated_at="2026-07-31T00:00:00Z",
        include_archived=False,
        window_kind="weekly",
        requested_limit=None,
        coverage=_coverage(span_count=len(spans), observation_count=1000),
        notes=[],
        time_origin="2026-07-28T00:00:00Z",
    )
    verbose = build_verbose_allowance_export(
        diagnostics,
        generated_at="2026-07-31T00:00:00Z",
        include_archived=False,
        notes=[],
    )

    compact_size = len(json.dumps(compact, separators=(",", ":")))
    verbose_size = len(json.dumps(verbose, separators=(",", ":")))
    assert compact_size <= verbose_size * 0.30


def test_compact_v3_export_is_complete_minute_resolved_and_strict(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.sqlite3"
    upsert_usage_events(
        [
            _usage_event(
                record_id="private-record-1",
                session_id="private-session",
                thread_key="thread:private",
                event_timestamp="2026-06-01T00:00:30Z",
                cumulative_total_tokens=100,
                rate_limit_plan_type="pro",
                rate_limit_limit_id="codex",
                rate_limit_primary_used_percent=10.0,
                rate_limit_primary_window_minutes=10080,
                rate_limit_primary_resets_at=1000,
            ),
            _usage_event(
                record_id="private-record-2",
                session_id="private-session",
                thread_key="thread:private",
                event_timestamp="2026-06-01T00:01:45Z",
                cumulative_total_tokens=200,
                rate_limit_plan_type="pro",
                rate_limit_limit_id="codex",
                rate_limit_primary_used_percent=11.0,
                rate_limit_primary_window_minutes=10080,
                rate_limit_primary_resets_at=1000,
            ),
        ],
        db_path=db_path,
    )

    payload = build_allowance_export_report(db_path=db_path).payload
    encoded = json.dumps(payload)

    assert payload["schema"] == "codex-usage-tracker-allowance-evidence-export-v3"
    assert payload["coverage"] == {
        "matched_observation_count": 2,
        "exported_observation_count": 2,
        "start_date": "2026-06-01",
        "end_date": "2026-06-01",
        "window_count": 1,
        "span_count": 1,
        "truncated": False,
    }
    assert payload["layout"]["time_origin"] == "2026-06-01T00:00:00Z"
    assert payload["layout"]["time_unit"] == "minute"
    assert payload["windows"][0]["span_rows"][0][:2] == [0, 1]
    assert "plan_comparison" not in payload
    assert "private-record" not in encoded
    assert "private-session" not in encoded
    assert "thread:private" not in encoded
    assert "2026-06-01T00:00:30Z" not in encoded
    assert "2026-06-01T00:01:45Z" not in encoded


def test_compact_v2_export_remains_available(tmp_path: Path) -> None:
    payload = build_allowance_export_report(
        db_path=tmp_path / "usage.sqlite3",
        export_format="compact-v2",
    ).payload

    assert payload["schema"] == "codex-usage-tracker-allowance-evidence-export-v2"
    assert "time_origin" not in payload["layout"]


def test_empty_compact_v3_export_has_null_origin(tmp_path: Path) -> None:
    payload = build_allowance_export_report(db_path=tmp_path / "usage.sqlite3").payload

    assert payload["schema"] == "codex-usage-tracker-allowance-evidence-export-v3"
    assert payload["layout"]["time_origin"] is None
    assert payload["coverage"]["span_count"] == 0


def test_compact_export_includes_sanitized_requested_plan_comparison() -> None:
    diagnostics = _diagnostics_with_spans([])
    payload = build_compact_allowance_export(
        diagnostics,
        generated_at="2026-07-31T00:00:00Z",
        include_archived=False,
        window_kind="weekly",
        requested_limit=None,
        coverage=_coverage(span_count=0, observation_count=0),
        notes=[],
        time_origin=None,
        plan_comparison={
            "status": "ready",
            "sample_count": 4,
            "session_ids": ["private-session"],
        },
    )

    assert payload["plan_comparison"] == {"status": "ready", "sample_count": 4}


def test_v2_builder_keeps_v2_schema() -> None:
    payload = build_compact_allowance_export_v2(
        _diagnostics_with_spans([]),
        generated_at="2026-07-31T00:00:00Z",
        include_archived=False,
        window_kind="weekly",
        requested_limit=None,
        coverage=_coverage(span_count=0, observation_count=0),
        notes=[],
    )

    assert payload["schema"] == "codex-usage-tracker-allowance-evidence-export-v2"


def test_verbose_export_remains_available(tmp_path: Path) -> None:
    payload = build_allowance_export_report(
        db_path=tmp_path / "usage.sqlite3",
        export_format="verbose",
    ).payload

    assert payload["schema"] == "codex-usage-tracker-allowance-evidence-export-v1"
    assert "change_candidates" in payload


def _diagnostics_with_spans(spans: list[dict[str, object]]) -> dict[str, object]:
    return {
        "summary": {
            "primary_window_kind": "weekly",
            "primary_evidence_grade": "no_change_detected",
            "candidate_change_count": 0,
            "research_readiness": {},
        },
        "windows": [
            {
                "window_kind": "weekly",
                "plan_type": "prolite",
                "limit_id": "codex",
                "observation_count": 1000,
                "positive_span_count": len(spans),
                "evidence_grade": "no_change_detected",
                "span_stats": {},
                "change_candidates": [],
                "spans": spans,
            }
        ],
        "change_candidates": [],
    }


def _coverage(*, span_count: int, observation_count: int) -> AllowanceExportCoverage:
    return AllowanceExportCoverage(
        matched_observation_count=observation_count,
        exported_observation_count=observation_count,
        start_date=None,
        end_date=None,
        window_count=1,
        span_count=span_count,
        truncated=False,
    )
