from __future__ import annotations

import json
from io import BytesIO

import pytest

from codex_usage_tracker.interfaces.http.agent import (
    AGENT_CAPABILITIES_SCHEMA,
    AGENT_ERROR_SCHEMA,
    AGENT_REQUEST_SCHEMA,
    HttpAgentFacade,
)


def _capabilities(*, output_limit: int = 256 * 1024) -> dict[str, object]:
    return {
        "schema": AGENT_CAPABILITIES_SCHEMA,
        "api_version": "2",
        "catalog_revision": "sha256:test",
        "operations": [
            {
                "name": "usage.query",
                "enabled": True,
                "input_limit_bytes": 32 * 1024,
                "output_limit_bytes": output_limit,
            },
            {
                "name": "job.get",
                "enabled": True,
                "input_limit_bytes": 32 * 1024,
                "output_limit_bytes": output_limit,
            },
        ],
    }


class FakeServices:
    def __init__(self, result: object | None = None) -> None:
        self.result = result or {"schema": "codex-usage-tracker.query.v2", "rows": []}
        self.calls: list[object] = []

    def capabilities(self) -> dict[str, object]:
        return _capabilities()

    def dispatch(self, request: object, **kwargs: object) -> object:
        self.calls.append((request, kwargs))
        return self.result


def _request(
    facade: HttpAgentFacade,
    method: str,
    payload: dict[str, object] | None = None,
    *,
    path: str = "/api/v2/agent",
    authorized: bool = True,
    content_type: str = "application/json",
):
    body = b"" if payload is None else json.dumps(payload).encode()
    return facade.handle(
        method=method,
        path=path,
        body=body,
        content_type=content_type,
        authorized=authorized,
    )


def _payload(*, operation: str = "usage.query", arguments: dict[str, object] | None = None):
    return {
        "schema": AGENT_REQUEST_SCHEMA,
        "operation": operation,
        "arguments": {} if arguments is None else arguments,
    }


def test_get_returns_catalog_without_usage_data() -> None:
    response = _request(HttpAgentFacade(FakeServices()), "GET", authorized=False)

    assert response.status == 200
    assert response.payload["schema"] == AGENT_CAPABILITIES_SCHEMA
    assert "result" not in response.payload
    assert "rows" not in response.payload


def test_get_reports_effective_server_scopes_and_disables_unavailable_operations() -> None:
    services = FakeServices()
    services.capabilities = lambda: {
        **_capabilities(),
        "operations": [
            {
                "name": "content.call_context",
                "enabled": True,
                "authorization_scope": "raw_context_read",
                "input_limit_bytes": 1024,
                "output_limit_bytes": 1024,
            }
        ],
    }
    response = _request(
        HttpAgentFacade(services, authorized_scopes=("aggregate_read",)),
        "GET",
        authorized=False,
    )

    assert response.payload["enabled_scopes"] == ["aggregate_read"]
    operation = response.payload["operations"][0]  # type: ignore[index]
    assert operation["enabled"] is False
    assert "raw_context_read" in operation["disabled_reason"]


def test_post_dispatches_one_operation_and_wraps_result() -> None:
    services = FakeServices()
    response = _request(HttpAgentFacade(services), "POST", _payload())

    assert response.status == 200
    assert response.payload["schema"] == "codex-usage-tracker.agent-response.v1"
    assert response.payload["operation"] == "usage.query"
    assert response.payload["result_schema"] == "codex-usage-tracker.query.v2"
    assert len(services.calls) == 1


def test_job_results_are_accepted_asynchronous_work() -> None:
    response = _request(
        HttpAgentFacade(
            FakeServices({"schema": "codex-usage-tracker.job.v1", "job_id": "job-1"})
        ),
        "POST",
        _payload(),
    )

    assert response.status == 202
    assert response.payload["job"]["job_id"] == "job-1"  # type: ignore[index]


def test_compression_start_active_result_returns_accepted() -> None:
    services = FakeServices(
        {
            "schema": "codex-usage-tracker.agent-response.v1",
            "operation": "compression.start",
            "result": {"status": "running", "run_id": "run-1"},
        }
    )
    services.capabilities = lambda: {
        **_capabilities(),
        "operations": [
            {
                "name": "compression.start",
                "enabled": True,
                "input_limit_bytes": 32 * 1024,
                "output_limit_bytes": 256 * 1024,
            }
        ],
    }
    response = _request(
        HttpAgentFacade(services),
        "POST",
        _payload(operation="compression.start"),
    )

    assert response.status == 202


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("GET", "/api/v2/other", 404, "not_found"),
        ("PUT", "/api/v2/agent", 405, "method_not_allowed"),
        ("POST", "/api/v2/agent", 401, "unauthorized"),
    ],
)
def test_route_method_path_and_auth_guards(
    method: str, path: str, status: int, code: str
) -> None:
    response = _request(
        HttpAgentFacade(FakeServices()),
        method,
        _payload() if method == "POST" else None,
        path=path,
        authorized=False,
    )

    assert response.status == status
    assert response.payload["schema"] == AGENT_ERROR_SCHEMA
    assert response.payload["error"]["code"] == code  # type: ignore[index]


@pytest.mark.parametrize(
    "body",
    [
        b'{"schema":"codex-usage-tracker.agent-request.v1","operation":"usage.query","operation":"usage.query"}',
        b'{"schema":"codex-usage-tracker.agent-request.v1","operation":"usage.query","arguments":{"n":NaN}}',
    ],
)
def test_duplicate_and_nonfinite_json_are_rejected(body: bytes) -> None:
    response = HttpAgentFacade(FakeServices()).handle(
        method="POST",
        path="/api/v2/agent",
        body=body,
        content_type="application/json",
        authorized=True,
    )

    assert response.status == 400
    assert response.payload["error"]["code"] == "invalid_json"  # type: ignore[index]


def test_unknown_top_level_and_wrong_media_type_are_rejected() -> None:
    unknown = _request(
        HttpAgentFacade(FakeServices()),
        "POST",
        {**_payload(), "surprise": True},
    )
    media = _request(
        HttpAgentFacade(FakeServices()),
        "POST",
        _payload(),
        content_type="text/plain",
    )

    assert unknown.status == 400
    assert unknown.payload["error"]["code"] == "invalid_request"  # type: ignore[index]
    assert media.status == 415


def test_stream_guard_requires_declared_length_and_enforces_limit() -> None:
    facade = HttpAgentFacade(FakeServices())
    missing = facade.handle_stream(
        method="POST",
        path="/api/v2/agent",
        stream=BytesIO(b"{}"),
        content_length=None,
        content_type="application/json",
        authorized=True,
    )
    oversized = facade.handle_stream(
        method="POST",
        path="/api/v2/agent",
        stream=BytesIO(b"x" * (512 * 1024 + 1)),
        content_length=str(512 * 1024 + 1),
        content_type="application/json",
        authorized=True,
    )

    assert missing.status == 411
    assert oversized.status == 413


def test_nonfinite_result_is_rejected_and_output_budget_is_enforced() -> None:
    nonfinite = _request(
        HttpAgentFacade(FakeServices({"schema": "x.v1", "value": float("nan")})),
        "POST",
        _payload(),
    )
    services = FakeServices({"schema": "x.v1", "value": "x" * 200})
    facade = HttpAgentFacade(services)
    facade.services.capabilities = lambda: {
        **_capabilities(output_limit=32),
        "operations": [
            {
                "name": "usage.query",
                "enabled": True,
                "input_limit_bytes": 32 * 1024,
                "output_limit_bytes": 32,
            }
        ],
    }
    too_large = _request(facade, "POST", _payload())

    assert nonfinite.status == 500
    assert nonfinite.payload["error"]["code"] == "invalid_result"  # type: ignore[index]
    assert too_large.status == 413
    assert too_large.payload["error"]["code"] == "response_too_large"  # type: ignore[index]
