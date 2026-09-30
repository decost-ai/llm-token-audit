from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

from .record import UsageRecord

SOURCE = "codex"

COMPONENTS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")


def default_dirs() -> list[Path]:
    base = os.environ.get("CODEX_HOME")
    return [Path(base) / "sessions"] if base else [Path.home() / ".codex" / "sessions"]


def _counts(usage: dict) -> tuple[int, ...]:
    return tuple(int(usage.get(key) or 0) for key in COMPONENTS)


def read(dirs: Iterable[Path], stats: Counter) -> Iterator[UsageRecord]:
    for root in dirs:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            stats["files"] += 1
            yield from _read_file(path, stats)


def _read_file(path: Path, stats: Counter) -> Iterator[UsageRecord]:
    session_id = path.stem
    project = None
    subagent = None
    model = None
    previous: tuple[int, ...] | None = None
    earlier_segments = 0
    emitted_total = 0
    event_index = 0

    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                stats["unparsed_lines"] += 1
                continue
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            kind = entry.get("type")

            if kind == "session_meta" and project is None:
                session_id = payload.get("id") or session_id
                cwd = payload.get("cwd")
                project = Path(cwd).name if isinstance(cwd, str) and cwd else None
                subagent = bool(payload.get("parent_thread_id"))
                continue
            if kind == "turn_context":
                model = payload.get("model") or model
                continue
            if kind != "event_msg" or payload.get("type") != "token_count":
                continue

            info = payload.get("info")
            if not info:
                stats["events_without_usage"] += 1
                continue
            total = _counts(info.get("total_token_usage") or {})
            # Codex re-emits an unchanged cumulative total; counting its per-turn usage again
            # would double-count that turn.
            if total == previous:
                stats["repeated_events_skipped"] += 1
                continue
            if previous is not None and any(now < before for now, before in zip(total, previous)):
                # The cumulative counter restarted; bank the finished segment for reconciliation.
                stats["counter_resets"] += 1
                earlier_segments += previous[-1]
            previous = total
            event_index += 1

            new_input, cached, output, reasoning, turn_total = _counts(info.get("last_token_usage") or {})
            emitted_total += turn_total
            record = dict(
                source=SOURCE,
                session_id=session_id,
                request_id=f"{session_id}:{event_index}",
                attempt=0,
                timestamp=entry.get("timestamp"),
                model=model,
                speed=None,
                project=project,
                is_subagent=subagent,
                superseded_attempt=False,
                # Codex never reports cache writes (the field is always 0), so they are unmeasured.
                cache_write_tokens=None,
                cache_write_extended_ttl_tokens=None,
            )
            if new_input == cached == output == reasoning == 0 and turn_total > 0:
                stats["total_only_events"] += 1
                yield UsageRecord(**record, input_tokens=None, cache_read_tokens=None, output_tokens=None,
                                  reasoning_tokens=None, total_only_tokens=turn_total)
                continue
            # `cached_input_tokens` is a subset of `input_tokens`, not a sibling of it.
            yield UsageRecord(**record, input_tokens=new_input - cached, cache_read_tokens=cached,
                              output_tokens=output, reasoning_tokens=reasoning, total_only_tokens=None)

    if previous is None:
        return
    stats["sessions_with_usage"] += 1
    if emitted_total == earlier_segments + previous[-1]:
        stats["sessions_reconciled"] += 1
    else:
        stats["sessions_not_reconciled"] += 1
