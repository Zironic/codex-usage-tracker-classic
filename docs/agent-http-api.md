# Agent HTTP API client guide

The tracker exposes one local, loopback-only agent route:

```text
GET  /api/v2/agent   # bounded capabilities catalog
POST /api/v2/agent   # one cataloged operation
```

The route is an application-service adapter. It does not accept SQL,
filesystem paths, source-log names, credentials in URLs, or arbitrary
operations. Responses are JSON envelopes with a schema, operation, privacy
posture, source revision, freshness, warnings, limitations, and the owning
result under `result`.

`GET /api/v2/agent` is the source of truth for the running instance. It lists
each operation's accepted argument fields, limits, data class, execution mode,
authorization scope, and effective enabled state. Operations whose local
content scope is disabled remain visible but are marked unavailable with a
reason.

## Discovering a running service

The managed service publishes a private JSON descriptor. Its shape is:

```json
{
  "schema": "codex-usage-tracker.agent-service.v1",
  "origin": "http://127.0.0.1:47821",
  "server_instance_id": "synthetic-instance",
  "credential_path": "synthetic-token-file",
  "enabled_scopes": ["aggregate_read", "analysis_read"]
}
```

The credential is a separate file and is never part of the descriptor response,
dashboard, logs, or an error message. Set
`CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR` or pass `--descriptor` to the helper.
The aliases `CODEX_USAGE_AGENT_DESCRIPTOR` and
`CODEX_USAGE_TRACKER_DESCRIPTOR` are accepted for scripts that already use
those names. A caller without a descriptor may pass a loopback `--base-url`
and `--credential` path explicitly. The helper does not start, ensure, adopt,
or terminate a service; an absent/stale descriptor gives recovery guidance.

Only `localhost`, `127.0.0.0/8`, and `::1` origins are accepted. Credentials
are sent in `X-Codex-Usage-Token` on POST requests and never in a query string.

## Dependency-free helper

The source and packaged copies of
`skills/codex-usage-api/scripts/agent_api.py` are byte-identical and use only
the Python standard library. Capabilities are a GET and need no token when
the server permits anonymous discovery:

```text
python skills/codex-usage-api/scripts/agent_api.py --capabilities \
  --descriptor "$CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR"
```

One operation is a POST. Arguments are inline JSON; use `--request` when an
exact `codex-usage-tracker.agent-request.v1` envelope is required:

```text
python skills/codex-usage-api/scripts/agent_api.py usage.query \
  --descriptor "$CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR" \
  --arguments '{"entity":"model","measures":["tokens","call_count"],"limit":5}'
```

`--poll` follows an accepted generic job through `job.get`. The interval and
poll count are bounded with `--poll-interval` and `--max-polls`; numeric
status/progress is written to stderr, while stdout contains only the exact
final JSON response. Pagination is never followed automatically.

The helper reads only the descriptor, the separate credential path, and the
inline request supplied by the caller. It never opens SQLite, session logs,
repository files, or configuration. A missing descriptor, credential, route,
or server is reported without echoing a credential:

```text
agent_api: No agent service was discovered. Pass --base-url with --credential, or set CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR to the private descriptor path.
```

## Synthetic curl request

Use a synthetic token file in examples and replace the origin only with a
known local service. Keep command output aggregate-first.

```bash
curl --fail --silent http://127.0.0.1:47821/api/v2/agent

curl --fail --silent \
  -H "Content-Type: application/json" \
  -H "X-Codex-Usage-Token: $(<synthetic-token-file)" \
  --data '{"schema":"codex-usage-tracker.agent-request.v1","operation":"system.status","arguments":{}}' \
  http://127.0.0.1:47821/api/v2/agent
```

Do not put a real token in shell history, a URL, a support bundle, or a
copied response.

## Synthetic PowerShell request

```powershell
$token = (Get-Content .\synthetic-token-file -Raw).Trim()
$headers = @{ 'X-Codex-Usage-Token' = $token }
$body = '{"schema":"codex-usage-tracker.agent-request.v1","operation":"usage.query","arguments":{"entity":"thread","measures":["tokens"],"limit":5}}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:47821/api/v2/agent `
  -Headers $headers -ContentType 'application/json' -Body $body
```

## Routing and privacy

Call `system.status` before reads when freshness matters, then use enabled
operations such as `usage.query`, `usage.report`, `analysis.run`,
`analysis.suggest`, `allowance.status`, `evidence.get`, and `job.get`.
Inspect capabilities before selecting an operation and preserve the returned
schema, scope, source revision, and limitations.

Aggregate operations are the default. `content.search`,
`content.thread_trace`, `diagnostics.get`, and `evidence.local_export` require
explicit user intent for indexed local evidence,
enabled `local_index_read`, and `acknowledge_sensitive_content=true`.
`content.call_context` additionally requires explicit raw-context intent and
the enabled `raw_context_read` scope. Their responses mark
`includes_indexed_content` or `includes_raw_fragments`; never expose those
fields through aggregate reports or exports.

If the local HTTP service is unavailable, report the discovery or connection
failure and its recovery guidance. Do not silently change transports or
reconstruct analytical results from SQLite.
