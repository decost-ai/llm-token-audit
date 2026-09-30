from __future__ import annotations

from collections import Counter, defaultdict
from typing import Callable, Iterable, Optional

from .pricing import PARTS, price
from .record import UsageRecord

PART_LABELS = {
    "input": "uncached input",
    "cache_read": "cache reads",
    "cache_write": "cache writes (short TTL)",
    "cache_write_extended": "cache writes (extended TTL)",
    "output": "output",
}


def _tokens(record: UsageRecord) -> int:
    return sum(
        value or 0
        for value in (
            record.input_tokens,
            record.cache_read_tokens,
            record.cache_write_tokens,
            record.output_tokens,
            record.total_only_tokens,
        )
    )


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _share(part: float, whole: float) -> str:
    return f"{part / whole * 100:5.1f}%" if whole else "    -"


def build(records: Iterable[UsageRecord], rates: dict) -> dict:
    scope: dict = defaultdict(lambda: {"attempts": 0, "sessions": set(), "first": None, "last": None})
    mix: dict = defaultdict(Counter)
    cost_by_part: Counter = Counter()
    by_model: dict = defaultdict(lambda: {"cost": 0.0, "attempts": 0})
    by_project: Counter = Counter()
    by_session: dict = defaultdict(lambda: {"cost": 0.0, "source": None, "project": None})
    unpriced: dict = defaultdict(lambda: {"attempts": 0, "tokens": 0})
    hidden = Counter()

    for record in records:
        s = scope[record.source]
        s["attempts"] += 1
        s["sessions"].add(record.session_id)
        if record.timestamp:
            s["first"] = min(filter(None, (s["first"], record.timestamp)))
            s["last"] = max(filter(None, (s["last"], record.timestamp)))

        m = mix[record.source]
        for field in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens",
                      "reasoning_tokens", "total_only_tokens"):
            m[field] += getattr(record, field) or 0
            if getattr(record, field) is None:
                m[f"{field}_unreported"] += 1

        if record.superseded_attempt:
            hidden["superseded_attempts"] += 1
            hidden["superseded_tokens"] += _tokens(record)

        cost, reason = price(record, rates)
        if cost is None:
            key = (record.source, reason, record.model or "(none)")
            unpriced[key]["attempts"] += 1
            unpriced[key]["tokens"] += _tokens(record)
            continue

        total = sum(cost.values())
        cost_by_part.update(cost)
        model_row = by_model[(record.source, record.model)]
        model_row["cost"] += total
        model_row["attempts"] += 1
        by_project[(record.source, record.project or "(unknown)")] += total
        session_row = by_session[(record.source, record.session_id)]
        session_row["cost"] += total
        session_row["project"] = record.project
        if record.is_subagent:
            hidden["subagent_cost"] += total

    return {
        "scope": scope,
        "mix": mix,
        "cost_by_part": cost_by_part,
        "by_model": by_model,
        "by_project": by_project,
        "by_session": by_session,
        "unpriced": unpriced,
        "hidden": hidden,
    }


def render(summary: dict, rates: dict, top: int, hide: Callable[[Optional[str]], Optional[str]]) -> str:
    out = []
    say = out.append

    say(f"llm-token-audit report · rates as of {rates['as_of']}")
    say("Costs are API-equivalent at the listed rates: not what a subscription plan charged,")
    say("and not the rates in effect when each request ran.")

    say("\nSCOPE")
    for source, s in sorted(summary["scope"].items()):
        span = f"{(s['first'] or '?')[:10]} to {(s['last'] or '?')[:10]}"
        say(f"  {source:12} {s['attempts']:>9,} attempts  {len(s['sessions']):>6,} sessions  {span}")

    say("\nTOKEN MIX")
    for source, m in sorted(summary["mix"].items()):
        input_side = m["input_tokens"] + m["cache_read_tokens"] + m["cache_write_tokens"]
        say(f"  {source}")
        say(f"    {'uncached input':24} {m['input_tokens']:>18,}  {_share(m['input_tokens'], input_side)} of input side")
        say(f"    {'cache reads':24} {m['cache_read_tokens']:>18,}  {_share(m['cache_read_tokens'], input_side)} of input side")
        writes = "not reported" if m["cache_write_tokens_unreported"] else f"{m['cache_write_tokens']:,}"
        say(f"    {'cache writes':24} {writes:>18}")
        say(f"    {'output':24} {m['output_tokens']:>18,}")
        say(f"    {'reasoning (in output)':24} {m['reasoning_tokens']:>18,}")
        if m["total_only_tokens"]:
            say(f"    {'total only, no breakdown':24} {m['total_only_tokens']:>18,}")

    parts = summary["cost_by_part"]
    total = sum(parts.values())
    say(f"\nAPI-EQUIVALENT COST (priced attempts): {_money(total)}")
    say("  by token type")
    for part in PARTS:
        if parts[part]:
            say(f"    {PART_LABELS[part]:28} {_money(parts[part]):>14}  {_share(parts[part], total)}")

    say("  by model")
    rows = sorted(summary["by_model"].items(), key=lambda item: -item[1]["cost"])
    for (source, model), row in rows:
        say(f"    {model:28} {_money(row['cost']):>14}  {_share(row['cost'], total)}  {row['attempts']:>8,} attempts  ({source})")

    say(f"  top {top} projects")
    for (source, project), cost in summary["by_project"].most_common(top):
        say(f"    {hide(project):28} {_money(cost):>14}  {_share(cost, total)}  ({source})")

    say(f"  top {top} sessions")
    sessions = sorted(summary["by_session"].items(), key=lambda item: -item[1]["cost"])[:top]
    for (source, session), row in sessions:
        say(f"    {hide(session):38} {_money(row['cost']):>14}  {hide(row['project']) or ''}  ({source})")

    hidden = summary["hidden"]
    say("\nHIDDEN COSTS")
    say(f"  subagent attempts             {_money(hidden['subagent_cost']):>14}  {_share(hidden['subagent_cost'], total)}")
    say(f"  attempts replaced by fallback {hidden['superseded_attempts']:>14,}  ({hidden['superseded_tokens']:,} tokens, model not logged)")

    if summary["unpriced"]:
        say("\nNOT PRICED")
        rows = sorted(summary["unpriced"].items(), key=lambda item: -item[1]["tokens"])
        for (source, reason, model), row in rows:
            say(f"  {model:28} {row['attempts']:>8,} attempts {row['tokens']:>16,} tokens  {reason} ({source})")

    notes = []
    if any(m["cache_write_tokens_unreported"] for m in summary["mix"].values()):
        notes.append("Codex logs do not report cache writes, so Codex costs exclude any cache-write charges.")
    if notes:
        say("\nNOTES")
        for note in notes:
            say(f"  {note}")
    return "\n".join(out)
