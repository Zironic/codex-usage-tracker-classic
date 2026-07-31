from __future__ import annotations

import json
from pathlib import Path

from codex_usage_tracker.allowance_intelligence import build_allowance_export_report
from codex_usage_tracker.allowance_intelligence.export_payload import (
    AllowanceExportCoverage,
    build_compact_allowance_export,
    build_verbose_allowance_export,
    compact_span_rows,
)
from codex_usage_tracker.store.api import upsert_usage_events
from tests.store_dashboard_helpers import _usage_event


def test_compact_span_rows_state_shared_scope_and_derived_fields_once() -> None:
    spans = [
        {
            "window_kind": "weekly",
            "plan_type": "pro",
            "limit_id": "codex",
            "start_observed_date": "2026-07-01",
            "end_observed_date": "2026-07-01",
            "start_used_percent": 10.0,
            "end_used_percent": 11.0,
            "delta_usage_percent": 1.0,
            "estimated_usage_credits": 250.0,
            "credits_per_percent": 250.0,
            "row_count": 2,
            "credit_confidence_mix": {"exact": 2},
        },
        {
            "window_kind": "weekly",
            "plan_type": "pro",
            "limit_id": "codex",
            "start_observed_date": "2026-07-01",
            "end_observed_date": "2026-07-02",
            "start_used_percent": 11.0,
            "end_used_percent": 13.0,
            "delta_usage_percent": 2.0,
            "estimated_usage_credits": 400.0,
            "credits_per_percent": 200.0,
            "row_count": 3,
            "credit_confidence_mix": {"estimated": 3},
        },
    ]

    rows, confidence = compact_span_rows(spans)

    assert rows == [
        ["2026-07-01", None, 10.0, 11.0, 250.0, 2],
        ["2026-07-01", "2026-07-02", 11.0, 13.0, 400.0, 3],
    ]
    assert confidence == {
        "default": "estimated",
        "overrides": [[0, "exact"]],
    }
    encoded = json.dumps(rows)
    assert "window_kind" not in encoded
    assert "delta_usage_percent" not in encoded
    assert "credits_per_percent" not in encoded


def test_compact_export_is_substantially_smaller_than_verbose_span_objects() -> None:
    spans = [
        {
            "window_kind": "weekly",
            "plan_type": "prolite",
            "limit_id": "codex",
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
    diagnostics = {
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
    compact = build_compact_allowance_export(
        diagnostics,
        generated_at="2026-07-31T00:00:00Z",
        include_archived=False,
        window_kind="weekly",
        requested_limit=None,
        coverage=AllowanceExportCoverage(
            matched_observation_count=1000,
            exported_observation_count=1000,
            start_date="2026-07-01",
            end_date="2026-07-31",
            window_count=1,
            span_count=len(spans),
            truncated=False,
        ),
        notes=[],
    )
    verbose = build_verbose_allowance_export(
        diagnostics,
        generated_at="2026-07-31T00:00:00Z",
        include_archived=False,
        notes=[],
    )

    compact_size = len(json.dumps(compact, separators=(",", ":")))
    verbose_size = len(json.dumps(verbose, separators=(",", ":")))
    assert compact_size <= verbose_size * 0.25


def test_compact_export_is_complete_and_strict(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.sqlite3"
    upsert_usage_events(
        [
            _usage_event(
                record_id="private-record-1",
                session_id="private-session",
                thread_key="thread:private",
                event_timestamp="2026-06-01T00:00:00Z",
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
                event_timestamp="2026-07-01T00:00:00Z",
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

    payload = build_allowance_export_report(
        db_path=db_path,
        export_format="compact",
    ).payload
    encoded = json.dumps(payload)

    assert payload["schema"] == "codex-usage-tracker-allowance-evidence-export-v2"
    assert payload["coverage"] == {
        "matched_observation_count": 2,
        "exported_observation_count": 2,
        "start_date": "2026-06-01",
        "end_date": "2026-07-01",
        "window_count": 1,
        "span_count": 1,
        "truncated": False,
    }
    assert "private-record" not in encoded
    assert "private-session" not in encoded
    assert "thread:private" not in encoded


def test_verbose_export_remains_available(tmp_path: Path) -> None:
    db_path = tmp_path / "usage.sqlite3"

    payload = build_allowance_export_report(
        db_path=db_path,
        export_format="verbose",
    ).payload

    assert payload["schema"] == "codex-usage-tracker-allowance-evidence-export-v1"
    assert "change_candidates" in payload
