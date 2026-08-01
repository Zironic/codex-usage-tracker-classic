"""Decision metadata for the stable agent HTTP route."""

from __future__ import annotations

from codex_usage_tracker.server.route_profile import DashboardRouteProfile, profile

AGENT_ROUTE_PROFILES: tuple[DashboardRouteProfile, ...] = (
    profile(
        "GET",
        "/api/v2/agent",
        "_handle_http_agent",
        "interfaces.http.agent",
        "interactive",
        "Returns the immutable enabled-operation catalog without usage data.",
        "One compact catalog up to 128 KiB.",
        "Process-static application catalog; never response-cached in the browser.",
        exposure="stable",
        output_limit_bytes=128 * 1024,
    ),
    profile(
        "POST",
        "/api/v2/agent",
        "_handle_http_agent",
        "interfaces.http.agent",
        "interactive",
        "Dispatches one allowlisted operation through the owning application service.",
        "Operation-specific bounded envelope, at most 512 KiB input and catalog output.",
        "Application-owned semantic reuse; no raw/indexed response caching.",
        may_scan_all_history=True,
        exposure="stable",
        input_limit_bytes=512 * 1024,
        output_limit_bytes=256 * 1024,
    ),
)
