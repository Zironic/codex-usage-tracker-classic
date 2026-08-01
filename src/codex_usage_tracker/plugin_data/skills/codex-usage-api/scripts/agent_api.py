#!/usr/bin/env python3
"""Small, dependency-free client for the local Codex Usage Tracker agent API.

The helper deliberately owns transport only.  It discovers the tracker from a
private descriptor, sends one request, and prints the server's JSON unchanged;
it does not interpret usage data or inspect tracker storage.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit, urlunsplit
from urllib.request import Request, urlopen

AGENT_ROUTE = "/api/v2/agent"
REQUEST_SCHEMA = "codex-usage-tracker.agent-request.v1"
DEFAULT_RUNTIME_DIR = Path.home() / ".codex-usage-tracker" / "runtime"
DEFAULT_DESCRIPTOR_PATH = DEFAULT_RUNTIME_DIR / "agent-service.json"
DESCRIPTOR_ENV_VARS = (
    "CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR",
    "CODEX_USAGE_AGENT_DESCRIPTOR",
    "CODEX_USAGE_TRACKER_DESCRIPTOR",
)
CREDENTIAL_ENV_VARS = (
    "CODEX_USAGE_TRACKER_AGENT_CREDENTIAL",
    "CODEX_USAGE_AGENT_CREDENTIAL",
    "CODEX_USAGE_TRACKER_AGENT_CREDENTIAL_PATH",
    "CODEX_USAGE_TRACKER_CREDENTIAL_PATH",
)
MAX_TIMEOUT_SECONDS = 300.0
MAX_POLL_INTERVAL_SECONDS = 60.0
MAX_POLL_COUNT = 1000
DEFAULT_POLL_INTERVAL_SECONDS = 0.4
DEFAULT_MAX_POLLS = 120
TERMINAL_JOB_STATES = frozenset(
    {"completed", "complete", "succeeded", "success", "failed", "error", "cancelled", "canceled"}
)


class AgentApiError(Exception):
    """An actionable, safe-to-print helper error."""


def _error(message: str) -> AgentApiError:
    return AgentApiError(message)


def _loopback_host(host: str | None) -> bool:
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _parse_url(raw_url: str) -> SplitResult:
    try:
        parsed = urlsplit(raw_url.strip())
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise _error("Invalid agent API URL; provide a loopback http(s) URL.") from exc
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise _error("Agent API URL must use http or https.")
    if not _loopback_host(hostname):
        raise _error("Agent API URL must target a loopback host (localhost, 127.0.0.1, or ::1).")
    if parsed.username is not None or parsed.password is not None:
        raise _error("Agent API URL must not contain a username or credential.")
    if parsed.query or parsed.fragment:
        raise _error("Agent API URL must not contain a query or fragment.")
    return parsed


def normalize_base_url(raw_url: str) -> str:
    """Validate a loopback origin and append the agent route when needed."""

    parsed = _parse_url(raw_url)
    path = parsed.path.rstrip("/")
    if path in {"", "/api/v2", AGENT_ROUTE}:
        path = AGENT_ROUTE
    else:
        raise _error(f"Agent API URL must be an origin or {AGENT_ROUTE}.")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _first_environment(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _read_descriptor(path_value: str) -> tuple[str, str | None]:
    path = Path(path_value).expanduser()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _error(
            "Agent service descriptor is unavailable; start the managed local service "
            "or pass --base-url with --credential."
        ) from exc
    try:
        descriptor = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("Agent service descriptor is not valid UTF-8 JSON.") from exc
    if not isinstance(descriptor, dict):
        raise _error("Agent service descriptor must contain a JSON object.")
    endpoint = next(
        (
            descriptor.get(key)
            for key in ("agentEndpoint", "agent_endpoint", "apiBase", "api_base", "origin")
            if descriptor.get(key)
        ),
        None,
    )
    origin = descriptor.get("origin")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise _error("Agent service descriptor has no usable loopback origin.")
    if endpoint.startswith("/"):
        if not isinstance(origin, str) or not origin.strip():
            raise _error("Agent service descriptor has no usable loopback origin.")
        endpoint = origin.rstrip("/") + endpoint
    credential = descriptor.get("credential_path")
    if credential is None:
        credential = descriptor.get("credentialPath")
    if credential is not None and not isinstance(credential, str):
        raise _error("Agent service descriptor has an invalid credential path.")
    if isinstance(credential, str) and credential and not Path(credential).expanduser().is_absolute():
        credential = str((path.parent / credential).resolve())
    return normalize_base_url(endpoint), credential


def _resolve_target(descriptor_value: str | None, base_url: str | None) -> tuple[str, str | None]:
    descriptor_path = descriptor_value or _first_environment(DESCRIPTOR_ENV_VARS)
    descriptor_url: str | None = None
    descriptor_credential: str | None = None
    if descriptor_path:
        descriptor_url, descriptor_credential = _read_descriptor(descriptor_path)
    elif not base_url:
        descriptor_url, descriptor_credential = _read_descriptor(str(DEFAULT_DESCRIPTOR_PATH))
    if base_url:
        return normalize_base_url(base_url), descriptor_credential
    if descriptor_url:
        return descriptor_url, descriptor_credential
    raise _error(
        "No agent service was discovered. Pass --base-url with --credential, "
        "or set CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR to the private descriptor path."
    )


def _resolve_credential(
    explicit_path: str | None, descriptor_path: str | None, *, required: bool
) -> str | None:
    value = explicit_path or descriptor_path or _first_environment(CREDENTIAL_ENV_VARS)
    if not value:
        if required:
            raise _error(
                "No agent API credential was supplied. Pass --credential or set "
                "CODEX_USAGE_TRACKER_AGENT_CREDENTIAL to a private credential path."
            )
        return None
    path = Path(value).expanduser()
    try:
        credential = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise _error("Agent API credential file is unavailable or unreadable.") from exc
    if not credential:
        raise _error("Agent API credential file is empty.")
    if any(character.isspace() for character in credential):
        raise _error("Agent API credential file contains invalid whitespace.")
    return credential


def _parse_json_object(raw: str, label: str) -> dict[str, Any]:
    if raw.startswith("@"):
        raise _error(f"{label} must be inline JSON; the helper does not read request files.")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _error(f"{label} must be valid JSON: {exc.msg}.") from exc
    if not isinstance(value, dict):
        raise _error(f"{label} must be a JSON object.")
    return value


def _request_body(args: argparse.Namespace) -> bytes:
    if args.request_json is not None:
        if args.operation or args.operation_pos or args.arguments_json is not None:
            raise _error("--request cannot be combined with --operation or --arguments.")
        body = _parse_json_object(args.request_json, "--request")
    else:
        operation = args.operation or args.operation_pos
        if not operation:
            raise _error("Choose --capabilities or provide an operation for POST.")
        if args.arguments_json is None:
            operation_arguments: dict[str, Any] = {}
        else:
            operation_arguments = _parse_json_object(args.arguments_json, "--arguments")
        body = {
            "schema": REQUEST_SCHEMA,
            "operation": operation,
            "arguments": operation_arguments,
        }
        if args.request_id is not None:
            body["request_id"] = args.request_id
        if args.privacy_mode is not None:
            body["privacy_mode"] = args.privacy_mode
        if args.execution is not None:
            body["execution"] = args.execution
    try:
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _error(f"Request JSON cannot be encoded: {exc}.") from exc


def _safe_response_error(status: int) -> str:
    if status == 401:
        return "Agent API rejected the credential; check the private credential path."
    if status == 403:
        return "Agent API denied this operation scope; inspect GET capabilities."
    if status == 404:
        return "Agent API route or operation was not found; inspect GET capabilities."
    if status == 503:
        return "Agent service is unavailable or still starting; retry after it is healthy."
    return f"Agent API request failed with HTTP {status}."


def _http_request(url: str, method: str, body: bytes | None, credential: str | None, timeout: float) -> tuple[int, bytes]:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    if credential:
        headers["X-Codex-Usage-Token"] = credential
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except HTTPError as exc:
        raise _error(_safe_response_error(exc.code)) from None
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError) or isinstance(exc, TimeoutError):
            raise _error("Agent service did not respond before the timeout; verify it is running.") from None
        raise _error(
            "Agent service could not be reached; verify the descriptor/base URL and start the local service."
        ) from None


def _object_at(value: Any, key: str) -> dict[str, Any] | None:
    candidate = value.get(key) if isinstance(value, dict) else None
    return candidate if isinstance(candidate, dict) else None


def _job_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for candidate in (payload, _object_at(payload, "job"), _object_at(payload, "result")):
        if not candidate:
            continue
        for key in ("job_id", "id"):
            value = candidate.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _job_data(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return _object_at(payload, "job") or _object_at(payload, "result") or payload


def _job_status(payload: Any) -> str | None:
    data = _job_data(payload)
    if not data:
        return None
    value = data.get("status")
    return value.casefold() if isinstance(value, str) else None


def _job_progress(payload: Any) -> tuple[Any, Any]:
    data = _job_data(payload) or {}
    percent = data.get("percent_complete", data.get("percent"))
    progress = data.get("progress")
    if isinstance(progress, dict):
        percent = progress.get("percent", progress.get("percent_complete", percent))
    stage = data.get("stage", data.get("current_stage"))
    if stage is None and isinstance(progress, dict):
        stage = progress.get("stage")
    return percent, stage


def _print_progress(job_id: str, payload: Any, credential: str | None) -> None:
    status = _job_status(payload) or "unknown"
    percent, stage = _job_progress(payload)
    text = f"job.get {job_id}: status={status}"
    if percent is not None:
        text += f" progress={percent}%"
    if stage is not None:
        text += f" stage={stage}"
    if credential:
        text = text.replace(credential, "[redacted]")
    print(text, file=sys.stderr, flush=True)


def _decode_payload(raw: bytes) -> Any | None:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _emit(raw: bytes) -> None:
    try:
        sys.stdout.buffer.write(raw)
    except AttributeError:
        sys.stdout.write(raw.decode("utf-8"))
    sys.stdout.flush()


def _poll_job(
    url: str, initial: bytes, credential: str | None, timeout: float, interval: float, max_polls: int
) -> bytes:
    payload = _decode_payload(initial)
    job_id = _job_id(payload)
    if not job_id:
        return initial
    _print_progress(job_id, payload, credential)
    if (_job_status(payload) or "").casefold() in TERMINAL_JOB_STATES:
        return initial
    last = initial
    for poll_number in range(max_polls):
        if interval:
            time.sleep(interval)
        request = {
            "schema": REQUEST_SCHEMA,
            "operation": "job.get",
            "arguments": {"job_id": job_id, "include_result": True},
        }
        body = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        _, last = _http_request(url, "POST", body, credential, timeout)
        current = _decode_payload(last)
        _print_progress(job_id, current, credential)
        status = _job_status(current)
        if status in TERMINAL_JOB_STATES or (status is None and current is not None):
            return last
        if poll_number + 1 == max_polls:
            break
    raise _error(f"Job {job_id} did not finish within --max-polls={max_polls}; rerun polling to continue.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call the local Codex Usage Tracker agent API.")
    parser.add_argument("operation_pos", nargs="?", help="operation name (for example usage.query)")
    parser.add_argument("--base-url", help=f"loopback origin or {AGENT_ROUTE}")
    parser.add_argument("--descriptor", help="private runtime descriptor path")
    parser.add_argument("--credential", "--credential-path", dest="credential", help="private credential path")
    parser.add_argument("--capabilities", action="store_true", help="GET the operation catalog")
    parser.add_argument("--operation", "-o", help="operation name for POST")
    parser.add_argument("--arguments", "--args", dest="arguments_json", help="operation arguments as inline JSON")
    parser.add_argument("--request", "--json", dest="request_json", help="complete request envelope as inline JSON")
    parser.add_argument("--request-id")
    parser.add_argument("--privacy-mode")
    parser.add_argument("--execution")
    parser.add_argument("--poll", "--poll-jobs", action="store_true", help="poll an accepted job")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--max-polls", type=int, default=DEFAULT_MAX_POLLS)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def _validate_options(args: argparse.Namespace) -> None:
    if args.capabilities and (args.operation or args.operation_pos or args.request_json is not None):
        raise _error("--capabilities cannot be combined with an operation or --request.")
    if args.poll_interval < 0 or args.poll_interval > MAX_POLL_INTERVAL_SECONDS:
        raise _error(f"--poll-interval must be between 0 and {MAX_POLL_INTERVAL_SECONDS:g} seconds.")
    if args.max_polls < 1 or args.max_polls > MAX_POLL_COUNT:
        raise _error(f"--max-polls must be between 1 and {MAX_POLL_COUNT}.")
    if args.timeout <= 0 or args.timeout > MAX_TIMEOUT_SECONDS:
        raise _error(f"--timeout must be between 0 and {MAX_TIMEOUT_SECONDS:g} seconds.")


def run(args: argparse.Namespace) -> int:
    _validate_options(args)
    url, descriptor_credential = _resolve_target(args.descriptor, args.base_url)
    if args.capabilities or (args.operation is None and args.operation_pos is None and args.request_json is None):
        credential = _resolve_credential(args.credential, descriptor_credential, required=False)
        _, raw = _http_request(url, "GET", None, credential, args.timeout)
        _emit(raw)
        return 0
    credential = _resolve_credential(args.credential, descriptor_credential, required=True)
    body = _request_body(args)
    _, raw = _http_request(url, "POST", body, credential, args.timeout)
    if args.poll or args.poll_interval != DEFAULT_POLL_INTERVAL_SECONDS or args.max_polls != DEFAULT_MAX_POLLS:
        raw = _poll_job(url, raw, credential, args.timeout, args.poll_interval, args.max_polls)
    _emit(raw)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except AgentApiError as exc:
        print(f"agent_api: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("agent_api: interrupted while waiting for the local service.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
