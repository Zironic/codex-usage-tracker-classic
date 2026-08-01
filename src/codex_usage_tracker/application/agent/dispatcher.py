"""Transport-neutral dispatch for the catalog's wired core operations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields
from typing import Any, cast

from codex_usage_tracker.analytics.analysis_models import AnalysisRequest, ComparisonWindow
from codex_usage_tracker.application.allowance_models import AllowanceRequest
from codex_usage_tracker.application.errors import ApplicationError
from codex_usage_tracker.application.query_models import QueryFilters, QueryRequest
from codex_usage_tracker.application.requests import (
    JobStatusRequest,
    RefreshRequest,
    RequestScope,
    StatusRequest,
)
from codex_usage_tracker.core.contracts.serialization import payload_mapping
from codex_usage_tracker.evidence.models import EvidenceRequest

from .catalog import OPERATION_CATALOG, OperationSpec, catalog_fingerprint, get_operation
from .contracts import AgentError, AgentRequest, AgentResponse
from .services import AgentApplicationServices

_QUERY_FILTER_FIELDS = {item.name for item in fields(QueryFilters)}


class AgentDispatcher:
    """Validate catalog policy and invoke application-owned core services."""

    def __init__(
        self,
        services: AgentApplicationServices | Any | None = None,
        *,
        catalog: Iterable[OperationSpec] = OPERATION_CATALOG,
    ) -> None:
        self.services = services or AgentApplicationServices()
        self.catalog = tuple(sorted(catalog, key=lambda item: item.name))
        self._catalog_by_name = {item.name: item for item in self.catalog}

    def dispatch(
        self,
        request: AgentRequest | Mapping[str, object],
        *,
        authorized_scopes: Iterable[str] | None = None,
    ) -> AgentResponse | AgentError:
        """Dispatch one request, returning a stable error instead of leaking exceptions."""

        try:
            normalized = (
                request
                if isinstance(request, AgentRequest)
                else AgentRequest.from_mapping(request)
            )
        except (TypeError, ValueError) as exc:
            return AgentError(code="invalid_request", message=str(exc))

        spec = self._catalog_by_name.get(normalized.operation)
        if spec is None:
            # Legacy names are accepted only as a compatibility lookup; the
            # response operation remains canonical.
            spec = get_operation(normalized.operation)
        if spec is None:
            return AgentError(
                code="unknown_operation",
                message=f"Unknown agent operation: {normalized.operation}",
                operation=normalized.operation,
                request_id=normalized.request_id,
            )
        if not spec.enabled:
            return AgentError(
                code="operation_disabled",
                message=spec.disabled_reason or "Operation is disabled.",
                operation=spec.name,
                request_id=normalized.request_id,
                remediation="Use meta.capabilities to discover enabled operations.",
            )
        if authorized_scopes is not None:
            scopes = set(authorized_scopes)
            if "*" not in scopes and spec.authorization_scope not in scopes:
                return AgentError(
                    code="authorization_scope_required",
                    message=f"Operation requires scope: {spec.authorization_scope}",
                    operation=spec.name,
                    request_id=normalized.request_id,
                    remediation="Request the operation's declared local authorization scope.",
                )
        try:
            raw = self._invoke(spec.name, normalized)
            response = self._response(spec, normalized, raw)
            if (
                normalized.expected_source_revision is not None
                and response.source_revision != normalized.expected_source_revision
            ):
                return AgentError(
                    code="stale_source_revision",
                    message="The requested source revision is not current.",
                    operation=spec.name,
                    request_id=normalized.request_id,
                    retryable=True,
                    remediation="Refresh the index and retry without the old revision.",
                )
            return response
        except (ApplicationError, LookupError, TypeError, ValueError) as exc:
            return self._application_error(spec, normalized, exc)

    # ``execute`` is a convenient transport-neutral spelling used by adapters.
    execute = dispatch

    def _invoke(self, operation: str, request: AgentRequest) -> object:
        args = request.arguments
        scope = _request_scope(request)
        if operation == "meta.capabilities":
            return self.services.capabilities()
        if operation == "meta.schema":
            target = args.get("operation", args.get("name"))
            if not isinstance(target, str) or not target:
                raise ValueError("meta.schema requires arguments.operation")
            return self.services.schema(target)
        if operation == "system.status":
            threshold = args.get("freshness_threshold_seconds", 300)
            if type(threshold) not in {int, float}:
                raise ValueError("freshness_threshold_seconds must be a number")
            return self.services.status(
                StatusRequest(scope=scope, freshness_threshold_seconds=cast(float, threshold))
            )
        if operation == "refresh.start":
            return self.services.refresh(
                RefreshRequest(
                    history=cast(Any, scope.history),
                    aggregate_only=_bool(args.get("aggregate_only", True), "aggregate_only"),
                    execution=cast(Any, args.get("execution", request.execution)),
                )
            )
        if operation == "job.get":
            job_id = args.get("job_id")
            if not isinstance(job_id, str):
                raise ValueError("job.get requires arguments.job_id")
            return self.services.job_status(
                JobStatusRequest(
                    job_id=job_id,
                    include_result=_bool(args.get("include_result", False), "include_result"),
                )
            )
        if operation == "usage.query":
            return self.services.query(_query_request(args, scope))
        if operation == "analysis.run":
            return self.services.analyze(_analysis_request(args, scope, request.execution))
        if operation == "evidence.get":
            return self.services.evidence(_evidence_request(args, scope))
        if operation in {
            "allowance.status",
            "allowance.series",
            "allowance.evidence",
            "allowance.analysis",
        }:
            return self.services.allowance(_allowance_request(operation, args, request.execution))
        if operation in self._catalog_by_name:
            report_arguments = dict(args)
            spec = self._catalog_by_name[operation]
            if spec.data_class in {"local_index", "raw_context"}:
                acknowledged = report_arguments.pop("acknowledge_sensitive_content", False)
                if acknowledged is not True:
                    raise ValueError(
                        "acknowledge_sensitive_content must be true for local content operations"
                    )
            return self.services.report(
                operation,
                report_arguments,
                privacy_mode=request.privacy_mode,
            )
        raise ValueError(f"Operation is cataloged but not wired: {operation}")

    def _response(
        self,
        spec: OperationSpec,
        request: AgentRequest,
        raw: object,
    ) -> AgentResponse:
        payload = payload_mapping(raw) if raw is not None else {}
        schema = payload.get("schema")
        result_schema = schema if isinstance(schema, str) else spec.result_schema
        is_job = result_schema == "codex-usage-tracker.job.v1"
        source_revision = _source_revision(payload)
        freshness = _first_mapping(payload, "freshness", "index")
        pagination = _pagination(payload)
        privacy = {
            "mode": request.privacy_mode,
            "includes_indexed_content": spec.data_class == "local_index",
            "includes_raw_fragments": spec.data_class == "raw_context",
            "redaction_applied": request.privacy_mode != "normal",
        }
        scope = dict(request.scope)
        scope.setdefault("history", "active")
        scope.setdefault("privacy_mode", request.privacy_mode)
        return AgentResponse(
            operation=spec.name,
            result=None if is_job else payload,
            result_schema=result_schema,
            request_id=request.request_id,
            server_instance_id="local",
            catalog_revision=catalog_fingerprint(self.catalog),
            data_class=spec.data_class,
            source_revision=source_revision,
            freshness=freshness,
            scope=scope,
            privacy=privacy,
            job=payload if is_job else None,
            pagination=pagination,
            warnings=_strings(payload.get("warnings")),
            limitations=_strings(payload.get("limitations")),
        )

    @staticmethod
    def _application_error(
        spec: OperationSpec,
        request: AgentRequest,
        error: Exception,
    ) -> AgentError:
        code = "not_found" if isinstance(error, LookupError) else "invalid_request"
        return AgentError(
            code=code,
            message=str(error),
            operation=spec.name,
            request_id=request.request_id,
            retryable=False,
        )


AgentApplicationDispatcher = AgentDispatcher


def dispatch_agent(
    request: AgentRequest | Mapping[str, object],
    *,
    services: AgentApplicationServices | Any | None = None,
    authorized_scopes: Iterable[str] | None = None,
) -> AgentResponse | AgentError:
    return AgentDispatcher(services).dispatch(request, authorized_scopes=authorized_scopes)


def _request_scope(request: AgentRequest) -> RequestScope:
    values = dict(request.scope)
    history = values.pop("history", "active")
    privacy_mode = values.pop("privacy_mode", request.privacy_mode)
    allowed = {"since", "until", "project", "thread_key", "model", "effort"}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unsupported scope field: {unknown[0]}")
    return RequestScope(
        since=cast(str | None, values.get("since")),
        until=cast(str | None, values.get("until")),
        history=cast(Any, history),
        privacy_mode=cast(Any, privacy_mode),
        project=cast(str | None, values.get("project")),
        thread_key=cast(str | None, values.get("thread_key")),
        model=cast(str | None, values.get("model")),
        effort=cast(str | None, values.get("effort")),
    )


def _query_request(args: Mapping[str, object], scope: RequestScope) -> QueryRequest:
    filters_value = args.get("filters", {})
    if not isinstance(filters_value, Mapping):
        raise ValueError("filters must be an object")
    filters = {
        key: value
        for key, value in {
            "since": scope.since,
            "until": scope.until,
            "project": scope.project,
            "thread_key": scope.thread_key,
            "model": scope.model,
            "effort": scope.effort,
        }.items()
        if value is not None
    }
    unknown = sorted(set(filters_value) - _QUERY_FILTER_FIELDS)
    if unknown:
        raise ValueError(f"unsupported filters field: {unknown[0]}")
    filters.update(filters_value)
    values = dict(args)
    values.pop("filters", None)
    entity = values.pop("entity", None)
    measures = values.pop("measures", None)
    if not isinstance(entity, str) or not entity:
        raise ValueError("usage.query requires arguments.entity")
    if isinstance(measures, str) or not isinstance(measures, (tuple, list)):
        raise ValueError("measures must be an array of strings")
    if any(not isinstance(item, str) for item in measures):
        raise ValueError("measures must contain only strings")
    group_by = values.pop("group_by", ())
    if isinstance(group_by, str) or not isinstance(group_by, (tuple, list)):
        raise ValueError("group_by must be an array of strings")
    if any(not isinstance(item, str) for item in group_by):
        raise ValueError("group_by must contain only strings")
    values.setdefault("history", scope.history)
    values["measures"] = tuple(measures)
    values["group_by"] = tuple(group_by)
    values["filters"] = QueryFilters(**filters)
    return QueryRequest(entity=cast(Any, entity), **values)


def _analysis_request(
    args: Mapping[str, object], scope: RequestScope, execution: str
) -> AnalysisRequest:
    values = dict(args)
    goal = values.pop("goal", None)
    if not isinstance(goal, str) or not goal:
        raise ValueError("analysis.run requires arguments.goal")
    filters_value = values.pop("filters", {})
    if not isinstance(filters_value, Mapping):
        raise ValueError("filters must be an object")
    unknown = sorted(set(filters_value) - _QUERY_FILTER_FIELDS)
    if unknown:
        raise ValueError(f"unsupported filters field: {unknown[0]}")
    base = {
        key: value
        for key, value in {
            "since": scope.since,
            "until": scope.until,
            "project": scope.project,
            "thread_key": scope.thread_key,
            "model": scope.model,
            "effort": scope.effort,
        }.items()
        if value is not None
    }
    base.update(filters_value)
    values["filters"] = QueryFilters(**base)
    values.setdefault("history", scope.history)
    values.setdefault("execution", execution)
    comparison = values.get("comparison")
    if comparison is not None:
        if not isinstance(comparison, Mapping):
            raise ValueError("comparison must be an object")
        if set(comparison) - {"since", "until"}:
            raise ValueError("comparison supports only since and until")
        values["comparison"] = ComparisonWindow(
            since=cast(str, comparison.get("since")),
            until=cast(str, comparison.get("until")),
        )
    return AnalysisRequest(goal=cast(Any, goal), **values)


def _evidence_request(args: Mapping[str, object], scope: RequestScope) -> EvidenceRequest:
    values = dict(args)
    values.setdefault("history", scope.history)
    allowed = {item.name for item in fields(EvidenceRequest)}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unsupported evidence field: {unknown[0]}")
    return EvidenceRequest(**values)  # type: ignore[arg-type]


def _allowance_request(operation: str, args: Mapping[str, object], execution: str) -> AllowanceRequest:
    expected = operation.removeprefix("allowance.")
    values = dict(args)
    supplied = values.pop("operation", expected)
    if supplied != expected:
        raise ValueError("allowance operation does not match the selected catalog operation")
    values.setdefault("execution", execution)
    values["operation"] = expected
    allowed = {item.name for item in fields(AllowanceRequest)}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unsupported allowance field: {unknown[0]}")
    return AllowanceRequest(**values)  # type: ignore[arg-type]


def _bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field_name} must be a bool")
    return cast(bool, value)


def _first_mapping(payload: Mapping[str, object], *keys: str) -> Mapping[str, object]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _source_revision(payload: Mapping[str, object]) -> str | None:
    for key in ("source_revision", "revision"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    for key in ("freshness", "index"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            revision = value.get("source_revision")
            if isinstance(revision, str):
                return revision
    return None


def _pagination(payload: Mapping[str, object]) -> dict[str, object]:
    cursor = payload.get("next_cursor")
    total = payload.get("total_matched")
    return {
        "next_cursor": cursor if isinstance(cursor, str) else None,
        "total_matched": total if type(total) is int else None,
        "truncated": cursor is not None,
    }


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


__all__ = [
    "AgentApplicationDispatcher",
    "AgentDispatcher",
    "dispatch_agent",
]
