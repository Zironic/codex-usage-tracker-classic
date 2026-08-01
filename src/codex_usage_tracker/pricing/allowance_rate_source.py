"""Live OpenAI Codex rate-card fetching and table parsing."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from codex_usage_tracker import __version__

OPENAI_CODEX_RATE_CARD_URL = "https://help.openai.com/en/articles/20001106-codex-rate-card"


class CodexRateCardParseError(ValueError):
    """Raised when the published Codex rate-card table cannot be parsed safely."""


@dataclass(frozen=True)
class PublishedCodexRateCard:
    """Numeric and explicitly unpriced rows parsed from the published table."""

    credit_rates: dict[str, dict[str, float]]
    display_names: dict[str, str]
    unpriced_models: dict[str, dict[str, str]]
    source_modified_at: str | None


def fetch_openai_codex_rate_card_html(
    source_url: str = OPENAI_CODEX_RATE_CARD_URL,
    *,
    fetched_at: datetime | None = None,
) -> str:
    """Fetch the live rate-card page outside browser caches.

    The request uses a unique query value plus explicit no-cache headers. This
    avoids relying on a browser, CDN response already stored by a browser, or a
    stale search-index representation of the article.
    """

    if urlsplit(source_url).scheme != "https":
        raise ValueError("Codex rate-card sources must use HTTPS")
    now = fetched_at or datetime.now(timezone.utc)
    request_url = _cache_busted_url(source_url, now)
    request = Request(
        request_url,
        headers={
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
            "User-Agent": f"codex-usage-tracker/{__version__}",
        },
    )
    try:
        # The source scheme is restricted to HTTPS above.
        with urlopen(request, timeout=20) as response:  # nosec B310
            content_type = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(content_type)
    except URLError as exc:
        raise RuntimeError(f"could not fetch Codex rate card {source_url}: {exc}") from exc


def parse_openai_codex_rate_card_html(html: str) -> PublishedCodexRateCard:
    """Parse the token-based Codex credit table from one Help Center page."""

    parser = _RateCardHTMLParser()
    parser.feed(html)
    parser.close()
    table = _select_rate_table(parser.tables)
    credit_rates: dict[str, dict[str, float]] = {}
    display_names: dict[str, str] = {}
    unpriced: dict[str, dict[str, str]] = {}
    for row in table[1:]:
        if len(row) < 4:
            continue
        display_name = _clean_cell(row[0])
        model = _model_id(display_name)
        if not model:
            continue
        values = [_credit_value(cell) for cell in row[1:4]]
        if all(value is None for value in values) and all(
            "research preview" in _clean_cell(cell).lower() for cell in row[1:4]
        ):
            unpriced[model] = {
                "display_name": display_name,
                "status": "research_preview",
                "note": "OpenAI publishes this model as research preview without final credit rates.",
            }
            continue
        if any(value is None for value in values):
            raise CodexRateCardParseError(
                f"Codex rate-card row has incomplete numeric values: {display_name}"
            )
        input_rate, cached_rate, output_rate = values
        assert input_rate is not None and cached_rate is not None and output_rate is not None
        credit_rates[model] = {
            "input_per_million": input_rate,
            "cached_input_per_million": cached_rate,
            "output_per_million": output_rate,
        }
        display_names[model] = display_name
    if not credit_rates:
        raise CodexRateCardParseError(
            "Codex rate-card source schema changed: no numeric token-pricing rows were parsed"
        )
    required = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5"}
    missing = sorted(required - credit_rates.keys())
    if missing:
        raise CodexRateCardParseError(
            "Codex rate-card source schema changed: missing required models " + ", ".join(missing)
        )
    return PublishedCodexRateCard(
        credit_rates=credit_rates,
        display_names=display_names,
        unpriced_models=unpriced,
        source_modified_at=_source_modified_at(parser.structured_data, parser.meta),
    )


def _cache_busted_url(source_url: str, now: datetime) -> str:
    parts = urlsplit(source_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("codex_usage_tracker_ts", str(int(now.timestamp()))))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _select_rate_table(tables: list[list[list[str]]]) -> list[list[str]]:
    wanted = {"model", "input tokens", "cached input tokens", "output tokens"}
    for table in tables:
        if not table:
            continue
        header = {_clean_cell(cell).lower() for cell in table[0]}
        if wanted.issubset(header):
            return table
    raise CodexRateCardParseError(
        "Codex rate-card source schema changed: token-pricing table was not found"
    )


def _credit_value(value: str) -> float | None:
    normalized = _clean_cell(value).lower()
    if "research preview" in normalized:
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", normalized)
    if match is None:
        return None
    return float(match.group(0).replace(",", ""))


def _model_id(display_name: str) -> str | None:
    normalized = display_name.strip().lower().replace("_", "-")
    if not normalized:
        return None
    normalized = re.sub(r"\s*\(([^)]+)\)\s*$", r"-\1", normalized)
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    return normalized.strip("-")


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _source_modified_at(
    structured_data: list[object],
    meta: dict[str, str],
) -> str | None:
    for payload in structured_data:
        value = _find_json_key(payload, "dateModified")
        normalized = _normalize_iso_timestamp(value)
        if normalized is not None:
            return normalized
    for key in ("article:modified_time", "last-modified", "dateModified"):
        normalized = _normalize_iso_timestamp(meta.get(key))
        if normalized is not None:
            return normalized
    return None


def _find_json_key(value: object, key: str) -> object:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for nested in value.values():
            found = _find_json_key(nested, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_json_key(nested, key)
            if found is not None:
                return found
    return None


def _normalize_iso_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


class _RateCardHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.structured_data: list[object] = []
        self.meta: dict[str, str] = {}
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._json_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
        elif tag == "script" and attributes.get("type", "").lower() == "application/ld+json":
            self._json_parts = []
        elif tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            content = attributes.get("content")
            if key and content:
                self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell_parts is not None and self._row is not None:
            self._row.append("".join(self._cell_parts))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None
        elif tag == "script" and self._json_parts is not None:
            text = "".join(self._json_parts).strip()
            if text:
                with suppress(json.JSONDecodeError):
                    self.structured_data.append(json.loads(text))
            self._json_parts = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        if self._json_parts is not None:
            self._json_parts.append(data)
