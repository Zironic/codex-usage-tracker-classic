"""Typed request contract for dashboard-only usage statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.util import find_spec
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HistoryScope = Literal["active", "all"]


@dataclass(frozen=True)
class StatisticsRequest:
    """Bounded dashboard statistics request."""

    since: str
    until: str
    timezone: str
    history: HistoryScope = "active"
    model: str | None = None
    session_gap_minutes: int = 30
    top_limit: int = 10
    all_time: bool = False

    def __post_init__(self) -> None:
        start = parse_statistics_timestamp(self.since, "since")
        end = parse_statistics_timestamp(self.until, "until")
        if start >= end:
            raise ValueError("since must be earlier than until")
        if self.history not in {"active", "all"}:
            raise ValueError("history must be active or all")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            if find_spec("tzdata") is None:
                raise ValueError(
                    "IANA timezone database unavailable; reinstall the tracker dependencies "
                    "or install the tzdata package"
                ) from exc
            raise ValueError(f"unknown IANA timezone: {self.timezone}") from exc
        if type(self.session_gap_minutes) is not int or not 5 <= self.session_gap_minutes <= 240:
            raise ValueError("session_gap_minutes must be between 5 and 240")
        if type(self.top_limit) is not int or not 1 <= self.top_limit <= 50:
            raise ValueError("top_limit must be between 1 and 50")
        if type(self.all_time) is not bool:
            raise ValueError("all_time must be a boolean")
        if self.model is not None and not self.model.strip():
            raise ValueError("model must be non-empty when provided")


def parse_statistics_timestamp(value: str, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone offset")
    return parsed.astimezone(timezone.utc)
