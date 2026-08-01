# Dashboard usage statistics

The Statistics page is a dashboard-only feature. It is served by the localhost dashboard through `POST /api/v2/statistics`; it is not registered as an MCP tool and has no CLI command.

## Data source

Statistics are calculated from current `recommendation_facts`. Those facts contain one canonical call per row plus the model-normalized Codex credit estimate, token counters, context utilization, and credit confidence. The endpoint refuses to report stale values when the recommendation-fact generation differs from the current source generation. Refresh the usage index to rebuild the facts.

Unpriced calls are unknown, not zero-credit calls. Credit totals and distributions use only calls with a numeric credit estimate. Every response also reports total calls, priced calls, unpriced calls, the priced-call ratio, and confidence counts. The dashboard displays unavailable credit values as `—`; a visible zero means a measured zero.

## Range and timezone

The dashboard includes Last 24 hours, 7-day, 30-day, 90-day, 365-day, and All time ranges. Last 24 hours is a rolling 24-hour interval and automatically selects the hourly graph. Longer calendar presets begin at local midnight on their first included date.

The dashboard sends inclusive `since` and exclusive `until` timestamps plus the browser's IANA timezone. Calendar dates and the 7×24 activity heatmap use that timezone. Elapsed-hour denominators use UTC duration, avoiding duplicated or missing elapsed hours during daylight-saving transitions.

The All time preset queries the full stored range but clamps calendar-day and elapsed-hour denominators to the first matching call.

The usage graph supports Daily and Hourly views. Hourly data is returned only for Last 24 hours, 7-day, and 30-day ranges. Longer ranges automatically use Daily view. The hourly series contains one zero-filled point per elapsed UTC hour and includes each point's local offset timestamp. A spring daylight-saving transition therefore has 23 local-day points, while a fall transition has 25 and preserves both repeated local hours.

The graph can display either known credits or call count without requesting the statistics again.

## Definitions

- **Mean credits per priced call:** known credits divided by priced calls.
- **Median, P75, P90, and P95:** linearly interpolated quantiles over per-call credit estimates.
- **Population standard deviation:** spread of selected per-call credit estimates.
- **Calendar day:** a local date intersecting the selected effective range, including zero-use dates.
- **Active day:** a local date containing at least one call.
- **Elapsed hour:** selected effective duration divided by 3,600 seconds.
- **Active hour:** a distinct UTC hour bucket containing at least one call.
- **Activity session:** consecutive calls separated by no more than the configured idle-gap threshold. This is independent of Codex session IDs.
- **Model transition:** a change between adjacent call models inside one inferred activity session.

A single-call activity session has a zero-second span. The tracker does not invent an assumed duration.

## Model comparison

The model table has Summary, Token composition, and Full column presets. Every numeric column is sortable, and selecting a model filters the entire statistics page. The model column and table header remain visible while scrolling a wide or long comparison.

Token averages use all selected calls for the model:

- average total tokens per call
- average input tokens per call
- average cached and uncached input tokens per call
- average output tokens per call
- average reasoning-output tokens per call

Ratios are calculated from aggregate totals rather than by averaging per-call percentages:

- **Weighted cache ratio:** total cached input divided by total input tokens.
- **Output ratio:** total output divided by total tokens.
- **Reasoning ratio:** total reasoning-output tokens divided by total output tokens.
- **Average context:** arithmetic mean of recorded context-window utilization values.

The table also reports call share, known-credit share, active days, active hours, and known credits per million total tokens. Credit fields remain unavailable when a model has no priced calls even though its token statistics remain usable. Missing or whitespace-only logged model labels are grouped under `Unknown model`.

## Concentration

The page reports the share of known credits consumed by the top 1% and top 10% of priced calls and the busiest day, hour, and inferred session.

## Privacy and transport

The endpoint returns aggregate statistics plus a bounded list of expensive call identifiers for opening local evidence. It does not return prompts, assistant text, tool output, commands, source paths, or unbounded raw call rows.
