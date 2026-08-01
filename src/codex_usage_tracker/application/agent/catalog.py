"""Deterministic, immutable operation catalog for the agent application API."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from codex_usage_tracker.core.contracts.serialization import payload_mapping, serialized_json

_DATA_CLASSES = {"aggregate", "local_index", "raw_context", "administrative"}
_EXECUTIONS = {"synchronous", "async-start", "polling"}
_PAGINATIONS = {"none", "revision_bound_cursor", "opaque_cursor"}
_MATURITIES = {"stable", "planned", "experimental", "deprecated"}


@dataclass(frozen=True)
class OperationSpec:
    """Policy and schema metadata for one canonical operation.

    No handler is stored in a descriptor.  This keeps discovery data
    serializable and prevents a transport module from becoming an accidental
    owner of application behavior.
    """

    name: str
    description: str
    maturity: str
    lifecycle: str
    owner: str
    data_class: str
    authorization_scope: str
    execution: str
    request_schema: str
    result_schema: str
    input_limit_bytes: int
    output_limit_bytes: int
    pagination: str
    may_scan_all_history: bool
    freshness: str = "read_current"
    active_history: bool = True
    supported_privacy_modes: tuple[str, ...] = ("normal", "redacted", "strict")
    cache: str = "none"
    row_limit: int | None = None
    character_limit: int | None = None
    enabled: bool = True
    default_enabled: bool = True
    disabled_reason: str | None = None
    legacy_names: tuple[str, ...] = ()
    argument_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "name",
            "description",
            "maturity",
            "lifecycle",
            "owner",
            "authorization_scope",
            "request_schema",
            "result_schema",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.maturity not in _MATURITIES:
            raise ValueError(f"unsupported maturity: {self.maturity}")
        if self.data_class not in _DATA_CLASSES:
            raise ValueError(f"unsupported data_class: {self.data_class}")
        if self.execution not in _EXECUTIONS:
            raise ValueError(f"unsupported execution: {self.execution}")
        if self.pagination not in _PAGINATIONS:
            raise ValueError(f"unsupported pagination: {self.pagination}")
        for field_name in ("input_limit_bytes", "output_limit_bytes", "row_limit", "character_limit"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{field_name} must be a positive integer")
        if type(self.may_scan_all_history) is not bool:
            raise TypeError("may_scan_all_history must be a bool")
        if type(self.active_history) is not bool:
            raise TypeError("active_history must be a bool")
        if type(self.enabled) is not bool or type(self.default_enabled) is not bool:
            raise TypeError("enabled and default_enabled must be bools")
        modes = tuple(self.supported_privacy_modes)
        if not modes or any(mode not in {"normal", "redacted", "strict"} for mode in modes):
            raise ValueError("supported_privacy_modes must contain valid privacy modes")
        object.__setattr__(self, "supported_privacy_modes", modes)
        object.__setattr__(self, "legacy_names", tuple(self.legacy_names))
        object.__setattr__(self, "argument_fields", tuple(self.argument_fields))
        if not self.enabled and not self.disabled_reason:
            object.__setattr__(self, "disabled_reason", "Operation is not wired in this release.")
        if self.enabled and self.disabled_reason is not None:
            raise ValueError("enabled operations cannot have a disabled_reason")

    @property
    def enabled_by_default(self) -> bool:
        """Alias used by discovery clients that call the field by policy name."""

        return self.default_enabled

    @property
    def request_limit_bytes(self) -> int:
        return self.input_limit_bytes

    @property
    def response_limit_bytes(self) -> int:
        return self.output_limit_bytes

    def to_payload(self) -> dict[str, object]:
        """Return a fresh JSON-compatible descriptor payload."""

        return payload_mapping(self)


def _spec(
    name: str,
    description: str,
    *,
    owner: str,
    data_class: str = "aggregate",
    authorization_scope: str = "aggregate_read",
    execution: str = "synchronous",
    result_schema: str | None = None,
    request_suffix: str | None = None,
    maturity: str = "planned",
    lifecycle: str = "planned",
    pagination: str = "none",
    may_scan_all_history: bool = False,
    freshness: str = "read_current",
    active_history: bool = True,
    cache: str = "none",
    row_limit: int | None = None,
    character_limit: int | None = None,
    enabled: bool = False,
    default_enabled: bool = False,
    disabled_reason: str | None = None,
    legacy_names: Iterable[str] = (),
) -> OperationSpec:
    slug = name.replace(".", "-")
    return OperationSpec(
        name=name,
        description=description,
        maturity=maturity,
        lifecycle=lifecycle,
        owner=owner,
        data_class=data_class,
        authorization_scope=authorization_scope,
        execution=execution,
        request_schema=f"codex-usage-tracker.agent-operation.{request_suffix or slug}.request.v1",
        result_schema=result_schema or f"codex-usage-tracker.agent-operation.{slug}.v1",
        input_limit_bytes=32 * 1024,
        output_limit_bytes=256 * 1024,
        pagination=pagination,
        may_scan_all_history=may_scan_all_history,
        freshness=freshness,
        active_history=active_history,
        cache=cache,
        row_limit=row_limit,
        character_limit=character_limit,
        enabled=enabled,
        default_enabled=default_enabled,
        disabled_reason=disabled_reason,
        legacy_names=tuple(legacy_names),
    )


def _core_specs() -> tuple[OperationSpec, ...]:
    common = {
        "maturity": "stable",
        "lifecycle": "active",
        "enabled": True,
        "default_enabled": True,
    }
    return (
        _spec(
            "meta.capabilities",
            "Discover operation policy, schemas, limits, and enabled state.",
            owner="application.agent.catalog",
            authorization_scope="catalog_read",
            result_schema="codex-usage-tracker.agent-capabilities.v1",
            request_suffix="meta-capabilities",
            **common,
            legacy_names=("usage_capabilities", "/api/v2/capabilities"),
        ),
        _spec(
            "meta.schema",
            "Read the bounded request and result schema metadata for one operation.",
            owner="application.agent.catalog",
            authorization_scope="catalog_read",
            result_schema="codex-usage-tracker.agent-schema.v1",
            request_suffix="meta-schema",
            **common,
            legacy_names=("usage_schema",),
        ),
        _spec(
            "system.status",
            "Read index freshness, source, pricing, accounting, and readiness status.",
            owner="application.status",
            result_schema="codex-usage-tracker.status.v2",
            request_suffix="system-status",
            **common,
            legacy_names=("usage_status", "/api/v2/status"),
        ),
        _spec(
            "refresh.start",
            "Refresh the local usage index and return a bounded result or job.",
            owner="application.refresh",
            authorization_scope="aggregate_write",
            execution="async-start",
            result_schema="codex-usage-tracker.refresh.v2",
            request_suffix="refresh-start",
            freshness="writes_index",
            **common,
            legacy_names=("usage_refresh", "refresh_usage_index", "usage_refresh_start", "/api/v2/refresh"),
        ),
        _spec(
            "job.get",
            "Poll a generic application job and optionally include its result.",
            owner="application.job_status",
            execution="polling",
            result_schema="codex-usage-tracker.job.v1",
            request_suffix="job-get",
            cache="job_registry",
            **common,
            legacy_names=("usage_job_status", "/api/v2/jobs/{job_id}"),
        ),
        _spec(
            "usage.query",
            "Run a bounded aggregate query with revision-bound pagination.",
            owner="application.query",
            result_schema="codex-usage-tracker.query.v2",
            request_suffix="usage-query",
            pagination="revision_bound_cursor",
            may_scan_all_history=True,
            row_limit=200,
            cache="none",
            **common,
            legacy_names=(
                "usage_query",
                "usage_summary",
                "usage_calls",
                "usage_threads",
                "session_usage",
                "most_expensive_usage_calls",
                "subagent_usage",
                "/api/v2/query",
            ),
        ),
        _spec(
            "analysis.run",
            "Run one cataloged usage analysis synchronously or as a reusable job.",
            owner="application.analyze",
            authorization_scope="analysis_read",
            execution="async-start",
            result_schema="codex-usage-tracker.analysis.v2",
            request_suffix="analysis-run",
            pagination="revision_bound_cursor",
            may_scan_all_history=True,
            row_limit=20,
            cache="semantic_job",
            **common,
            legacy_names=("usage_analyze", "/api/v2/analyze"),
        ),
        _spec(
            "evidence.get",
            "Resolve one exact aggregate evidence selector and bounded page.",
            owner="application.evidence",
            authorization_scope="evidence_read",
            result_schema="codex-usage-tracker.evidence-result.v1",
            request_suffix="evidence-get",
            pagination="revision_bound_cursor",
            row_limit=200,
            **common,
            legacy_names=("usage_evidence", "usage_call_detail", "/api/v2/evidence"),
        ),
    )


def _allowance_specs() -> tuple[OperationSpec, ...]:
    common = {
        "maturity": "stable",
        "lifecycle": "active",
        "enabled": True,
        "default_enabled": True,
        "authorization_scope": "allowance_read",
    }
    return (
        _spec(
            "allowance.status",
            "Read the constant-size current allowance state.",
            owner="application.allowance",
            result_schema="codex-usage-tracker-allowance-status-v2",
            request_suffix="allowance-status",
            active_history=False,
            **common,
            legacy_names=("usage_allowance_status", "usage_allowance"),
        ),
        _spec(
            "allowance.series",
            "Read a finite reset-aware allowance series.",
            owner="application.allowance",
            result_schema="codex-usage-tracker-allowance-series-v2",
            request_suffix="allowance-series",
            pagination="revision_bound_cursor",
            may_scan_all_history=True,
            row_limit=200,
            **common,
            legacy_names=("usage_allowance_series", "usage_allowance_history"),
        ),
        _spec(
            "allowance.evidence",
            "Read latest-first bounded allowance transition evidence.",
            owner="application.allowance",
            result_schema="codex-usage-tracker-allowance-evidence-v2",
            request_suffix="allowance-evidence",
            pagination="revision_bound_cursor",
            may_scan_all_history=True,
            row_limit=200,
            **common,
            legacy_names=("usage_allowance_evidence",),
        ),
        _spec(
            "allowance.analysis",
            "Read or start reusable allowance change analysis.",
            owner="application.allowance",
            execution="async-start",
            result_schema="codex-usage-tracker-allowance-analysis-v2",
            request_suffix="allowance-analysis",
            cache="semantic_job",
            **common,
            legacy_names=("usage_allowance_analysis",),
        ),
    )


_PLANNED_OPERATIONS: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = (
    ("system.doctor", "Read sanitized installation and environment health.", "application.doctor", "system_doctor", ("usage_doctor",)),
    ("system.coverage", "Read pricing, credit, source, parser, and tier coverage.", "reports.coverage", "system_coverage", ("usage_pricing_coverage", "usage_source_coverage")),
    ("system.configuration", "Read effective sanitized local configuration.", "application.configuration", "system_configuration", ()),
    ("usage.statistics", "Read bounded activity and attribution statistics.", "reports.statistics", "usage_statistics", ("/api/v2/statistics",)),
    ("usage.dedupe", "Read canonical-versus-physical deduplication facts.", "reports.dedupe", "usage_dedupe", ("usage_dedupe_diagnostics",)),
    ("usage.recommendations", "Read ranked aggregate usage recommendations.", "reports.recommendations", "usage_recommendations", ("usage_recommendations", "usage_dashboard_recommendations")),
    ("usage.report", "Read a compact aggregate report pack.", "reports.api", "usage_report", ("usage_report_pack",)),
    ("analysis.suggest", "Suggest bounded follow-up investigations.", "reports.discovery", "analysis_suggest", ("usage_suggest_investigations",)),
    ("analysis.hypotheses", "Evaluate explicit aggregate hypotheses.", "reports.hypotheses", "analysis_hypotheses", ("usage_test_hypotheses",)),
    ("analysis.action_brief", "Build an evidence-backed remediation brief.", "reports.action_brief", "analysis_action_brief", ("usage_action_brief",)),
    ("analysis.investigation", "Run a bounded aggregate investigation walk.", "reports.investigation", "analysis_investigation", ("usage_investigate", "usage_investigation_walk")),
    ("analysis.pattern_scan", "Scan bounded aggregate repetition and churn patterns.", "reports.discovery", "analysis_pattern_scan", ()),
    ("evidence.thread_calls", "Page calls for one exact thread evidence selector.", "application.evidence", "evidence_thread_calls", ()),
    ("evidence.local_export", "Create a strict bounded local evidence export.", "reports.exports", "evidence_local_export", ("usage_local_evidence_export",)),
    ("allowance.diagnostics", "Read allowance quality and movement diagnostics.", "allowance_intelligence", "allowance_diagnostics", ("usage_allowance_diagnostics",)),
    ("allowance.export", "Create a strict allowance evidence artifact.", "allowance_intelligence", "allowance_export", ("usage_allowance_export",)),
    ("diagnostics.get", "Read one allowlisted persisted diagnostic snapshot.", "diagnostics", "diagnostics_get", ()),
    ("diagnostics.refresh", "Refresh one allowlisted diagnostic snapshot.", "diagnostics", "diagnostics_refresh", ()),
    ("compression.start", "Start or reuse a compression analysis job.", "compression", "compression_start", ("usage_compression_start",)),
    ("compression.status", "Poll compression analysis progress.", "compression", "compression_status", ("usage_compression_status",)),
    ("compression.profile", "Read a completed compact compression profile.", "compression", "compression_profile", ("usage_compression_profile",)),
    ("compression.candidates", "Page ranked compression candidates.", "compression", "compression_candidates", ("usage_compression_candidates",)),
    ("compression.candidate", "Read one bounded compression candidate.", "compression", "compression_candidate", ("usage_compression_candidate_detail",)),
    ("compression.simulate", "Estimate bounded intervention effects.", "compression", "compression_simulate", ("usage_compression_simulate",)),
    ("content.search", "Search the local content index with explicit sensitive scope.", "context", "content_search", ("usage_content_search",)),
    ("content.thread_trace", "Read a paged local thread timeline.", "context", "content_thread_trace", ("usage_thread_trace",)),
    ("content.call_context", "Read one explicitly selected redacted call context.", "context", "content_call_context", ("usage_call_context",)),
    ("export.create", "Create a bounded aggregate artifact.", "reports.exports", "export_create", ("export_usage_csv", "generate_usage_dashboard")),
    ("artifact.get", "Read bounded metadata or bytes for an opaque artifact.", "application.artifacts", "artifact_get", ()),
    ("visualization.suggest", "Suggest renderer-independent visualizations.", "reports.visualization", "visualization_suggest", ()),
    ("visualization.render", "Render a bounded visualization specification.", "reports.visualization", "visualization_render", ()),
    ("dogfood.start", "Start strict-privacy maintainer dogfood analysis.", "reports.dogfood", "dogfood_start", ()),
    ("dogfood.status", "Poll dogfood analysis progress.", "reports.dogfood", "dogfood_status", ()),
    ("dogfood.result", "Read the compact dogfood aggregate artifact.", "reports.dogfood", "dogfood_result", ()),
)

_WIRED_INFORMATION_OPERATIONS = frozenset(
    {
        "system.doctor",
        "system.coverage",
        "usage.statistics",
        "usage.dedupe",
        "usage.recommendations",
        "usage.report",
        "analysis.suggest",
        "analysis.hypotheses",
        "analysis.action_brief",
        "analysis.investigation",
        "analysis.pattern_scan",
        "evidence.local_export",
        "content.search",
        "content.thread_trace",
        "content.call_context",
        "visualization.suggest",
        "visualization.render",
        "compression.start",
        "compression.status",
        "compression.profile",
        "compression.candidates",
        "compression.candidate",
        "compression.simulate",
        "diagnostics.get",
        "allowance.diagnostics",
        "allowance.export",
    }
)

_OPERATION_ARGUMENT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "meta.schema": ("operation", "name"),
    "system.status": ("freshness_threshold_seconds",),
    "refresh.start": ("aggregate_only", "execution"),
    "job.get": ("job_id", "include_result"),
    "usage.query": (
        "entity", "measures", "filters", "group_by", "order_by", "order", "limit", "cursor", "history",
    ),
    "analysis.run": ("goal", "filters", "history", "evidence_limit", "comparison", "execution"),
    "evidence.get": ("selector_kind", "selector_id", "section", "limit", "cursor", "history", "analysis_id"),
    "allowance.status": ("window", "range", "cursor", "limit", "analysis_id", "execution"),
    "allowance.series": ("window", "range", "cursor", "limit", "analysis_id", "execution"),
    "allowance.evidence": ("window", "range", "cursor", "limit", "analysis_id", "execution"),
    "allowance.analysis": ("window", "range", "cursor", "limit", "analysis_id", "execution"),
    "system.coverage": ("limit", "since", "include_archived"),
    "usage.statistics": ("group_by", "limit", "preset", "since", "include_archived"),
    "usage.dedupe": ("limit",),
    "usage.recommendations": (
        "since", "until", "model", "effort", "thread", "project", "include_archived",
        "min_score", "limit", "source_limit",
    ),
    "usage.report": ("limit", "since", "include_archived"),
    "analysis.suggest": ("goal", "since", "until", "thread", "include_archived", "limit"),
    "analysis.hypotheses": (
        "question", "hypotheses", "since", "until", "thread", "include_archived", "evidence_limit",
    ),
    "analysis.action_brief": ("goal", "since", "until", "thread", "include_archived", "evidence_limit"),
    "analysis.investigation": ("goal", "since", "until", "thread", "include_archived", "evidence_limit"),
    "analysis.pattern_scan": (
        "scan_type", "since", "until", "thread", "include_archived", "min_occurrences", "limit",
    ),
    "evidence.local_export": (
        "question", "since", "until", "thread", "include_archived", "min_occurrences",
        "evidence_limit", "acknowledge_sensitive_content",
    ),
    "content.search": (
        "query", "since", "until", "model", "effort", "thread", "include_archived", "limit",
        "offset", "max_snippet_chars", "acknowledge_sensitive_content",
    ),
    "content.thread_trace": (
        "thread", "thread_key", "session_id", "record_id", "since", "until", "include_archived",
        "limit", "offset", "max_snippet_chars", "acknowledge_sensitive_content",
    ),
    "content.call_context": (
        "record_id", "max_chars", "max_entries", "include_tool_output", "include_compaction_history",
        "diagnostics", "mode", "acknowledge_sensitive_content",
    ),
    "visualization.suggest": ("question", "scope"),
    "visualization.render": ("kind", "source", "include_archived", "evidence_limit"),
    "compression.start": (
        "since", "until", "thread", "include_archived", "model", "effort", "detector_families", "refresh",
    ),
    "compression.status": ("run_id",),
    "compression.profile": (
        "run_id", "since", "until", "thread", "include_archived", "model", "effort", "detector_families",
    ),
    "compression.candidates": (
        "run_id", "family", "confidence_grade", "model", "thread", "since", "until", "min_exposure",
        "min_likely_savings", "sort", "limit", "offset", "max_payload_bytes",
    ),
    "compression.candidate": (
        "candidate_id", "evidence_mode", "evidence_limit", "max_excerpt_chars", "max_payload_bytes",
    ),
    "compression.simulate": ("run_id", "candidate_ids", "max_payload_bytes"),
    "diagnostics.get": (
        "view", "limit", "offset", "since", "until", "model", "effort", "thread", "min_tokens",
        "fact_type", "fact_name", "fact_category", "fact_group", "include_archived", "sort", "direction",
        "acknowledge_sensitive_content",
    ),
    "allowance.diagnostics": ("include_archived", "window_kind", "limit"),
    "allowance.export": ("include_archived", "window_kind", "limit"),
}


def _planned_specs() -> tuple[OperationSpec, ...]:
    result: list[OperationSpec] = []
    for name, description, owner, suffix, legacy in _PLANNED_OPERATIONS:
        enabled = name in _WIRED_INFORMATION_OPERATIONS
        data_class = (
            "local_index"
            if name.startswith("content.")
            or name in {"evidence.local_export", "diagnostics.get"}
            else "aggregate"
        )
        if name == "content.call_context":
            data_class = "raw_context"
        scope = "local_index_read" if data_class == "local_index" else "aggregate_read"
        if data_class == "raw_context":
            scope = "raw_context_read"
        if name.startswith("allowance."):
            scope = "allowance_read"
        if name.endswith(".start") or name == "diagnostics.refresh":
            scope = "aggregate_write"
        result.append(
            _spec(
                name,
                description,
                owner=owner,
                data_class=data_class,
                authorization_scope=scope,
                execution=(
                    "async-start"
                    if name.endswith(".start")
                    else "polling" if name.endswith(".status") else "synchronous"
                ),
                request_suffix=suffix,
                maturity="stable" if enabled else "planned",
                lifecycle="active" if enabled else "planned",
                enabled=enabled,
                default_enabled=enabled,
                legacy_names=legacy,
                disabled_reason=None if enabled else "Planned operation is not wired in this release.",
            )
        )
    return tuple(result)


OPERATION_CATALOG: tuple[OperationSpec, ...] = tuple(
    replace(item, argument_fields=_OPERATION_ARGUMENT_FIELDS.get(item.name, ()))
    for item in sorted((*_core_specs(), *_allowance_specs(), *_planned_specs()), key=lambda item: item.name)
)
AGENT_OPERATION_CATALOG = OPERATION_CATALOG
CATALOG = OPERATION_CATALOG


def catalog() -> tuple[OperationSpec, ...]:
    return OPERATION_CATALOG


def get_operation(name: str, *, include_legacy: bool = True) -> OperationSpec | None:
    for operation in OPERATION_CATALOG:
        if operation.name == name or (include_legacy and name in operation.legacy_names):
            return operation
    return None


def catalog_fingerprint(operations: Iterable[OperationSpec] = OPERATION_CATALOG) -> str:
    payload = [item.to_payload() for item in sorted(operations, key=lambda item: item.name)]
    digest = hashlib.sha256(serialized_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def legacy_operation_map(operations: Iterable[OperationSpec] = OPERATION_CATALOG) -> Mapping[str, str]:
    mapping: dict[str, str] = {}
    for operation in operations:
        for legacy_name in operation.legacy_names:
            existing = mapping.get(legacy_name)
            if existing is not None and existing != operation.name:
                raise ValueError(f"legacy name maps to multiple operations: {legacy_name}")
            mapping[legacy_name] = operation.name
    return dict(sorted(mapping.items()))


def capabilities_payload(operations: Iterable[OperationSpec] = OPERATION_CATALOG) -> dict[str, object]:
    ordered = tuple(sorted(operations, key=lambda item: item.name))
    return {
        "schema": "codex-usage-tracker.agent-capabilities.v1",
        "api_version": "2",
        "catalog_revision": catalog_fingerprint(ordered),
        "operations": [item.to_payload() for item in ordered],
    }


def schema_payload(name: str, operations: Iterable[OperationSpec] = OPERATION_CATALOG) -> dict[str, object]:
    operation = next((item for item in operations if item.name == name), None)
    if operation is None:
        raise KeyError(name)
    return {
        "schema": "codex-usage-tracker.agent-schema.v1",
        "operation": operation.name,
        "request_schema": operation.request_schema,
        "result_schema": operation.result_schema,
        "request": {
            "type": "object",
            "properties": {field_name: {} for field_name in operation.argument_fields},
            "additional_properties": False,
        },
        "result": {"type": "object", "schema": operation.result_schema},
        "limits": {
            "input_bytes": operation.input_limit_bytes,
            "output_bytes": operation.output_limit_bytes,
            "rows": operation.row_limit,
            "characters": operation.character_limit,
        },
    }


__all__ = [
    "AGENT_OPERATION_CATALOG",
    "CATALOG",
    "OPERATION_CATALOG",
    "OperationSpec",
    "capabilities_payload",
    "catalog",
    "catalog_fingerprint",
    "get_operation",
    "legacy_operation_map",
    "schema_payload",
]
