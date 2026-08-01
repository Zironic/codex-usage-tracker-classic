# Dashboard/API Luna Delegation Efficiency Implementation Plan

> **Status:** Feature implementation plan. The dashboard is the human product surface and the versioned localhost HTTP API is the only analytical automation surface.
>
> **Implementation rule:** Execute each task on its own issue-backed branch from current `main`. Keep `main` releasable after every task. Update the execution ledger in the same commit as each task.

**Completed prerequisite:** [`docs/roadmap/agent-http-api.md`](../../roadmap/agent-http-api.md) owns the agent API catalog, envelope, discovery, authentication, scopes, jobs, pagination, runtime descriptor, helper, service lifecycle, and generic compatibility work. This plan begins only after that foundation is implemented and verified. It adds the operations and UI needed for Luna efficiency; it does not reopen or duplicate the API program.

## Goal

Build a privacy-safe, evidence-backed way to determine whether routing bounded work to Luna subagents improves completed-work efficiency, using:

- the local dashboard for people;
- versioned localhost HTTP endpoints for agents and other automation;
- shared application and store services behind those two surfaces.

## Outcome

When this plan is complete, a maintainer can answer all of the following without reading raw session logs:

1. How much token, credit, cost, and elapsed-time capacity did direct Sol work and Luna-assisted work consume?
2. How many work items were completed, accepted, accepted with rework, rejected, failed, cancelled, timed out, or remain unknown?
3. What was the child queue time, child runtime, parent integration overhead, total parent-plus-child cost, and effective parallelism?
4. How do those results differ by Luna worker tier, task class, predeclared complexity, project, policy version, and controlled experiment?
5. Is the evidence complete enough to make an efficiency claim, or is it only descriptive?
6. Which coverage limitation prevents a stronger conclusion?

The product must never convert missing identifiers, absent outcomes, incomplete pricing, inferred attachments, or OTLP-only rows into apparently successful work.

## Current Substrate and Verified Gaps

### What can be reused

- `src/codex_usage_tracker/application/query.py` and `query_models.py` already provide bounded aggregate queries for subagent role/type, model, effort, tier, parent thread, tokens, cost, credits, cache ratio, and derived duration.
- `src/codex_usage_tracker/store/subagent_usage_queries.py` already separates direct, subagent, and attributable-subagent usage and reports coverage.
- `src/codex_usage_tracker/reports/subagent_usage.py` correctly describes its direct-versus-subagent output as observed and non-causal.
- `src/codex_usage_tracker/interfaces/http/v2.py` already supplies strict request decoding, request/output limits, token policy, typed application-service dispatch, capabilities, and generic jobs.
- `src/codex_usage_tracker/store/content_index_events.py` already records privacy-safe tool and command timing, terminal status, exit codes, failure categories, and retry groups.
- `src/codex_usage_tracker/diagnostics/facts.py` already recognizes high-confidence `task_complete`, `turn_aborted`, `thread_rolled_back`, and `patch_applied` evidence.
- `frontend/dashboard` already has a typed API-client pattern, React Query cache policies, route registration, filters, loading/error states, and a descriptive Statistics view.

### What is not sufficient today

- The current report measures resource consumption, not completed-work efficiency.
- There is no explicit work-item identity, experiment identity, task class, predeclared complexity, routing policy version, or controlled-pair identity.
- There is no authoritative acceptance, rework, rejection, failure, cancellation, or timeout outcome for a delegated task.
- There is no complete spawn-request, child-start, child-finish, parent-integration, or work-completion lifecycle.
- Parent and child usage cannot always be attributed to one work item, so total cost and elapsed time can be incomplete.
- Concurrent children can cause parent cost to be double-counted if metrics are calculated per child rather than per work item.
- Existing duration values estimate active call time from timestamps and capped gaps; they are not provider lifecycle timing.
- OTLP events do not carry the JSONL subagent metadata needed to classify Luna work.
- The generic `subagent_cost` compatibility analysis collapses the useful report into a summary string and is not a suitable efficiency contract.
- The completed agent API does not yet have Luna work-item lifecycle, outcome, attribution, or efficiency operations.

### Correctness defect that blocks trustworthy spawn counts

`src/codex_usage_tracker/parser/jsonl_v1.py` currently substitutes the literal string `"unknown"` when a session ID is absent. `src/codex_usage_tracker/store/subagent_usage_queries.py` counts every nonblank session ID as an observed spawn. Multiple unidentified sessions can therefore be collapsed into one false spawn.

This defect must be fixed before any per-spawn or per-delegation metric is promoted in the API or dashboard.

## Product and Architecture Decisions

### Supported product surfaces

| Surface | Responsibility | Status |
|---|---|---|
| Dashboard | Human exploration, comparison, evidence coverage, work-item details, experiment status | Primary |
| `GET/POST /api/v2/agent` operation API | Direct agent/automation contract, lifecycle writes, aggregate reads, schema discovery, job polling | Primary |
| Application/store services | Shared domain logic and persistence; never transport-specific | Internal |
Historical tool-event labels found in imported Codex logs are data provenance. The Luna feature must preserve their parser compatibility and must not make transport-cleanup changes under cover of analysis work.

### Logical flow

```text
Codex JSONL/OTLP + explicit lifecycle API events
                    |
                    v
       canonical usage and efficiency stores
                    |
                    v
       application efficiency/query services
                    |
           +--------+--------+
           |                 |
           v                 v
   /api/v2/agent ops      React dashboard
      direct agents       calling the same ops
```

No dashboard component may recalculate business metrics that belong in the application service.

### Claim levels

Every efficiency response must contain one of these claim levels:

- `descriptive`: consumption and activity only; no task outcome denominator.
- `observational`: known work-item outcomes exist, but cohorts are not controlled or matched well enough for a causal claim.
- `controlled`: paired, predeclared benchmark work satisfies the controlled-evidence gates.
- `insufficient_evidence`: one or more required coverage or sample gates failed.

The UI must render the server-provided claim level and limitations. It must not derive or upgrade claim strength in TypeScript.

## Measurement Contract

### Cohorts

Classify at work-item creation time:

- `direct_sol`: no delegated child is expected.
- `luna_high`: bounded work is routed to `luna_worker_high`.
- `luna_low`: bounded work is routed to `luna_worker_low`.
- `mixed`: more than one routing strategy is intentionally used.
- `unknown`: insufficient metadata; excluded from comparative verdicts.

Observed usage qualifies as Luna only when both are true:

1. canonical subagent metadata identifies a subagent/parent relationship; and
2. the normalized model alias resolves to an approved Luna model alias for the source revision.

Do not classify every subagent as Luna or every Luna-model row as a spawned child. Return the alias configuration and its revision in the response.

### Predeclared task attributes

The caller supplies these before work begins:

- `task_class`: `exploration`, `implementation`, `debugging`, `testing`, `documentation`, or `review`;
- `complexity`: `small`, `medium`, or `large`;
- `cohort`;
- `policy_version`;
- optional opaque `experiment_id`;
- optional opaque `pair_id` for controlled direct/Luna pairs;
- optional project key from the existing local project configuration.

Do not accept free-form task descriptions, prompts, result text, notes, command text, or tool arguments.

### Outcomes

Work-item terminal outcome is exactly one of:

- `accepted`;
- `accepted_with_rework`;
- `rejected`;
- `failed`;
- `cancelled`;
- `timeout`;
- `unknown`.

Validation status is exactly one of `passed`, `failed`, `not_run`, or `unknown`.

Outcome source is exactly one of:

- `maintainer_reported`;
- `agent_reported`;
- `observed_signal`;
- `corrected`;
- `unknown`.

`task_complete`, successful command exit, or `patch_applied` may contribute observed evidence, but none of them alone means the maintainer accepted the work. Missing evidence remains `unknown`.

### Lifecycle events

Persist immutable, idempotent events for:

- `work_started`;
- `delegation_requested`;
- `delegation_started`;
- `delegation_finished`;
- `integration_started`;
- `validation_recorded`;
- `work_completed`;
- `work_corrected`.

Each event contains an opaque idempotency key, timestamp, source, work-item ID, optional delegation ID, and only the bounded enum/numeric fields allowed for that event type.

### Link confidence

Every parent/child usage attachment carries:

- `exact`: explicit session/delegation identity;
- `high`: deterministic metadata match with one candidate;
- `inferred`: cwd/time/thread heuristic;
- `unmatched`.

Only `exact` attachments contribute to the default total parent-plus-child efficiency verdict. The dashboard may show high/inferred rows separately, but never merge them silently.

### Metrics and formulas

Calculate at work-item level first, then aggregate. This prevents a parent session from being charged once per concurrent child.

- `accepted_items = accepted + accepted_with_rework`
- `acceptance_rate = accepted_items / terminal_items_with_known_outcome`
- `clean_acceptance_rate = accepted / terminal_items_with_known_outcome`
- `rework_rate = accepted_with_rework / accepted_items`
- `elapsed_ms = work_completed_at - work_started_at`
- `queue_ms = delegation_started_at - delegation_requested_at`
- `child_runtime_ms = delegation_finished_at - delegation_started_at`
- `integration_ms = work_completed_at - max(last_child_finished_at, integration_started_at)` when both endpoints are known
- `total_tokens = exact_parent_tokens + sum(exact_child_tokens)`
- `total_credits = exact_parent_credits + sum(exact_child_credits)`
- `total_cost_usd = exact_parent_cost + sum(exact_child_cost)`
- `tokens_per_accepted_item = total_tokens / accepted_items`
- `credits_per_accepted_item = total_credits / accepted_items`
- `elapsed_per_accepted_item = sum(elapsed_ms) / accepted_items`
- `sol_overhead_share = exact_parent_tokens / total_tokens`
- `parallelism_ratio = sum(child_runtime_ms) / union_duration_of_child_intervals`

Return denominators beside every rate and nullable value. Never zero-fill unknown outcome, timing, model, pricing, credit, or linkage data.

Do not create a composite “efficiency score.” Present cost, elapsed time, acceptance, rework, and coverage separately so tradeoffs remain visible.

### Readiness gates

Raw descriptive results may always be displayed. Comparative conclusions must be suppressed and `claim_level` set to `insufficient_evidence` unless all applicable gates pass:

- at least 10 terminal work items in each compared cohort;
- at least 90% known terminal outcomes;
- at least 90% exact parent linkage for total-resource claims;
- at least 90% exact child linkage for delegated cohorts;
- complete token accounting for included rows;
- at least 90% configured credit coverage for credit comparisons;
- 100% configured or estimated price coverage, with estimated coverage visibly separated, for cost comparisons;
- no mixed JSONL/OTLP cohort classification unless source coverage is broken out;
- controlled claims additionally require a predeclared `experiment_id`, unique pair IDs, both arms for each included pair, and at least 10 valid pairs.

Thresholds live in one application policy module and are returned in the API response. They are not hidden dashboard constants.

## Persistence Design

Add three local SQLite tables through the normal migration system.

### `delegation_work_items`

Stores one row per logical work item:

- opaque `work_item_id` primary key;
- idempotency key, created/start/completion timestamps;
- cohort, task class, complexity, policy version;
- optional experiment, pair, and project keys;
- terminal outcome, validation status, outcome source, rework count;
- linked parent session ID plus link method/confidence;
- source revision and row version.

### `delegation_runs`

Stores one row per delegated child attempt:

- opaque `delegation_id` primary key and `work_item_id` foreign key;
- caller-supplied opaque delegation key;
- worker tier, normalized model alias, role/type, attempt number;
- requested, started, finished timestamps and terminal status;
- linked child session ID plus link method/confidence;
- source revision and row version.

### `delegation_events`

Stores the immutable lifecycle/audit sequence:

- opaque `event_id` and unique idempotency key;
- work-item/delegation foreign keys;
- event type, event timestamp, source;
- bounded JSON-free columns for event-specific enum/numeric values;
- ingestion timestamp and source revision.

Add indexes for time/cohort/outcome queries, experiment/pair lookup, parent and child session lookup, and idempotency. Do not store arbitrary JSON event payloads.

The explicit lifecycle tables are local runtime data and must remain absent from CSV, static HTML, support bundles, screenshots, and fixtures derived from real use.

## HTTP API Contract

This feature reuses the completed operation catalog, envelope, discovery, authentication, scope, job, cursor, and response-budget behavior defined by [`agent-http-api.md`](../../roadmap/agent-http-api.md). It adds only the Luna operation descriptors, typed handlers, inner schemas, and feature policy.

### Required operations

- `delegation.work_item.create` — idempotently create and start a work item.
- `delegation.event.append` — append one idempotent lifecycle event.
- `delegation.efficiency.query` — return a bounded aggregate comparison and readiness result.
- `delegation.work_item.get` — return one aggregate-safe work-item timeline with linkage/coverage, never prompt or output content.

The two write operations declare a new narrow `delegation_write` scope. The two read operations use `aggregate_read`. Feature handlers reject unknown fields, invalid transitions, duplicate IDs with different content, future timestamps outside policy, and free-form text fields; generic transport enforcement remains owned by the completed API.

`delegation.efficiency.query` accepts bounded time range, project, cohort, task class, complexity, policy version, experiment, comparison mode, grouping, limit, and cursor. It returns schema ID, source revision/freshness, cohort metrics, outcomes, timing, accounting, coverage, readiness, limitations, and evidence selectors.

Use a dedicated inner result contract such as `codex-usage-tracker.delegation-efficiency.v1` inside the canonical agent response envelope. Do not rename or silently extend `subagent-usage.v1` into an efficiency schema.

The operation uses `job.get` when its bounded workload exceeds the synchronous budget. Cap result rows and response bytes; paginate work-item lists with a revision-bound cursor.

## Dashboard Experience

Add a primary route named `efficiency` with the visible label **Delegation Efficiency**. Do not hide it under legacy Reports.

The page contains:

1. An evidence-readiness banner showing claim level, failed gates, source coverage, and data freshness.
2. Headline cards for accepted items, acceptance rate, rework rate, tokens/credits per accepted item, median elapsed time, and Sol overhead share.
3. A cohort comparison table for direct Sol, Luna high, Luna low, mixed, and unknown.
4. An outcome funnel from started to terminal, validated, accepted, and accepted without rework.
5. Queue, child runtime, integration time, wall-clock, and concurrency distributions.
6. Task-class and complexity breakdowns with explicit sample counts.
7. Controlled-pair results separated visually from observational results.
8. A paginated work-item table and privacy-safe detail timeline.
9. A compact instrumentation panel with copyable HTTP examples and service/token guidance.

Default labels use human-readable cohort, task class, outcome, and date values. Opaque IDs are visually subordinate. Prompts, outputs, task messages, tool arguments, raw commands, and agent nicknames never appear on this page.

All calculations come from the API. TypeScript validates the schema, formats values, manages filters/cache/polling, and renders server-provided limitations.

## Execution Plan

### Task 0: Freeze the Luna measurement contract and golden fixture

**Branch:** `test/<issue>-luna-efficiency-contract`

**Files:**

- Create: `docs/architecture/delegation-efficiency.md`
- Create: `tests/fixtures/delegation_efficiency/golden_cohorts.json`
- Create: `tests/fixtures/delegation_efficiency/golden_events.jsonl`
- Create: `tests/fixtures/delegation_efficiency/expected_efficiency.json`

- [ ] Copy the cohort, outcome, lifecycle, linkage, formula, claim-level, and readiness definitions from this plan into one normative feature contract.
- [ ] Freeze one synthetic dataset containing direct Sol, Luna high, Luna low, mixed, unknown, rework, failure, cancellation, timeout, concurrent children, partial pricing, ambiguous linkage, and a controlled pair.
- [ ] Hand-calculate and review every expected numerator, denominator, duration, resource total, and claim-level decision in the golden result.
- [ ] Record the API foundation version/catalog revision this feature requires.

**Acceptance:** an independent reviewer can derive the golden result from the fixture, and every later store/service/API/dashboard test consumes the same definitions.

### Task 1: Fix session identity and spawn-count coverage

**Branch:** `fix/<issue>-unknown-session-spawns`

**Files:**

- Modify: `src/codex_usage_tracker/core/models.py`
- Modify: `src/codex_usage_tracker/core/schema.py`
- Modify: `src/codex_usage_tracker/parser/jsonl_v1.py`
- Modify: `src/codex_usage_tracker/parser/jsonl_values.py`
- Modify: `src/codex_usage_tracker/store/schema.py`
- Modify: `src/codex_usage_tracker/store/subagent_usage_queries.py`
- Modify: `src/codex_usage_tracker/core/threads.py`
- Modify: parser/store/query tests

- [ ] Add `session_id_known` or an equivalent provenance field without destabilizing existing `record_id` deduplication.
- [ ] Generate missing-session record identity from deterministic source-file/event location, not the public `"unknown"` sentinel.
- [ ] Require a known, nonblank session ID for observed-spawn denominators.
- [ ] Backfill only rows whose missing-session provenance is provable; otherwise exclude ambiguous sentinels and expose coverage.
- [ ] Separate exact, inferred, and unmatched parent attachment counts.
- [ ] Add synthetic fixtures for missing filename ID, missing `session_meta`, multiple unidentified sessions, repeated events, and a legitimate literal source value.
- [ ] Confirm refresh remains idempotent and existing known-session record IDs remain stable.

**Acceptance:** unidentified rows contribute tokens/calls and missing-ID coverage but never observed spawn count or per-spawn denominators.

### Task 2: Prove the collaboration lifecycle source contract

**Branch:** `test/<issue>-delegation-lifecycle-contract`

**Files:**

- Create: `docs/architecture/delegation-lifecycle-source-contract.md`
- Create: `tests/fixtures/sessions/delegation_lifecycle/` with synthetic-only JSONL fixtures
- Modify: `src/codex_usage_tracker/store/refresh_parse.py`
- Modify: `src/codex_usage_tracker/store/content_extract.py`
- Modify: `src/codex_usage_tracker/store/content_index_events.py`
- Modify: parser/content-index tests

- [ ] Inspect current local collaboration records only to identify field names and state transitions; never copy task messages, prompts, outputs, or tool arguments into fixtures or docs.
- [ ] Specify safe extraction for opaque task/delegation IDs, worker tier, parent ID, timestamps, and terminal state.
- [ ] Route extraction through the existing parser observer/accumulator rather than scanning raw logs a second time.
- [ ] Define explicit mappings for observed completion, abort, rollback, timeout, and unknown.
- [ ] Document JSONL eligibility and expose OTLP-only lifecycle/classification gaps.
- [ ] Add a GO/NO-GO test: exact task/delegation/parent/child linkage must be deterministic from safe fields. If it is not, keep those fields unknown and rely on explicit API events.

**Acceptance:** synthetic fixtures reproduce the safe structural envelope, all extracted fields have provenance/confidence, and no fixture contains real content. Failure of the GO gate blocks automatic exact linkage but not the explicit lifecycle API.

### Task 3: Persist work items, runs, and immutable events

**Branch:** `feature/<issue>-delegation-efficiency-store`

**Files:**

- Modify: `src/codex_usage_tracker/store/schema.py`
- Create: `src/codex_usage_tracker/store/delegation_efficiency_store.py`
- Create: `src/codex_usage_tracker/application/delegation_models.py`
- Create: `tests/store/test_delegation_efficiency_store.py`
- Modify: migration and refresh-idempotency tests

- [ ] Add the three tables and indexes described in this plan through the next schema migration.
- [ ] Implement strict enum/domain validation in application models before SQL writes.
- [ ] Enforce idempotency-key uniqueness and reject same-key/different-content requests.
- [ ] Enforce legal state transitions and optimistic row versions for corrections.
- [ ] Keep events immutable; corrections append an audit event and update the projection transactionally.
- [ ] Define rebuild behavior: usage/session links can be recomputed, explicit work-item outcomes cannot be erased by refresh.
- [ ] Add migration, rollback-on-error, concurrency, duplicate-event, correction, and idempotent-refresh tests.

**Acceptance:** a refresh/reindex can enrich links without duplicating or losing explicit lifecycle/outcome data, and concurrent duplicate writes produce one canonical event.

### Task 4: Add authenticated lifecycle HTTP writes

**Branch:** `feature/<issue>-delegation-lifecycle-api`

**Files:**

- Create: `src/codex_usage_tracker/application/delegation_lifecycle.py`
- Create: `src/codex_usage_tracker/core/json_contract_delegation.py`
- Modify: `src/codex_usage_tracker/application/agent/catalog.py`
- Modify: `src/codex_usage_tracker/application/agent/dispatcher.py`
- Modify: `src/codex_usage_tracker/core/json_contracts.py`
- Create: `tests/application/test_delegation_lifecycle.py`
- Create: `tests/interfaces/http/test_delegation_lifecycle.py`

- [ ] Implement create-work-item and append-event services with deterministic transition errors.
- [ ] Register `delegation.work_item.create` and `delegation.event.append` in the canonical agent operation catalog.
- [ ] Declare `delegation_write` and use the completed API's authentication and request guards.
- [ ] Reject unknown fields and all free-form content fields.
- [ ] Bound clock skew, IDs, event count, and enum lengths in the feature schema.
- [ ] Return canonical resource IDs, row version, accepted event, and current projection.
- [ ] Publish the two Luna schemas and examples through the existing catalog and `meta.schema` extension points.
- [ ] Add exact replay/idempotency tests and conflict tests.

**Acceptance:** an agent can instrument a direct or Luna-assisted work item entirely through documented HTTP calls, retry every write safely, and never send task content.

### Task 5: Correlate explicit lifecycle with usage evidence

**Branch:** `feature/<issue>-delegation-usage-correlation`

**Files:**

- Create: `src/codex_usage_tracker/store/delegation_link_queries.py`
- Create: `src/codex_usage_tracker/application/delegation_linking.py`
- Modify: `src/codex_usage_tracker/store/refresh_parse.py`
- Modify: `src/codex_usage_tracker/store/api.py`
- Modify: `src/codex_usage_tracker/core/threads.py`
- Create: `tests/store/test_delegation_link_queries.py`
- Create: `tests/application/test_delegation_linking.py`

- [ ] Prefer explicit parent/child session IDs and safe lifecycle markers.
- [ ] Fall back only to deterministic one-candidate metadata matches; label time/cwd heuristics `inferred`.
- [ ] Never assign one usage session to multiple work items for the same interval without an explicit shared marker.
- [ ] Attribute parent usage once per work item even when multiple children overlap.
- [ ] Preserve actual source revision and linkage method on every projection update.
- [ ] Exclude OTLP-only rows from Luna classification unless later telemetry gains equivalent metadata.
- [ ] Add overlapping children, retries, nested subagents, missing parent, reused nickname, duplicate log, and ambiguous time-window tests.

**Acceptance:** exact-link coverage is reproducible; ambiguous records remain unmatched; no test can produce parent-cost multiplication through concurrent children.

### Task 6: Build the efficiency application service and stable response

**Branch:** `feature/<issue>-delegation-efficiency-service`

**Files:**

- Create: `src/codex_usage_tracker/store/delegation_efficiency_queries.py`
- Create: `src/codex_usage_tracker/application/delegation_efficiency.py`
- Create: `src/codex_usage_tracker/application/delegation_efficiency_policy.py`
- Create: `src/codex_usage_tracker/core/json_contract_efficiency.py`
- Modify: pricing/credit facades only where coverage metadata is needed
- Create: `tests/store/test_delegation_efficiency_queries.py`
- Create: `tests/application/test_delegation_efficiency.py`
- Create: `tests/core/test_json_contract_efficiency.py`

- [ ] Implement work-item-first aggregation and the formulas/readiness gates in this plan.
- [ ] Return descriptive, observational, and controlled sections separately.
- [ ] Match observational cohorts only within task class, complexity, project, and bounded time window; label the result non-causal.
- [ ] Include only complete valid pairs in controlled deltas and report dropped-pair reasons.
- [ ] Include model alias, pricing source/date, credit rate-card revision, source parser mix, and coverage denominators.
- [ ] Reuse lower-level canonical token/cost/credit calculations; do not parse the old Markdown report or generic compatibility summary.
- [ ] Return nullable metrics and limitations instead of invented zeros.
- [ ] Add edge tests for no data, one cohort, unknown outcomes, partial pricing, inferred linkage, OTLP-only input, concurrency, rework, and cancelled work.

**Acceptance:** application tests prove every displayed rate from explicit numerator/denominator fixtures, and the same fixture cannot be promoted above its evidence gates.

### Task 7: Publish the dedicated efficiency and detail operations

**Branch:** `feature/<issue>-delegation-efficiency-http`

**Files:**

- Modify: `src/codex_usage_tracker/application/agent/catalog.py`
- Modify: `src/codex_usage_tracker/application/agent/dispatcher.py`
- Modify: `src/codex_usage_tracker/core/json_contracts.py`
- Modify: existing agent catalog/schema generation
- Create: `tests/interfaces/http/test_delegation_efficiency.py`
- Modify: operation-catalog and schema-registry tests

- [ ] Register `delegation.efficiency.query` with strict bounded filters and revision-bound cursor pagination.
- [ ] Register aggregate-safe `delegation.work_item.get`.
- [ ] Dispatch both through the completed agent operation extension point and declare the existing job threshold policy.
- [ ] Stamp responses with schema, source revision, freshness, policy thresholds, and claim level.
- [ ] Declare `aggregate_read`, feature row/result budgets, and use the existing scope, job, cursor, and response-budget mechanisms.
- [ ] Add operation-specific schema, scope declaration, stale-revision, cancellation, pagination, and privacy tests; rely on the completed API foundation for generic transport coverage.

**Acceptance:** both Luna read operations are discoverable and callable through the existing API, and their inner results match the golden fixture exactly.

### Task 8: Add the primary Delegation Efficiency dashboard route

**Branch:** `feature/<issue>-delegation-efficiency-dashboard`

**Files:**

- Create: `frontend/dashboard/src/api/delegationEfficiency.ts`
- Create: `frontend/dashboard/src/features/efficiency/DelegationEfficiencyPage.tsx`
- Create: `frontend/dashboard/src/features/efficiency/DelegationEfficiencyPage.module.css`
- Create focused panel/components and colocated tests under `features/efficiency/`
- Modify: `frontend/dashboard/src/routes/evidenceConsoleRoutes.ts`
- Modify: `frontend/dashboard/src/routes/DashboardRouteView.tsx`
- Modify: `frontend/dashboard/src/routes/dashboardSearch.ts`
- Modify: `frontend/dashboard/src/app/routeCatalog.ts`
- Modify: `frontend/dashboard/src/data/dashboardQueryRegistry.ts`
- Modify: `frontend/dashboard/src/data/dashboardQueryContracts.json`
- Modify: `frontend/dashboard/src/api/types.ts`
- Modify: relevant App shell, route, and navigation tests

- [ ] Add the primary route and a typed `/api/v2/agent` client for the efficiency operations, with inner-result validation, source-revision cache key, cancellation, loading, retry, empty, and error states.
- [ ] Render the readiness banner before comparative cards.
- [ ] Implement cohort, outcome, timing/concurrency, task-mix, controlled-pair, and coverage panels.
- [ ] Add URL-addressable filters and preserve global time/project context.
- [ ] Keep technical IDs subordinate and drill down only to aggregate-safe work-item evidence.
- [ ] Add direct HTTP instrumentation examples for the four Luna operations.
- [ ] Ensure cards and charts show denominators, unknown values, and partial pricing rather than zeros.
- [ ] Verify keyboard navigation, focus, screen-reader labels, reduced motion, desktop-small, tablet, and phone layouts.

**Acceptance:** component tests cover all claim levels and coverage failures; Playwright uses synthetic data and proves the primary workflow at configured breakpoints. Generated packaged assets are produced by the normal Vite build, never hand-edited.

### Task 9: Document and teach the Luna efficiency workflow

**Branch:** `docs/<issue>-luna-efficiency-guidance`

**Files:**

- Create: `docs/delegation-efficiency.md`
- Modify: `docs/dashboard-guide.md`
- Modify source and packaged copies of `skills/codex-usage-api/SKILL.md`

- [ ] Document how to instrument direct and Luna-assisted work through the four cataloged operations.
- [ ] Document cohort, lifecycle, outcome, linkage, formula, claim-level, and readiness semantics with concrete synthetic examples.
- [ ] Add the primary dashboard workflow, filter meanings, unknown/coverage behavior, and controlled-pair workflow.
- [ ] Document the feature's privacy boundary and why no task content is accepted or displayed.
- [ ] Explain descriptive versus observational versus controlled claims in user-facing language.
- [ ] Keep the Luna sections in the two source/bundled skill copies aligned and test their operation/schema examples against the feature catalog entries.

**Acceptance:** with the completed API already running, a user can instrument a work item, open the dashboard, interpret every metric/limitation, and reproduce the aggregate query using shipped Luna-efficiency guidance.

### Task 10: Performance, privacy, and feature acceptance

**Branch:** `test/<issue>-luna-efficiency-hardening`

**Files:**

- Modify: `scripts/benchmark_dashboard_routes.py`
- Modify: `scripts/dashboard_route_benchmark_support.py`
- Modify: `tests/cli/test_dashboard_route_benchmark.py`
- Modify: `tests/dashboard/test_dashboard_payload_privacy.py`
- Modify: `tests/core/test_privacy.py`
- Create: `tests/playwright/dashboard-delegation-efficiency.spec.mjs`

- [ ] Generate a 100k-row synthetic workload with direct, Luna high/low, mixed, unknown, incomplete-price, inferred-link, concurrent, retry, and controlled-pair cases.
- [ ] Record the identical cold/warm unprofiled workload before optimizing.
- [ ] Enforce bounded efficiency SQL, covering indexes, and no Python all-history materialization; use the API foundation's cursor and response limits.
- [ ] Set and document endpoint cold/warm p50/p95 budgets from the baseline before making speed claims.
- [ ] Add privacy scans proving no prompt/output/tool-argument fields enter efficiency tables, JSON, HTML, support bundles, docs, screenshots, or fixtures.
- [ ] Run one focused synthetic end-to-end workflow covering work creation, delegation events, refresh/linking, efficiency query, work-item detail, and dashboard rendering.
- [ ] Record the Luna-focused verification and measured budgets in the feature ledger. Generic API, package, CI, and release gates remain owned by their existing plans.

**Acceptance:** focused correctness, privacy, performance, and browser gates pass on synthetic data, and the dashboard refuses to make a comparative claim when any configured evidence gate fails.

## Verification Matrix

| Risk | Required proof |
|---|---|
| False spawn counts | Missing-session parser and SQL denominator regression tests |
| Duplicate lifecycle writes | Idempotency and same-key/different-content conflict tests |
| Invalid state | Full lifecycle transition table tests |
| Parent cost double-counting | Concurrent-child work-item aggregation test |
| False success | Unknown/observed/accepted outcome distinction tests |
| Misclassified Luna | Subagent predicate plus model-alias revision tests |
| OTLP ambiguity | Source-coverage response and exclusion tests |
| Partial pricing | Separate configured/estimated/unpriced coverage tests |
| Causal overclaim | Claim-level/readiness gate tests and controlled-pair tests |
| Privacy leakage | Luna schema allowlist, response snapshot, HTML, fixture, and secret-pattern tests |
| Unbounded Luna query | Feature row/time limits and completed API budget integration tests |
| Wrong authorization | Operation scope declarations and write/read scope tests |
| Dashboard/API drift | Golden inner-result fixture, Luna catalog/schema entries, and TypeScript validator parity |

## Required Local Gates

Run focused tests first for every task. The final Luna feature branch runs at least:

```text
python -m pytest tests/parser tests/store/test_subagent_usage_queries.py tests/store/test_delegation_efficiency_store.py tests/store/test_delegation_link_queries.py
python -m pytest tests/application/test_delegation_lifecycle.py tests/application/test_delegation_linking.py tests/application/test_delegation_efficiency.py
python -m pytest tests/interfaces/http/test_delegation_lifecycle.py tests/interfaces/http/test_delegation_efficiency.py tests/dashboard/test_dashboard_payload_privacy.py tests/core/test_privacy.py
python -m pytest tests/cli/test_dashboard_route_benchmark.py
python -m ruff check <touched Python files>
python -m mypy
python -m compileall src
npm.cmd test -- delegationEfficiency
npm.cmd run typecheck
npm.cmd run build
npx.cmd playwright test tests/playwright/dashboard-delegation-efficiency.spec.mjs --project=desktop-wide --project=desktop-small --project=tablet --project=phone
git diff --check
```

Run frontend commands from `frontend/dashboard` where required. Tests and screenshots use synthetic aggregate data only. The API and release programs still run their own generic/full repository gates before merge or publication; this feature plan does not duplicate them.

## Definition of Done

- The completed agent HTTP API prerequisite is green and unchanged except for registering the four Luna operations and their schemas/policies.
- Luna analytical behavior is exposed through the canonical `/api/v2/agent` operation API and rendered by the dashboard.
- All four Luna operations are discoverable, bounded, versioned, privacy-classified, and covered by the canonical agent catalog, envelope, and route inventory.
- Missing session identity cannot inflate spawn counts.
- Work items, delegated runs, lifecycle events, outcomes, validation, rework, and experiment identity are persisted idempotently without raw content.
- Parent/child linkage and all rate denominators expose exact/inferred/unmatched coverage.
- Parent usage is counted once per work item regardless of child concurrency.
- The API distinguishes descriptive, observational, controlled, and insufficient evidence.
- The dashboard makes no stronger claim than the API's readiness gates permit.
- Direct agents can discover and use the complete Luna workflow through HTTP.
- Luna documentation, skills, golden fixtures, inner schema, API operations, and dashboard all use the same measurement contract.

## Explicit Non-Goals

- No remote/cloud telemetry or hosted analytics service.
- No raw prompt, response, task message, tool argument, command text, or agent-output storage.
- No composite efficiency score.
- No inference that token use, `task_complete`, a successful command, or a patch alone means accepted work.
- No causal claim from unmatched observational cohorts.
- No attempt to make OTLP rows look attribution-complete when required metadata is absent.
- No changes to generic API discovery, credentials, jobs, service lifecycle, MCP/CLI migration, or broader compatibility work owned by `agent-http-api.md`.
