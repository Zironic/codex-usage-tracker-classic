"""Strict HTTP adapter for the surface-neutral agent operation API.

The agent endpoint is intentionally a very small transport adapter.  It owns
HTTP decoding, request/response byte budgets, and the stable envelope, while
the application ``AgentDispatcher`` owns operation validation and semantics.
The service dependency is injectable so the adapter can be tested without a
database or another transport handler.
"""

from __future__ import annotations

import inspect
import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import BinaryIO, Protocol

from codex_usage_tracker.interfaces.http.serialization import (
    HttpRequestError,
    decode_json_object,
    read_bounded_body,
    serialize_http_payload,
)

AGENT_ROUTE = "/api/v2/agent"
AGENT_REQUEST_SCHEMA = "codex-usage-tracker.agent-request.v1"
AGENT_CAPABILITIES_SCHEMA = "codex-usage-tracker.agent-capabilities.v1"
AGENT_RESPONSE_SCHEMA = "codex-usage-tracker.agent-response.v1"
AGENT_ERROR_SCHEMA = "codex-usage-tracker.agent-error.v1"

# A body must be bounded before operation-specific metadata can be trusted.
# Catalog entries may further narrow this value after decoding.
AGENT_BODY_LIMIT = 512 * 1024
AGENT_CAPABILITIES_OUTPUT_LIMIT = 128 * 1024
AGENT_DEFAULT_OUTPUT_LIMIT = 256 * 1024

_TOP_LEVEL_FIELDS = {
    "schema",
    "operation",
    "request_id",
    "scope",
    "privacy_mode",
    "execution",
    "expected_source_revision",
    "arguments",
}
_SCOPE_FIELDS = {
    "history",
    "since",
    "until",
    "project",
    "thread_key",
    "model",
    "effort",
}
_MISSING = object()


class AgentHttpServices(Protocol):
    """Transport-neutral application seam used by :class:`HttpAgentFacade`."""

    def capabilities(self) -> object: ...

    def dispatch(self, payload: Mapping[str, object], **kwargs: object) -> object: ...


@dataclass(frozen=True)
class HttpAgentResponse:
    status: int
    payload: dict[str, object]
    headers: Mapping[str, str]


class HttpAgentFacade:
    """Decode one agent request and dispatch exactly one application operation."""

    def __init__(
        self,
        services: AgentHttpServices,
        *,
        server_instance_id: str | None = None,
        authorized_scopes: Sequence[str] = (
            "catalog_read",
            "aggregate_read",
            "aggregate_write",
            "analysis_read",
            "evidence_read",
            "allowance_read",
            "export",
        ),
    ) -> None:
        self.services = services
        self.server_instance_id = server_instance_id or "agent-http"
        self.authorized_scopes = tuple(str(scope) for scope in authorized_scopes)

    def handle(
        self,
        *,
        method: str,
        path: str,
        query: str = "",
        body: bytes = b"",
        content_type: str = "",
        authorized: bool = False,
    ) -> HttpAgentResponse:
        """Handle one already-buffered request body.

        ``query`` is intentionally ignored.  In particular, query-string
        credentials are not accepted by this route.  The argument remains in
        the signature so the server mixin has the same shape as the v2 mixin.
        """

        del query
        try:
            return self._handle(
                method.upper(),
                path,
                body,
                content_type,
                authorized,
            )
        except HttpRequestError as exc:
            return _error(exc.status, exc.code, exc.message)
        except Exception:
            # Application errors are converted to the safe generic envelope;
            # never echo request content or local paths from an exception.
            return _error(500, "internal_error", "Agent operation failed")

    def handle_stream(
        self,
        *,
        method: str,
        path: str,
        query: str = "",
        stream: BinaryIO,
        content_length: str | None,
        content_type: str,
        authorized: bool = False,
    ) -> HttpAgentResponse:
        """Read one bounded POST body before dispatching it."""

        try:
            body = (
                read_bounded_body(
                    stream,
                    content_length=content_length,
                    max_bytes=AGENT_BODY_LIMIT,
                )
                if method.upper() == "POST"
                else b""
            )
        except HttpRequestError as exc:
            return _error(exc.status, exc.code, exc.message)
        return self.handle(
            method=method,
            path=path,
            query=query,
            body=body,
            content_type=content_type,
            authorized=authorized,
        )

    def _handle(
        self,
        method: str,
        path: str,
        body: bytes,
        content_type: str,
        authorized: bool,
    ) -> HttpAgentResponse:
        if path != AGENT_ROUTE:
            return _error(404, "not_found", "Unknown API endpoint")
        if method not in {"GET", "POST"}:
            return _error(405, "method_not_allowed", "Method not allowed", {"Allow": "GET, POST"})
        if method == "GET":
            return self._capabilities()
        if not authorized:
            return _error(401, "unauthorized", "Valid local API token required")

        payload = decode_json_object(
            body,
            content_type=content_type,
            max_bytes=AGENT_BODY_LIMIT,
        )
        request = _decode_request(payload)
        descriptor = _operation_descriptor(self.services, request["operation"])
        if descriptor is _MISSING:
            return _error(
                404,
                "unknown_operation",
                f"Unknown agent operation: {request['operation']}",
                operation=request["operation"],
                request_id=request.get("request_id"),
            )
        _enforce_input_limit(descriptor, len(body))
        _enforce_argument_shape(descriptor, request["arguments"])

        result = _dispatch(self.services, request, self.authorized_scopes)
        payload_result = _result_payload(result)
        if _is_error_payload(payload_result):
            status = _error_status(result, payload_result)
            return HttpAgentResponse(status, payload_result, {})
        response = _success_payload(
            payload_result,
            operation=request["operation"],
            request_id=request.get("request_id"),
            server_instance_id=self.server_instance_id,
            catalog_revision=_catalog_revision(self.services),
        )
        output_limit = _output_limit(descriptor)
        _enforce_output_limit(response, output_limit)
        status = 202 if _is_async_response(response) else 200
        return HttpAgentResponse(status, response, {})

    def _capabilities(self) -> HttpAgentResponse:
        value = _capabilities_value(self.services)
        payload = _result_payload(value)
        if payload.get("schema") != AGENT_CAPABILITIES_SCHEMA:
            payload = {
                "schema": AGENT_CAPABILITIES_SCHEMA,
                "api_version": "2",
                "catalog_revision": _catalog_revision(self.services),
                "server_instance_id": self.server_instance_id,
                "operations": payload.get("operations", []),
            }
        payload["server_instance_id"] = self.server_instance_id
        payload["enabled_scopes"] = list(self.authorized_scopes)
        operations = payload.get("operations")
        if isinstance(operations, Sequence) and not isinstance(operations, (str, bytes)):
            effective_operations: list[object] = []
            for operation in operations:
                if not isinstance(operation, Mapping):
                    effective_operations.append(operation)
                    continue
                effective = dict(operation)
                required_scope = effective.get("authorization_scope")
                if (
                    isinstance(required_scope, str)
                    and required_scope not in self.authorized_scopes
                    and "*" not in self.authorized_scopes
                ):
                    effective["enabled"] = False
                    effective["default_enabled"] = False
                    effective["disabled_reason"] = (
                        f"Required server scope is not enabled: {required_scope}"
                    )
                effective_operations.append(effective)
            payload["operations"] = effective_operations
        _enforce_output_limit(payload, AGENT_CAPABILITIES_OUTPUT_LIMIT)
        return HttpAgentResponse(200, payload, {})


def _decode_request(payload: Mapping[str, object]) -> dict[str, object]:
    _reject_unknown(payload, _TOP_LEVEL_FIELDS)
    schema = payload.get("schema")
    operation = payload.get("operation")
    if schema != AGENT_REQUEST_SCHEMA:
        raise HttpRequestError(400, "invalid_request", "schema must be agent-request.v1")
    if not isinstance(operation, str) or not operation or len(operation) > 128:
        raise HttpRequestError(400, "invalid_request", "operation must be a non-empty string")

    request_id = payload.get("request_id")
    if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 256):
        raise HttpRequestError(400, "invalid_request", "request_id must be a string of at most 256 bytes")

    scope = payload.get("scope", {})
    if not isinstance(scope, Mapping):
        raise HttpRequestError(400, "invalid_request", "scope must be an object")
    _reject_unknown(scope, _SCOPE_FIELDS, prefix="scope.")
    arguments = payload.get("arguments", {})
    if not isinstance(arguments, Mapping):
        raise HttpRequestError(400, "invalid_request", "arguments must be an object")

    privacy_mode = payload.get("privacy_mode", "normal")
    execution = payload.get("execution", "auto")
    expected_revision = payload.get("expected_source_revision")
    if not isinstance(privacy_mode, str) or not isinstance(execution, str):
        raise HttpRequestError(400, "invalid_request", "privacy_mode and execution must be strings")
    if expected_revision is not None and not isinstance(expected_revision, str):
        raise HttpRequestError(400, "invalid_request", "expected_source_revision must be a string")
    return {
        "schema": schema,
        "operation": operation,
        "request_id": request_id,
        "scope": dict(scope),
        "privacy_mode": privacy_mode,
        "execution": execution,
        "expected_source_revision": expected_revision,
        "arguments": dict(arguments),
    }


def _dispatch(
    services: AgentHttpServices,
    request: Mapping[str, object],
    authorized_scopes: Sequence[str],
) -> object:
    """Call either the typed dispatcher or the mapping test seam."""

    typed_request: object = dict(request)
    try:
        from codex_usage_tracker.application.agent import (  # type: ignore[import-not-found]
            AgentRequest,
        )

        typed_request = AgentRequest(**dict(request))
    except (ImportError, TypeError):
        pass

    dispatch = services.dispatch
    try:
        signature = inspect.signature(dispatch)
    except (TypeError, ValueError):
        signature = None
    if signature is not None and "authorized_scopes" in signature.parameters:
        return dispatch(typed_request, authorized_scopes=tuple(authorized_scopes))  # type: ignore[arg-type]
    return dispatch(typed_request)  # type: ignore[arg-type]


def _result_payload(value: object) -> dict[str, object]:
    if hasattr(value, "to_payload") and callable(value.to_payload):
        value = value.to_payload()
    try:
        payload = serialize_http_payload(value)
    except (TypeError, ValueError) as exc:
        raise HttpRequestError(500, "invalid_result", "Agent operation returned an invalid result") from exc
    try:
        _reject_nonfinite(payload)
    except ValueError as exc:
        raise HttpRequestError(500, "invalid_result", "Agent operation returned non-finite JSON") from exc
    return payload


def _success_payload(
    payload: Mapping[str, object],
    *,
    operation: str,
    request_id: object,
    server_instance_id: str,
    catalog_revision: str,
) -> dict[str, object]:
    if payload.get("schema") == AGENT_RESPONSE_SCHEMA:
        result = dict(payload)
        result.setdefault("operation", operation)
        if not result.get("request_id"):
            result["request_id"] = request_id or _request_id()
        result["server_instance_id"] = server_instance_id
        result.setdefault("catalog_revision", catalog_revision)
        return result
    # Keep application result schemas intact inside the stable envelope.
    return {
        "schema": AGENT_RESPONSE_SCHEMA,
        "operation": operation,
        "request_id": request_id or _request_id(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "server_instance_id": server_instance_id,
        "catalog_revision": catalog_revision,
        "data_class": "aggregate",
        "result_schema": payload.get("schema"),
        "source_revision": payload.get("source_revision"),
        "freshness": {},
        "scope": {},
        "privacy": {
            "mode": "normal",
            "includes_indexed_content": False,
            "includes_raw_fragments": False,
            "redaction_applied": False,
        },
        "result": dict(payload),
        "job": payload if payload.get("schema") == "codex-usage-tracker.job.v1" else None,
        "pagination": {"next_cursor": None, "total_matched": None, "truncated": False},
        "warnings": [],
        "limitations": [],
        "next_operations": [],
    }


def _is_error_payload(payload: Mapping[str, object]) -> bool:
    return payload.get("schema") == AGENT_ERROR_SCHEMA or "error" in payload and payload.get("schema") != AGENT_RESPONSE_SCHEMA


def _error_status(value: object, payload: Mapping[str, object]) -> int:
    status = getattr(value, "status", None)
    if isinstance(status, int) and 400 <= status <= 599:
        return status
    error = payload.get("error")
    if isinstance(error, Mapping):
        candidate = error.get("status")
        if isinstance(candidate, int) and 400 <= candidate <= 599:
            return candidate
        code = error.get("code")
        if code in {"unauthorized", "authentication_required"}:
            return 401
        if code in {"authorization_scope_required", "operation_disabled", "forbidden"}:
            return 403
        if code in {"unknown_operation", "not_found", "job_not_found", "evidence_not_found"}:
            return 404
        if code in {"stale_source_revision", "cursor_conflict", "idempotency_conflict"}:
            return 409
        if code in {"capability_unavailable", "sensitive_scope_disabled"}:
            return 422
        if code in {"rate_limited", "concurrency_limit"}:
            return 429
        if code in {"service_unavailable", "starting", "stopping"}:
            return 503
    return 400


def _is_async_response(payload: Mapping[str, object]) -> bool:
    if payload.get("job") is not None:
        return True
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return False
    if result.get("schema") == "codex-usage-tracker.job.v1":
        return True
    return (
        payload.get("operation") == "compression.start"
        and result.get("status") in {"pending", "running"}
    )


def _operation_descriptor(services: AgentHttpServices, operation: str) -> object:
    try:
        catalog = _result_payload(_capabilities_value(services))
    except Exception:
        return _MISSING
    operations = catalog.get("operations")
    if not isinstance(operations, Sequence) or isinstance(operations, (str, bytes)):
        return _MISSING
    for item in operations:
        if isinstance(item, Mapping) and item.get("name") == operation:
            if item.get("enabled", True) is False:
                return item
            return item
    return _MISSING


def _enforce_input_limit(descriptor: object, length: int) -> None:
    if not isinstance(descriptor, Mapping):
        return
    limit = descriptor.get("input_limit_bytes")
    if isinstance(limit, int) and limit > 0 and length > limit:
        raise HttpRequestError(413, "request_too_large", "request body exceeds the operation limit")


def _enforce_argument_shape(descriptor: object, arguments: Mapping[str, object]) -> None:
    if not isinstance(descriptor, Mapping):
        return
    allowed = descriptor.get("argument_fields", descriptor.get("arguments"))
    if isinstance(allowed, Sequence) and not isinstance(allowed, (str, bytes)):
        _reject_unknown(arguments, {str(item) for item in allowed}, prefix="arguments.")


def _output_limit(descriptor: object) -> int:
    if isinstance(descriptor, Mapping):
        value = descriptor.get("output_limit_bytes")
        if isinstance(value, int) and value > 0:
            return value
    return AGENT_DEFAULT_OUTPUT_LIMIT


def _enforce_output_limit(payload: Mapping[str, object], limit: int) -> None:
    _reject_nonfinite(payload)
    try:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise HttpRequestError(500, "invalid_result", "Agent response is not finite JSON") from exc
    if len(encoded) > limit:
        raise HttpRequestError(413, "response_too_large", "response exceeds the operation limit")


def _reject_nonfinite(value: object) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_nonfinite(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _reject_nonfinite(item)


def _catalog_revision(services: AgentHttpServices) -> str:
    try:
        value = _result_payload(_capabilities_value(services)).get("catalog_revision")
    except Exception:
        value = None
    return value if isinstance(value, str) and value else "sha256:unknown"


def _capabilities_value(services: AgentHttpServices) -> object:
    method = getattr(services, "capabilities", None)
    if callable(method):
        return method()
    nested = getattr(services, "services", None)
    method = getattr(nested, "capabilities", None)
    if callable(method):
        return method()
    try:
        from codex_usage_tracker.application.agent.catalog import capabilities_payload

        return capabilities_payload()
    except (ImportError, AttributeError):
        return {"schema": AGENT_CAPABILITIES_SCHEMA, "operations": []}


def _request_id() -> str:
    return f"agent-{uuid.uuid4().hex}"


def _reject_unknown(payload: Mapping[str, object], allowed: set[str], *, prefix: str = "") -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HttpRequestError(400, "invalid_request", f"unsupported field: {prefix}{unknown[0]}")


def _error(
    status: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
    *,
    operation: object = None,
    request_id: object = None,
) -> HttpAgentResponse:
    return HttpAgentResponse(
        status,
        {
            "schema": AGENT_ERROR_SCHEMA,
            "operation": operation,
            "request_id": request_id,
            "error": {
                "code": code,
                "message": message,
                "retryable": status in {409, 429, 500, 503},
                "remediation": None,
            },
        },
        headers or {},
    )
