# Dashboard usage statistics

The Statistics page is a dashboard-only feature. It is served by the localhost dashboard through `POST /api/v2/statistics`; it is not registered as an MCP tool and has no CLI command.

## Data source

Statistics are calculated from current `recommendation_facts`. Those facts contain one canonical call per row plus the model-normalized Codex credit estimate and its confidence. The endpoint refuses to report stale values when the recommendation-fact generation differs from the current source generation. Refresh the usage index to rebuild the facts.

Unpriced calls are unknown, not zero-credit calls. Credit totals and distributions use only calls with a numeric credit estimate. Every response also reports total calls, priced calls, unpriced calls, the priced-call ratio, and confidence counts.

## Range and timezone

The dashboard sends inclusive `since` and exclusive `until` timestamps plus the browser's IANA timezone. Calendar dates and the 7×24 activity heatmap use that timezone. Elapsed-hour denominators use UTC duration, avoiding duplicated or missing elapsed hours during daylight-saving transitions.

The All time preset queries the full stored range but clamps calendar-day and elapsed-hour denominators to the first matching call.

The usage graph supports Daily and Hourly views. Hourly data is returned only for ranges of 30 elapsed days or less, which currently corresponds to the 7-day and 30-day dashboard presets. Longer ranges automatically use Daily view. The hourly series contains one zero-filled point per elapsed UTC hour and includes each point's local offset timestamp. A spring daylight-saving transition therefore has 23 local-day points, while a fall transition has 25 and preserves both repeated local hours.

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

## Concentration

The page reports the share of known credits consumed by the top 1% and top 10% of priced calls and the busiest day, hour, and inferred session.

## Privacy and transport

The endpoint returns aggregate statistics plus a bounded list of expensive call identifiers for opening local evidence. It does not return prompts, assistant text, tool output, commands, source paths, or unbounded raw call rows.
