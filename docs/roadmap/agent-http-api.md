# Agent HTTP API Design Amendment And Implementation Plan

Status: proposed design amendment

Date: 2026-08-01
Target: complete before expired HTTP/MCP compatibility removal and the 1.0 contract freeze

## Outcome

An installed Codex Usage Tracker exposes one discoverable localhost API route
that lets an authorized agent retrieve every supported class of tracker
information without requiring MCP or reconstructing reports from SQLite.

The route is:

```text
GET  /api/v2/agent
POST /api/v2/agent
```

`GET` returns the enabled operation catalog and contract metadata. `POST`
executes one named operation through the owning application service. Long-running
work returns a generic job handle and is polled through the same route with the
`job.get` operation.

The API covers aggregate usage, status and freshness, allowance intelligence,
analysis, exact evidence, diagnostics, compression analysis, indexed-content
investigation, explicitly enabled raw context, sanitized configuration and
coverage metadata, visualization specifications, and bounded export artifacts.
It does not expose arbitrary SQL, arbitrary filesystem reads, secrets, or
destructive administration.

When this plan is complete, the bundled `codex-usage-api` skill uses the HTTP
API first. MCP remains a supported optional transport, not a prerequisite for
analysis.

## Why This Is A Design Amendment

The active roadmap currently declares MCP the primary analysis interface and
freezes unplanned public-surface growth. This plan changes that positioning to:

> Deterministic application services are the product core. The agent HTTP API,
> MCP, CLI, and Evidence Console are peer adapters selected according to client
> capability. No adapter owns analytical semantics.

Approval of this plan therefore requires a matching amendment to:

- `docs/roadmap/mcp-first-pivot.md`;
- `docs/superpowers/specs/2026-07-21-mcp-first-product-pivot-design.md`;
- `docs/superpowers/plans/2026-07-21-mcp-first-product-pivot.md`;
- `docs/deprecations.md`;
- `docs/architecture.md`.

The amendment must land before implementation. Until then, this document is a
proposal and does not authorize a new public route.

## Goals

1. Let an agent discover the local service, authenticate, refresh the index,
   inspect capability schemas, query bounded data, start analysis, poll jobs,
   and follow evidence without MCP.
2. Provide canonical API coverage for every current core, full, and developer
   MCP read capability and every relevant CLI JSON read/export capability.
3. Preserve deterministic calculations in existing application, analytics,
   report, diagnostic, compression, allowance, and context services.
4. Make privacy and data class visible before an agent calls an operation and
   in every response afterward.
5. Preserve focused SQL execution, revision-bound pagination, response budgets,
   freshness semantics, and the 100,000-row performance gates.
6. Make the installed skill and a dependency-free helper sufficient for agents
   that can run local commands and issue HTTP requests.
7. Retain MCP compatibility without requiring API code to import FastMCP,
   MCP registries, or MCP handler modules.

## Non-Goals And Hard Boundaries

The agent API is comprehensive for retrieving and analyzing data. It is not an
unrestricted remote-control endpoint.

The first stable contract does not permit:

- arbitrary SQL or database schema access;
- arbitrary filesystem paths, globbing, or source-log downloads;
- database reset, rebuild, migration, or deletion;
- plugin install, upgrade, uninstall, or publication;
- service install, stop, or process termination through HTTP;
- pricing, rate-card, allowance, threshold, project, or privacy configuration
  writes;
- network pricing refreshes or other outbound requests;
- Git operations, issue creation, publishing, or external messages;
- unbounded `limit=0` responses;
- returning API tokens, secrets, full source paths, raw prompts, assistant text,
  or tool output from aggregate operations.

Index refresh is the one intentional state-changing operation because current
information cannot be guaranteed without it. Diagnostic refresh and analytical
jobs may also update tracker-owned derived caches or snapshots, but they must
not modify source logs or user configuration.

## Verified Existing Substrate

The implementation must extend rather than replace these existing seams:

- `src/codex_usage_tracker/interfaces/http/v2.py` already provides strict,
  bounded adapters for status, refresh, jobs, analysis, query, evidence,
  allowance, and capabilities.
- `src/codex_usage_tracker/application/` owns the typed services behind all
  seven core MCP operations.
- `src/codex_usage_tracker/reports/api.py` exposes shared summary, query,
  recommendation, coverage, discovery, investigation, and export builders.
- `src/codex_usage_tracker/diagnostics/` owns diagnostic reports, persisted
  snapshots, and refresh behavior.
- `src/codex_usage_tracker/compression/` owns compression jobs, profiles,
  candidates, detail, and simulation.
- `src/codex_usage_tracker/context/api.py` owns bounded selected-call raw-context
  loading.
- `src/codex_usage_tracker/server/request_guards.py` owns loopback Host, Origin,
  and constant-time local-token checks.
- `src/codex_usage_tracker/server/route_inventory.py` and
  `server/v2_route_inventory.py` own route workload, exposure, execution,
  history, cache, and byte-budget metadata.
- `src/codex_usage_tracker/core/contracts/` and `core/json_contracts*.py` own
  shared envelopes and stable JSON contract validation.

The new route must call these services directly. It must never call a function
from `interfaces/mcp`, `cli/mcp_*.py`, or a CLI command adapter.

## Public Contract

### Route Semantics

`GET /api/v2/agent` returns a compact catalog:

```json
{
  "schema": "codex-usage-tracker.agent-capabilities.v1",
  "api_version": "2",
  "catalog_revision": "sha256:...",
  "server_instance_id": "...",
  "operations": [
    {
      "name": "usage.query",
      "maturity": "stable",
      "data_class": "aggregate",
      "authorization_scope": "aggregate_read",
      "execution": "synchronous",
      "request_schema": "codex-usage-tracker.agent-operation.usage-query.v1",
      "result_schema": "codex-usage-tracker.query.v2",
      "input_limit_bytes": 32768,
      "output_limit_bytes": 262144,
      "pagination": "revision_bound_cursor",
      "enabled": true,
      "disabled_reason": null
    }
  ]
}
```

The catalog is descriptive and bounded. Detailed field schemas are retrieved
with `meta.schema`; the full schema set is not embedded in every discovery
response.

`POST /api/v2/agent` accepts one strict JSON object:

```json
{
  "schema": "codex-usage-tracker.agent-request.v1",
  "operation": "usage.query",
  "request_id": "optional-client-id",
  "scope": {
    "history": "active",
    "since": null,
    "until": null,
    "project": null,
    "thread_key": null,
    "model": null,
    "effort": null
  },
  "privacy_mode": "normal",
  "execution": "auto",
  "expected_source_revision": null,
  "arguments": {
    "entity": "thread",
    "measures": ["tokens", "call_count"],
    "order_by": "tokens",
    "order": "desc",
    "limit": 20,
    "cursor": null
  }
}
```

Unknown top-level, scope, or operation-specific fields fail. Duplicate keys,
non-object bodies, invalid UTF-8, non-finite numbers, unsupported media types,
missing or incorrect `Content-Length`, and bodies over the declared operation
budget fail before application work begins.

Every successful response uses one surface-neutral envelope:

```json
{
  "schema": "codex-usage-tracker.agent-response.v1",
  "operation": "usage.query",
  "request_id": "server-or-client-id",
  "generated_at": "2026-08-01T12:00:00Z",
  "server_instance_id": "...",
  "catalog_revision": "sha256:...",
  "data_class": "aggregate",
  "result_schema": "codex-usage-tracker.query.v2",
  "source_revision": "...",
  "freshness": {},
  "scope": {},
  "privacy": {
    "mode": "normal",
    "includes_indexed_content": false,
    "includes_raw_fragments": false,
    "redaction_applied": false
  },
  "result": {},
  "job": null,
  "pagination": {
    "next_cursor": null,
    "total_matched": 0,
    "truncated": false
  },
  "warnings": [],
  "limitations": [],
  "next_operations": []
}
```

Application result schemas remain authoritative inside `result`. The agent
envelope does not rename or flatten existing result fields.

### Error Contract

All failures after Host/Origin validation use:

```json
{
  "schema": "codex-usage-tracker.agent-error.v1",
  "operation": "usage.query",
  "request_id": "...",
  "error": {
    "code": "stale_source_revision",
    "message": "The requested cursor belongs to an older source revision.",
    "retryable": true,
    "remediation": "Restart the query without the old cursor."
  }
}
```

The status mapping is fixed before implementation:

| HTTP status | Meaning |
| --- | --- |
| `200` | Synchronous success or completed job result |
| `202` | Accepted asynchronous work |
| `400` | Invalid envelope or operation arguments |
| `401` | Missing agent API token |
| `403` | Token valid but operation scope is not enabled |
| `404` | Unknown operation, job, selector, artifact, or evidence |
| `409` | Revision, cursor, server-instance, or idempotency conflict |
| `411` | Missing `Content-Length` |
| `413` | Request or response exceeds the operation budget |
| `415` | Unsupported media type |
| `422` | Operation is valid but required local facts/capability are unavailable |
| `429` | Bounded concurrency limit reached |
| `500` | Internal failure with no local content in the message |
| `503` | Service is starting, stopping, or temporarily unavailable |

Host/Origin guard failures must either adopt this envelope or be explicitly
documented as transport-level failures. The implementation may not leave the
current legacy error shape accidental.

### Operation Catalog Metadata

Each operation has one immutable descriptor containing:

- stable operation name and description;
- maturity and lifecycle;
- owning application service;
- input and result schema IDs;
- data class: `aggregate`, `local_index`, `raw_context`, or `administrative`;
- required authorization scope;
- synchronous, async-start, or polling behavior;
- active/all-history behavior;
- freshness requirements;
- supported privacy modes;
- request and response byte budgets;
- row, character, and pagination limits;
- cache and semantic-job reuse behavior;
- whether it may scan all history;
- canonical replacements for old MCP names, CLI commands, and v1 routes;
- enabled state and a safe disabled reason.

The catalog is the source for discovery, route dispatch, generated API
reference, bundled skill routing tables, parity tests, and deprecation mapping.
It must not contain handler functions from MCP or CLI modules.

## Canonical Operation Families

### Foundation

| Operation | Purpose | Existing owner/result |
| --- | --- | --- |
| `meta.capabilities` | Full enabled operation catalog | New catalog service |
| `meta.schema` | One operation's request/result schema | Contract registry |
| `system.status` | Index, source, pricing, accounting, allowance, and readiness status | `application.status`; `status.v2` |
| `system.doctor` | Sanitized installation/environment health | Existing doctor report; `doctor-v1` |
| `system.coverage` | Pricing, credit, source, parser, and service-tier coverage | Existing coverage builders |
| `system.configuration` | Effective sanitized read-only configuration and provenance | Existing config loaders; new redacted view |
| `refresh.start` | Active/all-history aggregate or content-index refresh | `application.refresh`; `refresh.v2` or job |
| `job.get` | Poll any generic API job and optionally include its result | `application.job_status`; `job.v1` |

`system.configuration` returns effective values needed to interpret results,
not secrets, raw config files, full paths, or writable handles.

### Usage And Statistics

| Operation | Purpose | Coverage |
| --- | --- | --- |
| `usage.query` | Bounded calls, threads, projects, models, efforts, origins, tiers, and subagents | Existing `query.v2`, extended only where parity requires |
| `usage.statistics` | Time/range/timezone activity, active-time, session, turn, plan/rate, project, and thread statistics | Existing `/api/v2/statistics` service moved under the catalog |
| `usage.dedupe` | Canonical-versus-physical rows and bounded clone provenance | Existing dedupe report |
| `usage.recommendations` | Ranked aggregate recommendations | Existing recommendation service |
| `usage.report` | Compact report pack and linked aggregate evidence | Existing report-pack builder |

`usage.query` remains the primary tabular primitive. Compatibility-specific
filters such as pricing status, credit confidence, minimum tokens, and minimum
credits must either gain bounded v2 semantics or be recorded as intentional
non-parity before their old surfaces can be removed.

### Analysis And Investigation

| Operation | Purpose | Existing owner |
| --- | --- | --- |
| `analysis.run` | Cataloged core goals such as token waste, usage spike, context bloat, cache failure, subagent cost, pricing gaps, and workflow churn | `application.analyze` |
| `analysis.suggest` | Ranked safe investigation ideas | Agentic discovery report |
| `analysis.hypotheses` | Explicit true/false/partial/inconclusive hypothesis evaluation | Hypothesis report service |
| `analysis.action_brief` | Evidence-backed remediation brief | Action-brief service |
| `analysis.investigation` | Bounded agentic or walk-style investigation | Investigation services |
| `analysis.pattern_scan` | Repetition, command-loop, file-churn, rediscovery, shell-churn, context-bloat, and large-low-output scans | Discovery/report services |

These operations return deterministic findings and evidence identifiers. The
agent interprets findings but does not reproduce scoring or classification from
raw rows.

### Evidence

| Operation | Purpose | Existing owner |
| --- | --- | --- |
| `evidence.get` | Exact call, thread, finding, allowance, or analysis evidence | `application.evidence` |
| `evidence.thread_calls` | Revision-bound page of calls for one thread | `application.evidence`/focused query |
| `evidence.local_export` | Strict, bounded evidence package with explicit content posture | Local evidence export builder |

Evidence results always identify source schema, selectors, source revision,
history scope, and privacy mode. Aggregate evidence never grows raw transcript
fields.

### Allowance And Limits

| Operation | Purpose | Existing owner |
| --- | --- | --- |
| `allowance.status` | Constant-size canonical current state | Allowance application service |
| `allowance.series` | Finite reset-aware time series | Allowance intelligence service |
| `allowance.evidence` | Latest-first bounded transition evidence | Allowance intelligence service |
| `allowance.analysis` | Persisted/reusable change analysis | Allowance application/job service |
| `allowance.diagnostics` | Quality, gaps, reset, and movement diagnostics | Existing allowance diagnostics |
| `allowance.export` | Strict shareable evidence artifact | Existing allowance export |

Weekly evidence remains the primary long-range signal. Five-hour evidence is
identified as noisy rolling-window context. Missing observations and outside
usage remain explicit limitations.

### Diagnostics

`diagnostics.get` accepts one allowlisted `kind`:

```text
summary
dedupe
facts
fact_calls
compactions
tools
overview
tool_output
commands
git_interactions
file_reads
file_modifications
read_productivity
concentration
guided_summary
usage_drain
```

`diagnostics.refresh` accepts only persisted snapshot kinds already supported
by the diagnostics service. Refresh starts asynchronously and returns a generic
job. Normal status/query/analysis calls must not implicitly rescan source logs
for diagnostic sections.

Diagnostic path and command information follows privacy-mode behavior already
owned by the diagnostic/report layer. Strict and redacted responses cannot
contain full paths, raw commands, prompts, assistant messages, or tool output.

### Compression

| Operation | Purpose |
| --- | --- |
| `compression.start` | Start or reuse one revision-keyed compression analysis |
| `compression.status` | Poll progress and cache/reuse state |
| `compression.profile` | Read the compact completed profile |
| `compression.candidates` | Page ranked candidates |
| `compression.candidate` | Read one candidate with aggregate handles by default |
| `compression.simulate` | Estimate bounded intervention effects for selected candidates |

All six current Compression Lab MCP operations must have direct parity. Jobs
must expose numeric progress, stage, cache/reuse state, and failures without
forcing an agent to infer completion from missing data.

### Indexed Content And Raw Context

| Operation | Data class | Default state | Purpose |
| --- | --- | --- | --- |
| `content.search` | `local_index` | Disabled unless indexed access is enabled | Bounded FTS/content-index search with snippets |
| `content.thread_trace` | `local_index` | Disabled unless indexed access is enabled | Paged thread timeline and normalized local facts |
| `content.call_context` | `raw_context` | Disabled unless raw access is enabled | One exact selected call's redacted source context |

Rules:

- Indexed and raw operations never run through an aggregate token.
- The server must be launched with the corresponding scope enabled.
- The request must set `acknowledge_sensitive_content=true`.
- `content.search` defaults to at most 20 results, at most 2,000 characters per
  snippet, and an aggregate response budget no larger than 256 KiB.
- `content.thread_trace` defaults to 50 timeline entries and uses a
  source-revision-bound cursor.
- `content.call_context` requires one exact `record_id`, defaults to 20 entries
  and 20,000 characters, omits tool output and compaction history, and retains
  existing explicit switches for those additions.
- Zero/unbounded limits are rejected.
- Results mark `includes_indexed_content` and `includes_raw_fragments`
  truthfully.
- Raw or indexed results are never cached in browser persistence, embedded in
  generated HTML, added to support bundles, or returned by aggregate exports.
- No operation accepts a source path or session-log filename.

### Exports And Artifacts

| Operation | Purpose |
| --- | --- |
| `export.create` | Create bounded JSON, CSV, HTML evidence, dashboard, allowance, local-evidence, or support artifacts |
| `artifact.get` | Read artifact metadata or one bounded byte range by opaque ID |

Large exports must not bypass normal response budgets. `export.create` returns
an inline result when it fits the operation budget or a process-owned
`artifact_id`. Artifacts:

- live in a tracker-owned runtime directory, never a caller-selected path;
- have a declared media type, size, SHA-256 digest, privacy/data-class metadata,
  creation time, and expiry time;
- use opaque identifiers rather than paths;
- have finite size and count limits plus automatic TTL cleanup;
- are unavailable after server restart unless the later persistent-job design
  explicitly owns them;
- never expose API credentials or arbitrary local files;
- require the same or stronger authorization scope used to create them.

The API does not need to reproduce CLI filesystem-output semantics. CLI export
continues to own user-selected output paths.

### Visualization And Developer Evidence

| Operation | Scope | Purpose |
| --- | --- | --- |
| `visualization.suggest` | `developer` or explicitly enabled aggregate | Rank supported visualization intents |
| `visualization.render` | `developer` or explicitly enabled aggregate | Return renderer-independent specs and synchronized evidence |
| `dogfood.start` | `developer` | Start strict-privacy maintainer dogfood analysis |
| `dogfood.status` | `developer` | Poll progress/cache state |
| `dogfood.result` | `developer` | Return the compact aggregate QA artifact |

Base-runtime visualization output remains a spec plus compact evidence, not
SVG/PNG generation or a new runtime dependency.

## Complete Legacy-Parity Ledger

Every current MCP tool must map to a canonical operation or an explicit safety
exclusion. A generated test owns this ledger; the grouped mapping below is the
design baseline.

| Existing public names | Canonical operation |
| --- | --- |
| `usage_status` | `system.status` |
| `usage_refresh`, `refresh_usage_index`, `usage_refresh_start` | `refresh.start` |
| `usage_job_status`, `usage_refresh_status`, analysis/compression/dogfood status tools | `job.get` or the matching family status operation |
| `usage_query`, `usage_summary`, `usage_calls`, `usage_threads`, `session_usage`, `most_expensive_usage_calls`, `subagent_usage` | `usage.query` |
| `usage_call_detail`, `usage_evidence` | `evidence.get` |
| `usage_analyze` | `analysis.run` |
| `usage_allowance` and all allowance status/series/evidence/analysis/history/diagnostic tools | `allowance.*` |
| `usage_dedupe_diagnostics` | `usage.dedupe` |
| `usage_report_pack` | `usage.report` |
| `usage_dashboard_recommendations`, `usage_recommendations` | `usage.recommendations` |
| `usage_pricing_coverage`, `usage_source_coverage` | `system.coverage` |
| `usage_suggest_investigations` | `analysis.suggest` |
| `usage_investigate`, `usage_investigation_walk` | `analysis.investigation` |
| `usage_action_brief` | `analysis.action_brief` |
| `usage_test_hypotheses` | `analysis.hypotheses` |
| repetition, command-loop, file-churn, rediscovery, shell-churn, large-low-output, and context-bloat tools | `analysis.pattern_scan` |
| all six compression tools | `compression.*` |
| `usage_content_search` | `content.search` |
| `usage_thread_trace` | `content.thread_trace` |
| `usage_call_context` | `content.call_context` |
| `usage_local_evidence_export` | `evidence.local_export` or `export.create` |
| `usage_allowance_export`, `export_usage_csv`, `generate_usage_dashboard` | `export.create` |
| visualization developer tools | `visualization.*` |
| dogfood developer tools | `dogfood.*` |
| `usage_doctor` | `system.doctor` |
| `init_usage_pricing_config`, `update_usage_pricing_config`, `init_usage_allowance_config` | Excluded: configuration mutation remains CLI-only |

The implementation adds an equivalent ledger for every stable/advanced CLI
JSON command and every registered v1 HTTP route. Compatibility removal is
blocked while any read capability lacks a canonical operation or a reviewed
exclusion.

## Application Architecture

### Catalog And Dispatch

Add a transport-neutral operation package, for example:

```text
src/codex_usage_tracker/application/agent/
  __init__.py
  catalog.py
  contracts.py
  dispatcher.py
  services.py
  artifacts.py
  authorization.py
```

The package may import application, analytics, reports, diagnostics,
compression, allowance, context, core contracts, and store APIs. It may not
import `interfaces.http`, `interfaces.mcp`, CLI modules, dashboard handlers, or
FastMCP.

The HTTP adapter lives separately:

```text
src/codex_usage_tracker/interfaces/http/agent.py
src/codex_usage_tracker/server/agent_api.py
src/codex_usage_tracker/server/agent_route_inventory.py
```

Responsibilities:

- application catalog: operation identity, policy, budgets, and service owner;
- application dispatcher: validate common scope, authorization decision, invoke
  the typed service, normalize result metadata, and create jobs/artifacts;
- HTTP adapter: strict JSON transport decoding and status serialization only;
- server mixin: Host/Origin/token extraction and response writing only;
- MCP adapters: may later use the same operation services, but are not part of
  the HTTP call path.

### Service Extraction Rule

Some compatibility tools still assemble results in `cli/mcp_*.py` modules. For
each such operation:

1. Identify the deterministic builder already exported by `reports/api.py`,
   diagnostics, compression, allowance, context, or dashboard services.
2. If no transport-neutral function exists, extract one into the owning domain
   module with a typed request and stable result.
3. Retarget the old MCP/CLI/v1 adapter to that service without changing its
   compatibility schema.
4. Add the agent operation adapter.
5. Prove parity with one shared synthetic fixture.

Do not preserve legacy behavior by importing an MCP or CLI handler into the new
route.

### Next Actions

Current contracts may name an MCP `tool`. Add a surface-neutral canonical
operation identifier without silently changing existing schemas. Either:

- add an optional `operation` field in an additive contract revision; or
- introduce `next-operation.v1` for the agent envelope while MCP continues to
  serialize `tool`.

Agent responses must never instruct an HTTP client to call MCP as the only next
step.

## Authentication, Discovery, And Lifecycle

### Request Guards

The server remains loopback-only and preserves existing Host and Origin checks.
For the agent route:

- every `POST` requires `X-Codex-Usage-Token`;
- query-string tokens are rejected to avoid URL/history/log leakage;
- comparison is constant-time;
- `GET` returns only bounded capability metadata and no usage/configuration
  values; it may remain tokenless after an explicit security review;
- aggregate read, compute, local-index, raw-context, export, and developer
  scopes are evaluated before decoding operation-specific arguments;
- disabled scopes remain absent or `enabled=false` in capabilities;
- error messages never echo credentials or request content.

Initial scopes:

```text
aggregate_read
compute
local_index
raw_context
export
developer
```

The normal service enables `aggregate_read`, `compute`, and bounded aggregate
exports. `local_index`, `raw_context`, and `developer` require explicit service
configuration. Enabling raw context does not imply tool-output inclusion.

### Private Runtime Descriptor

Agents need a supported way to find the server and token. Add a private,
atomically published runtime descriptor under the tracker-owned user data
directory:

```json
{
  "schema": "codex-usage-tracker.agent-service.v1",
  "origin": "http://127.0.0.1:47821",
  "server_instance_id": "...",
  "pid": 1234,
  "started_at": "...",
  "credential_path": "...",
  "enabled_scopes": ["aggregate_read", "compute", "export"]
}
```

The credential is stored separately, is never returned by HTTP, and is never
included in support bundles, dashboards, logs, generated docs, or exceptions.
The implementation must define and test current-user-only permissions on every
supported platform. If secure credential-file creation cannot be established,
startup fails closed rather than publishing a broadly readable token.

The descriptor is removed on clean shutdown. Discovery verifies process
identity, server instance ID, loopback origin, and health before trusting it.
Stale descriptors are ignored and safely replaced.

### Service Commands

Extend the existing `service` namespace rather than adding a top-level CLI
command:

```text
codex-usage-tracker service ensure --json
codex-usage-tracker service status --json
codex-usage-tracker service serve --agent-api
```

`ensure` is cross-platform. It may adopt only a tracker-managed service whose
descriptor, process identity, instance ID, and health response match. It must
never adopt or terminate an unknown listener merely because the port is open.

The JSON status result returns origin, health, instance ID, scopes, and
credential path, but not the credential value.

### Bundled Agent Helper

Add a dependency-free helper to both skill copies:

```text
skills/codex-usage-api/scripts/agent_api.py
src/codex_usage_tracker/plugin_data/skills/codex-usage-api/scripts/agent_api.py
```

The helper uses Python's standard library to:

1. run or consume `service ensure --json`;
2. verify the runtime descriptor and loopback origin;
3. read the private credential;
4. call `GET /api/v2/agent` or one `POST` operation;
5. poll generic jobs with bounded intervals and visible numeric progress;
6. follow pagination only when explicitly requested;
7. print the exact JSON response without interpreting analytical fields;
8. return machine-readable recovery guidance when the service is unavailable.

It must not read SQLite, source logs, config files other than the private
descriptor/credential, or repository source.

## Freshness, Jobs, Concurrency, And Caching

- Every data response includes the actual source revision used.
- Pagination cursors include request fingerprint and source revision and fail
  with `409` after incompatible refresh.
- Agents call `system.status`, then `refresh.start` when freshness recommends it.
  No read operation silently performs a full source refresh.
- Appending one synthetic source event and refreshing must advance source
  revision and latest-event time and make the event queryable.
- Heavy analysis, refresh, diagnostic refresh, compression, dogfood, and large
  exports use generic jobs.
- Start operations return immediate acknowledgement, job ID, numeric progress,
  stage, reuse/cache metadata, and a polling operation.
- Semantic job reuse is keyed by operation, normalized request, source revision,
  and relevant config/catalog fingerprints.
- Per-operation and global concurrency ceilings prevent an agent loop from
  launching unbounded work. A saturated service returns `429` with retry advice.
- Cancellation semantics remain explicit; ordinary polling never cancels work.
- Worker exceptions become failed jobs with safe errors. Cancellation remains
  cancellation and is never converted into a failed analytical finding.
- Aggregate immutable responses may be cached by source revision and semantic
  inputs. Raw/indexed responses and credentials are never browser-persisted.
- Persistent job work planned by the active roadmap must land before the API
  promises restart-safe polling. Until then, capabilities truthfully report
  `job_durability="process_local"`.

## Privacy And Data Posture

Every operation declares its data class before execution and every response
states its actual content posture.

Required tests use synthetic sentinels for prompts, assistant messages, tool
output, commands, full paths, secrets, and raw source fragments. They prove:

- aggregate operations never contain sentinels;
- strict/redacted project and thread handling follows existing privacy rules;
- support, dashboard, CSV, HTML, and aggregate JSON exports remain
  aggregate-first;
- indexed snippets appear only in local-index operations;
- raw fragments appear only in raw-context operations;
- raw-context tool output remains off by default;
- artifacts preserve or strengthen the source operation's scope;
- errors, job state, logs, catalog metadata, and runtime descriptors never leak
  request content or credentials;
- no static/package fixture is derived from real local logs.

The API never makes raw or indexed results shareable merely because the caller
requested `privacy_mode="strict"`. Strict privacy is a redaction mode, not a
permission grant.

## Performance And Resource Budgets

Each catalog descriptor records an enforced input and output budget. Initial
ceilings should reuse the existing v2 values unless focused evidence justifies a
change:

- metadata/status: 64 KiB;
- refresh/jobs/evidence: 128 KiB;
- bounded query/local-index pages: 256 KiB;
- analysis: 512 KiB;
- raw selected context: explicit character and entry caps plus 256 KiB maximum;
- capability catalog: compact summary under 128 KiB, with detailed schemas
  fetched individually;
- artifacts: finite configured maximum, never returned inline above the normal
  route budget.

The HTTP serializer must use the canonical deterministic finite-number policy.
It may not emit `NaN` or infinity.

Extend the synthetic route benchmark to include:

- capabilities and status;
- representative call and thread queries;
- thread evidence expansion;
- allowance status/series/evidence;
- synchronous and async analysis starts;
- job polling;
- diagnostic snapshot reads;
- compression candidate paging;
- indexed-content search with synthetic logs;
- selected raw context with synthetic logs;
- statistics;
- artifact metadata and bounded chunk reads.

At 100,000 aggregate rows, capture cold/warm p50 and p95 latency, bytes, SQL
plans, exact matched counts, and peak materialization behavior. Content/context
workloads use the existing synthetic source-log benchmark. No compatibility
route can be removed if its canonical operation materializes unbounded history
or misses the recorded budget.

## Implementation Program

The tasks below are independent review units. After approval, assign final
roadmap task numbers and use one `pivot/<task-number>-<slug>` branch per task.
Do not implement them on the current feature branch or directly on `main`.

### Dependencies On The Active Pivot

This program must be inserted into, not layered around, the active pivot:

- the Task 28 composition root must remain the only place that constructs
  application services for HTTP, MCP, CLI, and server adapters;
- the Task 33 persistent-job work must complete before the agent API advertises
  restart-safe jobs; earlier releases report process-local durability;
- the Task 34 blocking coverage, architecture, and work-proof gates must include
  the agent catalog and route;
- the Task 35 immutable CI-action and Task 36 build-once promotion work must be
  complete before public qualification;
- Task 41 compatibility deletion is blocked on API-13 parity evidence;
- Task 42 documentation/skill cleanup includes the API-first cutover from
  API-12;
- Task 44 golden/fault testing includes the agent lifecycle and sensitive-data
  cases in this plan;
- Task 45 freezes the agent operation catalog and schemas alongside the other
  1.0 contracts.

The approved roadmap amendment must assign whether these become inserted tasks
or explicit dependencies of existing tasks. It must not leave two competing
composition roots, job stores, contract registries, or release gates.

### API-01 - Approve The Product And Compatibility Amendment

**Outcome:** HTTP is a first-class agent transport and the surface freeze,
release map, compatibility removal gates, and execution ledger name this work.

**Files:** the five roadmap/design/architecture/deprecation documents named
above, `CHANGELOG.md`, public-doc tests.

**Acceptance:**

- product wording is consistent across public docs;
- 0.24 feature scope and 0.25 compatibility removal order are explicit;
- no old route/tool is scheduled for removal before agent-operation parity;
- branch/task identifiers and execution-ledger entries are assigned;
- independent non-author review is recorded.

### API-02 - Add The Transport-Neutral Operation Catalog And Contracts

**Outcome:** one typed catalog describes every operation, policy, schema,
budget, lifecycle, and legacy mapping without registering a route.

**Primary files:** new `application/agent/` catalog/contracts modules,
`core/json_contracts*.py`, contract tests, release catalog tests.

**Start with failing tests:**

- unique stable operation names and schema IDs;
- complete mapping of all 64 current MCP names;
- complete mapping of stable/advanced CLI JSON and registered v1 HTTP reads;
- reviewed exclusion for every mutation-only surface;
- no MCP/CLI/interface import from the application catalog;
- immutable catalog fingerprint and deterministic ordering;
- valid data class, auth scope, execution, pagination, and budgets.

Clean the duplicate `analysis-job.v1` entry in `docs/cli-json-schemas.md` while
updating the canonical schema registry; do not change either historical payload
under cover of the documentation cleanup.

### API-03 - Implement The Strict Agent Envelope And Discovery Route

**Outcome:** `GET/POST /api/v2/agent` supports capabilities, `meta.schema`,
strict request decoding, canonical success/error envelopes, and stub dispatch.

**Primary files:** `interfaces/http/agent.py`, `server/agent_api.py`,
`server/agent_route_inventory.py`, `server/routes.py`, serializers, focused HTTP
tests.

**Acceptance:**

- method/route/content-type/length/duplicate/unknown/non-finite cases pass;
- request and response budgets are enforced per catalog entry;
- output serialization rejects non-finite values deterministically;
- Host/Origin failures have the approved error shape;
- route inventory and public schema registry agree;
- the route imports no MCP or CLI code.

### API-04 - Wire Core Operations And Golden Questions

**Outcome:** status, refresh, jobs, query, analyze, evidence, and allowance are
available through the agent envelope with schema parity to existing v2/MCP
results.

**Acceptance:**

- the same typed application requests produce field-identical inner results;
- active/all-history, filters, grouping, cursors, comparisons, evidence
  selectors, allowance operations, and async jobs retain existing semantics;
- a synthetic appended event proves incremental freshness;
- golden questions can be answered with HTTP and no MCP/CLI fallback;
- query/evidence route budgets pass at 100,000 rows.

### API-05 - Add Secure Discovery, Credentials, And Cross-Platform Ensure

**Outcome:** an agent can find and authenticate to the managed localhost service
without scraping dashboard HTML or adopting an unknown listener.

**Primary files:** server lifecycle/runtime-state modules, existing `service`
namespace, private-state tests, installed smoke tests.

**Acceptance:**

- atomic descriptor/credential creation and cleanup;
- owner-only credential permissions or fail-closed startup;
- token never appears in JSON status, logs, support bundles, URLs, or errors;
- stale PID/descriptor, port collision, crash, and restart recovery tests;
- Windows, macOS, and Linux behavior is documented and CI-covered where
  possible;
- `service ensure` verifies managed identity before reuse.

### API-06 - Extract And Expose Aggregate Reports, Statistics, And Coverage

**Outcome:** doctor, coverage, sanitized configuration, statistics, dedupe,
recommendations, report pack, subagent analytics, summary/expensive/session
parity are available without legacy adapters.

**Acceptance:**

- old MCP/CLI/v1 adapters and the new API call the same service;
- old-only query filters receive bounded canonical semantics or a recorded
  exclusion;
- statistics freshness and timezone behavior are preserved;
- strict/redacted outputs pass sentinel privacy tests;
- no full-history Python materialization is introduced.

### API-07 - Expose Diagnostics And Diagnostic Refresh Jobs

**Outcome:** all allowlisted diagnostic kinds and persisted refresh jobs use the
generic agent contract.

**Acceptance:**

- every registered diagnostic read/refresh route maps to one catalog operation;
- refresh is explicit and job-backed;
- stored-snapshot reads do not rescan logs;
- command/path/tool-output privacy behavior is verified by kind;
- worker failure, DB lock, interruption, and stale snapshot states are truthful.

### API-08 - Expose Compression And Investigation Workflows

**Outcome:** compression, investigation suggestions, action briefs,
hypotheses, walk, and pattern scans have full agent API parity.

**Acceptance:**

- all six Compression Lab operations work;
- numeric progress and cache/reuse state appear immediately;
- candidate pages and detail stay bounded;
- simulation accepts only candidates from the matching run/revision;
- investigations return evidence identifiers, confidence, limitations, and
  canonical next operations;
- no agent-side recomputation is required.

### API-09 - Expose Indexed Content And Selected Raw Context

**Outcome:** explicit local-index and raw-context scopes cover content search,
thread trace, and selected-call context.

**Acceptance:**

- disabled-by-default capability reporting;
- server-scope plus per-request acknowledgement checks;
- strict record selectors and revision-bound pagination;
- entry, character, row, and response caps;
- tool output and compaction history off by default;
- aggregate tokens cannot call sensitive operations;
- no content leaks into jobs, logs, caches, exports, errors, or static HTML;
- synthetic source-log performance and privacy suites pass.

### API-10 - Add Bounded Export Artifacts

**Outcome:** agents can obtain shareable JSON/CSV/HTML/dashboard/allowance/local
evidence/support artifacts without arbitrary filesystem access.

**Acceptance:**

- opaque IDs, digests, media types, scope, expiry, and size metadata;
- inline-versus-artifact threshold is deterministic;
- bounded byte-range reads and authorization inheritance;
- finite registry size and TTL cleanup;
- no caller path, traversal, symlink escape, stale-ID reuse, or cross-scope read;
- process-local durability is reported truthfully;
- aggregate artifacts contain no indexed/raw sentinels.

### API-11 - Add Visualization And Developer Operations

**Outcome:** the five developer MCP capabilities have cataloged HTTP parity
behind an explicit developer scope.

**Acceptance:**

- dogfood start/status/result uses generic jobs and strict privacy;
- visualization returns specs and compact synchronized evidence only;
- developer operations are absent or disabled in normal capability discovery;
- no new visualization runtime dependency is added.

### API-12 - Ship The Agent Helper And Make Skills API-First

**Outcome:** installed agents use the API without needing MCP discovery.

**Primary files:** both `codex-usage-api` skill copies, both tracker skill
copies where routing overlaps, bundled helper scripts, API docs, first-five-
minutes guide, MCP docs, packaging tests.

**Acceptance:**

- source and packaged skill trees are byte-identical;
- ordinary status/query/analysis questions use no more than three API calls
  after discovery unless pagination/evidence is requested;
- broad analysis starts a job, reports numeric progress, and polls normally;
- raw/indexed operations require explicit user intent;
- MCP is documented as fallback/optional transport;
- CLI JSON remains the fallback when no long-lived local service is possible;
- installed-wheel smoke proves helper discovery, capabilities, refresh, query,
  analysis job polling, and evidence on synthetic data.

### API-13 - Prove Parity And Retire Only Redundant Compatibility Surfaces

**Outcome:** the compatibility ledger is executable and removal happens only
after functional, privacy, performance, and installed-package parity.

**Acceptance:**

- every v1 route and deprecated MCP tool is mapped or explicitly retained;
- focused Calls/Threads filters, sorts, counts, expansion, cost, and credit
  behavior have parity;
- 100,000-row route budgets pass;
- archived history and incremental freshness pass;
- advanced operations retained by product policy remain documented;
- removed surfaces follow `docs/deprecations.md` timing and return the approved
  migration behavior;
- no application service is deleted merely because an adapter is removed.

### API-14 - Release Hardening And Contract Freeze

**Outcome:** the API is safe to freeze for 1.0.

**Acceptance:**

- canonical operation, request, response, error, schema, and route manifests are
  snapshot-tested;
- breaking-change rules require a new schema version, migration example,
  deprecation entry, and release note;
- generic jobs satisfy persistent/recovery requirements before being documented
  as restart-safe;
- fault injection covers worker exception, DB lock, interrupted server,
  malformed cursor, stale revision, oversize input/result, missing content
  permission, expired artifact, and partial refresh;
- CI blocks on coverage, HTTP work-proof, route budgets, package contents,
  skill synchronization, release checks, and installed smoke;
- final independent review signs off privacy, security, performance, contracts,
  and compatibility.

## Dependency Order

```text
API-01 amendment
   |
API-02 catalog/contracts
   |
API-03 route/envelope -------- API-05 discovery/auth
   |                              |
API-04 core parity ---------------+
   |
   +---- API-06 aggregate reports/statistics
   +---- API-07 diagnostics
   +---- API-08 compression/investigation
   +---- API-09 indexed/raw content
   +---- API-10 exports/artifacts
   +---- API-11 developer operations
              |
          API-12 helper/skills
              |
          API-13 parity/removal
              |
          API-14 freeze
```

API-06 through API-11 may proceed in parallel after API-04 and API-05 define the
stable substrate. API-09 and API-10 require privacy/security review before
implementation, not merely before merge.

## Verification Program

### Focused Tests

Create focused suites under:

```text
tests/application/agent/
tests/interfaces/http/test_agent_api.py
tests/server/test_agent_api.py
tests/server/test_agent_api_guards.py
tests/server/test_agent_route_inventory.py
tests/server/test_agent_service_discovery.py
tests/privacy/test_agent_api_privacy.py
tests/performance/test_agent_api_queries.py
tests/packaging/test_agent_api_skill.py
tests/installed/test_agent_api_smoke.py
```

Every behavior task begins with the smallest failing tests for its contract.

### Required Integration Evidence

1. Start the real localhost service from an installed wheel using synthetic
   Codex logs.
2. Discover it through `service ensure --json` and the private descriptor.
3. Fetch capabilities.
4. Read stale status, start refresh, poll progress, and observe the new source
   revision.
5. Query calls, threads, models, efforts, tiers, and subagents with pagination.
6. Start each analysis family and follow exact evidence identifiers.
7. Read allowance status, series, evidence, and analysis.
8. Read diagnostics and run an explicit diagnostic refresh.
9. Run compression through candidates, detail, and simulation.
10. Prove indexed/raw operations are denied by default, then enable them against
    synthetic logs and verify content markers and bounds.
11. Create and read a strict aggregate artifact.
12. Restart the server and verify truthful job/artifact durability behavior.
13. Run the bundled helper from the installed skill tree with MCP unavailable.

### Repository Gates

Run focused tests first, then the full applicable release gate:

```text
python -m ruff check .
python -m mypy
python -m pytest
python -m pytest --cov=codex_usage_tracker --cov-report=term-missing
python -m compileall src
python scripts/benchmark_dashboard_routes.py --sizes 100000 --iterations 3 --enforce-thresholds
python scripts/benchmark_synthetic_history.py --rows 100000 --json --enforce-thresholds
python scripts/benchmark_synthetic_history.py --rows 1000 --with-source-logs --json --enforce-thresholds
python scripts/check_release.py
git diff --check
python -m build
python -m twine check dist/*
python scripts/check_release.py --dist
python scripts/smoke_installed_package.py
```

Add a blocking agent-route work-proof to CI. It must prove that each cataloged
operation reaches its owning application service or an explicit disabled path;
simple route registration is insufficient.

## Documentation Deliverables

- `docs/agent-http-api.md`: operator and client guide with curl, PowerShell, and
  helper examples using synthetic identifiers;
- `docs/agent-http-api-reference.md`: generated operation catalog and schemas;
- `docs/privacy.md`: scopes, descriptors, credentials, raw/indexed rules;
- `docs/cli-reference.md`: service ensure/status and credential behavior;
- `docs/architecture.md`: application catalog and adapter boundaries;
- `docs/cli-json-schemas.md`: schema registry and migration mapping;
- `docs/mcp.md`: MCP as optional adapter and compatibility mapping;
- `docs/deprecations.md`: v1/MCP/CLI replacement operations;
- README and first-five-minutes API-first examples;
- both bundled skill trees.

Examples and fixtures must remain synthetic. Documentation must never contain a
real credential, local path, prompt, assistant response, tool output, or source
log fragment.

## Rollout And Compatibility

1. Ship discovery, core operations, and the API-first helper additively.
2. Keep existing v2 endpoints, MCP core, full/developer profiles, CLI JSON, and
   v1 routes working during their documented compatibility windows.
3. Collect synthetic and local opt-in dogfood evidence; do not add telemetry.
4. Switch bundled skills to API-first only after installed-wheel API smoke is
   green on supported platforms.
5. Remove deprecated v1/MCP/CLI adapters only after the generated parity ledger,
   route budgets, privacy suite, and migration docs pass.
6. Freeze operation names and schemas only after fault and upgrade rehearsals.

No compatibility alias may silently change meaning. If exact parity is not
possible, keep the old surface through its promised window or publish a
versioned breaking-change notice.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| The single route becomes an untyped god endpoint | Strict operation catalog, typed per-operation requests, application ownership, and no arbitrary query language |
| API duplicates MCP/CLI logic | Extract transport-neutral services and test all adapters against the same synthetic fixture |
| Token discovery weakens localhost privacy | Header-only POST token, private credential file, scoped capabilities, fail-closed permissions, no token in URLs/status/logs |
| Raw/indexed content leaks into ordinary results | Data classes, disabled scopes, explicit acknowledgement, sentinel tests, no cache/export inheritance |
| Large results defeat response budgets | Revision-bound pagination and opaque TTL artifacts; no unbounded limits |
| Agents launch excessive analysis | Immediate jobs, semantic reuse, concurrency ceilings, `429`, numeric progress |
| Refresh invalidates pages silently | Source revision in every response and cursor; `409` on mismatch |
| Process restart loses jobs/artifacts | Truthful durability metadata, existing persistent-job roadmap dependency, bounded recovery tests |
| New facade regresses focused SQL | 100,000-row route budgets, SQL-plan evidence, no Python full-history materialization |
| Compatibility is removed prematurely | Generated exhaustive parity ledger blocks deletion |
| Skills and packaged copies drift | Byte-identity release check and installed-wheel smoke |
| Current dirty branch contaminates the program | Start each approved task from current `main`; never include unrelated dashboard/runtime edits |

## Effort Estimate

Expected implementation effort is 12-18 engineering days across 10-14 focused
PRs, excluding review latency and publication:

| Workstream | Estimate |
| --- | ---: |
| Amendment, catalog, envelope, and core parity | 3-4 days |
| Discovery, credentials, and cross-platform service ensure | 2-3 days |
| Aggregate reports, statistics, diagnostics, and allowance parity | 2-3 days |
| Compression, investigation, indexed content, and raw context | 2-3 days |
| Artifacts, developer operations, helper, and skill/docs cutover | 2-3 days |
| Full parity, performance, fault, package, and release hardening | 1-2 days |

The estimate assumes existing deterministic builders can be extracted without
schema redesign. Persistent restart-safe jobs, if not completed by the active
roadmap first, add approximately 2-4 engineering days and must not be hidden by
the API plan.

## Definition Of Done

The program is complete only when all of the following are true:

- an installed agent with no MCP tools can discover the service and answer the
  approved golden usage questions through HTTP;
- the operation catalog maps every current MCP tool, relevant CLI JSON command,
  and v1 HTTP read route to a canonical operation or reviewed exclusion;
- all operations call transport-neutral services and no agent HTTP module
  imports MCP/CLI handlers;
- aggregate, local-index, raw-context, administrative, and developer boundaries
  are enforced and visible;
- every response is bounded, schema-versioned, source-revision stamped,
  privacy-marked, and finite JSON;
- refresh, analysis, diagnostics, compression, export, and dogfood jobs provide
  immediate acknowledgement and numeric progress;
- exact evidence, allowance, content search, thread trace, and selected raw
  context work with documented bounds;
- unknown listener, stale descriptor, invalid token, disabled scope, stale
  cursor, oversize payload, worker failure, DB lock, restart, and expired
  artifact cases fail safely and truthfully;
- 100,000-row aggregate and synthetic source-log performance gates pass;
- source and packaged skills are byte-identical and teach API-first behavior;
- installed-wheel smoke passes with MCP unavailable;
- compatibility removal follows the amended deprecation ledger;
- the full local CI, build, distribution, privacy, and release checks pass;
- independent review approves architecture, security/privacy, performance, and
  public-contract changes.
