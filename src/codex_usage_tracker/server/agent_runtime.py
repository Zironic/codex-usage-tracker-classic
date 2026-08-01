"""Private runtime discovery state for the localhost agent API."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from codex_usage_tracker.core.paths import (
    DEFAULT_AGENT_CREDENTIAL_PATH,
    DEFAULT_AGENT_DESCRIPTOR_PATH,
)

_DESCRIPTOR_SCHEMA = "codex-usage-tracker.agent-service.v1"


@dataclass(frozen=True)
class AgentRuntimeDescriptor:
    """Discoverable metadata for one managed localhost server instance."""

    schema: str
    origin: str
    server_instance_id: str
    pid: int
    credential_path: str
    enabled_scopes: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        value = asdict(self)
        value["enabled_scopes"] = list(self.enabled_scopes)
        return value


@dataclass(frozen=True)
class PublishedAgentRuntime:
    descriptor: AgentRuntimeDescriptor
    descriptor_path: Path
    credential_path: Path


def publish_agent_runtime(
    *,
    origin: str,
    api_token: str,
    enabled_scopes: tuple[str, ...],
    server_instance_id: str | None = None,
    descriptor_path: Path = DEFAULT_AGENT_DESCRIPTOR_PATH,
    credential_path: Path = DEFAULT_AGENT_CREDENTIAL_PATH,
) -> PublishedAgentRuntime:
    """Atomically publish a token and descriptor under the tracker-owned directory."""

    if not origin.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:")):
        raise ValueError("agent API origin must be loopback")
    if not api_token:
        raise ValueError("agent API token must not be empty")
    if descriptor_path.parent != credential_path.parent:
        raise ValueError("agent descriptor and credential must share a runtime directory")

    runtime_dir = descriptor_path.parent
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _restrict_permissions(runtime_dir, 0o700)
    _atomic_write(credential_path, api_token + "\n", mode=0o600)
    descriptor = AgentRuntimeDescriptor(
        schema=_DESCRIPTOR_SCHEMA,
        origin=origin,
        server_instance_id=server_instance_id or secrets.token_urlsafe(16),
        pid=os.getpid(),
        credential_path=str(credential_path),
        enabled_scopes=tuple(sorted(set(enabled_scopes))),
    )
    _atomic_write(
        descriptor_path,
        json.dumps(descriptor.payload(), sort_keys=True, separators=(",", ":")) + "\n",
        mode=0o600,
    )
    return PublishedAgentRuntime(descriptor, descriptor_path, credential_path)


def clear_agent_runtime(runtime: PublishedAgentRuntime) -> None:
    """Remove only files still owned by the published server instance."""

    current = read_agent_runtime(runtime.descriptor_path)
    if current is None or current.server_instance_id != runtime.descriptor.server_instance_id:
        return
    runtime.credential_path.unlink(missing_ok=True)
    runtime.descriptor_path.unlink(missing_ok=True)


def read_agent_runtime(path: Path = DEFAULT_AGENT_DESCRIPTOR_PATH) -> AgentRuntimeDescriptor | None:
    """Read one valid descriptor without following arbitrary schema fields."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != _DESCRIPTOR_SCHEMA:
        return None
    try:
        scopes = payload["enabled_scopes"]
        if not isinstance(scopes, list) or any(not isinstance(item, str) for item in scopes):
            return None
        return AgentRuntimeDescriptor(
            schema=_DESCRIPTOR_SCHEMA,
            origin=str(payload["origin"]),
            server_instance_id=str(payload["server_instance_id"]),
            pid=int(payload["pid"]),
            credential_path=str(payload["credential_path"]),
            enabled_scopes=tuple(scopes),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _atomic_write(path: Path, content: str, *, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _restrict_permissions(temporary, mode)
        os.replace(temporary, path)
        _restrict_permissions(path, mode)
    finally:
        temporary.unlink(missing_ok=True)


def _restrict_permissions(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError as exc:
        raise RuntimeError(f"could not restrict agent runtime permissions: {path}") from exc
