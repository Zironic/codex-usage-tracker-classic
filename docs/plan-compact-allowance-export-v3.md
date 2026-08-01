# Compact Allowance Evidence Export v3 Implementation Plan

## Objective

Add minute-resolution timing to the strict-privacy allowance evidence export without returning to the repetitive object-per-span v1 format or breaking existing consumers.

The new default compact schema will preserve enough temporal information to estimate active usage hours, usage bursts, idle gaps, cross-boundary activity, partial-day effects, and usage rate per active hour. It will continue to omit prompts, assistant text, tool output, paths, thread names, record IDs, session IDs, and raw exact timestamps.

## Compatibility contract

Three explicit export modes will coexist:

- `format=compact` returns `codex-usage-tracker-allowance-evidence-export-v3`.
- `format=compact-v2` returns the existing date-only `codex-usage-tracker-allowance-evidence-export-v2`.
- `format=verbose` returns the historical object-per-span `codex-usage-tracker-allowance-evidence-export-v1`.
- An omitted `format` continues to return verbose v1 at the HTTP route so stale bundled dashboards fail safely rather than rejecting an unexpected schema.

The dashboard and CLI will request `compact` explicitly and therefore move to v3 after their source and generated assets are updated.

## V3 schema design

### Export-wide time basis

Add these fields under `layout`:

- `time_origin`: the earliest selected observation timestamp, converted to UTC and rounded down to the start of its minute; null when the export contains no observations.
- `time_unit`: always `minute`.
- `timestamp_precision`: always `minute_floor`.

A single origin avoids repeating ISO timestamps in every span row.

### Span rows

Replace the v2 date columns with minute offsets:

1. `start_minute`
2. `end_minute`
3. `start_used_percent`
4. `end_used_percent`
5. `estimated_usage_credits`
6. `row_count`

`start_minute` and `end_minute` are signed integer minute offsets from `layout.time_origin`. When the end offset equals the start offset, `end_minute` is encoded as null. This mirrors the v2 same-date compression and keeps short spans compact.

### Change candidates

Replace date-bucketed candidate boundaries with:

- `candidate_start_minute`
- `candidate_end_minute`

The same export-wide origin and minute-floor convention apply.

### Coverage

Retain `coverage.start_date` and `coverage.end_date` as human-readable coarse bounds. They remain useful for quickly understanding the export period, while the span rows carry the analytical timing precision.

### Privacy

The serializer may receive internal diagnostic spans containing exact timestamps and local identifiers, but must emit only:

- minute offsets,
- allowance percentages,
- estimated credits,
- aggregate row counts,
- confidence summaries,
- aggregate plan comparison fields.

Tests must explicitly search the serialized payload for source record IDs, session IDs, thread keys, and exact source timestamps.

## File-by-file implementation

### `src/codex_usage_tracker/allowance_intelligence/export_payload.py`

1. Promote `ALLOWANCE_EXPORT_COMPACT_SCHEMA` to v3.
2. Add `ALLOWANCE_EXPORT_COMPACT_V2_SCHEMA` for compatibility.
3. Extend `ALLOWANCE_EXPORT_FORMATS` with `compact-v2`.
4. Define separate v2 and v3 span column declarations.
5. Make `build_compact_allowance_export` build v3 and accept `time_origin`.
6. Add `build_compact_allowance_export_v2` containing the current date-only behavior.
7. Make v3 window, span, and candidate serializers convert ISO timestamps to minute offsets.
8. Keep v2 serializers date-bucketed and behaviorally unchanged.
9. Add defensive timestamp parsing:
   - accept `Z` and explicit offsets,
   - treat naive timestamps as UTC,
   - normalize all arithmetic to UTC,
   - return null rather than inventing an offset for invalid or missing timestamps.
10. Keep plan-comparison sanitization shared by v2 and v3.

### `src/codex_usage_tracker/allowance_intelligence/reports.py`

1. Recognize v1, v2, and v3 schemas in rendering.
2. For compact exports, build internal diagnostics with exact timestamps retained until serialization.
3. Continue building verbose v1 through strict date-only filtering.
4. Derive the export-wide UTC minute origin from the first selected observation.
5. Route `compact` to the v3 builder and `compact-v2` to the compatibility builder.
6. Update export notes:
   - v3 states that timestamps are represented as minute offsets from a UTC origin,
   - v2 states that timestamps are bucketed to dates,
   - v1 retains its historical behavior.
7. Ensure all compact builders remain strict at the serialized boundary even though their internal input contains local identifiers.

### `src/codex_usage_tracker/server/allowance.py`

No structural route change is required. The existing `format` value is forwarded to the report builder. The report builder’s expanded format validation will enable `compact-v2`. The omitted-format v1 fallback remains unchanged.

### `src/codex_usage_tracker/cli/parser_data.py`

1. Add `compact-v2` to `allowance-export --format` choices.
2. Update help text so `compact` is described as minute-resolution v3, `compact-v2` as date-only compatibility output, and `verbose` as v1.

### `frontend/dashboard/src/api/allowance.ts`

1. Preserve the v1 and v2 payload types.
2. Add v3 span-row and payload types.
3. Add v3 `layout.time_origin`, `time_unit`, and `timestamp_precision` fields.
4. Expand the export payload union to include v3.
5. Expand request format choices to include `compact-v2`.
6. Make default `compact` expect schema v3.
7. Map `compact-v2` to schema v2 and `verbose` to schema v1.
8. Mark `plan_comparison` optional because it is omitted unless a comparison is requested.

### `src/codex_usage_tracker/core/json_contract_allowance.py`

1. Add a v3 contract requiring request, coverage, layout, summary, windows, and notes.
2. Require v3 layout timing metadata with nullable `time_origin`.
3. Retain the existing v2 contract unchanged.

### `tests/allowance_intelligence/test_allowance_export_compact.py`

1. Update the primary compact-row test to assert minute offsets.
2. Add cross-hour and cross-day timestamp cases.
3. Verify equal-minute end offsets compress to null.
4. Verify offset arithmetic across timezone offsets normalizes through UTC.
5. Keep a dedicated v2 compatibility test proving date rows are unchanged.
6. Update the size-budget test to compare v3 against verbose v1.
7. Verify complete coverage metadata and strict identifier removal.
8. Verify exact timestamps are absent while `layout.time_origin` and offsets reconstruct minute-level timing.
9. Verify empty exports use a null origin and remain valid.

### `tests/server/test_server_allowance.py`

1. Change explicit `format=compact` expectations from v2 to v3.
2. Add explicit `format=compact-v2` coverage.
3. Retain omitted-format verbose-v1 compatibility coverage.
4. Update invalid-format error expectations to mention all accepted modes.

### `frontend/dashboard/src/api/allowance.test.ts`

1. Change the default compact schema expectation to v3.
2. Verify `format=compact` remains explicit in the URL.
3. Add a `compact-v2` request/schema test.
4. Retain verbose-v1 coverage.

### Generated dashboard assets

The connector cannot run the TypeScript build. After pulling locally, run:

```powershell
npm ci
npm run dashboard:build
```

This regenerates `src/codex_usage_tracker/plugin_data/dashboard/react` so the served button requests and accepts v3.

## Validation criteria

The implementation is complete when all of the following hold:

1. `allowance-export --format compact` emits schema v3.
2. The dashboard export button requests `format=compact` and accepts v3.
3. V3 span timestamps can be reconstructed to minute precision from `layout.time_origin` and row offsets.
4. V3 contains no exact per-span ISO timestamp strings.
5. V3 contains no record, session, thread, or path identifiers.
6. `format=compact-v2` reproduces the date-only v2 shape.
7. `format=verbose` and omitted HTTP format continue to produce v1.
8. The full unbounded export remains materially smaller than verbose v1.
9. Python tests, frontend tests, type checking, and the dashboard build pass.

## Local verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests/allowance_intelligence/test_allowance_export_compact.py tests/server/test_server_allowance.py
npm run dashboard:test -- --run frontend/dashboard/src/api/allowance.test.ts
npm run dashboard:typecheck
npm run dashboard:build
```

Then restart the local server, hard-refresh the dashboard, export again, and verify the JSON begins with the v3 schema and includes `layout.time_origin` plus integer minute offsets.
