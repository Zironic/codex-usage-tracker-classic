"""Transport-neutral application service bundle for agent operations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from codex_usage_tracker.analytics.analysis_catalog import ANALYSIS_GOALS
from codex_usage_tracker.analytics.analysis_models import AnalysisRequest
from codex_usage_tracker.application.allowance import get_allowance
from codex_usage_tracker.application.allowance_models import AllowanceRequest
from codex_usage_tracker.application.analyze import AnalysisRuntime, analyze_usage
from codex_usage_tracker.application.context import build_request_context
from codex_usage_tracker.application.evidence import get_evidence
from codex_usage_tracker.application.job_status import get_job_status
from codex_usage_tracker.application.query import query_usage
from codex_usage_tracker.application.query_models import (
    ALL_QUERY_MEASURES,
    QUERY_ENTITY_CAPABILITIES,
    QueryRequest,
)
from codex_usage_tracker.application.query_validation import normalize_query_filters
from codex_usage_tracker.application.refresh import default_job_service, refresh_usage
from codex_usage_tracker.application.requests import (
    JobStatusRequest,
    RefreshRequest,
    StatusRequest,
)
from codex_usage_tracker.application.status import get_status
from codex_usage_tracker.compression.jobs import CompressionJobRegistry
from codex_usage_tracker.core.contracts.serialization import payload_mapping
from codex_usage_tracker.core.paths import (
    DEFAULT_ALLOWANCE_PATH,
    DEFAULT_CODEX_HOME,
    DEFAULT_DB_PATH,
    DEFAULT_PRICING_PATH,
    DEFAULT_PROJECTS_PATH,
    DEFAULT_RATE_CARD_PATH,
    DEFAULT_THRESHOLDS_PATH,
)
from codex_usage_tracker.evidence.models import EvidenceRequest
from codex_usage_tracker.jobs.service import JobService

_REPORT_ARGUMENT_FIELDS: dict[str, frozenset[str]] = {
    "system.doctor": frozenset(),
    "system.coverage": frozenset({"limit", "since", "include_archived"}),
    "usage.statistics": frozenset(
        {"group_by", "limit", "preset", "since", "include_archived"}
    ),
    "usage.dedupe": frozenset({"limit"}),
    "usage.recommendations": frozenset(
        {
            "since",
            "until",
            "model",
            "effort",
            "thread",
            "project",
            "include_archived",
            "min_score",
            "limit",
            "source_limit",
        }
    ),
    "usage.report": frozenset({"limit", "since", "include_archived"}),
    "analysis.suggest": frozenset(
        {"goal", "since", "until", "thread", "include_archived", "limit"}
    ),
    "analysis.hypotheses": frozenset(
        {
            "question",
            "hypotheses",
            "since",
            "until",
            "thread",
            "include_archived",
            "evidence_limit",
        }
    ),
    "analysis.action_brief": frozenset(
        {"goal", "since", "until", "thread", "include_archived", "evidence_limit"}
    ),
    "analysis.investigation": frozenset(
        {"goal", "since", "until", "thread", "include_archived", "evidence_limit"}
    ),
    "analysis.pattern_scan": frozenset(
        {
            "scan_type",
            "since",
            "until",
            "thread",
            "include_archived",
            "min_occurrences",
            "limit",
        }
    ),
    "evidence.local_export": frozenset(
        {
            "question",
            "since",
            "until",
            "thread",
            "include_archived",
            "min_occurrences",
            "evidence_limit",
        }
    ),
    "content.search": frozenset(
        {
            "query",
            "since",
            "until",
            "model",
            "effort",
            "thread",
            "include_archived",
            "limit",
            "offset",
            "max_snippet_chars",
        }
    ),
    "content.thread_trace": frozenset(
        {
            "thread",
            "thread_key",
            "session_id",
            "record_id",
            "since",
            "until",
            "include_archived",
            "limit",
            "offset",
            "max_snippet_chars",
        }
    ),
    "content.call_context": frozenset(
        {
            "record_id",
            "max_chars",
            "max_entries",
            "include_tool_output",
            "include_compaction_history",
            "diagnostics",
            "mode",
        }
    ),
    "visualization.suggest": frozenset({"question", "scope"}),
    "visualization.render": frozenset(
        {"kind", "source", "include_archived", "evidence_limit"}
    ),
    "compression.start": frozenset(
        {
            "since", "until", "thread", "include_archived", "model", "effort",
            "detector_families", "refresh",
        }
    ),
    "compression.status": frozenset({"run_id"}),
    "compression.profile": frozenset(
        {
            "run_id", "since", "until", "thread", "include_archived", "model", "effort",
            "detector_families",
        }
    ),
    "compression.candidates": frozenset(
        {
            "run_id", "family", "confidence_grade", "model", "thread", "since", "until",
            "min_exposure", "min_likely_savings", "sort", "limit", "offset", "max_payload_bytes",
        }
    ),
    "compression.candidate": frozenset(
        {"candidate_id", "evidence_mode", "evidence_limit", "max_excerpt_chars", "max_payload_bytes"}
    ),
    "compression.simulate": frozenset({"run_id", "candidate_ids", "max_payload_bytes"}),
    "diagnostics.get": frozenset(
        {
            "view", "limit", "offset", "since", "until", "model", "effort", "thread",
            "min_tokens", "fact_type", "fact_name", "fact_category", "fact_group",
            "include_archived", "sort", "direction",
        }
    ),
    "allowance.diagnostics": frozenset({"include_archived", "window_kind", "limit"}),
    "allowance.export": frozenset({"include_archived", "window_kind", "limit"}),
}


def _path_fingerprint(path: Path) -> str:
    import hashlib

    content = path.read_bytes() if path.is_file() else b"missing"
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _catalog_version() -> str:
    from .catalog import catalog_fingerprint

    return catalog_fingerprint()


@dataclass
class AgentApplicationServices:
    """Application-owned dependencies and direct operation methods.

    The fields mirror the existing HTTP v2 service bundle so tests and local
    callers can inject temporary paths without constructing transport objects.
    """

    db_path: Path = DEFAULT_DB_PATH
    pricing_path: Path = DEFAULT_PRICING_PATH
    allowance_path: Path = DEFAULT_ALLOWANCE_PATH
    rate_card_path: Path = DEFAULT_RATE_CARD_PATH
    thresholds_path: Path = DEFAULT_THRESHOLDS_PATH
    projects_path: Path = DEFAULT_PROJECTS_PATH
    codex_home: Path = DEFAULT_CODEX_HOME
    job_service: JobService | None = None
    compression_registry: CompressionJobRegistry | None = None

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path)
        self.pricing_path = Path(self.pricing_path)
        self.allowance_path = Path(self.allowance_path)
        self.rate_card_path = Path(self.rate_card_path)
        self.thresholds_path = Path(self.thresholds_path)
        self.projects_path = Path(self.projects_path)
        self.codex_home = Path(self.codex_home)
        if self.job_service is None:
            self.job_service = default_job_service()
        if self.compression_registry is None:
            self.compression_registry = CompressionJobRegistry()
        self.analysis_runtime = AnalysisRuntime(
            job_service=self.job_service,
            pricing_fingerprint=_path_fingerprint(self.pricing_path),
            rate_card_fingerprint=_path_fingerprint(self.rate_card_path),
            thresholds_fingerprint=_path_fingerprint(self.thresholds_path),
            catalog_version=_catalog_version(),
        )

    def status(self, request: StatusRequest) -> object:
        return get_status(
            replace(
                request,
                db_path=self.db_path,
                pricing_path=self.pricing_path,
                codex_home=self.codex_home,
            )
        )

    def refresh(self, request: RefreshRequest) -> object:
        outcome = refresh_usage(
            request,
            codex_home=self.codex_home,
            db_path=self.db_path,
            pricing_path=self.pricing_path,
            job_service=self.job_service,
        )
        return outcome.result if outcome.result is not None else outcome.job

    def analyze(self, request: AnalysisRequest) -> object:
        normalized = replace(request, filters=normalize_query_filters(request.filters))
        context = build_request_context(
            db_path=self.db_path,
            pricing_path=self.pricing_path,
            scope=_request_scope(normalized),
        )
        outcome = analyze_usage(
            normalized,
            replace(context, analysis_runtime=self.analysis_runtime),
        )
        return outcome.completed if outcome.completed is not None else outcome.job

    def query(self, request: QueryRequest) -> object:
        return query_usage(
            request,
            db_path=self.db_path,
            pricing_path=self.pricing_path,
            allowance_path=self.allowance_path,
        )

    def evidence(self, request: EvidenceRequest) -> object:
        return get_evidence(
            request,
            db_path=self.db_path,
            pricing_path=self.pricing_path,
            job_service=self.job_service,
        )

    def allowance(self, request: AllowanceRequest) -> object:
        result = get_allowance(request, db_path=self.db_path, job_service=self.job_service)
        payload = dict(result.payload)
        payload.setdefault("schema", result.result_schema)
        return payload

    def job_status(self, request: JobStatusRequest) -> object:
        return get_job_status(request, job_service=self.job_service)

    def capabilities(self) -> dict[str, object]:
        from .catalog import capabilities_payload

        payload = capabilities_payload()
        payload["analysis_goals"] = list(ANALYSIS_GOALS)
        payload["query_entities"] = {
            name: {
                "identity": capability.identity,
                "measures": sorted(capability.measures),
                "group_by": sorted(capability.group_by),
            }
            for name, capability in sorted(QUERY_ENTITY_CAPABILITIES.items())
        }
        payload["query_measures"] = sorted(ALL_QUERY_MEASURES)
        return payload

    def schema(self, operation: str) -> dict[str, object]:
        from .catalog import schema_payload

        return schema_payload(operation)

    def report(self, operation: str, arguments: dict[str, Any], *, privacy_mode: str) -> object:
        """Invoke one bounded, read-only report owned by an existing application module."""

        from codex_usage_tracker.allowance_intelligence.reports import (
            build_allowance_diagnostics_report,
            build_allowance_export_report,
        )
        from codex_usage_tracker.compression.api import (
            compression_candidate_detail,
            compression_candidates,
            compression_profile,
            compression_status,
            start_compression_analysis,
        )
        from codex_usage_tracker.compression.models import CompressionScope
        from codex_usage_tracker.compression.simulation_api import compression_simulate
        from codex_usage_tracker.context.api import load_call_context
        from codex_usage_tracker.diagnostics.api import run_doctor
        from codex_usage_tracker.diagnostics.dedupe import build_dedupe_diagnostics
        from codex_usage_tracker.diagnostics.reports import (
            build_diagnostics_fact_calls_report,
            build_diagnostics_facts_report,
            build_diagnostics_summary_report,
        )
        from codex_usage_tracker.diagnostics.snapshots import (
            build_diagnostic_commands_report,
            build_diagnostic_concentration_report,
            build_diagnostic_file_modifications_report,
            build_diagnostic_file_reads_report,
            build_diagnostic_git_interactions_report,
            build_diagnostic_guided_summary_report,
            build_diagnostic_overview_report,
            build_diagnostic_read_productivity_report,
            build_diagnostic_tool_output_report,
            build_diagnostic_usage_drain_report,
        )
        from codex_usage_tracker.reports.action_brief import build_action_brief_report
        from codex_usage_tracker.reports.agentic import (
            build_agentic_investigation_report,
            build_investigation_suggestions_report,
        )
        from codex_usage_tracker.reports.api import (
            build_expensive_calls_report,
            build_hypothesis_test_report,
            build_summary_report,
        )
        from codex_usage_tracker.reports.discovery import (
            build_content_search_report,
            build_pattern_scan_report,
            build_pricing_coverage_report,
            build_source_coverage_report,
            build_thread_trace_report,
        )
        from codex_usage_tracker.reports.investigation_walk import (
            build_investigation_walk_report,
            build_local_evidence_export_report,
        )
        from codex_usage_tracker.reports.query import build_recommendations_report
        from codex_usage_tracker.reports.visualization import (
            build_visualization_result,
            suggest_visualizations,
        )

        args = dict(arguments)
        allowed = _REPORT_ARGUMENT_FIELDS.get(operation)
        if allowed is None:
            raise LookupError(operation)
        unknown = sorted(set(args) - allowed)
        if unknown:
            raise ValueError(f"unsupported argument: {unknown[0]}")
        if operation == "system.doctor":
            return run_doctor(
                codex_home=self.codex_home,
                db_path=self.db_path,
                pricing_path=self.pricing_path,
                suggest_repair=False,
            )
        if operation in {"allowance.diagnostics", "allowance.export"}:
            builder = (
                build_allowance_diagnostics_report
                if operation == "allowance.diagnostics"
                else build_allowance_export_report
            )
            common = {
                "db_path": self.db_path,
                "allowance_path": self.allowance_path,
                "rate_card_path": self.rate_card_path,
                "include_archived": _bool(
                    args.pop("include_archived", False), "include_archived"
                ),
                "window_kind": _optional_str(
                    args.pop("window_kind", None), "window_kind"
                ),
                "limit": _optional_bounded_int(
                    args.pop("limit", None), "limit", 1, 1000
                ),
            }
            _no_arguments(args)
            if operation == "allowance.diagnostics":
                return builder(**common, privacy_mode=privacy_mode)
            return builder(**common)
        if operation == "system.coverage":
            return {
                "schema": "codex-usage-tracker.agent-system-coverage.v1",
                "pricing": payload_mapping(
                    build_pricing_coverage_report(
                        db_path=self.db_path,
                        pricing_path=self.pricing_path,
                        limit=_bounded_int(args.pop("limit", 1000), "limit", 1, 5000),
                        since=_optional_str(args.pop("since", None), "since"),
                    )
                ),
                "sources": payload_mapping(
                    build_source_coverage_report(
                        db_path=self.db_path,
                        include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                    )
                ),
            }
        if operation == "usage.statistics":
            return build_summary_report(
                db_path=self.db_path,
                pricing_path=self.pricing_path,
                projects_path=self.projects_path,
                group_by=_str(args.pop("group_by", "thread"), "group_by"),
                limit=_optional_bounded_int(args.pop("limit", 20), "limit", 1, 200),
                preset=_optional_str(args.pop("preset", None), "preset"),
                since=_optional_str(args.pop("since", None), "since"),
                privacy_mode=privacy_mode,
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
            )
        if operation == "diagnostics.get":
            view = _str(args.pop("view", "summary"), "view")
            include_archived = _bool(
                args.pop("include_archived", False), "include_archived"
            )
            if view in {"summary", "facts"}:
                common = {
                    "db_path": self.db_path,
                    "limit": _bounded_int(
                        args.pop("limit", 20 if view == "summary" else 50),
                        "limit",
                        1,
                        200,
                    ),
                    "since": _optional_str(args.pop("since", None), "since"),
                    "until": _optional_str(args.pop("until", None), "until"),
                    "model": _optional_str(args.pop("model", None), "model"),
                    "effort": _optional_str(args.pop("effort", None), "effort"),
                    "thread": _optional_str(args.pop("thread", None), "thread"),
                    "min_tokens": _optional_bounded_int(
                        args.pop("min_tokens", None), "min_tokens", 0, 10**12
                    ),
                    "fact_type": _optional_str(args.pop("fact_type", None), "fact_type"),
                    "fact_name": _optional_str(args.pop("fact_name", None), "fact_name"),
                    "fact_category": _optional_str(
                        args.pop("fact_category", None), "fact_category"
                    ),
                    "include_archived": include_archived,
                    "sort": _str(args.pop("sort", "uncached"), "sort"),
                    "direction": _str(args.pop("direction", "desc"), "direction"),
                }
                if view == "facts":
                    common["fact_group"] = _optional_str(
                        args.pop("fact_group", None), "fact_group"
                    )
                    common["view"] = "facts"
                _no_arguments(args)
                builder = (
                    build_diagnostics_summary_report
                    if view == "summary"
                    else build_diagnostics_facts_report
                )
                return builder(**common)
            if view == "fact_calls":
                result = build_diagnostics_fact_calls_report(
                    db_path=self.db_path,
                    fact_type=_str(args.pop("fact_type", None), "fact_type"),
                    fact_name=_str(args.pop("fact_name", None), "fact_name"),
                    limit=_bounded_int(args.pop("limit", 50), "limit", 1, 200),
                    offset=_bounded_int(args.pop("offset", 0), "offset", 0, 1_000_000),
                    since=_optional_str(args.pop("since", None), "since"),
                    until=_optional_str(args.pop("until", None), "until"),
                    model=_optional_str(args.pop("model", None), "model"),
                    effort=_optional_str(args.pop("effort", None), "effort"),
                    thread=_optional_str(args.pop("thread", None), "thread"),
                    min_tokens=_optional_bounded_int(
                        args.pop("min_tokens", None), "min_tokens", 0, 10**12
                    ),
                    include_archived=include_archived,
                    sort=_str(args.pop("sort", "tokens"), "sort"),
                    direction=_str(args.pop("direction", "desc"), "direction"),
                    privacy_mode=privacy_mode,
                )
                _no_arguments(args)
                return result
            snapshots = {
                "overview": build_diagnostic_overview_report,
                "tool_output": build_diagnostic_tool_output_report,
                "commands": build_diagnostic_commands_report,
                "git_interactions": build_diagnostic_git_interactions_report,
                "file_reads": build_diagnostic_file_reads_report,
                "file_modifications": build_diagnostic_file_modifications_report,
                "read_productivity": build_diagnostic_read_productivity_report,
                "concentration": build_diagnostic_concentration_report,
                "guided_summary": build_diagnostic_guided_summary_report,
                "usage_drain": build_diagnostic_usage_drain_report,
            }
            builder = snapshots.get(view)
            if builder is None:
                raise ValueError(f"unsupported diagnostics view: {view}")
            _no_arguments(args)
            if view == "usage_drain":
                return builder(
                    db_path=self.db_path,
                    pricing_path=self.pricing_path,
                    allowance_path=self.allowance_path,
                    rate_card_path=self.rate_card_path,
                    include_archived=include_archived,
                    refresh=False,
                )
            return builder(
                db_path=self.db_path,
                include_archived=include_archived,
                refresh=False,
            )
        if operation == "usage.dedupe":
            return build_dedupe_diagnostics(
                db_path=self.db_path,
                limit=_bounded_int(args.pop("limit", 100), "limit", 1, 500),
            )
        if operation == "usage.recommendations":
            return build_recommendations_report(
                db_path=self.db_path,
                pricing_path=self.pricing_path,
                allowance_path=self.allowance_path,
                rate_card_path=self.rate_card_path,
                thresholds_path=self.thresholds_path,
                projects_path=self.projects_path,
                since=_optional_str(args.pop("since", None), "since"),
                until=_optional_str(args.pop("until", None), "until"),
                model=_optional_str(args.pop("model", None), "model"),
                effort=_optional_str(args.pop("effort", None), "effort"),
                thread=_optional_str(args.pop("thread", None), "thread"),
                project=_optional_str(args.pop("project", None), "project"),
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                min_score=_optional_number(args.pop("min_score", None), "min_score"),
                limit=_bounded_int(args.pop("limit", 20), "limit", 1, 100),
                source_limit=_optional_bounded_int(args.pop("source_limit", None), "source_limit", 1, 5000),
                privacy_mode=privacy_mode,
            )
        if operation == "usage.report":
            limit = _bounded_int(args.pop("limit", 20), "limit", 1, 100)
            since = _optional_str(args.pop("since", None), "since")
            include_archived = _bool(args.pop("include_archived", False), "include_archived")
            _no_arguments(args)
            return {
                "schema": "codex-usage-tracker.agent-report-pack.v1",
                "summary": payload_mapping(
                    build_summary_report(
                        db_path=self.db_path,
                        pricing_path=self.pricing_path,
                        projects_path=self.projects_path,
                        group_by="thread",
                        limit=limit,
                        since=since,
                        privacy_mode=privacy_mode,
                        include_archived=include_archived,
                    )
                ),
                "expensive": payload_mapping(
                    build_expensive_calls_report(
                        db_path=self.db_path,
                        pricing_path=self.pricing_path,
                        limit=limit,
                        since=since,
                        privacy_mode=privacy_mode,
                    )
                ),
            }
        if operation == "analysis.suggest":
            return build_investigation_suggestions_report(
                goal=_optional_str(args.pop("goal", None), "goal"),
                since=_optional_str(args.pop("since", None), "since"),
                until=_optional_str(args.pop("until", None), "until"),
                thread=_optional_str(args.pop("thread", None), "thread"),
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                limit=_optional_bounded_int(args.pop("limit", 10), "limit", 1, 100),
                privacy_mode=privacy_mode,
            )
        if operation == "analysis.hypotheses":
            return build_hypothesis_test_report(
                db_path=self.db_path,
                pricing_path=self.pricing_path,
                allowance_path=self.allowance_path,
                projects_path=self.projects_path,
                question=_str(args.pop("question", None), "question"),
                hypotheses=cast(Any, args.pop("hypotheses", None)),
                since=_optional_str(args.pop("since", None), "since"),
                until=_optional_str(args.pop("until", None), "until"),
                thread=_optional_str(args.pop("thread", None), "thread"),
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                evidence_limit=_bounded_int(args.pop("evidence_limit", 5), "evidence_limit", 1, 20),
                privacy_mode=privacy_mode,
            )
        if operation in {"analysis.action_brief", "analysis.investigation"}:
            common = _investigation_arguments(args, privacy_mode)
            builder = (
                build_action_brief_report
                if operation == "analysis.action_brief"
                else build_agentic_investigation_report
            )
            return builder(
                db_path=self.db_path,
                pricing_path=self.pricing_path,
                allowance_path=self.allowance_path,
                projects_path=self.projects_path,
                **common,
            )
        if operation == "analysis.pattern_scan":
            return build_pattern_scan_report(
                db_path=self.db_path,
                scan_type=_str(args.pop("scan_type", "all"), "scan_type"),
                since=_optional_str(args.pop("since", None), "since"),
                until=_optional_str(args.pop("until", None), "until"),
                thread=_optional_str(args.pop("thread", None), "thread"),
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                min_occurrences=_bounded_int(args.pop("min_occurrences", 2), "min_occurrences", 2, 100),
                limit=_optional_bounded_int(args.pop("limit", 20), "limit", 1, 100),
                privacy_mode=privacy_mode,
            )
        if operation == "evidence.local_export":
            return build_local_evidence_export_report(
                db_path=self.db_path,
                question=_str(args.pop("question", None), "question"),
                since=_optional_str(args.pop("since", None), "since"),
                until=_optional_str(args.pop("until", None), "until"),
                thread=_optional_str(args.pop("thread", None), "thread"),
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                min_occurrences=_bounded_int(args.pop("min_occurrences", 2), "min_occurrences", 2, 100),
                evidence_limit=_bounded_int(args.pop("evidence_limit", 5), "evidence_limit", 1, 20),
            )
        if operation == "content.search":
            return build_content_search_report(
                db_path=self.db_path,
                query=_str(args.pop("query", None), "query"),
                since=_optional_str(args.pop("since", None), "since"),
                until=_optional_str(args.pop("until", None), "until"),
                model=_optional_str(args.pop("model", None), "model"),
                effort=_optional_str(args.pop("effort", None), "effort"),
                thread=_optional_str(args.pop("thread", None), "thread"),
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                limit=_optional_bounded_int(args.pop("limit", 20), "limit", 1, 100),
                offset=_bounded_int(args.pop("offset", 0), "offset", 0, 1_000_000),
                max_snippet_chars=_optional_bounded_int(args.pop("max_snippet_chars", 800), "max_snippet_chars", 1, 4000),
                privacy_mode=privacy_mode,
            )
        if operation == "content.thread_trace":
            return build_thread_trace_report(
                db_path=self.db_path,
                thread=_optional_str(args.pop("thread", None), "thread"),
                thread_key=_optional_str(args.pop("thread_key", None), "thread_key"),
                session_id=_optional_str(args.pop("session_id", None), "session_id"),
                record_id=_optional_str(args.pop("record_id", None), "record_id"),
                since=_optional_str(args.pop("since", None), "since"),
                until=_optional_str(args.pop("until", None), "until"),
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                limit=_optional_bounded_int(args.pop("limit", 100), "limit", 1, 200),
                offset=_bounded_int(args.pop("offset", 0), "offset", 0, 1_000_000),
                max_snippet_chars=_optional_bounded_int(args.pop("max_snippet_chars", 800), "max_snippet_chars", 1, 4000),
                privacy_mode=privacy_mode,
            )
        if operation == "content.call_context":
            return load_call_context(
                _str(args.pop("record_id", None), "record_id"),
                db_path=self.db_path,
                max_chars=_bounded_int(args.pop("max_chars", 20_000), "max_chars", 1, 50_000),
                max_entries=_bounded_int(args.pop("max_entries", 80), "max_entries", 1, 200),
                include_tool_output=_bool(args.pop("include_tool_output", False), "include_tool_output"),
                include_compaction_history=_bool(args.pop("include_compaction_history", False), "include_compaction_history"),
                diagnostics=_bool(args.pop("diagnostics", False), "diagnostics"),
                mode=_str(args.pop("mode", "quick"), "mode"),
            )
        if operation == "visualization.suggest":
            result = suggest_visualizations(
                _str(args.pop("question", None), "question"),
                scope=_str(args.pop("scope", "auto"), "scope"),
            )
            _no_arguments(args)
            return result
        if operation == "visualization.render":
            kind = _str(args.pop("kind", None), "kind")
            source = args.pop("source", None)
            if not isinstance(source, dict):
                raise ValueError("source must be an object")
            result = build_visualization_result(
                kind,
                source,
                include_archived=_bool(args.pop("include_archived", False), "include_archived"),
                evidence_limit=_bounded_int(args.pop("evidence_limit", 12), "evidence_limit", 1, 100),
            )
            _no_arguments(args)
            return result
        if operation == "compression.start":
            scope = _compression_scope(args, CompressionScope)
            detector_families = _optional_str_sequence(
                args.pop("detector_families", None), "detector_families"
            )
            refresh = _bool(args.pop("refresh", False), "refresh")
            _no_arguments(args)
            return start_compression_analysis(
                self.db_path,
                scope,
                detector_families=detector_families,
                refresh=refresh,
                registry=cast(CompressionJobRegistry, self.compression_registry),
            )
        if operation == "compression.status":
            run_id = _str(args.pop("run_id", None), "run_id")
            _no_arguments(args)
            return compression_status(
                self.db_path,
                run_id=run_id,
                registry=cast(CompressionJobRegistry, self.compression_registry),
            )
        if operation == "compression.profile":
            run_id = _optional_str(args.pop("run_id", None), "run_id")
            scope = None if run_id is not None else _compression_scope(args, CompressionScope)
            detector_families = _optional_str_sequence(
                args.pop("detector_families", None), "detector_families"
            )
            _no_arguments(args)
            return compression_profile(
                self.db_path,
                run_id=run_id,
                scope=scope,
                detector_families=detector_families,
            )
        if operation == "compression.candidates":
            result = compression_candidates(
                self.db_path,
                run_id=_str(args.pop("run_id", None), "run_id"),
                family=_optional_str(args.pop("family", None), "family"),
                confidence_grade=_optional_str(
                    args.pop("confidence_grade", None), "confidence_grade"
                ),
                model=_optional_str(args.pop("model", None), "model"),
                thread=_optional_str(args.pop("thread", None), "thread"),
                since=_optional_str(args.pop("since", None), "since"),
                until=_optional_str(args.pop("until", None), "until"),
                min_exposure=_bounded_int(
                    args.pop("min_exposure", 0), "min_exposure", 0, 10**12
                ),
                min_likely_savings=_bounded_int(
                    args.pop("min_likely_savings", 0), "min_likely_savings", 0, 10**12
                ),
                sort=_str(args.pop("sort", "adjusted_likely"), "sort"),
                limit=_optional_bounded_int(args.pop("limit", 50), "limit", 1, 200),
                offset=_bounded_int(args.pop("offset", 0), "offset", 0, 1_000_000),
                max_payload_bytes=_optional_bounded_int(
                    args.pop("max_payload_bytes", None), "max_payload_bytes", 1024, 256 * 1024
                ),
            )
            _no_arguments(args)
            return result
        if operation == "compression.candidate":
            evidence_mode = _str(
                args.pop("evidence_mode", "handles"), "evidence_mode"
            )
            if evidence_mode == "excerpts":
                raise ValueError(
                    "compression.candidate does not expose indexed excerpts; use content operations"
                )
            result = compression_candidate_detail(
                self.db_path,
                candidate_id=_str(args.pop("candidate_id", None), "candidate_id"),
                evidence_mode=evidence_mode,
                evidence_limit=_bounded_int(
                    args.pop("evidence_limit", 20), "evidence_limit", 1, 100
                ),
                max_excerpt_chars=_bounded_int(
                    args.pop("max_excerpt_chars", 400), "max_excerpt_chars", 1, 4000
                ),
                max_payload_bytes=_bounded_int(
                    args.pop("max_payload_bytes", 24_576),
                    "max_payload_bytes",
                    1024,
                    256 * 1024,
                ),
            )
            _no_arguments(args)
            return result
        if operation == "compression.simulate":
            result = compression_simulate(
                self.db_path,
                run_id=_str(args.pop("run_id", None), "run_id"),
                candidate_ids=_str_sequence(args.pop("candidate_ids", None), "candidate_ids"),
                max_payload_bytes=_bounded_int(
                    args.pop("max_payload_bytes", 16_384),
                    "max_payload_bytes",
                    1024,
                    256 * 1024,
                ),
            )
            _no_arguments(args)
            return result
        if operation == "analysis.investigation_walk":
            return build_investigation_walk_report(db_path=self.db_path, **args)
        raise LookupError(operation)


def _investigation_arguments(args: dict[str, Any], privacy_mode: str) -> dict[str, object]:
    values: dict[str, object] = {
        "goal": _str(args.pop("goal", "token_waste"), "goal"),
        "since": _optional_str(args.pop("since", None), "since"),
        "until": _optional_str(args.pop("until", None), "until"),
        "thread": _optional_str(args.pop("thread", None), "thread"),
        "include_archived": _bool(args.pop("include_archived", False), "include_archived"),
        "evidence_limit": _bounded_int(args.pop("evidence_limit", 5), "evidence_limit", 1, 20),
        "privacy_mode": privacy_mode,
    }
    _no_arguments(args)
    return values


def _no_arguments(arguments: dict[str, Any]) -> None:
    if arguments:
        raise ValueError(f"unsupported argument: {sorted(arguments)[0]}")


def _str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _str(value, name)


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a bool")
    return cast(bool, value)


def _bounded_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= cast(int, value) <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return cast(int, value)


def _optional_bounded_int(
    value: object, name: str, minimum: int, maximum: int
) -> int | None:
    if value is None:
        return None
    return _bounded_int(value, name, minimum, maximum)


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float}:
        raise ValueError(f"{name} must be a number")
    return float(cast(float, value))


def _compression_scope(args: dict[str, Any], scope_type: Any) -> object:
    return scope_type(
        since=_optional_str(args.pop("since", None), "since"),
        until=_optional_str(args.pop("until", None), "until"),
        thread=_optional_str(args.pop("thread", None), "thread"),
        include_archived=_bool(args.pop("include_archived", False), "include_archived"),
        model=_optional_str(args.pop("model", None), "model"),
        effort=_optional_str(args.pop("effort", None), "effort"),
    )


def _str_sequence(value: object, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} must be an array of strings")
    if not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} must contain non-empty strings")
    return tuple(cast(list[str] | tuple[str, ...], value))


def _optional_str_sequence(value: object, name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _str_sequence(value, name)


def _request_scope(request: AnalysisRequest):
    from codex_usage_tracker.application.requests import RequestScope

    filters = request.filters
    return RequestScope(
        since=filters.since,
        until=filters.until,
        history=cast(Any, request.history),
        project=filters.project,
        thread_key=filters.thread_key,
        model=filters.model,
        effort=filters.effort,
    )


__all__ = ["AgentApplicationServices"]
