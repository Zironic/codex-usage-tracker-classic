# Dashboard usage statistics

The Statistics page is a dashboard-only feature. It is served by the localhost dashboard through `POST /api/v2/statistics`; it is not registered as an MCP tool and has no CLI command.

## Data source

Statistics are calculated from current `recommendation_facts` joined to the corresponding canonical usage events. The materialized facts supply timestamp-normalized credits and token counters. Canonical events supply turn, timing, initiator, plan, meter, service-tier, Fast-mode, subagent, project, and thread dimensions.

The endpoint refuses to report stale values when the recommendation-fact generation differs from the current source generation. Refresh the usage index to rebuild the facts.

Unpriced calls are unknown, not zero-credit calls. Credit totals and distributions use only calls with a numeric credit estimate. Every response also reports total calls, priced calls, unpriced calls, the priced-call ratio, and confidence counts. The dashboard displays unavailable credit values as `—`; a visible zero means a measured zero.

## Range and timezone

The dashboard includes Last 24 hours, 7-day, 30-day, 90-day, 365-day, and All time ranges. Last 24 hours is a rolling 24-hour interval and automatically selects the hourly graph. Longer calendar presets begin at local midnight on their first included date.

The dashboard sends inclusive `since` and exclusive `until` timestamps plus the browser's IANA timezone. Calendar dates, hourly labels, and the 7×24 activity heatmap use that timezone. Elapsed-hour denominators use UTC duration, avoiding duplicated or missing elapsed hours during daylight-saving transitions.

The All time preset queries the full stored range but clamps calendar-day and elapsed-hour denominators to the first matching call.

The usage graph supports Daily and Hourly views. Hourly data is returned only for Last 24 hours, 7-day, and 30-day ranges. Longer ranges automatically use Daily view. The hourly series contains one zero-filled point per elapsed UTC hour and includes each point's local offset timestamp. A spring daylight-saving transition therefore has 23 local-day points, while a fall transition has 25 and preserves both repeated local hours.

The graph can display known credits, call count, or estimated active minutes without requesting the statistics again.

## True active time

Occupied hour buckets are retained as a descriptive grouping, but they are not used as an estimate of real working time.

For each call, estimated active time is:

```text
measured call duration
+ min(non-overlapping idle gap before the call starts, configured active-gap cap)
```

The default active-gap cap is five minutes and can be changed from zero to sixty minutes. Zero means call duration only.

The estimate has the following safeguards:

- The first selected call cannot import activity from before the selected range.
- A gap that overlaps measured call duration is not counted again.
- Consecutive calls inside the same turn use the prior completed call as the next call's start, so the interval is measured once.
- Missing or invalid call-start timestamps fall back to zero measured duration rather than inventing time.

The page reports measured call-duration seconds, capped idle-gap seconds, estimated active minutes and hours, calls per active hour, and credits per active hour. The older occupied-bucket rates remain available internally as `calls_per_active_hour_bucket` and `credits_per_active_hour_bucket`.

## Sessions and uninterrupted periods

An activity session is a run of calls separated by no more than the configured session-gap threshold. This remains independent of Codex session IDs.

For every inferred session, the page reports:

- wall-clock span from first call start to last call completion;
- estimated active time;
- calls and distinct turns;
- priced calls and known credits;
- subagent calls and model switches;
- credits per estimated active hour.

Median, P75, and P90 session durations use wall-clock spans. The longest uninterrupted periods are ranked by estimated active time. A single-call session may have non-zero duration when the call log contains a usable turn or call start timestamp.

## Turns

Distinct turns are grouped from the recorded session and turn identifiers. When those identifiers are unavailable, the call forms its own fallback turn group.

The page reports:

- distinct turns;
- calls per turn;
- known credits per turn;
- subagent calls per turn;
- the most active turn groups.

Persisted session and turn identifiers never leave the statistics service. Before serialization, they are replaced with response-local ordinal group numbers.

## Plan and rate-period comparison

The page automatically segments consecutive calls whenever either of these values changes:

- the observed allowance plan;
- the credit-rate revision selected for the call's event timestamp.

The same plan and rate revision can therefore appear in more than one row when usage later returns to that combination.

Each cohort reports:

- calls, active minutes, turns, and credits per elapsed day;
- credits per priced call;
- credits per turn;
- credits per estimated active hour;
- model and effort mix;
- primary and secondary meter burn per day where observations exist.

Meter burn sums only non-negative changes between consecutive observations. Decreases are treated as meter resets and are not subtracted from later burn.

The dashboard also accepts an arbitrary before/after timestamp inside the selected range. This produces two cohorts using the same definitions and is intended for releases, plan changes, rate changes, and workflow experiments.

## Initiator, effort, tier, and Fast-mode decomposition

The recurring breakdowns include:

- user/direct versus subagent calls;
- raw initiator;
- effort;
- service tier;
- Standard versus Fast;
- model × effort;
- initiator type × model;
- initiator type × local active hour.

Every group reports calls, tokens, known credits, estimated active minutes, turns, subagent calls, and normalized per-turn and per-active-hour rates. Token and call metrics include unpriced calls; credit metrics retain explicit priced-call coverage.

A call is classified as a subagent call when the event identifies a subagent thread, subagent type, or parent session.

## Project and thread attribution

Project attribution uses only the final component of the recorded working directory. Full local paths are not returned. Missing project identity is grouped as `Unknown project`.

Thread attribution uses the visible thread name when available and falls back to the canonical thread key.

The page reports the top projects and threads by calls, known credits, and estimated active time. Each row includes call share, credit share, active-time share, turns, credits per active hour, and model and effort mix.

Project and thread concentration includes top-group share and Herfindahl–Hirschman indexes for calls and known credits.

## Model comparison

The model table has Summary, Token composition, and Full column presets. Every numeric column is sortable, and selecting a model filters the entire statistics page. The model column and table header remain visible while scrolling a wide or long comparison.

Token averages use all selected calls for the model:

- average total tokens per call;
- average input tokens per call;
- average cached and uncached input tokens per call;
- average output tokens per call;
- average reasoning-output tokens per call.

Ratios are calculated from aggregate totals rather than by averaging per-call percentages:

- **Weighted cache ratio:** total cached input divided by total input tokens.
- **Output ratio:** total output divided by total tokens.
- **Reasoning ratio:** total reasoning-output tokens divided by total output tokens.
- **Average context:** arithmetic mean of recorded context-window utilization values.

The table also reports call share, known-credit share, active days, occupied UTC hour buckets, and known credits per million total tokens. Credit fields remain unavailable when a model has no priced calls even though its token statistics remain usable. Missing or whitespace-only logged model labels are grouped under `Unknown model`.

## Call-level diagnostics

The bounded expensive-call list now also carries duration, estimated active time, effort, initiator type, project, thread, reasoning tokens, cache ratio, and context-window utilization. These fields support follow-up rankings without returning unbounded raw calls.

## Compact research export

The compact Calls JSON and CSV remain the escape hatch for novel analyses. In addition to the existing dimensions, they include:

- `plan`;
- `rate_revision`;
- `fast`;
- `turn_group`;
- `subagent_type`.

`turn_group` is an opaque file-local integer. The encoder uses the original session and turn values only as private map keys and never serializes them. Record IDs, session IDs, turn IDs, parent IDs, CWDs, source files, Git identifiers, prompts, assistant text, tool output, and commands remain omitted.

The live Calls API supplies plan and rate revision. A bounded loaded-dashboard snapshot may lack those fields and is explicitly marked as an incomplete result set.

## Privacy and transport

The Statistics endpoint returns aggregates plus bounded local call identifiers for opening evidence in the same dashboard. It does not return prompts, assistant text, tool output, commands, full source paths, raw turn identifiers, or unbounded raw call rows.
