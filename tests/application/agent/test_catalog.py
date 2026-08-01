from __future__ import annotations

from collections import Counter

import pytest

from codex_usage_tracker.application.agent import (
    OPERATION_CATALOG,
    AgentError,
    AgentRequest,
    capabilities_payload,
    catalog_fingerprint,
    get_operation,
    legacy_operation_map,
    schema_payload,
)


def test_catalog_names_and_schema_ids_are_unique_and_deterministic() -> None:
    assert len({item.name for item in OPERATION_CATALOG}) == len(OPERATION_CATALOG)
    assert len({item.request_schema for item in OPERATION_CATALOG}) == len(OPERATION_CATALOG)
    assert len({item.result_schema for item in OPERATION_CATALOG}) == len(OPERATION_CATALOG)
    assert tuple(item.name for item in OPERATION_CATALOG) == tuple(
        sorted(item.name for item in OPERATION_CATALOG)
    )
    assert catalog_fingerprint() == catalog_fingerprint(tuple(reversed(OPERATION_CATALOG)))


def test_core_legacy_names_map_to_canonical_operations() -> None:
    expected = {
        "usage_status": "system.status",
        "usage_refresh": "refresh.start",
        "usage_job_status": "job.get",
        "usage_query": "usage.query",
        "usage_analyze": "analysis.run",
        "usage_evidence": "evidence.get",
        "usage_allowance": "allowance.status",
    }
    mapping = legacy_operation_map()
    assert {name: mapping[name] for name in expected} == expected


def test_capabilities_report_disabled_planned_operations_truthfully() -> None:
    payload = capabilities_payload()
    assert payload["catalog_revision"] == catalog_fingerprint()
    operations = {item["name"]: item for item in payload["operations"]}  # type: ignore[index]
    assert operations["usage.query"]["enabled"] is True
    assert operations["content.search"]["enabled"] is True
    assert operations["content.call_context"]["authorization_scope"] == "raw_context_read"
    assert operations["compression.start"]["enabled"] is True
    assert operations["artifact.get"]["enabled"] is False
    assert operations["artifact.get"]["disabled_reason"]


def test_spec_and_contracts_detach_caller_owned_mappings() -> None:
    arguments = {"filters": {"project": "demo"}}
    request = AgentRequest(operation="usage.query", arguments=arguments)
    arguments["filters"]["project"] = "changed"
    assert request.arguments["filters"]["project"] == "demo"
    with pytest.raises(TypeError):
        request.arguments["new"] = 1  # type: ignore[index]

    spec = get_operation("usage.query")
    assert spec is not None
    descriptor = spec.to_payload()
    descriptor["legacy_names"] = []
    assert spec.legacy_names


def test_schema_payload_rejects_unknown_operation() -> None:
    assert schema_payload("usage.query")["result_schema"] == "codex-usage-tracker.query.v2"
    with pytest.raises(KeyError):
        schema_payload("missing")


def test_error_uses_nested_stable_error_shape() -> None:
    payload = AgentError(code="x", message="bad", operation="usage.query").to_payload()
    assert payload["schema"] == "codex-usage-tracker.agent-error.v1"
    assert payload["error"]["code"] == "x"  # type: ignore[index]


def test_no_duplicate_legacy_aliases() -> None:
    aliases = [alias for item in OPERATION_CATALOG for alias in item.legacy_names]
    assert not [alias for alias, count in Counter(aliases).items() if count > 1]
