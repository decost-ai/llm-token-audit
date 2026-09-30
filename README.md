# llm-token-audit

Find where your AI agent's tokens go. `llm-token-audit` reads Claude Code and Codex session
logs on your machine and turns them into one row per model attempt, with uncached input, cache
reads, cache writes, output, and reasoning tokens in separate columns. Only counts leave your
logs.

## Why parse the logs carefully

Agent session logs look simple and are easy to miscount:

- **Claude Code repeats usage on every streamed line.** Summing each line overstated total
  tokens by 124% on the logs we measured.
- **Codex reports cached input inside input.** Treating the two as separate counts can turn a
  96.8% cache rate into 49.2%.
- **Model fallbacks hide an attempt.** When Claude Code falls back to another model, the
  replaced attempt appears only in a nested field that top-level usage leaves out.

[docs/log-formats.md](docs/log-formats.md) documents each rule with the measurements behind it.

## Quick start

Requires Python 3.9 or later. No dependencies.

```sh
git clone https://github.com/decost-ai/llm-token-audit
cd llm-token-audit

# Parse statistics, reconciliation results, and token totals
python3 -m llm_token_audit check

# One CSV row per model attempt
python3 -m llm_token_audit normalize -o usage.csv
```

The defaults read `~/.claude/projects` and `~/.codex/sessions`, or the directories set by
`CLAUDE_CONFIG_DIR` and `CODEX_HOME`. Point at other locations with `--claude-dir` and
`--codex-dir`, each repeatable. Limit to one tool with `--source claude-code` or
`--source codex`.

## Supported logs

| Source | Verified by |
| --- | --- |
| Claude Code | Exact match with an independent recount keyed on request ID |
| Codex CLI | Per-turn rows sum to the log's own cumulative total in every session |

`check` reruns the Codex reconciliation on your logs and counts any session that fails.

## Output columns

| Column | Meaning |
| --- | --- |
| `source`, `session_id`, `request_id`, `attempt` | Where the row came from; `attempt` numbers fallback attempts within one response |
| `timestamp`, `model`, `project` | When, which model, and the working directory's folder name |
| `is_subagent` | Whether a subagent made the call |
| `superseded_attempt` | An attempt replaced by a model fallback |
| `input_tokens` | Uncached input only |
| `cache_read_tokens`, `cache_write_tokens` | Cache reads and writes, separate from input |
| `cache_write_extended_ttl_tokens` | Part of `cache_write_tokens` written to a longer-lived cache tier |
| `output_tokens` | All output, including reasoning |
| `reasoning_tokens` | Part of `output_tokens` |
| `total_only_tokens` | A total the log reported without a breakdown |

An empty cell means the log did not report that value. It never means zero.

## Privacy

The tool reads logs locally and makes no network requests. Output contains counts, IDs, model
names, timestamps, and project folder names, never prompt, response, or file content.
`normalize --redact` replaces session IDs, request IDs, and project names with short hashes
before you share a file.

## Roadmap

- **Audit report:** spend by session and model, stable context against new input, cache hit
  rate, and repeated large tool outputs, priced with a rates file you supply.
- **More adapters:** each one listed only after it passes a verification like the ones above.

## License

MIT. Built by [decost.ai](https://decost.ai), which publishes free guides on production AI
costs.
