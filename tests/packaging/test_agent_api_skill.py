from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SKILL = REPO_ROOT / "skills" / "codex-usage-api"
PACKAGED_SKILL = REPO_ROOT / "src" / "codex_usage_tracker" / "plugin_data" / "skills" / "codex-usage-api"
HELPER = SOURCE_SKILL / "scripts" / "agent_api.py"


class _Handler(BaseHTTPRequestHandler):
    responses: list[tuple[int, bytes]] = []
    requests: list[tuple[str, dict[str, str], bytes]] = []

    def log_message(self, *_args: object) -> None:
        return

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self.__class__.requests.append(("GET", dict(self.headers), b""))
        status, body = self.__class__.responses.pop(0)
        self._send(status, body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.__class__.requests.append(("POST", dict(self.headers), body))
        status, response = self.__class__.responses.pop(0)
        self._send(status, response)


@contextmanager
def _server(responses: list[tuple[int, bytes]]) -> Iterator[tuple[str, type[_Handler]]]:
    _Handler.responses = list(responses)
    _Handler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", _Handler
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _run_helper(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    process_env = None
    if env is not None:
        process_env = dict(os.environ)
        process_env.update(env)
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        env=process_env,
    )


def test_source_and_packaged_api_skill_files_are_byte_identical() -> None:
    assert (SOURCE_SKILL / "SKILL.md").read_bytes() == (PACKAGED_SKILL / "SKILL.md").read_bytes()
    assert (SOURCE_SKILL / "scripts" / "agent_api.py").read_bytes() == (
        PACKAGED_SKILL / "scripts" / "agent_api.py"
    ).read_bytes()


def test_helper_rejects_non_loopback_origin_without_reading_a_credential(tmp_path: Path) -> None:
    token_path = tmp_path / "token"
    token_path.write_text("synthetic-secret", encoding="utf-8")

    result = _run_helper("--base-url", "https://example.test", "--credential", str(token_path), "--capabilities")

    assert result.returncode != 0
    assert b"loopback" in result.stderr.lower()
    assert b"synthetic-secret" not in result.stdout + result.stderr


def test_helper_sends_credential_header_and_emits_exact_json(tmp_path: Path) -> None:
    token_path = tmp_path / "token"
    token_path.write_text("synthetic-secret\n", encoding="utf-8")
    exact = b'{"schema":"synthetic.v1","result":{"value":3}}\n'
    with _server([(200, exact)]) as (origin, handler):
        result = _run_helper(
            "system.status",
            "--base-url",
            origin,
            "--credential",
            str(token_path),
        )

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == exact
    assert result.stderr == b""
    method, headers, body = handler.requests[0]
    assert method == "POST"
    assert headers["X-Codex-Usage-Token"] == "synthetic-secret"
    assert json.loads(body)["operation"] == "system.status"
    assert b"synthetic-secret" not in result.stdout + result.stderr


def test_helper_get_capabilities_does_not_require_a_token() -> None:
    exact = b'{"schema":"codex-usage-tracker.agent-capabilities.v1","operations":[]}\n'
    with _server([(200, exact)]) as (origin, handler):
        result = _run_helper("--base-url", origin, "--capabilities")

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == exact
    assert handler.requests[0][0] == "GET"
    assert "X-Codex-Usage-Token" not in handler.requests[0][1]


def test_helper_discovers_camel_case_descriptor_fields_from_environment(tmp_path: Path) -> None:
    token_path = tmp_path / "token"
    token_path.write_text("synthetic-secret", encoding="utf-8")
    descriptor_path = tmp_path / "agent-service.json"
    with _server([(200, b'{"ok":true}')]) as (origin, handler):
        descriptor_path.write_text(
            json.dumps(
                {
                    "schema": "codex-usage-tracker.agent-service.v1",
                    "agentEndpoint": f"{origin}/api/v2/agent",
                    "credentialPath": str(token_path),
                }
            ),
            encoding="utf-8",
        )
        result = _run_helper(
            "system.status",
            env={"CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR": str(descriptor_path)},
        )

    assert result.returncode == 0, result.stderr.decode()
    assert handler.requests[0][1]["X-Codex-Usage-Token"] == "synthetic-secret"


def test_helper_polls_job_and_reports_progress_on_stderr(tmp_path: Path) -> None:
    token_path = tmp_path / "token"
    token_path.write_text("synthetic-secret", encoding="utf-8")
    responses = [
        (202, b'{"job":{"job_id":"job-synthetic","status":"queued","percent_complete":0}}'),
        (202, b'{"job":{"job_id":"job-synthetic","status":"running","percent_complete":50}}'),
        (200, b'{"job":{"job_id":"job-synthetic","status":"completed","percent_complete":100},"result":{"value":7}}'),
    ]
    with _server(responses) as (origin, handler):
        result = _run_helper(
            "analysis.run",
            "--base-url",
            origin,
            "--credential",
            str(token_path),
            "--poll",
            "--poll-interval",
            "0",
            "--max-polls",
            "3",
        )

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout == responses[-1][1]
    assert b"job.get job-synthetic" in result.stderr
    assert b"progress=50%" in result.stderr
    assert b"synthetic-secret" not in result.stdout + result.stderr
    assert [json.loads(request[2]).get("operation") for request in handler.requests] == [
        "analysis.run",
        "job.get",
        "job.get",
    ]


def test_helper_error_does_not_echo_credential(tmp_path: Path) -> None:
    token_path = tmp_path / "token"
    token_path.write_text("synthetic-secret", encoding="utf-8")
    with _server([(401, b'{"error":{"message":"synthetic-secret"}}')]) as (origin, _handler):
        result = _run_helper("system.status", "--base-url", origin, "--credential", str(token_path))

    assert result.returncode != 0
    assert b"synthetic-secret" not in result.stdout + result.stderr
    assert b"credential" in result.stderr.lower()
