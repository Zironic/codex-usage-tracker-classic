"""CLI runners for local configuration and pricing commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codex_usage_tracker.cli.output import print_json
from codex_usage_tracker.core.api_payloads import path_payload
from codex_usage_tracker.core.projects import write_project_template
from codex_usage_tracker.pricing.allowance import (
    CODEX_RATE_CARD_URL,
    update_rate_card,
    write_allowance_from_text,
    write_allowance_template,
)
from codex_usage_tracker.pricing.api import (
    pin_pricing_snapshot,
    update_pricing_from_openai_docs,
    write_pricing_template,
)
from codex_usage_tracker.reports.recommendations import write_threshold_template


def run_init_pricing(args: argparse.Namespace) -> int:
    """Write a local pricing template."""
    output = write_pricing_template(args.output, force=args.force)
    return _template_result(
        args,
        output=output,
        schema="codex-usage-tracker-init-pricing-v1",
        path_key="pricing_path",
        message=f"Wrote local pricing template to {output}",
    )


def run_update_pricing(args: argparse.Namespace) -> int:
    """Refresh the local pricing config from OpenAI docs."""
    output = args.output or args.pricing
    result = update_pricing_from_openai_docs(
        output,
        tier=args.tier,
        source_url=args.source_url,
        include_estimates=not args.no_estimates,
    )
    if args.as_json:
        print_json(
            {
                "schema": "codex-usage-tracker-update-pricing-v1",
                "pricing_path": path_payload(result.path),
                "source_url": result.source_url,
                "tier": result.tier,
                "fetched_at": result.fetched_at,
                "model_count": result.model_count,
                "estimated_model_count": result.estimated_model_count,
                "backup_path": path_payload(result.backup_path) if result.backup_path else None,
            }
        )
        return 0
    estimate_suffix = (
        f", including {result.estimated_model_count} estimated internal model"
        f"{'' if result.estimated_model_count == 1 else 's'}"
        if result.estimated_model_count
        else ""
    )
    print(
        f"Wrote {result.model_count} {result.tier} pricing entries from "
        f"{result.source_url} to {result.path}{estimate_suffix}"
        + (f" (backup: {result.backup_path})" if result.backup_path else "")
    )
    return 0


def run_pin_pricing(args: argparse.Namespace) -> int:
    """Pin the active pricing config to a reproducible snapshot."""
    output = pin_pricing_snapshot(
        source_path=args.pricing,
        output_path=args.output,
        force=args.force,
    )
    if args.as_json:
        print_json(
            {
                "schema": "codex-usage-tracker-pin-pricing-v1",
                "pricing_path": path_payload(output),
                "source_pricing_path": path_payload(args.pricing),
            }
        )
        return 0
    print(f"Pinned pricing snapshot to {output}")
    print("Use this file with --pricing for reproducible historical reports.")
    return 0


def run_init_allowance(args: argparse.Namespace) -> int:
    """Write a local allowance template."""
    output = write_allowance_template(args.output or args.allowance, force=args.force)
    return _template_result(
        args,
        output=output,
        schema="codex-usage-tracker-init-allowance-v1",
        path_key="allowance_path",
        message=f"Wrote local allowance template to {output}",
    )


def run_parse_allowance(args: argparse.Namespace) -> int:
    """Parse pasted allowance text into the local allowance file."""
    text = " ".join(args.text).strip()
    if not text:
        if sys.stdin.isatty():
            raise ValueError("provide pasted usage text or pipe it on stdin")
        text = sys.stdin.read().strip()
    output = write_allowance_from_text(
        text,
        path=args.output or args.allowance,
        force=args.force,
    )
    if args.as_json:
        print_json(
            {
                "schema": "codex-usage-tracker-parse-allowance-v1",
                "allowance_path": path_payload(output),
                "updated": True,
            }
        )
        return 0
    print(f"Updated allowance windows from pasted usage text at {output}")
    return 0


def run_update_rate_card(args: argparse.Namespace) -> int:
    """Refresh the local Codex credit rate card."""
    source_file = args.source_file
    output = args.output or args.rate_card
    fallback_reason: str | None = None
    try:
        result = update_rate_card(
            output,
            source_file=source_file,
            source_url=None if source_file is not None else CODEX_RATE_CARD_URL,
        )
    except RuntimeError as exc:
        if source_file is not None:
            raise
        fallback_reason = str(exc)
        result = update_rate_card(output)

    if args.as_json:
        print_json(
            {
                "schema": "codex-usage-tracker-update-rate-card-v1",
                "rate_card_path": path_payload(result.path),
                "source_url": result.source_url,
                "fetched_at": result.fetched_at,
                "model_count": result.model_count,
                "unpriced_model_count": result.unpriced_model_count,
                "alias_count": result.alias_count,
                "live_fetch": result.live_fetch,
                "revision_changed": result.revision_changed,
                "effective_at": result.effective_at,
                "effective_at_precision": result.effective_at_precision,
                "fallback_reason": fallback_reason,
                "backup_path": path_payload(result.backup_path) if result.backup_path else None,
            }
        )
        return 0

    if fallback_reason is not None:
        print(
            "Warning: live OpenAI rate-card fetch failed; wrote the bundled snapshot instead. "
            f"Reason: {fallback_reason}",
            file=sys.stderr,
        )
    if result.live_fetch:
        source_label = "live OpenAI page"
    elif source_file is not None:
        source_label = "supplied snapshot"
    else:
        source_label = "bundled fallback snapshot"
    print(
        f"Wrote {result.model_count} Codex credit rates, "
        f"{result.unpriced_model_count} explicitly unpriced models, and "
        f"{result.alias_count} aliases to {result.path} from {source_label}"
        + (f" ({result.source_url})" if result.source_url else "")
        + (f" (backup: {result.backup_path})" if result.backup_path else "")
    )
    if result.revision_changed:
        print(
            "Recorded changed rates from "
            f"{result.effective_at} (precision={result.effective_at_precision})."
        )
    else:
        print("Published numeric rates match the active local snapshot; no revision was added.")
    return 0


def run_init_thresholds(args: argparse.Namespace) -> int:
    """Write a local recommendation threshold template."""
    output = write_threshold_template(args.output or args.thresholds, force=args.force)
    return _template_result(
        args,
        output=output,
        schema="codex-usage-tracker-init-thresholds-v1",
        path_key="thresholds_path",
        message=f"Wrote recommendation threshold template to {output}",
    )


def run_init_projects(args: argparse.Namespace) -> int:
    """Write a local project attribution template."""
    output = write_project_template(args.output or args.projects, force=args.force)
    return _template_result(
        args,
        output=output,
        schema="codex-usage-tracker-init-projects-v1",
        path_key="projects_path",
        message=f"Wrote project attribution template to {output}",
    )


def _template_result(
    args: argparse.Namespace,
    *,
    output: Path,
    schema: str,
    path_key: str,
    message: str,
) -> int:
    if args.as_json:
        print_json({"schema": schema, path_key: path_payload(output), "created": True})
        return 0
    print(message)
    return 0
