from __future__ import annotations

from pathlib import Path

import pytest

from codex_usage_tracker.pricing.allowance_config import load_allowance_config
from codex_usage_tracker.pricing.allowance_rate_history import parse_rate_revisions
from codex_usage_tracker.pricing.allowance_usage import annotate_rows_with_allowance


def test_bundled_rates_switch_at_timestamped_revision(tmp_path: Path) -> None:
    config = load_allowance_config(
        path=tmp_path / "missing-allowance.json",
        rate_card_path=tmp_path / "missing-rate-card.json",
    )
    rows = [
        _usage_row("gpt-5.6-luna", "2026-07-31T23:59:59Z"),
        _usage_row("gpt-5.6-luna", "2026-08-01T00:00:00Z"),
    ]

    before, after = annotate_rows_with_allowance(rows, config)

    assert before["usage_credits"] == pytest.approx(50.0)
    assert before["usage_credit_rate_revision"] == "2026-07-09-bundled-baseline"
    assert before["usage_credit_rate_effective_at"] is None
    assert after["usage_credits"] == pytest.approx(5.0)
    assert after["usage_credit_rate_revision"] == "2026-08-01-official-rate-card"
    assert after["usage_credit_rate_effective_at"] == "2026-08-01T00:00:00Z"
    assert after["usage_credit_rate_effective_at_precision"] == "day"


def test_aliases_use_historical_target_rate(tmp_path: Path) -> None:
    config = load_allowance_config(
        path=tmp_path / "missing-allowance.json",
        rate_card_path=tmp_path / "missing-rate-card.json",
    )
    before, after = annotate_rows_with_allowance(
        [
            _usage_row("gpt-5.6", "2026-07-31T12:00:00Z"),
            _usage_row("gpt-5.6", "2026-08-01T12:00:00Z"),
        ],
        config,
    )

    assert before["usage_credit_model"] == "gpt-5.6-sol"
    assert before["usage_credits"] == pytest.approx(250.0)
    assert after["usage_credit_model"] == "gpt-5.6-sol"
    assert after["usage_credits"] == pytest.approx(125.0)


def test_missing_timestamp_uses_current_top_level_rate(tmp_path: Path) -> None:
    config = load_allowance_config(
        path=tmp_path / "missing-allowance.json",
        rate_card_path=tmp_path / "missing-rate-card.json",
    )
    row = _usage_row("gpt-5.6-terra", None)

    annotated = annotate_rows_with_allowance([row], config)[0]

    assert annotated["usage_credits"] == pytest.approx(50.0)
    assert annotated["usage_credit_rate_revision"] is None


def test_rate_revisions_reject_non_increasing_timestamps() -> None:
    raw = [
        {
            "revision_id": "later",
            "effective_at": "2026-08-02T00:00:00Z",
            "credit_rates": {"model": _rates(2.0)},
        },
        {
            "revision_id": "earlier",
            "effective_at": "2026-08-01T00:00:00Z",
            "credit_rates": {"model": _rates(1.0)},
        },
    ]

    with pytest.raises(ValueError, match="strictly increasing"):
        parse_rate_revisions(raw, default_source={})


def _usage_row(model: str, timestamp: str | None) -> dict[str, object]:
    return {
        "model": model,
        "event_timestamp": timestamp,
        "input_tokens": 1_000_000,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 1_000_000,
        "output_tokens": 0,
        "total_tokens": 1_000_000,
    }


def _rates(input_rate: float) -> dict[str, float]:
    return {
        "input_per_million": input_rate,
        "cached_input_per_million": input_rate / 10,
        "output_per_million": input_rate * 6,
    }
