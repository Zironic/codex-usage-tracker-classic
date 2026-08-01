from __future__ import annotations

from codex_usage_tracker.application import statistics
from codex_usage_tracker.application.statistics_models import StatisticsRequest
from codex_usage_tracker.store.usage_statistics_queries import UsageStatisticsSelection


def test_usage_statistics_calculates_distribution_rates_sessions_and_models(monkeypatch) -> None:
    rows = [
        _row(
            "a",
            "2026-07-30T08:00:00Z",
            "gpt-sol",
            10.0,
            "exact",
            input_tokens=100,
            cached_input_tokens=80,
            uncached_input_tokens=20,
            output_tokens=10,
            reasoning_output_tokens=4,
            total_tokens=110,
            context_window_percent=0.5,
        ),
        _row(
            "b",
            "2026-07-30T08:10:00Z",
            "gpt-sol",
            20.0,
            "exact",
            input_tokens=200,
            cached_input_tokens=100,
            uncached_input_tokens=100,
            output_tokens=20,
            reasoning_output_tokens=10,
            total_tokens=220,
            context_window_percent=0.7,
        ),
        _row("c", "2026-07-30T10:00:00Z", "gpt-luna", None, "unpriced"),
        _row("d", "2026-07-31T09:00:00Z", "gpt-luna", 30.0, "estimated"),
    ]
    monkeypatch.setattr(
        statistics,
        "query_usage_statistics_rows",
        lambda **_kwargs: _selection(rows),
    )
    monkeypatch.setattr(statistics, "_rate_revisions", lambda: ())

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

    sol = payload["model_rows"][0]
    assert sol["call_share"] == 0.5
    assert sol["credit_share"] == 0.5
    assert sol["avg_total_tokens_per_call"] == 165.0
    assert sol["avg_input_tokens_per_call"] == 150.0
    assert sol["avg_cached_input_tokens_per_call"] == 90.0
    assert sol["avg_uncached_input_tokens_per_call"] == 60.0
    assert sol["avg_output_tokens_per_call"] == 15.0
    assert sol["avg_reasoning_tokens_per_call"] == 7.0
    assert sol["weighted_cache_ratio"] == 0.6
    assert sol["output_ratio"] == 0.090909
    assert sol["reasoning_output_ratio"] == 0.466667
    assert sol["average_context_window_percent"] == 0.6

    hourly = payload["hourly_series"]
    assert hourly["granularity"] == "hour"
    assert hourly["timezone"] == "Europe/Stockholm"
    assert len(hourly["points"]) == 48
    assert hourly["points"][8]["calls"] == 2
    assert hourly["points"][9]["calls"] == 0
    assert hourly["points"][10]["calls"] == 1


def test_active_time_turns_cohorts_breakdowns_and_attribution(monkeypatch) -> None:
    rows = [
        _row(
            "a",
            "2026-07-30T08:02:00Z",
            "gpt-sol",
            10.0,
            "exact",
            session_id="session-1",
            turn_id="turn-1",
            turn_timestamp="2026-07-30T08:00:00Z",
            cwd="C:/work/Tracker",
            thread_name="Statistics work",
            plan="Plus",
        ),
        _row(
            "b",
            "2026-07-30T08:05:00Z",
            "gpt-sol",
            5.0,
            "exact",
            session_id="session-1",
            turn_id="turn-1",
            turn_timestamp="2026-07-30T08:00:00Z",
            previous_call_event_timestamp="2026-07-30T08:02:00Z",
            previous_call_session_id="session-1",
            previous_call_turn_id="turn-1",
            cwd="C:/work/Tracker",
            thread_name="Statistics work",
            plan="Plus",
            parent_session_id="parent-1",
            subagent_type="worker",
        ),
        _row(
            "c",
            "2026-07-30T08:20:00Z",
            "gpt-luna",
            15.0,
            "exact",
            session_id="session-1",
            turn_id="turn-2",
            turn_timestamp="2026-07-30T08:18:00Z",
            previous_call_event_timestamp="2026-07-30T08:05:00Z",
            previous_call_session_id="session-1",
            previous_call_turn_id="turn-1",
            cwd="C:/work/Tracker",
            thread_name="Statistics work",
            plan="Prolite",
            effort="high",
            fast=True,
        ),
    ]
    monkeypatch.setattr(
        statistics,
        "query_usage_statistics_rows",
        lambda **_kwargs: _selection(rows),
    )
    monkeypatch.setattr(statistics, "_rate_revisions", lambda: ())

    payload = statistics.get_usage_statistics(
        StatisticsRequest(
            since="2026-07-30T08:00:00Z",
            until="2026-07-30T09:00:00Z",
            timezone="UTC",
            session_gap_minutes=30,
            active_gap_cap_minutes=5,
            comparison_at="2026-07-30T08:10:00Z",
        )
    )

    assert payload["activity"]["estimated_active_seconds"] == 720.0
    assert payload["activity"]["measured_call_duration_seconds"] == 420.0
    assert payload["activity"]["capped_inter_call_gap_seconds"] == 300.0
    assert payload["activity"]["distinct_turns"] == 2
    assert payload["activity"]["calls_per_turn"] == 1.5
    assert payload["activity"]["subagent_calls_per_turn"] == 0.5
    assert payload["headline"]["calls_per_active_hour"] == 15.0
    assert payload["headline"]["credits_per_active_hour"] == 150.0
    assert payload["sessions"]["count"] == 1
    assert payload["sessions"]["duration_distribution"]["median"] == 1200.0
    assert payload["turns"]["rows"][0]["turn_group"] in {0, 1}
    assert "session-1" not in str(payload["turns"]["rows"])

    plan_rows = payload["cohorts"]["plan_rate_rows"]
    assert [row["plan"] for row in plan_rows] == ["Plus", "Prolite"]
    assert len(payload["cohorts"]["breakpoint_rows"]) == 2
    assert payload["breakdowns"]["initiator_kind"][0]["label"] == "User/direct"
    assert payload["breakdowns"]["fast_mode"][0]["label"] in {"Standard", "Fast"}
    assert payload["attribution"]["projects"][0]["label"] == "Tracker"
    assert payload["attribution"]["threads"][0]["thread"] == "Statistics work"


def test_model_labels_normalize_whitespace_and_keep_unpriced_credit_metrics_unknown(
    monkeypatch,
) -> None:
    rows = [_row("a", "2026-07-30T08:00:00Z", "   ", None, "unpriced")]
    monkeypatch.setattr(
        statistics,
        "query_usage_statistics_rows",
        lambda **_kwargs: _selection(rows),
    )
    monkeypatch.setattr(statistics, "_rate_revisions", lambda: ())

    payload = statistics.get_usage_statistics(
        StatisticsRequest(
            since="2026-07-30T00:00:00Z",
            until="2026-07-31T00:00:00Z",
            timezone="UTC",
        )
    )

    model = payload["model_rows"][0]
    assert model["model"] == "Unknown model"
    assert model["known_credits"] == 0
    assert model["mean"] is None
    assert model["credit_share"] is None
    assert model["priced_call_ratio"] == 0


def test_hourly_series_preserves_dst_skips_and_repeated_hours(monkeypatch) -> None:
    monkeypatch.setattr(
        statistics,
        "query_usage_statistics_rows",
        lambda **_kwargs: _selection([]),
    )
    monkeypatch.setattr(statistics, "_rate_revisions", lambda: ())

    spring = statistics.get_usage_statistics(
        StatisticsRequest(
            since="2026-03-28T23:00:00Z",
            until="2026-03-29T22:00:00Z",
            timezone="Europe/Stockholm",
        )
    )
    spring_points = spring["hourly_series"]["points"]
    assert len(spring_points) == 23
    assert not any(
        str(point["local_period_start"]).startswith("2026-03-29T02:00")
        for point in spring_points
    )

    autumn = statistics.get_usage_statistics(
        StatisticsRequest(
            since="2026-10-24T22:00:00Z",
            until="2026-10-25T23:00:00Z",
            timezone="Europe/Stockholm",
        )
    )
    autumn_points = autumn["hourly_series"]["points"]
    repeated = [
        point
        for point in autumn_points
        if str(point["local_period_start"]).startswith("2026-10-25T02:00")
    ]
    assert len(autumn_points) == 25
    assert len(repeated) == 2
    assert repeated[0]["local_period_start"] != repeated[1]["local_period_start"]


def test_hourly_series_is_omitted_for_long_ranges(monkeypatch) -> None:
    monkeypatch.setattr(
        statistics,
        "query_usage_statistics_rows",
        lambda **_kwargs: _selection([]),
    )
    monkeypatch.setattr(statistics, "_rate_revisions", lambda: ())

    payload = statistics.get_usage_statistics(
        StatisticsRequest(
            since="2026-05-01T00:00:00Z",
            until="2026-08-01T00:00:00Z",
            timezone="UTC",
        )
    )

    assert payload["series"]["granularity"] == "day"
    assert payload["hourly_series"] is None


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


def _selection(rows):
    return UsageStatisticsSelection(
        rows=rows,
        data_state="ready",
        reason=None,
        source_generation=4,
        fact_generation=4,
        materialized_call_count=len(rows),
    )


def _row(
    record_id: str,
    timestamp: str,
    model: str,
    credits: float | None,
    confidence: str,
    *,
    input_tokens: int = 100,
    cached_input_tokens: int = 50,
    uncached_input_tokens: int = 50,
    output_tokens: int = 10,
    reasoning_output_tokens: int = 5,
    total_tokens: int = 110,
    context_window_percent: float = 0.5,
    session_id: str | None = None,
    turn_id: str | None = None,
    turn_timestamp: str | None = None,
    previous_call_event_timestamp: str | None = None,
    previous_call_session_id: str | None = None,
    previous_call_turn_id: str | None = None,
    cwd: str | None = None,
    thread_name: str | None = None,
    plan: str | None = None,
    effort: str = "medium",
    fast: bool | None = False,
    parent_session_id: str | None = None,
    subagent_type: str | None = None,
):
    return {
        "record_id": record_id,
        "event_timestamp": timestamp,
        "model": model,
        "effort": effort,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": total_tokens,
        "context_window_percent": context_window_percent,
        "usage_credits": credits,
        "usage_credit_confidence": confidence,
        "session_id": session_id,
        "turn_id": turn_id,
        "turn_timestamp": turn_timestamp,
        "previous_call_event_timestamp": previous_call_event_timestamp,
        "previous_call_session_id": previous_call_session_id,
        "previous_call_turn_id": previous_call_turn_id,
        "cwd": cwd,
        "thread_name": thread_name,
        "call_initiator": "user",
        "rate_limit_plan_type": plan,
        "service_tier": "priority" if fast else "standard",
        "fast": fast,
        "thread_source": "subagent" if subagent_type else "session",
        "subagent_type": subagent_type,
        "parent_session_id": parent_session_id,
    }
