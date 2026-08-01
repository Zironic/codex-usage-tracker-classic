from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_usage_tracker.server.agent_runtime import (
    clear_agent_runtime,
    publish_agent_runtime,
    read_agent_runtime,
)


def test_publish_and_clear_agent_runtime(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "runtime" / "agent-service.json"
    credential_path = tmp_path / "runtime" / "agent-service.token"

    runtime = publish_agent_runtime(
        origin="http://127.0.0.1:47821",
        api_token="secret-token",
        enabled_scopes=("compute", "aggregate_read", "compute"),
        server_instance_id="server-test",
        descriptor_path=descriptor_path,
        credential_path=credential_path,
    )

    assert credential_path.read_text(encoding="utf-8").strip() == "secret-token"
    payload = json.loads(descriptor_path.read_text(encoding="utf-8"))
    assert payload["origin"] == "http://127.0.0.1:47821"
    assert payload["enabled_scopes"] == ["aggregate_read", "compute"]
    assert "secret-token" not in descriptor_path.read_text(encoding="utf-8")
    assert read_agent_runtime(descriptor_path) == runtime.descriptor
    assert runtime.descriptor.server_instance_id == "server-test"

    clear_agent_runtime(runtime)
    assert not descriptor_path.exists()
    assert not credential_path.exists()


def test_clear_does_not_remove_newer_runtime(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "runtime" / "agent-service.json"
    credential_path = tmp_path / "runtime" / "agent-service.token"
    older = publish_agent_runtime(
        origin="http://127.0.0.1:47821",
        api_token="old",
        enabled_scopes=("aggregate_read",),
        descriptor_path=descriptor_path,
        credential_path=credential_path,
    )
    newer = publish_agent_runtime(
        origin="http://127.0.0.1:47822",
        api_token="new",
        enabled_scopes=("aggregate_read",),
        descriptor_path=descriptor_path,
        credential_path=credential_path,
    )

    clear_agent_runtime(older)
    assert read_agent_runtime(descriptor_path) == newer.descriptor
    assert credential_path.read_text(encoding="utf-8").strip() == "new"


@pytest.mark.parametrize("origin", ["http://example.com:47821", "https://127.0.0.1:47821"])
def test_publish_rejects_non_loopback_http_origin(tmp_path: Path, origin: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        publish_agent_runtime(
            origin=origin,
            api_token="token",
            enabled_scopes=("aggregate_read",),
            descriptor_path=tmp_path / "runtime" / "agent-service.json",
            credential_path=tmp_path / "runtime" / "agent-service.token",
        )


def test_read_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "agent-service.json"
    path.write_text('{"schema":"unknown"}', encoding="utf-8")
    assert read_agent_runtime(path) is None
