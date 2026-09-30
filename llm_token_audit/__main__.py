from __future__ import annotations

import argparse
import csv
import hashlib
import json
import signal
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Iterator

from . import __version__, claude_code, codex
from .record import FIELDS, TOKEN_FIELDS, UsageRecord

ADAPTERS = {"claude-code": claude_code, "codex": codex}


def _records(args: argparse.Namespace, stats: dict[str, Counter]) -> Iterator[UsageRecord]:
    dirs = {"claude-code": args.claude_dir, "codex": args.codex_dir}
    for name, adapter in ADAPTERS.items():
        if args.source not in ("all", name):
            continue
        stats[name] = Counter()
        yield from adapter.read(dirs[name] or adapter.default_dirs(), stats[name])


def _redact(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else value


def normalize(args: argparse.Namespace) -> None:
    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    stats: dict[str, Counter] = {}
    writer = csv.DictWriter(out, fieldnames=FIELDS) if args.format == "csv" else None
    if writer:
        writer.writeheader()
    for record in _records(args, stats):
        row = asdict(record)
        if args.redact:
            for key in ("session_id", "request_id", "project"):
                row[key] = _redact(row[key])
        if writer:
            writer.writerow(row)
        else:
            out.write(json.dumps(row) + "\n")
    if out is not sys.stdout:
        out.close()


def check(args: argparse.Namespace) -> None:
    stats: dict[str, Counter] = {}
    totals: dict[str, Counter] = {}
    unreported: dict[str, Counter] = {}
    records: Counter = Counter()
    for record in _records(args, stats):
        records[record.source] += 1
        totals.setdefault(record.source, Counter())
        unreported.setdefault(record.source, Counter())
        for field in TOKEN_FIELDS:
            value = getattr(record, field)
            if value is None:
                unreported[record.source][field] += 1
            else:
                totals[record.source][field] += value

    for source, counter in stats.items():
        print(f"\n{source}")
        for key, value in sorted(counter.items()):
            print(f"  {key:32} {value:>14,}")
        print(f"  {'records':32} {records[source]:>14,}")
        if source not in totals:
            continue
        print("  tokens (records with the field unreported in brackets)")
        for field in TOKEN_FIELDS:
            missing = unreported[source][field]
            note = f"  [{missing:,} unreported]" if missing else ""
            print(f"    {field:30} {totals[source][field]:>14,}{note}")


def main() -> None:
    if hasattr(signal, "SIGPIPE"):
        # Exit quietly when output is piped into a command that stops reading, such as `head`.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    parser = argparse.ArgumentParser(prog="llm-token-audit", description="Normalize AI agent session logs into per-attempt token records.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    for name, handler, summary in (
        ("normalize", normalize, "write one row per model attempt"),
        ("check", check, "print parse statistics, reconciliation, and token totals"),
    ):
        command = commands.add_parser(name, help=summary)
        command.set_defaults(handler=handler)
        command.add_argument("--source", choices=["all", *ADAPTERS], default="all")
        command.add_argument("--claude-dir", type=Path, action="append", help="Claude Code projects directory (repeatable)")
        command.add_argument("--codex-dir", type=Path, action="append", help="Codex sessions directory (repeatable)")
        if name == "normalize":
            command.add_argument("--format", choices=["csv", "jsonl"], default="csv")
            command.add_argument("--redact", action="store_true", help="hash session IDs, request IDs, and project names")
            command.add_argument("-o", "--output", help="write to a file instead of stdout")

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
