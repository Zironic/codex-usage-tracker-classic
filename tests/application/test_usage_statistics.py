from __future__ import annotations

from codex_usage_tracker.application import statistics
from codex_usage_tracker.application.statistics_models import StatisticsRequest
from codex_usage_tracker.store.usage_statistics_queries import UsageStatisticsSelection


def test_usage_statistics_calculates_distribution_rates_sessions_and_models(monkeypatch) -> None:
    rows = [
        _row("a", "2026-07-30T08:00:00Z", "gpt-sol", 10.0, "exact"),
        _row("b", "2026-07-30T08:10:00Z", "gpt-sol", 20.0, "exact"),
        _row("c", "2026-07-30T10:00:00Z", "gpt-luna", None, "unpriced"),
        _row("d", "2026-07-31T09:00:00Z", "gpt-luna", 30.0, "estimated"),
    ]
    monkeypatch.setattr(
        statistics,
        "query_usage_statistics_rows",
        lambda **_kwargs: UsageStatisticsSelection(
            rows=rows,
            data_state="ready",
            reason=None,
            source_generation=4,
            fact_generation=4,
            materialized_call_count=4,
        ),
    )

    payload = statistics.get_usage_statistics(
        StatisticsRequest(
            since="2026-07-30T00:00:00Z",
            until="2026-08-01T00:00:00Z",
            timezone="Europe/Stockholm",
            session_gap_minutes=30,
        )
    )

    assert payload["coverage"]["priced_call_count"] == 3
    assert payload["coverage"]["unpriced_call_count"] == 1
    assert payload["distribution"]["mean"] == 20.0
    assert payload["distribution"]["median"] == 20.0
    assert payload["time_rates"]["calendar_day_count"] == 2
    assert payload["sessions"]["count"] == 3
    assert payload["model_transitions"]["switch_count"] == 0
    assert [row["model"] for row in payload["model_rows"]] == ["gpt-sol", "gpt-luna"]
    assert len(payload["heatmap"]) == 168


def test_usage_statistics_returns_refresh_required_without_stale_values(monkeypatch) -> None:
    monkeypatch.setattr(
        statistics,
        "query_usage_statistics_rows",
        lambda **_kwargs: UsageStatisticsSelection(
            rows=[],
            data_state="refresh_required",
            reason="recommendation_facts_stale",
            source_generation=5,
            fact_generation=4,
            materialized_call_count=100,
        ),
    )

    payload = statistics.get_usage_statistics(
        StatisticsRequest(
            since="2026-07-01T00:00:00Z",
            until="2026-08-01T00:00:00Z",
            timezone="UTC",
        )
    )

    assert payload["data_state"] == "refresh_required"
    assert payload["reason"] == "recommendation_facts_stale"
    assert "headline" not in payload


def _row(record_id: str, timestamp: str, model: str, credits: float | None, confidence: str):
    return {
        "record_id": record_id,
        "event_timestamp": timestamp,
        "model": model,
        "effort": "medium",
        "total_tokens": 100,
        "usage_credits": credits,
        "usage_credit_confidence": confidence,
    }
