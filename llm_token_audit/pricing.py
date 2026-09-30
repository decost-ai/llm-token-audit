from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

from .record import UsageRecord

RATES_DIR = Path(__file__).parent / "rates"

PARTS = ("input", "cache_read", "cache_write", "cache_write_extended", "output")


def default_rates_path() -> Path:
    return sorted(RATES_DIR.glob("*.json"))[-1]


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def price(record: UsageRecord, rates: dict) -> Tuple[Optional[dict], Optional[str]]:
    """Return USD cost per token type, or None and the reason the attempt cannot be priced."""
    if record.total_only_tokens is not None:
        return None, "log gives no token breakdown"
    if record.model is None:
        return None, "model not logged"
    entry = rates["models"].get(rates.get("aliases", {}).get(record.model, record.model))
    if entry is None:
        return None, "no rate for model"
    if record.speed not in (None, "standard"):
        entry = entry.get(record.speed)
        if entry is None:
            return None, f"no {record.speed}-speed rate"

    prompt = (record.input_tokens or 0) + (record.cache_read_tokens or 0) + (record.cache_write_tokens or 0)
    limit = entry.get("short_context_max_input_tokens")
    if limit is not None and prompt > limit:
        entry = entry.get("long_context")
        if entry is None:
            return None, "no long-context rate"

    extended = record.cache_write_extended_ttl_tokens or 0
    tokens = {
        "input": record.input_tokens or 0,
        "cache_read": record.cache_read_tokens or 0,
        "cache_write": (record.cache_write_tokens or 0) - extended,
        "cache_write_extended": extended,
        "output": record.output_tokens or 0,
    }
    cost = {}
    for part, count in tokens.items():
        if not count:
            cost[part] = 0.0
            continue
        rate = entry.get(part)
        if rate is None:
            return None, f"no {part.replace('_', ' ')} rate"
        cost[part] = count * rate / 1_000_000
    return cost, None
