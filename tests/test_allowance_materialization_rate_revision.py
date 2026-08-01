from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from codex_usage_tracker.pricing.allowance_config import load_allowance_config
from codex_usage_tracker.store import allowance_materialization
from codex_usage_tracker.store.api import connect, upsert_usage_events
from tests.store_dashboard_helpers import _usage_event


def test_materialization_reprices_unchanged_observations_when_rate_card_changes(
    tmp_path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "usage.sqlite3"
    events = [
        replace(
            _usage_event(
                record_id="anchor",
                session_id="session",
                thread_key="thread:rates",
                event_timestamp="2026-07-31T23:58:00Z",
                cumulative_total_tokens=1_000_000,
                rate_limit_plan_type="prolite",
                rate_limit_limit_id="codex",
                rate_limit_primary_used_percent=10.0,
                rate_limit_primary_window_minutes=10080,
                rate_limit_primary_resets_at=2_000_000_000,
            ),
            model="gpt-5.6-luna",
            input_tokens=1_000_000,
            cached_input_tokens=0,
            uncached_input_tokens=1_000_000,
            output_tokens=0,
            total_tokens=1_000_000,
        ),
        replace(
            _usage_event(
                record_id="end",
                session_id="session",
                thread_key="thread:rates",
                event_timestamp="2026-07-31T23:59:00Z",
                cumulative_total_tokens=2_000_000,
                rate_limit_plan_type="prolite",
                rate_limit_limit_id="codex",
                rate_limit_primary_used_percent=11.0,
                rate_limit_primary_window_minutes=10080,
                rate_limit_primary_resets_at=2_000_000_000,
            ),
            model="gpt-5.6-luna",
            input_tokens=1_000_000,
            cached_input_tokens=0,
            uncached_input_tokens=1_000_000,
            output_tokens=0,
            total_tokens=1_000_000,
        ),
    ]
    upsert_usage_events(events, db_path)

    base = load_allowance_config(
        path=tmp_path / "missing-allowance.json",
        rate_card_path=tmp_path / "missing-rate-card.json",
    )
    old_rates = {**base.credit_rates, "gpt-5.6-luna": _rates(50.0)}
    new_rates = {**base.credit_rates, "gpt-5.6-luna": _rates(5.0)}
    current = [replace(base, credit_rates=old_rates, rate_revisions=())]
    monkeypatch.setattr(allowance_materialization, "load_allowance_config", lambda: current[0])

    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    with connect(db_path) as connection:
        assert allowance_materialization.materialize_allowance_intelligence(
            connection,
            now=now,
        )
        before = connection.execute(
            "SELECT estimated_credits FROM allowance_intervals "
            "WHERE point_kind = 'positive'"
        ).fetchone()[0]
        assert before == 50.0

        current[0] = replace(base, credit_rates=new_rates, rate_revisions=())
        assert allowance_materialization.materialize_allowance_intelligence(
            connection,
            now=now,
        )
        after = connection.execute(
            "SELECT estimated_credits FROM allowance_intervals "
            "WHERE point_kind = 'positive'"
        ).fetchone()[0]
        generation = connection.execute(
            "SELECT allowance_generation FROM allowance_source_state WHERE state_id = 1"
        ).fetchone()[0]

    assert after == 5.0
    assert generation == 2


def _rates(input_rate: float) -> dict[str, float]:
    return {
        "input_per_million": input_rate,
        "cached_input_per_million": input_rate / 10,
        "output_per_million": input_rate * 6,
    }
