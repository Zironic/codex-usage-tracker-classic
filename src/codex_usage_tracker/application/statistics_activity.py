"""True active-time and call-dimension semantics for dashboard statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any


@dataclass(frozen=True)
class EnrichedCall:
    """One canonical priced call with derived activity and grouping dimensions."""

    row: dict[str, Any]
    observed: datetime
    local_day: date
    local_hour: int
    call_started_at: datetime
    duration_seconds: float
    capped_gap_seconds: float
    active_seconds: float
    turn_key: str
    is_subagent: bool
    project: str
    thread: str
    initiator: str
    initiator_kind: str
    service_tier: str
    fast_mode: str
    plan: str
    rate_revision: str
    model: str
    effort: str
    credits: float | None
    total_tokens: int
    primary_meter_percent: float | None
    secondary_meter_percent: float | None


def enrich_call(
    row: dict[str, Any],
    *,
    observed: datetime,
    range_start: datetime,
    local_day: date,
    local_hour: int,
    gap_cap_seconds: float,
    rate_revision: str,
) -> EnrichedCall:
    """Derive bounded active time without double-counting call duration and idle gaps."""

    previous = _timestamp(row.get("previous_call_event_timestamp"))
    turn_started = _timestamp(row.get("turn_timestamp"))
    same_turn_previous = (
        previous is not None
        and _text(row.get("previous_call_session_id")) == _text(row.get("session_id"))
        and bool(_text(row.get("previous_call_turn_id")))
        and _text(row.get("previous_call_turn_id")) == _text(row.get("turn_id"))
    )
    started = previous if same_turn_previous else turn_started
    if started is None or started > observed:
        started = observed
    started = max(started, range_start)
    duration_seconds = max((observed - started).total_seconds(), 0.0)
    capped_gap_seconds = 0.0
    if previous is not None and previous >= range_start and started > previous:
        capped_gap_seconds = min((started - previous).total_seconds(), gap_cap_seconds)
    subagent = _is_subagent(row)
    return EnrichedCall(
        row=row,
        observed=observed,
        local_day=local_day,
        local_hour=local_hour,
        call_started_at=started,
        duration_seconds=duration_seconds,
        capped_gap_seconds=max(capped_gap_seconds, 0.0),
        active_seconds=duration_seconds + max(capped_gap_seconds, 0.0),
        turn_key=_turn_key(row),
        is_subagent=subagent,
        project=_project_label(row.get("cwd")),
        thread=_thread_label(row),
        initiator=_label(row.get("call_initiator"), "unknown"),
        initiator_kind="Subagent" if subagent else "User/direct",
        service_tier=_label(row.get("service_tier"), "Unknown tier"),
        fast_mode=_fast_mode(row.get("fast")),
        plan=_label(row.get("rate_limit_plan_type"), "Unknown plan"),
        rate_revision=rate_revision or "Unknown rate revision",
        model=_label(row.get("model"), "Unknown model"),
        effort=_label(row.get("effort"), "Unknown effort"),
        credits=_optional_number(row.get("usage_credits")),
        total_tokens=max(_integer(row.get("total_tokens")), 0),
        primary_meter_percent=_percent(row.get("rate_limit_primary_used_percent")),
        secondary_meter_percent=_percent(row.get("rate_limit_secondary_used_percent")),
    )


def _turn_key(row: dict[str, Any]) -> str:
    session = _text(row.get("session_id"))
    turn = _text(row.get("turn_id"))
    if session and turn:
        return f"{session}:{turn}"
    if turn:
        return f"turn:{turn}"
    record = _text(row.get("record_id")) or _text(row.get("event_timestamp"))
    return f"record:{record or 'unknown'}"


def _is_subagent(row: dict[str, Any]) -> bool:
    return (
        _text(row.get("thread_source")).lower() == "subagent"
        or bool(_text(row.get("subagent_type")))
        or bool(_text(row.get("parent_session_id")))
    )


def _project_label(value: object) -> str:
    text = _text(value).rstrip("/\\")
    if not text:
        return "Unknown project"
    parts = [part for part in text.replace("\\", "/").split("/") if part]
    return parts[-1] if parts else "Unknown project"


def _thread_label(row: dict[str, Any]) -> str:
    return _label(row.get("thread_name") or row.get("thread_key"), "Untitled thread")


def _fast_mode(value: object) -> str:
    if value is True or value == 1:
        return "Fast"
    if value is False or value == 0:
        return "Standard"
    return "Unknown mode"


def _label(value: object, fallback: str) -> str:
    text = _text(value)
    return text or fallback


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return 0


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if parsed >= 0 else None


def _percent(value: object) -> float | None:
    parsed = _optional_number(value)
    if parsed is None:
        return None
    return parsed * 100 if parsed <= 1 else parsed
