from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from codex_usage_tracker.server import statistics_route


def test_statistics_route_decodes_dashboard_request(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_statistics(request, *, db_path):
        captured["request"] = request
        captured["db_path"] = db_path
        return {
            "schema": "codex-usage-tracker.dashboard-statistics.v1",
            "data_state": "ready",
            "reason": None,
            "scope": {},
        }

    monkeypatch.setattr(statistics_route, "get_usage_statistics", fake_statistics)
    body = json.dumps({
        "since": "2026-07-01T00:00:00Z",
        "until": "2026-08-01T00:00:00Z",
        "timezone": "Europe/Stockholm",
        "history": "active",
        "session_gap_minutes": 30,
    }).encode()

    status, payload = statistics_route.statistics_response(
        method="POST",
        stream=BytesIO(body),
        content_length=str(len(body)),
        content_type="application/json",
        db_path=tmp_path / "usage.sqlite3",
    )

    assert status == 200
    assert payload["schema"] == "codex-usage-tracker.dashboard-statistics.v1"
    assert captured["request"].timezone == "Europe/Stockholm"
    assert captured["db_path"] == tmp_path / "usage.sqlite3"


def test_statistics_route_rejects_unknown_fields(tmp_path: Path) -> None:
    body = json.dumps({
        "since": "2026-07-01T00:00:00Z",
        "until": "2026-08-01T00:00:00Z",
        "timezone": "UTC",
        "surprise": True,
    }).encode()

    status, payload = statistics_route.statistics_response(
        method="POST",
        stream=BytesIO(body),
        content_length=str(len(body)),
        content_type="application/json",
        db_path=tmp_path / "usage.sqlite3",
    )

    assert status == 400
    assert payload["error"]["code"] == "invalid_request"
