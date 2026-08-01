"""Transport-neutral request, response, and error contracts for the agent API.

The HTTP adapter is deliberately not imported here.  These contracts are small
JSON-facing values that can be used by any local transport while retaining the
application services' result schemas inside ``result``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import cast

from codex_usage_tracker.core.contracts.common import immutable_snapshot
from codex_usage_tracker.core.contracts.serialization import payload_mapping

AGENT_REQUEST_SCHEMA = "codex-usage-tracker.agent-request.v1"
AGENT_RESPONSE_SCHEMA = "codex-usage-tracker.agent-response.v1"
AGENT_ERROR_SCHEMA = "codex-usage-tracker.agent-error.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    snapshot = immutable_snapshot(value)
    if not isinstance(snapshot, Mapping):  # pragma: no cover - immutable_snapshot preserves maps
        raise TypeError(f"{field_name} must be an object")
    return cast(Mapping[str, object], snapshot)


def _identifier(value: str | None, field_name: str, *, maximum: int = 256) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded non-empty string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} contains control characters")


@dataclass(frozen=True)
class AgentRequest:
    """One operation request independent of its transport adapter."""

    operation: str
    arguments: Mapping[str, object] = field(default_factory=dict)
    request_id: str | None = None
    scope: Mapping[str, object] = field(default_factory=dict)
    privacy_mode: str = "normal"
    execution: str = "auto"
    expected_source_revision: str | None = None
    schema: str = AGENT_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("operation must be a non-empty string")
        if self.schema != AGENT_REQUEST_SCHEMA:
            raise ValueError(f"schema must be {AGENT_REQUEST_SCHEMA}")
        if self.privacy_mode not in {"normal", "redacted", "strict"}:
            raise ValueError(f"unsupported privacy_mode: {self.privacy_mode}")
        if self.execution not in {"auto", "sync", "async"}:
            raise ValueError(f"unsupported execution: {self.execution}")
        object.__setattr__(self, "arguments", _mapping(self.arguments, "arguments"))
        object.__setattr__(self, "scope", _mapping(self.scope, "scope"))
        _identifier(self.request_id, "request_id")
        _identifier(self.expected_source_revision, "expected_source_revision")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> AgentRequest:
        """Build and validate a request from a JSON-like mapping."""

        allowed = {
            "schema",
            "operation",
            "arguments",
            "request_id",
            "scope",
            "privacy_mode",
            "execution",
            "expected_source_revision",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unsupported field: {unknown[0]}")
        return cls(
            operation=cast(str, payload.get("operation", "")),
            arguments=cast(Mapping[str, object], payload.get("arguments", {})),
            request_id=cast(str | None, payload.get("request_id")),
            scope=cast(Mapping[str, object], payload.get("scope", {})),
            privacy_mode=cast(str, payload.get("privacy_mode", "normal")),
            execution=cast(str, payload.get("execution", "auto")),
            expected_source_revision=cast(str | None, payload.get("expected_source_revision")),
            schema=cast(str, payload.get("schema", AGENT_REQUEST_SCHEMA)),
        )

    def to_payload(self) -> dict[str, object]:
        return payload_mapping(self)


@dataclass(frozen=True)
class AgentResponse:
    """Canonical success envelope around an existing application result."""

    operation: str
    result: object | None = None
    result_schema: str | None = None
    request_id: str | None = None
    generated_at: str = field(default_factory=_utc_now)
    server_instance_id: str = "local"
    catalog_revision: str = ""
    data_class: str = "aggregate"
    source_revision: str | None = None
    freshness: Mapping[str, object] = field(default_factory=dict)
    scope: Mapping[str, object] = field(default_factory=dict)
    privacy: Mapping[str, object] = field(default_factory=dict)
    job: object | None = None
    pagination: Mapping[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    next_operations: tuple[str, ...] = ()
    schema: str = AGENT_RESPONSE_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not self.operation.strip():
            raise ValueError("operation must be a non-empty string")
        if self.schema != AGENT_RESPONSE_SCHEMA:
            raise ValueError(f"schema must be {AGENT_RESPONSE_SCHEMA}")
        if self.data_class not in {"aggregate", "local_index", "raw_context", "administrative"}:
            raise ValueError(f"unsupported data_class: {self.data_class}")
        object.__setattr__(self, "result", immutable_snapshot(self.result))
        object.__setattr__(self, "job", immutable_snapshot(self.job))
        for field_name in ("freshness", "scope", "privacy", "pagination"):
            object.__setattr__(
                self,
                field_name,
                _mapping(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        object.__setattr__(self, "next_operations", tuple(self.next_operations))
        _identifier(self.request_id, "request_id")
        _identifier(self.server_instance_id, "server_instance_id")
        _identifier(self.catalog_revision, "catalog_revision", maximum=512)
        _identifier(self.source_revision, "source_revision")

    def to_payload(self) -> dict[str, object]:
        return payload_mapping(self)


@dataclass(frozen=True)
class AgentError:
    """Stable operation failure envelope used before HTTP status mapping."""

    code: str
    message: str
    operation: str | None = None
    request_id: str | None = None
    retryable: bool = False
    remediation: str | None = None
    schema: str = AGENT_ERROR_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != AGENT_ERROR_SCHEMA:
            raise ValueError(f"schema must be {AGENT_ERROR_SCHEMA}")
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("code must be a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string")
        if type(self.retryable) is not bool:
            raise TypeError("retryable must be a bool")
        _identifier(self.operation, "operation")
        _identifier(self.request_id, "request_id")

    @property
    def error(self) -> Mapping[str, object]:
        """Return a detached nested error mapping for adapter convenience."""

        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "remediation": self.remediation,
        }

    def to_payload(self) -> dict[str, object]:
        return payload_mapping(
            {
                "schema": self.schema,
                "operation": self.operation,
                "request_id": self.request_id,
                "error": self.error,
            }
        )


__all__ = [
    "AGENT_ERROR_SCHEMA",
    "AGENT_REQUEST_SCHEMA",
    "AGENT_RESPONSE_SCHEMA",
    "AgentError",
    "AgentRequest",
    "AgentResponse",
]
