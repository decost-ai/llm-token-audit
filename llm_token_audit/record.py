from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class UsageRecord:
    """One model attempt. None means the log did not report the value; it never means zero."""

    source: str
    session_id: str
    request_id: str
    attempt: int
    timestamp: Optional[str]
    model: Optional[str]
    # Provider service speed when logged ("standard", or a premium mode such as "fast").
    speed: Optional[str]
    project: Optional[str]
    is_subagent: Optional[bool]
    superseded_attempt: bool
    # Uncached input only. Cache reads and writes are separate columns, so the three never overlap.
    input_tokens: Optional[int]
    cache_read_tokens: Optional[int]
    cache_write_tokens: Optional[int]
    # Subset of cache_write_tokens written at a longer-lived (and pricier) cache tier.
    cache_write_extended_ttl_tokens: Optional[int]
    # Includes reasoning tokens; reasoning_tokens is a subset of this column.
    output_tokens: Optional[int]
    reasoning_tokens: Optional[int]
    # Set only when a log reports a total with no input/output breakdown.
    total_only_tokens: Optional[int]


FIELDS = [f.name for f in fields(UsageRecord)]

TOKEN_FIELDS = [
    "input_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cache_write_extended_ttl_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_only_tokens",
]
