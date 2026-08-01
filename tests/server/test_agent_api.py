from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from codex_usage_tracker.server.agent_route_inventory import AGENT_ROUTE_PROFILES
from codex_usage_tracker.server.api import _UsageDashboardHandler
from codex_usage_tracker.server.routes import GET_ROUTE_METHODS, POST_ROUTE_METHODS
from tests.application.test_query import _seed
from tests.store_dashboard_helpers import _http_error_json, _read_json


@contextmanager
def _agent_server(tmp_path: Path) -> Iterator[str]:
    handler = partial(
        _UsageDashboardHandler,
        directory=str(tmp_path),
        db_path=tmp_path / "usage.sqlite3",
        pricing_path=tmp_path / "pricing.json",
        allowance_path=tmp_path / "allowance.json",
        thresholds_path=tmp_path / "thresholds.json",
        projects_path=tmp_path / "projects.json",
        limit=100,
        since=None,
        codex_home=tmp_path / ".codex",
        include_archived=False,
        dashboard_name="dashboard.html",
        context_chars=2000,
        api_token="test-token",
        refresh_lock=threading.Lock(),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _workspace_tmp() -> Path:
    path = Path(".agent/tmp/http-agent-test")
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_agent_route_tables_and_inventory_are_stable() -> None:
    assert GET_ROUTE_METHODS["/api/v2/agent"] == "_handle_http_agent"
    assert POST_ROUTE_METHODS["/api/v2/agent"] == "_handle_http_agent"
    assert {(item.method, item.path) for item in AGENT_ROUTE_PROFILES} == {
        ("GET", "/api/v2/agent"),
        ("POST", "/api/v2/agent"),
    }
    assert all(item.exposure == "stable" for item in AGENT_ROUTE_PROFILES)
    assert all(item.output_limit_bytes for item in AGENT_ROUTE_PROFILES)


def test_live_agent_get_is_aggregate_free_and_origin_guard_uses_agent_error() -> None:
    tmp_path = _workspace_tmp()
    with _agent_server(tmp_path) as base_url:
        capabilities = _read_json(f"{base_url}/api/v2/agent")
        rejected = _http_error_json(
            f"{base_url}/api/v2/agent",
            headers={"Origin": "https://example.invalid"},
        )

    assert capabilities["schema"] == "codex-usage-tracker.agent-capabilities.v1"
    assert "result" not in capabilities
    assert "rows" not in capabilities
    content_context = next(
        item for item in capabilities["operations"] if item["name"] == "content.call_context"
    )
    assert content_context["enabled"] is False
    assert "raw_context_read" not in capabilities["enabled_scopes"]
    assert rejected["status"] == 403
    assert rejected["payload"]["schema"] == "codex-usage-tracker.agent-error.v1"  # type: ignore[index]


def test_live_agent_post_requires_header_token_and_rejects_query_token() -> None:
    tmp_path = _workspace_tmp()
    body = json.dumps(
        {
            "schema": "codex-usage-tracker.agent-request.v1",
            "operation": "system.status",
            "arguments": {},
        }
    ).encode()
    with _agent_server(tmp_path) as base_url:
        for suffix in ("", "?api_token=test-token"):
            request = urllib.request.Request(
                f"{base_url}/api/v2/agent{suffix}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(request, timeout=5)  # noqa: S310 - local test server only
            except urllib.error.HTTPError as exc:
                with exc:
                    payload = json.loads(exc.read())
                    assert exc.code == 401
                    assert payload["schema"] == "codex-usage-tracker.agent-error.v1"
                    assert payload["error"]["code"] == "unauthorized"
            else:
                raise AssertionError("expected HTTPError")


def test_live_agent_post_dispatches_real_status_service() -> None:
    tmp_path = _workspace_tmp()
    body = json.dumps(
        {
            "schema": "codex-usage-tracker.agent-request.v1",
            "operation": "system.status",
            "request_id": "live-status",
            "arguments": {},
        }
    ).encode()
    with _agent_server(tmp_path) as base_url:
        request = urllib.request.Request(
            f"{base_url}/api/v2/agent",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Codex-Usage-Token": "test-token",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            payload = json.loads(response.read())

    assert payload["schema"] == "codex-usage-tracker.agent-response.v1"
    assert payload["operation"] == "system.status"
    assert payload["request_id"] == "live-status"
    assert payload["result_schema"] == "codex-usage-tracker.status.v2"
    assert payload["result"]["schema"] == "codex-usage-tracker.status.v2"


def test_live_agent_post_queries_synthetic_usage_through_real_service() -> None:
    tmp_path = _workspace_tmp()
    _seed(tmp_path / "usage.sqlite3")
    body = json.dumps(
        {
            "schema": "codex-usage-tracker.agent-request.v1",
            "operation": "usage.query",
            "arguments": {
                "entity": "thread",
                "measures": ["tokens", "call_count"],
                "limit": 10,
            },
        }
    ).encode()
    with _agent_server(tmp_path) as base_url:
        request = urllib.request.Request(
            f"{base_url}/api/v2/agent",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Codex-Usage-Token": "test-token",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            payload = json.loads(response.read())

    assert payload["schema"] == "codex-usage-tracker.agent-response.v1"
    assert payload["result_schema"] == "codex-usage-tracker.query.v2"
    assert payload["result"]["total_matched"] == 2
    assert sum(row["call_count"] for row in payload["result"]["rows"]) == 2
