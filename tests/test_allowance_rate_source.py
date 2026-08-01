from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from codex_usage_tracker.pricing import allowance_rate_source
from codex_usage_tracker.pricing.allowance_rate_card import update_rate_card

_RATE_TABLE_HTML = """
<html>
<head>
<script type="application/ld+json">
{"@type":"TechArticle","dateModified":"2026-08-01T00:00:00Z"}
</script>
</head>
<body>
<table>
<tr><th>Model</th><th>Input tokens</th><th>Cached input tokens</th><th>Output tokens</th></tr>
<tr><td>GPT-5.6 Sol</td><td>125 credits</td><td>12.50 credits</td><td>750 credits</td></tr>
<tr><td>GPT-5.6 Terra</td><td>50 credits</td><td>5 credits</td><td>300 credits</td></tr>
<tr><td>GPT-5.6 Luna</td><td>5 credits</td><td>0.5 credits</td><td>30 credits</td></tr>
<tr><td>GPT-5.5</td><td>125 credits</td><td>12.50 credits</td><td>750 credits</td></tr>
<tr><td>GPT-5.5 Cyber</td><td>312.5 credits</td><td>31.25 credits</td><td>1,875 credits</td></tr>
<tr><td>GPT-5.4</td><td>62.50 credits</td><td>6.250 credits</td><td>375 credits</td></tr>
<tr><td>GPT-5.4-Mini</td><td>18.75 credits</td><td>1.875 credits</td><td>113 credits</td></tr>
<tr><td>GPT-5.3-Codex</td><td>43.75 credits</td><td>4.375 credits</td><td>350 credits</td></tr>
<tr><td>GPT-5.2</td><td>43.75 credits</td><td>4.375 credits</td><td>350 credits</td></tr>
<tr><td>GPT-5.3-Codex-Spark</td><td>research preview</td><td>research preview</td><td>research preview</td></tr>
<tr><td>GPT-Image-2.0 (image)</td><td>200 credits</td><td>50 credits</td><td>750 credits</td></tr>
<tr><td>GPT-Image-2.0 (text)</td><td>125 credits</td><td>31.25 credits</td><td>250 credits</td></tr>
</table>
</body>
</html>
"""


def test_parse_live_rate_table_including_image_and_preview_rows() -> None:
    parsed = allowance_rate_source.parse_openai_codex_rate_card_html(_RATE_TABLE_HTML)

    assert parsed.credit_rates["gpt-5.6-sol"] == _rates(125, 12.5, 750)
    assert parsed.credit_rates["gpt-5.6-terra"] == _rates(50, 5, 300)
    assert parsed.credit_rates["gpt-5.6-luna"] == _rates(5, 0.5, 30)
    assert parsed.credit_rates["gpt-5.5-cyber"] == _rates(312.5, 31.25, 1875)
    assert parsed.credit_rates["gpt-image-2.0-image"] == _rates(200, 50, 750)
    assert parsed.credit_rates["gpt-image-2.0-text"] == _rates(125, 31.25, 250)
    assert parsed.unpriced_models["gpt-5.3-codex-spark"]["status"] == "research_preview"
    assert parsed.source_modified_at == "2026-08-01T00:00:00Z"


def test_live_fetch_uses_cache_buster_and_no_cache_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class Headers:
        @staticmethod
        def get_content_charset() -> str:
            return "utf-8"

    class Response:
        headers = Headers()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read() -> bytes:
            return _RATE_TABLE_HTML.encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["cache_control"] = request.get_header("Cache-control")
        captured["pragma"] = request.get_header("Pragma")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(allowance_rate_source, "urlopen", fake_urlopen)
    fetched = allowance_rate_source.fetch_openai_codex_rate_card_html(
        allowance_rate_source.OPENAI_CODEX_RATE_CARD_URL,
        fetched_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    assert fetched == _RATE_TABLE_HTML
    assert "codex_usage_tracker_ts=1785542400" in captured["url"]
    assert captured["cache_control"] == "no-cache, no-store, max-age=0"
    assert captured["pragma"] == "no-cache"
    assert captured["timeout"] == 20


def test_live_update_preserves_old_rates_as_timestamped_history(tmp_path: Path) -> None:
    path = tmp_path / "rate-card.json"
    path.write_text(
        json.dumps(
            {
                "schema": "codex-usage-tracker-codex-rate-card-v1",
                "version": "2026-07-09",
                "source": {
                    "name": "Old bundled card",
                    "url": "https://example.test/old-card",
                    "fetched_at": "2026-07-09",
                    "tier": "standard",
                },
                "credit_rates": {
                    "gpt-5.6-sol": _rates(250, 25, 1500),
                    "gpt-5.6-terra": _rates(125, 12.5, 125),
                    "gpt-5.6-luna": _rates(50, 5, 300),
                    "gpt-5.5": _rates(125, 12.5, 750),
                },
                "aliases": {"gpt-5.6": {"model": "gpt-5.6-sol"}},
                "fast_multipliers": {},
            }
        ),
        encoding="utf-8",
    )

    result = update_rate_card(
        path,
        source_url=allowance_rate_source.OPENAI_CODEX_RATE_CARD_URL,
        fetch_text=lambda _url: _RATE_TABLE_HTML,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert result.live_fetch is True
    assert result.revision_changed is True
    assert result.effective_at == "2026-08-01T00:00:00Z"
    assert result.effective_at_precision == "second"
    assert result.model_count == 11
    assert result.unpriced_model_count == 1
    assert payload["credit_rates"]["gpt-5.6-luna"]["input_per_million"] == 5
    assert payload["credit_rates"]["gpt-image-2.0-image"]["input_per_million"] == 200
    assert payload["unpriced_models"]["gpt-5.3-codex-spark"]["status"] == "research_preview"
    assert len(payload["rate_revisions"]) == 2
    assert payload["rate_revisions"][0]["effective_at"] is None
    assert payload["rate_revisions"][0]["credit_rates"]["gpt-5.6-luna"][
        "input_per_million"
    ] == 50
    assert payload["rate_revisions"][1]["effective_at"] == "2026-08-01T00:00:00Z"

    second = update_rate_card(
        path,
        source_url=allowance_rate_source.OPENAI_CODEX_RATE_CARD_URL,
        fetch_text=lambda _url: _RATE_TABLE_HTML,
    )
    second_payload = json.loads(path.read_text(encoding="utf-8"))
    assert second.revision_changed is False
    assert len(second_payload["rate_revisions"]) == 2


def _rates(input_rate: float, cached_rate: float, output_rate: float) -> dict[str, float]:
    return {
        "input_per_million": input_rate,
        "cached_input_per_million": cached_rate,
        "output_per_million": output_rate,
    }
