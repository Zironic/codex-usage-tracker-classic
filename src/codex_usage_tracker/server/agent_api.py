"""Live-server integration for the strict agent HTTP facade."""

from __future__ import annotations

import hmac
import importlib
import inspect
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from typing import Any, BinaryIO, Protocol, cast
from urllib.parse import urlparse

from codex_usage_tracker.interfaces.http.agent import (
    AGENT_ERROR_SCHEMA,
    AgentHttpServices,
    HttpAgentFacade,
)
from codex_usage_tracker.server.responses import send_json_response


class _HttpAgentHandler(Protocol):
    path: str
    command: str
    rfile: BinaryIO
    headers: Message
    _db_path: Path
    _pricing_path: Path
    _allowance_path: Path
    _rate_card_path: Path
    _thresholds_path: Path
    _projects_path: Path
    _codex_home: Path
    _api_token: str
    _compression_jobs: object


class _UnavailableAgentServices:
    """Safe fallback while an application catalog is unavailable at startup."""

    def capabilities(self) -> object:
        return {
            "schema": "codex-usage-tracker.agent-capabilities.v1",
            "api_version": "2",
            "catalog_revision": "sha256:unavailable",
            "server_instance_id": "agent-http",
            "operations": [],
        }

    def dispatch(self, payload: object, **kwargs: object) -> object:
        del payload, kwargs
        return {
            "schema": AGENT_ERROR_SCHEMA,
            "error": {
                "code": "service_unavailable",
                "message": "Agent application services are unavailable",
                "retryable": True,
                "remediation": "Retry after the server finishes starting",
            },
        }


class _DispatcherAgentServices:
    """Expose a dispatcher plus its application-owned capability provider."""

    def __init__(self, dispatcher: object, services: object | None) -> None:
        self._dispatcher = dispatcher
        self._services = services

    def capabilities(self) -> object:
        method = getattr(self._dispatcher, "capabilities", None)
        if callable(method):
            return method()
        method = getattr(self._services, "capabilities", None)
        if callable(method):
            return method()
        catalog = importlib.import_module("codex_usage_tracker.application.agent.catalog")
        return catalog.capabilities_payload()

    def dispatch(self, payload: object, **kwargs: object) -> object:
        method = getattr(self._dispatcher, "dispatch", None)
        if not callable(method):
            raise RuntimeError("agent dispatcher is unavailable")
        return method(payload, **kwargs)


class AgentRouteMixin:
    """Attach the strict agent API to the dashboard request handler."""

    def _configure_http_agent(
        self,
        services: AgentHttpServices | None = None,
        *,
        authorized_scopes: tuple[str, ...] | None = None,
    ) -> None:
        handler = cast(_HttpAgentHandler, self)
        self._http_agent_facade = HttpAgentFacade(
            services or _build_application_services(handler),
            server_instance_id=str(getattr(self, "_server_instance_id", "agent-http")),
            authorized_scopes=authorized_scopes
            or (
                "catalog_read",
                "aggregate_read",
                "aggregate_write",
                "analysis_read",
                "evidence_read",
                "allowance_read",
                "export",
            ),
        )

    def _handle_http_agent(self, query: str) -> None:
        handler = cast(_HttpAgentHandler, self)
        parsed = urlparse(handler.path)
        response = self._http_agent_facade.handle_stream(
            method=handler.command,
            path=parsed.path,
            query=query,
            stream=handler.rfile,
            content_length=handler.headers.get("Content-Length"),
            content_type=handler.headers.get("Content-Type", ""),
            authorized=_has_header_token(handler.headers, handler._api_token),
        )
        send_json_response(
            cast(Any, self),
            HTTPStatus(response.status),
            response.payload,
            headers=response.headers,
        )

    def _send_http_agent_transport_error(self, status: HTTPStatus, message: str) -> None:
        """Write a stable agent error for Host/Origin failures before dispatch."""

        send_json_response(
            cast(Any, self),
            status,
            {
                "schema": AGENT_ERROR_SCHEMA,
                "operation": None,
                "request_id": None,
                "error": {
                    "code": "forbidden",
                    "message": message,
                    "retryable": False,
                    "remediation": None,
                },
            },
        )


def _has_header_token(headers: Message, expected: str) -> bool:
    """Validate only the header token; query-string tokens are never accepted."""

    provided = headers.get("X-Codex-Usage-Token") or ""
    return hmac.compare_digest(str(provided), expected)


def _build_application_services(handler: _HttpAgentHandler) -> AgentHttpServices:
    """Construct the application dispatcher without coupling to other adapters.

    The catalog worker may expose either ``AgentDispatcher`` directly or an
    ``AgentApplicationServices`` object.  We inspect constructor parameters so
    paths can be passed when supported without imposing a constructor shape on
    the application layer.
    """

    try:
        module = importlib.import_module("codex_usage_tracker.application.agent")
    except ImportError:
        return _UnavailableAgentServices()

    paths = {
        "db_path": handler._db_path,
        "pricing_path": handler._pricing_path,
        "allowance_path": handler._allowance_path,
        "rate_card_path": handler._rate_card_path,
        "thresholds_path": handler._thresholds_path,
        "projects_path": handler._projects_path,
        "compression_registry": handler._compression_jobs,
        "codex_home": handler._codex_home,
    }
    services_cls = getattr(module, "AgentApplicationServices", None)
    dispatcher_cls = getattr(module, "AgentDispatcher", None)
    try:
        services = _construct(services_cls, paths) if services_cls is not None else None
        if dispatcher_cls is not None:
            dispatcher = _construct_dispatcher(dispatcher_cls, services)
            if hasattr(dispatcher, "capabilities") and hasattr(dispatcher, "dispatch"):
                return cast(AgentHttpServices, dispatcher)
            if hasattr(dispatcher, "dispatch"):
                return cast(AgentHttpServices, _DispatcherAgentServices(dispatcher, services))
        if services is not None and hasattr(services, "capabilities") and hasattr(services, "dispatch"):
            return cast(AgentHttpServices, services)
    except (TypeError, ValueError):
        # A malformed optional application composition must fail closed rather
        # than make the dashboard server unavailable.
        return _UnavailableAgentServices()
    return _UnavailableAgentServices()


def _construct(cls: object, values: dict[str, object]) -> object:
    if not callable(cls):
        return None
    try:
        signature = inspect.signature(cls)
    except (TypeError, ValueError):
        return cls()  # type: ignore[operator]
    kwargs = {
        name: value
        for name, value in values.items()
        if name in signature.parameters
    }
    return cls(**kwargs)  # type: ignore[operator]


def _construct_dispatcher(cls: object, services: object) -> object:
    if not callable(cls):
        return None
    try:
        signature = inspect.signature(cls)
    except (TypeError, ValueError):
        return cls(services=services)  # type: ignore[operator]
    if "services" in signature.parameters:
        return cls(services=services)  # type: ignore[operator]
    if services is not None:
        return cls(services)  # type: ignore[operator]
    return cls()  # type: ignore[operator]
