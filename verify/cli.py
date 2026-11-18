"""Command line entry point: `python -m verify [command]`."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import core, duplicates, live, rebuild, snapshot

ROOT = Path(__file__).resolve().parents[1]

COMMANDS = ("all", "snapshot", "rebuild", "duplicates", "links", "live")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m verify",
        description="Audit price, date, ticket link and duplicate integrity of the snapshot.",
    )
    parser.add_argument("command", nargs="?", default="all", choices=COMMANDS)
    parser.add_argument("--data-dir", help="directory holding events_*.json (default: <root>/data)")
    parser.add_argument("--root", help="repository root (default: this package's parent)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="machine-readable report")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--source", help="source name for the live command")
    parser.add_argument("--limit", type=int, help="max URLs for the links command")
    parser.add_argument("--timeout", type=float, default=10.0, help="per-request timeout in seconds")
    return parser


def _load_snapshot(data_dir: Path):
    normalized = core.load_json(data_dir / "events_normalized.json")
    deduped = core.load_json(data_dir / "events_deduped.json")
    if not isinstance(normalized, list):
        raise core.VerifyInputError(f"{data_dir / 'events_normalized.json'} is not a JSON list")
    if not isinstance(deduped, dict):
        raise core.VerifyInputError(f"{data_dir / 'events_deduped.json'} is not a JSON object")
    last_run_path = data_dir / "last_run.json"
    last_run = core.load_json(last_run_path) if last_run_path.exists() else None
    return normalized, deduped, last_run


def main(argv=None, root=None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already printed usage
        return int(exc.code or 2)

    base = Path(root or args.root or ROOT)
    data_dir = Path(args.data_dir) if args.data_dir else base / "data"
    report = core.Report(
        meta={"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    )

    try:
        normalized, deduped, last_run = _load_snapshot(data_dir)
        clusters = len(deduped.get("clusters") or [])

        if args.command in ("snapshot", "all", "duplicates", "rebuild"):
            report.meta["scope"] = f"snapshot: {len(normalized)} events, {clusters} clusters"

        if args.command in ("snapshot", "all"):
            report.extend(snapshot.run_snapshot(normalized, deduped, last_run))

        if args.command in ("rebuild", "all"):
            findings, meta = rebuild.check_rebuild(data_dir, normalized)
            report.extend(findings)
            report.meta["scope"] += f" · rebuild: {meta.get('sources', 0)} raw source(s)"

        if args.command in ("duplicates", "all"):
            report.extend(duplicates.find_candidates(normalized, deduped))

        if args.command == "links":
            report.meta["scope"] = f"links: {len(normalized)} events, {args.limit or 'all'} URL cap"
            report.extend(
                live.check_links(normalized, timeout=args.timeout, limit=args.limit)
            )

        if args.command == "live":
            if not args.source:
                print("verify: --source is required for the live command", file=sys.stderr)
                return 2
            report.meta["scope"] = f"live: {args.source}"
            report.extend(live.live_source(args.source, normalized))
    except core.VerifyInputError as exc:
        print(f"verify: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.render())
    return report.exit_code(strict=args.strict)
