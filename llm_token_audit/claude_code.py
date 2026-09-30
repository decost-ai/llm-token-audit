from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

from .record import UsageRecord

SOURCE = "claude-code"


def default_dirs() -> list[Path]:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return [Path(base) / "projects"] if base else [Path.home() / ".claude" / "projects"]


def _project(cwd: object) -> str | None:
    return Path(cwd).name or None if isinstance(cwd, str) and cwd else None


def read(dirs: Iterable[Path], stats: Counter) -> Iterator[UsageRecord]:
    # Claude Code writes one line per streamed content block, repeating the message's usage on
    # each, and copies earlier responses into the new file when a session is resumed. Keying on
    # the API message ID across every file counts each response once.
    responses: dict[str, dict] = {}

    for root in dirs:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            stats["files"] += 1
            subagent_file = "subagents" in path.parts
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        stats["unparsed_lines"] += 1
                        continue
                    if entry.get("type") != "assistant":
                        continue
                    message = entry.get("message")
                    if not isinstance(message, dict):
                        continue
                    usage = message.get("usage")
                    message_id = message.get("id")
                    if not usage or not message_id:
                        continue
                    stats["usage_lines"] += 1
                    if message.get("model") == "<synthetic>":
                        stats["synthetic_lines_skipped"] += 1
                        continue

                    subagent = subagent_file or bool(entry.get("isSidechain"))
                    timestamp = entry.get("timestamp")
                    seen = responses.get(message_id)
                    if seen is None:
                        responses[message_id] = {
                            "usage": usage,
                            "model": message.get("model"),
                            "session": entry.get("sessionId") or path.stem,
                            "project": _project(entry.get("cwd")),
                            "timestamp": timestamp,
                            "subagent": subagent,
                            "files": {path},
                        }
                        continue

                    stats["repeat_lines"] += 1
                    seen["files"].add(path)
                    seen["subagent"] = seen["subagent"] or subagent
                    # Input and cache counts are constant across a response's lines; output grows.
                    if (usage.get("output_tokens") or 0) >= (seen["usage"].get("output_tokens") or 0):
                        seen["usage"] = usage
                    if timestamp and (seen["timestamp"] is None or timestamp < seen["timestamp"]):
                        seen["timestamp"] = timestamp
                        seen["session"] = entry.get("sessionId") or path.stem
                        seen["project"] = _project(entry.get("cwd"))

    stats["responses"] = len(responses)
    stats["responses_in_multiple_files"] = sum(1 for r in responses.values() if len(r["files"]) > 1)

    for message_id, response in responses.items():
        usage = response["usage"]
        iterations = usage.get("iterations") or []
        # A model fallback logs the replaced attempt only inside `iterations`; the top-level
        # usage covers the final attempt alone.
        parts = iterations if len(iterations) > 1 else [usage]
        details = usage.get("output_tokens_details") or {}
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            if not final:
                stats["superseded_attempts"] += 1
            cache_creation = part.get("cache_creation") or {}
            yield UsageRecord(
                source=SOURCE,
                session_id=response["session"],
                request_id=message_id,
                attempt=index,
                timestamp=response["timestamp"],
                model=response["model"] if final else None,
                speed=usage.get("speed"),
                project=response["project"],
                is_subagent=response["subagent"],
                superseded_attempt=not final,
                input_tokens=part.get("input_tokens"),
                cache_read_tokens=part.get("cache_read_input_tokens"),
                cache_write_tokens=part.get("cache_creation_input_tokens"),
                cache_write_extended_ttl_tokens=cache_creation.get("ephemeral_1h_input_tokens") if cache_creation else None,
                output_tokens=part.get("output_tokens"),
                reasoning_tokens=details.get("thinking_tokens") if len(parts) == 1 else None,
                total_only_tokens=None,
            )
