"""Transport-neutral agent operation catalog, contracts, and dispatcher."""

from .catalog import (
    AGENT_OPERATION_CATALOG,
    CATALOG,
    OPERATION_CATALOG,
    OperationSpec,
    capabilities_payload,
    catalog,
    catalog_fingerprint,
    get_operation,
    legacy_operation_map,
    schema_payload,
)
from .contracts import (
    AGENT_ERROR_SCHEMA,
    AGENT_REQUEST_SCHEMA,
    AGENT_RESPONSE_SCHEMA,
    AgentError,
    AgentRequest,
    AgentResponse,
)
from .dispatcher import AgentApplicationDispatcher, AgentDispatcher, dispatch_agent
from .services import AgentApplicationServices

__all__ = [
    "AGENT_ERROR_SCHEMA",
    "AGENT_OPERATION_CATALOG",
    "AGENT_REQUEST_SCHEMA",
    "AGENT_RESPONSE_SCHEMA",
    "AgentApplicationDispatcher",
    "AgentApplicationServices",
    "AgentDispatcher",
    "AgentError",
    "AgentRequest",
    "AgentResponse",
    "CATALOG",
    "OPERATION_CATALOG",
    "OperationSpec",
    "capabilities_payload",
    "catalog",
    "catalog_fingerprint",
    "dispatch_agent",
    "get_operation",
    "legacy_operation_map",
    "schema_payload",
]
