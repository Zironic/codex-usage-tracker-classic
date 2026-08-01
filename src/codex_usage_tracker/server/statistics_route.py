"""Focused localhost handler for dashboard usage statistics."""

from __future__ import annotations

import sqlite3
from dataclasses import fields
from http import HTTPStatus
from pathlib import Path
from typing import Any, BinaryIO

from codex_usage_tracker.application.statistics import get_usage_statistics
from codex_usage_tracker.application.statistics_models import StatisticsRequest
from codex_usage_tracker.interfaces.http.serialization import (
    HttpRequestError,
    decode_json_object,
    read_bounded_body,
    serialize_http_payload,
)

MAX_STATISTICS_REQUEST_BYTES = 16 * 1024
MAX_STATISTICS_RESPONSE_BYTES = 256 * 1024


def statistics_response(
    *,
    method: str,
    stream: BinaryIO,
    content_length: str | None,
    content_type: str,
    db_path: Path,
) -> tuple[HTTPStatus, dict[str, object]]:
    """Decode and execute one dashboard statistics request."""

    if method != "POST":
        return HTTPStatus.METHOD_NOT_ALLOWED, _error("method_not_allowed", "Method not allowed")
    try:
        body = read_bounded_body(
            stream,
            content_length=content_length,
            max_bytes=MAX_STATISTICS_REQUEST_BYTES,
        )
        values = decode_json_object(
            body,
            content_type=content_type,
            max_bytes=MAX_STATISTICS_REQUEST_BYTES,
        )
        allowed = {item.name for item in fields(StatisticsRequest)}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(f"unsupported field: {unknown[0]}")
        result = get_usage_statistics(StatisticsRequest(**values), db_path=db_path)  # type: ignore[arg-type]
        payload = serialize_http_payload(result)
    except HttpRequestError as exc:
        return HTTPStatus(exc.status), _error(exc.code, exc.message)
    except (TypeError, ValueError) as exc:
        return HTTPStatus.BAD_REQUEST, _error("invalid_request", str(exc))
    except sqlite3.Error:
        return HTTPStatus.INTERNAL_SERVER_ERROR, _error(
            "database_error", "Database error while calculating usage statistics"
        )
    return HTTPStatus.OK, payload


def _error(code: str, message: str) -> dict[str, object]:
    return {
        "schema": "codex-usage-tracker.error.v1",
        "error": {"code": code, "message": message},
    }
