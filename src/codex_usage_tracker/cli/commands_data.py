"""Allowance, export, and support-bundle CLI command handlers."""

from __future__ import annotations

import argparse
import json

from codex_usage_tracker.allowance_intelligence import (
    build_allowance_diagnostics_report,
    build_allowance_export_report,
    build_allowance_history_report,
)
from codex_usage_tracker.cli.output import print_json
from codex_usage_tracker.core.api_payloads import path_payload
from codex_usage_tracker.diagnostics.dedupe import (
    build_dedupe_diagnostics,
    render_dedupe_diagnostics,
)
from codex_usage_tracker.reports.support import (
    build_support_bundle,
    support_bundle_issue_guidance,
)
from codex_usage_tracker.store.api import export_usage_csv


def _run_allowance_history(args: argparse.Namespace) -> int:
    report = build_allowance_history_report(
        db_path=args.db,
        allowance_path=args.allowance,
        rate_card_path=args.rate_card,
        include_archived=args.include_archived,
        window_kind=args.window_kind,
        limit=_allowance_report_limit(args.limit),
        privacy_mode=args.privacy_mode,
    )
    if args.as_json:
        print_json(report.payload)
        return 0
    print(report.render())
    return 0


def _run_allowance_diagnostics(args: argparse.Namespace) -> int:
    report = build_allowance_diagnostics_report(
        db_path=args.db,
        allowance_path=args.allowance,
        rate_card_path=args.rate_card,
        include_archived=args.include_archived,
        window_kind=args.window_kind,
        limit=_allowance_report_limit(args.limit),
        privacy_mode=args.privacy_mode,
    )
    if args.as_json:
        print_json(report.payload)
        return 0
    print(report.render())
    return 0


def _run_allowance_export(args: argparse.Namespace) -> int:
    report = build_allowance_export_report(
        db_path=args.db,
        allowance_path=args.allowance,
        rate_card_path=args.rate_card,
        include_archived=args.include_archived,
        window_kind=args.window_kind,
        limit=_allowance_report_limit(args.limit),
        export_format=args.export_format,
        from_plan=args.from_plan,
        to_plan=args.to_plan,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.export_format.startswith("compact"):
            encoded = json.dumps(
                report.payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        else:
            encoded = json.dumps(
                report.payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        args.output.write_text(encoded + "\n", encoding="utf-8")
    if args.as_json:
        print_json(report.payload)
        return 0
    if args.output is not None:
        coverage = report.payload.get("coverage")
        if isinstance(coverage, dict):
            print(
                "Wrote allowance evidence export to "
                f"{args.output} ({coverage.get('exported_observation_count', 0)} "
                f"observations, {coverage.get('start_date')} to "
                f"{coverage.get('end_date')}, "
                f"truncated={coverage.get('truncated')})"
            )
            _print_plan_comparison(report.payload.get("plan_comparison"))
        else:
            print(f"Wrote allowance evidence export to {args.output}")
        return 0
    print(report.render())
    return 0


def _print_plan_comparison(value: object) -> None:
    if not isinstance(value, dict):
        return
    transition = value.get("transition")
    relative = value.get("relative_meter_size")
    if not isinstance(transition, dict) or not isinstance(relative, dict):
        return
    before_plan = transition.get("from_plan")
    after_plan = transition.get("to_plan")
    ratio_percent = relative.get("after_as_percent_of_before")
    if before_plan and after_plan:
        print(f"Plan comparison: {before_plan} -> {after_plan}")
    if isinstance(ratio_percent, int | float):
        print(f"Post-switch meter estimate: {float(ratio_percent):.1f}% of pre-switch")
    print(f"Evidence: {value.get('status', 'unknown')}")


def _allowance_report_limit(limit: int | None) -> int | None:
    if limit is None or limit <= 0:
        return None
    return limit


def _run_dedupe_diagnostics(args: argparse.Namespace) -> int:
    payload = build_dedupe_diagnostics(db_path=args.db, limit=args.limit)
    if args.as_json:
        print_json(payload)
        return 0
    print(render_dedupe_diagnostics(payload))
    return 0


def _run_export(args: argparse.Namespace) -> int:
    count = export_usage_csv(
        output_path=args.output,
        db_path=args.db,
        limit=args.limit,
        privacy_mode=args.privacy_mode,
    )
    if args.as_json:
        print_json(
            {
                "schema": "codex-usage-tracker-export-v1",
                "rows": count,
                "csv_path": path_payload(args.output),
                "limit": args.limit,
                "privacy_mode": args.privacy_mode,
            }
        )
        return 0
    print(f"Wrote {count} aggregate usage rows to {args.output}")
    return 0


def _run_support_bundle(args: argparse.Namespace) -> int:
    output = build_support_bundle(
        output_path=args.output,
        codex_home=args.codex_home,
        db_path=args.db,
        pricing_path=args.pricing,
        allowance_path=args.allowance,
        rate_card_path=args.rate_card,
        thresholds_path=args.thresholds,
        projects_path=args.projects,
        privacy_mode=args.privacy_mode,
    )
    issue_guidance = support_bundle_issue_guidance(args.privacy_mode)
    if args.as_json:
        print_json(
            {
                "schema": "codex-usage-tracker-support-bundle-v1",
                "support_bundle_path": path_payload(output),
                "privacy": {
                    "contains_raw_logs": False,
                    "contains_prompts": False,
                    "contains_assistant_messages": False,
                    "contains_tool_output": False,
                    "project_metadata_mode": args.privacy_mode,
                },
                "issue_report": issue_guidance,
            }
        )
        return 0
    print(f"Wrote privacy-preserving support bundle to {output}")
    print("Bundle excludes raw logs, prompts, assistant messages, tool output, and context text.")
    print(
        "GitHub issue fields safe to paste after review: "
        + ", ".join(issue_guidance["cli_hint_fields"])
    )
    print("Full strict-bundle field list lives in issue_report.safe_fields.")
    if not issue_guidance["safe_to_paste_after_review"]:
        print("Use --privacy-mode strict before sharing support bundles publicly.")
    return 0
