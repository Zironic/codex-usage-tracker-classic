---
name: codex-usage-api
description: Use when the user wants to discuss, investigate, compare, explain, or improve Codex usage with the local Codex Usage Tracker HTTP API, including token waste, cache/context problems, allowance changes, pricing confidence, dashboard evidence, and explicitly requested local-content investigations.
---

# Codex Usage API Companion

Act as an evidence-first analyst for Codex Usage Tracker data. Use the local
HTTP API first, answer from structured evidence, and keep the user-facing
result concise. The helper is transport-only: print and validate the server's
JSON, but do not recreate analytical semantics from rows.

## API-first transport

The API is a loopback-only service at `GET /api/v2/agent` (capabilities) and
`POST /api/v2/agent` (one named operation). Use the dependency-free helper
shipped beside this skill:

```text
python skills/codex-usage-api/scripts/agent_api.py --capabilities
python skills/codex-usage-api/scripts/agent_api.py usage.query \
  --arguments '{"entity":"thread","measures":["tokens","call_count"],"limit":20}'
```

The packaged copy is at
`src/codex_usage_tracker/plugin_data/skills/codex-usage-api/scripts/agent_api.py`.
The helper discovers the private runtime descriptor from
`CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR` (or `--descriptor`), or accepts an
explicit loopback `--base-url`. POST requests read a credential from the
descriptor's separate `credential_path`, `--credential`, or a credential-path
environment variable and send it only as `X-Codex-Usage-Token`. It rejects
non-loopback origins, does not run a service-ensure command, and never reads
SQLite, source logs, repository files, or configuration. Missing descriptors
and stopped services produce actionable recovery errors.

Use `--request` when an exact `codex-usage-tracker.agent-request.v1` envelope is
needed. Use `--poll` for asynchronous work; the helper polls `job.get` with a
bounded `--poll-interval` and `--max-polls`, writes numeric status/progress to
stderr, and emits only the final response JSON to stdout. Pagination is never
followed unless the request explicitly supplies its cursor.

Before interpreting a response, check its `schema`, `operation`,
`data_class`, `source_revision`, `freshness`, `scope`, `privacy`, truncation,
warnings, limitations, and `next_operations`. Treat aggregate responses as
shareable by default; do not echo credentials, full paths, prompts, assistant
messages, raw tool output, commands, or transcript snippets.

## Operating rules

- For "Open dashboard" requests, start the live localhost dashboard with
  `codex-usage-tracker serve-dashboard --context-api explicit --open`. Refresh
  is the default for dashboard launch commands. Use `open-dashboard` only when
  the user explicitly wants a static/offline snapshot or the environment
  cannot keep a server alive. Say the result is static and Live requires
  `serve-dashboard`.
- Ask the API for `system.status` before a broad read when freshness matters;
  call `refresh.start` only when the status recommends it or the user asks to
  refresh. Never hide a full source refresh inside a read operation.
- Name scope: time window, project/thread/model filters, included archived
  state, row limit, detail mode, and whether results are estimates.
- Separate exact facts from estimates. Call out `pricing_estimated`, missing
  `pricing_model`, `usage_credit_confidence`, missing allowance windows, and
  outside-usage caveats.
- For broad asks, give diagnosis plus remediation: **Evidence**, **Hypothesis
  result**, **Likely waste pattern**, **Next action**, and **How to verify**.

## Core API routing

Use the canonical HTTP operation first. Discovery (`--capabilities`) is one
call; ordinary status/query/analysis questions should need no more than three
API calls after discovery unless the user requests pagination or evidence.

| User intent | First HTTP operation |
| --- | --- |
| broad diagnostic or usage spike | `analysis.run` (`goal="usage_spike"`) |
| token waste or cache/context failure | `analysis.run` (`goal="token_waste"`) or `compression.start` |
| exact grouped/filter query | `usage.query` |
| explicit hypotheses | `analysis.hypotheses` |
| limits or allowance | `allowance.status` |
| finite allowance history | `allowance.series` |
| allowance transition evidence | `allowance.evidence` |
| persisted allowance analysis | `allowance.analysis` |
| ranked investigations | `analysis.suggest` |
| report pack or exact evidence | `usage.report` / `evidence.get` |
| visualization or chart | `visualization.suggest` / `visualization.render` |

Long-running `analysis.run`, allowance analysis, and refresh calls return a
generic job. Poll those with `job.get` (the helper's
`--poll` flag) until `completed` or `failed`, and preserve numeric progress,
stage, cache/reuse metadata, and safe errors in the answer. Do not infer
completion from a missing result.

`compression.start` returns a compression `run_id`; poll it with
`compression.status`, then read `compression.profile`, page
`compression.candidates`, inspect selected `compression.candidate` evidence,
or call `compression.simulate` with explicit candidate IDs.

For cache misses, cold resumes, context bloat, or low-output expensive calls,
use the bounded compression lifecycle. For shell probing or file rediscovery,
use `analysis.pattern_scan` and selected evidence. Observed subagent calls are
distinct persisted sessions; comparisons are descriptive, not causal.

Allowance status is canonical/deduped and reports copied clone rows excluded.
Use weekly windows as the primary signal and five-hour windows as noisy rolling
context. `finite` ranges, `canonical` rows, and compatibility behavior must
remain visible in answers.

## Indexed and raw content

Indexed and raw operations are never part of the default flow. Use
`content.search`, `content.thread_trace`, `diagnostics.get`, or
`evidence.local_export` only after the user explicitly says that indexed local
evidence is needed and the server advertises
the `local_index_read` scope. Use `content.call_context` only after explicit raw
context intent, the `raw_context_read` scope, and the request's
`acknowledge_sensitive_content=true`. Keep limits bounded and state
`includes_indexed_content`/`includes_raw_fragments` truthfully. Aggregate
questions must not be "upgraded" to local content merely because it is
available.

## Agentic investigation loop

For "look through my usage", recommendations, hypothesis tests, or token-waste
discovery:

1. Start with `analysis.suggest` when the user needs ideas.
2. Use `compression.start` for broad token-waste, cache-failure, or
   context-compression questions and poll with `compression.status`.
3. Read the profile and page candidates only when needed; use
   `analysis.pattern_scan` or exact evidence selectors to narrow findings
   before asking for local indexed evidence.
4. Convert findings into explicit hypotheses: "I'd like to be able to...", "I
   will accomplish it using...", "I'm missing access to...", and "My hypothesis
   was true/false/inconclusive because...".
5. Recommend a concrete fix and end with the verification operation/query.

If the local HTTP service is absent, its descriptor is stale, or a needed API
operation is disabled, report that state and its recovery guidance. Do not
silently switch transports, reconstruct results from SQLite, invent a service
origin, or start/kill an unknown listener.

## Synthetic direct-HTTP examples

Examples use only synthetic values. A caller with a known local origin can
inspect capabilities without a token:

```bash
curl --fail --silent http://127.0.0.1:47821/api/v2/agent
```

For an authorized operation, keep the token in a private file and never put it
in a URL, shell history, or output:

```bash
curl --fail --silent \
  -H "Content-Type: application/json" \
  -H "X-Codex-Usage-Token: $(<synthetic-token-file)" \
  --data '{"schema":"codex-usage-tracker.agent-request.v1","operation":"usage.query","arguments":{"entity":"model","measures":["tokens"],"limit":5}}' \
  http://127.0.0.1:47821/api/v2/agent
```

PowerShell keeps the same header/body contract:

```powershell
$token = (Get-Content .\synthetic-token-file -Raw).Trim()
$headers = @{ 'X-Codex-Usage-Token' = $token }
$body = '{"schema":"codex-usage-tracker.agent-request.v1","operation":"system.status","arguments":{}}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:47821/api/v2/agent -Headers $headers -ContentType 'application/json' -Body $body
```

The helper equivalent is:

```text
python skills/codex-usage-api/scripts/agent_api.py system.status --descriptor "$CODEX_USAGE_TRACKER_AGENT_DESCRIPTOR"
```

If descriptor or server errors occur, show the recovery guidance; never print
the credential or include it in an error report.

## Dashboard evidence targets

When a response includes `dashboard_target.absolute_url`, surface **Open
evidence** with that exact loopback URL. When it is absent, show
`dashboard_target.relative_url` and its exact `fallback_instruction`; do not
invent or infer an origin. A dashboard target is not proof that the current
task's API operations are available.

## Answer style

- Lead with the direct answer and strongest metric.
- Use at most one short progress update, such as "Refreshing aggregate usage,
  then ranking likely waste patterns."
- Keep explanations tied to aggregate fields or clearly labeled local-index
  evidence.
- Do not guess conversation content from token patterns.
- For allowance-change answers, separate local evidence from public claims,
  quote the evidence grade, and say when outside usage or missing observations
  could explain movement.
