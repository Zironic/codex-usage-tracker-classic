"""Codex credit rate-card loading, live updates, and parsing helpers."""

from __future__ import annotations

import json
import math
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from codex_usage_tracker.core.paths import DEFAULT_RATE_CARD_PATH
from codex_usage_tracker.pricing.allowance_rate_source import (
    OPENAI_CODEX_RATE_CARD_URL,
    PublishedCodexRateCard,
    fetch_openai_codex_rate_card_html,
    parse_openai_codex_rate_card_html,
)

RATE_CARD_SCHEMA = "codex-usage-tracker-codex-rate-card-v1"

CODEX_PRICING_URL = OPENAI_CODEX_RATE_CARD_URL
CODEX_RATE_CARD_URL = OPENAI_CODEX_RATE_CARD_URL

DEFAULT_SOURCE = {
    "name": "OpenAI Codex rate card",
    "url": CODEX_RATE_CARD_URL,
    "pricing_url": CODEX_PRICING_URL,
    "fetched_at": "2026-08-01T06:43:00Z",
    "basis": "credits per 1M input, cached input, and output tokens",
    "tier": "standard",
}


@dataclass(frozen=True)
class RateCardUpdateResult:
    """Result from writing a local Codex credit rate-card snapshot."""

    path: Path
    source_url: str | None
    fetched_at: str | None
    model_count: int
    alias_count: int
    backup_path: Path | None = None
    unpriced_model_count: int = 0
    revision_changed: bool = False
    effective_at: str | None = None
    effective_at_precision: str | None = None
    live_fetch: bool = False


@dataclass(frozen=True)
class FastMultiplierRate:
    """One source-stamped ChatGPT Fast credit multiplier."""

    multiplier: float
    source_name: str
    source_url: str | None
    fetched_at: str | None
    confidence: str


def load_bundled_rate_card() -> dict[str, Any]:
    """Load the package-bundled Codex credit rate-card snapshot."""

    rate_card = (
        resources.files("codex_usage_tracker.plugin_data")
        .joinpath("rate_cards")
        .joinpath("codex-credit-rates.json")
    )
    with rate_card.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("bundled Codex rate card must be a JSON object")
    return raw


def update_rate_card(
    path: Path = DEFAULT_RATE_CARD_PATH,
    *,
    source_file: Path | None = None,
    source_url: str | None = None,
    effective_at: str | None = None,
    fetch_text: Callable[[str], str] | None = None,
) -> RateCardUpdateResult:
    """Write a validated local Codex credit rate-card snapshot.

    ``source_file`` imports a supplied JSON snapshot. Supplying ``source_url``
    performs a cache-busted live fetch, parses the published token-rate table,
    preserves prior revisions, and appends or replaces the effective revision
    when the numeric rates changed. With neither option the historical bundled
    snapshot is copied, preserving the pre-existing Python API behavior.
    """

    path = path.expanduser()
    live_fetch = source_file is None and source_url is not None
    revision_changed = False
    resolved_effective_at: str | None = None
    effective_precision: str | None = None
    if source_file is not None:
        raw = load_json_file(source_file)
    elif live_fetch:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fetched_at = _iso_z(now)
        fetcher = fetch_text or (
            lambda url: fetch_openai_codex_rate_card_html(url, fetched_at=now)
        )
        html = fetcher(source_url or CODEX_RATE_CARD_URL)
        published = parse_openai_codex_rate_card_html(html)
        base = _rate_card_update_base(path)
        (
            raw,
            revision_changed,
            resolved_effective_at,
            effective_precision,
        ) = _live_rate_card_payload(
            base,
            published,
            source_url=source_url or CODEX_RATE_CARD_URL,
            fetched_at=fetched_at,
            explicit_effective_at=effective_at,
        )
    else:
        raw = load_bundled_rate_card()

    source, credit_rates, aliases, fast_multipliers = _validate_rate_card(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = _backup_existing_rate_card(path)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    unpriced = raw.get("unpriced_models")
    return RateCardUpdateResult(
        path=path,
        source_url=optional_str(source.get("url")),
        fetched_at=optional_str(source.get("fetched_at")),
        model_count=len(credit_rates),
        alias_count=len(aliases),
        backup_path=backup_path,
        unpriced_model_count=len(unpriced) if isinstance(unpriced, dict) else 0,
        revision_changed=revision_changed,
        effective_at=resolved_effective_at,
        effective_at_precision=effective_precision,
        live_fetch=live_fetch,
    )


def _validate_rate_card(
    raw: dict[str, Any],
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, float]],
    dict[str, dict[str, str]],
    dict[str, FastMultiplierRate],
]:
    schema = raw.get("schema") or raw.get("_schema")
    if schema and schema != RATE_CARD_SCHEMA:
        raise ValueError(f"unsupported Codex rate-card schema: {schema}")
    source = parse_rate_card_source(raw)
    credit_rates = parse_credit_rates(raw.get("credit_rates", {}))
    aliases = parse_aliases(raw.get("aliases", {}))
    fast_multipliers = parse_fast_multipliers(
        raw.get("fast_multipliers", {}), source=source
    )
    if not credit_rates:
        raise ValueError("rate card must contain at least one credit rate")
    parse_credit_rate_metadata(raw.get("credit_rates", {}), source=source)
    parse_alias_metadata(raw.get("aliases", {}), source=source)
    if isinstance(raw.get("fast_multipliers"), dict) and len(fast_multipliers) != len(
        raw["fast_multipliers"]
    ):
        raise ValueError("rate card contains an invalid Fast multiplier")
    _validate_raw_revisions(raw.get("rate_revisions"))
    return source, credit_rates, aliases, fast_multipliers


def _rate_card_update_base(path: Path) -> dict[str, Any]:
    if path.exists():
        return load_json_file(path)
    return load_bundled_rate_card()


def _live_rate_card_payload(
    base: dict[str, Any],
    published: PublishedCodexRateCard,
    *,
    source_url: str,
    fetched_at: str,
    explicit_effective_at: str | None,
) -> tuple[dict[str, Any], bool, str | None, str | None]:
    source_modified_at = published.source_modified_at
    source = {
        "name": "OpenAI Codex rate card",
        "url": source_url,
        "pricing_url": source_url,
        "fetched_at": fetched_at,
        "source_modified_at": source_modified_at,
        "basis": "credits per 1M input, cached input, and output tokens",
        "tier": "standard",
        "cache_policy": "cache_busted_no_store",
    }
    live_rows = {
        model: {
            **rates,
            "confidence": "exact",
            "source_url": source_url,
            "fetched_at": fetched_at,
            "tier": "standard",
            "display_name": published.display_names.get(model),
        }
        for model, rates in published.credit_rates.items()
    }
    revisions = _json_list(base.get("rate_revisions"))
    previous_rates = parse_credit_rates(base.get("credit_rates", {}))
    rates_changed = previous_rates != published.credit_rates
    resolved_effective_at: str | None = None
    effective_precision: str | None = None
    if rates_changed:
        if not revisions and previous_rates:
            revisions.append(_baseline_revision(base))
        resolved_effective_at, effective_precision = _revision_boundary(
            explicit_effective_at,
            source_modified_at,
            fetched_at,
        )
        revision = {
            "revision_id": _revision_id(resolved_effective_at),
            "effective_at": resolved_effective_at,
            "effective_at_precision": effective_precision,
            "source": {
                **source,
                "note": (
                    "Effective time came from an explicit override."
                    if explicit_effective_at
                    else (
                        "Effective time came from the source article's structured modification timestamp."
                        if source_modified_at
                        else "Exact rollout time was unavailable; this revision is effective from first live observation."
                    )
                ),
            },
            "credit_rates": live_rows,
            "unpriced_models": published.unpriced_models,
        }
        _append_or_replace_revision(revisions, revision)

    payload = _json_object(base)
    payload.update(
        {
            "schema": RATE_CARD_SCHEMA,
            "version": fetched_at[:10],
            "source": source,
            "credit_rates": live_rows,
            "unpriced_models": published.unpriced_models,
            "rate_revisions": revisions,
        }
    )
    payload.setdefault("aliases", {})
    payload.setdefault("fast_multipliers", {})
    return payload, rates_changed, resolved_effective_at, effective_precision


def _baseline_revision(base: dict[str, Any]) -> dict[str, Any]:
    source = parse_rate_card_source(base)
    revision_id = optional_str(base.get("version")) or optional_str(source.get("fetched_at"))
    return {
        "revision_id": revision_id or "pre-live-update-baseline",
        "effective_at": None,
        "effective_at_precision": "unknown",
        "source": {
            **source,
            "note": "Undated baseline preserves the active rates before the first live update.",
        },
        "credit_rates": _json_object(base.get("credit_rates")),
    }


def _revision_boundary(
    explicit: str | None,
    source_modified_at: str | None,
    fetched_at: str,
) -> tuple[str, str]:
    if explicit is not None:
        normalized, precision = _normalize_effective_at(explicit)
        return normalized, precision
    if source_modified_at is not None:
        normalized, precision = _normalize_effective_at(source_modified_at)
        return normalized, precision
    return fetched_at, "observed"


def _normalize_effective_at(value: str) -> tuple[str, str]:
    text = value.strip()
    precision = "day" if len(text) == 10 else "second"
    if precision == "day":
        text = f"{text}T00:00:00Z"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("effective_at must be an ISO date or timezone-aware timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("effective_at must include a timezone")
    return _iso_z(parsed.astimezone(timezone.utc)), precision


def _revision_id(effective_at: str) -> str:
    compact = effective_at.replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    return f"{compact}-openai-rate-card"


def _append_or_replace_revision(
    revisions: list[dict[str, Any]],
    revision: dict[str, Any],
) -> None:
    effective_at = optional_str(revision.get("effective_at"))
    if effective_at is None:
        raise ValueError("live rate revision must have an effective_at timestamp")
    if not revisions:
        revisions.append(revision)
        return
    latest = revisions[-1]
    latest_effective_at = optional_str(latest.get("effective_at"))
    if latest_effective_at is None or latest_effective_at < effective_at:
        revisions.append(revision)
        return
    if latest_effective_at == effective_at:
        revisions[-1] = revision
        return
    raise ValueError(
        "live rate-card effective_at precedes the latest stored revision; "
        "provide a later --effective-at override"
    )


def _validate_raw_revisions(raw: object) -> None:
    if raw is None:
        return
    if not isinstance(raw, list):
        raise ValueError("rate_revisions must be a list")
    last_effective: str | None = None
    for index, revision in enumerate(raw):
        if not isinstance(revision, dict):
            raise ValueError(f"rate_revisions[{index}] must be an object")
        rates = parse_credit_rates(revision.get("credit_rates", {}))
        if not rates:
            raise ValueError(f"rate_revisions[{index}] must contain credit_rates")
        effective_at = optional_str(revision.get("effective_at"))
        if effective_at is None:
            if index != 0:
                raise ValueError("only the first rate revision may be an undated baseline")
            continue
        normalized, _precision = _normalize_effective_at(effective_at)
        if last_effective is not None and normalized <= last_effective:
            raise ValueError("dated rate revisions must be strictly increasing")
        last_effective = normalized


def parse_credit_rates(raw: object) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, dict[str, float]] = {}
    for model, rates in raw.items():
        normalized = normalize_model(model)
        if not normalized or not isinstance(rates, dict):
            continue
        parsed[normalized] = {
            "input_per_million": _required_rate(rates, "input_per_million", normalized),
            "cached_input_per_million": _required_rate(
                rates, "cached_input_per_million", normalized
            ),
            "output_per_million": _required_rate(rates, "output_per_million", normalized),
        }
    return parsed


def parse_fast_multipliers(
    raw: object,
    *,
    source: dict[str, Any],
    default_confidence: str = "exact",
) -> dict[str, FastMultiplierRate]:
    """Parse valid source-stamped Fast multipliers, skipping malformed entries."""

    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, FastMultiplierRate] = {}
    for family, value in raw.items():
        normalized = normalize_model(family)
        if not normalized:
            continue
        entry = value if isinstance(value, dict) else {"multiplier": value}
        multiplier = _fast_multiplier_number(entry.get("multiplier"))
        if multiplier is None:
            continue
        confidence = (
            "user_override"
            if default_confidence == "user_override"
            else optional_str(entry.get("confidence")) or default_confidence
        )
        parsed[normalized] = FastMultiplierRate(
            multiplier=multiplier,
            source_name=optional_str(entry.get("source_name"))
            or optional_str(source.get("name"))
            or "Codex Fast multiplier",
            source_url=optional_str(entry.get("source_url"))
            or optional_str(source.get("url")),
            fetched_at=optional_str(entry.get("fetched_at"))
            or optional_str(source.get("fetched_at")),
            confidence=confidence,
        )
    return parsed


def _fast_multiplier_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        multiplier = number_value(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(multiplier) or multiplier < 1.0:
        return None
    return multiplier


def parse_aliases(raw: object) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, dict[str, str]] = {}
    for source, target in raw.items():
        source_model = normalize_model(source)
        if not source_model:
            continue
        alias = _parse_alias_entry(source_model, target)
        if alias is not None:
            parsed[source_model] = alias
    return parsed


def _parse_alias_entry(source_model: str, target: object) -> dict[str, str] | None:
    if isinstance(target, str):
        return {
            "model": normalize_model(target) or target,
            "confidence": "estimated",
            "note": f"Mapped from {source_model} by local allowance config.",
        }
    if not isinstance(target, dict):
        return None
    target_model = normalize_model(target.get("model"))
    if not target_model:
        return None
    return {
        "model": target_model,
        "confidence": optional_str(target.get("confidence")) or "estimated",
        "note": optional_str(target.get("note"))
        or f"Mapped from {source_model} by local allowance config.",
    }


def parse_rate_card_source(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return dict(DEFAULT_SOURCE)
    source = raw.get("source") or raw.get("_source")
    if not isinstance(source, dict):
        return dict(DEFAULT_SOURCE)
    return {**DEFAULT_SOURCE, **source}


def parse_credit_rate_metadata(
    raw: object,
    *,
    source: dict[str, Any],
    default_confidence: str = "exact",
) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, dict[str, Any]] = {}
    for model, rates in raw.items():
        entry = _credit_rate_metadata_entry(model, rates, source, default_confidence)
        if entry is not None:
            normalized, metadata = entry
            parsed[normalized] = metadata
    return parsed


def _credit_rate_metadata_entry(
    model: object,
    rates: object,
    source: dict[str, Any],
    default_confidence: str,
) -> tuple[str, dict[str, Any]] | None:
    normalized = normalize_model(model)
    if not normalized or not isinstance(rates, dict):
        return None
    return normalized, {
        "confidence": optional_str(rates.get("confidence")) or default_confidence,
        "source_name": optional_str(rates.get("source_name"))
        or optional_str(source.get("name"))
        or "Codex credit rates",
        "source_url": optional_str(rates.get("source_url")) or optional_str(source.get("url")),
        "fetched_at": optional_str(rates.get("fetched_at"))
        or optional_str(source.get("fetched_at")),
        "tier": optional_str(rates.get("tier")) or optional_str(source.get("tier")),
        "note": optional_str(rates.get("note")),
        "display_name": optional_str(rates.get("display_name")),
    }


def parse_alias_metadata(raw: object, *, source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, dict[str, Any]] = {}
    for alias, target in raw.items():
        entry = _alias_metadata_entry(alias, target, source)
        if entry is not None:
            normalized, metadata = entry
            parsed[normalized] = metadata
    return parsed


def _alias_metadata_entry(
    alias: object,
    target: object,
    source: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    normalized = normalize_model(alias)
    if not normalized:
        return None
    if isinstance(target, str):
        return normalized, _string_alias_metadata(target, source)
    if isinstance(target, dict):
        return normalized, _mapping_alias_metadata(target, source)
    return None


def _string_alias_metadata(target: str, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "confidence": "estimated",
        "source_name": optional_str(source.get("name")) or "Codex credit rates",
        "source_url": optional_str(source.get("url")),
        "fetched_at": optional_str(source.get("fetched_at")),
        "tier": optional_str(source.get("tier")),
        "note": f"Mapped to {normalize_model(target) or target} by local alias.",
        "alias_reason": None,
    }


def _mapping_alias_metadata(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    return {
        "confidence": optional_str(target.get("confidence")) or "estimated",
        "source_name": optional_str(target.get("source_name"))
        or optional_str(source.get("name"))
        or "Codex credit rates",
        "source_url": optional_str(target.get("source_url")) or optional_str(source.get("url")),
        "fetched_at": optional_str(target.get("fetched_at"))
        or optional_str(source.get("fetched_at")),
        "tier": optional_str(target.get("tier")) or optional_str(source.get("tier")),
        "note": optional_str(target.get("note")),
        "alias_reason": optional_str(target.get("alias_reason")),
    }


def load_json_file(path: Path) -> dict[str, Any]:
    raw = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"JSON config must be an object: {path}")
    return raw


def _backup_existing_rate_card(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(f"{path.name}.{stamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def normalize_model(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower().replace("_", "-")


def _required_rate(raw: dict[str, Any], key: str, model: str) -> float:
    parsed = optional_positive_number(raw.get(key))
    if parsed is None:
        raise ValueError(f"missing {key} for Codex credit model {model}")
    return parsed


def optional_positive_number(value: object) -> float | None:
    if value is None or value == "":
        return None
    number = number_value(value)
    if number < 0:
        raise ValueError("allowance values cannot be negative")
    return number


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def number_value(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        return float(value)
    return 0.0


def _json_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return json.loads(json.dumps(value))


def _json_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        json.loads(json.dumps(item))
        for item in value
        if isinstance(item, dict)
    ]


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
