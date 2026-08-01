from __future__ import annotations

from dataclasses import asdict

from codex_usage_tracker.application.agent import (
    AgentDispatcher,
    AgentError,
    AgentRequest,
    AgentResponse,
)


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def capabilities(self) -> dict[str, object]:
        self.calls.append(("capabilities", None))
        return {"schema": "codex-usage-tracker.agent-capabilities.v1", "operations": []}

    def schema(self, operation: str) -> dict[str, object]:
        self.calls.append(("schema", operation))
        return {"schema": "codex-usage-tracker.agent-schema.v1", "operation": operation}

    def status(self, request: object) -> dict[str, object]:
        self.calls.append(("status", request))
        return {
            "schema": "codex-usage-tracker.status.v2",
            "index": {"source_revision": "rev-1", "state": "fresh"},
        }

    def query(self, request: object) -> dict[str, object]:
        self.calls.append(("query", request))
        return {
            "schema": "codex-usage-tracker.query.v2",
            "rows": [],
            "next_cursor": None,
            "total_matched": 0,
        }

    def refresh(self, request: object) -> dict[str, object]:
        self.calls.append(("refresh", request))
        return {"schema": "codex-usage-tracker.refresh.v2", "source_revision": "rev-2"}

    def analyze(self, request: object) -> dict[str, object]:
        self.calls.append(("analyze", request))
        return {"schema": "codex-usage-tracker.analysis.v2", "source_revision": "rev-1"}

    def evidence(self, request: object) -> dict[str, object]:
        self.calls.append(("evidence", request))
        return {"schema": "codex-usage-tracker.evidence-result.v1", "records": []}

    def allowance(self, request: object) -> dict[str, object]:
        self.calls.append(("allowance", request))
        return {"schema": "codex-usage-tracker-allowance-status-v2", "rows": []}

    def job_status(self, request: object) -> dict[str, object]:
        self.calls.append(("job_status", request))
        return {"schema": "codex-usage-tracker.job.v1", "job_id": "job-1", "status": "queued"}

    def report(
        self, operation: str, arguments: dict[str, object], *, privacy_mode: str
    ) -> dict[str, object]:
        self.calls.append(("report", (operation, arguments, privacy_mode)))
        return {"schema": f"codex-usage-tracker.{operation}.v1", "rows": []}


def test_core_dispatch_preserves_inner_query_schema_and_metadata() -> None:
    services = FakeServices()
    dispatcher = AgentDispatcher(services)
    result = dispatcher.dispatch(
        AgentRequest(
            operation="usage.query",
            arguments={"entity": "thread", "measures": ["tokens"]},
            request_id="req-1",
            scope={"history": "all", "project": "demo"},
        )
    )
    assert isinstance(result, AgentResponse)
    assert result.operation == "usage.query"
    assert result.result_schema == "codex-usage-tracker.query.v2"
    assert result.result["schema"] == "codex-usage-tracker.query.v2"  # type: ignore[index]
    request = services.calls[-1][1]
    assert asdict(request)["history"] == "all"
    assert asdict(request)["filters"]["project"] == "demo"


def test_dispatch_maps_all_wired_core_operations() -> None:
    services = FakeServices()
    dispatcher = AgentDispatcher(services)
    requests = (
        AgentRequest(operation="meta.capabilities"),
        AgentRequest(operation="meta.schema", arguments={"operation": "usage.query"}),
        AgentRequest(operation="system.status"),
        AgentRequest(
            operation="refresh.start",
            arguments={"execution": "sync"},
        ),
        AgentRequest(operation="job.get", arguments={"job_id": "job-1"}),
        AgentRequest(
            operation="usage.query",
            arguments={"entity": "thread", "measures": ["tokens"]},
        ),
        AgentRequest(
            operation="analysis.run",
            arguments={"goal": "usage_spike", "execution": "sync"},
        ),
        AgentRequest(
            operation="evidence.get",
            arguments={"selector_kind": "call", "selector_id": "a" * 64},
        ),
        AgentRequest(operation="allowance.status"),
        AgentRequest(operation="allowance.series"),
        AgentRequest(operation="allowance.evidence"),
        AgentRequest(operation="allowance.analysis", arguments={"execution": "sync"}),
    )
    results = [dispatcher.dispatch(request) for request in requests]
    assert all(isinstance(result, AgentResponse) for result in results)
    assert {name for name, _ in services.calls} == {
        "capabilities",
        "schema",
        "status",
        "refresh",
        "job_status",
        "query",
        "analyze",
        "evidence",
        "allowance",
    }


def test_unknown_disabled_and_unauthorized_operations_are_errors() -> None:
    dispatcher = AgentDispatcher(FakeServices())
    unknown = dispatcher.dispatch(AgentRequest(operation="missing"))
    disabled = dispatcher.dispatch(AgentRequest(operation="artifact.get"))
    unauthorized = dispatcher.dispatch(
        AgentRequest(operation="usage.query"), authorized_scopes={"catalog_read"}
    )
    assert isinstance(unknown, AgentError) and unknown.code == "unknown_operation"
    assert isinstance(disabled, AgentError) and disabled.code == "operation_disabled"
    assert isinstance(unauthorized, AgentError)
    assert unauthorized.code == "authorization_scope_required"


def test_response_and_job_result_are_immutable_to_callers() -> None:
    services = FakeServices()
    result = AgentDispatcher(services).dispatch(AgentRequest(operation="job.get", arguments={"job_id": "job-1"}))
    assert isinstance(result, AgentResponse)
    payload = result.to_payload()
    payload["job"]["job_id"] = "changed"  # type: ignore[index]
    assert result.job["job_id"] == "job-1"  # type: ignore[index]


def test_information_report_dispatches_through_application_service() -> None:
    services = FakeServices()
    result = AgentDispatcher(services).dispatch(
        AgentRequest(
            operation="usage.recommendations",
            arguments={"limit": 5},
            privacy_mode="redacted",
        ),
        authorized_scopes={"aggregate_read"},
    )
    assert isinstance(result, AgentResponse)
    assert services.calls[-1] == (
        "report",
        ("usage.recommendations", {"limit": 5}, "redacted"),
    )


def test_sensitive_content_requires_scope_and_explicit_acknowledgement() -> None:
    dispatcher = AgentDispatcher(FakeServices())
    request = AgentRequest(operation="content.search", arguments={"query": "cache"})
    missing_scope = dispatcher.dispatch(request, authorized_scopes={"aggregate_read"})
    missing_ack = dispatcher.dispatch(request, authorized_scopes={"local_index_read"})
    accepted = dispatcher.dispatch(
        AgentRequest(
            operation="content.search",
            arguments={"query": "cache", "acknowledge_sensitive_content": True},
            privacy_mode="redacted",
        ),
        authorized_scopes={"local_index_read"},
    )
    assert isinstance(missing_scope, AgentError)
    assert missing_scope.code == "authorization_scope_required"
    assert isinstance(missing_ack, AgentError)
    assert missing_ack.code == "invalid_request"
    assert isinstance(accepted, AgentResponse)
